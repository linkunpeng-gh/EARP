"""Enterprise retrieval Phase 1 — routing + metadata filtering tests.

Three-layer verification (2026-08-09 会话决策):
  mechanism layer: build/rebuild triggers, locality (doc ops must NOT touch
    DD embeddings), idempotency (hash skip), permission filtering, metadata
    type-sensitive filtering — all deterministic under the bigram stub.
  effect layer: routing_eval pass rate (fixtures/routing_eval.md, ≥90%).

The stub embeds texts as a character-bigram bag, so queries sharing bigrams
with DD descriptions rank high — CI validates the *mechanism* with
deterministic semantics; real semantic accuracy is measured in dev with
bge-m3 via scripts/verify_routing.py.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import (
    create_document,
    normalize_metadata,
    update_document_metadata,
)
from earp_server.knowledge.embedding_service import embed_chunks, embed_query
from earp_server.knowledge.routing import (
    build_routing_index,
    check_description_coverage,
    match_data_domains,
    route_debug,
    route_query,
)
from earp_server.knowledge.search_service import search_chunks

DIM = 1024
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


class _BigramStubProvider:
    """Deterministic char-bigram bag embedding (dim=1024). Texts sharing
    bigrams get high cosine similarity — enough for mechanism-level routing."""

    name = "bigram-stub"
    dim = DIM

    def _bigrams(self, t: str) -> set[str]:
        chars = re.findall(r"[\w\u4e00-\u9fff]", t.lower())
        return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * DIM
            for bg in self._bigrams(t):
                vec[hashlib.md5(bg.encode()).digest()[0] % DIM] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


def _install_stub(monkeypatch) -> _BigramStubProvider:
    import earp_server.knowledge.routing as routing

    provider = _BigramStubProvider()
    monkeypatch.setattr(routing, "get_embedding_provider", lambda: provider)
    # embedding_service uses the same provider instance for query embeddings
    import earp_server.knowledge.embedding_service as svc

    monkeypatch.setattr(svc, "get_embedding_provider", lambda: provider)
    return provider


async def _purge(migration_url: str, ids: list[str]) -> None:
    """data_domains PK is single-column (cross-tenant conflict, known debt #7):
    purge shared semantic ids before seeding so each test owns them."""
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM chunks WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:dds))"
            ),
            {"dds": ids},
        )
        await conn.execute(
            text(
                "DELETE FROM documents WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:dds))"
            ),
            {"dds": ids},
        )
        await conn.execute(text("DELETE FROM knowledge_bases WHERE data_domain_id = ANY(:dds)"), {"dds": ids})
        await conn.execute(text("DELETE FROM data_domains WHERE data_domain_id = ANY(:dds)"), {"dds": ids})
        await conn.execute(
            text("DELETE FROM roles WHERE role_id = ANY(:rids)"), {"rids": ["r-all", "r-nofin"]}
        )
    await eng.dispose()


async def _seed_tenant(engine, migration_url: str, tid: str) -> None:
    """DDs + role + KBs + a doc per KB (titles carry the eval keywords)."""
    await _purge(migration_url, ["finance_data", "equipment_data", "hr_data"])
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, data_classification, status) "
                "VALUES "
                "('finance_data', :tid, '财务数据', '财务制度、报销与成本管理', 'internal', 'active'), "
                "('equipment_data', :tid, '设备数据', '设备运行、报警与维护', 'internal', 'active'), "
                "('hr_data', :tid, '人力资源', '员工、休假与公司政策', 'internal', 'active') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'routing-tester', '{}', 'all', "
                "'[{\"data_domain_id\": \"finance_data\"}, "
                "{\"data_domain_id\": \"equipment_data\"}, "
                "{\"data_domain_id\": \"hr_data\"}]') "
                "ON CONFLICT DO NOTHING"
            ),
            {"rid": "r-all", "tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'no-finance', '{}', 'all', '[{\"data_domain_id\": \"equipment_data\"}]') "
                "ON CONFLICT DO NOTHING"
            ),
            {"rid": "r-nofin", "tid": tid},
        )
        kbs = [
            ("kb-fin", "费用报销流程手册", "finance_data", "报销标准与流程说明", '[]'),
            ("kb-alarm", "报警阈值配置", "equipment_data", "设备报警阈值设定", '[]'),
            ("kb-manual", "设备手册", "equipment_data", "设备结构、主轴轴承更换周期", '[]'),
            ("kb-policy", "公司政策", "hr_data", "员工休假政策", '[]'),
        ]
        for kid, name, dd, desc, schema in kbs:
            await session.execute(
                text(
                    "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, "
                    "description, metadata_schema) VALUES (:kid, :tid, :name, :dd, :desc, :ms) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"kid": kid, "tid": tid, "name": name, "dd": dd, "desc": desc, "ms": schema},
            )


async def _index_eval_docs(engine, tid: str, monkeypatch) -> None:
    """Upload eval-case documents so KB summaries carry doc titles."""
    _install_stub(monkeypatch)
    docs = [
        ("kb-fin", "报销制度v1", "财务部报销制度：差旅报销标准与流程。"),
        ("kb-fin", "2024报销标准", "2024年报销标准：住宿每天500元，餐饮每天100元。"),
        ("kb-alarm", "报警阈值配置说明", "设备报警阈值：主轴温度超过85度触发报警。"),
        ("kb-manual", "主轴轴承更换周期", "主轴轴承更换周期：每运行8000小时更换一次。"),
        ("kb-policy", "员工休假政策", "员工年假10天，病假凭证明，产假按国家规定。"),
    ]
    for kb, title, content in docs:
        await create_document(engine, tid, kb, content, title=title)
    await build_routing_index(engine, tid)


# ── mechanism layer ──────────────────────────────────────────────────────────
async def test_build_index_idempotent_and_locality(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rt-loc"
    await _seed_tenant(engine, migrated, tid)

    stats1 = await build_routing_index(engine, tid)
    assert stats1["dds_rebuilt"] == 3 and stats1["kbs_rebuilt"] == 4, stats1
    # idempotent: same aggregate text → skipped (no embedding calls)
    stats2 = await build_routing_index(engine, tid)
    assert stats2["dds_skipped"] == 3 and stats2["kbs_skipped"] == 4, stats2

    # locality: uploading a doc must not change DD embeddings (title-free DDs)
    async with tenant_session(engine, tid) as session:
        row = await session.execute(
            text("SELECT routing_hash FROM data_domains WHERE data_domain_id = 'finance_data'")
        )
        dd_hash_before = row.scalar()
    await create_document(engine, tid, "kb-fin", "新增文档内容：费用报销补充规定。", title="报销补充规定")
    await build_routing_index(engine, tid, kb_ids=["kb-fin"])
    async with tenant_session(engine, tid) as session:
        row = await session.execute(
            text("SELECT routing_hash FROM data_domains WHERE data_domain_id = 'finance_data'")
        )
        assert row.scalar() == dd_hash_before  # DD untouched by doc ops


async def test_kb_rename_triggers_dd_rebuild(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rt-ren"
    await _seed_tenant(engine, migrated, tid)
    await build_routing_index(engine, tid)

    async with tenant_session(engine, tid) as session:
        before = (
            await session.execute(
                text("SELECT routing_hash FROM data_domains WHERE data_domain_id = 'finance_data'")
            )
        ).scalar()
    # KB rename → DD aggregate text changes → DD hash changes (C-7 locality scoped)
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text("UPDATE knowledge_bases SET name = '费用报销手册v2' WHERE knowledge_base_id = 'kb-fin'")
        )
        await session.commit()
    await build_routing_index(engine, tid, dd_ids=["finance_data"], kb_ids=["kb-fin"])
    async with tenant_session(engine, tid) as session:
        after = (
            await session.execute(
                text("SELECT routing_hash FROM data_domains WHERE data_domain_id = 'finance_data'")
            )
        ).scalar()
    assert before != after


async def test_route_query_fusion_and_permissions(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rt-route"
    await _seed_tenant(engine, migrated, tid)
    await build_routing_index(engine, tid)
    q_emb = await embed_query("设备报警阈值是多少")

    # keyword lane: "报警" hits equipment_data directly
    assert "equipment_data" in match_data_domains("设备报警阈值是多少")
    # vector lane should also rank equipment (bigrams overlap with DD desc)
    routed = await route_query(engine, tid, "设备报警阈值是多少", q_emb, "r-all")
    dd_ids = [c["data_domain_id"] for c in routed["candidate_dds"]]
    assert "equipment_data" in dd_ids, dd_ids
    assert routed["candidate_kbs"], "candidate KBs must not be empty"

    # permission: a role without finance access must not get finance candidates
    q2 = await embed_query("报销制度是什么")
    routed2 = await route_query(engine, tid, "报销制度是什么", q2, "r-nofin")
    dd_ids2 = [c["data_domain_id"] for c in routed2["candidate_dds"]]
    assert "finance_data" not in dd_ids2, dd_ids2
    # but the same query for an unrestricted role routes to finance
    routed3 = await route_query(engine, tid, "报销制度是什么", q2, "r-all")
    dd_ids3 = [c["data_domain_id"] for c in routed3["candidate_dds"]]
    assert "finance_data" in dd_ids3, dd_ids3


async def test_route_debug_shows_layers(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rt-dbg"
    await _seed_tenant(engine, migrated, tid)
    await build_routing_index(engine, tid)
    q_emb = await embed_query("报销制度是什么")
    dbg = await route_debug(engine, tid, "报销制度是什么", q_emb, "r-all")
    assert "corporate_data" in dbg["dd_keyword_hits"]  # "制度" keyword lane
    assert any(c["data_domain_id"] == "finance_data" for c in dbg["candidate_dds"])
    assert dbg["coverage"], "coverage self-check per domain"
    fin = next(d for d in dbg["coverage"] if d["data_domain_id"] == "finance_data")
    assert fin["missing_kb_names"] == [], "auto-aggregated description covers all KB names"


def test_description_coverage_check() -> None:
    assert check_description_coverage("财务数据。领域知识库：费用报销流程手册", ["费用报销流程手册"]) == []
    assert check_description_coverage("财务数据。", ["费用报销流程手册"]) == ["费用报销流程手册"]


def test_normalize_metadata_strong_validation() -> None:
    schema = [
        {"key": "year", "type": "number", "required": False},
        {"key": "department", "type": "string", "required": False},
        {"key": "archived", "type": "boolean", "required": False},
    ]
    assert normalize_metadata({"year": "2024", "department": "财务部"}, schema) == {
        "year": 2024,
        "department": "财务部",
    }
    assert normalize_metadata({"archived": "true"}, schema) == {"archived": True}
    with pytest.raises(ValueError):
        normalize_metadata({"year": "not-a-number"}, schema)
    with pytest.raises(ValueError):
        normalize_metadata({"unknown_key": 1}, schema)


# ── metadata filtering (type-sensitive containment on documents.metadata) ────
async def test_metadata_filtering_and_editing(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rt-meta"
    await _seed_tenant(engine, migrated, tid)
    # give kb-fin a metadata schema
    schema = json.dumps(
        [
            {"key": "year", "type": "number"},
            {"key": "department", "type": "string"},
        ],
        ensure_ascii=False,
    )
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text("UPDATE knowledge_bases SET metadata_schema = :ms WHERE knowledge_base_id = 'kb-fin'"),
            {"ms": schema},
        )
        await session.commit()

    doc = await create_document(
        engine, tid, "kb-fin", "2024年报销标准：住宿每天500元。", title="2024报销标准",
        metadata={"year": "2024", "department": "财务部"},
    )
    await create_chunks(engine, tid, doc["document_id"], "2024年报销标准：住宿每天500元。")
    await embed_chunks(engine, tid, [doc["document_id"]])
    doc2 = await create_document(engine, tid, "kb-fin", "2025年报销标准：住宿每天600元。", title="2025报销标准")
    await create_chunks(engine, tid, doc2["document_id"], "2025年报销标准：住宿每天600元。")
    await embed_chunks(engine, tid, [doc2["document_id"]])

    # auto fields injected with stable ids + common defaults
    async with tenant_session(engine, tid) as session:
        row = await session.execute(
            text("SELECT metadata FROM documents WHERE document_id = :did"), {"did": doc["document_id"]}
        )
        md = row.scalar()
    assert md["source_kb"] == "kb-fin" and md["data_domain"] == "finance_data"
    assert "data_classification" not in md  # mutable business value, not an auto field
    assert md["year"] == 2024 and isinstance(md["year"], int)  # type-normalized
    # common defaults (product request 2026-08-09)
    assert md["original_file_name"] == "2024报销标准"
    assert md["source"] == "upload"
    assert md["uploaded_at"] and md["updated_at"]
    uploaded_at = md["uploaded_at"]

    q_emb = await embed_query("报销标准")
    hits = await search_chunks(
        engine, tid, q_emb, "r-all", top_k=10, knowledge_base_ids=["kb-fin"],
        metadata_filters={"year": 2024}, embedding_dim=DIM,
    )
    assert len(hits) == 1 and hits[0]["document_id"] == doc["document_id"]

    # type-sensitive: string filter does NOT match stored number (A-2 decision)
    hits_str = await search_chunks(
        engine, tid, q_emb, "r-all", top_k=10, knowledge_base_ids=["kb-fin"],
        metadata_filters={"year": "2024"}, embedding_dim=DIM,
    )
    assert hits_str == []

    # edit manual metadata via update_document_metadata (merge + validate)
    updated = await update_document_metadata(engine, tid, doc["document_id"], {"department": "行政部"})
    assert updated["department"] == "行政部" and updated["year"] == 2024
    # updated_at refreshed by the server; uploaded_at snapshot unchanged
    assert updated["updated_at"] != uploaded_at
    assert updated["uploaded_at"] == uploaded_at
    # auto fields are rejected (incl. new common defaults)
    with pytest.raises(ValueError):
        await update_document_metadata(engine, tid, doc["document_id"], {"source_kb": "hacked"})
    with pytest.raises(ValueError):
        await update_document_metadata(engine, tid, doc["document_id"], {"original_file_name": "hacked"})
    # unknown key rejected
    with pytest.raises(ValueError):
        await update_document_metadata(engine, tid, doc["document_id"], {"bogus": 1})


async def test_kb_summary_text_override(migrated: str, app_url: str, monkeypatch) -> None:
    """KB parity with DD (2026-08-09): summary_text non-empty = manual override
    used for the Level-2 summary embedding; visible in the debug view."""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rt-sum"
    await _seed_tenant(engine, migrated, tid)
    await build_routing_index(engine, tid)

    override = "财务报销专属手册：费用标准、审批流程、发票要求"
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text("UPDATE knowledge_bases SET summary_text = :st WHERE knowledge_base_id = 'kb-fin'"),
            {"st": override},
        )
        await session.commit()
    await build_routing_index(engine, tid, kb_ids=["kb-fin"])

    # debug view shows the override as the summary text (not the auto-aggregate)
    q_emb = await embed_query("报销制度是什么")
    dbg = await route_debug(engine, tid, "报销制度是什么", q_emb, "r-all")
    fin_sum = next(s for s in dbg["kb_summaries"] if s["knowledge_base_id"] == "kb-fin")
    assert fin_sum["summary_text"] == override
    assert not fin_sum["stale"]


# ── effect layer: routing_eval pass rate ─────────────────────────────────────
def _parse_eval_cases() -> list[dict]:
    md = (FIXTURES / "routing_eval.md").read_text(encoding="utf-8")
    cases = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|") or "query" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        cases.append({"query": cells[1], "expected_dd": cells[2], "expected_kb": cells[3]})
    return cases


async def test_routing_eval_pass_rate(migrated: str, app_url: str, monkeypatch) -> None:
    """Mechanism-level run of the eval set: expected DD ∈ candidate top-N.

    CI uses the bigram stub (deterministic, shared vocabulary with the seeded
    DD descriptions); real semantic accuracy is measured in dev with bge-m3
    via scripts/verify_routing.py. Acceptance: ≥90% (design §7).
    """
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rt-eval"
    await _seed_tenant(engine, migrated, tid)
    await _index_eval_docs(engine, tid, monkeypatch)

    cases = _parse_eval_cases()
    assert len(cases) == 5, cases
    hits = 0
    misses: list[tuple[str, str, list[str]]] = []
    for case in cases:
        q_emb = await embed_query(case["query"])
        routed = await route_query(engine, tid, case["query"], q_emb, "r-all", top_n=5, top_k=3)
        dd_ids = [c["data_domain_id"] for c in routed["candidate_dds"]]
        if case["expected_dd"] in dd_ids:
            hits += 1
        else:
            misses.append((case["query"], case["expected_dd"], dd_ids))
    rate = hits / len(cases)
    assert rate >= 0.9, f"routing eval pass rate {rate:.0%} < 90%; misses: {misses}"
