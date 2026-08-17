#!/usr/bin/env python3
"""Dev-only Planning eval with the REAL LLM upgrade path (qwen via Ollama).

CI runs the mechanism layer (test_planning.py + test_planning_eval.py); this
script measures the full chain against the live stack: understand (+LLM upgrade)
→ select_plan → strategy execution (real DB: routing/search/graph) → PlanResult,
reporting strategy hit rate (§17 Plan ≥95%) + per-strategy p95 latency (§11.3).

Usage (from apps/earp-server, with services up):
    uv run python scripts/verify_planning.py

Requires: Postgres migrated + LLM reachable (EARP_OLLAMA_BASE_URL / DB config).
"""

from __future__ import annotations

import asyncio
import pathlib
import statistics
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from earp_server.config import Settings  # noqa: E402
from earp_server.infra.db import tenant_session  # noqa: E402
from earp_server.infra.ext.ext_embedding import init_app as _init_embedding  # noqa: E402
from earp_server.ontology import abox_service, tbox_service  # noqa: E402
from earp_server.ontology.planning import execute_plan, select_plan  # noqa: E402
from earp_server.ontology.understanding import (  # noqa: E402
    Intent,
    StructuredQuery,
    build_structured_query,
    understand,
    upgrade_with_llm,
)

EVAL_MD = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "understanding_eval.md"
TENANT = "verify-planning"
RELIABLE = {"FACT", "RELATION", "AGGREGATION"}
ALLOWED_TRACE = {
    "RESOLVE_ENTITY",
    "GRAPH_QUERY",
    "VECTOR_SEARCH",
    "KEYWORD_SEARCH",
    "METADATA_FILTER",
    "DD_ROUTING",
    "KB_ROUTING",
    "CAPABILITY_QUERY",
    "FUSION_RERANK",
    "ANSWER",
}


def _parse_cases() -> list[dict]:
    cases = []
    for line in EVAL_MD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or "query" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        cases.append({"num": cells[0], "query": cells[1], "intent": cells[2].upper()})
    return cases


def _expected_plan(intent_label: str) -> str:
    if intent_label in ("FACT", "FALLBACK", "CAUSAL", "MIXED"):
        return "plan_fact"
    if intent_label in ("RELATION", "ATTRIBUTE", "LIST", "MULTI_HOP"):
        return "plan_relation"
    if intent_label in ("AGGREGATION", "COMPARISON", "TREND"):
        return "plan_aggregation"
    return "plan_fact"


def _intent_from_label(label: str) -> Intent:
    """标注 label → StructuredQuery.intent（FALLBACK 用 FACT 兜底——规则层回落语义）。"""
    if label in Intent.__members__:
        return Intent[label]
    return Intent.FACT


