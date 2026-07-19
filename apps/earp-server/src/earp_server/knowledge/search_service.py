"""pgvector similarity search with accessible_roles filtering."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import CloudEvent, EventBus

logger = logging.getLogger(__name__)


async def search_chunks(
    engine: AsyncEngine,
    tenant_id: str,
    query_embedding: list[float],
    role_id: str,
    top_k: int = 5,
    eventbus: EventBus | None = None,
) -> list[dict]:
    """Cosine similarity search over chunks, filtered by accessible_roles."""
    embedding_str = f"[{', '.join(str(x) for x in query_embedding)}]"
    search_sql = (
        "SELECT c.chunk_id, c.document_id, c.content, c.chunk_index, "
        "1 - (c.embedding <=> :qemb::vector(1536)) AS similarity "
        "FROM chunks c "
        "JOIN documents d ON c.document_id = d.document_id "
        "JOIN knowledge_bases kb ON d.knowledge_base_id = kb.knowledge_base_id "
        "WHERE c.tenant_id = :tid "
        "AND (kb.accessible_roles IS NULL OR kb.accessible_roles = '{}' OR :rid = ANY(kb.accessible_roles)) "
        "ORDER BY c.embedding <=> :qemb2::vector(1536) LIMIT :lim"
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            rows = await conn.execute(
                text(search_sql),
                {"qemb": embedding_str, "qemb2": embedding_str, "tid": tenant_id, "rid": role_id, "lim": top_k},
            )
            return [dict(r._mapping) for r in rows]
    except Exception:
        logger.exception("search_chunks failed")
        if eventbus:
            eventbus.publish(
                CloudEvent(
                    type="earp.retrieval.failed",
                    source="earp-server/knowledge",
                    tenant_id=tenant_id,
                    data={"role_id": role_id, "top_k": top_k},
                )
            )
        return []
