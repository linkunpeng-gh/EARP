"""M4 knowledge pipeline integration test — document → chunk → embed → search.

Covers PRD-2026-024 US-01/US-03 against the REAL schema (post-0007 alignment).
This is the missing integration test that would have caught the kb_id/doc_id
schema drift: ingestion code used knowledge_base_id/document_id while M0 DDL
created kb_id/doc_id.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import create_document
from earp_server.knowledge.embedding_service import embed_chunks, embed_query
from earp_server.knowledge.search_service import search_chunks

DIM = 1024  # chunks.embedding is vector(1024) after migration 0004


class _StubProvider:
    """Deterministic embedding stub: hash-based pseudo-vector of dim=1024."""

    name = "stub"
    dim = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        out = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            # stretch digest deterministically to DIM entries (repeat 256-byte digest)
            vec = [float(b) / 255.0 for b in (digest * (DIM // len(digest) + 1))[:DIM]]
            out.append(vec)
        return out


def _install_stub(monkeypatch):
    import earp_server.knowledge.embedding_service as svc

    provider = _StubProvider()
    monkeypatch.setattr(svc, "get_embedding_provider", lambda: provider)
    return provider


async def test_knowledge_pipeline_full_cycle(migrated: str, app_url: str, monkeypatch) -> None:
    """US-01/US-03: upload → chunks → embed → search returns top chunk."""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "kbpipe-t1"

    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, data_classification, status) "
                "VALUES ('equipment_data', :tid, '设备数据', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id) "
                "VALUES ('kbp-1', :tid, '设备手册', 'equipment_data')"
            ),
            {"tid": tid},
        )

    doc = await create_document(engine, tid, "kbp-1", "CNC 设备操作手册。主轴轴承每 6 个月更换一次。", "CNC Manual")
    assert doc["document_id"].startswith("doc-")

    chunk_ids = await create_chunks(engine, tid, doc["document_id"], "CNC 设备操作手册。主轴轴承每 6 个月更换一次。")
    assert len(chunk_ids) > 0

    await embed_chunks(engine, tid, chunk_ids)

    # chunk rows now carry embedding + chunk_index + content_hash
    async with tenant_session(engine, tid) as session:
        row = await session.execute(
            text(
                "SELECT chunk_id, chunk_index, content_hash, embedding IS NOT NULL AS has_emb "
                "FROM chunks WHERE document_id = :did"
            ),
            {"did": doc["document_id"]},
        )
        rows = row.fetchall()
        assert len(rows) == len(chunk_ids)
        assert all(r.has_emb for r in rows)
        assert rows[0].chunk_index == 0

    # search: same content → top-1 chunk should be from our doc
    q_emb = await embed_query("主轴轴承更换周期")
    hits = await search_chunks(engine, tid, q_emb, role_id="r-any", top_k=3, embedding_dim=DIM)
    assert hits, "search must return at least one chunk"
    assert hits[0]["document_id"] == doc["document_id"]
