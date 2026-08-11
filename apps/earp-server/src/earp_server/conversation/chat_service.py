"""chat_service — RAG 问答编排（P1 问答链路一期，设计 §4.3/§4.4/§4.6）。

POST /chat_apps/{app_id}/chat  SSE 流式编排：
  会话创建/续接 → 用户消息先 commit → 多轮 (user,assistant) 配对取 N 对
  → 检索（kb_scope 空=软路由 / 限定 KB 静默过滤）→ 拼提示词（app.system_prompt
  + 结构尾巴含 [N] 编号规则）→ LLM.chat_stream（模型三级解析）→ done 后落库
  助手消息 + citations。

模型三级解析（CP2）：chat_apps.model_config_id → system_model_settings(llm) → env。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.connector import ConnectorError, LLMConnector
from earp_server.knowledge.embedding_service import embed_query
from earp_server.knowledge.routing import route_query
from earp_server.knowledge.search_service import search_chunks

logger = logging.getLogger(__name__)

# 结构尾巴（代码内置不可改，CP3）：引用编号规则 + 内容边界 + 回答要求
_SYSTEM_TAIL = """

【回答规则】
1. 优先依据上方编号资料回答；资料未覆盖时明确说明「知识库中暂无相关内容」，不得编造。
2. 引用资料时在对应句末标注编号，如 [1]；同一资料多次引用可复用编号，编号与资料一一对应。
3. 回答使用中文，简洁清晰。"""

_TITLE_MAX = 30  # 会话标题 = 首问截断长度


class ChatError(Exception):
    """Chat 链路可预期失败（转 SSE error 事件，不产生 500）。"""


# ── 模型三级解析（Task 8 / CP2）───────────────────────────────────────────


async def resolve_llm_override(engine: AsyncEngine, tenant_id: str, app: dict[str, Any]) -> dict[str, Any] | None:
    """chat_apps.model_config_id → system_model_settings(llm) → None(=env)。

    返回 model_override dict（provider/model_name/base_url/api_key…），或 None 表示 env。
    """
    config_id = app.get("model_config_id")
    if not config_id:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = (
                await conn.execute(
                    text(
                        "SELECT model_config_id FROM system_model_settings "
                        "WHERE tenant_id = :tid AND setting_type = 'llm'"
                    ),
                    {"tid": tenant_id},
                )
            ).first()
            config_id = row.model_config_id if row else None
    if not config_id:
        return None
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text(
                    "SELECT provider, model_name, credentials FROM model_configs "
                    "WHERE config_id = :cid AND tenant_id = :tid"
                ),
                {"cid": config_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            return None
        creds = row.credentials or {}
        if isinstance(creds, str):
            try:
                creds = json.loads(creds)
            except (TypeError, ValueError):
                creds = {}
        # model_configs.credentials 加密存储（credential_crypto）——解密后才是 base_url/api_key
        if creds and "ciphertext" in creds:
            from earp_server.infra.credential_crypto import decrypt

            try:
                creds = decrypt(creds)
            except Exception:
                logger.warning("resolve_llm_override: credential decrypt failed, falling back empty")
                creds = {}
        return {"provider": row.provider, "model_name": row.model_name, **creds}


# ── 多轮历史配对（S1）─────────────────────────────────────────────────────


async def _recent_pairs(engine: AsyncEngine, tenant_id: str, conversation_id: str, turns: int) -> list[dict]:
    """按 (user, assistant) 配对取最近 N 对完整轮次；当前用户消息（末尾孤立 user）跳过。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT role, content FROM messages WHERE conversation_id = :cid "
                "ORDER BY seq DESC LIMIT :lim"
            ),
            {"cid": conversation_id, "lim": turns * 4 + 1},
        )
        msgs = list(reversed(rows.fetchall()))

    # 当前问题已落库（末尾 user）—— 不参与历史（chat_stream 会再拼当前 query）
    if msgs and msgs[-1].role == "user":
        msgs = msgs[:-1]

    pairs: list[list[dict]] = []
    i = len(msgs) - 1
    while i >= 1 and len(pairs) < turns:
        if msgs[i].role == "assistant" and msgs[i - 1].role == "user":
            pairs.append(
                [
                    {"role": "user", "content": msgs[i - 1].content},
                    {"role": "assistant", "content": msgs[i].content},
                ]
            )
            i -= 2
        else:
            i -= 1
    pairs.reverse()
    return [m for pair in pairs for m in pair]


# ── 检索与引用（§4.3 ⑤）───────────────────────────────────────────────────


