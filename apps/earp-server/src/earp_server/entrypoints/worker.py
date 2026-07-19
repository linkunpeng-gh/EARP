"""Worker process: runs the TaskQueue worker until SIGTERM/SIGINT."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from earp_server.config import Settings
from earp_server.infra.ext import init_all
from earp_server.infra.task_queue import ProcrastinateTaskQueue

logger = logging.getLogger(__name__)


async def _run() -> int:
    settings = Settings()
    init_all(settings)
    queue = ProcrastinateTaskQueue(settings)
    try:
        await queue.open()
        await queue.assert_schema()

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        worker = asyncio.create_task(queue.run_worker(concurrency=4))
        logger.info("worker started")
        await stop.wait()
        logger.info("worker stopping (signal)")
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
    finally:
        await queue.close()
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
