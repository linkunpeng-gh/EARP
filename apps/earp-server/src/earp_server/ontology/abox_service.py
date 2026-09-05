"""Ontology ABox service — entity/fact CRUD + lookup + graph traversal + profile.

PRD-2026-030 M1. Native-SQL style, RLS via SET LOCAL. Compiled Truth profile
aggregation is rule-based in M1 (summary/key_facts/related_entities/stats).
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def upsert_entity(
    engine: AsyncEngine,
    tenant_id: str,
    entity_type_id: str,
    name: str,
    *,
    entity_id: str | None = None,
    business_code: str | None = None,
    attributes: dict | None = None,
    source_mode: str = "extracted",
    source_ref: str | None = None,
    data_domain_id: str | None = None,
) -> dict:
    """Idempotent upsert keyed by (tenant, entity_type, business_code) when code given;
    otherwise keyed by entity_id. business_code NULL → always insert new entity.

    2026-09 一致性（arch/design/2026-09-04-entity-type-data-domain-change-design.md §4.4）：
    实例数据域以**所属类型的 data_domain_id** 为唯一事实——省略自动取类型域；
    显式传入与类型不一致 → fail-fast（不静默覆盖）。merge-update 路径同规则
    （顺带纠正历史不一致实例）。
    """
    eid = entity_id or f"ent-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        # 类型域（一致性事实源）：同连接查询，避免开额外连接
        # FOR SHARE：与 TBox update 审批（_apply_domain_update 对类型行加排他锁并级联迁移
        # active/deprecated 实例）互斥。READ COMMITTED 下若无锁，存在 TOCTOU：本事务读到
        # 旧域 → 审批并发迁移类型+实例并提交 → 本事务再把旧域写回实例行，静默覆盖已迁移
        # 实例（RLS 数据域可见性随之错位，直到该行再次被 upsert）。共享锁保证两种时序均
        # 一致：审批先提交 → 本读阻塞后重读拿到新域；审批后到 → 阻塞至本事务提交，其级联
        # 迁移随后覆盖本事务写入的行。
        trow = await conn.execute(
            text("SELECT data_domain_id FROM entity_types WHERE entity_type_id = :et AND tenant_id = :tid FOR SHARE"),
            {"et": entity_type_id, "tid": tenant_id},
        )
        tr = trow.fetchone()
        type_dd: str | None = tr.data_domain_id if tr is not None else None
        if data_domain_id is not None and data_domain_id != type_dd:
            raise ValueError(
                f"数据域 {data_domain_id} 与实体类型 {entity_type_id} 的数据域不一致"
                f"（{type_dd or '未配置'}）——数据域以类型为准，请省略该字段"
            )
        dd = type_dd
        if business_code:
            # find existing row by (entity_type, business_code) and merge
            existing = await conn.execute(
                text(
                    "SELECT entity_id FROM entities "
                    "WHERE tenant_id = :tid AND entity_type_id = :et AND business_code = :code "
                    "AND status = 'active'"
                ),
                {"tid": tenant_id, "et": entity_type_id, "code": business_code},
            )
            row = existing.fetchone()
            if row is not None:
                eid = row.entity_id
                await conn.execute(
                    text(
                        "UPDATE entities SET name = :name, attributes = :attrs, "
                        "data_domain_id = :dd, updated_at = now() "
                        "WHERE entity_id = :eid"
                    ),
                    {"name": name, "attrs": json.dumps(attributes or {}), "dd": dd, "eid": eid},
                )
                await conn.commit()
                # tech-debt #11：merge 写时失效（实体变更 → profile 重编译）+ timeline
                await _invalidate_profiles(engine, tenant_id, [eid])
                await _log_timeline(
                    engine,
                    tenant_id,
                    eid,
                    "entity.updated",
                    {"entity_type_id": entity_type_id, "name": name},
                    eid,
                )
                return {"entity_id": eid, "merged": True}

        await conn.execute(
            text(
                "INSERT INTO entities "
                "(entity_id, tenant_id, entity_type_id, name, business_code, attributes, "
                "source_mode, source_ref, data_domain_id) "
                "VALUES (:eid, :tid, :et, :name, :code, :attrs, :sm, :ref, :dd)"
            ),
            {
                "eid": eid,
                "tid": tenant_id,
                "et": entity_type_id,
                "name": name,
                "code": business_code,
                "attrs": json.dumps(attributes or {}),
                "sm": source_mode,
                "ref": source_ref,
                "dd": dd,
            },
        )
        await conn.commit()
    # tech-debt #11：新实体写 timeline（entity.created）；无 profile 无需失效（惰性编译兜底）
    await _log_timeline(
        engine,
        tenant_id,
        eid,
        "entity.created",
        {"entity_type_id": entity_type_id, "name": name},
        eid,
    )
    return {"entity_id": eid, "merged": False}


async def get_entity(engine: AsyncEngine, tenant_id: str, entity_id: str) -> dict | None:
    """Fetch an entity by id. 2026-08-16：允许 deprecated（管理详情/图谱追溯）；
    检索路径用 lookup_entities（仍仅 active），互不影响。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT * FROM entities WHERE entity_id = :eid AND status IN ('active','deprecated')"),
            {"eid": entity_id},
        )
        r = row.fetchone()
        return dict(r._mapping) if r else None


