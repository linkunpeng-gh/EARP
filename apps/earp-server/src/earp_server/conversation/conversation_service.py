"""Conversation CRUD — create, list, get messages + 会话上下文（C 系列）。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

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
        # 会话元数据（C 系列）：message_count + last_active_at 由 add_message 单一维护
        # （与 context 写入解耦——审批「确认」等无实体轮次照常更新元数据）
        await conn.execute(
            text(
                "UPDATE conversations SET message_count = message_count + 1, "
                "last_active_at = now() WHERE conversation_id = :cid"
            ),
            {"cid": conversation_id},
        )
        await conn.commit()
    return {"message_id": msg_id}


async def get_messages(
    engine: AsyncEngine,
    tenant_id: str,
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
    *,
    role_id: str | None = None,
    is_admin: bool = False,
) -> list[dict]:
    # C 系列（Task 5 D5）：会话查询统一走 chat_app 可见性——应用不可见 → 其对话不可枚举
    # （防「应用隐藏但对话可枚举」缝隙）；直建会话（chat_app_id NULL）不受此约束
    if not is_admin and not await _conversation_visible(engine, tenant_id, conversation_id, role_id or ""):
        return []
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
    *,
    role_id: str | None = None,
    is_admin: bool = False,
) -> list[dict]:
    """Conversation list with message count + last message time.

    P1 问答链路一期新增端点（设计 §4.2 Q1）——对话日志与二期应用形态的数据源。
    应用中心：可选按 chat_app_id（运行页会话历史按智能体维度）与 user_id 过滤。
    C 系列（Task 5 D5）：会话查询统一走 chat_app 可见性——应用对角色不可见 →
    其对话不可枚举（防缝隙）；直建会话（chat_app_id NULL）不受应用可见性约束。
    """
    conds = ["c.tenant_id = :tid"]
    params: dict = {"tid": tenant_id, "lim": limit, "off": offset}
    if chat_app_id:
        conds.append("c.chat_app_id = :cid")
        params["cid"] = chat_app_id
    if user_id:
        conds.append("c.user_id = :uid")
        params["uid"] = user_id
    if not is_admin:
        # 与 search_chat_apps 同源可见性谓词（access_mode=open | 角色白名单）
        conds.append(
            "(c.chat_app_id IS NULL OR ca.access_mode = 'open' OR EXISTS "
            "(SELECT 1 FROM app_role_access ar WHERE ar.chat_app_id = c.chat_app_id "
            " AND ar.role_id = :rid AND ar.tenant_id = c.tenant_id))"
        )
        params["rid"] = role_id or ""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT c.conversation_id, c.title, c.chat_app_id, c.user_id, c.created_at, "
                "       count(m.message_id) AS message_count, max(m.created_at) AS last_message_at "
                "FROM conversations c "
                "LEFT JOIN chat_apps ca ON ca.chat_app_id = c.chat_app_id "
                "LEFT JOIN messages m ON m.conversation_id = c.conversation_id "
                "WHERE " + " AND ".join(conds) + " "
                "GROUP BY c.conversation_id, c.title, c.chat_app_id, c.user_id, c.created_at "
                "ORDER BY COALESCE(max(m.created_at), c.created_at) DESC "
                "LIMIT :lim OFFSET :off"
            ),
            params,
        )
        return [dict(r._mapping) for r in rows]


async def _conversation_visible(engine: AsyncEngine, tenant_id: str, conversation_id: str, role_id: str) -> bool:
    """C 系列（Task 5）：会话归属应用对角色是否可见（应用不可见 → 会话不可枚举）。

    直建会话（chat_app_id NULL）恒可见（user_id 隔离由调用方保证）；
    access_mode='open' 全员可见；restricted → 角色白名单（app_role_access）。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text(
                    "SELECT c.chat_app_id, ca.access_mode FROM conversations c "
                    "LEFT JOIN chat_apps ca ON ca.chat_app_id = c.chat_app_id "
                    "WHERE c.conversation_id = :cid"
                ),
                {"cid": conversation_id},
            )
        ).first()
        if row is None:
            return False
        if row.chat_app_id is None or row.access_mode == "open":
            return True
        whitelist = (
            await conn.execute(
                text(
                    "SELECT 1 FROM app_role_access WHERE chat_app_id = :aid "
                    "AND role_id = :rid AND tenant_id = :tid LIMIT 1"
                ),
                {"aid": row.chat_app_id, "rid": role_id, "tid": tenant_id},
            )
        ).first()
        return whitelist is not None


# ── 会话上下文（C 系列 Task 2/3：读写在链路）──────────────────────────────


def _coerce_context(raw: str | dict | None) -> dict:
    """JSONB 防御反序列化（context 列）。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


async def read_conversation_context(
    engine: AsyncEngine,
    tenant_id: str,
    conversation_id: str,
) -> dict:
    """读 conversations.context（C 系列 D3 读时机：指代消解输入）。

    仅取 last-* 结构化块（last_entities/last_intent/last_relations），无则 {}。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text("SELECT context FROM conversations WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
        ).first()
        return _coerce_context(row.context if row is not None else None)


async def update_conversation_context(
    engine: AsyncEngine,
    tenant_id: str,
    conversation_id: str,
    *,
    entities: list[dict] | None = None,
    intent: str | None = None,
    relations: list[dict] | None = None,
) -> None:
    """每轮 chat 结束后 upsert conversations.context（C 系列 D2 写时机）。

    只写「实体非空」轮次（任务书风险 1：审批「确认」等无实体轮次不覆写
    last_entities，防污染）；last_active_at/message_count 由 add_message 维护。
    异常不阻断主链路（上下文写失败不影响回答返回）。
    """
    payload: dict = {}
    if entities:
        payload["last_entities"] = entities
        if intent:
            payload["last_intent"] = intent
        if relations:
            payload["last_relations"] = relations
        payload["updated_at"] = datetime.now(UTC).isoformat()
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            if payload:
                await conn.execute(
                    text(
                        "UPDATE conversations SET context = context || CAST(:ctx AS jsonb) "
                        "WHERE conversation_id = :cid"
                    ),
                    {"ctx": json.dumps(payload, ensure_ascii=False), "cid": conversation_id},
                )
            await conn.commit()
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "update_conversation_context failed (cid=%s)", conversation_id, exc_info=True
        )
