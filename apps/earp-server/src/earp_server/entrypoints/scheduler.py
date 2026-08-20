"""Scheduler process: DB-driven trigger loop + enrichment (tech-debt #11 D3 → M3 D2).

- 心跳 loop（原 idle，M0）
- 每 ENRICHMENT_INTERVAL_SECONDS（默认 3600s，ENV EARP_ENRICHMENT_INTERVAL_SECONDS）
  对每个租户执行 enrichment 全流程（M3 D2）：
  ④ profile 重编（stale）→ ③ 失效事实清理（valid_to 过期 revoke）→
  ① timeline 回填（executions.result citations）→ ② 热度报告。
  Enrichment 走 scheduler 循环（D4 决策：周期扫描型与队列任务无增量收益；
  同步任务才是 queue 消费）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

from earp_server.config import Settings
from earp_server.infra.ext import init_all

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0
ENRICHMENT_INTERVAL_SECONDS = float(os.environ.get("EARP_ENRICHMENT_INTERVAL_SECONDS", "3600"))
# Chatflow F4: human_approval 等待超时扫描间隔（惰性检查在恢复时兜底，双保险）
APPROVAL_SCAN_INTERVAL_SECONDS = float(os.environ.get("EARP_APPROVAL_SCAN_INTERVAL_SECONDS", "60"))


async def _expire_approvals_once(engine) -> int:
    """F4: 逐租户超时扫描——waiting_human 超时 → timeout 终态 + 超时消息落库。返回超时数。"""
    from sqlalchemy import text

    from earp_server.conversation import flow_runs
    from earp_server.conversation.conversation_service import add_message

    ttl = int(os.environ.get("EARP_APPROVAL_TTL", "3600"))
    expired = await flow_runs.expire_waiting_approvals(engine, ttl)
    for run in expired:
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{run['tenant_id']}'"))
                row = (
                    await conn.execute(
                        text("SELECT user_id FROM conversations WHERE conversation_id = :cid"),
                        {"cid": run["conversation_id"]},
                    )
                ).first()
            if row:
                await add_message(
                    engine,
                    run["tenant_id"],
                    run["conversation_id"],
                    "assistant",
                    "⏰ 等待超时，流程终止",
                    row.user_id,
                )
        except Exception:
            logger.warning("approval timeout: message persist failed for %s", run.get("execution_id"), exc_info=True)
    return len(expired)


async def _run_enrichment_once(engine) -> dict:
    """所有租户 enrichment 全流程一轮。返回分项统计汇总。"""
    from sqlalchemy import text

    from earp_server.ontology import enrichment

    async with engine.connect() as conn:
        tenants = (await conn.execute(text("SELECT tenant_id FROM tenants"))).fetchall()
    total = {"profiles_recompiled": 0, "facts_revoked": 0, "timeline_added": 0}
    for t in tenants:
        tid = t.tenant_id
        try:
            stats = await enrichment.enrichment_run(engine, tid)
        except Exception:
            logger.warning("enrichment: run failed for %s", tid, exc_info=True)
            continue
        for k in total:
            total[k] += stats.get(k, 0)
    return total


async def _run() -> int:
    settings = Settings()
    init_all(settings)
    from earp_server.infra.db import build_engine

    engine = build_engine(settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("scheduler started (heartbeat + enrichment every %ss)", ENRICHMENT_INTERVAL_SECONDS)
    ticks = 0
    last_enrichment = 0.0
    last_approval_scan = 0.0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            ticks += 1
            now = time.monotonic()
            if now - last_enrichment >= ENRICHMENT_INTERVAL_SECONDS:
                last_enrichment = now
                try:
                    total = await _run_enrichment_once(engine)
                    logger.info("enrichment: %s", total)
                except Exception:
                    logger.exception("enrichment failed")
            if now - last_approval_scan >= APPROVAL_SCAN_INTERVAL_SECONDS:
                last_approval_scan = now
                try:
                    expired = await _expire_approvals_once(engine)
                    if expired:
                        logger.info("approval timeout scan: %d run(s) expired", expired)
                except Exception:
                    logger.exception("approval timeout scan failed")
            if ticks % 30 == 0:
                logger.info("scheduler heartbeat")
    logger.info("scheduler stopping (signal)")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
