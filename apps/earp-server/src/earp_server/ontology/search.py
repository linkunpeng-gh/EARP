"""Ontology search — three-layer retrieval (PRD-2026-030 M2).

Layer 1: entity lookup → Compiled Truth profile (zero-LLM hit)
Layer 2: graph traversal from matched entities (multi-hop facts)
Layer 3: vector chunks (reuses knowledge/search_service)

Merged with Reciprocal Rank Fusion (k=60). Also provides entity-aware
capability resolution for Planner candidate narrowing (planner-spec §5.1.5).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import EventBus
from earp_server.knowledge.search_service import search_chunks
from earp_server.ontology import abox_service, tbox_service

logger = logging.getLogger(__name__)

RRF_K = 60


def _tokenize(query: str) -> list[str]:
    """Split query into candidate entity tokens (alnum runs incl. CJK)."""
    import re

    return [t for t in re.findall(r"[\w\u4e00-\u9fff\-]+", query) if t]


async def _entity_hits(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    *,
    entity_type_ids: list[str] | None = None,
    data_domain_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Entity lookup across query tokens — match any token, dedup by entity_id."""
    tokens = _tokenize(query)
    if not tokens:
        return []
    seen: dict[str, dict] = {}
    for tok in tokens[:5]:
        hits = await abox_service.lookup_entities(
            engine,
            tenant_id,
            tok,
            entity_type_ids=entity_type_ids,
            data_domain_ids=data_domain_ids,
            top_k=top_k,
        )
        for h in hits:
            seen[h["entity_id"]] = h
    return list(seen.values())[:top_k]


async def _knowledge_layers(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    *,
    embedding: list[float] | None = None,
    role_id: str,
    data_domain_ids: list[str] | None = None,
    entity_type_ids: list[str] | None = None,
    top_k: int = 5,
    embedding_dim: int | None = None,
    knowledge_base_ids: list[str] | None = None,
    query_text: str = "",
    mode: str = "vector",
    threshold: float | None = None,
    metadata_filters: dict | None = None,
    eventbus: EventBus | None = None,
    rerank: bool = True,
    rerank_top_n: int = 20,
) -> tuple[dict, list[dict]]:
    """Three-layer recall computation (recall layer, QU design §8.1).

    Returns (layers: {profile, graph, chunk}, fused: RRF top_k hits).
    knowledge_search 返回 fused；route_debug 用 layers 做逐层明细展示。

    Layer 1/2 (profile/graph) scoped by ROLE's allowed domains（2026-08-18 FDE
    修复：不再按路由候选 DD 限定——实体名不在 DD 描述中，路由对齐性差时实体层
    被静默滤掉，profile/graph 不生效；权限由角色允许域保证，admin 不限域）；
    Layer 3 (chunks) scoped by knowledge_base_ids (precedence) falling back
    to data_domain_ids（文档层保持路由对齐）。
    """
    lane_lists: list[list[dict]] = []

    # ── Layer 1: entity lookup → Compiled Truth profile ──
    from earp_server.knowledge.search_service import _role_scope_domains

    entity_dds = await _role_scope_domains(engine, tenant_id, role_id)
    entities: list[dict] = []
    if entity_dds is None:
        # admin/全权限：不限域
        entities = await _entity_hits(
            engine,
            tenant_id,
            query,
            entity_type_ids=entity_type_ids,
            top_k=top_k,
        )
    elif entity_dds:
        entities = await _entity_hits(
            engine,
            tenant_id,
            query,
            entity_type_ids=entity_type_ids,
            data_domain_ids=sorted(entity_dds),
            top_k=top_k,
        )
    # 空集（角色无域授权）→ fail-closed 无实体
    profile_hits: list[dict] = []
    if entities:
        for ent in entities[:top_k]:
            profile = await abox_service.get_entity_profile(engine, tenant_id, ent["entity_id"])
            if profile is None:
                profile = await abox_service.compile_profile(engine, tenant_id, ent["entity_id"])
            if profile is None:
                continue
            p = profile.get("profile", {})
            profile_hits.append(
                {
                    "key": ent["entity_id"],
                    "source": "profile",
                    "entity_id": ent["entity_id"],
                    "entity_type": ent["entity_type_id"],
                    "title": f"{p.get('name', '') or ent['entity_id']}（实体档案）",
                    "content": p.get("summary") or f"{p.get('name', '')}（{ent['entity_type_id']}）",
                    "score": 1.0,
                    "key_facts": p.get("key_facts", []),
                }
            )
    if profile_hits:
        lane_lists.append(profile_hits)

    # ── Layer 2: graph traversal from matched entities ──
    graph_hits: list[dict] = []
    if entities:
        for ent in entities[:2]:
            hops = await abox_service.graph_query(engine, tenant_id, ent["entity_id"], max_hops=2)
            for h in hops:
                graph_hits.append(
                    {
                        "key": f"g:{h['target_entity_id']}",
                        "source": "graph",
                        "entity_id": h["target_entity_id"],
                        "entity_type": h.get("target_type"),
                        "title": f"图谱：{h['relation_type_id']} → {h.get('target_name', h['target_entity_id'])}",
                        "content": f"{h['relation_type_id']} → {h.get('target_name', h['target_entity_id'])}",
                        "score": 1.0 / (1 + h["depth"]),
                        "depth": h["depth"],
                    }
                )
    if graph_hits:
        lane_lists.append(graph_hits)

    # ── Layer 3: vector chunks (requires embedding; skip gracefully if unavailable) ──
    chunk_hits: list[dict] = []
    if embedding is not None:
        try:
            chunks = await search_chunks(
                engine,
                tenant_id,
                embedding,
                role_id,
                top_k,
                data_domain_ids=data_domain_ids,
                embedding_dim=embedding_dim,
                knowledge_base_ids=knowledge_base_ids,
                threshold=threshold,
                query_text=query_text,
                mode=mode,
                metadata_filters=metadata_filters,
                eventbus=eventbus,
                rerank=rerank,
                rerank_top_n=rerank_top_n,
            )
            for c in chunks:
                merged = dict(c)
                merged["key"] = c["chunk_id"]
                merged["source"] = "chunk"
                merged["score"] = c.get("similarity", 0.0)
                chunk_hits.append(merged)
        except Exception:
            logger.warning("knowledge_search: vector layer failed, skipping", exc_info=True)
    if chunk_hits:
        lane_lists.append(chunk_hits)

    if not lane_lists:
        return {"profile": [], "graph": [], "chunk": []}, []

    return (
        {"profile": profile_hits, "graph": graph_hits, "chunk": chunk_hits},
        _rrf_merge(lane_lists, top_k),
    )


