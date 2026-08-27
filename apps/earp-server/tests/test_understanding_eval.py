"""Phase B — Understanding 评估集机制层 runner（Task 11，§17 门槛）。

CI 机制层：规则层（不真调 LLM）跑 understanding_eval.md（N≥100）；
dev 真模型（真 LLM 升级路径）由 scripts/verify_understanding.py 覆盖。

门槛（§17 Understanding 层）：
- intent 准确率 ≥ 85%（仅可靠子集计分；FALLBACK 回落即正确）
- 实体提及召回 ≥ 90%
- relation 准确率 ≥ 80%（标注 relation 必须 ∈ TBox）
- schema 合规率 = 100%（relation ∈ TBox、intent ∈ 枚举、confidence ∈ [0,1]）
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.ontology import abox_service, tbox_service
from earp_server.ontology.understanding import fetch_relation_candidates, understand

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _parse_eval_cases() -> list[dict]:
    md = (FIXTURES / "understanding_eval.md").read_text(encoding="utf-8")
    cases = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|") or "query" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        entities = []
        if len(cells) > 3 and cells[3]:
            for item in cells[3].split(";"):
                if ":" in item:
                    m, st = item.split(":", 1)
                    entities.append({"mention": m.strip(), "semantic_type": st.strip()})
        relations = [r.strip() for r in cells[4].split(";") if r.strip()]
        cases.append(
            {
                "num": cells[0],
                "query": cells[1],
                "intent": cells[2].upper(),
                "entities": entities,
                "relations": relations,
                "time": cells[5],
                "constraints": json.loads(cells[6]) if cells[6] else {},
                "note": cells[7] if len(cells) > 7 else "",
            }
        )
    return cases


def _context_from_note(note: str) -> dict | None:
    """note 含 `ctx:mention:semantic_type` 前缀 → 指代消解上下文。"""
    if note.startswith("ctx:"):
        mention, st = note[4:].split(":", 1)
        return {"last_entities": [{"mention": mention.strip(), "semantic_type": st.strip()}]}
    return None


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


async def _run_eval(cases: list[dict], engine: AsyncEngine, tid: str) -> dict:
    """逐条跑规则层，返回统计。"""
    stats: dict[str, Any] = {
        "n": len(cases),
        "intent_ok": 0,
        "intent_scored": 0,
        "ent_ok": 0,
        "ent_total": 0,
        "rel_ok": 0,
        "rel_scored": 0,
        "coref_cases": 0,
        "coref_ok": 0,  # C 系列 Task 4：指代消解命中（ctx 用例）
        "schema_violations": [],
        "intent_misses": [],
        "entity_misses": [],
        "relation_misses": [],
        "coref_misses": [],
    }
    rel_cands = await fetch_relation_candidates(engine, tid)
    tbox_ids = {c["relation_type_id"] for c in rel_cands}
    # fixture 自身合规：标注 relation 必须 ∈ TBox
    for case in cases:
        for rel in case["relations"]:
            assert rel in tbox_ids, f"fixture 标注 relation {rel} 不在 TBox（#{case['num']}）"

    for case in cases:
        ctx = _context_from_note(case["note"])
        r = await understand(engine, tid, case["query"], context=ctx)
        # intent（可靠子集计分；FALLBACK 回落即正确）
        stats["intent_scored"] += 1
        if case["intent"] == "FALLBACK":
            if r.intent is None:
                stats["intent_ok"] += 1
            else:
                stats["intent_misses"].append((case["num"], case["query"], "FALLBACK", r.intent.value))
        elif r.intent is not None and r.intent.value == case["intent"]:
            stats["intent_ok"] += 1
        else:
            stats["intent_misses"].append(
                (case["num"], case["query"], case["intent"], r.intent.value if r.intent else None)
            )
        # 实体提及召回（标注实体对被 result 命中的比例）
        for ent in case["entities"]:
            stats["ent_total"] += 1
            hit = any(m.mention == ent["mention"] and m.semantic_type == ent["semantic_type"] for m in r.entities)
            if hit:
                stats["ent_ok"] += 1
            else:
                stats["entity_misses"].append((case["num"], case["query"], ent["mention"]))
        # relation 准确率（期望集合 ⊆ result 集合）
        if case["relations"]:
            stats["rel_scored"] += 1
            got = {x.relation for x in r.relations}
            if all(rel in got for rel in case["relations"]):
                stats["rel_ok"] += 1
            else:
                stats["relation_misses"].append((case["num"], case["query"], case["relations"], sorted(got)))
        # 指代消解命中（C 系列 Task 4）：ctx 用例标注实体全部被解析即命中（≥80% 门槛）
        if case["note"].startswith("ctx:"):
            stats["coref_cases"] += 1
            if case["entities"] and all(
                any(m.mention == ent["mention"] and m.semantic_type == ent["semantic_type"] for m in r.entities)
                for ent in case["entities"]
            ):
                stats["coref_ok"] += 1
            else:
                stats["coref_misses"].append((case["num"], case["query"]))
        # schema 合规（result 侧）
        for rel in r.relations:
            if rel.relation not in tbox_ids:
                stats["schema_violations"].append((case["num"], case["query"], rel.relation))
    return stats


async def test_understanding_eval_gates(migrated: str, app_url: str) -> None:
    """机制层门槛：intent ≥85% / 实体提及 ≥90% / relation ≥80% / schema 100%。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "qu-eval"
    await _seed_eval_tenant(engine, tid)

    cases = _parse_eval_cases()
    assert len(cases) >= 100, f"评估集规模不足: {len(cases)} < 100"

    stats = await _run_eval(cases, engine, tid)
    intent_rate = stats["intent_ok"] / stats["intent_scored"]
    ent_rate = stats["ent_ok"] / stats["ent_total"] if stats["ent_total"] else 1.0
    rel_rate = stats["rel_ok"] / stats["rel_scored"] if stats["rel_scored"] else 1.0
    coref_rate = stats["coref_ok"] / stats["coref_cases"] if stats["coref_cases"] else 1.0

    print(
        f"\n[understanding_eval] n={stats['n']} "
        f"intent={stats['intent_ok']}/{stats['intent_scored']}={intent_rate:.0%} "
        f"entity={stats['ent_ok']}/{stats['ent_total']}={ent_rate:.0%} "
        f"relation={stats['rel_ok']}/{stats['rel_scored']}={rel_rate:.0%} "
        f"coref={stats['coref_ok']}/{stats['coref_cases']}={coref_rate:.0%} "
        f"schema_violations={len(stats['schema_violations'])}"
    )
    if stats["intent_misses"]:
        print("  intent misses:", stats["intent_misses"][:8])
    if stats["entity_misses"]:
        print("  entity misses:", stats["entity_misses"][:8])
    if stats["relation_misses"]:
        print("  relation misses:", stats["relation_misses"][:8])
    if stats["coref_misses"]:
        print("  coref misses:", stats["coref_misses"][:8])

    assert stats["schema_violations"] == [], stats["schema_violations"]
    assert intent_rate >= 0.85, f"intent {intent_rate:.0%} < 85%"
    assert ent_rate >= 0.90, f"entity recall {ent_rate:.0%} < 90%"
    assert rel_rate >= 0.80, f"relation {rel_rate:.0%} < 80%"
    assert coref_rate >= 0.80, f"指代命中率 {coref_rate:.0%} < 80%（C 系列 Task 4 门槛）"
