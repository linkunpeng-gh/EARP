"""Phase 1 pull synchronization for authoritative Catalog source adapters."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session

from .hashing import CatalogCanonicalizationError, content_hash
from .source import SourceAdapter, SourceObject


class CatalogSyncError(ValueError):
    """A source pull cannot be safely committed to the Catalog index."""


@dataclass(frozen=True)
class SyncResult:
    sync_run_id: str
    status: str
    seen_count: int
    updated_count: int
    error_code: str | None = None


def _verify_source(adapter: SourceAdapter, source: SourceObject) -> str:
    try:
        digest = content_hash(source.canonical_input, schema_version=source.schema_version)
    except CatalogCanonicalizationError as error:
        raise CatalogSyncError("unsupported source schema version") from error
    if digest != source.content_hash:
        raise CatalogSyncError("authoritative content hash mismatch")
    identity = adapter.source_identity(source).strip()
    if not adapter.source_system.strip() or not identity:
        raise CatalogSyncError("source adapter did not provide immutable provenance")
    return identity


async def _record_failed_run(
    engine: AsyncEngine,
    tenant_id: str,
    sync_run_id: str,
    source_system: str,
    error_code: str,
) -> None:
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO catalog_sync_runs "
                "(tenant_id,sync_run_id,source_system,status,error_code,finished_at) VALUES "
                "(:tenant,:run,:source,'failed',:error,now())"
            ),
            {
                "tenant": tenant_id,
                "run": sync_run_id,
                "source": source_system,
                "error": error_code,
            },
        )


async def pull_once(engine: AsyncEngine, tenant_id: str, adapter: SourceAdapter) -> SyncResult:
    """Pull one page, verify every object, then commit refs and cursor atomically."""
    sync_run_id = f"csync-{uuid.uuid4().hex[:12]}"
    source_system = adapter.source_system.strip()
    try:
        async with tenant_session(engine, tenant_id) as session:
            row = await session.execute(
                text("SELECT cursor FROM catalog_sync_cursors WHERE tenant_id=:tenant AND source_system=:source"),
                {"tenant": tenant_id, "source": source_system},
            )
            cursor = row.scalar_one_or_none()
        objects, next_cursor = await adapter.list_since(cursor)
        identities = {id(source): _verify_source(adapter, source) for source in objects}
        if not source_system:
            raise CatalogSyncError("source_system is required")
    except CatalogSyncError as error:
        await _record_failed_run(engine, tenant_id, sync_run_id, source_system or "unknown", "HASH_OR_SCHEMA_REJECTED")
        return SyncResult(sync_run_id, "failed", 0, 0, str(error))
    except Exception as error:  # source timeout/5xx stays observable and does not alter refs
        await _record_failed_run(engine, tenant_id, sync_run_id, source_system or "unknown", "SOURCE_UNAVAILABLE")
        return SyncResult(sync_run_id, "failed", 0, 0, str(error))

    try:
        async with tenant_session(engine, tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO catalog_sync_runs "
                    "(tenant_id,sync_run_id,source_system,status,cursor_before) VALUES "
                    "(:tenant,:run,:source,'running',:cursor)"
                ),
                {"tenant": tenant_id, "run": sync_run_id, "source": source_system, "cursor": cursor},
            )
            updated_count = 0
            for source in objects:
                existing = await session.execute(
                    text(
                        "SELECT ref_id,content_hash FROM catalog_refs WHERE tenant_id=:tenant "
                        "AND kind=:kind AND stable_id=:stable_id AND version=:version"
                    ),
                    {
                        "tenant": tenant_id,
                        "kind": source.kind,
                        "stable_id": source.stable_id,
                        "version": source.version,
                    },
                )
                row = existing.mappings().first()
                if row is not None:
                    if row["content_hash"] != source.content_hash:
                        raise CatalogSyncError("existing exact CatalogRef hash conflict")
                    await session.execute(
                        text(
                            "UPDATE catalog_refs SET status=:status,source_identity=:identity,updated_at=now() "
                            "WHERE tenant_id=:tenant AND ref_id=:ref_id"
                        ),
                        {
                            "tenant": tenant_id,
                            "ref_id": row["ref_id"],
                            "status": source.status,
                            "identity": identities[id(source)],
                        },
                    )
                else:
                    await session.execute(
                        text(
                            "INSERT INTO catalog_refs "
                            "(tenant_id,ref_id,kind,stable_id,version,content_hash,semantic_schema_version,"
                            "canonicalizer_version,source_system,source_identity,data_domain_id,status) VALUES "
                            "(:tenant,:ref_id,:kind,:stable_id,:version,:content_hash,:schema,:canonicalizer,"
                            ":source,:identity,:domain,:status)"
                        ),
                        {
                            "tenant": tenant_id,
                            "ref_id": f"cref-{uuid.uuid4().hex[:12]}",
                            "kind": source.kind,
                            "stable_id": source.stable_id,
                            "version": source.version,
                            "content_hash": source.content_hash,
                            "schema": source.schema_version,
                            "canonicalizer": "sha256/canonical-json/v1",
                            "source": source_system,
                            "identity": identities[id(source)],
                            "domain": source.data_domain_id,
                            "status": source.status,
                        },
                    )
                updated_count += 1
            await session.execute(
                text(
                    "INSERT INTO catalog_sync_cursors "
                    "(tenant_id,source_system,cursor,last_sync_at,last_object_id) VALUES "
                    "(:tenant,:source,:cursor,now(),:last) "
                    "ON CONFLICT (tenant_id,source_system) DO UPDATE SET cursor=EXCLUDED.cursor,"
                    "last_sync_at=EXCLUDED.last_sync_at,last_object_id=EXCLUDED.last_object_id,updated_at=now()"
                ),
                {
                    "tenant": tenant_id,
                    "source": source_system,
                    "cursor": next_cursor,
                    "last": objects[-1].stable_id if objects else None,
                },
            )
            await session.execute(
                text(
                    "UPDATE catalog_sync_runs SET status='succeeded',cursor_after=:cursor,seen_count=:seen,"
                    "finished_at=now() WHERE tenant_id=:tenant AND sync_run_id=:run"
                ),
                {
                    "tenant": tenant_id,
                    "run": sync_run_id,
                    "cursor": next_cursor,
                    "seen": len(objects),
                },
            )
    except CatalogSyncError as error:
        await _record_failed_run(engine, tenant_id, sync_run_id, source_system or "unknown", "HASH_OR_SCHEMA_REJECTED")
        return SyncResult(sync_run_id, "failed", 0, 0, str(error))
    except Exception as error:  # database failure also leaves existing refs and cursor untouched
        await _record_failed_run(engine, tenant_id, sync_run_id, source_system or "unknown", "COMMIT_FAILED")
        return SyncResult(sync_run_id, "failed", 0, 0, str(error))
    return SyncResult(sync_run_id, "succeeded", len(objects), updated_count)