async def knowledge_search(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    *,
    embedding: list[float] | None = None,
    role_id: str,
    data_domain_ids: list[str] | None = None,
    entity_type_ids: list[str] | None = None,
    top_k: int = 5,
    embedding_dim: int | None = None,
    knowledge_base_ids: list[str] | None = None,
    query_text: str = "",
    mode: str = "vector",
    threshold: float | None = None,
    metadata_filters: dict | None = None,
    eventbus: EventBus | None = None,
    rerank: bool = True,
    rerank_top_n: int = 20,
) -> list[dict]:
    """Three-layer retrieval with RRF fusion (recall layer, QU design §8.1).

    Returns up to top_k hits, each {source: profile|graph|chunk, key, title,
    content, score(original), rrf_score}. Permission model: chunks filtered by
    DD + accessible_roles inside search_chunks; entity layer filtered by DD ids.
    """
    _, fused = await _knowledge_layers(
        engine,
        tenant_id,
        query,
        embedding=embedding,
        role_id=role_id,
        data_domain_ids=data_domain_ids,
        entity_type_ids=entity_type_ids,
        top_k=top_k,
        embedding_dim=embedding_dim,
        knowledge_base_ids=knowledge_base_ids,
        query_text=query_text,
        mode=mode,
        threshold=threshold,
        metadata_filters=metadata_filters,
        eventbus=eventbus,
        rerank=rerank,
        rerank_top_n=rerank_top_n,
    )
    return fused


def _rrf_merge(ranked_lists: list[list[dict]], top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion: score = Σ 1/(k + rank), k=60 (per-lane ranking)."""
    fused: dict[str, dict] = {}
    for lane in ranked_lists:
        for rank, item in enumerate(lane):
            key = item["key"]
            if key not in fused:
                merged = dict(item)
                merged["rrf_score"] = 0.0
                fused[key] = merged
            fused[key]["rrf_score"] += 1.0 / (RRF_K + rank + 1)
    return sorted(fused.values(), key=lambda x: -x["rrf_score"])[:top_k]


async def resolve_with_entities(
    engine: AsyncEngine,
    tenant_id: str,
    intent: str,
    *,
    top_k: int = 10,
) -> list[dict]:
    """Entity-aware capability resolution (planner-spec §5.1.5, PRD-2026-030 M2).

    Intent → entity lookup → entity_type_ids → capability_entity_map reverse
    lookup → candidate capabilities. Empty when no entity matched — callers
    MUST fall back to full semantic discovery (must not block routing).
    """
    entities = await _entity_hits(engine, tenant_id, intent, top_k=3)
    if not entities:
        return []

    type_ids = list({e["entity_type_id"] for e in entities})
    candidates: dict[str, dict] = {}
    for et in type_ids:
        caps = await tbox_service.find_capabilities_by_entity_type(engine, tenant_id, et)
        for c in caps:
            candidates[c["capability_id"]] = c
    return list(candidates.values())[:top_k]


async def resolve_with_query(
    engine: AsyncEngine,
    tenant_id: str,
    query,
    *,
    top_k: int = 10,
) -> list[dict]:
    """Entity-aware capability resolution from a StructuredQuery（§6.5 新签名，Phase D）。

    与 resolve_with_entities 的区别（v0.2 缺陷闭合）：
    - 直接用 query.entities 的 semantic_type/mention，不重新 tokenize intent
    - 命中实体不再内部丢弃——每个候选带 matched_entity_ids（Evidence 溯源用）

    返回 [{capability_id, entity_type_id, matched_entity_ids, name, type, operation}]。
    空 entities → 返回 []（调用方回落，MUST NOT block routing）。
    """
    from earp_server.ontology.understanding import StructuredQuery

    if not isinstance(query, StructuredQuery) or not query.entities:
        return []
    type_ids = list({e.semantic_type for e in query.entities if e.semantic_type})
    if not type_ids:
        return []

    # matched_entity_ids：每个 semantic_type 下的实体命中（mention → lookup）
    matched: dict[str, list[str]] = {}
    for ent in query.entities[:5]:
        if not ent.semantic_type:
            continue
        hits = await abox_service.lookup_entities(engine, tenant_id, ent.mention, top_k=1)
        if hits:
            matched.setdefault(ent.semantic_type, []).append(hits[0]["entity_id"])

    candidates: dict[str, dict] = {}
    for et in type_ids:
        caps = await tbox_service.find_capabilities_by_entity_type(engine, tenant_id, et)
        for c in caps:
            key = c["capability_id"]
            if key not in candidates:
                candidates[key] = {**c, "entity_type_id": et, "matched_entity_ids": list(matched.get(et, []))}
            else:
                candidates[key]["matched_entity_ids"].extend(matched.get(et, []))
    return list(candidates.values())[:top_k]
