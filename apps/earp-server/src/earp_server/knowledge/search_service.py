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
    data_domain_ids: list[str] | None = None,
    eventbus: EventBus | None = None,
    *,
    embedding_dim: int = 1024,
) -> list[dict]:
    """Cosine similarity search over chunks, filtered by data_domain + accessible_roles."""
    embedding_str = f"[{', '.join(str(x) for x in query_embedding)}]"
    conditions = ["c.tenant_id = :tid"]
    params: dict = {"qemb": embedding_str, "qemb2": embedding_str, "tid": tenant_id, "rid": role_id, "lim": top_k}

    # Data Domain filter (optional — None = no filter, backward compatible)
    if data_domain_ids:
        conditions.append("(kb.data_domain_id = ANY(:ddids) OR kb.data_domain_id IS NULL)")
        params["ddids"] = data_domain_ids

    # accessible_roles filter
    conditions.append("(kb.accessible_roles IS NULL OR kb.accessible_roles = '{}' OR :rid = ANY(kb.accessible_roles))")

    where_clause = " AND ".join(conditions)
    search_sql = (
        f"SELECT c.chunk_id, c.document_id, c.content, c.chunk_index, "
        f"d.data_classification, "
        f"1 - (c.embedding <=> CAST(:qemb AS vector({embedding_dim}))) AS similarity "
        f"FROM chunks c "
        f"JOIN documents d ON c.document_id = d.document_id "
        f"JOIN knowledge_bases kb ON d.knowledge_base_id = kb.knowledge_base_id "
        f"WHERE {where_clause} "
        f"ORDER BY c.embedding <=> CAST(:qemb2 AS vector({embedding_dim})) LIMIT :lim"
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            rows = await conn.execute(
                text(search_sql),
                params,
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