async def _retrieve(
    engine: AsyncEngine,
    tenant_id: str,
    role_id: str,
    query: str,
    q_emb: list[float],
    app: dict[str, Any],
    embedding_dim: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (chunks, citations)。kb_scope 空 → 软路由；否则限定 KB（无权限静默过滤）。

    检索保持原 top_k 语义（chunk 级）；引用去重在展示层做（前端按文档聚合）。
    """
    retrieval = app.get("retrieval") or {}
    top_k = retrieval.get("top_k", 5)
    threshold = retrieval.get("threshold") or 0.0
    mode = retrieval.get("mode", "hybrid")

    kb_scope = app.get("kb_scope") or []
    if kb_scope:
        chunks = await search_chunks(
            engine, tenant_id, q_emb, role_id,
            top_k=top_k, eventbus=None, embedding_dim=embedding_dim,
            knowledge_base_ids=kb_scope, threshold=threshold,
            query_text=query, mode=mode,
        )
    else:
        routed = await route_query(engine, tenant_id, query, q_emb, role_id)
        cand = [kb["knowledge_base_id"] for kb in routed.get("candidate_kbs", [])]
        logger.info("chat soft-routing: query=%r candidates=%s fallback=%s", query, cand, routed.get("fallback_used"))
        chunks = await search_chunks(
            engine, tenant_id, q_emb, role_id,
            top_k=top_k, eventbus=None, embedding_dim=embedding_dim,
            knowledge_base_ids=cand or None, threshold=threshold,
            query_text=query, mode=mode,
        )

    citations = []
    for ch in chunks:
        citations.append(
            {
                "chunk_id": ch.get("chunk_id"),
                "document_id": ch.get("document_id"),
                "title": ch.get("title") or ch.get("doc_name") or "",
                "kb_id": ch.get("kb_id"),
                "kb_name": ch.get("kb_name"),
                "metadata": ch.get("metadata"),
                "similarity": ch.get("similarity"),
            }
        )
    return chunks, citations


def _build_context_block(chunks: list[dict[str, Any]]) -> str:
    """编号资料块（CP3：按返回顺序 [1]..[N]）。"""
    lines = ["【知识资料】"]
    for i, ch in enumerate(chunks, 1):
        src = ch.get("title") or ch.get("doc_name") or ch.get("document_id") or "未命名"
        kb = ch.get("kb_name") or ch.get("kb_id") or ""
        meta = ch.get("metadata") or {}
        meta_txt = ""
        for k in ("version", "year", "doc_type", "department"):
            v = meta.get(k)
            if v not in (None, ""):
                meta_txt += f" {k}={v}"
        lines.append(f"[{i}] 《{src}》（{kb}{meta_txt}）\n{ch.get('content', '')}")
    return "\n\n".join(lines)


# ── 落库 helper ───────────────────────────────────────────────────────────


async def _set_citations(engine: AsyncEngine, tenant_id: str, message_id: str, citations: list[dict]) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text("UPDATE messages SET citations = :cits WHERE message_id = :mid"),
            {"cits": json.dumps(citations), "mid": message_id},
        )
        await conn.commit()


# ── SSE 主编排（§4.3）──────────────────────────────────────────────────────


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def chat_sse(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    role_id: str,
    app: dict[str, Any],
    query: str,
    conversation_id: str | None,
    *,
    base_llm: LLMConnector,
    settings,
    rate_limiter=None,
    embedding_dim: int | None = None,
) -> AsyncGenerator[str, None]:
    """SSE 事件流：token* → done(message_id, citations) | error。"""
    from earp_server.conversation.conversation_service import add_message, create_conversation

    if not (query or "").strip():
        yield _sse({"type": "error", "message": "问题不能为空"})
        return

    try:
        # ② 会话创建/续接（chat_app_id 归属写入）
        if conversation_id:
            async with engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM conversations WHERE conversation_id = :cid"),
                        {"cid": conversation_id},
                    )
                ).first()
            if not exists:
                raise ChatError("会话不存在或不属于当前租户")
        else:
            conv = await create_conversation(
                engine, tenant_id, user_id, query.strip()[:_TITLE_MAX], chat_app_id=app["chat_app_id"]
            )
            conversation_id = conv["conversation_id"]

        # ③ 用户消息先 commit（CP4：SSE 开始前已可见）
        await add_message(engine, tenant_id, conversation_id, "user", query, user_id)

        # ④ 多轮历史（配对）
        turns = int(app.get("context_turns") or 6)
        history = await _recent_pairs(engine, tenant_id, conversation_id, turns)

        # ⑤ 检索
        if embedding_dim is None:
            embedding_dim = getattr(settings, "embedding_dim", 1024)
        q_emb = await embed_query(query)
        chunks, citations = await _retrieve(engine, tenant_id, role_id, query, q_emb, app, embedding_dim)

        # ⑥ 提示词 = app.system_prompt + 结构尾巴；上下文进 user 消息
        system = (app.get("system_prompt") or "").strip() + _SYSTEM_TAIL
        context_block = _build_context_block(chunks)
        user_content = f"{context_block}\n\n用户问题：{query}" if chunks else f"用户问题：{query}"

        # ⑦ LLM：模型三级解析
        override = await resolve_llm_override(engine, tenant_id, app)
        chat_llm = (
            LLMConnector(settings, rate_limiter=rate_limiter, model_override=override)
            if override
            else base_llm
        )

        # ⑧ 流式生成（应用级生成参数：temperature/top_p/max_tokens）
        gen = app.get("generation") or {}
        answer_parts: list[str] = []
        async for ev in chat_llm.chat_stream(
            system,
            history,
            user_content,
            temperature=gen.get("temperature", 0.7),
            top_p=gen.get("top_p", 0.9),
            max_tokens=gen.get("max_tokens"),
        ):
            tok = ev.token
            if tok:
                answer_parts.append(tok)
                yield _sse({"type": "token", "content": tok})

        # 落库助手消息 + citations
        answer = "".join(answer_parts)
        msg = await add_message(engine, tenant_id, conversation_id, "assistant", answer, user_id)
        await _set_citations(engine, tenant_id, msg["message_id"], citations)
        yield _sse(
            {
                "type": "done",
                "message_id": msg["message_id"],
                "conversation_id": conversation_id,
                "citations": citations,
            }
        )
    except (ConnectorError, ChatError) as e:
        logger.warning("chat failed (user msg persisted): %s", e)
        yield _sse({"type": "error", "message": f"回答生成失败：{e}"})
    except Exception:
        logger.exception("chat unexpected error")
        yield _sse({"type": "error", "message": "回答生成失败，请稍后重试"})
