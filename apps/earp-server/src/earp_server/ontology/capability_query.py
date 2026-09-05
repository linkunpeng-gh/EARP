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


async def descendant_count(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    anchor_entity_id: str,
    target_type_ids: list[str],
    role_id: str | None = None,
    max_hops: int = 3,
) -> dict:
    """多跳子图计数（B2，2026-09）：锚点实体沿 facts 出边 ≤max_hops 跳，统计并列出
    目标类型（target_type_ids）的实体（distinct，环路安全——path 去重）。

    用途：plan_aggregation 的 COUNT 兜底——「3号矿有多少台采煤机」在没有 query
    capability 候选（或候选无数据）时，以锚点（3号矿）沿 has_equipment_group /
    equipped_with 等出边走到 shearer 计数，不再回落 plan_fact 答不出数量。

    返回 {rows, aggregate: {count: n}, anchor_entity_id, target_type_ids, hops}；
    锚点无出边/无目标命中 → count=0（0 台也是有效答案，调用方直接产出，区别于
    None=无 capability 支持）。权限：角色域白名单过滤目标实体（fail-closed，
    对齐 execute_capability_query）。
    """
    dds = await _allowed_domain_ids(engine, tenant_id, role_id)
    if role_id and dds == []:
        return {
            "rows": [],
            "aggregate": {"count": 0},
            "anchor_entity_id": anchor_entity_id,
            "target_type_ids": target_type_ids,
            "hops": int(max_hops),
            "permission_denied": True,
        }
    dd_clause = ""
    params: dict = {"tid": tenant_id, "anchor": anchor_entity_id, "tids": target_type_ids, "hops": int(max_hops)}
    if dds:
        dd_clause = " AND e.data_domain_id = ANY(:dds)"
        params["dds"] = dds
    sql = f"""
        WITH RECURSIVE sub AS (
            SELECT 1 AS depth, f.target_entity_id AS eid,
                   CAST(f.source_entity_id AS TEXT) AS path
            FROM facts f
            WHERE f.tenant_id = :tid AND f.source_entity_id = :anchor
              AND f.status = 'active' AND f.valid_to IS NULL
            UNION ALL
            SELECT s.depth + 1, f.target_entity_id, s.path || ',' || f.target_entity_id
            FROM sub s
            JOIN facts f ON f.source_entity_id = s.eid
              AND f.tenant_id = :tid AND f.status = 'active' AND f.valid_to IS NULL
            WHERE s.depth < :hops
              AND position(f.target_entity_id IN s.path) = 0
        )
        SELECT e.entity_id, e.name, e.entity_type_id, min(s.depth) AS depth
        FROM sub s
        JOIN entities e ON e.entity_id = s.eid AND e.tenant_id = :tid AND e.status = 'active'
        WHERE e.entity_type_id = ANY(:tids){dd_clause}
        GROUP BY e.entity_id, e.name, e.entity_type_id
        ORDER BY e.name
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = (await conn.execute(text(sql), params)).fetchall()
    data = [dict(r._mapping) for r in rows]
    return {
        "rows": data,
        "aggregate": {"count": len(data)},
        "anchor_entity_id": anchor_entity_id,
        "target_type_ids": target_type_ids,
        "hops": int(max_hops),
    }
