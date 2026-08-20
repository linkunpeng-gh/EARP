"""M3 D1 — Enrichment 夜间任务（Phase 2c）：④ profile 重编 → ③ 失效事实清理 →
① timeline 回填 → ② 热度报告。

载体（D4）：scheduler 循环（与 tech-debt #11 的 profile enrichment 合并，同进程同节奏）；
手动触发端点 POST /v1/ontology/enrichment/run（调试/测试）。

- ③ 失效清理（G4）：status='active' AND valid_to < now() → revoke_fact 完整流程
  （timeline + audit + updated_at + 写时失效）→ profile 自动 stale → ④ 下一轮重编；limit 分批 + 幂等
- ① timeline 回填（G2）：近窗 executions.result 的 citations[].entity_id（profile/graph 源）
  → entity_timeline（event_type 映射 + source_ref=execution_id 去重）——不用名称匹配
  （audit_logs 无实体名，capability_entity_map 是类型级）
- ② 热度报告（G3）：同窗实体引用频次 top-N（仅报告，不落库——Phase 2b 未实现无消费方）
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session
from earp_server.ontology import abox_service

logger = logging.getLogger(__name__)

# G2：citations 源 → timeline event_type 映射（执行结果溯源到实体行为）
_SOURCE_EVENT = {"profile": "query.entity", "graph": "graph.entity"}


def _extract_entity_refs(result: dict) -> list[tuple[str, str]]:
    """从 PlanResult dict 提取 (entity_id, event_type)。容错：无 citations/无 entity_id 跳过。"""
    refs: list[tuple[str, str]] = []
    for cit in result.get("citations") or []:
        eid = cit.get("entity_id")
        if not eid:
            continue
        event_type = _SOURCE_EVENT.get(cit.get("source"), "query.entity")
        refs.append((eid, event_type))
    return refs


async def _add_timeline_once(
    engine: AsyncEngine,
    tenant_id: str,
    entity_id: str,
    event_type: str,
    source_ref: str,
    occurred_at,
) -> bool:
    """写 timeline（去重：同 entity+source_ref+event_type 跳过；实体不存在 FK 兜底跳过）。"""
    async with tenant_session(engine, tenant_id) as session:
        dup = await session.execute(
            text(
                "SELECT 1 FROM entity_timeline WHERE entity_id = :e AND source_ref = :r "
                "AND event_type = :t"
            ),
            {"e": entity_id, "r": source_ref, "t": event_type},
        )
        if dup.first():
            return False
        try:
            await session.execute(
                text(
                    "INSERT INTO entity_timeline (entity_timeline_id, tenant_id, entity_id, "
                    "event_type, payload, occurred_at, source_ref) "
                    "VALUES (:id, :tid, :e, :t, :p, :o, :r)"
                ),
                {
                    "id": f"tl-{uuid.uuid4().hex[:12]}",
                    "tid": tenant_id,
                    "e": entity_id,
                    "t": event_type,
                    "p": json.dumps({"source": "execution"}),
                    "o": occurred_at,
                    "r": source_ref,
                },
            )
            return True
        except Exception:  # noqa: BLE001 — 实体被删/FK 失败 → 跳过不阻断
            logger.debug("timeline insert skipped for %s (%s)", entity_id, source_ref)
            return False


async def enrichment_run(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    window_days: int = 7,
    limit: int = 200,
) -> dict:
    """Enrichment 全流程（④③①②）。返回分项统计。"""
    profiles_recompiled = 0
    facts_revoked = 0
    timeline_added = 0

    # ④ profile 重编（复用 tech-debt #11 D3 逻辑）
    stale = await abox_service.find_stale_profiles(engine, tenant_id, max_n=limit)
    for eid in stale:
        try:
            await abox_service.compile_profile(engine, tenant_id, eid)
            profiles_recompiled += 1
        except Exception:  # noqa: BLE001
            logger.warning("enrichment: profile recompile failed %s", eid, exc_info=True)

    # ③ 失效事实清理（G4：完整 revoke 流程，只处理 active，limit 分批幂等）
    async with tenant_session(engine, tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT fact_id FROM facts WHERE tenant_id = :t AND status = 'active' "
                    "AND valid_to < now() LIMIT :lim"
                ),
                {"t": tenant_id, "lim": limit},
            )
        ).mappings().all()
    for r in rows:
        fid = r["fact_id"]
        try:
            await abox_service.revoke_fact(engine, tenant_id, fid, reason="valid_to 过期（enrichment）")
            facts_revoked += 1
        except Exception:  # noqa: BLE001
            logger.warning("enrichment: revoke failed %s", fid, exc_info=True)

    # ① timeline 回填（G2：executions.result citations → entity_timeline）
    async with tenant_session(engine, tenant_id) as session:
        exec_rows = (
            await session.execute(
                text(
                    "SELECT execution_id, created_at, result FROM executions "
                    "WHERE tenant_id = :t AND result IS NOT NULL "
                    "AND created_at > now() - make_interval(days => :win)"
                ),
                {"t": tenant_id, "win": window_days},
            )
        ).mappings().all()
    hot: Counter[str] = Counter()
    for ex in exec_rows:
        raw = ex["result"] or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
        if not isinstance(raw, dict):
            continue
        for eid, event_type in _extract_entity_refs(raw):
            hot[eid] += 1
            inserted = await _add_timeline_once(
                engine, tenant_id, eid, event_type, ex["execution_id"], ex["created_at"]
            )
            if inserted:
                timeline_added += 1

    # ② 热度报告（同源 top-N，仅报告不落库——G3）
    hot_missing = [{"entity_id": eid, "refs": n} for eid, n in hot.most_common(10)]
    return {
        "profiles_recompiled": profiles_recompiled,
        "facts_revoked": facts_revoked,
        "timeline_added": timeline_added,
        "hot_missing": hot_missing,
    }
