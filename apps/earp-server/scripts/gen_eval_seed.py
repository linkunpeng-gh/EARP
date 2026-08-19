#!/usr/bin/env python3
"""Generate ontology/eval_seed.py from the evaluation fixtures (B6, D2).

fixtures remain the canonical CI source (hermetic); this generator materialises
the same cases as committed Python data so the platform seed does not depend on
tests/fixtures at runtime. Run from apps/earp-server:

    uv run python scripts/gen_eval_seed.py

Output: src/earp_server/ontology/eval_seed.py  (do not hand-edit)
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "src" / "earp_server" / "ontology" / "eval_seed.py"

HEADER = '''"""Builtin evaluation sets (B6, D2) — GENERATED FILE, do not hand-edit.

真源：tests/fixtures/routing_eval.md + understanding_eval.md（CI 机制层 runner 直接读）；
本文件由 scripts/gen_eval_seed.py 生成（平台种子不依赖 tests/fixtures 运行时存在）。
再生成：uv run python scripts/gen_eval_seed.py
"""

# ruff: noqa: E501  （生成的长 JSON 行）

'''

_THRESHOLDS = {
    "routing": {"dd_accuracy": 0.90, "kb_accuracy": 0.90},
    "understanding": {
        "intent_accuracy": 0.85,
        "entity_recall": 0.90,
        "relation_accuracy": 0.80,
        "schema_violations": 0,
    },
    "planning": {"strategy_hit_rate": 0.95},
}

# D4-1: 内置模板版本——模板改进后递增，老租户同步可见（eval_sets.seed_version）
_SEED_VERSION = 1

# T3 D6: 每 kind 参与 gate 判定的指标名清单（门槛覆盖校验用；
# 注意：routing 仅 dd_accuracy 参与 gate——kb_accuracy 是报告项（既有行为，
# 保持；understanding/planning 与 _THRESHOLDS 键对齐）
_GATED_METRICS: dict[str, list[str]] = {
    "routing": ["dd_accuracy"],
    "understanding": ["intent_accuracy", "entity_recall", "relation_accuracy", "schema_violations"],
    "planning": ["strategy_hit_rate"],
}

_DESCRIPTIONS = {
    "routing": "路由评估集（设计 §7）——软路由/元数据过滤/三层检索验收基线",
    "understanding": "Query Understanding 评估集（QU v0.3 §17）——规则层 + LLM 升级路径验收基线",
    "planning": "Plan 层评估集（QU v0.3 §17 Plan 层）——select_plan 映射 + 策略执行验收基线",
}

_NAMES = {
    "routing": "路由评估集",
    "understanding": "理解层评估集",
    "planning": "Plan 层评估集",
}


def _md_rows(path: pathlib.Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or "query" in line or "---" in line:
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def _build_routing() -> list[dict]:
    cases = []
    for cells in _md_rows(FIXTURES / "routing_eval.md"):
        cases.append(
            {
                "query": cells[1],
                "expected": {"data_domain_id": cells[2], "knowledge_base_id": cells[3]},
                "note": cells[4] if len(cells) > 4 else "",
            }
        )
    assert len(cases) == 5, f"routing eval must have 5 cases, got {len(cases)}"
    return cases


def _parse_understanding_row(cells: list[str]) -> dict:
    entities = []
    if len(cells) > 3 and cells[3]:
        for item in cells[3].split(";"):
            if ":" in item:
                m, st = item.split(":", 1)
                entities.append({"mention": m.strip(), "semantic_type": st.strip()})
    relations = [r.strip() for r in cells[4].split(";") if r.strip()]
    return {
        "query": cells[1],
        "expected": {
            "intent": cells[2].upper(),
            "entities": entities,
            "relations": relations,
            "time": cells[5] if len(cells) > 5 else "",
            "constraints": json.loads(cells[6]) if len(cells) > 6 and cells[6] else {},
        },
        "note": cells[7] if len(cells) > 7 else "",
    }


def _build_understanding() -> list[dict]:
    cases = [_parse_understanding_row(cells) for cells in _md_rows(FIXTURES / "understanding_eval.md")]
    assert len(cases) >= 100, f"understanding eval must have ≥100 cases, got {len(cases)}"
    return cases


def _build_planning() -> list[dict]:
    """planning eval reuses the understanding annotations (intent label → §11.2 mapping)."""
    cases = []
    for cells in _md_rows(FIXTURES / "understanding_eval.md"):
        cases.append(
            {
                "query": cells[1],
                "expected": {"intent_label": cells[2].upper()},
                "note": cells[7] if len(cells) > 7 else "",
            }
        )
    assert len(cases) >= 100, f"planning eval must have ≥100 cases, got {len(cases)}"
    return cases


def _emit() -> str:
    sets = {
        "routing": {"name": _NAMES["routing"], "description": _DESCRIPTIONS["routing"], "cases": _build_routing()},
        "understanding": {
            "name": _NAMES["understanding"],
            "description": _DESCRIPTIONS["understanding"],
            "cases": _build_understanding(),
        },
        "planning": {"name": _NAMES["planning"], "description": _DESCRIPTIONS["planning"], "cases": _build_planning()},
    }
    out = [HEADER, "THRESHOLDS: dict[str, dict[str, float]] = " + json.dumps(_THRESHOLDS, ensure_ascii=False, indent=2)]
    out.append("")
    out.append(f"SEED_VERSION: int = {_SEED_VERSION}")
    out.append("")
    out.append("GATED_METRICS: dict[str, list[str]] = " + json.dumps(_GATED_METRICS, ensure_ascii=False, indent=2))
    out.append("")
    out.append("")
    out.append("BUILTIN_EVAL_SETS: dict[str, dict] = {")
    for kind, spec in sets.items():
        out.append(f"    {kind!r}: {{")
        out.append(f"        'name': {spec['name']!r},")
        out.append(f"        'description': {spec['description']!r},")
        out.append("        'cases': [")
        for c in spec["cases"]:
            out.append("            " + json.dumps(c, ensure_ascii=False))
            out[-1] += ","
        out.append("        ],")
        out.append("    },")
    out.append("}")
    out.append("")
    out.append("KIND_ORDER = ('routing', 'understanding', 'planning')")
    out.append("")
    return "\n".join(out)


def main() -> int:
    OUT.write_text(_emit(), encoding="utf-8")
    ns: dict = {}
    exec(OUT.read_text(encoding="utf-8"), ns)
    for kind in ("routing", "understanding", "planning"):
        n = len(ns["BUILTIN_EVAL_SETS"][kind]["cases"])
        print(f"  {kind}: {n} cases")
        for i, c in enumerate(ns["BUILTIN_EVAL_SETS"][kind]["cases"]):
            assert isinstance(c["query"], str) and c["query"], f"{kind} case {i} bad query"
    print(f"wrote {OUT}")

    # consistency spot-checks against fixtures
    routing = _md_rows(FIXTURES / "routing_eval.md")
    assert ns["BUILTIN_EVAL_SETS"]["routing"]["cases"][0]["query"] == routing[0][1]
    assert ns["BUILTIN_EVAL_SETS"]["routing"]["cases"][0]["expected"]["data_domain_id"] == routing[0][2]
    und = _md_rows(FIXTURES / "understanding_eval.md")
    assert ns["BUILTIN_EVAL_SETS"]["understanding"]["cases"][0]["query"] == und[0][1]
    assert ns["BUILTIN_EVAL_SETS"]["planning"]["cases"][0]["expected"]["intent_label"] == und[0][2].upper()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
