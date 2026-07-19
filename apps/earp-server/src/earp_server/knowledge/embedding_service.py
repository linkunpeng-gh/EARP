"""Embedding generation + pgvector storage. M4: pseudo-embedding (random 1536d)."""

from __future__ import annotations

import random

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def embed_chunks(engine: AsyncEngine, tenant_id: str, chunk_ids: list[str]) -> None:
    """Generate embeddings for chunks and UPDATE the chunks.embedding column.

    M4: pseudo-random embedding (1536 dimensions). Phase 2: replace with
    real LLM embedding model (OpenAI text-embedding-ada-002 or local model).
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        for chunk_id in chunk_ids:
            # pseudo-embedding: random unit-length 1536d vector
            vec = [random.uniform(-1, 1) for _ in range(1536)]
            norm = sum(v * v for v in vec) ** 0.5
            normalized = [v / norm for v in vec]
            embedding_str = f"[{', '.join(str(x) for x in normalized)}]"
            await conn.execute(
                text("UPDATE chunks SET embedding = :emb::vector(1536) WHERE chunk_id = :cid"),
                {"emb": embedding_str, "cid": chunk_id},
            )
        await conn.commit()


async def embed_query(query: str) -> list[float]:
    """Generate embedding for a search query. M4: same pseudo-random as embed_chunks."""
    vec = [random.uniform(-1, 1) for _ in range(1536)]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]
