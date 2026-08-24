"""Conversation CRUD — create, list, get messages."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def create_conversation(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    title: str = "",
    chat_app_id: str | None = None,
) -> dict:
    conv_id = f"conv-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id, title, chat_app_id) "
                "VALUES (:cid, :tid, :uid, :title, :app)"
            ),
            {"cid": conv_id, "tid": tenant_id, "uid": user_id, "title": title, "app": chat_app_id},
        )
        await conn.commit()
    return {"conversation_id": conv_id}


async def add_message(
    engine: AsyncEngine,
    tenant_id: str,
    conversation_id: str,
    role: str,
    content: str,
    user_id: str,
) -> dict:
    msg_id = f"msg-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        # messages.seq is NOT NULL without default — compute next sequence for the conversation
        row = await conn.execute(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = :cid"),
            {"cid": conversation_id},
        )
        next_seq = row.scalar()
        await conn.execute(
            text(
                "INSERT INTO messages (message_id, tenant_id, conversation_id, seq, role, content) "
                "VALUES (:mid, :tid, :cid, :seq, :role, :content)"
            ),
            {
                "mid": msg_id,
                "tid": tenant_id,
                "cid": conversation_id,
                "seq": next_seq,
                "role": role,
                "content": content,
            },
        )
        await conn.commit()
    return {"message_id": msg_id}


async def get_messages(
    engine: AsyncEngine,
    tenant_id: str,
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT message_id, seq, role, content, citations, created_at FROM messages "
                "WHERE conversation_id = :cid ORDER BY seq LIMIT :lim OFFSET :off"
            ),
            {"cid": conversation_id, "lim": limit, "off": offset},
        )
        out = []
        for r in rows:
            d = dict(r._mapping)
            # JSONB 防御反序列化（citations 引用数组）
            if isinstance(d.get("citations"), str):
                import json

                try:
                    d["citations"] = json.loads(d["citations"])
                except (TypeError, ValueError):
                    d["citations"] = None
            out.append(d)
        return out


async def list_conversations(
    engine: AsyncEngine,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    chat_app_id: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    """Conversation list with message count + last message time.

    P1 问答链路一期新增端点（设计 §4.2 Q1）——对话日志与二期应用形态的数据源。
    应用中心：可选按 chat_app_id（运行页会话历史按智能体维度）与 user_id 过滤。
    """
    conds = ["c.tenant_id = :tid"]
    params: dict = {"tid": tenant_id, "lim": limit, "off": offset}
    if chat_app_id:
        conds.append("c.chat_app_id = :cid")
        params["cid"] = chat_app_id
    if user_id:
        conds.append("c.user_id = :uid")
        params["uid"] = user_id
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT c.conversation_id, c.title, c.chat_app_id, c.user_id, c.created_at, "
                "       count(m.message_id) AS message_count, max(m.created_at) AS last_message_at "
                "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.conversation_id "
                "WHERE " + " AND ".join(conds) + " "
                "GROUP BY c.conversation_id, c.title, c.chat_app_id, c.user_id, c.created_at "
                "ORDER BY COALESCE(max(m.created_at), c.created_at) DESC "
                "LIMIT :lim OFFSET :off"
            ),
            params,
        )
        return [dict(r._mapping) for r in rows]
