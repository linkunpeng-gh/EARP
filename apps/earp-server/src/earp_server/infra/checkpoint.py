"""Minimal CheckpointStore — writes checkpoints + checkpoint_blobs (M1 single-step).

M5 extends with multi-step, durability modes, writes-table usage.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class CheckpointStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(
        self,
        execution_id: str,
        session_id: str,
        tenant_id: str,
        state: dict,
        channels: dict[str, bytes],
        *,
        checkpoint_ns: str = "",
    ) -> str:
        checkpoint_id = uuid.uuid4().hex
        thread_id = execution_id
        ckpt_ns = checkpoint_ns

        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))

            # checkpoints row (small snapshot)
            await conn.execute(
                text(
                    "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, tenant_id, "
                    "checkpoint, metadata) VALUES (:tid, :ns, :cid, :tenant, :ckpt, '{}')"
                ),
                {"tid": thread_id, "ns": ckpt_ns, "cid": checkpoint_id, "tenant": tenant_id, "ckpt": json.dumps(state)},
            )

            # checkpoint_blobs rows (channel values)
            for channel_name, blob in channels.items():
                await conn.execute(
                    text(
                        "INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, version, "
                        "tenant_id, type, blob) VALUES (:tid, :ns, :ch, '1', :tenant, 'default', :blob)"
                    ),
                    {"tid": thread_id, "ns": ckpt_ns, "ch": channel_name, "tenant": tenant_id, "blob": blob},
                )

            await conn.commit()
        return checkpoint_id

    async def write_writes(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str, tenant_id: str,
        task_id: str, task_path: str, channel: str, value: bytes,
    ) -> None:
        """M5: write a pending write entry to checkpoint_writes table."""
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            await conn.execute(
                text(
                    "INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, "
                    "tenant_id, task_id, task_path, channel, type, value) "
                    "VALUES (:tid, :ns, :cid, :tenant, :task, :path, :ch, 'default', :val)"
                ),
                {
                    "tid": thread_id, "ns": checkpoint_ns, "cid": checkpoint_id, "tenant": tenant_id,
                    "task": task_id, "path": task_path, "ch": channel, "val": value,
                },
            )
            await conn.commit()
