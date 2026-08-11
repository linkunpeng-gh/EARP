"""Audit worker process: consumes events from Redis Streams → audit_logs table.

Runs independently of the API server. Connects to Redis Streams (same as API
server's EventBus), reads execution events, and persists to PostgreSQL.

Start: make audit-worker
"""

from __future__ import annotations

import asyncio
import logging
import signal

from earp_server.audit.consumer import audit_handler_factory
from earp_server.config import Settings
from earp_server.infra.db import build_engine
from earp_server.infra.ext import init_all
from earp_server.infra.redis_eventbus import RedisStreamsEventBus

logger = logging.getLogger(__name__)


async def _run() -> int:
    settings = Settings()
    init_all(settings)

    engine = build_engine(settings)
    bus = RedisStreamsEventBus()

    # Subscribe audit handler to execution + chat_app events
    # （chat_app 审计：P1 问答链路一期，设计 §4.6 F2）
    bus.subscribe("earp.execution.*", audit_handler_factory(engine))
    bus.subscribe("earp.chat_app.*", audit_handler_factory(engine))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("audit worker starting — consuming from Redis Streams")
    consumer_task = asyncio.create_task(bus.start_consumer())

    await stop.wait()
    logger.info("audit worker stopping (signal)")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    finally:
        await engine.dispose()

    logger.info("audit worker stopped")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