async def lookup_entities(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    *,
    entity_type_ids: list[str] | None = None,
    data_domain_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Name / business_code match with data-domain filter (双层权限由调用方按 DD 评估).

    双向子串匹配（2026-08-16 修复「纯中文实体长查询不命中」）：
      - 正向：实体名包含查询串（name ILIKE %query%，原行为）
      - 反向：查询串包含实体名（:qpat LIKE %name%）——「主变压器是哪个公司生产的」→
        命中实体「主变压器」（实体提及检测的本质）。代价：两方向均全表扫，
        实体表规模 < 万级可接受（QU Phase B 实体识别增强前的兜底）。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        sql = (
            "SELECT entity_id, entity_type_id, name, business_code, attributes, source_mode, data_domain_id "
            "FROM entities WHERE tenant_id = :tid AND status = 'active' "
            "AND (name ILIKE :pat OR business_code ILIKE :pat "
            "     OR :qpat LIKE '%' || name || '%' "
            "     OR (:qpat LIKE '%' || business_code || '%'))"
        )
        params: dict = {"tid": tenant_id, "pat": f"%{query}%", "qpat": query}
        if entity_type_ids:
            sql += " AND entity_type_id = ANY(:ets)"
            params["ets"] = entity_type_ids
        if data_domain_ids:
            sql += " AND data_domain_id = ANY(:dds)"
            params["dds"] = data_domain_ids
        sql += f" ORDER BY name LIMIT {int(top_k)}"
        rows = await conn.execute(text(sql), params)
        return [dict(r._mapping) for r in rows.fetchall()]


async def list_entities(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    entity_type_ids: list[str] | None = None,
    data_domain_ids: list[str] | None = None,
    status: str = "active",
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
) -> tuple[list[dict], int]:
    """Paginated entity list with type/DD filters + keyword search (M4 admin). Returns (rows, total)."""
    where = ["tenant_id = :tid"]
    params: dict = {"tid": tenant_id}
    if status != "all":  # all = 不过滤状态（含 deprecated，配合「显示已停用」）
        where.append("status = :st")
        params["st"] = status
    if q:
        where.append("(name ILIKE :q OR business_code ILIKE :q)")
        params["q"] = f"%{q}%"
    if entity_type_ids:
        where.append("entity_type_id = ANY(:ets)")
        params["ets"] = entity_type_ids
    if data_domain_ids:
        where.append("data_domain_id = ANY(:dds)")
        params["dds"] = data_domain_ids
    w = " AND ".join(where)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        total = (await conn.execute(text(f"SELECT count(*) FROM entities WHERE {w}"), params)).scalar()
        rows = await conn.execute(
            text(
                f"SELECT entity_id, entity_type_id, name, business_code, attributes, source_mode, "
                f"data_domain_id, status, created_at, updated_at FROM entities WHERE {w} "
                f"ORDER BY updated_at DESC LIMIT :lim OFFSET :off"
            ),
            {**params, "lim": page_size, "off": (page - 1) * page_size},
        )
        return [dict(r._mapping) for r in rows.fetchall()], int(total or 0)


async def deprecate_entity(engine: AsyncEngine, tenant_id: str, entity_id: str) -> dict | None:
    """Mark entity deprecated (soft-delete; facts referencing it stay for audit)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE entities SET status = 'deprecated', updated_at = now() "
                "WHERE entity_id = :eid AND status = 'active' RETURNING entity_id, status"
            ),
            {"eid": entity_id},
        )
        await conn.commit()
        r = result.fetchone()
        return dict(r._mapping) if r else None


# ── tech-debt #11: profile 过期管理（写时失效 + timeline）──────────────────────


async def _log_timeline(
    engine: AsyncEngine,
    tenant_id: str,
    entity_id: str,
    event_type: str,
    payload: dict | None = None,
    source_ref: str | None = None,
) -> None:
    """写 entity_timeline（recent_events 消费 + freshness 时间源之一）。失败不影响主操作。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            await conn.execute(
                text(
                    "INSERT INTO entity_timeline "
                    "(entity_timeline_id, tenant_id, entity_id, event_type, payload, occurred_at, source_ref) "
                    "VALUES (:id, :tid, :eid, :et, :p, now(), :ref)"
                ),
                {
                    "id": f"tl-{uuid.uuid4().hex[:12]}",
                    "tid": tenant_id,
                    "eid": entity_id,
                    "et": event_type,
                    "p": json.dumps(payload or {}),
                    "ref": source_ref,
                },
            )
            await conn.commit()
    except Exception:
        logger.warning("_log_timeline failed for %s/%s", entity_id, event_type, exc_info=True)


async def _profile_exists(engine: AsyncEngine, tenant_id: str, entity_id: str) -> bool:
    """轻量 profile 存在性检查（避免 get_entity_profile 的 freshness 递归编译）。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(text("SELECT 1 FROM entity_profiles WHERE entity_id = :eid"), {"eid": entity_id})
        return row.fetchone() is not None


async def _invalidate_profiles(engine: AsyncEngine, tenant_id: str, entity_ids: list[str]) -> None:
    """写时失效（D1）：已有 profile 的实体重编译；无 profile 跳过（惰性编译兜底）。

    钩子失败不影响主操作（写事实是主操作，profile 重编译是补偿）。
    """
    for eid in entity_ids:
        try:
            if await _profile_exists(engine, tenant_id, eid):
                await compile_profile(engine, tenant_id, eid)
        except Exception:
            logger.warning("_invalidate_profiles failed for %s", eid, exc_info=True)


async def add_fact(
    engine: AsyncEngine,
    tenant_id: str,
    source_entity_id: str,
    relation_type_id: str,
    target_entity_id: str,
    *,
    confidence: float = 1.0,
    source_ref: str | None = None,
    fact_id: str | None = None,
) -> dict:
    fid = fact_id or f"fact-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO facts "
                "(fact_id, tenant_id, source_entity_id, relation_type_id, target_entity_id, confidence, source_ref) "
                "VALUES (:fid, :tid, :src, :rel, :tgt, :conf, :ref)"
            ),
            {
                "fid": fid,
                "tid": tenant_id,
                "src": source_entity_id,
                "rel": relation_type_id,
                "tgt": target_entity_id,
                "conf": confidence,
                "ref": source_ref,
            },
        )
        await conn.commit()
    # tech-debt #11：写时失效（source+target profile 重编译）+ timeline
    await _invalidate_profiles(engine, tenant_id, [source_entity_id, target_entity_id])
    await _log_timeline(
        engine,
        tenant_id,
        source_entity_id,
        "fact.added",
        {"relation_type_id": relation_type_id, "target_entity_id": target_entity_id},
        fid,
    )
    return {"fact_id": fid, "status": "active"}


async def revoke_fact(engine: AsyncEngine, tenant_id: str, fact_id: str, reason: str = "") -> dict | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        src = await conn.execute(text("SELECT source_entity_id FROM facts WHERE fact_id = :fid"), {"fid": fact_id})
        src_row = src.fetchone()
        result = await conn.execute(
            text(
                "UPDATE facts SET status = 'revoked', updated_at = now() WHERE fact_id = :fid RETURNING fact_id, status"
            ),
            {"fid": fact_id},
        )
        await conn.commit()
        r = result.fetchone()
        if r is None:
            return None
    # tech-debt #11：写时失效（source profile）+ timeline
    if src_row is not None:
        await _invalidate_profiles(engine, tenant_id, [src_row.source_entity_id])
        await _log_timeline(engine, tenant_id, src_row.source_entity_id, "fact.revoked", {"fact_id": fact_id}, fact_id)
    return dict(r._mapping)


async def graph_query(
    engine: AsyncEngine,
    tenant_id: str,
    entity_id: str,
    max_hops: int = 3,
    direction: str = "forward",
) -> list[dict]:
    """Recursive CTE traversal (≤ max_hops, cycle-protected via visited path).

    direction: "forward" (source→target, default) | "backward" (target→source)
    — backward 用于「某实体被谁关联」（如 工厂 → 位于该厂的设备，QU 设计 §12 例 4
    Phase D2 缺口闭合）。返回行统一为 {depth, relation_type_id, source_entity_id,
    target_entity_id, target_name, target_type}：backward 时邻居实体（原 source）
    以 target_* 字段呈现，消费方（knowledge_search Layer 2）无需感知方向。
    """
    if direction == "backward":
        sql = text(
            """
            WITH RECURSIVE hops AS (
                SELECT 1 AS depth, f.relation_type_id, f.source_entity_id, f.target_entity_id,
                       f.fact_id,
                       CAST(f.source_entity_id AS TEXT) AS path
                FROM facts f
                WHERE f.tenant_id = :tid AND f.target_entity_id = :eid
                  AND f.status = 'active' AND f.valid_to IS NULL
                UNION ALL
                SELECT h.depth + 1, f.relation_type_id, f.source_entity_id, f.target_entity_id,
                       f.fact_id,
                       h.path || ',' || f.source_entity_id
                FROM hops h
                JOIN facts f ON f.target_entity_id = h.source_entity_id
                    AND f.tenant_id = :tid AND f.status = 'active' AND f.valid_to IS NULL
                WHERE h.depth < :max_hops
                  AND position(f.source_entity_id in h.path) = 0
            )
            SELECT h.depth, h.relation_type_id, h.source_entity_id, h.target_entity_id,
                   h.fact_id,
                   e.name AS target_name, e.entity_type_id AS target_type
            FROM hops h
            LEFT JOIN entities e ON e.entity_id = h.source_entity_id AND e.tenant_id = :tid
            ORDER BY h.depth, h.source_entity_id
            """
        )
    else:
        sql = text(
            """
            WITH RECURSIVE hops AS (
                SELECT 1 AS depth, f.relation_type_id, f.source_entity_id, f.target_entity_id,
                       f.fact_id,
                       CAST(f.target_entity_id AS TEXT) AS path
                FROM facts f
                WHERE f.tenant_id = :tid AND f.source_entity_id = :eid
                  AND f.status = 'active' AND f.valid_to IS NULL
                UNION ALL
                SELECT h.depth + 1, f.relation_type_id, f.source_entity_id, f.target_entity_id,
                       f.fact_id,
                       h.path || ',' || f.target_entity_id
                FROM hops h
                JOIN facts f ON f.source_entity_id = h.target_entity_id
                    AND f.tenant_id = :tid AND f.status = 'active' AND f.valid_to IS NULL
                WHERE h.depth < :max_hops
                  AND position(f.target_entity_id in h.path) = 0
            )
            SELECT h.depth, h.relation_type_id, h.source_entity_id, h.target_entity_id,
                   h.fact_id,
                   e.name AS target_name, e.entity_type_id AS target_type
            FROM hops h
            LEFT JOIN entities e ON e.entity_id = h.target_entity_id AND e.tenant_id = :tid
            ORDER BY h.depth, h.target_entity_id
            """
        )
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(sql, {"tid": tenant_id, "eid": entity_id, "max_hops": max_hops})
        return [dict(r._mapping) for r in rows.fetchall()]


async def find_stale_profiles(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    max_n: int = 100,
) -> list[str]:
    """扫描需要重编译的实体（tech-debt #11 D3）：无 profile 或 compiled_at < last_change。

    last_change 同 get_entity_profile 三源（timeline / facts.updated_at / entities.updated_at）。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT e.entity_id FROM entities e "
                "LEFT JOIN entity_profiles p ON p.entity_id = e.entity_id "
                "WHERE e.tenant_id = :tid AND e.status = 'active' "
                "AND (p.entity_id IS NULL OR p.compiled_at < GREATEST("
                "  COALESCE((SELECT MAX(t.occurred_at) FROM entity_timeline t "
                "     WHERE t.entity_id = e.entity_id), '-infinity'::timestamptz), "
                "  COALESCE((SELECT MAX(f.updated_at) FROM facts f "
                "     WHERE f.source_entity_id = e.entity_id OR f.target_entity_id = e.entity_id), "
                "     '-infinity'::timestamptz), "
                "  COALESCE(e.updated_at, '-infinity'::timestamptz)"
                ")) "
                "LIMIT :n"
            ),
            {"tid": tenant_id, "n": max_n},
        )
        return [r.entity_id for r in rows.fetchall()]


