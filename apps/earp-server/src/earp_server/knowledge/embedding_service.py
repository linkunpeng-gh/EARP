"""Embedding generation via Ollama API + pgvector storage.

Uses bge-m3 (1024d) by default. Callers must pass Settings for the
Ollama endpoint URL and model name.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.config import Settings

logger = logging.getLogger(__name__)

# Maximum texts per Ollama /api/embed batch — bge-m3 handles ~512 tokens each,
# so keep batch size conservative to avoid OOM on the Ollama server.
_BATCH_SIZE = 32


async def _ollama_embed(settings: Settings, texts: list[str]) -> list[list[float]]:
    """Call Ollama /api/embed with a list of texts, return embeddings."""
    if not texts:
        return []
    url = f"{settings.ollama_base_url}/api/embed"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                json={"model": settings.ollama_embedding_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]
    except httpx.HTTPError as exc:
        logger.error("Ollama embed failed: %s", exc)
        raise RuntimeError(f"Ollama embedding call failed: {exc}") from exc


async def embed_chunks(
    engine: AsyncEngine,
    tenant_id: str,
    chunk_ids: list[str],
    settings: Settings,
) -> None:
    """Generate embeddings for chunks and UPDATE chunks.embedding via Ollama bge-m3.

    Phase 2: replaces pseudo-random embedding with real bge-m3 (1024d).
    """
    if not chunk_ids:
        return

    # 1. Read chunk contents from DB
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        # Build IN clause with parameterized placeholders (psycopg doesn't
        # support array parameters for IN, so we use executemany-style or
        # build the list ourselves — chunk_ids are trusted internal values).
        placeholders = ", ".join(f":cid{i}" for i in range(len(chunk_ids)))
        params = {f"cid{i}": cid for i, cid in enumerate(chunk_ids)}
        result = await conn.execute(
            text(f"SELECT chunk_id, content FROM chunks WHERE chunk_id IN ({placeholders})"),
            params,
        )
        rows = result.fetchall()

    if not rows:
        logger.warning("embed_chunks: no rows found for %d chunk_ids", len(chunk_ids))
        return

    chunk_contents: dict[str, str] = {row.chunk_id: row.content for row in rows}

    # 2. Batch-embed via Ollama (bge-m3 supports batch)
    texts_to_embed = [chunk_contents[cid] for cid in chunk_ids if cid in chunk_contents]
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts_to_embed), _BATCH_SIZE):
        batch = texts_to_embed[i : i + _BATCH_SIZE]
        batch_embs = await _ollama_embed(settings, batch)
        all_embeddings.extend(batch_embs)

    if len(all_embeddings) != len(texts_to_embed):
        logger.error(
            "embed_chunks: embedding count mismatch — expected %d, got %d",
            len(texts_to_embed), len(all_embeddings),
        )
        raise RuntimeError(
            f"Ollama returned {len(all_embeddings)} embeddings for {len(texts_to_embed)} texts"
        )

    # 3. Update embeddings in DB
    emb_map: dict[str, list[float]] = {}
    emb_idx = 0
    for cid in chunk_ids:
        if cid in chunk_contents and emb_idx < len(all_embeddings):
            emb_map[cid] = all_embeddings[emb_idx]
            emb_idx += 1

    if not emb_map:
        return

    dim = settings.embedding_dim
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        for cid, emb in emb_map.items():
            emb_str = f"[{', '.join(str(x) for x in emb)}]"
            await conn.execute(
                text(f"UPDATE chunks SET embedding = CAST(:emb AS vector({dim})) WHERE chunk_id = :cid"),
                {"emb": emb_str, "cid": cid},
            )
        await conn.commit()

    logger.info("embed_chunks: embedded %d chunks (dim=%d)", len(emb_map), dim)


async def embed_query(query: str, settings: Settings) -> list[float]:
    """Generate embedding for a single search query via Ollama bge-m3."""
    embeddings = await _ollama_embed(settings, [query])
    if not embeddings:
        raise RuntimeError("Ollama returned empty embeddings for query")
    return embeddings[0]
