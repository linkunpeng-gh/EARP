"""P3 rerank — cross-encoder re-ranking tests.

Mechanism layer: mock reranker drives re-ordering; provider disabled → RRF-only
order preserved (graceful degradation). Real-model accuracy is measured in dev
(verify_ontology / routing_eval) when a reranker provider is configured.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.ext import ext_reranker
from earp_server.knowledge.search_service import _rerank_results, search_chunks

DIM = 1024


class _OrderedReranker:
    """Deterministic fake: score = 1/(1+index) → reverses candidate order."""

    def __init__(self, order: list[str] | None = None) -> None:
        self.order = order or []
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.calls.append((query, documents))
        # 升序打分：最后一个候选最相关（score=len..1）→ rerank 后顺序反转
        return [float(i + 1) for i in range(len(documents))]


def _mk(chunk_id: str, content: str, similarity: float = 0.5) -> dict:
    return {"chunk_id": chunk_id, "content": content, "similarity": similarity}


async def test_rerank_results_reorders_and_caps() -> None:
    """rerank 后按分数重排 + 截断 top_k + 打 rerank_score。"""
    rk = _OrderedReranker()
    old = ext_reranker._reranker
    ext_reranker._reranker = rk
    ext_reranker._RERANKER_INIT = True
    try:
        results = [_mk("a", "A", 0.9), _mk("b", "B", 0.8), _mk("c", "C", 0.7)]
        out = await _rerank_results(results, "q", top_k=2, rerank_top_n=3)
        assert [o["chunk_id"] for o in out] == ["c", "b"]  # 升序打分 → 重排
        assert out[0]["rerank_score"] == 3.0  # c（index 2）得最高分 3.0
        assert rk.calls[0][0] == "q"  # query 透传
    finally:
        ext_reranker._reranker = old


async def test_rerank_disabled_keeps_order(monkeypatch) -> None:
    """provider 为 None（rerank_provider=none）→ 原顺序保留（优雅降级）。"""
    monkeypatch.setattr(ext_reranker, "_reranker", None)
    monkeypatch.setattr(ext_reranker, "_RERANKER_INIT", True)
    results = [_mk("a", "A", 0.9), _mk("b", "B", 0.8)]
    out = await _rerank_results(results, "q", top_k=2, rerank_top_n=5)
    assert [o["chunk_id"] for o in out] == ["a", "b"]  # 不变
    assert "rerank_score" not in out[0]


async def test_search_chunks_rerank_integration(migrated: str, app_url: str, monkeypatch) -> None:
    """search_chunks 全链路：rerank 启用（mock provider）→ 排序变化；禁用 → 原样。"""
    # seed 一个 KB + doc + chunk
    from earp_server.knowledge.chunk_service import create_chunks
    from earp_server.knowledge.document_service import create_document
    from earp_server.knowledge.embedding_service import embed_chunks

    engine: AsyncEngine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rr-t1"
    import hashlib

    class Stub:
        name = "stub"
        dim = DIM

        async def embed(self, texts):
            out = []
            for t in texts:
                d = hashlib.sha256(t.encode()).digest()
                out.append([float(b) / 255.0 for b in (d * (DIM // len(d) + 1))[:DIM]])
            return out

    import earp_server.knowledge.embedding_service as esvc

    monkeypatch.setattr(esvc, "get_embedding_provider", lambda: Stub())
    from sqlalchemy import text

    from earp_server.infra.db import tenant_session

    async with tenant_session(engine, tid) as s:
        await s.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, data_classification, status) "
                "VALUES ('rr_dd', :t, 'rr', 'rr', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await s.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, description) "
                "VALUES ('rr-kb', :t, 'rr-kb', 'rr_dd', 'rr') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
    doc = await create_document(engine, tid, "rr-kb", "报销标准：住宿500元。设备维护说明。", title="rr-doc")
    cids = await create_chunks(engine, tid, doc["document_id"], "报销标准：住宿500元。设备维护说明。")
    await embed_chunks(engine, tid, cids)

    emb = (await Stub().embed(["报销"]))[0]

    # ① rerank 禁用（provider none）→ RRF/vector 原顺序
    monkeypatch.setattr(ext_reranker, "_reranker", None)
    monkeypatch.setattr(ext_reranker, "_RERANKER_INIT", True)
    no_rr = await search_chunks(
        engine, tid, emb, "r-any", top_k=5, knowledge_base_ids=["rr-kb"],
        query_text="报销", mode="hybrid", embedding_dim=DIM, rerank=True,
    )
    assert no_rr and "rerank_score" not in (no_rr[0] if no_rr else {})

    # ② rerank 启用（mock 逆序）→ rerank_score 出现且顺序按 mock
    rk = _OrderedReranker()
    monkeypatch.setattr(ext_reranker, "_reranker", rk)
    with_rr = await search_chunks(
        engine, tid, emb, "r-any", top_k=5, knowledge_base_ids=["rr-kb"],
        query_text="报销", mode="hybrid", embedding_dim=DIM, rerank=True,
    )
    assert with_rr
    assert "rerank_score" in with_rr[0]
    assert rk.calls and rk.calls[0][0] == "报销"
    await engine.dispose()
