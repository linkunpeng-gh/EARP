"""Tenant account join service — link a user to multiple tenants (跨域 #30).

M0 DDL tenant_account_joins 表启用。
Columns: tenant_id, user_id, role_ids TEXT[], current_role_id VARCHAR(64).

Uses tenant_session() — preferred pattern for new data-access code.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session


async def add_account_join(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    role_id: str,
) -> dict:
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_account_joins (tenant_id, user_id, current_role_id) "
                "VALUES (:tid, :uid, :rid) "
                "ON CONFLICT (tenant_id, user_id) DO UPDATE SET current_role_id = :rid2"
            ),
            {"tid": tenant_id, "uid": user_id, "rid": role_id, "rid2": role_id},
        )
    return {"tenant_id": tenant_id, "user_id": user_id, "role_id": role_id}


async def get_user_tenants(engine: AsyncEngine, user_id: str, tenant_id: str = "") -> list[dict]:
    if tenant_id:
        async with tenant_session(engine, tenant_id) as session:
            rows = await session.execute(
                text("SELECT tenant_id, current_role_id, user_id FROM tenant_account_joins WHERE user_id = :uid"),
                {"uid": user_id},
            )
            return [dict(r._mapping) for r in rows]
    # No tenant context — cross-tenant query (admin use)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tenant_id, current_role_id, user_id FROM tenant_account_joins WHERE user_id = :uid"),
            {"uid": user_id},
        )
        return [dict(r._mapping) for r in rows]
