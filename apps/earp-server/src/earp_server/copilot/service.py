"""Copilot service — SSE streaming endpoint for AI configuration assistance.

This module provides the core copilot functionality:
1. Receive user query + page context + form state
2. Retrieve relevant KB content
3. Call LLM with assembled context
4. Stream response back via SSE
5. Persist conversation history (multi-turn)
6. Emit audit events for every interaction
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from earp_server.copilot.context_builder import build_copilot_context, format_kb_results

logger = logging.getLogger(__name__)

# ── 6.1: Copilot knowledge base constants ─────────────────────────────────────
COPILOT_KB_NAME = "EARP 配置助手知识库"
COPILOT_KB_DESC = "EARP 管理后台配置指南，供 AI 配置助手（Copilot）RAG 检索使用"
_COPILOT_KB_ID: str | None = None  # cached after first creation


# ── 6.1: Ensure copilot KB exists and upload config guide ─────────────────────
async def ensure_copilot_kb(engine: Any, tenant_id: str) -> str | None:
    """Ensure the copilot knowledge base exists and contains the config guide.

    Returns the knowledge_base_id, or None on failure.
    """
    global _COPILOT_KB_ID
    if _COPILOT_KB_ID:
        return _COPILOT_KB_ID

    try:
        from earp_server.knowledge.admin_service import create_kb, list_kbs
        from earp_server.knowledge.document_service import create_document, find_duplicate
        from earp_server.knowledge.chunk_service import create_chunks
        from earp_server.knowledge.embedding_service import embed_chunks
        from earp_server.knowledge.routing import build_routing_index

        # Check if copilot KB already exists
        kbs = await list_kbs(engine, tenant_id)
        existing = [k for k in kbs if k["name"] == COPILOT_KB_NAME]
        if existing:
            _COPILOT_KB_ID = existing[0]["knowledge_base_id"]
            logger.info("ensure_copilot_kb: found existing KB %s", _COPILOT_KB_ID)
            return _COPILOT_KB_ID

        # Create the copilot KB
        kb = await create_kb(
            engine,
            tenant_id,
            name=COPILOT_KB_NAME,
            description=COPILOT_KB_DESC,
            retrieval_model={
                "segmentation": {"separator": "\n\n", "max_tokens": 1000, "chunk_overlap": 200},
                "mode": "hybrid",
                "top_k": 5,
                "score_threshold": 0.3,
            },
        )
        _COPILOT_KB_ID = kb["knowledge_base_id"]
        logger.info("ensure_copilot_kb: created KB %s", _COPILOT_KB_ID)

        # Upload the config guide document
        guide_content = _load_config_guide()
        if guide_content:
            doc = await create_document(
                engine,
                tenant_id,
                _COPILOT_KB_ID,
                content=guide_content,
                title="EARP 平台配置指南",
                data_classification="internal",
            )
            chunk_ids = await create_chunks(engine, tenant_id, doc["document_id"], guide_content)
            if chunk_ids:
                await embed_chunks(engine, tenant_id, chunk_ids)
            await build_routing_index(engine, tenant_id, kb_ids=[_COPILOT_KB_ID])
            logger.info("ensure_copilot_kb: uploaded config guide, %d chunks", len(chunk_ids))

        return _COPILOT_KB_ID

    except Exception:
        logger.exception("ensure_copilot_kb: failed to create/setup copilot KB")
        return None


def _load_config_guide() -> str:
    """Load the copilot config guide content from the docs directory."""
    import pathlib

    candidates = [
        pathlib.Path(__file__).resolve().parents[4] / "docs" / "copilot-config-guide.md",
        pathlib.Path(__file__).resolve().parents[3] / "docs" / "copilot-config-guide.md",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8")
    logger.warning("_load_config_guide: copilot-config-guide.md not found")
    return ""


# ── 6.2: Conversation persistence helpers ──────────────────────────────────────
async def _get_or_create_conversation(
    engine: Any, tenant_id: str, user_id: str, conversation_id: str | None
) -> str:
    """Return conversation_id (existing or newly created)."""
    from earp_server.conversation.conversation_service import create_conversation

    if conversation_id:
        return conversation_id

    conv = await create_conversation(engine, tenant_id, user_id, title="Copilot 对话")
    return conv["conversation_id"]


async def _save_message(
    engine: Any, tenant_id: str, conversation_id: str, role: str, content: str, user_id: str
) -> None:
    """Persist a single message to the conversation."""
    try:
        from earp_server.conversation.conversation_service import add_message

        await add_message(engine, tenant_id, conversation_id, role, content, user_id)
    except Exception:
        logger.warning("_save_message: failed to save %s message", role, exc_info=True)


async def _load_history(
    engine: Any, tenant_id: str, conversation_id: str, limit: int = 6
) -> list[dict[str, str]]:
    """Load recent conversation history as [{"role": ..., "content": ...}, ...]."""
    try:
        from earp_server.conversation.conversation_service import get_messages

        msgs = await get_messages(engine, tenant_id, conversation_id, limit=limit)
        return [{"role": m["role"], "content": m["content"]} for m in msgs]
    except Exception:
        logger.warning("_load_history: failed for %s", conversation_id, exc_info=True)
        return []


# ── 6.3: Audit event helper ────────────────────────────────────────────────────
async def _emit_copilot_audit(
    engine: Any,
    tenant_id: str,
    user_id: str,
    page_id: str,
    intent: str,
    query: str,
    conversation_id: str,
    token_count: int,
) -> None:
    """Emit a copilot interaction audit event to the EventBus."""
    try:
        from earp_server.infra.eventbus import CloudEvent, EventBus

        event = CloudEvent(
            type="earp.copilot.interaction",
            source="earp-server/copilot",
            tenant_id=tenant_id,
            data={
                "entity_type": "copilot",
                "entity_id": conversation_id,
                "user_id": user_id,
                "page_id": page_id,
                "intent": intent,
                "query": query[:200],
                "token_count": token_count,
            },
        )
        bus = EventBus()
        bus.publish(event)
    except Exception:
        logger.warning("_emit_copilot_audit: failed to emit event", exc_info=True)


# ── Existing parsers ───────────────────────────────────────────────────────────
def _parse_apply_response(response: str) -> dict[str, Any]:
    """Parse the LLM response into a structured apply plan.

    Returns:
        {"fields": {field_name: value, ...}, "explanation": "..."}
    """
    json_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", response)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.warning("_parse_apply_response: no JSON found in response: %s", response[:200])
            return {"fields": {}, "explanation": "AI 未能生成有效配置方案，请重试。"}

    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            fields = parsed.get("fields", {})
            if not isinstance(fields, dict):
                fields = {}
            explanation = str(parsed.get("explanation", ""))
            clean_fields = {}
            for k, v in fields.items():
                clean_fields[str(k)] = v if isinstance(v, (str, int, float, bool)) else str(v)
            return {"fields": clean_fields, "explanation": explanation}
        else:
            logger.warning("_parse_apply_response: response is not a dict: %s", type(parsed))
            return {"fields": {}, "explanation": "AI 返回格式异常，请重试。"}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("_parse_apply_response: failed to parse JSON: %s", exc)
        return {"fields": {}, "explanation": "AI 返回解析失败，请重试。"}


def _parse_autofill_response(response: str) -> list[dict[str, Any]]:
    """Parse the LLM response into structured autofill suggestions."""
    json_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", response)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_match = re.search(r"\[[\s\S]*\]", response)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.warning("_parse_autofill_response: no JSON found in response: %s", response[:200])
            return []

    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, list):
            valid_suggestions = []
            for item in parsed:
                if isinstance(item, dict) and "field" in item and "value" in item:
                    valid_suggestions.append(
                        {
                            "field": str(item["field"]),
                            "value": item["value"],
                            "confidence": float(item.get("confidence", 0.5)),
                            "reason": str(item.get("reason", "")),
                        }
                    )
            return valid_suggestions
        else:
            logger.warning("_parse_autofill_response: response is not a list: %s", type(parsed))
            return []
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("_parse_autofill_response: failed to parse JSON: %s", exc)
        return []


def _sse(obj: dict[str, Any]) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# ── Main SSE generator ─────────────────────────────────────────────────────────
async def copilot_assist(
    engine: Any,
    tenant_id: str,
    page_id: str,
    form_state: dict[str, Any],
    query: str,
    intent: str,
    llm: Any,
    settings: Any,
    rate_limiter: Any | None = None,
    embedding_dim: int = 1024,
    conversation_id: str | None = None,
    role_id: str = "role-admin",
    user_id: str = "user-copilot",
) -> AsyncGenerator[str, None]:
    """SSE generator for copilot assist endpoint.

    Yields SSE-formatted strings:
        data: {"type": "token", "content": "<tok>"}
        data: {"type": "sources", "items": [...]}
        data: {"type": "done", "conversation_id": "..."}
        data: {"type": "error", "message": "..."}
    """
    token_count = 0
    try:
        # ── 6.2: Resolve conversation and load history ──────────────────────
        conv_id = await _get_or_create_conversation(engine, tenant_id, user_id, conversation_id)
        history = await _load_history(engine, tenant_id, conv_id)

        # Save user message to conversation
        await _save_message(engine, tenant_id, conv_id, "user", query, user_id)

        # ── 6.1: Ensure copilot KB exists (fire-and-forget on first call) ───
        try:
            await ensure_copilot_kb(engine, tenant_id)
        except Exception:
            pass  # non-critical; KB retrieval will still work with other KBs

        # 1. Knowledge base retrieval
        kb_context_str = ""
        kb_results: list[dict[str, Any]] = []
        try:
            from earp_server.knowledge.embedding_service import embed_query
            from earp_server.knowledge.search_service import search_chunks

            q_emb = await embed_query(query)

            from earp_server.knowledge.admin_service import list_data_domains

            dds = await list_data_domains(engine, tenant_id)
            dd_ids = [d["data_domain_id"] for d in dds] if dds else None

            search_results = await search_chunks(
                engine,
                tenant_id,
                q_emb,
                role_id,
                top_k=5,
                data_domain_ids=dd_ids,
                threshold=0.3,
            )

            if search_results:
                kb_results = search_results
                kb_context_str = format_kb_results(search_results)
        except Exception:
            logger.warning("copilot_assist: KB retrieval failed, continuing without KB context", exc_info=True)

        # 2. Build context
        ctx = build_copilot_context(
            page_id=page_id,
            form_state=form_state,
            query=query,
            intent=intent,
            kb_context=kb_context_str,
        )

        # 3. Send sources if we have KB results
        if kb_results:
            sources = [
                {
                    "title": r.get("title", ""),
                    "content": (r.get("content", "") or "")[:200],
                    "knowledge_base_name": r.get("knowledge_base_name", ""),
                    "score": r.get("score", 0),
                }
                for r in kb_results[:5]
            ]
            yield _sse({"type": "sources", "items": sources})

        # 4. Handle autofill/apply intent — collect full response and parse JSON
        logger.info("copilot_assist: intent=%s page_id=%s calling LLM (model=%s)...", intent, page_id, getattr(llm, '_model', 'unknown'))
        if intent in ("autofill", "apply"):
            full_response = ""
            async for ev in llm.chat_stream(
                system=ctx["system_prompt"],
                history=history,
                query=ctx["user_prompt"],
                temperature=0.3,
                top_p=0.9,
                max_tokens=1024,
            ):
                full_response += ev.token

            if intent == "autofill":
                suggestions = _parse_autofill_response(full_response)
                yield _sse({"type": "suggestions", "items": suggestions})
            else:
                plan = _parse_apply_response(full_response)
                yield _sse({"type": "apply_plan", "fields": plan["fields"], "explanation": plan["explanation"]})

            # Save assistant response (summary) to conversation
            summary = plan["explanation"] if intent == "apply" else (full_response[:300] if full_response else "")
            await _save_message(engine, tenant_id, conv_id, "assistant", summary, user_id)
        else:
            # Stream LLM response for other intents
            assistant_content = ""
            async for ev in llm.chat_stream(
                system=ctx["system_prompt"],
                history=history,
                query=ctx["user_prompt"],
                temperature=0.3,
                top_p=0.9,
                max_tokens=512,
            ):
                token_count += 1
                assistant_content += ev.token
                yield _sse({"type": "token", "content": ev.token})

            # Save assistant response to conversation
            await _save_message(engine, tenant_id, conv_id, "assistant", assistant_content, user_id)

        # 5. Done
        logger.info("copilot_assist: intent=%s LLM call completed, token_count=%d, sending done", intent, token_count)
        yield _sse({"type": "done", "conversation_id": conv_id})

        # 6.3: Emit audit event
        await _emit_copilot_audit(
            engine, tenant_id, user_id, page_id, intent, query, conv_id, token_count
        )

    except Exception as exc:
        logger.exception("copilot_assist: error")
        yield _sse({"type": "error", "message": f"AI 助手出错: {exc}"})