async def _seed(engine, tid: str) -> None:
    """实体图 + facts + KB/docs/chunks + query capability + 登录身份（plan_fact 检索 / plan_aggregation 候选）。"""
    from earp_server.knowledge.chunk_service import create_chunks
    from earp_server.knowledge.document_service import create_document
    from earp_server.knowledge.embedding_service import embed_chunks
    from earp_server.knowledge.routing import build_routing_index

    async with engine.begin() as conn:
        # tenants 无 RLS（顶层表）；users RLS-scoped——登录身份（/auth/login 校验存在性）
        await conn.execute(
            text("INSERT INTO tenants (tenant_id, name, status) VALUES (:tid, :name, 'active') "
                 "ON CONFLICT (tenant_id) DO NOTHING"),
            {"tid": tid, "name": "Verify Planning"},
        )
        await conn.execute(
            text("INSERT INTO users (user_id, tenant_id, name, email) "
                 "VALUES ('vp-user', :tid, 'VP', 'vp@local') ON CONFLICT (user_id) DO NOTHING"),
            {"tid": tid},
        )
        for tbl in ("entity_timeline", "entity_profiles", "facts", "entities", "relation_types", "entity_types"):
            await conn.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :tid"), {"tid": tid})
        for tbl in ("chunks", "documents", "knowledge_bases", "data_domains"):
            await conn.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :tid"), {"tid": tid})
    await tbox_service.init_tenant_tbox(engine, tid)

    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) "
                "VALUES ('equipment_data', :tid, '设备数据', '设备报警维护', 'internal', 'active'), "
                "('finance_data', :tid, '财务数据', '财务制度报销', 'internal', 'active') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES ('vp-role', :tid, 'vp-all', '{}', 'all', "
                '\'[{"data_domain_id": "equipment_data"}, {"data_domain_id": "finance_data"}]\') '
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, description) "
                "VALUES ('kb-vp-maint', :tid, '设备维护手册', 'equipment_data', '维护'), "
                "('kb-vp-alarm', :tid, '报警阈值配置', 'equipment_data', '报警'), "
                "('kb-vp-fin', :tid, '费用报销手册', 'finance_data', '报销') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
    docs = [
        ("kb-vp-maint", "维护手册v1", "设备维护：主轴轴承更换周期为每季度一次。"),
        ("kb-vp-alarm", "报警阈值", "设备报警阈值：主轴温度超过85度触发报警。"),
        ("kb-vp-fin", "报销制度v1", "财务报销标准：2024年住宿每天500元。"),
    ]
    all_chunks: list[str] = []
    for kb, title, content in docs:
        doc = await create_document(engine, tid, kb, content, title=title)
        all_chunks.extend(await create_chunks(engine, tid, doc["document_id"], content))
    try:
        await embed_chunks(engine, tid, all_chunks)
    except Exception:
        print("  [warn] embed_chunks failed — vector lane degraded")
    await build_routing_index(engine, tid)

    e = {
        "equip": await abox_service.upsert_entity(
            engine, tid, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
        ),
        "plant": await abox_service.upsert_entity(
            engine, tid, "plant", "华东一厂", business_code="PL-1", data_domain_id="equipment_data"
        ),
        "line": await abox_service.upsert_entity(
            engine, tid, "production_line", "A产线", business_code="LN-A", data_domain_id="equipment_data"
        ),
        "supplier": await abox_service.upsert_entity(
            engine, tid, "supplier", "上海某精机", business_code="SUP-1", data_domain_id="equipment_data"
        ),
        "emp": await abox_service.upsert_entity(
            engine, tid, "employee", "张工", business_code="EMP-1", data_domain_id="equipment_data"
        ),
        "alarm": await abox_service.upsert_entity(engine, tid, "alarm", "高温报警", data_domain_id="equipment_data"),
        "comp": await abox_service.upsert_entity(
            engine, tid, "component", "主轴轴承", business_code="CMP-1", data_domain_id="equipment_data"
        ),
    }
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "manufactured_by", e["supplier"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "located_in", e["plant"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "belongs_to", e["line"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["alarm"]["entity_id"], "caused_by", e["equip"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["comp"]["entity_id"], "belongs_to", e["equip"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["comp"]["entity_id"], "supplied_by", e["supplier"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["line"]["entity_id"], "responsible_for", e["emp"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "maintained_by", e["emp"]["entity_id"])

    cap_id = "cap-vp-alarm"
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                f"VALUES ('{cap_id}', :tid, 'equipment', 'query_equipment_alarm', 'query', "
                "'{}', '{}', '{{alarm:read}}', '1.0.0') ON CONFLICT (capability_id) DO NOTHING"
            ),
            {"tid": tid},
        )
    await tbox_service.map_capability_entity(engine, tid, cap_id, "equipment", "read")


async def main() -> int:
    settings = Settings()
    _init_embedding(settings)  # 真实 embedding（bge-m3）用于语义检索
    engine = create_async_engine(settings.migration_database_url)
    await _seed(engine, TENANT)

    cases = _parse_cases()
    stats: dict[str, Any] = {
        "n": len(cases),
        "mapping_hit": 0,  # §17 Plan 门槛：select_plan 映射正确性（标注口径）
        "executed": {},  # 端到端实际执行策略分布（LLM 升级影响，报告不 gate）
        "lat": {"plan_fact": [], "plan_relation": [], "plan_aggregation": []},
        "evidence_channels": {},
        "illegal_trace": [],
        "fallbacks": {},
    }
    # ── Plan 层门槛（§17）：标注 intent → select_plan 映射正确性（纯函数，不受 LLM 影响）──
    for case in cases:
        expected = _expected_plan(case["intent"])
        q_ann = StructuredQuery(intent=_intent_from_label(case["intent"]), confidence=0.9)
        if select_plan(q_ann).plan_name == expected:
            stats["mapping_hit"] += 1
    # ── 端到端执行报告（理解 + 规划 + 策略函数，dev 真 LLM）──
    for case in cases:
        r = await understand(engine, TENANT, case["query"])
        r = await upgrade_with_llm(engine, TENANT, case["query"], r, settings=settings)
        sq = build_structured_query(r)
        _, plan = await execute_plan(
            engine,
            TENANT,
            "vp-role",
            case["query"],
            sq,
            settings=settings,
        )
        stats["executed"][plan.plan_name] = stats["executed"].get(plan.plan_name, 0) + 1
        for t in plan.trace:
            if t.type not in ALLOWED_TRACE:
                stats["illegal_trace"].append((case["num"], t.type))
        stats["lat"].setdefault(plan.plan_name, []).append(plan.latency_ms)
        for e in plan.evidence:
            stats["evidence_channels"][e.channel] = stats["evidence_channels"].get(e.channel, 0) + 1
        if plan.fallback_reason:
            stats["fallbacks"][plan.plan_name] = stats["fallbacks"].get(plan.plan_name, 0) + 1

    mapping_rate = stats["mapping_hit"] / stats["n"]
    print(
        f"\n[verify_planning] n={stats['n']} select_plan mapping hit="
        f"{stats['mapping_hit']}/{stats['n']}={mapping_rate:.0%} (≥95%)"
    )
    print(f"  executed plans: {stats['executed']} (LLM 升级影响理解层，Phase B 已计 intent 准确率)")
    for name, lats in stats["lat"].items():
        if lats:
            p95 = sorted(lats)[int(len(lats) * 0.95) - 1]
            print(
                f"  {name:16} p95={p95}ms mean={statistics.mean(lats):.0f}ms "
                "(budget: fact 800 / relation 500 / agg 600)"
            )
    print(f"  evidence channels: {stats['evidence_channels']}")
    print(f"  fallbacks: {stats['fallbacks']}")
    print(f"  illegal trace steps: {len(stats['illegal_trace'])} {stats['illegal_trace'][:3]}")
    ok = mapping_rate >= 0.95 and not stats["illegal_trace"]
    print(f"\ngates: {'PASS ✅' if ok else 'FAIL ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
