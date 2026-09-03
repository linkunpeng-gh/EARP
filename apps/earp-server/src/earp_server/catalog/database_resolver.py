# ruff: noqa: E501
"""Database-backed Catalog Resolver; no file or fixture fallback exists here."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.causal_model_management.catalog import (
    CatalogResolutionError,
    CatalogValidationContext,
    CatalogValidationResult,
    ResolvedCatalogRef,
)
from earp_server.causal_model_management.schemas import CatalogRef
from earp_server.infra.db import tenant_session

from .domain import validate_manifest_for_activation


class DatabaseCatalogResolver:
    """Resolve only exact pins in the signed, active Profile Manifest."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._cache: dict[tuple[str, str, int, str, str, str], ResolvedCatalogRef] = {}

    async def resolve(
        self,
        tenant_id: str,
        ref: CatalogRef,
        expected_kind: str,
        *,
        at_version: str | None = None,
        context: CatalogValidationContext | None = None,
    ) -> ResolvedCatalogRef:
        if ref.kind != expected_kind:
            raise CatalogResolutionError("CATALOG_REF_KIND_MISMATCH", ref, "CatalogRef kind does not match its use.")
        if at_version is not None and at_version != ref.version:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "CatalogRef version is not exact.")
        profile_id = str((context.location if context else {}).get("profile_id", ""))
        if not profile_id:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "Catalog Profile is not specified.")
        try:
            async with tenant_session(self._engine, tenant_id) as session:
                active = await self._active(session, tenant_id, profile_id)
                if active is None:
                    raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "No active signed Catalog manifest.")
                manifest, attestation = await self._manifest(session, tenant_id, active)
                validate_manifest_for_activation(manifest, attestation)
                row = await self._entry(session, tenant_id, active, ref)
        except CatalogResolutionError:
            raise
        except Exception as error:  # database or signature validation failure is fail-closed
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "Catalog Resolver is unavailable.") from error
        if row is None:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "CatalogRef is absent from the active manifest.")
        if row["status"] != "active":
            raise CatalogResolutionError("CATALOG_REF_INACTIVE", ref, "CatalogRef is not active for new use.")
        if row["current_hash"] != row["content_hash"]:
            raise CatalogResolutionError(
                "CATALOG_REF_NOT_FOUND", ref, "CatalogRef content hash drifted; resolution blocked."
            )
        if context is not None and row["data_domain_id"] != context.data_domain_id:
            raise CatalogResolutionError(
                "CATALOG_REF_DOMAIN_FORBIDDEN", ref, "CatalogRef is outside the allowed data domain."
            )
        cache_key = (
            tenant_id,
            profile_id,
            int(active["active_revision_generation"]),
            ref.kind,
            ref.stable_id,
            ref.version,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        projection = row["projection"] or {}
        resolved = ResolvedCatalogRef(
            kind=row["kind"],
            stable_id=row["stable_id"],
            version=row["version"],
            content_hash=row["content_hash"],
            status=row["status"],
            data_domain_id=row["data_domain_id"],
            semantic_schema_version=row["semantic_schema_version"],
            display_name=projection.get("display_name"),
            input_schema=projection.get("input_schema"),
            output_schema=projection.get("output_schema"),
            compatibility_metadata=projection.get("compatibility_metadata", {}),
        )
        self._cache[cache_key] = resolved
        return resolved

    def invalidate(self, tenant_id: str, profile_id: str) -> None:
        """Drop cached entries for an active pointer after an outbox event."""
        self._cache = {key: value for key, value in self._cache.items() if key[0] != tenant_id or key[1] != profile_id}

    async def validate(
        self, tenant_id: str, refs: list[tuple[CatalogRef, str]], context: CatalogValidationContext
    ) -> CatalogValidationResult:
        resolved: list[ResolvedCatalogRef] = []
        errors: list[CatalogResolutionError] = []
        for ref, expected_kind in refs:
            try:
                resolved.append(await self.resolve(tenant_id, ref, expected_kind, context=context))
            except CatalogResolutionError as error:
                errors.append(error)
        return CatalogValidationResult(tuple(resolved), tuple(errors))

    async def _active(self, session: AsyncSession, tenant_id: str, profile_id: str) -> dict[str, Any] | None:
        row = await session.execute(
            text(
                "SELECT manifest_id,manifest_revision,active_revision_generation "
                "FROM catalog_active_manifests "
                "WHERE tenant_id=:tenant AND profile_id=:profile AND manifest_id IS NOT NULL"
            ),
            {"tenant": tenant_id, "profile": profile_id},
        )
        item = row.mappings().first()
        return dict(item) if item else None

    async def _entry(
        self, session: AsyncSession, tenant_id: str, active: dict[str, Any], ref: CatalogRef
    ) -> dict[str, Any] | None:
        row = await session.execute(
            text(
                "SELECT me.*,cr.content_hash AS current_hash FROM catalog_manifest_entries me "
                "JOIN catalog_refs cr ON cr.tenant_id=me.tenant_id AND cr.kind=me.kind "
                "AND cr.stable_id=me.stable_id AND cr.version=me.version "
                "WHERE me.tenant_id=:tenant AND me.manifest_id=:manifest AND me.manifest_revision=:revision "
                "AND me.kind=:kind AND me.stable_id=:stable_id AND me.version=:version"
            ),
            {
                "tenant": tenant_id,
                "manifest": active["manifest_id"],
                "revision": active["manifest_revision"],
                "kind": ref.kind,
                "stable_id": ref.stable_id,
                "version": ref.version,
            },
        )
        item = row.mappings().first()
        return dict(item) if item else None

    async def _manifest(
        self, session: AsyncSession, tenant_id: str, active: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM catalog_manifests WHERE tenant_id=:tenant AND manifest_id=:manifest "
                        "AND manifest_revision=:revision AND status IN ('active','fully_signed','active_archive_pending')"
                    ),
                    {"tenant": tenant_id, "manifest": active["manifest_id"], "revision": active["manifest_revision"]},
                )
            )
            .mappings()
            .one()
        )
        entries = (
            (
                await session.execute(
                    text(
                        "SELECT kind,stable_id,version,content_hash,status,data_domain_id,semantic_schema_version,source_pack_id,projection "
                        "FROM catalog_manifest_entries WHERE tenant_id=:tenant AND manifest_id=:manifest AND manifest_revision=:revision"
                    ),
                    {"tenant": tenant_id, "manifest": active["manifest_id"], "revision": active["manifest_revision"]},
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
            "manifest_id": row["manifest_id"],
            "manifest_revision": row["manifest_revision"],
            "scope": row["scope"],
            "pack_lock": row["pack_lock"],
            "entries": manifest_entries,
            "owners": row["owners"],
            "resolver_adapter": {"identity": row["resolver_identity"], "contract_version": "catalog-resolver/v1.0"},
            "manifest_hash": row["manifest_hash"],
        }
        attestation = {
            **(row["signoff"] or {}),
            "manifest_hash": row["manifest_hash"],
            "envelope_hash": row["envelope_hash"],
        }
        return manifest, attestation
