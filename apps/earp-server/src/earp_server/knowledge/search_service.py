"""pgvector similarity search with accessible_roles filtering.

Modes:
  - vector: pure cosine similarity over chunk embeddings (default)
  - hybrid: Reciprocal Rank Fusion of vector hits + PostgreSQL full-text hits
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import CloudEvent, EventBus

logger = logging.getLogger(__name__)

RRF_K = 60


def _build_conditions(
    params: dict[str, Any],
    *,
    tenant_id: str,
    role_id: str,
    data_domain_ids: list[str] | None,
    knowledge_base_ids: list[str] | None,
    metadata_filters: dict[str, Any] | None = None,
) -> str:
    """Shared WHERE clause for both vector and text lanes (RLS-scoped).

    NOTE: similarity threshold is intentionally NOT here — it applies only to
    the vector lane (see _vector_lane). Exact keyword hits in the text lane are
    strong signals and must never be filtered out by a vector-score threshold.

    metadata_filters uses JSONB containment (d.metadata @> ...) so the
    jsonb_path_ops GIN index on documents.metadata serves it (2026-08-09
    enterprise-retrieval design §4.2 — values must match stored JSON types).
    """
    conditions = ["c.tenant_id = :tid"]
    params["tid"] = tenant_id
    params["rid"] = role_id

    # only enabled documents are retrievable
    conditions.append("d.status = 'active'")

    if metadata_filters:
        conditions.append("d.metadata @> CAST(:mf AS jsonb)")
        params["mf"] = json.dumps(metadata_filters, ensure_ascii=False)

    if knowledge_base_ids:
        conditions.append("kb.knowledge_base_id = ANY(:kbids)")
        params["kbids"] = knowledge_base_ids
    elif data_domain_ids:
        conditions.append("(kb.data_domain_id = ANY(:ddids) OR kb.data_domain_id IS NULL)")
        params["ddids"] = data_domain_ids

    conditions.append(
        "(kb.accessible_roles IS NULL OR kb.accessible_roles = '{}' OR :rid = ANY(kb.accessible_roles))"
    )

    return " AND ".join(conditions)


_SELECT_COLS = (
    "c.chunk_id, c.document_id, d.title, d.name AS doc_name, c.content, c.chunk_index, d.data_classification, "
    "kb.knowledge_base_id AS kb_id, kb.name AS kb_name, d.metadata"
)


async def _vector_lane(
    conn,
    params: dict[str, Any],
    where_clause: str,
    embedding_dim: int,
    embedding_str: str,
    threshold: float | None = None,
) -> list[dict]:
    threshold_sql = ""
    if threshold is not None:
        params["qemb3"] = embedding_str
        params["thr"] = threshold
        threshold_sql = (
            f" AND 1 - (c.embedding <=> CAST(:qemb3 AS vector({embedding_dim}))) >= :thr"
        )
    sql = (
        f"SELECT {_SELECT_COLS}, "
        f"1 - (c.embedding <=> CAST(:qemb AS vector({embedding_dim}))) AS similarity, 0 AS text_score "
        f"FROM chunks c "
        f"JOIN documents d ON c.document_id = d.document_id "
        f"JOIN knowledge_bases kb ON d.knowledge_base_id = kb.knowledge_base_id "
        f"WHERE {where_clause}{threshold_sql} "
        f"ORDER BY c.embedding <=> CAST(:qemb2 AS vector({embedding_dim})) LIMIT :lim"
    )
    rows = await conn.execute(text(sql), params)
    return [dict(r._mapping) for r in rows]


def _tokenize_cn(query: str) -> list[str]:
    """Split a query into keyword tokens: English/number runs + CJK runs.

    CJK runs are kept whole ("入库流程" stays one keyword) so substring
    matching works without a Chinese word segmenter.
    """
    import re

    return [t for t in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", query) if t]


async def _text_lane(
    conn,
    params: dict[str, Any],
    where_clause: str,
    query: str,
) -> list[dict]:
    """Keyword exact/substring lane (CJK-friendly).

    PG's 'simple' FTS doesn't segment Chinese, so plainto_tsquery misses every
    CJK query. Instead: split the query into keywords (EN runs + CJK runs) and
    rank chunks by how many keywords appear verbatim in the content — real
    exact-match signal that complements the semantic vector lane.
    """
    keywords = list(dict.fromkeys(_tokenize_cn(query)))[:10]
    if not keywords:
        return []
    for i, kw in enumerate(keywords):
        params[f"kw{i}"] = kw
    match_conds = " OR ".join(f"position(lower(:kw{i}) in lower(c.content)) > 0" for i in range(len(keywords)))
    score_expr = " + ".join(f"(position(lower(:kw{i}) in lower(c.content)) > 0)::int" for i in range(len(keywords)))
    sql = (
        f"SELECT {_SELECT_COLS}, 0 AS similarity, ({score_expr}) AS text_score "
        f"FROM chunks c "
        f"JOIN documents d ON c.document_id = d.document_id "
        f"JOIN knowledge_bases kb ON d.knowledge_base_id = kb.knowledge_base_id "
        f"WHERE {where_clause} AND ({match_conds}) "
        f"ORDER BY text_score DESC, c.chunk_index LIMIT :lim"
    )
    rows = await conn.execute(text(sql), params)
    return [dict(r._mapping) for r in rows]


def _rrf_merge(ranked_lists: list[list[dict]], top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion over lane results. Keeps lane scores for display:
    similarity from the vector lane, text_score (keyword hits) from the text lane."""
    fused: dict[str, dict] = {}
    for lane in ranked_lists:
        for rank, item in enumerate(lane):
            cid = item["chunk_id"]
            if cid not in fused:
                merged = dict(item)
                merged["rrf_score"] = 0.0
                fused[cid] = merged
            else:
                # merge lane-specific scores (max across lanes)
                if item.get("text_score", 0) > fused[cid].get("text_score", 0):
                    fused[cid]["text_score"] = item["text_score"]
                if item.get("similarity", 0) > fused[cid].get("similarity", 0):
                    fused[cid]["similarity"] = item["similarity"]
            fused[cid]["rrf_score"] += 1.0 / (RRF_K + rank + 1)
    return sorted(fused.values(), key=lambda x: -x["rrf_score"])[:top_k]


