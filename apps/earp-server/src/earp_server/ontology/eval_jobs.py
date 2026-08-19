"""评估跑分后台任务（T1）— 注册到 Procrastinate 队列，worker 进程消费。

背景：跑分原为 API 进程内 asyncio.create_task（进程重启即丢/变僵尸）。
T1 迁移到队列：任务名 "eval.run"，payload {tenant_id, run_id, role_id}；
worker 侧注册（API 进程只 enqueue 不注册）。job 内每 case 更新
heartbeat_at（D2 心跳方案——不用 started_at 一刀切，避免 TTL 误杀
llm 跑分 55min 合法时长）。

async task 支持（D1b）：procrastinate 3.9 worker 为 async 模式
（run_worker_async），spike S1/S3 已用 async def 任务验证（100 任务 /
2 worker 全过 + async SQLAlchemy 会话共存）——无需 asyncio.run 桥接。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.config import Settings
from earp_server.infra.db import build_engine, tenant_session
from earp_server.infra.task_queue import ProcrastinateTaskQueue
from earp_server.ontology import eval_service

logger = logging.getLogger(__name__)


def _make_heartbeat(engine: AsyncEngine, tenant_id: str, run_id: str) -> Callable[[], Awaitable[None]]:
    """每 case 报到：UPDATE eval_runs.heartbeat_at = now()（RLS 逐租户会话）。"""

    async def beat() -> None:
        async with tenant_session(engine, tenant_id) as session:
            await session.execute(
                text("UPDATE eval_runs SET heartbeat_at = now() WHERE run_id = :rid"),
                {"rid": run_id},
            )

    return beat


def register(queue: ProcrastinateTaskQueue) -> None:
    """注册 eval.run 任务（worker 侧调用；API 进程只 enqueue 不注册）。

    job 从 worker 侧 Settings() 构造 engine（与 worker 进程同 env：
    EARP_DATABASE_URL 等）；跑分在 worker 进程调 Ollama/embedding。
    """

    @queue.task(name="eval.run")
    async def run_eval_job(tenant_id: str, run_id: str, role_id: str = "r-all") -> None:
        settings = Settings()
        engine = build_engine(settings)
        try:
            await eval_service.run_eval_task(
                engine,
                tenant_id,
                run_id,
                settings=settings,
                role_id=role_id,
                heartbeat=_make_heartbeat(engine, tenant_id, run_id),
            )
        finally:
            await engine.dispose()
