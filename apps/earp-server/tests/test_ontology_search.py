"""PRD-2026-030 M2 — three-layer knowledge_search (RRF) + resolve_with_entities."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.ontology import abox_service, search, tbox_service

DIM = 1024


class _StubProvider:
    name = "stub"
    dim = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            out.append([float(b) / 255.0 for b in (digest * (DIM // len(digest) + 1))[:DIM]])
        return out


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def _install_stub(monkeypatch):
    import earp_server.knowledge.embedding_service as svc

    provider = _StubProvider()
    monkeypatch.setattr(svc, "get_embedding_provider", lambda: provider)
    return provider


async def _seed_entity_graph(engine: AsyncEngine, tid: str) -> dict:
    """CNC-01 (equipment) —manufactured_by→ 上海某精机 (supplier); 高温报警 → CNC-01."""
    await tbox_service.init_tenant_tbox(engine, tid)
    sup = await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-1")
    equip = await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01", business_code="CNC-01")
    alarm = await abox_service.upsert_entity(engine, tid, "alarm", "高温报警")
    await abox_service.add_fact(engine, tid, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.add_fact(engine, tid, alarm["entity_id"], "caused_by", equip["entity_id"])
    await abox_service.compile_profile(engine, tid, equip["entity_id"])
    return {"equip": equip["entity_id"], "sup": sup["entity_id"], "alarm": alarm["entity_id"]}


async def test_knowledge_search_profile_layer(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "osr-t1"
    await _seed_entity_graph(engine, tid)

    # query matches entity name → profile layer hit first
    hits = await search.knowledge_search(engine, tid, "CNC-01", role_id="r-any", top_k=5, embedding_dim=DIM)
    assert hits, "must return hits"
    top = hits[0]
    assert top["source"] in ("profile", "graph")
    # graph layer must surface the supplier fact via traversal
    sources = {h["source"] for h in hits}
    assert "graph" in sources


async def test_knowledge_search_fallback_no_embedding(migrated: str, app_url: str, monkeypatch) -> None:
    """No embedding provider → profile/graph layers still work (vector degrades)."""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "osr-t2"
    await _seed_entity_graph(engine, tid)

    hits = await search.knowledge_search(engine, tid, "上海某精机", role_id="r-any", top_k=5)
    assert hits
    assert any(h["source"] == "profile" for h in hits)


def test_rrf_merge_ordering() -> None:
    lane_a = [
        {"key": "x1", "source": "profile", "content": "a"},
        {"key": "x2", "source": "profile", "content": "b"},
    ]
    lane_b = [
        {"key": "x2", "source": "graph", "content": "c"},
        {"key": "x3", "source": "graph", "content": "d"},
    ]
    merged = search._rrf_merge([lane_a, lane_b], top_k=3)
    # x2 appears in both lanes → highest RRF score
    assert merged[0]["key"] == "x2"
    assert len(merged) == 3


async def test_resolve_with_entities_narrows_candidates(app_engine: AsyncEngine) -> None:
    tid = "osr-t3"
    await tbox_service.init_tenant_tbox(app_engine, tid)

    from sqlalchemy import text

    async with tenant_session(app_engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                "VALUES ('cap-osr-query', :tid, 'equipment', 'query_alarms', 'query', "
                "'{}', '{}', '{alarm:read}', '1.0.0') ON CONFLICT (capability_id) DO NOTHING"
            ),
            {"tid": tid},
        )
    await tbox_service.map_capability_entity(app_engine, tid, "cap-osr-query", "equipment", "read")

    # intent mentions an entity that exists → narrowed candidates include the mapped capability
    await abox_service.upsert_entity(app_engine, tid, "equipment", "CNC-01", business_code="CNC-01")
    caps = await search.resolve_with_entities(app_engine, tid, "CNC-01 高温报警")
    assert any(c["capability_id"] == "cap-osr-query" for c in caps)

    # intent with no entity match → empty (caller falls back to full discovery)
    assert await search.resolve_with_entities(app_engine, tid, "不存在的实体关键词xyz") == []
