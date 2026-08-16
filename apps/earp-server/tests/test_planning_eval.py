"""Phase C — Plan 层评估（Task 9，§17 Plan 层门槛）。

复用 understanding_eval.md（N=111 标注 intent）端到端验证：
understand → build_structured_query → select_plan（§11.2 映射表）→ 策略名。

门槛（§17 Plan 层）：
- 策略命中率 ≥ 95%（期望策略由标注 intent 按 §11.2 推导；FALLBACK 回落即命中）
- 非法调用 = 0、越权访问 = 0、Command = 0（trace 扫描在 test_planning.py 覆盖）
"""

from __future__ import annotations

import pathlib

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.ontology import abox_service, tbox_service
from earp_server.ontology.planning import select_plan
from earp_server.ontology.understanding import build_structured_query, understand

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _parse_cases() -> list[dict]:
    md = (FIXTURES / "understanding_eval.md").read_text(encoding="utf-8")
    cases = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|") or "query" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        cases.append(
            {"num": cells[0], "query": cells[1], "intent": cells[2].upper(), "note": cells[7] if len(cells) > 7 else ""}
        )
    return cases


def _expected_plan(intent_label: str) -> str:
    """§11.2 映射表：标注 intent → 期望策略（FALLBACK 回落 plan_fact 即正确，QP-14）。"""
    if intent_label in ("FACT", "FALLBACK", "CAUSAL", "MIXED"):
        return "plan_fact"
    if intent_label in ("RELATION", "ATTRIBUTE", "LIST", "MULTI_HOP"):
        return "plan_relation"
    if intent_label in ("AGGREGATION", "COMPARISON", "TREND"):
        return "plan_aggregation"
    return "plan_fact"


async def _seed_eval_tenant(engine: AsyncEngine, tid: str) -> None:
    """评估租户实体/事实（与 fixture 标注的 mention/relation 对齐）。"""
    await tbox_service.init_tenant_tbox(engine, tid)
    e = {
        "equip": await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01", business_code="CNC-01"),
        "plant": await abox_service.upsert_entity(engine, tid, "plant", "华东一厂", business_code="PL-1"),
        "line": await abox_service.upsert_entity(engine, tid, "production_line", "A产线", business_code="LN-A"),
        "supplier": await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-1"),
        "emp": await abox_service.upsert_entity(engine, tid, "employee", "张工", business_code="EMP-1"),
        "alarm": await abox_service.upsert_entity(engine, tid, "alarm", "高温报警"),
        "comp": await abox_service.upsert_entity(engine, tid, "component", "主轴轴承", business_code="CMP-1"),
        "product": await abox_service.upsert_entity(engine, tid, "product", "P-100", business_code="P-100"),
    }
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "manufactured_by", e["supplier"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "located_in", e["plant"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "belongs_to", e["line"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["alarm"]["entity_id"], "caused_by", e["equip"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["comp"]["entity_id"], "belongs_to", e["equip"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["comp"]["entity_id"], "supplied_by", e["supplier"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["line"]["entity_id"], "responsible_for", e["emp"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "maintained_by", e["emp"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["line"]["entity_id"], "produces", e["product"]["entity_id"])


async def test_plan_eval_strategy_hit_rate(migrated: str, app_url: str) -> None:
    """策略命中率 ≥ 95%（机制层规则 only，不真调 LLM）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "qu-plan-eval"
    await _seed_eval_tenant(engine, tid)

    cases = _parse_cases()
    assert len(cases) >= 100
    hits = 0
    misses: list[tuple[str, str, str, str]] = []
    for case in cases:
        r = await understand(engine, tid, case["query"])
        sq = build_structured_query(r)
        sel = select_plan(sq)
        expected = _expected_plan(case["intent"])
        if sel.plan_name == expected:
            hits += 1
        else:
            misses.append((case["num"], case["query"], expected, sel.plan_name))
    rate = hits / len(cases)
    print(f"\n[plan_eval] strategy hit rate = {hits}/{len(cases)} = {rate:.0%} (acceptance ≥ 95%)")
    if misses:
        print("  misses:", misses[:8])
    assert rate >= 0.95, f"strategy hit rate {rate:.0%} < 95%"
