"""Tenant account join service — link a user to multiple tenants (跨域 #30).

M0 DDL tenant_account_joins 表启用。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def add_account_join(
    engine: AsyncEngine, tenant_id: str, user_id: str, role_id: str, org_unit_id: str = "",
) -> dict:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO tenant_account_joins (tenant_id, user_id, role_id, org_unit_id) "
                "VALUES (:tid, :uid, :rid, :oid) "
                "ON CONFLICT (tenant_id, user_id) DO UPDATE SET role_id = :rid2"
            ),
            {"tid": tenant_id, "uid": user_id, "rid": role_id, "oid": org_unit_id, "rid2": role_id},
        )
        await conn.commit()
    return {"tenant_id": tenant_id, "user_id": user_id, "role_id": role_id}


async def get_user_tenants(engine: AsyncEngine, user_id: str, tenant_id: str = "") -> list[dict]:
    async with engine.connect() as conn:
        if tenant_id:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text("SELECT tenant_id, role_id, org_unit_id FROM tenant_account_joins WHERE user_id = :uid"),
            {"uid": user_id},
        )
        return [dict(r._mapping) for r in rows]
