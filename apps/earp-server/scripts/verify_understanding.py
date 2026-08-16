#!/usr/bin/env python3
"""Dev-only Understanding eval with the REAL LLM upgrade path (qwen via Ollama).

CI runs the mechanism layer (rule-only, test_understanding_eval.py); this script
measures the full understanding chain against the live stack: seed TBox/ABox →
run understanding_eval.md cases → rule layer + low-confidence LLM upgrade →
report gates (design §17 Understanding layer).

Usage (from apps/earp-server, with services up):
    uv run python scripts/verify_understanding.py

Requires: Postgres migrated + LLM reachable (EARP_OLLAMA_BASE_URL / DB model config).
"""

from __future__ import annotations

import asyncio
import pathlib
import statistics
import sys
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from earp_server.config import Settings  # noqa: E402
from earp_server.ontology import abox_service, tbox_service  # noqa: E402
from earp_server.ontology.understanding import (  # noqa: E402
    fetch_relation_candidates,
    understand,
    upgrade_with_llm,
)

EVAL_MD = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "understanding_eval.md"
TENANT = "verify-understanding"
RELIABLE = {"FACT", "RELATION", "AGGREGATION"}


def _parse_cases() -> list[dict]:
    cases = []
    for line in EVAL_MD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or "query" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        entities = []
        if cells[3]:
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
                "note": cells[7] if len(cells) > 7 else "",
            }
        )
    return cases


def _context_from_note(note: str) -> dict | None:
    if note.startswith("ctx:"):
        mention, st = note[4:].split(":", 1)
        return {"last_entities": [{"mention": mention.strip(), "semantic_type": st.strip()}]}
    return None


async def _seed(engine, tid: str) -> None:
    """评估租户实体/事实（与 fixture 标注对齐）；purge 本租户旧数据（migration 引擎无 RLS）。"""
    async with engine.begin() as conn:
        for tbl in ("entity_timeline", "entity_profiles", "facts", "entities", "relation_types", "entity_types"):
            await conn.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :tid"), {"tid": tid})
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


async def main() -> int:
    settings = Settings()
    engine = create_async_engine(settings.migration_database_url)
    await _seed(engine, TENANT)

    cases = _parse_cases()
    rel_cands = await fetch_relation_candidates(engine, TENANT)
    tbox_ids = {c["relation_type_id"] for c in rel_cands}
    for case in cases:
        for rel in case["relations"]:
            assert rel in tbox_ids, f"fixture relation {rel} 不在 TBox（#{case['num']}）"

    stats: dict[str, Any] = {
        "n": len(cases), "rule_only": 0, "llm_upgraded": 0,
        "intent_ok": 0, "intent_scored": 0,
        "ent_ok": 0, "ent_total": 0,
        "rel_ok": 0, "rel_scored": 0,
        "schema_violations": [], "latencies_ms": [], "llm_latencies_ms": [],
    }
    for case in cases:
        ctx = _context_from_note(case["note"])
        t0 = time.monotonic()
        r = await understand(engine, TENANT, case["query"], context=ctx)
        stats["latencies_ms"].append(round((time.monotonic() - t0) * 1000, 1))
        t1 = time.monotonic()
        r = await upgrade_with_llm(engine, TENANT, case["query"], r, settings=settings)
        stats["llm_latencies_ms"].append(round((time.monotonic() - t1) * 1000, 1))
        if r.llm_upgraded:
            stats["llm_upgraded"] += 1
            if not r.field_reasons.get("llm"):
                stats["rule_only"] += 0  # upgraded successfully
        else:
            stats["rule_only"] += 1

        # intent（可靠子集计分；FALLBACK = 回落即正确，最终 intent 非可靠子集即回落）
        stats["intent_scored"] += 1
        final_intent = r.intent.value if r.intent else None
        if case["intent"] == "FALLBACK":
            if final_intent is None or final_intent not in RELIABLE:
                stats["intent_ok"] += 1
        elif final_intent == case["intent"]:
            stats["intent_ok"] += 1

        for ent in case["entities"]:
            stats["ent_total"] += 1
            if any(m.mention == ent["mention"] and m.semantic_type == ent["semantic_type"] for m in r.entities):
                stats["ent_ok"] += 1
        if case["relations"]:
            stats["rel_scored"] += 1
            got = {x.relation for x in r.relations}
            if all(rel in got for rel in case["relations"]):
                stats["rel_ok"] += 1
        for rel in r.relations:
            if rel.relation not in tbox_ids:
                stats["schema_violations"].append((case["num"], case["query"], rel.relation))

    intent_rate = stats["intent_ok"] / stats["intent_scored"]
    ent_rate = stats["ent_ok"] / stats["ent_total"] if stats["ent_total"] else 1.0
    rel_rate = stats["rel_ok"] / stats["rel_scored"] if stats["rel_scored"] else 1.0
    lats = sorted(stats["latencies_ms"])
    p95 = lats[int(len(lats) * 0.95) - 1] if lats else 0
    print(
        f"\n[verify_understanding] n={stats['n']} "
        f"rule_only={stats['rule_only']} llm_upgraded={stats['llm_upgraded']}\n"
        f"  intent={stats['intent_ok']}/{stats['intent_scored']}={intent_rate:.0%} (≥85%)\n"
        f"  entity={stats['ent_ok']}/{stats['ent_total']}={ent_rate:.0%} (≥90%)\n"
        f"  relation={stats['rel_ok']}/{stats['rel_scored']}={rel_rate:.0%} (≥80%)\n"
        f"  schema_violations={len(stats['schema_violations'])}\n"
        f"  rule latency p95={p95}ms (budget <50ms) mean={statistics.mean(stats['latencies_ms']):.1f}ms "
        f"| llm upgrade mean={statistics.mean(stats['llm_latencies_ms']):.0f}ms"
    )
    if stats["schema_violations"]:
        print("  schema violations:", stats["schema_violations"])
    ok = (
        not stats["schema_violations"]
        and intent_rate >= 0.85
        and ent_rate >= 0.90
        and rel_rate >= 0.80
    )
    print(f"\ngates: {'PASS ✅' if ok else 'FAIL ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
