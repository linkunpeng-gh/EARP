"""Enterprise retrieval routing — soft routing + hierarchical funnel (Phase 1).

Level 1 — DD routing: keyword lane (moved from planner/business_dictionary per
          2026-08-09 会话决策 D-13) + embedding lane over routing_description.
Level 2 — KB locating: knowledge_bases.summary_embedding within candidate DDs
          (permission-filtered). Empty candidate KBs fall back to whole-tenant
          KB summary matching so a routing miss never yields empty recall.
Level 3 — chunk recall: caller passes candidate_kbs to search_chunks.

Design: arch/design/2026-08-09-enterprise-retrieval-design.md (2026-08-09 会话).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.ext.ext_embedding import get_embedding_provider

logger = logging.getLogger(__name__)

# ── Data Domain keyword lane ─────────────────────────────────────────────────
# Moved here from planner/business_dictionary.py (D-13: keyword table lives in
# the knowledge domain; planner re-imports from here). planner-spec v1.1 §5.1.2.
_DATA_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "equipment_data": [
        "设备",
        "产线",
        "机床",
        "报警",
        "维护",
        "alarm",
        "alarms",
        "equipment",
        "maintenance",
        "machine",
    ],
    "hr_data": ["休假", "请假", "考勤", "员工", "人事", "政策", "leave", "hr", "employee", "policy"],
    "corporate_data": ["安全", "规范", "制度", "手册", "safety", "standards", "handbook"],
    "production_data": ["工单", "生产", "订单", "work order", "production", "order"],
    "supply_chain_data": ["供应商", "库存", "物料", "supplier", "inventory", "material"],
}

# vector dim for routing/summary embeddings — aligned with 0004 (bge-m3, 1024).
_ROUTING_DIM = 1024

# KB summary text caps (avoid embedding dilution on huge KBs)
_MAX_TITLES_IN_SUMMARY = 60
_MAX_SUMMARY_CHARS = 2000


def match_data_domains(intent: str) -> list[str]:
    """Rule-based Data Domain routing — keyword match on intent text.

    Returns matching data_domain_ids in definition order; empty list when no
    keyword hits. Callers MUST NOT block on empty (soft-routing: vector lane
    still applies).
    """
    text_lower = intent.lower()
    return [dd for dd, keywords in _DATA_DOMAIN_KEYWORDS.items() if any(kw in text_lower for kw in keywords)]


def _tokenize(text_str: str) -> list[str]:
    return [t for t in re.findall(r"[\w\u4e00-\u9fff]+", text_str) if t]


def _desc_hash(text_str: str) -> str:
    return hashlib.md5(text_str.encode()).hexdigest()


def check_description_coverage(dd_text: str, kb_names: list[str]) -> list[str]:
    """Coverage self-check: each KB name (or its space/punct-separated tokens)
    must appear in the DD description. Empty = covered. Used by the routing
    debug view to surface manually-written descriptions that miss KB topics.
    """
    missing: list[str] = []
    for name in kb_names:
        tokens = [t for t in re.split(r"[\s,，。;；、/()（）]+", name) if t] or [name]
        if not any(tok in dd_text for tok in tokens):
            missing.append(name)
    return missing


# ── Text aggregation ─────────────────────────────────────────────────────────
async def _dd_description_text(conn, tenant_id: str, dd: dict) -> str:
    """DD description = DD name/description + Σ(KB name + description).
    Document titles deliberately excluded (D-13/C-7): doc ops must not trigger
    DD-level rebuilds; title semantics live in the KB summary instead.
    """
    rows = await conn.execute(
        text(
            "SELECT name, description FROM knowledge_bases "
            "WHERE tenant_id = :tid AND data_domain_id = :dd ORDER BY name"
        ),
        {"tid": tenant_id, "dd": dd["data_domain_id"]},
    )
    kb_parts = []
    for r in rows:
        desc = f"（{r.description}）" if r.description else ""
        kb_parts.append(f"{r.name}{desc}")
    base = dd.get("description") or ""
    parts = [dd.get("name") or dd["data_domain_id"]]
    if base:
        parts.append(base)
    if kb_parts:
        parts.append("领域知识库：" + "；".join(kb_parts))
    return "。".join(parts)


async def _kb_summary_text(conn, kb: dict) -> str:
    """KB summary = manual override (summary_text) if set; otherwise auto:
    KB name + description + Σ(document titles, capped)."""
    override = kb.get("summary_text")
    if override:
        return override[:_MAX_SUMMARY_CHARS]
    rows = await conn.execute(
        text(
            "SELECT title FROM documents "
            "WHERE knowledge_base_id = :kid AND status = 'active' AND title IS NOT NULL AND title <> '' "
            "ORDER BY created_at LIMIT :lim"
        ),
        {"kid": kb["knowledge_base_id"], "lim": _MAX_TITLES_IN_SUMMARY},
    )
    titles = [r.title for r in rows]
    parts = [kb.get("name") or kb["knowledge_base_id"]]
    if kb.get("description"):
        parts.append(kb["description"])
    if titles:
        parts.append("文档：" + "；".join(titles))
    joined = "。".join(parts)
    return joined[:_MAX_SUMMARY_CHARS]


# ── Index build (offline + incremental) ──────────────────────────────────────
async def build_routing_index(
    engine: AsyncEngine,
    tenant_id: str,
    dd_ids: list[str] | None = None,
    kb_ids: list[str] | None = None,
) -> dict:
    """Rebuild DD routing embeddings and/or KB summary embeddings.

    Idempotent per row: when the aggregated text hash equals the stored hash
    the row is skipped (no embedding call). NULL embeddings are kept NULL when
    the provider is unavailable — graceful degrade (keyword lane still works).

    Returns stats for observability/tests.
    """
    stats = {
        "dds_rebuilt": 0,
        "dds_skipped": 0,
        "kbs_rebuilt": 0,
        "kbs_skipped": 0,
        "failed": 0,
    }
    provider = None
    try:
        provider = get_embedding_provider()
    except RuntimeError:
        logger.warning("build_routing_index: no embedding provider — skipping vector writes")

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))

        # ── DD routing_description embeddings ──
        sql = "SELECT data_domain_id, name, description, routing_embedding, routing_hash FROM data_domains"
        params: dict = {"tid": tenant_id}
        if dd_ids:
            sql += " WHERE tenant_id = :tid AND data_domain_id = ANY(:dids)"
            params["dids"] = dd_ids
        else:
            sql += " WHERE tenant_id = :tid"
        rows = (await conn.execute(text(sql), params)).fetchall()
        for dd in (dict(r._mapping) for r in rows):
            current = await _dd_description_text(conn, tenant_id, dd)
            h = _desc_hash(current)
            if dd.get("routing_hash") == h:
                stats["dds_skipped"] += 1
                continue
            if provider is None:
                stats["failed"] += 1
                continue
            try:
                emb = (await provider.embed([current]))[0]
                emb_str = f"[{', '.join(str(x) for x in emb)}]"
                await conn.execute(
                    text(
                        "UPDATE data_domains SET routing_embedding = CAST(:emb AS vector(1024)), "
                        "routing_hash = :h WHERE data_domain_id = :dd AND tenant_id = :tid"
                    ),
                    {"emb": emb_str, "h": h, "dd": dd["data_domain_id"], "tid": tenant_id},
                )
                stats["dds_rebuilt"] += 1
            except Exception:
                logger.exception("routing: DD embedding failed for %s", dd["data_domain_id"])
                stats["failed"] += 1

        # ── KB summary embeddings ──
        ksql = (
            "SELECT knowledge_base_id, name, description, summary_text, "
            "summary_embedding, summary_hash FROM knowledge_bases"
        )
        kparams: dict = {"tid": tenant_id}
        if kb_ids:
            ksql += " WHERE tenant_id = :tid AND knowledge_base_id = ANY(:kbs)"
            kparams["kbs"] = kb_ids
        else:
            ksql += " WHERE tenant_id = :tid"
        krows = (await conn.execute(text(ksql), kparams)).fetchall()
        for kb in (dict(r._mapping) for r in krows):
            current = await _kb_summary_text(conn, kb)
            h = _desc_hash(current)
            if kb.get("summary_hash") == h:
                stats["kbs_skipped"] += 1
                continue
            if provider is None:
                stats["failed"] += 1
                continue
            try:
                emb = (await provider.embed([current]))[0]
                emb_str = f"[{', '.join(str(x) for x in emb)}]"
                await conn.execute(
                    text(
                        "UPDATE knowledge_bases SET summary_embedding = CAST(:emb AS vector(1024)), "
                        "summary_hash = :h WHERE knowledge_base_id = :kid AND tenant_id = :tid"
                    ),
                    {"emb": emb_str, "h": h, "kid": kb["knowledge_base_id"], "tid": tenant_id},
                )
                stats["kbs_rebuilt"] += 1
            except Exception:
                logger.exception("routing: KB summary embedding failed for %s", kb["knowledge_base_id"])
                stats["failed"] += 1

        await conn.commit()
    return stats


# ── Permission helpers (inlined to avoid knowledge→policy cross-domain import;
#    mirrors policy_service.check_data_domain_access) ─────────────────────────
async def _allowed_domain_ids(conn, tenant_id: str, role_id: str, requested: list[str]) -> set[str]:
    if not requested:
        return set()
    row = await conn.execute(
        text("SELECT data_domain_access FROM roles WHERE role_id = :rid AND tenant_id = :tid"),
        {"rid": role_id, "tid": tenant_id},
    )
    r = row.fetchone()
    if r is None:
        return set()
    access_list = r._mapping.get("data_domain_access") or []
    allowed = {entry["data_domain_id"] for entry in access_list if "data_domain_id" in entry}
    return {did for did in requested if did in allowed}


# ── Query routing ────────────────────────────────────────────────────────────
async def route_query(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    query_embedding: list[float] | None,
    role_id: str,
    top_n: int = 3,
    top_k: int = 3,
) -> dict:
    """Soft route: keyword ∪ vector DD candidates (permission-filtered) → KB
    candidates (accessible_roles-filtered). Empty DD candidates → whole-tenant
    KB fallback so routing misses never yield empty recall.

    query_embedding=None → vector lane 跳过（keyword lane 仍工作，优雅降级）。
    """
    emb_str = f"[{', '.join(str(x) for x in query_embedding)}]" if query_embedding else None
    t_l0 = time.monotonic()
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))

        # ── Level 1a: keyword lane (exact hits, kept in full — soft routing) ──
        keyword_hits = match_data_domains(query)

        # ── Level 1b: vector lane over routing_description ──
        if emb_str is not None:
            rows = await conn.execute(
                text(
                    "SELECT dd.data_domain_id, dd.name, "
                    "1 - (dd.routing_embedding <=> CAST(:qemb AS vector(1024))) AS score "
                    "FROM data_domains dd "
                    "WHERE dd.tenant_id = :tid AND dd.routing_embedding IS NOT NULL "
                    "ORDER BY dd.routing_embedding <=> CAST(:qemb2 AS vector(1024)) LIMIT :n"
                ),
                {"qemb": emb_str, "qemb2": emb_str, "tid": tenant_id, "n": top_n},
            )
            vector_cands = [dict(r._mapping) for r in rows]
        else:
            vector_cands = []

        # ── union + permission filter (roles.data_domain_access) ──
        by_id: dict[str, dict] = {}
        for c in vector_cands:
            by_id[c["data_domain_id"]] = {**c, "via": "vector"}
        for dd in keyword_hits:
            if dd in by_id:
                by_id[dd]["via"] = "both"
            else:
                by_id[dd] = {"data_domain_id": dd, "name": dd, "score": 1.0, "via": "keyword"}
        allowed = await _allowed_domain_ids(conn, tenant_id, role_id, list(by_id))
        candidate_dds = [by_id[did] for did in by_id if did in allowed]
        t_l1 = time.monotonic()

        # ── Level 2: KB summary within candidate DDs (accessible_roles) ──
        kb_rows = []
        fallback_used = False
        if candidate_dds and emb_str is not None:
            kb_rows = (
                await conn.execute(
                    text(
                        "SELECT kb.knowledge_base_id, kb.name, kb.data_domain_id, "
                        "1 - (kb.summary_embedding <=> CAST(:qemb AS vector(1024))) AS score "
                        "FROM knowledge_bases kb "
                        "WHERE kb.tenant_id = :tid AND kb.summary_embedding IS NOT NULL "
                        "AND kb.data_domain_id = ANY(:dids) "
                        "AND (kb.accessible_roles IS NULL OR kb.accessible_roles = '{}' "
                        "     OR :rid = ANY(kb.accessible_roles)) "
                        "ORDER BY kb.summary_embedding <=> CAST(:qemb2 AS vector(1024)) LIMIT :k"
                    ),
                    {
                        "qemb": emb_str,
                        "qemb2": emb_str,
                        "tid": tenant_id,
                        "dids": [c["data_domain_id"] for c in candidate_dds],
                        "rid": role_id,
                        "k": top_k,
                    },
                )
            ).fetchall()
        if not kb_rows:
            # fallback: whole-tenant KB summary match (routing miss must not
            # yield empty recall); still permission-filtered on accessible_roles.
            fallback_used = True
            if emb_str is not None:
                kb_rows = (
                    await conn.execute(
                        text(
                            "SELECT kb.knowledge_base_id, kb.name, kb.data_domain_id, "
                            "1 - (kb.summary_embedding <=> CAST(:qemb AS vector(1024))) AS score "
                            "FROM knowledge_bases kb "
                            "WHERE kb.tenant_id = :tid AND kb.summary_embedding IS NOT NULL "
                            "AND (kb.accessible_roles IS NULL OR kb.accessible_roles = '{}' "
                            "     OR :rid = ANY(kb.accessible_roles)) "
                            "ORDER BY kb.summary_embedding <=> CAST(:qemb2 AS vector(1024)) LIMIT :k"
                        ),
                        {"qemb": emb_str, "qemb2": emb_str, "tid": tenant_id, "rid": role_id, "k": top_k},
                    )
                ).fetchall()
        candidate_kbs = [dict(r._mapping) for r in kb_rows]
        t_l2 = time.monotonic()

    timings = {
        "dd_lanes_ms": round((t_l1 - t_l0) * 1000, 1),  # keyword + vector + permission
        "kb_locate_ms": round((t_l2 - t_l1) * 1000, 1),  # KB summary match (+ fallback)
        "total_ms": round((t_l2 - t_l0) * 1000, 1),
    }

    logger.info(
        "route_query query=%r keyword=%s vector=%s candidate_dds=%s candidate_kbs=%s fallback=%s",
        query,
        keyword_hits,
        [(c["data_domain_id"], round(c["score"], 3)) for c in vector_cands],
        [(c["data_domain_id"], c["via"]) for c in candidate_dds],
        [(k["knowledge_base_id"], round(k["score"], 3)) for k in candidate_kbs],
        fallback_used,
    )

    return {
        "candidate_dds": candidate_dds,
        "candidate_kbs": candidate_kbs,
        "fallback_used": fallback_used,
        "timings": timings,
    }


# ── Debug view (routing observability: every layer's scores) ────────────────
async def _ontology_layers_debug(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    query_embedding: list[float],
    role_id: str,
    candidate_dds: list[dict],
    candidate_kbs: list[dict],
) -> dict:
    """三层检索（profile/graph/chunk）逐层命中明细——路由调试可观测（P2 增补）。

    函数内 import 避免 knowledge.routing → ontology.search → knowledge.search_service
    的模块级环。candidate_dds 空 → 不触发三层（与 /knowledge/search 决策 D4 一致）。
    """
    cand_dds = [d["data_domain_id"] for d in candidate_dds]
    cand_kbs = [kb["knowledge_base_id"] for kb in candidate_kbs]
    if not cand_dds:
        return {"triggered": False, "reason": "无候选 DD（决策 D4：全租户 chunk 兜底，不触发三层）"}
    from earp_server.ontology.search import _knowledge_layers

    layers, fused = await _knowledge_layers(
        engine,
        tenant_id,
        query,
        embedding=query_embedding,
        role_id=role_id,
        data_domain_ids=cand_dds,
        knowledge_base_ids=cand_kbs or None,
        top_k=5,
        embedding_dim=_ROUTING_DIM,
        query_text=query,
        mode="hybrid",
    )
    return {
        "triggered": True,
        "profile": [
            {k: h.get(k) for k in ("entity_id", "entity_type", "title", "score")} for h in layers["profile"][:5]
        ],
        "graph": [
            {k: h.get(k) for k in ("entity_id", "entity_type", "title", "depth", "score")} for h in layers["graph"][:5]
        ],
        "chunk": [{k: h.get(k) for k in ("chunk_id", "title", "kb_name", "score")} for h in layers["chunk"][:5]],
        "fused": [{k: h.get(k) for k in ("source", "title", "rrf_score")} for h in fused],
    }


async def route_debug(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    query_embedding: list[float],
    role_id: str,
    top_n: int = 3,
    top_k: int = 3,
) -> dict:
    """Routing debug view: per-layer scores + description coverage + freshness."""
    t_debug0 = time.monotonic()
    emb_str = f"[{', '.join(str(x) for x in query_embedding)}]"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))

        keyword_hits = match_data_domains(query)
        t_dd_vec0 = time.monotonic()
        rows = await conn.execute(
            text(
                "SELECT dd.data_domain_id, dd.name, "
                "1 - (dd.routing_embedding <=> CAST(:qemb AS vector(1024))) AS score "
                "FROM data_domains dd "
                "WHERE dd.tenant_id = :tid AND dd.routing_embedding IS NOT NULL "
                "ORDER BY dd.routing_embedding <=> CAST(:qemb2 AS vector(1024)) LIMIT :n"
            ),
            {"qemb": emb_str, "qemb2": emb_str, "tid": tenant_id, "n": top_n},
        )
        vector_cands = [dict(r._mapping) for r in rows]
        t_coverage0 = time.monotonic()

        # coverage + freshness for ALL tenant DDs (visible in debug view)
        all_rows = (
            await conn.execute(
                text(
                    "SELECT data_domain_id, name, description, routing_embedding, routing_hash "
                    "FROM data_domains WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).fetchall()  # materialize BEFORE nested queries (psycopg async: no
        # interleaved cursor ops on one connection — would hang the request)
        coverage: list[dict] = []
        freshness: list[dict] = []
        for dd in (dict(r._mapping) for r in all_rows):
            current = await _dd_description_text(conn, tenant_id, dd)
            h = _desc_hash(current)
            kb_names = [
                r.name
                for r in (
                    await conn.execute(
                        text("SELECT name FROM knowledge_bases WHERE tenant_id = :tid AND data_domain_id = :dd"),
                        {"tid": tenant_id, "dd": dd["data_domain_id"]},
                    )
                ).fetchall()
            ]
            missing = check_description_coverage(current, kb_names)
            coverage.append({"data_domain_id": dd["data_domain_id"], "name": dd["name"], "missing_kb_names": missing})
            freshness.append(
                {
                    "data_domain_id": dd["data_domain_id"],
                    "name": dd["name"],
                    "indexed": dd.get("routing_embedding") is not None,
                    "stale": bool(dd.get("routing_hash")) and dd.get("routing_hash") != h,
                    "description": current,
                }
            )
        t_coverage1 = time.monotonic()

    result = await route_query(engine, tenant_id, query, query_embedding, role_id, top_n, top_k)
    # KB summary text preview (observability: what text backs the summary vector)
    kb_summaries: list[dict] = []
    if result["candidate_kbs"]:
        t_kbs0 = time.monotonic()
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            for kb in result["candidate_kbs"]:
                row = await conn.execute(
                    text(
                        "SELECT name, description, summary_text, summary_hash FROM knowledge_bases "
                        "WHERE knowledge_base_id = :kid"
                    ),
                    {"kid": kb["knowledge_base_id"]},
                )
                r = row.fetchone()
                if r is None:
                    continue
                summary_text = await _kb_summary_text(
                    conn,
                    {
                        "knowledge_base_id": kb["knowledge_base_id"],
                        "name": r.name,
                        "description": r.description,
                        "summary_text": r.summary_text,
                    },
                )
                kb_summaries.append(
                    {
                        "knowledge_base_id": kb["knowledge_base_id"],
                        "name": kb["name"],
                        "score": kb["score"],
                        "summary_text": summary_text,
                        "indexed": True,
                        "stale": bool(r.summary_hash) and r.summary_hash != _desc_hash(summary_text),
                    }
                )
    return {
        "query": query,
        "dd_keyword_hits": keyword_hits,
        "dd_vector_candidates": vector_cands,
        "candidate_dds": result["candidate_dds"],
        "candidate_kbs": result["candidate_kbs"],
        "kb_summaries": kb_summaries,
        "ontology_layers": await _ontology_layers_debug(
            engine,
            tenant_id,
            query,
            query_embedding,
            role_id,
            result["candidate_dds"],
            result["candidate_kbs"],
        ),
        "timings": {
            "dd_vector_ms": round((t_coverage0 - t_dd_vec0) * 1000, 1),
            "coverage_freshness_ms": round((t_coverage1 - t_coverage0) * 1000, 1),
            "route_query": result["timings"],  # dd_lanes_ms + kb_locate_ms
            "kb_summaries_ms": (round((time.monotonic() - t_kbs0) * 1000, 1) if result["candidate_kbs"] else 0.0),
            "total_ms": round((time.monotonic() - t_debug0) * 1000, 1),
        },
        "fallback_used": result["fallback_used"],
        "coverage": coverage,
        "freshness": freshness,
    }
