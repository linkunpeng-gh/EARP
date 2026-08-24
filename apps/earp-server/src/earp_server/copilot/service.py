"""Copilot service — SSE streaming endpoint for AI configuration assistance.

This module provides the core copilot functionality:
1. Receive user query + page context + form state
2. Retrieve relevant KB content
3. Call LLM with assembled context
4. Stream response back via SSE
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from earp_server.copilot.context_builder import build_copilot_context, format_kb_results

logger = logging.getLogger(__name__)


def _sse(obj: dict[str, Any]) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


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
) -> AsyncGenerator[str, None]:
    """SSE generator for copilot assist endpoint.

    Yields SSE-formatted strings:
        data: {"type": "token", "content": "<tok>"}
        data: {"type": "sources", "items": [...]}
        data: {"type": "done", "conversation_id": "..."}
        data: {"type": "error", "message": "..."}
    """
    try:
        # 1. Knowledge base retrieval
        kb_context_str = ""
        kb_results: list[dict[str, Any]] = []
        try:
            from earp_server.knowledge.embedding_service import embed_query
            from earp_server.knowledge.search_service import search_chunks

            q_emb = await embed_query(query)

            # Search across all accessible KBs for this tenant
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

        # 4. Stream LLM response
        async for ev in llm.chat_stream(
            system=ctx["system_prompt"],
            history=[],
            query=ctx["user_prompt"],
            temperature=0.3,
            top_p=0.9,
        ):
            yield _sse({"type": "token", "content": ev.token})

        # 5. Done
        yield _sse({"type": "done", "conversation_id": conversation_id or ""})

    except Exception as exc:
        logger.exception("copilot_assist: error")
        yield _sse({"type": "error", "message": f"AI 助手出错: {exc}"})
