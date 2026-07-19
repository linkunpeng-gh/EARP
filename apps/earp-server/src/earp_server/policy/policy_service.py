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
    policy_type: str = "access_control",
    rules: str = "{}",
    status: str = "active",
) -> dict:
    policy_id = f"pol-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO policies (policy_id, tenant_id, policy_type, rules, status) "
                "VALUES (:pid, :tid, :ptype, :rules, :status)"
            ),
            {"pid": policy_id, "tid": tenant_id, "ptype": policy_type, "rules": rules, "status": status},
        )
        await conn.commit()
    return {"policy_id": policy_id}


async def bind_policy(
    engine: AsyncEngine,
    tenant_id: str,
    policy_id: str,
    entity_type: str = "role",
    entity_id: str = "",
) -> dict:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO policy_bindings (policy_id, entity_type, entity_id, tenant_id) "
                "VALUES (:pid, :etype, :eid, :tid)"
            ),
            {"pid": policy_id, "etype": entity_type, "eid": entity_id, "tid": tenant_id},
        )
        await conn.commit()
    return {"policy_id": policy_id, "entity_type": entity_type, "entity_id": entity_id}


async def get_policies_for_role(
    engine: AsyncEngine, tenant_id: str, role_id: str,
) -> list[dict]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT p.policy_id, p.policy_type, p.rules, p.status "
                "FROM policies p "
                "JOIN policy_bindings pb ON p.policy_id = pb.policy_id "
                "WHERE pb.entity_type = 'role' AND pb.entity_id = :rid "
                "AND p.tenant_id = :tid"
            ),
            {"rid": role_id, "tid": tenant_id},
        )
        return [dict(r._mapping) for r in rows]
