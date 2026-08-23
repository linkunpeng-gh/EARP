"""Embedding generation — delegates to the active EmbeddingProvider.

Provider is set at startup via init_embedding_provider() in ext_embedding.py.
This service handles batch orchestration: read chunks from DB → embed → update.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.ext.ext_embedding import get_embedding_provider

logger = logging.getLogger(__name__)

_BATCH_SIZE = 32


async def embed_chunks(
    engine: AsyncEngine,
    tenant_id: str,
    chunk_ids: list[str],
) -> None:
    """Generate embeddings for chunks and UPDATE chunks.embedding."""
    if not chunk_ids:
        return
    provider = get_embedding_provider()
    dim = provider.dim

    # 1. Read chunk contents
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        placeholders = ", ".join(f":cid{i}" for i in range(len(chunk_ids)))
        params = {f"cid{i}": cid for i, cid in enumerate(chunk_ids)}
        result = await conn.execute(
            text(f"SELECT chunk_id, content FROM chunks WHERE chunk_id IN ({placeholders})"),
            params,
        )
        rows = result.fetchall()

    if not rows:
        logger.warning("embed_chunks: no rows for %d chunk_ids", len(chunk_ids))
        return

    chunk_map = {row.chunk_id: row.content for row in rows}
    texts = [chunk_map[cid] for cid in chunk_ids if cid in chunk_map]

    # 2. Batch-embed
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        batch_embs = await provider.embed(batch)
        all_embeddings.extend(batch_embs)

    if len(all_embeddings) != len(texts):
        raise RuntimeError(f"Embedding count mismatch: got {len(all_embeddings)}, expected {len(texts)}")

    # 3. Update DB
    emb_iter = iter(all_embeddings)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        for cid, _text_content in zip(chunk_ids, texts, strict=False):
            if cid not in chunk_map:
                continue
            emb = next(emb_iter)
            emb_str = f"[{', '.join(str(x) for x in emb)}]"
            await conn.execute(
                text(f"UPDATE chunks SET embedding = CAST(:emb AS vector({dim})) WHERE chunk_id = :cid"),
                {"emb": emb_str, "cid": cid},
            )
        await conn.commit()
    logger.info("embed_chunks: embedded %d chunks (provider=%s, dim=%d)", len(all_embeddings), provider.name, dim)


_EMB_CACHE: OrderedDict[str, list[float]] = OrderedDict()
_EMB_CACHE_MAX = 256


async def embed_query(query: str) -> list[float]:
    """Generate embedding for a single search query（带内存 LRU 缓存）。

    同文本不重复调 provider——QU/plan_relation 循环里反复 embed 相同片段直接命中；
    缓存键含文本即可（同 provider 下 embedding 是文本的纯函数）。
    """
    hit = _EMB_CACHE.get(query)
    if hit is not None:
        _EMB_CACHE.move_to_end(query)
        return hit
    provider = get_embedding_provider()
    embs = await provider.embed([query])
    vec = embs[0]
    _EMB_CACHE[query] = vec
    _EMB_CACHE.move_to_end(query)
    if len(_EMB_CACHE) > _EMB_CACHE_MAX:
        _EMB_CACHE.popitem(last=False)
    return vec
