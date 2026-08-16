"""Knowledge Query Plan — 最小固定策略 Planner（Phase C，QU 设计 v0.3 §10/§11/§12）。

- PlanResult / Evidence / TraceRecord / QueryContext schema（Task 1）
- select_plan 规则映射表（Task 2，§11.2，10 类 intent 全覆盖 QP-11）
- plan_fact / plan_relation / plan_aggregation 三策略（Task 3-5）

一期边界（D2/D3 方案 A）：
- plan_aggregation 只做候选解析 + 回落（capability 执行链 Phase D1，不 mock）
- Plan 不落库（QP-12）；chat 一期不接入（Phase D 接 answer）
- Evidence 为 recall 层通道映射（§9.2 冲突消解 Phase D3）

设计依据：`arch/design/query-understanding-query-plan-design-v0.3.md`
任务书：`tasks/query-understanding-phase-c-task-breakdown.md`
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.ontology.understanding import Intent, StructuredQuery

logger = logging.getLogger(__name__)


# ── Task 1: schema（§9.1/§10/§11.1 冻结）──────────────────────────────────────


class EvidenceChannel(StrEnum):
    GRAPH = "graph"
    CHUNK = "chunk"
    CAPABILITY = "capability"
    PROFILE = "profile"


class Evidence(BaseModel):
    """Evidence Set schema（§9.1 冻结）。一期为 recall 层通道直接映射（D5）；
    conflict 恒 False（§9.2 消解 Phase D3）。"""

    evidence_id: str
    channel: EvidenceChannel
    content: str  # 归一化摘要/事实文本（供 LLM）
    source: str  # 来源系统/文档名
    source_ref: str  # document_id | fact_id | capability_call_id
    confidence: float = Field(ge=0.0, le=1.0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    payload: dict = Field(default_factory=dict)  # channel 多态
    conflict: bool = False


class TraceRecord(BaseModel):
    """Execution Trace（§10，观测记录，非执行 DSL）。"""

    step_id: str
    type: str  # RESOLVE_ENTITY / GRAPH_QUERY / VECTOR_SEARCH / KEYWORD_SEARCH /
    #          METADATA_FILTER / DD_ROUTING / KB_ROUTING / CAPABILITY_QUERY /
    #          FUSION_RERANK / ANSWER
    input: dict = Field(default_factory=dict)
    output: dict | None = None
    latency_ms: float = 0.0


class PlanResult(BaseModel):
    """策略函数产出（§11.1）。evidence/citations/trace 均为一期观测产物，不落库。"""

    plan_name: str
    evidence: list[Evidence] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)  # chat-agent-design citations 结构
    trace: list[TraceRecord] = Field(default_factory=list)
    fallback_reason: str | None = None
    latency_ms: float = 0.0


@dataclass
class QueryContext:
    """策略函数上下文（D6：显式注入，无隐式全局）。"""

    engine: AsyncEngine
    tenant_id: str
    role_id: str
    query: str = ""  # 原始查询文本（embed/lookup/resolve 用）
    settings: Any | None = None
    context: dict = field(default_factory=dict)  # 会话上下文（指代消解等）
    top_k: int = 5
    max_hops: int = 3


@dataclass
class PlanSelection:
    """select_plan 输出：策略函数 + 参数 + 回落标注。"""

    plan_name: str
    plan_fn: Callable[..., Any]
    plan_kwargs: dict = field(default_factory=dict)
    fallback_reason: str | None = None


# ── trace 辅助 ───────────────────────────────────────────────────────────────


class _Tracer:
    """策略函数内 trace 记录器（step_id 自增 + 耗时）。"""

    def __init__(self) -> None:
        self._records: list[TraceRecord] = []
        self._seq = 0
        self._pending: dict = {}
        self._t0 = 0.0

    def step(self, type_: str, *, input_: dict | None = None) -> _Tracer:
        self._t0 = time.monotonic()
        self._pending = {"type": type_, "input": input_ or {}}
        return self

    def finish(self, output: dict | None = None) -> None:
        self._seq += 1
        self._records.append(
            TraceRecord(
                step_id=f"t{self._seq}",
                type=self._pending["type"],
                input=self._pending["input"],
                output=output,
                latency_ms=round((time.monotonic() - self._t0) * 1000, 1),
            )
        )

    @property
    def records(self) -> list[TraceRecord]:
        return self._records


def _mk_evidence(
    channel: EvidenceChannel,
    *,
    content: str,
    source: str,
    source_ref: str,
    confidence: float = 1.0,
    payload: dict | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=f"ev-{uuid.uuid4().hex[:10]}",
        channel=channel,
        content=content,
        source=source,
        source_ref=source_ref,
        confidence=confidence,
        payload=payload or {},
    )


# ── Task 2: select_plan 规则映射表（§11.2，10 类全覆盖 QP-11）──────────────────

# QP-14：CAUSAL/MIXED 显式回落 plan_fact 并写 trace/fallback_reason，不静默当 FACT
_FALLBACK_REASONS: dict[str, str] = {
    "CAUSAL": "intent 未绑定策略（QP-14 显式回落 plan_fact）",
    "MIXED": "intent 未绑定策略（QP-14 显式回落 plan_fact）",
}


def select_plan(q: StructuredQuery) -> PlanSelection:
    """§11.2 规则映射表：intent → 策略（非 LLM 自由规划）。

    FACT → plan_fact；RELATION/ATTRIBUTE/LIST → plan_relation（解析失败回落
    plan_fact）；MULTI_HOP → plan_relation(max_hops=2)；AGGREGATION/COMPARISON/
    TREND → plan_aggregation（无 capability → plan_fact）；CAUSAL/MIXED →
    plan_fact（显式回落）。10 类全覆盖（QP-11）。
    """
    intent = q.intent
    if intent == Intent.FACT:
        return PlanSelection("plan_fact", plan_fact)
    if intent in (Intent.RELATION, Intent.ATTRIBUTE, Intent.LIST):
        return PlanSelection("plan_relation", plan_relation)
    if intent == Intent.MULTI_HOP:
        return PlanSelection("plan_relation", plan_relation, plan_kwargs={"max_hops": 2})
    if intent in (Intent.AGGREGATION, Intent.COMPARISON, Intent.TREND):
        return PlanSelection("plan_aggregation", plan_aggregation)
    if intent in (Intent.CAUSAL, Intent.MIXED):
        return PlanSelection("plan_fact", plan_fact, fallback_reason=_FALLBACK_REASONS[intent.value])
    # 理论不可达（StructuredQuery.intent 必填枚举），兜底防未定义落点（QP-11）
    return PlanSelection("plan_fact", plan_fact, fallback_reason="unknown intent fallback")


# ── Task 3/4/5 策略函数（§12 例 1-4）───────────────────────────────────────

_COST_TOP_K = 50  # §11.4 top_k 上限
_COST_CAND = 3  # §11.4 候选 DD/KB 上限


async def _route_limited(query: str, ctx: QueryContext, tracer: _Tracer) -> dict:
    """软路由 + 成本截断（§11.4：候选 DD/KB ≤ 3）。返回 routed（含 candidate_dds/kbs/fallback_used）。"""
    from earp_server.knowledge.embedding_service import embed_query
    from earp_server.knowledge.routing import route_query

    tracer.step("DD_ROUTING", input_={"query": query})
    try:
        q_emb = await embed_query(query)
    except Exception:
        q_emb = None  # 向量层优雅降级（keyword lane 仍工作）
    routed = await route_query(ctx.engine, ctx.tenant_id, query, q_emb, ctx.role_id)
    tracer.finish({"candidate_dds": len(routed.get("candidate_dds", [])), "fallback_used": routed.get("fallback_used")})
    routed["_q_emb"] = q_emb
    routed["candidate_dds"] = routed.get("candidate_dds", [])[:_COST_CAND]
    routed["candidate_kbs"] = routed.get("candidate_kbs", [])[:_COST_CAND]
    return routed


def _citations_from_items(items: list[dict]) -> list[dict]:
    """三源 citations 转换（复用 chat_service._retrieve 模式，独立实现——D1 不循环 import）。"""
    citations: list[dict] = []
    for ch in items:
        src = ch.get("source")
        if src == "profile":
            citations.append(
                {
                    "source": "profile",
                    "entity_id": ch.get("entity_id"),
                    "entity_type": ch.get("entity_type"),
                    "title": ch.get("title") or "",
                    "key_facts": ch.get("key_facts", []),
                }
            )
        elif src == "graph":
            citations.append(
                {
                    "source": "graph",
                    "entity_id": ch.get("entity_id"),
                    "entity_type": ch.get("entity_type"),
                    "title": ch.get("title") or "",
                }
            )
        else:
            citations.append(
                {
                    "chunk_id": ch.get("chunk_id"),
                    "document_id": ch.get("document_id"),
                    "title": ch.get("title") or ch.get("doc_name") or "",
                    "kb_id": ch.get("kb_id"),
                    "kb_name": ch.get("kb_name"),
                    "metadata": ch.get("metadata"),
                    "similarity": ch.get("similarity"),
                }
            )
    return citations


def _evidence_from_items(items: list[dict]) -> list[Evidence]:
    """recall 层 item → Evidence（D5：通道直接映射，无冲突消解）。"""
    out: list[Evidence] = []
    for ch in items:
        src = ch.get("source")
        if src == "profile":
            out.append(
                _mk_evidence(
                    EvidenceChannel.PROFILE,
                    content=str(ch.get("key_facts") or ch.get("content") or ""),
                    source=ch.get("title") or ch.get("entity_id") or "",
                    source_ref=ch.get("entity_id") or "",
                    confidence=1.0,
                    payload={
                        "entity_id": ch.get("entity_id"),
                        "entity_type": ch.get("entity_type"),
                        "key_facts": ch.get("key_facts", []),
                    },
                )
            )
        elif src == "graph":
            out.append(
                _mk_evidence(
                    EvidenceChannel.GRAPH,
                    content=str(ch.get("content") or ""),
                    source=ch.get("title") or ch.get("entity_id") or "",
                    source_ref=ch.get("fact_id") or "",
                    confidence=round(1.0 / (1 + int(ch.get("depth") or 0)), 3),
                    payload={
                        "relation_type_id": ch.get("relation_type_id"),
                        "source_entity_id": ch.get("source_entity_id"),
                        "target_entity_id": ch.get("target_entity_id"),
                        "depth": ch.get("depth"),
                    },
                )
            )
        else:  # chunk
            out.append(
                _mk_evidence(
                    EvidenceChannel.CHUNK,
                    content=str(ch.get("content") or ""),
                    source=ch.get("title") or ch.get("doc_name") or ch.get("document_id") or "",
                    source_ref=ch.get("document_id") or "",
                    confidence=round(float(ch.get("similarity") or 0.0), 3),
                    payload={
                        "chunk_id": ch.get("chunk_id"),
                        "kb_id": ch.get("kb_id"),
                        "metadata": ch.get("metadata"),
                        "similarity": ch.get("similarity"),
                    },
                )
            )
    return out


async def plan_fact(query: StructuredQuery, *, ctx: QueryContext) -> PlanResult:
    """plan_fact（§12 例 1）：route_query → 三层检索（candidate_dds 非空）| 全租户 chunk（空）。

    trace: DD_ROUTING → KB_ROUTING → METADATA_FILTER → VECTOR/KEYWORD → FUSION_RERANK
    """
    t0 = time.monotonic()
    tracer = _Tracer()
    qtext = ctx.query or ""
    top_k = min(ctx.top_k or 5, _COST_TOP_K)

    routed = await _route_limited(qtext, ctx, tracer)
    cand_dds = [dd["data_domain_id"] for dd in routed.get("candidate_dds", [])]
    cand_kbs = [kb["knowledge_base_id"] for kb in routed.get("candidate_kbs", [])]

    from earp_server.knowledge.search_service import search_chunks
    from earp_server.ontology.search import knowledge_search

    items: list[dict] = []
    if cand_dds:
        tracer.step("KB_ROUTING", input_={"candidate_dds": cand_dds, "candidate_kbs": cand_kbs})
        tracer.finish({"kb_count": len(cand_kbs)})
        if query.constraints:
            tracer.step("METADATA_FILTER", input_=dict(query.constraints))
            tracer.finish({"filters": len(query.constraints)})
        tracer.step("VECTOR_SEARCH", input_={"mode": "hybrid", "top_k": top_k})
        try:
            items = await knowledge_search(
                ctx.engine,
                ctx.tenant_id,
                qtext,
                embedding=routed.get("_q_emb"),
                role_id=ctx.role_id,
                data_domain_ids=cand_dds,
                knowledge_base_ids=cand_kbs or None,
                top_k=top_k,
                embedding_dim=getattr(ctx.settings, "embedding_dim", 1024) if ctx.settings else 1024,
                query_text=qtext,
                mode="hybrid",
                threshold=0.0,
                metadata_filters=query.constraints or None,
                eventbus=None,
                rerank=True,
            )
        except Exception:
            logger.exception("plan_fact: knowledge_search failed")
            items = []
        tracer.finish({"items": len(items)})
    else:
        # 无候选 DD → 全租户 chunk 兜底（P2 D4 语义）
        tracer.step("VECTOR_SEARCH", input_={"mode": "hybrid", "fallback": "whole-tenant"})
        q_emb = routed.get("_q_emb")
        if q_emb is None:
            items = []  # embedding 不可达 → 向量层优雅降级（无候选 DD 时无可检索内容）
        else:
            try:
                items = await search_chunks(
                    ctx.engine,
                    ctx.tenant_id,
                    q_emb,
                    ctx.role_id,
                    top_k=top_k,
                    embedding_dim=getattr(ctx.settings, "embedding_dim", 1024) if ctx.settings else 1024,
                    knowledge_base_ids=cand_kbs or None,
                    threshold=0.0,
                    query_text=qtext,
                    mode="hybrid",
                    metadata_filters=query.constraints or None,
                    eventbus=None,
                    rerank=True,
                )
            except Exception:
                logger.exception("plan_fact: search_chunks fallback failed")
                items = []
        tracer.finish({"items": len(items)})

    if items:
        tracer.step("FUSION_RERANK", input_={"items": len(items)})
        tracer.finish({"top": top_k})
    return PlanResult(
        plan_name="plan_fact",
        evidence=_evidence_from_items(items),
        citations=_citations_from_items(items),
        trace=tracer.records,
        latency_ms=round((time.monotonic() - t0) * 1000, 1),
    )


async def plan_relation(query: StructuredQuery, *, ctx: QueryContext, max_hops: int = 1) -> PlanResult:
    """plan_relation（§12 例 2/例 3）：lookup_entities → graph_query（前向）→ chunk 补证。

    无实体命中 → 显式回落 plan_fact（§11.2「解析失败回落 plan_fact」）。
    graph 无事实 → RAG 补证（§14 fallback，trace 标注）。
    """
    t0 = time.monotonic()
    tracer = _Tracer()
    qtext = ctx.query or ""
    top_k = min(ctx.top_k or 5, _COST_TOP_K)
    hops = min(max_hops or 1, ctx.max_hops or _COST_TOP_K)

    from earp_server.ontology import abox_service

    # RESOLVE_ENTITY：用 StructuredQuery.entities 的 mention（不重新 tokenize）
    tracer.step("RESOLVE_ENTITY", input_={"mentions": [e.mention for e in query.entities]})
    entity_ids: list[str] = []
    for ent in query.entities[:2]:
        hits = await abox_service.lookup_entities(ctx.engine, ctx.tenant_id, ent.mention, top_k=1)
        if hits:
            entity_ids.append(hits[0]["entity_id"])
    tracer.finish({"entity_ids": entity_ids})
    if not entity_ids:
        # 解析失败 → 回落 plan_fact（§11.2）
        sub = await plan_fact(query, ctx=ctx)
        sub.plan_name = "plan_fact"
        sub.fallback_reason = "entity resolution failed → plan_fact"
        return sub

    # GRAPH_QUERY（forward）
    graph_rows: list[dict] = []
    for eid in entity_ids[:2]:
        tracer.step("GRAPH_QUERY", input_={"entity_id": eid, "max_hops": hops})
        rows = await abox_service.graph_query(ctx.engine, ctx.tenant_id, eid, max_hops=hops)
        graph_rows.extend(rows)
        tracer.finish({"rows": len(rows)})

    items: list[dict] = []
    if graph_rows:
        for row in graph_rows[:10]:
            items.append(
                {
                    "source": "graph",
                    "key": f"g:{row['target_entity_id']}",
                    "entity_id": row["target_entity_id"],
                    "entity_type": row.get("target_type"),
                    "title": f"图谱：{row['relation_type_id']} → {row.get('target_name', row['target_entity_id'])}",
                    "content": f"{row['relation_type_id']} → {row.get('target_name', row['target_entity_id'])}",
                    "relation_type_id": row["relation_type_id"],
                    "source_entity_id": row["source_entity_id"],
                    "target_entity_id": row["target_entity_id"],
                    "depth": row["depth"],
                    "fact_id": row.get("fact_id"),
                }
            )
    else:
        # graph 无事实 → RAG 补证（§14）
        tracer.step("VECTOR_SEARCH", input_={"note": "graph 无事实 → RAG 补证"})
        from earp_server.knowledge.embedding_service import embed_query
        from earp_server.knowledge.search_service import search_chunks

        try:
            q_emb = await embed_query(qtext)
            chunks = await search_chunks(
                ctx.engine,
                ctx.tenant_id,
                q_emb,
                ctx.role_id,
                top_k=top_k,
                embedding_dim=getattr(ctx.settings, "embedding_dim", 1024) if ctx.settings else 1024,
                query_text=qtext,
                mode="hybrid",
                eventbus=None,
                rerank=True,
            )
            for c in chunks:
                merged = dict(c)
                merged["source"] = "chunk"
                items.append(merged)
        except Exception:
            logger.exception("plan_relation: chunk 补证失败")
        tracer.finish({"items": len(items)})

    return PlanResult(
        plan_name="plan_relation",
        evidence=_evidence_from_items(items),
        citations=_citations_from_items(items),
        trace=tracer.records,
        latency_ms=round((time.monotonic() - t0) * 1000, 1),
    )


async def plan_aggregation(query: StructuredQuery, *, ctx: QueryContext) -> PlanResult:
    """plan_aggregation（§12 例 4，D2 方案 A）：resolve_with_entities 候选解析。

    一期 capability 执行链未建成（connector.execute 仅 demo.echo）——有 query
    候选 → trace 标注「capability 通道未就绪」，不 mock 假执行；无候选 → 显式
    回落 plan_fact（§11.2）。Phase D1 接入 resolve_with_query + 执行器后重标。
    """
    t0 = time.monotonic()
    tracer = _Tracer()
    qtext = ctx.query or ""

    from earp_server.ontology.search import resolve_with_entities

    tracer.step("CAPABILITY_QUERY", input_={"intent": qtext, "operation": query.operation.model_dump()})
    candidates = await resolve_with_entities(ctx.engine, ctx.tenant_id, qtext)
    query_cands = [c for c in candidates if c.get("type") == "query"]
    tracer.finish({"candidates": len(candidates), "query_candidates": len(query_cands)})

    if not query_cands:
        # 无候选 query capability → 回落 plan_fact（§11.2）
        sub = await plan_fact(query, ctx=ctx)
        sub.plan_name = "plan_fact"
        sub.fallback_reason = "no query capability candidate → plan_fact"
        return sub

    # 有候选但执行链未就绪（D2）：trace 标注，不假执行
    tracer.step(
        "CAPABILITY_QUERY",
        input_={
            "note": "capability 通道未就绪（Phase D1）",
            "candidates": [c["capability_id"] for c in query_cands[:5]],
        },
    )
    tracer.finish({"executed": False})
    result = PlanResult(
        plan_name="plan_aggregation",
        trace=tracer.records,
        fallback_reason="capability 通道未就绪（Phase D1 接入执行器）——已解析候选，未执行",
        latency_ms=round((time.monotonic() - t0) * 1000, 1),
    )
    return result


async def execute_plan(
    engine: AsyncEngine,
    tenant_id: str,
    role_id: str,
    query: str,
    structured_query: StructuredQuery,
    *,
    settings=None,
    context: dict | None = None,
    top_k: int = 5,
) -> tuple[PlanSelection, PlanResult]:
    """理解链入口：select_plan → 策略函数执行（debug 端点 / verify 脚本共用）。

    返回 (selection, result)——selection 含 plan_name/fallback_reason 供展示。
    """
    ctx = QueryContext(
        engine=engine,
        tenant_id=tenant_id,
        role_id=role_id,
        settings=settings,
        context=context or {},
        top_k=top_k,
        query=query,
    )
    sel = select_plan(structured_query)
    result = await sel.plan_fn(structured_query, ctx=ctx, **sel.plan_kwargs)
    return sel, result