async def _rerank_results(
    results: list[dict], query: str, top_k: int, rerank_top_n: int,
) -> list[dict]:
    """Cross-encoder re-rank the recalled candidates (P3).

    Takes top `rerank_top_n` candidates, scores them against the query with the
    configured reranker, re-sorts, returns top_k. Any failure (provider missing /
    upstream error) → original order preserved (graceful degradation).
    """
    try:
        from earp_server.infra.ext.ext_reranker import get_reranker

        reranker = get_reranker()
        if reranker is None:
            return results
        cands = results[:rerank_top_n]
        scores = await reranker.rerank(query, [c["content"] for c in cands])
        for c, s in zip(cands, scores, strict=True):
            c["rerank_score"] = s
        cands.sort(key=lambda x: -(x.get("rerank_score") or 0.0))
        logger.info("rerank: %d/%d candidates scored → top %d", len(cands), len(results), top_k)
        return cands[:top_k]
    except Exception:
        logger.warning("rerank skipped (provider unavailable or failed) — RRF order kept", exc_info=True)
        return results


async def search_chunks(
    engine: AsyncEngine,
    tenant_id: str,
    query_embedding: list[float],
    role_id: str,
    top_k: int = 5,
    data_domain_ids: list[str] | None = None,
    eventbus: EventBus | None = None,
    *,
    embedding_dim: int | None = None,
    knowledge_base_ids: list[str] | None = None,
    threshold: float | None = None,
    query_text: str = "",
    mode: str = "vector",
    metadata_filters: dict[str, Any] | None = None,
    rerank: bool = True,
    rerank_top_n: int = 20,
) -> list[dict]:
    """Search chunks, filtered by scope + accessible_roles.

    Filters (all optional, additive):
      - data_domain_ids: chunks in KBs belonging to these data domains
      - knowledge_base_ids: chunks in these specific KBs (takes precedence)
      - threshold: only return chunks with similarity >= threshold (vector lane)
      - mode: "vector" | "hybrid" (RRF of vector + PostgreSQL full-text lanes)
      - query_text: original query string (required for the hybrid text lane)
      - metadata_filters: JSONB containment filter on documents.metadata
        (values must match stored JSON types; served by the GIN index)
      - rerank: cross-encoder re-rank the recalled candidates (P3). No-op when
        no reranker provider is configured or query_text is empty — RRF-only
        result is returned unchanged (graceful degradation).
    """
    embedding_str = f"[{', '.join(str(x) for x in query_embedding)}]"
    if embedding_dim is None:
        try:
            from earp_server.infra.ext.ext_embedding import embedding_dim as get_dim

            embedding_dim = get_dim()
        except RuntimeError:
            embedding_dim = 1024  # fallback

    logger.info(
        "search_chunks scope: kb_ids=%s dd_ids=%s metadata_filters=%s mode=%s top_k=%d",
        knowledge_base_ids,
        data_domain_ids,
        bool(metadata_filters),
        mode,
        top_k,
    )

    params: dict[str, Any] = {
        "qemb": embedding_str,
        "qemb2": embedding_str,
        "lim": top_k,
    }
    where_clause = _build_conditions(
        params,
        tenant_id=tenant_id,
        role_id=role_id,
        data_domain_ids=data_domain_ids,
        knowledge_base_ids=knowledge_base_ids,
        metadata_filters=metadata_filters,
    )

    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            if mode == "hybrid":
                lanes = [
                    await _vector_lane(
                        conn, params, where_clause, embedding_dim, embedding_str, threshold=threshold
                    ),
                ]
                if query_text.strip():
                    lanes.append(await _text_lane(conn, params, where_clause, query_text))
                results = _rrf_merge([lane for lane in lanes if lane], top_k)
            else:
                results = await _vector_lane(
                    conn, params, where_clause, embedding_dim, embedding_str, threshold=threshold
                )
        # P3 rerank：跨编码器精排（enterprise-retrieval §8 Phase 2 ⑧）。provider 未配置
        # / query_text 为空 / 调用失败 → 原样返回（优雅降级，不阻塞召回）。
        if rerank and results and query_text.strip():
            results = await _rerank_results(results, query_text, top_k, rerank_top_n)
        # Recall statistics: +1 per document per matching query (deduped)
        if results:
            hit_doc_ids = list({r["document_id"] for r in results})
            async with engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
                for did in hit_doc_ids:
                    await conn.execute(
                        text("UPDATE documents SET recall_count = recall_count + 1 WHERE document_id = :did"),
                        {"did": did},
                    )
                await conn.commit()
        return results
    except Exception:
        logger.exception("search_chunks failed (mode=%s)", mode)
        if eventbus:
            eventbus.publish(
                CloudEvent(
                    type="earp.retrieval.failed",
                    source="earp-server/knowledge",
                    tenant_id=tenant_id,
                    data={"role_id": role_id, "top_k": top_k, "mode": mode},
                )
            )
        return []
