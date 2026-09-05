"""Persist Catalog reference pins after an authoritative-source verification."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.infra.db import tenant_session

from .hashing import CANONICALIZER_VERSION
from .registration import CatalogRegistrationError, verified_source_ref
from .source import SourceAdapter


async def _find_revoke_replay(
    session: AsyncSession, *, tenant_id: str, actor_id: str, idempotency_key: str
) -> dict[str, Any] | None:
    """Return the stored catalog-ref.revoke idempotency record for a key, if any."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT request_hash,response_body FROM idempotency_records WHERE tenant_id=:tenant "
                    "AND actor_id=:actor AND operation='catalog-ref.revoke' AND idempotency_key=:key"
                ),
                {"tenant": tenant_id, "actor": actor_id, "key": idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


class CatalogRefRegistry:
    """Reference registry; it stores pins and provenance, never semantic payloads."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def register(
        self,
        adapter: SourceAdapter,
        *,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        kind: str,
        stable_id: str,
        version: str,
    ) -> dict[str, object]:
        """Verify then persist one immutable source-owned exact reference.

        Repeating a verified registration for the same exact pin is idempotent.
        A source returning different semantics for an existing exact version is
        rejected; Catalog never overwrites an exact pin.
        """
        source = await verified_source_ref(adapter, kind=kind, stable_id=stable_id, version=version)
        source_system = adapter.source_system.strip()
        source_identity = adapter.source_identity(source).strip()
        if not source_system or not source_identity:
            raise CatalogRegistrationError("source adapter did not provide immutable provenance")
        if source.status not in {"active", "deprecated", "inactive", "suspected_missing"}:
            raise CatalogRegistrationError("source adapter returned an unsupported lifecycle status")

        async with tenant_session(self._engine, tenant_id) as session:
            existing = await session.execute(
                text(
                    "SELECT * FROM catalog_refs WHERE tenant_id=:tenant AND kind=:kind "
                    "AND stable_id=:stable_id AND version=:version"
                ),
                {
                    "tenant": tenant_id,
                    "kind": kind,
                    "stable_id": stable_id,
                    "version": version,
                },
            )
            row = existing.mappings().first()
            if row is not None:
                result = dict(row)
                if result["content_hash"] != source.content_hash:
                    raise CatalogRegistrationError("existing exact CatalogRef has a different content hash")
                return result

            ref_id = f"cref-{uuid.uuid4().hex[:12]}"
            inserted = (
                await session.execute(
                    text(
                        "INSERT INTO catalog_refs "
                        "(tenant_id,ref_id,kind,stable_id,version,content_hash,semantic_schema_version,"
                        "canonicalizer_version,source_system,source_identity,data_domain_id,status) "
                        "VALUES (:tenant,:ref_id,:kind,:stable_id,:version,:content_hash,:schema_version,"
                        ":canonicalizer,:source_system,:source_identity,:data_domain_id,:status) "
                        "ON CONFLICT (tenant_id, kind, stable_id, version) DO NOTHING RETURNING ref_id"
                    ),
                    {
                        "tenant": tenant_id,
                        "ref_id": ref_id,
                        "kind": source.kind,
                        "stable_id": source.stable_id,
                        "version": source.version,
                        "content_hash": source.content_hash,
                        "schema_version": source.schema_version,
                        "canonicalizer": CANONICALIZER_VERSION,
                        "source_system": source_system,
                        "source_identity": source_identity,
                        "data_domain_id": source.data_domain_id,
                        "status": source.status,
                    },
                )
            ).scalar_one_or_none()
            if inserted is not None:
                # Only the transaction that actually created the row writes the audit event;
                # a concurrent duplicate resolves to the winner's row below.
                await session.execute(
                    text(
                        "INSERT INTO catalog_audit_logs "
                        "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,after_hash,"
                        "status,correlation_id,detail) VALUES "
                        "(:tenant,:audit_id,:actor,'catalog_ref',:resource_id,'register',:after_hash,"
                        "'succeeded',:correlation_id,CAST(:detail AS jsonb))"
                    ),
                    {
                        "tenant": tenant_id,
                        "audit_id": f"caud-{uuid.uuid4().hex[:12]}",
                        "actor": actor_id,
                        "resource_id": ref_id,
                        "after_hash": source.content_hash,
                        "correlation_id": correlation_id,
                        "detail": json.dumps(
                            {
                                "source_system": source_system,
                                "source_identity": source_identity,
                                "exact_ref": {key: asdict(source)[key] for key in ("kind", "stable_id", "version")},
                            }
                        ),
                    },
                )
            created = await session.execute(
                text(
                    "SELECT * FROM catalog_refs WHERE tenant_id=:tenant AND kind=:kind "
                    "AND stable_id=:stable_id AND version=:version"
                ),
                {"tenant": tenant_id, "kind": kind, "stable_id": stable_id, "version": version},
            )
            result = dict(created.mappings().one())
            if result["content_hash"] != source.content_hash:
                raise CatalogRegistrationError("existing exact CatalogRef has a different content hash")
            return result

    async def refresh_from_source(
        self,
        adapter: SourceAdapter,
        *,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        kind: str,
        stable_id: str,
        version: str,
    ) -> dict[str, object]:
        """Refresh lifecycle/provenance from an exact authoritative source object."""
        source = await verified_source_ref(adapter, kind=kind, stable_id=stable_id, version=version)
        if source.status not in {"active", "deprecated", "inactive", "suspected_missing"}:
            raise CatalogRegistrationError("source adapter returned an unsupported lifecycle status")
        source_identity = adapter.source_identity(source).strip()
        if not source_identity or not adapter.source_system.strip():
            raise CatalogRegistrationError("source adapter did not provide immutable provenance")
        async with tenant_session(self._engine, tenant_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM catalog_refs WHERE tenant_id=:tenant AND kind=:kind "
                            "AND stable_id=:stable_id AND version=:version FOR UPDATE"
                        ),
                        {"tenant": tenant_id, "kind": kind, "stable_id": stable_id, "version": version},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise CatalogRegistrationError("exact CatalogRef is not registered; register it first")
            if row["content_hash"] != source.content_hash:
                raise CatalogRegistrationError("authoritative content hash drifted; status refresh blocked")
            next_status = source.status
            if row["status"] == "inactive" and source.status != "inactive":
                next_status = "inactive"
            if row["status"] != next_status or row["source_identity"] != source_identity:
                await session.execute(
                    text(
                        "UPDATE catalog_refs SET status=:status,source_identity=:identity,updated_at=now() "
                        "WHERE tenant_id=:tenant AND ref_id=:ref_id"
                    ),
                    {
                        "tenant": tenant_id,
                        "ref_id": row["ref_id"],
                        "status": next_status,
                        "identity": source_identity,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO catalog_audit_logs "
                        "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,before_hash,after_hash,"
                        "status,correlation_id,detail) VALUES "
                        "(:tenant,:audit,:actor,'catalog_ref',:resource,'status_refresh',:before,:after,"
                        "'succeeded',:correlation,CAST(:detail AS jsonb))"
                    ),
                    {
                        "tenant": tenant_id,
                        "audit": f"caud-{uuid.uuid4().hex[:12]}",
                        "actor": actor_id,
                        "resource": row["ref_id"],
                        "before": row["content_hash"],
                        "after": source.content_hash,
                        "correlation": correlation_id,
                        "detail": json.dumps(
                            {
                                "before_status": row["status"],
                                "after_status": next_status,
                                "source_identity": source_identity,
                            }
                        ),
                    },
                )
            refreshed = await session.execute(
                text("SELECT * FROM catalog_refs WHERE tenant_id=:tenant AND ref_id=:ref_id"),
                {"tenant": tenant_id, "ref_id": row["ref_id"]},
            )
            return dict(refreshed.mappings().one())

    async def revoke(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        kind: str,
        stable_id: str,
        version: str,
        reason: str,
    ) -> dict[str, object]:
        """Apply an explicit, audited lifecycle revoke after human confirmation."""
        if not idempotency_key.strip() or not reason.strip():
            raise CatalogRegistrationError("revoke reason and idempotency_key are required")
        payload = {"kind": kind, "stable_id": stable_id, "version": version, "reason": reason}
        request_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        async with tenant_session(self._engine, tenant_id) as session:
            replay = await _find_revoke_replay(
                session, tenant_id=tenant_id, actor_id=actor_id, idempotency_key=idempotency_key
            )
            if replay is not None:
                if replay["request_hash"] != request_hash:
                    raise CatalogRegistrationError("Idempotency-Key was reused with a different request")
                return {**replay["response_body"], "replayed": True}
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM catalog_refs WHERE tenant_id=:tenant AND kind=:kind "
                            "AND stable_id=:stable_id AND version=:version AND deleted_at IS NULL FOR UPDATE"
                        ),
                        {"tenant": tenant_id, "kind": kind, "stable_id": stable_id, "version": version},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise CatalogRegistrationError("exact CatalogRef is not registered")
            if row["status"] == "inactive":
                # End state already holds. A concurrent same-key retry answers from the winner's
                # idempotency record; a genuinely new revoke of an already-inactive pin is a
                # conflict instead of a silent duplicate audit event.
                replay = await _find_revoke_replay(
                    session, tenant_id=tenant_id, actor_id=actor_id, idempotency_key=idempotency_key
                )
                if replay is not None:
                    if replay["request_hash"] != request_hash:
                        raise CatalogRegistrationError("Idempotency-Key was reused with a different request")
                    return {**replay["response_body"], "replayed": True}
                raise CatalogRegistrationError("catalog ref is already inactive; nothing to revoke")
            body: dict[str, object] = {
                "ref_id": row["ref_id"],
                "kind": kind,
                "stable_id": stable_id,
                "version": version,
                "status": "inactive",
                "content_hash": row["content_hash"],
            }
            # Claim the idempotency slot before mutating the ref so a rejected concurrent
            # duplicate (same key, different pin) never leaves a partial side effect.
            claimed = (
                await session.execute(
                    text(
                        "INSERT INTO idempotency_records "
                        "(tenant_id,actor_id,operation,idempotency_key,request_hash,response_status,response_body) "
                        "VALUES (:tenant,:actor,'catalog-ref.revoke',:key,:hash,200,CAST(:body AS jsonb)) "
                        "ON CONFLICT (tenant_id, actor_id, operation, idempotency_key) DO NOTHING "
                        "RETURNING idempotency_key"
                    ),
                    {
                        "tenant": tenant_id,
                        "actor": actor_id,
                        "key": idempotency_key,
                        "hash": request_hash,
                        "body": json.dumps(body),
                    },
                )
            ).scalar_one_or_none()
            if claimed is None:
                # A concurrent request with the same Idempotency-Key won the slot.
                replay = await _find_revoke_replay(
                    session, tenant_id=tenant_id, actor_id=actor_id, idempotency_key=idempotency_key
                )
                if replay is None or replay["request_hash"] != request_hash:
                    raise CatalogRegistrationError("Idempotency-Key was reused with a different request")
                return {**replay["response_body"], "replayed": True}
            await session.execute(
                text(
                    "UPDATE catalog_refs SET status='inactive',revoked_at=COALESCE(revoked_at,now()),updated_at=now() "
                    "WHERE tenant_id=:tenant AND ref_id=:ref"
                ),
                {"tenant": tenant_id, "ref": row["ref_id"]},
            )
            await session.execute(
                text(
                    "INSERT INTO catalog_audit_logs "
                    "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,before_hash,after_hash,"
                    "status,reason,correlation_id,detail) VALUES (:tenant,:audit,:actor,'catalog_ref',:resource,"
                    "'revoke',:before,:after,'succeeded',:reason,:correlation,CAST(:detail AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "audit": f"caud-{uuid.uuid4().hex[:12]}",
                    "actor": actor_id,
                    "resource": row["ref_id"],
                    "before": row["content_hash"],
                    "after": row["content_hash"],
                    "reason": reason,
                    "correlation": correlation_id,
                    "detail": json.dumps({"before_status": row["status"], "after_status": "inactive"}),
                },
            )
            return body
