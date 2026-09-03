"""Atomic Catalog Manifest publication, activation and audit primitives."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session

from .domain import CatalogCompositionError, compose_packs, manifest_content_hash, validate_manifest_for_activation


class CatalogManifestError(ValueError):
    """A Manifest cannot be signed, activated or atomically published."""


_ENTRY_FIELDS = {
    "kind",
    "stable_id",
    "version",
    "content_hash",
    "status",
    "data_domain_id",
    "semantic_schema_version",
    "source_pack_id",
}


class CatalogManifestService:
    """Publish an immutable Manifest revision and move its active pointer atomically."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def build_from_packs(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        manifest_id: str,
        manifest_revision: int,
        packs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Generate a Manifest reference snapshot from published Packs.

        This method deliberately reads only Catalog pins and Profile metadata.
        It never accepts semantic object payloads and never replaces a source
        system as an editing surface.
        """
        if not packs:
            raise CatalogManifestError("at least one published Pack is required")
        if manifest_revision < 1:
            raise CatalogManifestError("Manifest revision must be positive")
        async with tenant_session(self._engine, tenant_id) as session:
            profile = (
                (
                    await session.execute(
                        text(
                            "SELECT catalog_profile_id,industry_scope,enterprise_scope,data_domain_id,roles,status "
                            "FROM catalog_profiles WHERE tenant_id=:tenant AND profile_id=:profile "
                            "AND deleted_at IS NULL AND status IN ('draft','active')"
                        ),
                        {"tenant": tenant_id, "profile": profile_id},
                    )
                )
                .mappings()
                .first()
            )
            if profile is None:
                raise CatalogManifestError("Catalog Profile is not found")
            pack_rows: list[dict[str, Any]] = []
            for requested in packs:
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT pack_id,version,layer,name,content_hash,status FROM catalog_packs "
                                "WHERE tenant_id=:tenant AND pack_id=:pack_id AND version=:version "
                                "AND deleted_at IS NULL"
                            ),
                            {
                                "tenant": tenant_id,
                                "pack_id": requested.get("pack_id"),
                                "version": requested.get("version"),
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None or row["status"] != "published" or not row["content_hash"]:
                    raise CatalogManifestError("Manifest can only be generated from published Packs")
                entry_rows = (
                    await session.execute(
                        text(
                            "SELECT e.kind,e.stable_id,e.version,e.content_hash,r.status,r.data_domain_id,"
                            "r.semantic_schema_version FROM catalog_pack_entries e JOIN catalog_refs r ON "
                            "r.tenant_id=e.tenant_id AND r.kind=e.kind AND r.stable_id=e.stable_id "
                            "AND r.version=e.version WHERE e.tenant_id=:tenant AND e.pack_id=:pack_id "
                            "AND e.pack_version=:version ORDER BY e.kind,e.stable_id,e.version"
                        ),
                        {
                            "tenant": tenant_id,
                            "pack_id": row["pack_id"],
                            "version": row["version"],
                        },
                    )
                ).mappings()
                pack_rows.append(
                    {
                        **dict(row),
                        "entries": [dict(entry) for entry in entry_rows],
                    }
                )
            try:
                entries, pack_lock = compose_packs(pack_rows)
            except CatalogCompositionError as error:
                raise CatalogManifestError(str(error)) from error
            domain = profile["data_domain_id"]
            if any(entry.get("data_domain_id") != domain for entry in entries):
                raise CatalogManifestError("Pack entries do not match the Profile data domain")
            owners = profile["roles"] or []
            if not owners:
                raise CatalogManifestError("Catalog Profile has no configured owners")
            manifest = {
                "manifest_schema_version": "catalog-manifest/v1",
                "manifest_id": manifest_id,
                "manifest_revision": manifest_revision,
                "scope": {
                    "industry_scope": profile["industry_scope"],
                    "enterprise_scope": profile["enterprise_scope"],
                    "tenant_id": tenant_id,
                    "data_domains": [domain],
                    "global_enabled": False,
                },
                "pack_lock": pack_lock,
                "entries": entries,
                "owners": owners,
                "resolver_adapter": {
                    "identity": "earp.catalog.resolver.api/v1",
                    "contract_version": "catalog-resolver/v1.0",
                },
            }
            manifest["manifest_hash"] = manifest_content_hash(manifest)
            return manifest

    async def publish_and_activate(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        manifest: dict[str, Any],
        attestation: dict[str, Any],
        expected_active_revision: int | None = None,
    ) -> str:
        """Validate and atomically persist a signed Manifest revision.

        The caller supplies only a prepared reference snapshot and signed
        envelope. Semantic source objects are never edited or copied here.
        """
        try:
            validate_manifest_for_activation(manifest, attestation)
        except CatalogCompositionError as error:
            raise CatalogManifestError(str(error)) from error
        if manifest.get("profile_id", profile_id) != profile_id:
            raise CatalogManifestError("Manifest profile does not match the activation request")
        if not idempotency_key.strip():
            raise CatalogManifestError("idempotency_key is required")
        manifest_id = str(manifest.get("manifest_id", ""))
        revision = manifest.get("manifest_revision")
        if not manifest_id or not isinstance(revision, int) or revision < 1:
            raise CatalogManifestError("Manifest identity and positive revision are required")
        signoff = {
            key: attestation.get(key)
            for key in (
                "signoff_tag",
                "change_order",
                "signed_at",
                "effective_from",
                "effective_until",
                "signers",
            )
        }

        async with tenant_session(self._engine, tenant_id) as session:
            prior = await session.execute(
                text("SELECT resource_id FROM catalog_outbox WHERE tenant_id=:tenant AND idempotency_key=:key"),
                {"tenant": tenant_id, "key": f"{idempotency_key}:cache_invalidate"},
            )
            previous = prior.scalar_one_or_none()
            if previous is not None:
                return manifest["manifest_hash"]

            profile = await session.execute(
                text(
                    "SELECT data_domain_id FROM catalog_profiles WHERE tenant_id=:tenant "
                    "AND profile_id=:profile AND deleted_at IS NULL AND status IN ('draft','active')"
                ),
                {"tenant": tenant_id, "profile": profile_id},
            )
            profile_domain = profile.scalar_one_or_none()
            if profile_domain is None:
                raise CatalogManifestError("Catalog Profile is not found")
            domains = manifest.get("scope", {}).get("data_domains", [])
            if domains != [profile_domain]:
                raise CatalogManifestError("Manifest scope does not match the Profile data domain")

            await self._verify_pack_lock(session, tenant_id, manifest.get("pack_lock", []))
            entries = list(manifest.get("entries", []))
            if any(entry.get("status") == "suspected_missing" for entry in entries):
                raise CatalogManifestError("suspected_missing entries cannot enter a new manifest")
            await self._verify_entries(session, tenant_id, entries, profile_domain)

            active = await session.execute(
                text(
                    "SELECT manifest_revision FROM catalog_active_manifests "
                    "WHERE tenant_id=:tenant AND profile_id=:profile FOR UPDATE"
                ),
                {"tenant": tenant_id, "profile": profile_id},
            )
            active_revision = active.scalar_one_or_none()
            if active_revision != expected_active_revision:
                if not (active_revision is None and expected_active_revision is None):
                    raise CatalogManifestError("active Manifest CAS precondition failed")

            await session.execute(
                text(
                    "INSERT INTO catalog_manifests "
                    "(tenant_id,manifest_id,manifest_revision,profile_id,manifest_hash,envelope_hash,"
                    "manifest_schema_version,canonicalizer_version,resolver_identity,status,scope,pack_lock,"
                    "owners,signoff) VALUES (:tenant,:manifest_id,:revision,:profile,:manifest_hash,:envelope_hash,"
                    ":manifest_schema,:canonicalizer,:resolver,'active',CAST(:scope AS jsonb),"
                    "CAST(:pack_lock AS jsonb),"
                    ":owners,CAST(:signoff AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "manifest_id": manifest_id,
                    "revision": revision,
                    "profile": profile_id,
                    "manifest_hash": manifest["manifest_hash"],
                    "envelope_hash": attestation["envelope_hash"],
                    "manifest_schema": manifest["manifest_schema_version"],
                    "canonicalizer": "sha256/canonical-json/v1",
                    "resolver": manifest["resolver_adapter"]["identity"],
                    "scope": json.dumps(manifest["scope"]),
                    "pack_lock": json.dumps(manifest["pack_lock"]),
                    "owners": json.dumps(manifest["owners"]),
                    "signoff": json.dumps(signoff),
                },
            )
            for entry in entries:
                projection = {key: value for key, value in entry.items() if key not in _ENTRY_FIELDS}
                await session.execute(
                    text(
                        "INSERT INTO catalog_manifest_entries "
                        "(tenant_id,manifest_id,manifest_revision,kind,stable_id,version,content_hash,status,"
                        "data_domain_id,semantic_schema_version,source_pack_id,projection) VALUES "
                        "(:tenant,:manifest_id,:revision,:kind,:stable_id,:version,:content_hash,:status,"
                        ":domain,:schema,:source_pack,CAST(:projection AS jsonb))"
                    ),
                    {
                        "tenant": tenant_id,
                        "manifest_id": manifest_id,
                        "revision": revision,
                        "kind": entry["kind"],
                        "stable_id": entry["stable_id"],
                        "version": entry["version"],
                        "content_hash": entry["content_hash"],
                        "status": entry["status"],
                        "domain": entry["data_domain_id"],
                        "schema": entry["semantic_schema_version"],
                        "source_pack": entry.get("source_pack_id"),
                        "projection": json.dumps(projection),
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO catalog_signoffs "
                    "(tenant_id,signoff_id,manifest_id,manifest_revision,signoff_tag,change_order,attestation,"
                    "envelope_hash,signed_at,effective_from,effective_until,signers) VALUES "
                    "(:tenant,:signoff_id,:manifest_id,:revision,:signoff_tag,:change_order,"
                    "CAST(:attestation AS jsonb),"
                    ":envelope_hash,:signed_at,:effective_from,:effective_until,CAST(:signers AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "signoff_id": f"csig-{uuid.uuid4().hex[:12]}",
                    "manifest_id": manifest_id,
                    "revision": revision,
                    "signoff_tag": attestation["signoff_tag"],
                    "change_order": attestation["change_order"],
                    "attestation": json.dumps(attestation),
                    "envelope_hash": attestation["envelope_hash"],
                    "signed_at": attestation["signed_at"],
                    "effective_from": attestation["effective_from"],
                    "effective_until": attestation.get("effective_until"),
                    "signers": json.dumps(attestation["signers"]),
                },
            )
            if active_revision is None:
                await session.execute(
                    text(
                        "INSERT INTO catalog_active_manifests "
                        "(tenant_id,profile_id,manifest_id,manifest_revision,active_revision_generation) "
                        "VALUES (:tenant,:profile,:manifest_id,:revision,1)"
                    ),
                    {
                        "tenant": tenant_id,
                        "profile": profile_id,
                        "manifest_id": manifest_id,
                        "revision": revision,
                    },
                )
            else:
                await session.execute(
                    text(
                        "UPDATE catalog_active_manifests SET manifest_id=:manifest_id,manifest_revision=:revision,"
                        "active_revision_generation=active_revision_generation+1,updated_at=now() "
                        "WHERE tenant_id=:tenant AND profile_id=:profile AND manifest_revision=:expected"
                    ),
                    {
                        "tenant": tenant_id,
                        "profile": profile_id,
                        "manifest_id": manifest_id,
                        "revision": revision,
                        "expected": expected_active_revision,
                    },
                )
            for event_type in ("cache_invalidate", "git_archive"):
                await session.execute(
                    text(
                        "INSERT INTO catalog_outbox "
                        "(tenant_id,event_id,idempotency_key,event_type,resource_type,resource_id,payload) VALUES "
                        "(:tenant,:event_id,:key,:event_type,'catalog_manifest',:resource_id,CAST(:payload AS jsonb))"
                    ),
                    {
                        "tenant": tenant_id,
                        "event_id": f"cout-{uuid.uuid4().hex[:12]}",
                        "key": f"{idempotency_key}:{event_type}",
                        "event_type": event_type,
                        "resource_id": f"{manifest_id}@{revision}",
                        "payload": json.dumps(
                            {
                                "profile_id": profile_id,
                                "manifest_id": manifest_id,
                                "manifest_revision": revision,
                                "manifest_hash": manifest["manifest_hash"],
                            }
                        ),
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO catalog_audit_logs "
                    "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,after_hash,status,"
                    "correlation_id,detail) VALUES "
                    "(:tenant,:audit_id,:actor,'catalog_manifest',:resource_id,'publish_activate',:after_hash,"
                    "'succeeded',:correlation_id,CAST(:detail AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "audit_id": f"caud-{uuid.uuid4().hex[:12]}",
                    "actor": actor_id,
                    "resource_id": f"{manifest_id}@{revision}",
                    "after_hash": manifest["manifest_hash"],
                    "correlation_id": correlation_id,
                    "detail": json.dumps({"profile_id": profile_id, "envelope_hash": attestation["envelope_hash"]}),
                },
            )
            return manifest["manifest_hash"]

    async def revoke_active(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        """Revoke the active pointer without mutating any historical revision."""
        if not reason.strip():
            raise CatalogManifestError("Manifest revoke reason is required")
        cache_key = f"{idempotency_key}:cache_invalidate"
        async with tenant_session(self._engine, tenant_id) as session:
            replay = (
                await session.execute(
                    text("SELECT resource_id FROM catalog_outbox WHERE tenant_id=:tenant AND idempotency_key=:key"),
                    {"tenant": tenant_id, "key": cache_key},
                )
            ).scalar_one_or_none()
            if replay is not None:
                return {"profile_id": profile_id, "manifest_revision": None, "status": "revoked", "replayed": True}
            active = (
                (
                    await session.execute(
                        text(
                            "SELECT manifest_id,manifest_revision FROM catalog_active_manifests "
                            "WHERE tenant_id=:tenant AND profile_id=:profile AND manifest_id IS NOT NULL FOR UPDATE"
                        ),
                        {"tenant": tenant_id, "profile": profile_id},
                    )
                )
                .mappings()
                .first()
            )
            if active is None:
                raise CatalogManifestError("Profile has no active Manifest")
            resource_id = f"{active['manifest_id']}@{active['manifest_revision']}"
            await session.execute(
                text(
                    "UPDATE catalog_manifests SET status='revoked',revoked_at=now() "
                    "WHERE tenant_id=:tenant AND manifest_id=:manifest AND manifest_revision=:revision"
                ),
                {
                    "tenant": tenant_id,
                    "manifest": active["manifest_id"],
                    "revision": active["manifest_revision"],
                },
            )
            await session.execute(
                text(
                    "UPDATE catalog_active_manifests SET manifest_id=NULL,manifest_revision=NULL,"
                    "active_revision_generation=active_revision_generation+1,updated_at=now() "
                    "WHERE tenant_id=:tenant AND profile_id=:profile"
                ),
                {"tenant": tenant_id, "profile": profile_id},
            )
            await session.execute(
                text(
                    "INSERT INTO catalog_outbox "
                    "(tenant_id,event_id,idempotency_key,event_type,resource_type,resource_id,payload) "
                    "VALUES (:tenant,:event,:key,'cache_invalidate','catalog_manifest',:resource,"
                    "CAST(:payload AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "event": f"cout-{uuid.uuid4().hex[:12]}",
                    "key": cache_key,
                    "resource": resource_id,
                    "payload": json.dumps({"profile_id": profile_id, "reason": reason}),
                },
            )
            await session.execute(
                text(
                    "INSERT INTO catalog_audit_logs "
                    "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,status,reason,"
                    "correlation_id,detail) VALUES (:tenant,:audit,:actor,'catalog_manifest',:resource,"
                    "'revoke','succeeded',:reason,:correlation,CAST(:detail AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "audit": f"caud-{uuid.uuid4().hex[:12]}",
                    "actor": actor_id,
                    "resource": resource_id,
                    "reason": reason,
                    "correlation": correlation_id,
                    "detail": json.dumps({"profile_id": profile_id}),
                },
            )
            return {
                "profile_id": profile_id,
                "manifest_id": active["manifest_id"],
                "manifest_revision": active["manifest_revision"],
                "status": "revoked",
                "replayed": False,
            }

    async def rollback(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        target_revision: int,
        new_manifest_id: str,
        new_revision: int,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        attestation: dict[str, Any],
    ) -> str:
        """Re-publish a historical snapshot as a newly signed revision."""
        async with tenant_session(self._engine, tenant_id) as session:
            active_row = (
                await session.execute(
                    text(
                        "SELECT manifest_revision FROM catalog_active_manifests "
                        "WHERE tenant_id=:tenant AND profile_id=:profile AND manifest_id IS NOT NULL"
                    ),
                    {"tenant": tenant_id, "profile": profile_id},
                )
            ).scalar_one_or_none()
            if active_row is None or new_revision <= int(active_row):
                raise CatalogManifestError("Rollback must create a revision newer than the active Manifest")
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM catalog_manifests WHERE tenant_id=:tenant AND profile_id=:profile "
                            "AND manifest_revision=:revision"
                        ),
                        {"tenant": tenant_id, "profile": profile_id, "revision": target_revision},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise CatalogManifestError("Rollback target Manifest revision is not found")
            entries = (
                (
                    await session.execute(
                        text(
                            "SELECT kind,stable_id,version,content_hash,status,data_domain_id,"
                            "semantic_schema_version,source_pack_id,projection FROM catalog_manifest_entries "
                            "WHERE tenant_id=:tenant AND manifest_id=:manifest AND manifest_revision=:revision"
                        ),
                        {
                            "tenant": tenant_id,
                            "manifest": row["manifest_id"],
                            "revision": target_revision,
                        },
                    )
                )
                .mappings()
                .all()
            )
            manifest_entries = []
            for entry in entries:
                item = dict(entry["projection"] or {})
                item.update({key: entry[key] for key in entry.keys() if key != "projection"})
                manifest_entries.append(item)
            manifest = {
                "manifest_schema_version": row["manifest_schema_version"],
                "manifest_id": new_manifest_id,
                "manifest_revision": new_revision,
                "scope": row["scope"],
                "pack_lock": row["pack_lock"],
                "entries": manifest_entries,
                "owners": row["owners"],
                "resolver_adapter": {"identity": row["resolver_identity"], "contract_version": "catalog-resolver/v1.0"},
            }
            manifest["manifest_hash"] = manifest_content_hash(manifest)
            if attestation.get("manifest_hash") != manifest["manifest_hash"]:
                raise CatalogManifestError("Rollback attestation must bind the new Manifest hash")
        return await self.publish_and_activate(
            tenant_id=tenant_id,
            profile_id=profile_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            manifest=manifest,
            attestation=attestation,
            expected_active_revision=int(active_row),
        )

    async def _verify_pack_lock(self, session: Any, tenant_id: str, pack_lock: list[dict[str, Any]]) -> None:
        for locked in pack_lock:
            row = await session.execute(
                text(
                    "SELECT content_hash,status FROM catalog_packs WHERE tenant_id=:tenant AND pack_id=:pack_id "
                    "AND version=:version"
                ),
                {
                    "tenant": tenant_id,
                    "pack_id": locked["pack_id"],
                    "version": locked["version"],
                },
            )
            pack = row.mappings().first()
            if pack is None or pack["status"] != "published" or pack["content_hash"] != locked["content_hash"]:
                raise CatalogManifestError("Manifest pack_lock is not backed by the published Pack hash")

    async def _verify_entries(
        self, session: Any, tenant_id: str, entries: list[dict[str, Any]], profile_domain: str
    ) -> None:
        for entry in entries:
            if entry.get("data_domain_id") != profile_domain:
                raise CatalogManifestError("Manifest entry is outside the Profile data domain")
            row = await session.execute(
                text(
                    "SELECT content_hash,status FROM catalog_refs WHERE tenant_id=:tenant AND kind=:kind "
                    "AND stable_id=:stable_id AND version=:version AND deleted_at IS NULL"
                ),
                {
                    "tenant": tenant_id,
                    "kind": entry["kind"],
                    "stable_id": entry["stable_id"],
                    "version": entry["version"],
                },
            )
            ref = row.mappings().first()
            if ref is None or ref["content_hash"] != entry["content_hash"]:
                raise CatalogManifestError("Manifest entry is not backed by the current CatalogRef hash")
            if ref["status"] in {"inactive", "suspected_missing"}:
                raise CatalogManifestError("Manifest cannot contain an unavailable CatalogRef")
