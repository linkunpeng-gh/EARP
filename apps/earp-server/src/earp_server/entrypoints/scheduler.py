"""Scheduler process: DB-driven trigger loop + profile enrichment (tech-debt #11 D3).

- 心跳 loop（原 idle，M0）
- 每 ENRICHMENT_INTERVAL_SECONDS（默认 3600s，ENV EARP_ENRICHMENT_INTERVAL_SECONDS）
  扫描所有租户 stale profile（无 profile / compiled_at < last_change）→ 批量重编译。
  规则聚合（非 LLM summary——M2 范畴）。
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


async def _run_enrichment_once(engine) -> int:
    """所有租户 stale profile 重编译一轮。返回重编译实体数。"""
    from sqlalchemy import text

    from earp_server.ontology import abox_service

    async with engine.connect() as conn:
        tenants = (await conn.execute(text("SELECT tenant_id FROM tenants"))).fetchall()
    total = 0
    for t in tenants:
        tid = t.tenant_id
        try:
            stale = await abox_service.find_stale_profiles(engine, tid, max_n=200)
        except Exception:
            logger.warning("enrichment: find_stale_profiles failed for %s", tid, exc_info=True)
            continue
        for eid in stale:
            try:
                await abox_service.compile_profile(engine, tid, eid)
                total += 1
            except Exception:
                logger.warning("enrichment: compile_profile failed for %s/%s", tid, eid, exc_info=True)
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

    logger.info("scheduler started (heartbeat + profile enrichment every %ss)", ENRICHMENT_INTERVAL_SECONDS)
    ticks = 0
    last_enrichment = 0.0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            ticks += 1
            now = time.monotonic()
            if now - last_enrichment >= ENRICHMENT_INTERVAL_SECONDS:
                last_enrichment = now
                try:
                    n = await _run_enrichment_once(engine)
                    logger.info("enrichment: %d profiles recompiled", n)
                except Exception:
                    logger.exception("enrichment failed")
            if ticks % 30 == 0:
                logger.info("scheduler heartbeat")
    logger.info("scheduler stopping (signal)")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
