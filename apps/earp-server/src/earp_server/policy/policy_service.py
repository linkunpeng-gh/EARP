"""Policy table service — enable M0 DDL policies + policy_bindings tables (M7+ #21/22).

M2 PolicyLayer currently hardcodes role.permissions check via DB lookup.
M7+: dynamic policies registered here feed into PolicyLayer evaluation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def create_policy(
    engine: AsyncEngine,
    tenant_id: str,
    name: str,
    resource_type: str,
    action: str,
    conditions: str = "{}",
) -> dict:
    policy_id = f"pol-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO policies (policy_id, tenant_id, name, resource_type, action, conditions) "
                "VALUES (:pid, :tid, :name, :rtype, :action, :conds)"
            ),
            {"pid": policy_id, "tid": tenant_id, "name": name, "rtype": resource_type,
             "action": action, "conds": conditions},
        )
        await conn.commit()
    return {"policy_id": policy_id}


async def bind_policy(
    engine: AsyncEngine,
    tenant_id: str,
    policy_id: str,
    role_id: str,
) -> dict:
    binding_id = f"bnd-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO policy_bindings (binding_id, tenant_id, policy_id, role_id) "
                "VALUES (:bid, :tid, :pid, :rid)"
            ),
            {"bid": binding_id, "tid": tenant_id, "pid": policy_id, "rid": role_id},
        )
        await conn.commit()
    return {"binding_id": binding_id}


async def get_policies_for_role(
    engine: AsyncEngine, tenant_id: str, role_id: str,
) -> list[dict]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT p.policy_id, p.name, p.resource_type, p.action, p.conditions "
                "FROM policies p "
                "JOIN policy_bindings pb ON p.policy_id = pb.policy_id "
                "WHERE pb.role_id = :rid AND p.tenant_id = :tid"
            ),
            {"rid": role_id, "tid": tenant_id},
        )
        return [dict(r._mapping) for r in rows]
