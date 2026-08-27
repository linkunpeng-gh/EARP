"""Capability query 执行器（Phase D D1b）——内置 ontology 事实聚合 adapter。

plan_aggregation 的真实执行：capability_call.input = {entity_type_ids,
data_domain_ids, aggregate, group_by, relations} → 从 ABox facts/entities 聚合
（COUNT + group_by；关系计数 join facts）。

一期范围（任务书 D1 方案 A）：
- 实体计数 / 关系计数 / entity_type 分组计数
- SUM/AVG/MAX/MIN 需要数值属性支撑——facts/entities 无数值属性列时返回 None
  （调用方回落，不假造，风险 #1）
- 执行器在 ontology 域直连 DB；**connector 保持无 DB**（通用 adapter 分发 Phase F）
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def _allowed_domain_ids(engine: AsyncEngine, tenant_id: str, role_id: str | None) -> list[str] | None:
    """角色可用数据域（capability_query 权限过滤）。role_id None → 不过滤（None）。

    tech-debt #9：is_admin 角色 → None（全权限，不过滤）；其余按 data_domain_access
    白名单（fail-closed）——不推断（实体 data_domain_id 可指向非 active DD 行）。
    """
    if role_id is None:
        return None
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT is_admin, data_domain_access FROM roles WHERE role_id = :rid AND tenant_id = :tid"),
            {"rid": role_id, "tid": tenant_id},
        )
        r = row.fetchone()
        if r is None:
            return []
        if r.is_admin:
            return None
        if not r.data_domain_access:
            return []
        return [
            str(d["data_domain_id"]) for d in r.data_domain_access if isinstance(d, dict) and d.get("data_domain_id")
        ]


async def execute_capability_query(
    engine: AsyncEngine,
    tenant_id: str,
    capability: dict,
    sq,
    *,
    role_id: str | None = None,
) -> dict | None:
    """执行 ontology 事实聚合。

    返回 {rows, aggregate, capability_id, permission_denied?} 或 None（失败/无数值
    属性支撑——调用方回落 plan_fact）。aggregate: {count: n} 或 {count: n, by: [...rows]}。
    """
    from earp_server.ontology.understanding import StructuredQuery

    if not isinstance(sq, StructuredQuery):
        return None
    entity_type_ids = list({e.semantic_type for e in sq.entities if e.semantic_type})
    if not entity_type_ids:
        return None
    rels = list({r.relation for r in sq.relations if r.relation})
    agg = (sq.operation.aggregate or "COUNT").upper()
    if agg in ("SUM", "AVG", "MAX", "MIN"):
        # 无数值属性支撑（Phase F 绑定业务数据源）
        return None

    dds = await _allowed_domain_ids(engine, tenant_id, role_id)
    if role_id and dds == []:
        return {
            "rows": [],
            "aggregate": {"count": 0},
            "capability_id": capability.get("capability_id"),
            "permission_denied": True,
        }

    group_by = sq.operation.group_by or []
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        params: dict = {"tid": tenant_id, "ets": entity_type_ids}
        dd_clause = ""
        if dds:
            dd_clause = " AND e.data_domain_id = ANY(:dds)"
            params["dds"] = dds
        if rels:
            params["rels"] = rels
            if group_by:
                sql = (
                    "SELECT f.relation_type_id AS by_key, count(*) AS n "
                    "FROM facts f JOIN entities e ON e.entity_id = f.source_entity_id "
                    "WHERE f.tenant_id = :tid AND f.status = 'active' AND f.valid_to IS NULL "
                    "AND f.relation_type_id = ANY(:rels) AND e.entity_type_id = ANY(:ets)"
                    + dd_clause
                    + " GROUP BY f.relation_type_id ORDER BY n DESC LIMIT :lim"
                )
                params["lim"] = sq.operation.limit or 10
            else:
                sql = (
                    "SELECT count(*) AS n FROM facts f JOIN entities e ON e.entity_id = f.source_entity_id "
                    "WHERE f.tenant_id = :tid AND f.status = 'active' AND f.valid_to IS NULL "
                    "AND f.relation_type_id = ANY(:rels) AND e.entity_type_id = ANY(:ets)" + dd_clause
                )
        else:
            if group_by:
                sql = (
                    "SELECT entity_type_id AS by_key, count(*) AS n FROM entities "
                    "WHERE tenant_id = :tid AND status = 'active' AND entity_type_id = ANY(:ets)"
                    + dd_clause.replace("e.data_domain_id", "data_domain_id")
                    + " GROUP BY entity_type_id ORDER BY n DESC LIMIT :lim"
                )
                params["lim"] = sq.operation.limit or 10
            else:
                sql = (
                    "SELECT count(*) AS n FROM entities "
                    "WHERE tenant_id = :tid AND status = 'active' AND entity_type_id = ANY(:ets)"
                    + dd_clause.replace("e.data_domain_id", "data_domain_id")
                )
        rows = await conn.execute(text(sql), params)
        data = [dict(r._mapping) for r in rows.fetchall()]

    if group_by:
        return {
            "rows": data,
            "aggregate": {"count": sum(int(r["n"]) for r in data), "by": data},
            "capability_id": capability.get("capability_id"),
        }
    total = int(data[0]["n"]) if data else 0
    return {
        "rows": data,
        "aggregate": {"count": total},
        "capability_id": capability.get("capability_id"),
    }
