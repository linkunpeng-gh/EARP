"""Chatflow F4 — flow_runs 执行状态持久化 service（挂起/恢复 CRUD + 超时扫描）。

flow_runs（0026）是「可挂起/恢复」的载体：human_approval 节点挂起时 pool 序列化
落库（node_state + pending_node_id），用户下一轮消息恢复继续执行。纯 DB 层——
pool 序列化辅助（serialize_pool/deserialize_pool）在 orchestrator.workflow_dsl
（StepResult 在 orchestrator 内部，避免 conversation→orchestrator 跨域）。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session

logger = logging.getLogger(__name__)

_COLS = (
    "execution_id, tenant_id, chat_app_id, conversation_id, status, pending_node_id, "
    "node_state, flow_input, attempts, created_at, updated_at, finished_at"
)


async def create_run(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    execution_id: str,
    chat_app_id: str,
    conversation_id: str,
    flow_input: dict[str, Any],
) -> None:
    """新建 run（status=running）。同 conversation 的 waiting_human run 唯一由 D6 保证。"""
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO flow_runs (execution_id, tenant_id, chat_app_id, conversation_id, "
                "status, flow_input) VALUES (:eid, :tid, :app, :cid, 'running', :input)"
            ),
            {
                "eid": execution_id,
                "tid": tenant_id,
                "app": chat_app_id,
                "cid": conversation_id,
                "input": json.dumps(flow_input, ensure_ascii=False),
            },
        )


async def get_waiting_run(engine: AsyncEngine, tenant_id: str, conversation_id: str) -> dict[str, Any] | None:
    """同 conversation 的最新 waiting_human run（D6：有则视为恢复输入，唯一性）。"""
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text(
                    f"SELECT {_COLS} FROM flow_runs WHERE tenant_id = :tid AND conversation_id = :cid "
                    "AND status = 'waiting_human' ORDER BY updated_at DESC LIMIT 1"
                ),
                {"tid": tenant_id, "cid": conversation_id},
            )
        ).mappings().first()
    return _row_to_dict(row) if row else None


async def update_waiting(
    engine: AsyncEngine,
    tenant_id: str,
    execution_id: str,
    *,
    pending_node_id: str | None,
    node_state: dict[str, Any],
    attempts: int,
) -> None:
    """挂起/恢复后更新 run（复用同一 execution_id——conversation 的 waiting_human 始终唯一）。"""
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "UPDATE flow_runs SET status = 'waiting_human', pending_node_id = :pid, "
                "node_state = :ns, attempts = :att, updated_at = now() "
                "WHERE execution_id = :eid AND tenant_id = :tid"
            ),
            {
                "pid": pending_node_id,
                "ns": json.dumps(node_state, ensure_ascii=False),
                "att": attempts,
                "eid": execution_id,
                "tid": tenant_id,
            },
        )


async def finish_run(engine: AsyncEngine, tenant_id: str, execution_id: str, *, status: str) -> None:
    """终态化（completed/failed/timeout/cancelled）：清 pending_node_id + finished_at。"""
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "UPDATE flow_runs SET status = :st, pending_node_id = NULL, updated_at = now(), "
                "finished_at = now() WHERE execution_id = :eid AND tenant_id = :tid"
            ),
            {"st": status, "eid": execution_id, "tid": tenant_id},
        )


async def expire_waiting_approvals(engine: AsyncEngine, ttl_seconds: int) -> list[dict[str, Any]]:
    """超时扫描（D4）：逐租户将 waiting_human 且 updated_at 超时 → timeout 终态。

    返回被超时 run 列表（调用方负责落库「⏰ 等待超时」消息）。scheduler 循环 + 恢复时
    惰性检查双保险。
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
    timed_out: list[dict[str, Any]] = []
    async with engine.connect() as conn:
        tenants = (await conn.execute(text("SELECT tenant_id FROM tenants"))).fetchall()
    for t in tenants:
        tid = t.tenant_id
        async with tenant_session(engine, tid) as session:
            expired = (
                await session.execute(
                    text(
                        f"SELECT {_COLS} FROM flow_runs WHERE tenant_id = :tid "
                        "AND status = 'waiting_human' AND updated_at < :cutoff"
                    ),
                    {"tid": tid, "cutoff": cutoff},
                )
            ).mappings().all()
            for r in expired:
                await session.execute(
                    text(
                        "UPDATE flow_runs SET status = 'timeout', pending_node_id = NULL, "
                        "updated_at = now(), finished_at = now() WHERE execution_id = :eid"
                    ),
                    {"eid": r["execution_id"]},
                )
                timed_out.append(_row_to_dict(r))
    if timed_out:
        logger.info("expire_waiting_approvals: %d run(s) timed out", len(timed_out))
    return timed_out


def _row_to_dict(r) -> dict[str, Any]:
    d = dict(r)
    for k in ("node_state", "flow_input"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                d[k] = {}
    return d
