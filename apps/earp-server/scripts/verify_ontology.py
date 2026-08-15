#!/usr/bin/env python3
"""Dev-only ontology retrieval eval with REAL embedding provider (bge-m3 via Ollama).

P2 acceptance (ontology-layer-design §9): entity-class questions — three-layer
retrieval (profile/graph + chunk RRF) must beat the pure-vector baseline by
≥10 points in P@5. CI validates the mechanism with bigram stub
(tests/test_ontology_search.py); this script measures semantic accuracy
against the live stack: seed DD/KB/docs + entity graph → run each question
through both paths → report per-case hits + pass rate.

Usage (from apps/earp-server, with PG + Ollama up, bge-m3 pulled):
    uv run python scripts/verify_ontology.py

Requires: Postgres migrated + embedding provider reachable (EARP_OLLAMA_*).

Manual smoke (optional): running this script also seeds the verify-ontology
tenant (DD/KB/docs + entity graph) for API/frontend manual testing — see
`tasks/ontology-soft-routing-task-breakdown.md` §人工测试指南 for curl steps.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from earp_server.config import Settings  # noqa: E402
from earp_server.infra.db import tenant_session  # noqa: E402
from earp_server.infra.ext.ext_embedding import init_app as _init_embedding  # noqa: E402
from earp_server.knowledge.chunk_service import create_chunks  # noqa: E402
from earp_server.knowledge.document_service import create_document  # noqa: E402
from earp_server.knowledge.embedding_service import embed_chunks, embed_query  # noqa: E402
from earp_server.knowledge.routing import build_routing_index, route_query  # noqa: E402
from earp_server.knowledge.search_service import search_chunks  # noqa: E402
from earp_server.ontology import abox_service, tbox_service  # noqa: E402

TENANT = "verify-ontology"
ROLE = "verify-role"

# 实体类问题集：期望 top-5 命中目标实体（三层经 profile/graph 命中；
# 纯 vector 只能靠文档内容——seed 文档刻意不含实体关系，作对照）。
CASES = [
    {"q": "CNC-01 由哪家供应商制造", "expect": ["上海某精机"], "note": "graph: manufactured_by"},
    {"q": "CNC-01 位于哪个工厂", "expect": ["华东一厂"], "note": "graph: located_in"},
    {"q": "CNC-01 属于哪条产线", "expect": ["A产线"], "note": "graph: belongs_to"},
    {"q": "A产线由谁负责", "expect": ["张工"], "note": "graph: responsible_for"},
    {"q": "高温报警由什么设备引起", "expect": ["CNC-01"], "note": "graph: caused_by"},
    {"q": "CNC-01 是什么设备", "expect": ["CNC-01"], "note": "profile: 实体档案"},
]

SEED = [
    ("equipment_data", "设备数据", "设备运行、报警与维护", "kb-manual", "设备手册", "设备结构与维护"),
    ("equipment_data", "设备数据", "设备运行、报警与维护", "kb-alarm", "报警阈值配置", "设备报警阈值设定"),
]

DOCS = [
    # 背景文档刻意不含实体关系答案（对照：纯 vector 无法从文档命中目标实体）
    ("kb-manual", "设备维护手册", "设备维护保养说明：定期检查主轴、轴承与润滑系统。"),
    ("kb-alarm", "报警阈值", "设备报警阈值设定：主轴温度超过85度触发报警。"),
]


async def _purge(engine) -> None:
    """跨租户清理 equipment_data 域同 id 数据（dev 库被 verify_routing/verify_chat 复用过）。"""
    ids = ["equipment_data"]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM chunks WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await conn.execute(
            text(
                "DELETE FROM documents WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await conn.execute(text("DELETE FROM knowledge_bases WHERE data_domain_id = ANY(:ids)"), {"ids": ids})
        await conn.execute(text("DELETE FROM data_domains WHERE data_domain_id = ANY(:ids)"), {"ids": ids})
        await conn.execute(text("DELETE FROM roles WHERE role_id = :rid"), {"rid": ROLE})
        await conn.execute(
            text(
                "DELETE FROM facts WHERE source_entity_id IN "
                "(SELECT entity_id FROM entities WHERE data_domain_id = ANY(:ids)) "
                "OR target_entity_id IN "
                "(SELECT entity_id FROM entities WHERE data_domain_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await conn.execute(
            text(
                "DELETE FROM entity_profiles WHERE entity_id IN "
                "(SELECT entity_id FROM entities WHERE data_domain_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await conn.execute(
            text(
                "DELETE FROM entity_timeline WHERE entity_id IN "
                "(SELECT entity_id FROM entities WHERE data_domain_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await conn.execute(text("DELETE FROM entities WHERE data_domain_id = ANY(:ids)"), {"ids": ids})


async def _seed(engine) -> None:
    async with tenant_session(engine, TENANT) as s:
        for dd_id, dd_name, dd_desc, kb_id, kb_name, kb_desc in SEED:
            await s.execute(
                text(
                    "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                    "data_classification, status) "
                    "VALUES (:dd, :t, :n, :d, 'internal', 'active') ON CONFLICT DO NOTHING"
                ),
                {"dd": dd_id, "t": TENANT, "n": dd_name, "d": dd_desc},
            )
            await s.execute(
                text(
                    "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, description) "
                    "VALUES (:kb, :t, :n, :dd, :d) ON CONFLICT DO NOTHING"
                ),
                {"kb": kb_id, "t": TENANT, "n": kb_name, "dd": dd_id, "d": kb_desc},
            )
        await s.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:r, :t, 'verify', '{}', 'all', "
                "'[{\"data_domain_id\": \"equipment_data\"}]') ON CONFLICT DO NOTHING"
            ),
            {"r": ROLE, "t": TENANT},
        )
    all_chunk_ids = []
    for kb, title, content in DOCS:
        doc = await create_document(engine, TENANT, kb, content, title=title)
        all_chunk_ids.extend(await create_chunks(engine, TENANT, doc["document_id"], content))
    await embed_chunks(engine, TENANT, all_chunk_ids)

    # 实体图谱（答案载体）：CNC-01 的关系 + 档案
    await tbox_service.init_tenant_tbox(engine, TENANT)
    plant = await abox_service.upsert_entity(
        engine, TENANT, "plant", "华东一厂", business_code="PLANT-1", data_domain_id="equipment_data"
    )
    line = await abox_service.upsert_entity(
        engine, TENANT, "production_line", "A产线", business_code="LINE-A", data_domain_id="equipment_data"
    )
    sup = await abox_service.upsert_entity(
        engine, TENANT, "supplier", "上海某精机", business_code="SUP-1", data_domain_id="equipment_data"
    )
    worker = await abox_service.upsert_entity(
        engine, TENANT, "employee", "张工", business_code="EMP-1", data_domain_id="equipment_data"
    )
    equip = await abox_service.upsert_entity(
        engine, TENANT, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
    )
    alarm = await abox_service.upsert_entity(
        engine, TENANT, "alarm", "高温报警", business_code="ALM-HT", data_domain_id="equipment_data"
    )
    await abox_service.add_fact(engine, TENANT, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.add_fact(engine, TENANT, equip["entity_id"], "located_in", plant["entity_id"])
    await abox_service.add_fact(engine, TENANT, equip["entity_id"], "belongs_to", line["entity_id"])
    await abox_service.add_fact(engine, TENANT, line["entity_id"], "responsible_for", worker["entity_id"])
    await abox_service.add_fact(engine, TENANT, alarm["entity_id"], "caused_by", equip["entity_id"])
    await abox_service.compile_profile(engine, TENANT, equip["entity_id"])
    await build_routing_index(engine, TENANT)


async def _three_layer(engine, settings, q: str, top_k: int = 5) -> list[dict]:
    from earp_server.ontology.search import knowledge_search

    emb = await embed_query(q)
    routed = await route_query(engine, TENANT, q, emb, ROLE)
    cand_dds = [d["data_domain_id"] for d in routed["candidate_dds"]]
    cand_kbs = [kb["knowledge_base_id"] for kb in routed["candidate_kbs"]] or None
    if not cand_dds:
        # 路由未命中任何 DD → 全租户 chunk（P2 决策 D4，与原行为一致）
        return await search_chunks(
            engine, TENANT, emb, ROLE, top_k=top_k,
            knowledge_base_ids=cand_kbs, embedding_dim=settings.embedding_dim,
        )
    return await knowledge_search(
        engine, TENANT, q, embedding=emb, role_id=ROLE,
        data_domain_ids=cand_dds, knowledge_base_ids=cand_kbs,
        top_k=top_k, embedding_dim=settings.embedding_dim,
    )


async def _pure_vector(engine, settings, q: str) -> list[dict]:
    """P2 之前的行为：route_query → search_chunks（候选 KB 限定），无实体层。"""
    emb = await embed_query(q)
    routed = await route_query(engine, TENANT, q, emb, ROLE)
    cand = [kb["knowledge_base_id"] for kb in routed["candidate_kbs"]] or None
    return await search_chunks(
        engine, TENANT, emb, ROLE, top_k=5,
        knowledge_base_ids=cand, embedding_dim=settings.embedding_dim,
    )


def _hit_three_layer(items: list[dict], expect: list[str]) -> bool:
    for it in items:
        if it.get("source") in ("profile", "graph"):
            title = it.get("title") or ""
            if any(e in title for e in expect):
                return True
    return False


def _layer_hit_all(items: list[dict], expect: list[str]) -> tuple[bool, list[str]]:
    """全量 layer 命中诊断：区分「实体层未命中」vs「命中但被 RRF top-5 截断」。"""
    titles = [f"{i.get('source')}:{i.get('title', '')}" for i in items if i.get("source") in ("profile", "graph")]
    hit = any(any(e in (i.get("title") or "") for e in expect) for i in items)
    return hit, titles


def _hit_pure_vector(chunks: list[dict], expect: list[str]) -> bool:
    # 纯 vector 只能靠文档原文——seed 文档不含实体名 → 期望不命中
    joined = " ".join(c.get("content", "") for c in chunks[:5])
    return any(e in joined for e in expect)


async def main() -> int:
    settings = Settings()
    _init_embedding(settings)
    # dev tool: use the migration (superuser) engine — BYPASSRLS so we can purge
    # cross-tenant same-id rows (knowledge_base_id / role_id 非复合主键，debt #7 模式)
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.migration_database_url)
    await _purge(engine)
    await _seed(engine)

    print(f"\n{'问题':<28} {'三层':<6} {'纯vector':<8} 说明")
    print("-" * 78)
    total = len(CASES)
    hits3 = hitsv = 0
    for case in CASES:
        items3 = await _three_layer(engine, settings, case["q"], top_k=5)
        itemsv = await _pure_vector(engine, settings, case["q"])
        h3 = _hit_three_layer(items3, case["expect"])
        hv = _hit_pure_vector(itemsv, case["expect"])
        hits3 += 1 if h3 else 0
        hitsv += 1 if hv else 0
        mark3 = "✓" if h3 else "✗"
        markv = "✓" if hv else "✗"
        print(f"{case['q']:<28} {mark3:<6} {markv:<8} {case['note']}")
        if not h3:
            items3_full = await _three_layer(engine, settings, case["q"], top_k=20)
            all_hit, layer_titles = _layer_hit_all(items3_full, case["expect"])
            if all_hit:
                print(f"    → 实体层已命中但被 RRF top-5 截断；graph/profile: {layer_titles}")
            else:
                print(f"    → 实体层未命中（lookup/tokenize 局限，QU Phase B 范畴）；graph/profile: {layer_titles}")
    p3 = hits3 / total * 100
    pv = hitsv / total * 100
    print("-" * 78)
    print(f"三层 P@5 命中率: {hits3}/{total} = {p3:.0f}%")
    print(f"纯 vector P@5 命中率: {hitsv}/{total} = {pv:.0f}%")
    print(f"提升: {p3 - pv:+.0f} 个百分点  (验收线 ≥ +10)")
    ok = (p3 - pv) >= 10
    print("结论:", "PASS ✅" if ok else "FAIL ❌")
    await engine.dispose()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
