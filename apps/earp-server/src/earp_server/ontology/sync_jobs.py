"""M3 B2 — 中台同步任务注册到 Procrastinate 队列（worker 消费）。

同步是触发型 + 重负载（批量 upsert），queue + 心跳 + 卡死恢复（T1 模式）：
- 任务名 "ontology.sync_data_source"，payload {tenant_id, data_source_id}
- worker 侧 Settings() 构造 engine（与 worker 进程同 env），job 内：
  running 状态 + 每 50 行心跳（last_synced_at 刷新）→ sync_from_connector → completed/failed
- 卡死恢复（recover_interrupted_sync）：下次触发时前次 running 且心跳旧
  （EARP_SYNC_RUN_TTL 默认 1800s）→ 标 interrupted 再开始；心跳新鲜 → 并发 409
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from earp_server.config import Settings
from earp_server.infra.db import build_engine
from earp_server.infra.task_queue import ProcrastinateTaskQueue
from earp_server.ontology import import_service

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def recover_interrupted_sync(engine, tenant_id: str, data_source_id: str, ttl_seconds: int) -> bool:
    """卡死恢复（B2）：前次 running 且心跳旧 → 标 interrupted，返回 True；
    running 但心跳新鲜（并发在跑）→ 返回 False（调用方 409）；非 running → False。"""
    ds = await import_service.get_data_source(engine, tenant_id, data_source_id)
    if ds is None or ds["last_sync_status"] != "running" or not ds["last_synced_at"]:
        return False
    last = datetime.fromisoformat(ds["last_synced_at"])
    if (datetime.now(UTC) - last).total_seconds() > ttl_seconds:
        await import_service.mark_sync_state(engine, tenant_id, data_source_id, status="interrupted")
        return True
    return False


def register(queue: ProcrastinateTaskQueue) -> None:
    """注册 ontology.sync_data_source 任务（worker 侧调用；API 进程只 enqueue 不注册）。"""

    @queue.task(name="ontology.sync_data_source")
    async def sync_data_source_job(tenant_id: str, data_source_id: str) -> None:
        settings = Settings()
        engine = build_engine(settings)

        async def _beat() -> None:
            await import_service.mark_sync_state(engine, tenant_id, data_source_id, status="running")

        try:
            await import_service.mark_sync_state(
                engine, tenant_id, data_source_id, status="running", synced_at=_now()
            )
            await import_service.sync_from_connector(
                engine, tenant_id, data_source_id, heartbeat=_beat
            )
            await import_service.mark_sync_state(
                engine, tenant_id, data_source_id, status="completed", synced_at=_now()
            )
        except Exception:  # noqa: BLE001 — 取数失败/异常 → 状态 failed，不重试风暴
            logger.exception("sync %s failed", data_source_id)
            try:
                await import_service.mark_sync_state(
                    engine, tenant_id, data_source_id, status="failed"
                )
            except Exception:  # noqa: BLE001
                logger.exception("mark sync failed state failed")
        finally:
            await engine.dispose()
