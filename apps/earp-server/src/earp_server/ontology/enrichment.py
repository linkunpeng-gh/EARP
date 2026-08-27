"""M3 D1 — Enrichment 夜间任务（Phase 2c）：④ profile 重编 → ③ 失效事实清理 →
① timeline 回填 → ② 热度报告。

载体（D4）：scheduler 循环（与 tech-debt #11 的 profile enrichment 合并，同进程同节奏）；
手动触发端点 POST /v1/ontology/enrichment/run（调试/测试）。

- ③ 失效清理（G4）：status='active' AND valid_to < now() → revoke_fact 完整流程
  （timeline + audit + updated_at + 写时失效）→ profile 自动 stale → ④ 下一轮重编；limit 分批 + 幂等
- ① timeline 回填（G2 + review A 修复）：近窗 messages.citations（chat 真实引用落库，
  chat_service:306 UPDATE messages SET citations）→ entity_timeline（event_type 映射 +
  source_ref=message_id 去重）。**executions.result 无生产写入方**（仅 invoke 写 status，
  INSERT 不含 result；plan-debug 不落库）——已移除该死路径，勿加回
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

# G2：citations 源 → timeline event_type 映射（引用溯源到实体行为）
_SOURCE_EVENT = {"profile": "query.entity", "graph": "graph.entity"}


def _extract_entity_refs(raw: object) -> list[tuple[str, str]]:
    """从 citations 素材提取 (entity_id, event_type)。容错两种形状：
    - messages.citations 直接是数组（chat 引用）
    - 含 citations 字段的 dict（兼容 PlanResult 包装）
    """
    citations: list | None = None
    if isinstance(raw, list):
        citations = raw
    elif isinstance(raw, dict):
        for k, v in raw.items():
            if k == "citations":
                cit_raw = v
                if isinstance(cit_raw, list):
                    citations = cit_raw
                break
    refs: list[tuple[str, str]] = []
    for cit in citations or []:
        if not isinstance(cit, dict):
            continue
        eid = cit.get("entity_id")  # type: ignore[reportCallIssue]  # dict[Unknown, Unknown] 泛型限制
        if not eid:
            continue
        event_type = _SOURCE_EVENT.get(cit.get("source"), "query.entity")  # type: ignore[reportCallIssue]
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
            text("SELECT 1 FROM entity_timeline WHERE entity_id = :e AND source_ref = :r AND event_type = :t"),
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
                    "p": json.dumps({"source": "message"}),
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
            (
                await session.execute(
                    text(
                        "SELECT fact_id FROM facts WHERE tenant_id = :t AND status = 'active' "
                        "AND valid_to < now() LIMIT :lim"
                    ),
                    {"t": tenant_id, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
    for r in rows:
        fid = r["fact_id"]
        try:
            await abox_service.revoke_fact(engine, tenant_id, fid, reason="valid_to 过期（enrichment）")
            facts_revoked += 1
        except Exception:  # noqa: BLE001
            logger.warning("enrichment: revoke failed %s", fid, exc_info=True)

    # ① timeline 回填（A 修复：messages.citations 是真实引用源——chat_service 写；
    # executions.result 无生产写入方，已移除）
    async with tenant_session(engine, tenant_id) as session:
        msg_rows = (
            (
                await session.execute(
                    text(
                        "SELECT message_id, created_at, citations FROM messages "
                        "WHERE tenant_id = :t AND citations IS NOT NULL "
                        "AND created_at > now() - make_interval(days => :win) LIMIT :lim"
                    ),
                    {"t": tenant_id, "win": window_days, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
    hot: Counter[str] = Counter()
    for m in msg_rows:
        for eid, event_type in _extract_entity_refs(m["citations"]):
            hot[eid] += 1
            inserted = await _add_timeline_once(engine, tenant_id, eid, event_type, m["message_id"], m["created_at"])
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