async def compile_profile(engine: AsyncEngine, tenant_id: str, entity_id: str) -> dict | None:
    """Rule-based Compiled Truth: aggregate entity + active facts + recent timeline."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        entity_row = await conn.execute(
            text("SELECT * FROM entities WHERE entity_id = :eid AND status IN ('active','deprecated')"),
            {"eid": entity_id},
        )
        e = entity_row.fetchone()
        if e is None:
            return None

        facts_rows = await conn.execute(
            text(
                "SELECT r.name AS relation, t.name AS target_name, t.entity_type_id AS target_type "
                "FROM facts f JOIN relation_types r ON r.relation_type_id = f.relation_type_id "
                "JOIN entities t ON t.entity_id = f.target_entity_id "
                "WHERE f.source_entity_id = :eid AND f.status = 'active' AND f.valid_to IS NULL"
            ),
            {"eid": entity_id},
        )
        key_facts = [dict(r._mapping) for r in facts_rows.fetchall()]

        rel_rows = await conn.execute(
            text(
                "SELECT DISTINCT entity_type_id FROM entities "
                "WHERE entity_id IN (SELECT target_entity_id FROM facts "
                "WHERE source_entity_id = :eid AND status = 'active' AND valid_to IS NULL)"
            ),
            {"eid": entity_id},
        )
        related_types = [r.entity_type_id for r in rel_rows.fetchall()]

        timeline_rows = await conn.execute(
            text(
                "SELECT event_type, occurred_at FROM entity_timeline "
                "WHERE entity_id = :eid ORDER BY occurred_at DESC LIMIT 20"
            ),
            {"eid": entity_id},
        )
        recent_events = [dict(r._mapping) for r in timeline_rows.fetchall()]

    profile = {
        "entity_id": entity_id,
        "entity_type": e.entity_type_id,
        "name": e.name,
        "summary": None,  # LLM-generated summary deferred to M2 (rule aggregation only)
        "key_facts": key_facts,
        "related_types": related_types,
        "stats": {"fact_count": len(key_facts), "recent_events": len(recent_events)},
    }

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "INSERT INTO entity_profiles (entity_profile_id, tenant_id, entity_id, profile, profile_version) "
                "VALUES (:pid, :tid, :eid, :prof, 1) "
                "ON CONFLICT (entity_id) DO UPDATE SET profile = EXCLUDED.profile, "
                "profile_version = entity_profiles.profile_version + 1, compiled_at = now() "
                "RETURNING entity_id, profile_version, compiled_at"
            ),
            {
                "pid": f"prof-{uuid.uuid4().hex[:12]}",
                "tid": tenant_id,
                "eid": entity_id,
                "prof": json.dumps(profile, default=str),
            },
        )
        await conn.commit()
        r = result.fetchone()
        assert r is not None
        return {"entity_id": r.entity_id, "profile_version": r.profile_version, "profile": profile}


async def get_entity_profile(engine: AsyncEngine, tenant_id: str, entity_id: str) -> dict | None:
    """Fetch profile with read-time freshness check (tech-debt #11 D2).

    last_change = GREATEST(entity_timeline MAX, facts.updated_at MAX, entities.updated_at)
    —— timeline 为主源（钩子写入），facts.updated_at/entities.updated_at 回退存量；
    过期（compiled_at < last_change）→ 重编译并返回新值。knowledge_search 的
    profile lane 复用本函数，自动获得校验（无需改检索代码）。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT entity_id, profile, profile_version, compiled_at FROM entity_profiles WHERE entity_id = :eid"),
            {"eid": entity_id},
        )
        r = row.fetchone()
        if r is None:
            return None
        last_change = await conn.execute(
            text(
                "SELECT GREATEST("
                "  COALESCE((SELECT MAX(occurred_at) FROM entity_timeline "
                "     WHERE entity_id = :eid), '-infinity'::timestamptz), "
                "  COALESCE((SELECT MAX(updated_at) FROM facts "
                "     WHERE source_entity_id = :eid OR target_entity_id = :eid), "
                "     '-infinity'::timestamptz), "
                "  COALESCE((SELECT updated_at FROM entities WHERE entity_id = :eid), "
                "     '-infinity'::timestamptz)"
                ")"
            ),
            {"eid": entity_id},
        )
        last = last_change.scalar()
        if last is not None and r.compiled_at < last:
            # 过期 → 重编译（profile_version 递增）
            return await compile_profile(engine, tenant_id, entity_id)
        return dict(r._mapping)
