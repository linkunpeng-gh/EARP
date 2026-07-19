"""Scheduler process: DB-driven trigger loop skeleton (idle in M0, real logic in M5)."""

from __future__ import annotations

import asyncio
import logging
import signal

from earp_server.config import Settings
from earp_server.infra.ext import init_all

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0


async def _run() -> int:
    settings = Settings()
    init_all(settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("scheduler started (idle loop, M0)")
    ticks = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            ticks += 1
            if ticks % 30 == 0:
                logger.info("scheduler heartbeat")
    logger.info("scheduler stopping (signal)")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
