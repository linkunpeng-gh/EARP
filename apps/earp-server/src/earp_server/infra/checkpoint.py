"""Minimal CheckpointStore — writes checkpoints + checkpoint_blobs (M1 single-step).

M5 extends with multi-step, durability modes, writes-table usage.
"""

from __future__ import annotations

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
    ) -> str:
        checkpoint_id = uuid.uuid4().hex
        thread_id = execution_id
        ckpt_ns = ""

        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))

            # checkpoints row (small snapshot)
            await conn.execute(
                text(
                    "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, tenant_id, "
                    "checkpoint, metadata) VALUES (:tid, :ns, :cid, :tenant, :ckpt, '{}')"
                ),
                {"tid": thread_id, "ns": ckpt_ns, "cid": checkpoint_id, "tenant": tenant_id, "ckpt": state},
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
