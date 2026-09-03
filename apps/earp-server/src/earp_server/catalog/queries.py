"""Tenant-scoped read models used by the Catalog product pages."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session


async def list_refs(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    kind: str | None = None,
    status: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["deleted_at IS NULL"]
    params: dict[str, Any] = {}
    if kind:
        clauses.append("kind=:kind")
        params["kind"] = kind
    if status:
        clauses.append("status=:status")
        params["status"] = status
    if query:
        clauses.append("(stable_id ILIKE :query OR source_identity ILIKE :query)")
        params["query"] = f"%{query}%"
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT ref_id,kind,stable_id,version,content_hash,semantic_schema_version,"
                "source_system,source_identity,data_domain_id,status,created_at,updated_at "
                f"FROM catalog_refs WHERE {' AND '.join(clauses)} ORDER BY kind,stable_id,version"
            ),
            params,
        )
        return [dict(row) for row in rows.mappings()]


async def list_packs(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT p.pack_id,p.version,p.layer,p.name,p.owner_role,p.content_hash,p.status,"
                "p.revision,p.created_at,p.published_at,count(e.kind)::int AS entry_count "
                "FROM catalog_packs p LEFT JOIN catalog_pack_entries e ON "
                "e.tenant_id=p.tenant_id AND e.pack_id=p.pack_id AND e.pack_version=p.version "
                "WHERE p.deleted_at IS NULL GROUP BY p.tenant_id,p.pack_id,p.version "
                "ORDER BY p.layer,p.pack_id,p.version"
            )
        )
        return [dict(row) for row in rows.mappings()]


async def list_manifests(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT m.manifest_id,m.manifest_revision,m.profile_id,m.manifest_hash,m.envelope_hash,"
                "m.status,m.created_at,m.revoked_at,(a.manifest_id IS NOT NULL) AS is_active "
                "FROM catalog_manifests m LEFT JOIN catalog_active_manifests a ON "
                "a.tenant_id=m.tenant_id AND a.manifest_id=m.manifest_id "
                "AND a.manifest_revision=m.manifest_revision AND a.profile_id=m.profile_id "
                "ORDER BY m.profile_id,m.manifest_revision DESC"
            )
        )
        return [dict(row) for row in rows.mappings()]


async def list_profiles(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT profile_id,catalog_profile_id,profile_schema_version,industry_scope,"
                "enterprise_scope,data_domain_id,jsonb_array_length(roles)::int AS role_count,"
                "backup_approver,status,revision,created_at,updated_at FROM catalog_profiles "
                "WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
        )
        return [dict(row) for row in rows.mappings()]


async def list_approvals(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT approval_id,request_id,approver_id,decision,reason,emergency,expires_at,created_at "
                "FROM catalog_approvals ORDER BY created_at DESC"
            )
        )
        return [dict(row) for row in rows.mappings()]


async def catalog_metrics(engine: AsyncEngine, tenant_id: str) -> dict[str, Any]:
    """Return tenant-scoped operational counters for the Catalog dashboard."""
    async with tenant_session(engine, tenant_id) as session:
        refs = await session.execute(
            text("SELECT status,count(*)::int AS count FROM catalog_refs WHERE deleted_at IS NULL GROUP BY status")
        )
        packs = await session.execute(
            text("SELECT status,count(*)::int AS count FROM catalog_packs WHERE deleted_at IS NULL GROUP BY status")
        )
        approvals = await session.execute(
            text(
                "SELECT count(*)::int FROM catalog_change_requests "
                "WHERE status IN ('submitted','approved_pending_fulfillment','fulfillment_failed')"
            )
        )
        sync = await session.execute(
            text(
                "SELECT source_system,status,started_at,finished_at,error_code FROM catalog_sync_runs "
                "ORDER BY started_at DESC LIMIT 20"
            )
        )
        drift = await session.execute(
            text(
                "SELECT count(*)::int FROM catalog_manifest_entries me "
                "JOIN catalog_active_manifests am ON am.tenant_id=me.tenant_id "
                "AND am.manifest_id=me.manifest_id AND am.manifest_revision=me.manifest_revision "
                "JOIN catalog_refs cr ON cr.tenant_id=me.tenant_id AND cr.kind=me.kind "
                "AND cr.stable_id=me.stable_id AND cr.version=me.version "
                "WHERE me.tenant_id=:tenant AND am.manifest_id IS NOT NULL "
                "AND cr.content_hash <> me.content_hash"
            ),
            {"tenant": tenant_id},
        )
        return {
            "refs_by_status": {row["status"]: row["count"] for row in refs.mappings()},
            "packs_by_status": {row["status"]: row["count"] for row in packs.mappings()},
            "approval_backlog": approvals.scalar_one(),
            "hash_drift_count": drift.scalar_one(),
            "recent_sync_runs": [dict(row) for row in sync.mappings()],
            "runtime": {
                "api_latency_ms": None,
                "api_error_rate": None,
                "resolver_cache_hit_rate": None,
                "note": "process metrics require the deployment metrics exporter",
            },
        }
