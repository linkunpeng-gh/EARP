"""Worker process: runs the TaskQueue worker until SIGTERM/SIGINT."""

from __future__ import annotations

import asyncio
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

        # T1: 注册业务任务（eval.run 等）——worker 消费队列前必须注册
        from earp_server.ontology import eval_jobs

        eval_jobs.register(queue)

        # T1 D2: stale 恢复——进程中断遗留的 running 僵尸标 failed（interrupted）。
        # 心跳新鲜的在跑任务不动；cancelled/completed/failed 不碰。
        from earp_server.infra.db import build_engine
        from earp_server.ontology import eval_service

        engine = build_engine(settings)
        try:
            n = await eval_service.recover_stale_runs(engine, ttl_seconds=settings.eval_run_ttl)
            if n:
                logger.warning("stale recovery: %d eval runs marked failed (interrupted)", n)
        except Exception:  # noqa: BLE001 — 恢复失败不阻塞 worker 启动
            logger.exception("recover_stale_runs failed — continuing")
        finally:
            await engine.dispose()

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        worker = asyncio.create_task(queue.run_worker(concurrency=4))
        logger.info("worker started")
        await stop.wait()
        logger.info("worker stopping (signal)")
        worker.cancel()
        try:
            await asyncio.wait_for(worker, timeout=3)
        except (asyncio.CancelledError, TimeoutError):
            pass
    finally:
        try:
            await asyncio.wait_for(queue.close(), timeout=2)
        except TimeoutError:
            logger.warning("queue.close() timed out")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
