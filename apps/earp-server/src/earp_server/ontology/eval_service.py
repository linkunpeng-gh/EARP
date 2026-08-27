"""评估集管理 + 跑分引擎（B6，D1/D3/D4/D5）。

三套内置评估（routing/understanding/planning）落库（按租户惰性种子，tbox 先例）；
跑分支持 rules（规则层，CI 机制层口径）与 llm（真 LLM 升级路径，dev 口径）两模式，
后台任务执行（start_run 返回即跑，run_eval_task 落结果），按 §17 / 设计 §7 门槛判定 gates。

评分逻辑对齐 CI runner（test_routing effect layer / test_understanding_eval /
test_planning_eval），平台跑分与 CI 口径一致。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session
from earp_server.ontology.eval_seed import (
    BUILTIN_EVAL_SETS,
    GATED_METRICS,
    KIND_ORDER,
    SEED_VERSION,
    THRESHOLDS,
)
from earp_server.ontology.understanding import Intent

logger = logging.getLogger(__name__)

VALID_KINDS = ("routing", "understanding", "planning")
VALID_MODES = ("rules", "llm")


class EvalError(Exception):
    """评估集业务错误（404/409/400 语义由路由层映射）。"""


# ── 种子（D2：惰性初始化，tbox 先例）───────────────────────────────────────
async def ensure_eval_sets(engine: AsyncEngine, tenant_id: str) -> None:
    """无评估集时按租户插入 3 套内置种子（幂等）。"""
    async with tenant_session(engine, tenant_id) as session:
        row = await session.execute(text("SELECT 1 FROM eval_sets WHERE tenant_id = :tid LIMIT 1"), {"tid": tenant_id})
        if row.fetchone():
            return
        for kind in KIND_ORDER:
            spec = BUILTIN_EVAL_SETS[kind]
            set_id = f"evs-{tenant_id}-{kind}"
            await session.execute(
                text(
                    "INSERT INTO eval_sets (eval_set_id, tenant_id, kind, name, description, source, thresholds, "
                    "seed_version) VALUES (:sid, :tid, :kind, :name, :desc, 'builtin', :thr, :ver) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "sid": set_id,
                    "tid": tenant_id,
                    "kind": kind,
                    "name": spec["name"],
                    "desc": spec["description"],
                    "thr": json.dumps(THRESHOLDS[kind]),
                    "ver": SEED_VERSION,
                },
            )
            for i, case in enumerate(spec["cases"], 1):
                await session.execute(
                    text(
                        "INSERT INTO eval_cases (case_id, tenant_id, eval_set_id, sort_order, query, expected, note, "
                        "source) VALUES (:cid, :tid, :sid, :ord, :q, :exp, :note, 'builtin') "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "cid": f"evc-{tenant_id}-{kind}-{i:03d}",
                        "tid": tenant_id,
                        "sid": set_id,
                        "ord": i,
                        "q": case["query"],
                        "exp": json.dumps(case["expected"]),
                        "note": case.get("note") or "",
                    },
                )


# ── 评估集 CRUD ────────────────────────────────────────────────────────────
async def list_eval_sets(engine: AsyncEngine, tenant_id: str) -> list[dict]:
    """集合列表 + case_count + 最新一次跑分摘要（overall 徽标用）。"""
    await ensure_eval_sets(engine, tenant_id)
    async with tenant_session(engine, tenant_id) as session:
        rows = (await session.execute(text("SELECT * FROM eval_sets ORDER BY created_at, eval_set_id"))).fetchall()
        sets = [dict(r._mapping) for r in rows]
        counts = (
            await session.execute(
                text(
                    "SELECT eval_set_id, COUNT(*) AS n, COUNT(*) FILTER (WHERE enabled) AS enabled_n "
                    "FROM eval_cases GROUP BY eval_set_id"
                )
            )
        ).fetchall()
        count_map = {r.eval_set_id: dict(r._mapping) for r in counts}
        latest = (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (eval_set_id) eval_set_id, run_id, mode, status, summary, gates, started_at, "
                    "finished_at FROM eval_runs ORDER BY eval_set_id, started_at DESC"
                )
            )
        ).fetchall()
        latest_map = {r.eval_set_id: dict(r._mapping) for r in latest}
    for s in sets:
        c = count_map.get(s["eval_set_id"], {})
        s["case_count"] = c.get("n", 0)
        s["enabled_case_count"] = c.get("enabled_n", 0)
        s["latest_run"] = latest_map.get(s["eval_set_id"])
    return sets


async def get_eval_set(engine: AsyncEngine, tenant_id: str, eval_set_id: str) -> dict | None:
    """集合详情 + 用例列表（仅 enabled 用 enabled_only=False 参数控制——详情页给全量）。"""
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT * FROM eval_sets WHERE eval_set_id = :sid AND tenant_id = :tid"),
                {"sid": eval_set_id, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            return None
        s = dict(row._mapping)
        cases = (
            await session.execute(
                text("SELECT * FROM eval_cases WHERE eval_set_id = :sid ORDER BY sort_order, created_at"),
                {"sid": eval_set_id},
            )
        ).fetchall()
        s["cases"] = [dict(r._mapping) for r in cases]
        return s


async def create_eval_set(
    engine: AsyncEngine, tenant_id: str, *, kind: str, name: str, description: str | None = None
) -> dict:
    """自定义评估集（custom）。"""
    if kind not in VALID_KINDS:
        raise EvalError(f"kind 必须是 {'/'.join(VALID_KINDS)}")
    if not name or not name.strip():
        raise EvalError("name 不能为空")
    set_id = f"evs-{tenant_id}-{kind}-{uuid.uuid4().hex[:6]}"
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO eval_sets (eval_set_id, tenant_id, kind, name, description, source, thresholds) "
                "VALUES (:sid, :tid, :kind, :name, :desc, 'custom', :thr)"
            ),
            {
                "sid": set_id,
                "tid": tenant_id,
                "kind": kind,
                "name": name.strip(),
                "desc": description or "",
                "thr": json.dumps(THRESHOLDS[kind]),
            },
        )
    return {"eval_set_id": set_id, "kind": kind, "name": name.strip(), "source": "custom"}


def _validate_expected(kind: str, expected: dict) -> None:
    if kind == "routing":
        if not expected.get("data_domain_id"):
            raise EvalError("routing 用例 expected.data_domain_id 必填")
    elif kind == "understanding":
        if expected.get("intent") not in (
            "FACT",
            "RELATION",
            "AGGREGATION",
            "FALLBACK",
            "ATTRIBUTE",
            "LIST",
            "MULTI_HOP",
            "COMPARISON",
            "TREND",
            "CAUSAL",
            "MIXED",
        ):
            raise EvalError(f"understanding 用例 expected.intent 非法: {expected.get('intent')!r}")
    elif kind == "planning":
        if not expected.get("intent_label"):
            raise EvalError("planning 用例 expected.intent_label 必填")


async def add_eval_case(
    engine: AsyncEngine,
    tenant_id: str,
    eval_set_id: str,
    *,
    query: str,
    expected: dict,
    note: str | None = None,
) -> dict:
    if not query or not query.strip():
        raise EvalError("query 不能为空")
    set_row = await get_eval_set(engine, tenant_id, eval_set_id)
    if set_row is None:
        raise EvalError("评估集不存在")
    _validate_expected(set_row["kind"], expected)
    case_id = f"evc-{tenant_id}-{uuid.uuid4().hex[:10]}"
    async with tenant_session(engine, tenant_id) as session:
        max_ord = (
            await session.execute(
                text("SELECT COALESCE(MAX(sort_order), 0) AS m FROM eval_cases WHERE eval_set_id = :sid"),
                {"sid": eval_set_id},
            )
        ).scalar()
        ord_val = int(max_ord or 0) + 1
        await session.execute(
            text(
                "INSERT INTO eval_cases (case_id, tenant_id, eval_set_id, sort_order, query, expected, note, source) "
                "VALUES (:cid, :tid, :sid, :ord, :q, :exp, :note, 'custom')"
            ),
            {
                "cid": case_id,
                "tid": tenant_id,
                "sid": eval_set_id,
                "ord": ord_val,
                "q": query.strip(),
                "exp": json.dumps(expected),
                "note": note or "",
            },
        )
    return {"case_id": case_id}


async def update_eval_case(
    engine: AsyncEngine,
    tenant_id: str,
    case_id: str,
    *,
    query: str | None = None,
    expected: dict | None = None,
    note: str | None = None,
    enabled: bool | None = None,
) -> dict | None:
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT * FROM eval_cases WHERE case_id = :cid AND tenant_id = :tid"),
                {"cid": case_id, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            return None
        cur = dict(row._mapping)
        new_q = query if query is not None else cur["query"]
        new_exp = expected if expected is not None else cur["expected"]
        if query is not None or expected is not None:
            set_row = await get_eval_set(engine, tenant_id, cur["eval_set_id"])
            if set_row is None:
                raise EvalError("评估集不存在")
            _validate_expected(set_row["kind"], new_exp)
        await session.execute(
            text(
                "UPDATE eval_cases SET query = :q, expected = :exp, note = :note, enabled = :en, updated_at = now() "
                "WHERE case_id = :cid"
            ),
            {
                "q": new_q,
                "exp": json.dumps(new_exp),
                "note": note if note is not None else cur["note"],
                "en": enabled if enabled is not None else cur["enabled"],
                "cid": case_id,
            },
        )
    return {"case_id": case_id, "updated": True}


async def delete_eval_case(engine: AsyncEngine, tenant_id: str, case_id: str) -> bool:
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM eval_cases WHERE case_id = :cid AND tenant_id = :tid"),
                {"cid": case_id, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            return False
        await session.execute(
            text("DELETE FROM eval_cases WHERE case_id = :cid AND tenant_id = :tid"),
            {"cid": case_id, "tid": tenant_id},
        )
        return True


# ── 跑分记录 ───────────────────────────────────────────────────────────────
async def start_run(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str | None,
    eval_set_id: str,
    mode: str = "rules",
) -> dict:
    """创建 running 记录并返回 run_id（实际执行由调用方 run_eval_task 后台跑，D4）。"""
    if mode not in VALID_MODES:
        raise EvalError(f"mode 必须是 {'/'.join(VALID_MODES)}")
    set_row = await get_eval_set(engine, tenant_id, eval_set_id)
    if set_row is None:
        raise EvalError("评估集不存在")
    if not set_row["enabled"]:
        raise EvalError("评估集已停用")
    async with tenant_session(engine, tenant_id) as session:
        busy = (
            await session.execute(
                text("SELECT run_id FROM eval_runs WHERE eval_set_id = :sid AND status = 'running' LIMIT 1"),
                {"sid": eval_set_id},
            )
        ).fetchone()
        if busy:
            raise EvalError(f"该评估集已有跑分进行中（run_id={busy.run_id}）")
        run_id = f"evr-{uuid.uuid4().hex[:12]}"
        await session.execute(
            text(
                "INSERT INTO eval_runs (run_id, tenant_id, eval_set_id, mode, status, triggered_by) "
                "VALUES (:rid, :tid, :sid, :mode, 'running', :by)"
            ),
            {"rid": run_id, "tid": tenant_id, "sid": eval_set_id, "mode": mode, "by": user_id or ""},
        )
    return {"run_id": run_id, "status": "running", "mode": mode}


async def list_runs(engine: AsyncEngine, tenant_id: str, eval_set_id: str | None = None) -> list[dict]:
    async with tenant_session(engine, tenant_id) as session:
        if eval_set_id:
            rows = await session.execute(
                text("SELECT * FROM eval_runs WHERE eval_set_id = :sid ORDER BY started_at DESC"),
                {"sid": eval_set_id},
            )
        else:
            rows = await session.execute(text("SELECT * FROM eval_runs ORDER BY started_at DESC"))
        return [dict(r._mapping) for r in rows]


async def get_run(engine: AsyncEngine, tenant_id: str, run_id: str) -> dict | None:
    """跑分明细 + 逐用例结果（join eval_cases 取 query/expected 供展示）。

    T3 D5：响应附带 progress（completed=已落库 case 数 / total=启用用例数），
    前端轮询即可渲染进度条（取消后 completed 冻结不回落）。
    """
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT * FROM eval_runs WHERE run_id = :rid AND tenant_id = :tid"),
                {"rid": run_id, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            return None
        run = dict(row._mapping)
        results = (
            await session.execute(
                text(
                    "SELECT rc.*, c.query, c.expected, c.sort_order "
                    "FROM eval_run_cases rc JOIN eval_cases c ON c.case_id = rc.case_id "
                    "WHERE rc.run_id = :rid ORDER BY c.sort_order"
                ),
                {"rid": run_id},
            )
        ).fetchall()
        run["results"] = [dict(r._mapping) for r in results]
        total = (
            await session.execute(
                text("SELECT count(*) FROM eval_cases WHERE eval_set_id = :sid AND enabled"),
                {"sid": run["eval_set_id"]},
            )
        ).scalar_one()
        completed = len(run["results"])
        run["progress"] = {
            "completed": completed,
            "total": int(total),
            "percent": round(completed / int(total) * 100, 1) if int(total) else 0,
        }
        return run


async def _finish_run(
    engine: AsyncEngine, tenant_id: str, run_id: str, *, status: str, summary: dict, gates: dict
) -> None:
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "UPDATE eval_runs SET status = :st, summary = :sum, gates = :gates, finished_at = now() "
                "WHERE run_id = :rid"
            ),
            {"st": status, "sum": json.dumps(summary), "gates": json.dumps(gates), "rid": run_id},
        )


# ── 跑分引擎（D3/D5）───────────────────────────────────────────────────────
def _expected_plan(intent_label: str) -> str:
    """§11.2 映射表：标注 intent → 期望策略（FALLBACK 回落 plan_fact 即正确，QP-14）。"""
    if intent_label in ("FACT", "FALLBACK", "CAUSAL", "MIXED"):
        return "plan_fact"
    if intent_label in ("RELATION", "ATTRIBUTE", "LIST", "MULTI_HOP"):
        return "plan_relation"
    if intent_label in ("AGGREGATION", "COMPARISON", "TREND"):
        return "plan_aggregation"
    return "plan_fact"


def _context_from_note(note: str) -> dict | None:
    """note 含 `ctx:mention:semantic_type` 前缀 → 指代消解上下文。"""
    if note and note.startswith("ctx:"):
        mention, st = note[4:].split(":", 1)
        return {"last_entities": [{"mention": mention.strip(), "semantic_type": st.strip()}]}
    return None


async def _eval_routing_case(engine: AsyncEngine, tenant_id: str, role_id: str, case: dict) -> dict:
    from earp_server.knowledge.embedding_service import embed_query
    from earp_server.knowledge.routing import route_query

    q = case["query"]
    exp = case.get("expected") or {}
    t0 = time.monotonic()
    try:
        q_emb = await embed_query(q)
        vector_lane = True
    except Exception:
        logger.warning("eval routing: embed_query failed — keyword lane only", exc_info=True)
        q_emb = None
        vector_lane = False
    routed = await route_query(engine, tenant_id, q, q_emb, role_id, top_n=5, top_k=3)
    dd_ids = [c["data_domain_id"] for c in routed["candidate_dds"]]
    kb_ids = [k["knowledge_base_id"] for k in routed["candidate_kbs"]]
    dd_ok = exp.get("data_domain_id") in dd_ids
    kb_ok = not exp.get("knowledge_base_id") or exp["knowledge_base_id"] in kb_ids
    actual = {
        "candidate_dds": dd_ids,
        "candidate_kbs": kb_ids,
        "fallback_used": routed["fallback_used"],
        "vector_lane": vector_lane,
    }
    detail = {
        "dd_ok": dd_ok,
        "kb_ok": kb_ok,
        "expected_dd": exp.get("data_domain_id"),
        "expected_kb": exp.get("knowledge_base_id"),
    }
    return {
        "passed": dd_ok,
        "actual": actual,
        "detail": detail,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "dd_ok": dd_ok,
        "kb_ok": kb_ok,
        "vector_lane": vector_lane,
    }


async def _eval_understanding_case(engine: AsyncEngine, tenant_id: str, case: dict, mode: str, settings: Any) -> dict:
    from earp_server.ontology.understanding import (
        build_structured_query,
        understand,
        upgrade_with_llm,
    )

    q = case["query"]
    exp = case.get("expected") or {}
    ctx = _context_from_note(case.get("note") or "")
    t0 = time.monotonic()
    r = await understand(engine, tenant_id, q, context=ctx)
    if mode == "llm" and settings is not None:
        r = await upgrade_with_llm(engine, tenant_id, q, r, settings=settings)
    sq = build_structured_query(r)
    # intent（可靠子集计分；FALLBACK 回落即正确）
    intent_ok = (exp.get("intent") == "FALLBACK" and r.intent is None) or (
        r.intent is not None and r.intent.value == exp.get("intent")
    )
    # 实体提及召回
    exp_entities = exp.get("entities") or []
    ent_hits = [
        any(m.mention == e.get("mention") and m.semantic_type == e.get("semantic_type") for m in r.entities)
        for e in exp_entities
    ]
    ent_ok = all(ent_hits) if exp_entities else True
    # relation 准确率（期望集合 ⊆ 结果集合）
    exp_relations = exp.get("relations") or []
    got_relations = {x.relation for x in r.relations}
    rel_ok = all(rel in got_relations for rel in exp_relations) if exp_relations else True
    # schema 合规（result relation ∈ TBox 候选）
    tbox_ids = {c["relation_type_id"] for c in r.relation_candidates}
    schema_violations = [x.relation for x in r.relations if x.relation not in tbox_ids]
    passed = intent_ok and ent_ok and rel_ok and not schema_violations
    actual = {
        "intent": r.intent.value if r.intent else None,
        "entities": [{"mention": m.mention, "semantic_type": m.semantic_type} for m in r.entities],
        "relations": sorted(got_relations),
        "confidence": r.confidence,
        "llm_upgraded": r.llm_upgraded,
        "structured_query": sq.model_dump(mode="json"),
    }
    detail = {
        "intent_ok": intent_ok,
        "entity_hits": ent_hits,
        "entity_total": len(exp_entities),
        "relation_ok": rel_ok,
        "schema_violations": schema_violations,
        "field_hits": r.field_hits,
    }
    return {
        "passed": passed,
        "actual": actual,
        "detail": detail,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "intent_ok": intent_ok,
        "entity_hits": ent_hits,
        "relation_ok": rel_ok,
        "rel_scored": bool(exp_relations),
        "schema_violations": schema_violations,
    }


async def _eval_planning_case(
    engine: AsyncEngine,
    tenant_id: str,
    role_id: str,
    case: dict,
    mode: str,
    settings: Any,
) -> dict:
    from earp_server.ontology.planning import execute_plan, select_plan
    from earp_server.ontology.understanding import (
        StructuredQuery,
        build_structured_query,
        understand,
        upgrade_with_llm,
    )

    q = case["query"]
    exp = case.get("expected") or {}
    label = exp.get("intent_label", "FALLBACK")
    expected_plan = _expected_plan(label)
    t0 = time.monotonic()
    if mode == "rules":
        # 对齐 CI（test_planning_eval）：标注 intent → select_plan 映射（纯函数）
        # 映射判定不变；同时执行策略函数（规则层 StructuredQuery）记录执行结果
        # 供跑分明细展示（trace/evidence/耗时）——FDE 反馈「rules 明细看不到执行」
        ann_intent = Intent[label] if label in Intent.__members__ else Intent.FACT
        sq = StructuredQuery(intent=ann_intent, confidence=0.9)
        sel = select_plan(sq)
        plan_name = sel.plan_name
        # 执行结果展示用；失败不影响映射判定（gates 口径不变）
        executed = None
        try:
            _, executed = await execute_plan(engine, tenant_id, role_id, q, sq, settings=None)
        except Exception as exc:  # noqa: BLE001 — 执行环境异常（embedding 不可达等）不崩 run
            executed = None
            logger.warning("eval planning rules: execute_plan failed q=%r: %s", q, exc)
        actual = {
            "plan_name": plan_name,
            "mode": "rules",
            "trace": [t.type for t in executed.trace] if executed else [],
            "evidence_channels": sorted({e.channel for e in executed.evidence}) if executed else [],
            "evidence_count": len(executed.evidence) if executed else 0,
            "latency_ms": executed.latency_ms if executed else None,
        }
        detail = {
            "expected_plan": expected_plan,
            "fallback_reason": sel.fallback_reason,
            "executed_plan": executed.plan_name if executed else "(执行失败)",
            "trace": [t.type for t in executed.trace] if executed else [],
        }
    else:
        # llm：真理解 → LLM 升级 → 端到端执行
        r = await understand(engine, tenant_id, q)
        r = await upgrade_with_llm(engine, tenant_id, q, r, settings=settings)
        sq = build_structured_query(r)
        _, plan = await execute_plan(engine, tenant_id, role_id, q, sq, settings=settings)
        plan_name = plan.plan_name
        actual = {
            "plan_name": plan_name,
            "mode": "llm",
            "intent": sq.intent.value,
            "llm_upgraded": r.llm_upgraded,
            "evidence_channels": sorted({e.channel for e in plan.evidence}),
        }
        detail = {
            "expected_plan": expected_plan,
            "fallback_reason": plan.fallback_reason,
            "trace": [t.type for t in plan.trace],
        }
    return {
        "passed": plan_name == expected_plan,
        "actual": actual,
        "detail": detail,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "plan_ok": plan_name == expected_plan,
    }


def _aggregate(kind: str, results: list[dict], thresholds: dict) -> tuple[dict, dict]:
    """逐 kind 汇总 metrics + gates（D5）。返回 (summary, gates)。"""
    n = len(results)
    passed = sum(1 for r in results if r["passed"])
    if kind == "routing":
        summary = {
            "n": n,
            "passed": passed,
            "dd_accuracy": round(sum(r["dd_ok"] for r in results) / n, 4) if n else 1.0,
            "kb_accuracy": round(sum(r["kb_ok"] for r in results) / n, 4) if n else 1.0,
            "vector_lane": all(r["vector_lane"] for r in results) if n else True,
        }
    elif kind == "understanding":
        ent_hits = sum(sum(1 for h in r["entity_hits"] if h) for r in results)
        ent_total = sum(r["detail"]["entity_total"] for r in results)
        rel_scored = sum(1 for r in results if r["rel_scored"])
        rel_ok = sum(1 for r in results if r["rel_scored"] and r["relation_ok"])
        summary = {
            "n": n,
            "passed": passed,
            "intent_accuracy": round(sum(r["intent_ok"] for r in results) / n, 4) if n else 1.0,
            "entity_recall": round(ent_hits / ent_total, 4) if ent_total else 1.0,
            "relation_accuracy": round(rel_ok / rel_scored, 4) if rel_scored else 1.0,
            "schema_violations": sum(len(r["schema_violations"]) for r in results),
            "llm_upgraded": sum(1 for r in results if r["actual"].get("llm_upgraded")),
        }
    else:  # planning
        summary = {
            "n": n,
            "passed": passed,
            "strategy_hit_rate": round(sum(r["plan_ok"] for r in results) / n, 4) if n else 1.0,
        }
    gates: dict[str, bool] = {}
    for metric in GATED_METRICS[kind]:
        thr = thresholds.get(metric)
        if thr is None:
            gates[metric] = True
            continue
        value = summary.get(metric, 0)
        gates[metric] = value == 0 if isinstance(thr, int) and thr == 0 else value >= thr
    gates["overall"] = all(gates.values()) if gates else False
    return summary, gates


async def cancel_run(engine: AsyncEngine, tenant_id: str, run_id: str) -> dict | None:
    """取消进行中的跑分：running → cancelled。后台任务每 case 前检查后提前终止。

    返回 {run_id, status} 或 None（不存在/非 running——幂等：已完成/已取消返回当前态）。
    """
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status FROM eval_runs WHERE run_id = :rid AND tenant_id = :tid"),
                {"rid": run_id, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            return None
        if row.status != "running":
            return {"run_id": run_id, "status": row.status}
        await session.execute(
            text("UPDATE eval_runs SET status = 'cancelled', finished_at = now() WHERE run_id = :rid"),
            {"rid": run_id},
        )
        return {"run_id": run_id, "status": "cancelled"}


async def run_eval_task(
    engine: AsyncEngine,
    tenant_id: str,
    run_id: str,
    *,
    settings: Any = None,
    role_id: str = "r-all",
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """后台跑分执行（D4）：逐 case 评分落库 → 汇总 gates → completed/failed。

    不抛出——任何异常转为 status=failed + summary.error（调用方异步 fire-and-forget）。
    """
    try:
        async with tenant_session(engine, tenant_id) as session:
            run = (
                await session.execute(
                    text("SELECT * FROM eval_runs WHERE run_id = :rid AND tenant_id = :tid"),
                    {"rid": run_id, "tid": tenant_id},
                )
            ).fetchone()
            if run is None:
                logger.warning("run_eval_task: run %s not found", run_id)
                return
            run = dict(run._mapping)
            set_row = (
                await session.execute(
                    text("SELECT * FROM eval_sets WHERE eval_set_id = :sid AND tenant_id = :tid"),
                    {"sid": run["eval_set_id"], "tid": tenant_id},
                )
            ).fetchone()
            if set_row is None:
                raise EvalError(f"评估集不存在: {run['eval_set_id']}")
            kind = dict(set_row._mapping)["kind"]
            thresholds = dict(set_row._mapping)["thresholds"] or THRESHOLDS.get(kind, {})
            cases = (
                await session.execute(
                    text(
                        "SELECT * FROM eval_cases WHERE eval_set_id = :sid AND enabled ORDER BY sort_order, created_at"
                    ),
                    {"sid": run["eval_set_id"]},
                )
            ).fetchall()
            cases = [dict(r._mapping) for r in cases]
        if not cases:
            raise EvalError("评估集无启用的用例，无法跑分")
        if kind in ("understanding", "planning"):
            from earp_server.ontology import tbox_service

            await tbox_service.init_tenant_tbox(engine, tenant_id)

        mode = run["mode"]
        results: list[dict] = []
        for case in cases:
            if not await _is_running(engine, tenant_id, run_id):
                # 被取消（cancelled）→ 提前终止，不写 completed/failed
                logger.info("eval run %s cancelled — stopping early", run_id)
                return
            if heartbeat is not None:  # T1 D2：每 case 前报到，stale 判定用 heartbeat_at
                await heartbeat()
            if kind == "routing":
                res = await _eval_routing_case(engine, tenant_id, role_id, case)
            elif kind == "understanding":
                res = await _eval_understanding_case(engine, tenant_id, case, mode, settings)
            else:
                res = await _eval_planning_case(engine, tenant_id, role_id, case, mode, settings)
            results.append(res)
            await _insert_result(engine, tenant_id, run_id, case["case_id"], res)

        summary, gates = _aggregate(kind, results, thresholds)
        summary["skipped"] = 0
        await _finish_run(engine, tenant_id, run_id, status="completed", summary=summary, gates=gates)
        logger.info(
            "eval run %s (%s/%s) completed: %s gates=%s",
            run_id,
            kind,
            mode,
            {k: v for k, v in summary.items() if k in GATED_METRICS[kind]},
            gates,
        )
    except Exception as exc:  # noqa: BLE001 — 后台任务兜底
        logger.exception("eval run %s failed", run_id)
        await _finish_run(
            engine,
            tenant_id,
            run_id,
            status="failed",
            summary={"error": str(exc)},
            gates={},
        )


async def recover_stale_runs(engine: AsyncEngine, *, ttl_seconds: int = 3600) -> int:
    """进程中断遗留的 running 僵尸 → failed（T1 D2/D3，心跳 stale 判定）。

    worker 启动时调用：只处理 running 且 heartbeat_at 早于 now()-TTL 的行
    （心跳新鲜的合法在跑任务不动）；cancelled/completed/failed 不碰。
    summary.error='interrupted'（中断语义 = 进程终止，非业务失败）。
    多租户：running 行跨租户（RLS），逐租户扫描（tenants 无 RLS，scheduler 先例）。
    返回标记为 failed 的行数。
    """
    async with engine.connect() as conn:
        tenants = (await conn.execute(text("SELECT tenant_id FROM tenants"))).fetchall()
    n = 0
    for t in tenants:
        async with tenant_session(engine, t.tenant_id) as session:
            res = await session.execute(
                text(
                    "WITH upd AS (UPDATE eval_runs SET status = 'failed', "
                    "summary = '{\"error\": \"interrupted\"}'::jsonb, gates = '{}'::jsonb, "
                    "finished_at = now() "
                    "WHERE status = 'running' AND heartbeat_at < now() - make_interval(secs => :ttl) "
                    "RETURNING run_id) SELECT count(*) FROM upd"
                ),
                {"ttl": ttl_seconds},
            )
            n += int(res.scalar_one() or 0)
    if n:
        logger.warning("recover_stale_runs: %d stale eval runs marked failed (interrupted)", n)
    return n


async def _is_running(engine: AsyncEngine, tenant_id: str, run_id: str) -> bool:
    """后台任务循环内检查：被取消（cancelled）则提前终止，不覆盖状态。"""
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status FROM eval_runs WHERE run_id = :rid AND tenant_id = :tid"),
                {"rid": run_id, "tid": tenant_id},
            )
        ).fetchone()
        return row is not None and row.status == "running"


async def _insert_result(engine: AsyncEngine, tenant_id: str, run_id: str, case_id: str, res: dict) -> None:
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO eval_run_cases (result_id, tenant_id, run_id, case_id, passed, actual, detail, "
                "latency_ms) VALUES (:rid, :tid, :run, :cid, :passed, :actual, :detail, :lat)"
            ),
            {
                "rid": f"evrc-{uuid.uuid4().hex[:12]}",
                "tid": tenant_id,
                "run": run_id,
                "cid": case_id,
                "passed": res["passed"],
                "actual": json.dumps(res["actual"]),
                "detail": json.dumps(res["detail"]),
                "lat": res["latency_ms"],
            },
        )


# ── 治理（T3）：per-set 门槛 / 模板同步 / 导出导入 ─────────────────────────
def _validate_thresholds(kind: str, override: dict) -> dict:
    """校验并合并默认门槛（D6-1）：服务端合并默认全量存储（防部分覆盖丢指标）。

    指标名 ∈ GATED_METRICS[kind]；数值 0-1（schema_violations 允许非负整数）。
    """
    unknown = [k for k in override if k not in GATED_METRICS[kind]]
    if unknown:
        raise EvalError(f"未知门槛指标: {'、'.join(unknown)}（允许: {'/'.join(GATED_METRICS[kind])}）")
    merged = dict(THRESHOLDS[kind])
    for k, v in override.items():
        if k == "schema_violations":
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise EvalError("schema_violations 门槛必须是非负整数（0 = 必须为 0）")
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= 1):
            raise EvalError(f"{k} 门槛必须是 0-1 之间的数值")
        merged[k] = v
    return merged


async def update_eval_set(
    engine: AsyncEngine,
    tenant_id: str,
    set_id: str,
    *,
    thresholds: dict | None = None,
    enabled: bool | None = None,
) -> dict | None:
    """per-set 门槛/启停更新（T3 D6）：部分覆盖合并默认全量存储，判定逻辑零改动。"""
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT * FROM eval_sets WHERE eval_set_id = :sid AND tenant_id = :tid"),
                {"sid": set_id, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            return None
        cur = dict(row._mapping)
        new_thr = cur["thresholds"] or {}
        if thresholds is not None:
            new_thr = _validate_thresholds(cur["kind"], thresholds)
        new_en = enabled if enabled is not None else cur["enabled"]
        await session.execute(
            text("UPDATE eval_sets SET thresholds = :thr, enabled = :en, updated_at = now() WHERE eval_set_id = :sid"),
            {"thr": json.dumps(new_thr), "en": new_en, "sid": set_id},
        )
    return {"eval_set_id": set_id, "kind": cur["kind"], "thresholds": new_thr, "enabled": new_en}


async def sync_builtin_set(engine: AsyncEngine, tenant_id: str, set_id: str) -> dict | None:
    """同步内置模板（T3 D4-2）：仅 builtin；重建 builtin 用例（custom 保留）+ 版本更新。

    幂等：同步前后题量一致；custom 用例不动（D4-4 source 列区分）。
    破坏性：覆盖内置题（前端需确认弹窗）。
    """
    async with tenant_session(engine, tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT * FROM eval_sets WHERE eval_set_id = :sid AND tenant_id = :tid"),
                {"sid": set_id, "tid": tenant_id},
            )
        ).fetchone()
        if row is None:
            return None
        cur = dict(row._mapping)
        if cur["source"] != "builtin":
            raise EvalError("仅内置评估集可同步模板")
        kind = cur["kind"]
        spec = BUILTIN_EVAL_SETS[kind]
        await session.execute(
            text("DELETE FROM eval_cases WHERE eval_set_id = :sid AND source = 'builtin'"),
            {"sid": set_id},
        )
        for i, case in enumerate(spec["cases"], 1):
            await session.execute(
                text(
                    "INSERT INTO eval_cases (case_id, tenant_id, eval_set_id, sort_order, query, expected, note, "
                    "source) VALUES (:cid, :tid, :sid, :ord, :q, :exp, :note, 'builtin') ON CONFLICT DO NOTHING"
                ),
                {
                    "cid": f"evc-{tenant_id}-{kind}-{i:03d}",
                    "tid": tenant_id,
                    "sid": set_id,
                    "ord": i,
                    "q": case["query"],
                    "exp": json.dumps(case["expected"]),
                    "note": case.get("note") or "",
                },
            )
        await session.execute(
            text("UPDATE eval_sets SET seed_version = :ver, updated_at = now() WHERE eval_set_id = :sid"),
            {"ver": SEED_VERSION, "sid": set_id},
        )
        cnt = (
            await session.execute(text("SELECT count(*) FROM eval_cases WHERE eval_set_id = :sid"), {"sid": set_id})
        ).scalar_one()
    return {"eval_set_id": set_id, "source": "builtin", "seed_version": SEED_VERSION, "case_count": int(cnt)}


async def export_eval_set(engine: AsyncEngine, tenant_id: str, set_id: str) -> dict | None:
    """导出集合（T3 D4-3）：name/kind/description/thresholds/cases（无租户/敏感字段，id 自动生成）。"""
    s = await get_eval_set(engine, tenant_id, set_id)
    if s is None:
        return None
    return {
        "kind": s["kind"],
        "name": s["name"],
        "description": s.get("description") or "",
        "source": s["source"],
        "thresholds": s["thresholds"] or {},
        "cases": [{"query": c["query"], "expected": c["expected"], "note": c.get("note") or ""} for c in s["cases"]],
    }


async def import_eval_set(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    name: str,
    kind: str,
    description: str | None = None,
    thresholds: dict | None = None,
    cases: list[dict],
) -> dict:
    """导入集合（T3 D4-3）：目标租户建 custom 集合（id 自动生成），用例 source='custom'。"""
    if kind not in VALID_KINDS:
        raise EvalError(f"kind 必须是 {'/'.join(VALID_KINDS)}")
    if not name or not name.strip():
        raise EvalError("name 不能为空")
    if not cases:
        raise EvalError("cases 不能为空")
    merged = _validate_thresholds(kind, thresholds or {})
    set_id = f"evs-{tenant_id}-{kind}-{uuid.uuid4().hex[:6]}"
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO eval_sets (eval_set_id, tenant_id, kind, name, description, source, thresholds, "
                "seed_version) VALUES (:sid, :tid, :kind, :name, :desc, 'custom', :thr, NULL)"
            ),
            {
                "sid": set_id,
                "tid": tenant_id,
                "kind": kind,
                "name": name.strip(),
                "desc": description or "",
                "thr": json.dumps(merged),
            },
        )
        for i, c in enumerate(cases, 1):
            q = (c.get("query") or "").strip()
            if not q:
                raise EvalError(f"第 {i} 条用例 query 不能为空")
            _validate_expected(kind, c.get("expected") or {})
            await session.execute(
                text(
                    "INSERT INTO eval_cases (case_id, tenant_id, eval_set_id, sort_order, query, expected, note, "
                    "source) VALUES (:cid, :tid, :sid, :ord, :q, :exp, :note, 'custom')"
                ),
                {
                    "cid": f"evc-{tenant_id}-{uuid.uuid4().hex[:10]}",
                    "tid": tenant_id,
                    "sid": set_id,
                    "ord": i,
                    "q": q,
                    "exp": json.dumps(c.get("expected") or {}),
                    "note": c.get("note") or "",
                },
            )
    return {"eval_set_id": set_id, "kind": kind, "name": name.strip(), "source": "custom", "case_count": len(cases)}
