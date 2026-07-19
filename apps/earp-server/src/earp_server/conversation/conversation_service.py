"""Conversation CRUD — create, list, get messages."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def create_conversation(engine: AsyncEngine, tenant_id: str, user_id: str, title: str = "") -> dict:
    conv_id = f"conv-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id, title) "
                "VALUES (:cid, :tid, :uid, :title)"
            ),
            {"cid": conv_id, "tid": tenant_id, "uid": user_id, "title": title},
        )
        await conn.commit()
    return {"conversation_id": conv_id}


async def add_message(
    engine: AsyncEngine, tenant_id: str, conversation_id: str, role: str, content: str, user_id: str,
) -> dict:
    msg_id = f"msg-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO messages (message_id, tenant_id, conversation_id, role, content, user_id) "
                "VALUES (:mid, :tid, :cid, :role, :content, :uid)"
            ),
            {"mid": msg_id, "tid": tenant_id, "cid": conversation_id, "role": role, "content": content, "uid": user_id},
        )
        await conn.commit()
    return {"message_id": msg_id}


async def get_messages(
    engine: AsyncEngine, tenant_id: str, conversation_id: str, limit: int = 50, offset: int = 0,
) -> list[dict]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT message_id, role, content, user_id, created_at FROM messages "
                "WHERE conversation_id = :cid ORDER BY created_at LIMIT :lim OFFSET :off"
            ),
            {"cid": conversation_id, "lim": limit, "off": offset},
        )
        return [dict(r._mapping) for r in rows]
