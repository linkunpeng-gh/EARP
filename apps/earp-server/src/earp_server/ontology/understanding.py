"""Query Understanding — 理解层（Phase B，QU 设计 v0.3 §5/§6）。

产出 Structured Query（§6.2 schema 冻结）+ 规则层基础 + relation 候选校验。
一期可靠分类子集 {FACT, RELATION, AGGREGATION}（§5.4/QP-14）；其余 7 类不建
关键词，显式回落（rule_fields 标注 reason，不静默当 FACT）。

设计依据：`arch/design/query-understanding-query-plan-design-v0.3.md`
任务书：`tasks/query-understanding-phase-b-task-breakdown.md`（Task 1-6）
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.ontology.search import _entity_hits

logger = logging.getLogger(__name__)

# Chatflow QU 提速：LLM 升级结果 LRU 缓存（键 = (tenant_id, query)）——
# 同问题重复询问不重复等 LLM；仅缓存成功响应；规则层对同 query 输出确定 → 安全。
_UPGRADE_CACHE: OrderedDict[tuple[str, str], dict | None] = OrderedDict()
_UPGRADE_CACHE_MAX = 128
_CACHE_MISS = object()  # 区分「未缓存」与「缓存了失败(None)」


# ── §6.2 冻结 schema ─────────────────────────────────────────────────────────


class Intent(str, Enum):
    """问题类型（10 类枚举，知识检索维度，与 capability intent 正交并存）。

    一期可靠分类子集 = {FACT, RELATION, AGGREGATION}（§5.4）；其余 7 类规则层
    不分类，由 LLM 升级尝试，仍不中则显式回落（rule_fields 标注，QP-14）。
    """

    FACT = "FACT"
    ATTRIBUTE = "ATTRIBUTE"
    RELATION = "RELATION"
    MULTI_HOP = "MULTI_HOP"
    LIST = "LIST"
    AGGREGATION = "AGGREGATION"
    COMPARISON = "COMPARISON"
    TREND = "TREND"
    CAUSAL = "CAUSAL"
    MIXED = "MIXED"


class TimeConstraint(BaseModel):
    """时间（§5.5 单独建模，与 constraints 分开——类型安全优先于字段合并）。

    resolved_start/resolved_end 由运行时回填（D9：不让规则/LLM 猜日期）。
    """

    kind: Literal["absolute", "relative", "none"] = "none"
    expression: str | None = None  # "yesterday" / "最近三个月"
    resolved_start: datetime | None = None  # 运行时回填
    resolved_end: datetime | None = None


class EntityMention(BaseModel):
    """实体提及（mention → semantic_type，非 entity_id——解析留给 Phase C lookup_entities）。"""

    mention: str
    semantic_type: str | None = None  # equipment/supplier/...
    role: Literal["subject", "target", "intermediate", "scope"] | None = None


class RelationMention(BaseModel):
    """关系提及（relation MUST be in relation_types.relation_type_id，动态查表 D2）。"""

    subject: str
    relation: str
    object_type: str | None = None
    object_mention: str | None = None


class Operation(BaseModel):
    """聚合/排序/比较（AGGREGATION/COMPARISON/TREND 策略消费 → capability 调用参数）。"""

    aggregate: Literal["COUNT", "SUM", "AVG", "MAX", "MIN"] | None = None
    group_by: list[str] = Field(default_factory=list)
    order_by: str | None = None
    limit: int | None = None
    compare_subjects: list[str] = Field(default_factory=list)  # COMPARISON 用


class AnswerRequirement(BaseModel):
    """回答要求（一期 answer_type 单值 summary；其余 reserved，YAGNI）。"""

    answer_type: Literal["summary"] = "summary"
    evidence_required: bool = False
    citation_required: bool = True


class StructuredQuery(BaseModel):
    """Query Understanding 输出（§6.2 冻结）。

    约束：
    - relations[].relation 必须在 relation_types（validate_relation_sources 过滤）
    - intent 必须是枚举值
    - confidence 必须由 §6.4 机械计算，不得由 LLM 自报
    """

    context: dict = Field(default_factory=dict)
    entities: list[EntityMention] = Field(default_factory=list)
    relations: list[RelationMention] = Field(default_factory=list)
    intent: Intent
    constraints: dict = Field(default_factory=dict)  # metadata 过滤（department/year/doc_type…），不含 time
    time: TimeConstraint = Field(default_factory=TimeConstraint)
    operation: Operation = Field(default_factory=Operation)
    answer_requirement: AnswerRequirement = Field(default_factory=AnswerRequirement)
    confidence: float = Field(ge=0.0, le=1.0)


# ── _INTENT_KEYWORDS（Task 1，Task 4 消费；与 _DATA_DOMAIN_KEYWORDS 分离——D3）───
# 问题类型维度 ≠ DD 路由维度，不混用。保守原则（风险 #4）：关键词必须强指向，
# 宁可回落也不误判；「哪个」等弱词仅在组合中出现（"哪个最多" → AGGREGATION）。
_INTENT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.FACT: [
        "是什么",
        "是啥",
        "什么是",
        "定义",
        "含义",
        "指什么",
        "包括什么",
        "包含什么",
        "有什么",
        "介绍",
        "说明",
        "要求",
        "标准",
        "流程",
        "规定",
        "制度",
        "政策",
        "规范",
        "手册",
        "注意事项",
        "基本情况",
    ],
    Intent.RELATION: [
        "谁",
        "哪个",
        "哪家",
        "哪条",
        "由谁",
        "由什么",
        "是什么引起的",
        "谁生产",
        "谁制造",
        "谁负责",
        "谁供应",
        "生产什么",
        "属于",
        "位于",
        "在哪",
        "在哪个",
    ],
    Intent.AGGREGATION: [
        "有多少",
        "多少台",
        "多少个",
        "多少次",
        "多少条",
        "多少项",
        "多少起",
        "数量",
        "总计",
        "合计",
        "统计",
        "最多",
        "最少",
        "平均",
        "占比",
        "几个",
        "几台",
        "几次",
        "频率",
        "哪个最多",
        "哪个最少",
    ],
}

# 规则层多候选歧义时按此顺序消歧（词频/语义强度，Task 4/6 使用）。
# AGGREGATION 优先于 RELATION："哪个最多/最多的是哪个设备" 聚合语义强于疑问词。
_INTENT_AMBIGUITY_ORDER: tuple[Intent, ...] = (
    Intent.AGGREGATION,
    Intent.RELATION,
    Intent.FACT,
)


# ── relation 候选（D2：动态查表，不硬编码在 prompt/code）──────────────────────


async def fetch_relation_candidates(engine: AsyncEngine, tenant_id: str) -> list[dict]:
    """动态拉取 relation_types 候选集（active）——规则层动词映射与 LLM 升级共用。

    返回 [{relation_type_id, name, source_type, target_type}]；空表时调用方回落
    （relation 提取与校验均依赖候选集）。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT relation_type_id, name, source_type, target_type FROM relation_types "
                "WHERE tenant_id = :tid AND status = 'active' ORDER BY relation_type_id"
            ),
            {"tid": tenant_id},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


def validate_relation_sources(
    relations: list[RelationMention],
    candidates: list[dict],
) -> list[RelationMention]:
    """Schema 合规校验：relation ∈ relation_types 候选集（动态，D2）。

    非法关系过滤（schema 合规率 100% 是验收门槛）；source_type/target_type 方向
    校验在 Task 5 动词映射时做（relation 候选本身携带 source/target 类型）。
    """
    valid_ids = {c["relation_type_id"] for c in candidates}
    return [r for r in relations if r.relation in valid_ids]


# ── Task 2: 时间/数字提取（§5.5/§6.3，D9）────────────────────────────────────
# 相对时间 → time（resolved_* 运行时回填）；绝对年份 → constraints（metadata 过滤
# 维度，§5.5 例 year=2024）；constraints 与 time 分开建模，不合并。

_TIME_TERMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"昨天"), "yesterday"),
    (re.compile(r"前天"), "day_before_yesterday"),
    (re.compile(r"今天|今日"), "today"),
    (re.compile(r"上周|上一周"), "last_week"),
    (re.compile(r"上个月|上月"), "last_month"),
    (re.compile(r"去年"), "last_year"),
    (re.compile(r"今年"), "this_year"),
    (re.compile(r"最近([0-9一二三四五六七八九十两]+)天"), "recent_{n}_days"),
    (re.compile(r"最近([0-9一二三四五六七八九十两]+)周"), "recent_{n}_weeks"),
    (re.compile(r"最近([0-9一二三四五六七八九十两]+)个月"), "recent_{n}_months"),
    (re.compile(r"最近([0-9一二三四五六七八九十两]+)年"), "recent_{n}_years"),
    (re.compile(r"近([0-9一二三四五六七八九十两]+)天"), "recent_{n}_days"),
]

_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})\s*年")
_MONTH_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})(?:月)?")


def _extract_time(query: str) -> tuple[TimeConstraint, dict, bool]:
    """提取时间与 metadata 约束（§5.5 分离建模）。返回 (time, constraints, hit)。"""
    time = TimeConstraint()
    constraints: dict = {}
    hit = False
    for pat, expr in _TIME_TERMS:
        m = pat.search(query)
        if m:
            time.kind = "relative"
            time.expression = expr.format(n=m.group(1)) if "{n}" in expr else expr
            hit = True
            break
    ym = _YEAR_RE.search(query)
    if ym:
        constraints["year"] = int(ym.group(1))
        hit = True
    mm = _MONTH_RE.search(query)
    if mm:
        constraints["year"] = int(mm.group(1))
        constraints["month"] = int(mm.group(2))
        hit = True
    return time, constraints, hit


# ── Task 3: 实体提及识别（D2/D8）──────────────────────────────────────────────

_ROLE_Q_RE = re.compile(r"(谁|哪个|哪家|哪些|由谁|在哪|位于)")
_COREF_RE = re.compile(r"(它|这个|该设备|该机器|这台|那台)")

# TBox seed 实体类型中文名（与 tbox_service.SEED_ENTITY_TYPES 对齐；Phase 可换动态
# 拉取）。仅作「实体维度相关」判定提示词，不产出 mention（防泛词误判，Task 3）。
_ENTITY_HINT_WORDS: tuple[str, ...] = (
    "设备", "部件", "产线", "工厂", "传感器", "报警", "工单",
    "物料", "产品", "供应商", "客户", "员工", "部门",
)


def _mention_role(query: str, mention: str) -> Literal["subject", "target"] | None:
    """一期保守 role 启发式（Task 3）：疑问词位置 vs mention 位置。

    疑问词在 mention 之后（"CNC-01 由谁生产"）→ subject；之前（"谁生产 CNC-01"）
    → target。不确定（无法定位）留 None——role 是 Phase C 策略函数消费维度，
    一期不追求高准确（§17 门槛不含 role）。
    """
    q = _ROLE_Q_RE.search(query)
    if q is None:
        return None
    pos = query.find(mention)
    if pos < 0:
        return None
    return "subject" if pos < q.start() else "target"


async def _extract_entities(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    *,
    context: dict | None = None,
    top_k: int = 5,
) -> list[EntityMention]:
    """实体提及识别：lookup_entities 双向子串（复用 _entity_hits）+ 指代消解（D8）。

    只产 mention/semantic_type，不解析 entity_id（Phase C plan_relation 职责）。
    """
    hits = await _entity_hits(engine, tenant_id, query, top_k=top_k)
    mentions: list[EntityMention] = []
    seen: set[str] = set()
    for h in hits:
        mention = h.get("name") or h.get("business_code") or h.get("entity_id", "")
        if not mention or mention in seen:
            continue
        seen.add(mention)
        mentions.append(
            EntityMention(
                mention=mention,
                semantic_type=h.get("entity_type_id"),
                role=_mention_role(query, mention),
            )
        )
    # 指代消解（D8）：query 含指代词 + context.last_entities → 映射上文实体
    if _COREF_RE.search(query) and not mentions:
        last = (context or {}).get("last_entities") or []
        if last:
            prev = last[-1]
            if isinstance(prev, dict):
                mentions.append(
                    EntityMention(
                        mention=prev.get("mention") or "",
                        semantic_type=prev.get("semantic_type"),
                        role="subject",
                    )
                )
    return mentions


def _entity_relevant(query: str, context: dict | None) -> bool:
    """实体维度是否相关（应提取字段判定，§6.4）——保守：疑似即相关。"""
    if context and context.get("last_entities"):
        return True
    if _COREF_RE.search(query):
        return True
    if re.search(r"[A-Z]{2,}-\d+", query):  # CNC-01 等业务代码（排除纯年份数字）
        return True
    return any(kw in query for kw in _ENTITY_HINT_WORDS)


# ── Task 4: intent 分类（§5.4/QP-14，D3）──────────────────────────────────────


def _classify_intent(query: str) -> tuple[Intent | None, list[Intent]]:
    """关键词匹配 → 可靠子集 intent；多候选返回候选列表（ambiguity_penalty）。

    其余 7 类（ATTRIBUTE/MULTI_HOP/LIST/COMPARISON/TREND/CAUSAL/MIXED）不建关键词
    ——显式回落（QP-14），由 LLM 升级尝试，仍不中则标注 reason 不静默当 FACT。
    消歧顺序 _INTENT_AMBIGUITY_ORDER（RELATION > AGGREGATION > FACT）。
    """
    hits: list[Intent] = []
    for intent, kws in _INTENT_KEYWORDS.items():
        if any(kw in query for kw in kws):
            hits.append(intent)
    if not hits:
        return None, []
    chosen = min(hits, key=lambda i: _INTENT_AMBIGUITY_ORDER.index(i))
    return chosen, hits


# ── Task 5: relation 提取（D2 动态候选 + 方向校验）─────────────────────────────

# 动词词典 → relation_type_id 提示词（实际 relation 必须 ∈ 动态候选集；
# source_type/target_type 方向校验用候选集字段，词典只做动词触发）。
# 一期只做「被动/实体作 subject」模式（任务书 Task 5）：query 中已命中实体是
# 关系源（CNC-01 由谁制造 → CNC-01 是 subject）。“谁负责 A产线”等主动疑问
# （实体在 target 侧）一期不提取（subject 未命中，Phase C plan_relation 范畴）。
# 长短语在前（dict 保序）——「供应商生产」先于「生产」匹配，避免误映射 produces。
_VERB_TO_RELATION: dict[str, str] = {
    "由谁制造": "manufactured_by",
    "供应商生产": "manufactured_by",
    "哪家供应商": "manufactured_by",
    "谁生产": "manufactured_by",
    "制造": "manufactured_by",
    "生产商": "manufactured_by",
    "谁供应": "supplied_by",
    "由谁供应": "supplied_by",
    "供应": "supplied_by",
    "位于": "located_in",
    "在哪": "located_in",
    "在哪个": "located_in",
    "属于": "belongs_to",
    "由什么引起": "caused_by",
    "引起": "caused_by",
    "导致": "caused_by",
    "谁负责": "responsible_for",
    "负责": "responsible_for",
    "谁维护": "maintained_by",
    "维护": "maintained_by",
    "监测": "monitored_by",
    "监控": "monitored_by",
    "关联": "relates_to",
    "批准": "approved_by",
    "生产": "produces",
    "消耗": "consumes",
}


async def _extract_relations(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    entity_mentions: list[EntityMention],
    candidates: list[dict],
    *,
    context: dict | None = None,
) -> tuple[list[RelationMention], list[str]]:
    """动词词典 + 实体命中 → RelationMention；方向校验（subject 类型 ∈ source_type）。

    返回 (relations, 命中的动词)。无实体命中时可用指代消解上下文实体作 subject。
    """
    relations: list[RelationMention] = []
    verbs_hit: list[str] = []
    # 动词匹配按词典顺序（避免「制造」先于「由谁制造」的错误子串优先）
    for verb, rel_id in _VERB_TO_RELATION.items():
        if verb not in query:
            continue
        verbs_hit.append(verb)
        cand = next((c for c in candidates if c["relation_type_id"] == rel_id), None)
        if cand is None:
            continue  # 候选表无此关系（动态 D2）
        source_types = set(s.strip() for s in cand["source_type"].split(","))
        subject = next(
            (e for e in entity_mentions if not e.semantic_type or e.semantic_type in source_types),
            None,
        )
        if subject is None:
            # 方向校验失败不强行用首实体（避免错误关系如 CNC-01→produces）——
            # 「谁负责 A产线」等主动疑问（实体在 target 侧）一期不提取，Phase C 范畴
            continue
        relations.append(
            RelationMention(
                subject=subject.mention,
                relation=rel_id,
                object_type=cand["target_type"],
            )
        )
    return relations, verbs_hit


def _verb_hit(query: str) -> bool:
    return any(v in query for v in _VERB_TO_RELATION)


# ── operation 提取（§5.6，AGGREGATION 消费维度）────────────────────────────────

_AGG_OP_WORDS: dict[str, Literal["COUNT", "SUM", "AVG", "MAX", "MIN"]] = {
    "有多少": "COUNT",
    "多少台": "COUNT",
    "多少个": "COUNT",
    "多少次": "COUNT",
    "数量": "COUNT",
    "总计": "SUM",
    "合计": "SUM",
    "统计": "COUNT",
    "最多": "MAX",
    "最少": "MIN",
    "平均": "AVG",
    "几次": "COUNT",
}


def _extract_operation(query: str) -> tuple[Operation, bool]:
    for kw, agg in _AGG_OP_WORDS.items():
        if kw in query:
            return Operation(aggregate=agg), True
    return Operation(), False


# ── Task 6: 规则层组装 + 置信度（§6.4）────────────────────────────────────────

_ALL_FIELDS: tuple[str, ...] = ("time", "entities", "relations", "intent", "constraints", "operation")


@dataclass
class RuleResult:
    """规则层单次提取结果（debug 端点 + 评估集溯源用，QP-12 不落库）。"""

    time: TimeConstraint = field(default_factory=TimeConstraint)
    constraints: dict = field(default_factory=dict)
    entities: list[EntityMention] = field(default_factory=list)
    intent: Intent | None = None
    intent_candidates: list[Intent] = field(default_factory=list)
    relations: list[RelationMention] = field(default_factory=list)
    operation: Operation = field(default_factory=Operation)
    context: dict = field(default_factory=dict)
    field_hits: dict[str, bool] = field(default_factory=dict)
    field_reasons: dict[str, str] = field(default_factory=dict)
    ambiguity_fields: list[str] = field(default_factory=list)  # 多候选字段（penalty）
    relevant_fields: set[str] = field(default_factory=set)
    relation_candidates: list[dict] = field(default_factory=list)  # 本次实际使用的候选（溯源）
    confidence: float = 0.0
    llm_upgraded: bool = False

    @property
    def missing_fields(self) -> list[str]:
        """未命中字段清单（Task 7 LLM 升级只补这些字段）。"""
        return [f for f in _ALL_FIELDS if f in self.relevant_fields and not self.field_hits.get(f)]


async def understand(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    *,
    context: dict | None = None,
    top_k: int = 5,
) -> RuleResult:
    """规则层理解主入口（Task 6）。产出 RuleResult（含 StructuredQuery 组装）。

    confidence 机械计算（§6.4）：rule_coverage − 0.2 × 多候选字段数；
    ≥ 阈值直接产出（零 LLM），< 阈值由 Task 7 触发 LLM 升级（只补未命中字段）。
    """
    result = RuleResult()
    result.context = context or {}
    # 0. 动态候选（D2）
    rel_cands = await fetch_relation_candidates(engine, tenant_id)
    result.relation_candidates = rel_cands
    # 1. 各维度提取
    result.time, result.constraints, time_hit = _extract_time(query)
    result.entities = await _extract_entities(engine, tenant_id, query, context=context, top_k=top_k)
    result.intent, result.intent_candidates = _classify_intent(query)
    result.relations, _verbs = await _extract_relations(
        engine, tenant_id, query, result.entities, rel_cands, context=context
    )
    result.operation, op_hit = _extract_operation(query)

    # 2. 相关字段判定（§6.4：未涉及的维度不拉低覆盖率）
    relevant: set[str] = {"intent"}
    if time_hit:
        relevant.add("time")
    if _verb_hit(query):
        relevant.add("relations")
    if op_hit or any(
        kw in query for kw in ("有多少", "数量", "统计", "最多", "最少", "平均", "总计", "合计", "几次")
    ):
        relevant.add("operation")
    if result.constraints:
        relevant.add("constraints")
    if _entity_relevant(query, context):
        relevant.add("entities")
    result.relevant_fields = relevant

    # 3. 命中判定
    hits: dict[str, bool] = {
        "time": time_hit,
        "entities": bool(result.entities),
        "relations": bool(result.relations),
        "intent": result.intent is not None,
        "constraints": bool(result.constraints),
        "operation": op_hit,
    }
    result.field_hits = {f: hits[f] for f in _ALL_FIELDS}

    # 4. 未命中原因（回落标注，QP-14：不静默当 FACT）
    if result.intent is None:
        result.field_reasons["intent"] = "规则层未命中可靠子集关键词——显式回落（QP-14），待 LLM 升级或 Phase C 标注回落"
    if not result.entities:
        result.field_reasons["entities"] = "lookup_entities 无命中（含指代消解尝试）"
    if not result.relations and _verb_hit(query):
        result.field_reasons["relations"] = "动词命中但无合格 subject/候选（方向校验或动态候选缺失）"

    # 5. 多候选歧义（ambiguity_penalty）
    ambiguous: list[str] = []
    if len(result.intent_candidates) > 1:
        ambiguous.append("intent")
    result.ambiguity_fields = ambiguous

    # 6. 置信度（§6.4）
    n_relevant = max(1, len(relevant))
    n_hit = sum(1 for f in relevant if hits.get(f))
    rule_coverage = n_hit / n_relevant
    ambiguity_penalty = 0.2 * len(ambiguous)
    result.confidence = round(max(0.0, min(1.0, rule_coverage - ambiguity_penalty)), 3)
    return result


def build_structured_query(result: RuleResult) -> StructuredQuery:
    """RuleResult → StructuredQuery（§6.2 冻结模型；intent 兜底 FACT + 低置信标注）。

    规则层/LLM 均未可靠分类时兜底 FACT（plan_fact 是最通用回落策略，§11.2），
    但 field_reasons 保留「未分类」事实——Phase C select_plan 据此显式回落，
    不静默（QP-14）。
    """
    return StructuredQuery(
        entities=result.entities,
        relations=result.relations,
        intent=result.intent if result.intent is not None else Intent.FACT,
        constraints=result.constraints,
        time=result.time,
        operation=result.operation,
        confidence=result.confidence,
    )


# ── Task 8: derive_needs() 纯函数（§7，单一来源 = §8.2 通道角色表）─────────────
_DOCUMENT_MAIN_INTENTS: frozenset[Intent] = frozenset(
    {Intent.AGGREGATION, Intent.COMPARISON, Intent.TREND}
)
_STRUCTURED_INTENTS: frozenset[Intent] = frozenset(
    {Intent.AGGREGATION, Intent.COMPARISON, Intent.TREND, Intent.CAUSAL, Intent.MIXED}
)


def derive_needs(q: StructuredQuery) -> dict[str, bool]:
    """Retrieval Need 推导（§7 逐条，纯函数无 IO）。

    由 §8.2 通道角色表单一来源机械推导（QP-12：派生不存储，存储不派生）——
    document_evidence = intent ∉ {AGGREGATION, COMPARISON, TREND}（chunk 是
    主/佐证通道）；structured_data = intent ∈ 结构化四类。
    """
    return {
        "entity_resolution": bool(q.entities),
        "relation_reasoning": bool(q.relations),
        "document_evidence": q.intent not in _DOCUMENT_MAIN_INTENTS,
        "structured_data": q.intent in _STRUCTURED_INTENTS,
        "metadata_filter": bool(q.constraints),
        "aggregation": q.operation.aggregate is not None,
        "real_time": q.time.kind in ("relative", "absolute") and q.intent in _STRUCTURED_INTENTS,
    }


# ── Task 7: LLM 低置信度升级（决策 D4 方案 A）─────────────────────────────────

_DEFAULT_CONF_THRESHOLD = 0.7  # §6.4；settings 可配 EARP_QU_CONFIDENCE_THRESHOLD（D5）


async def upgrade_with_llm(
    engine: AsyncEngine,
    tenant_id: str,
    query: str,
    result: RuleResult,
    settings=None,
    *,
    threshold: float = _DEFAULT_CONF_THRESHOLD,
) -> RuleResult:
    """低置信度 LLM 升级（Task 7）：只补未命中字段（§6.1，省 token）。

    - confidence ≥ threshold → 原样返回（零 LLM）
    - < threshold → LLM 只补 `result.missing_fields`；输出过 schema 校验 +
      relation ∈ TBox 过滤（D4）；LLM 不可达/非法 → 保持规则结果（回落），
      schema 合规率 100% 不破
    - 升级后重算置信度（补命中字段反映到覆盖率）
    """
    if result.confidence >= threshold:
        return result
    missing = result.missing_fields
    if not missing:
        result.confidence = 1.0
        return result
    if settings is None:
        result.field_reasons["llm"] = "settings 未注入——跳过 LLM 升级（保持规则结果）"
        return result

    # 全局默认 LLM（D4：与 suggest 一致，DB 优先 env 兜底）
    llm_cfg: dict = {}
    try:
        from earp_server.admin import model_service as _ms

        llm_cfg = (await _ms.load_runtime_models(engine, tenant_id)).get("llm") or {}
    except Exception:
        logger.warning("upgrade_with_llm: load_runtime_models failed — env defaults", exc_info=True)
    from earp_server.connector import LLMConnector

    conn = LLMConnector(settings, model_override=llm_cfg or None)
    rel_desc = ", ".join(
        f"{c['relation_type_id']}({c['source_type']}→{c['target_type']})" for c in result.relation_candidates
    )
    system = (
        "你是企业知识库查询理解助手。把用户查询解析为结构化 JSON，"
        "只能输出 JSON 对象，不得输出任何其他内容。"
    )
    prompt = (
        f"解析以下用户查询（只补未命中字段：{missing}）：\n\n"        "规则：\n"
        "1. intent 只能取枚举值之一：FACT, ATTRIBUTE, RELATION, MULTI_HOP, LIST, "
        "AGGREGATION, COMPARISON, TREND, CAUSAL, MIXED\n"
        "2. relations 的 relation 只能从候选关系中选择，禁止发明：" + (rel_desc or "（无候选）") + "\n"
        "3. entities 是 [{\"mention\": \"实体名\", \"semantic_type\": \"类型\"}] 形式\n"
        "4. constraints 是文档元数据过滤（如 department/year/doc_type），time 单独用 "
        "{\"kind\": \"relative|absolute|none\", \"expression\": \"...\"}\n"
        "5. 只补未命中字段，已命中字段不要输出\n\n"
        "输出 JSON 形如：{\"intent\": \"FACT\", \"entities\": [], \"relations\": [], "
        "\"constraints\": {}, \"time\": {\"kind\": \"none\"}}\n\n"
        f"用户查询：{query}\n"
        f"上下文：{json.dumps(result.context or {})}"
    )
    result.llm_upgraded = True  # 尝试走 LLM 升级（成功/失败均标记，debug 可溯源）
    # 超时预算（默认 8s）：小模型 JSON 生成可吃满 30s 默认超时——QU 节点等不起，
    # 超时即回落规则结果（置信度升级失败不影响）。settings 注入时读取。
    budget = 8.0
    if settings is not None:
        budget = float(getattr(settings, "qu_upgrade_timeout_seconds", 8.0) or 8.0)
    # 升级结果 LRU 缓存（键 = tenant+query，含负缓存：超时/失败也记 None——弱模型同问题
    # 重复询问不再白等预算，直接规则回落）。规则层对同 query 输出确定 → 缓存安全。
    key = (tenant_id, query)
    data = _UPGRADE_CACHE.get(key, _CACHE_MISS)
    if data is _CACHE_MISS:
        data = await conn.json_complete(system, prompt, timeout=budget)
        _UPGRADE_CACHE[key] = data  # 成功 dict 或失败 None 均缓存
        _UPGRADE_CACHE.move_to_end(key)
        if len(_UPGRADE_CACHE) > _UPGRADE_CACHE_MAX:
            _UPGRADE_CACHE.popitem(last=False)
    if data is None:
        result.field_reasons["llm"] = "LLM 不可达/非 JSON——保持规则结果（回落）"
        return result
    # 只补未命中字段 + schema 校验（D4：LLM 输出必须过校验，非法回落）
    try:
        if "intent" in missing and data.get("intent"):
            iv = str(data["intent"]).upper()
            if iv in Intent.__members__:
                result.intent = Intent[iv]
                result.field_hits["intent"] = True
            else:
                result.field_reasons["intent"] = (
                    result.field_reasons.get("intent", "") + "；LLM 非法 intent 已拒"
                )
        if "entities" in missing and data.get("entities"):
            parsed = [EntityMention(**e) for e in data["entities"]]
            if parsed:
                result.entities = parsed
                result.field_hits["entities"] = True
        # relations/entities 额外允许「LLM 主动输出 + result 当前为空」——实体/关系是
        # LLM 最能提供增量价值的字段，schema 校验（TBox）已是硬门槛（D4）；
        # 已命中字段不重做（§6.1）
        if data.get("relations") and not result.relations:
            try:
                parsed = [RelationMention(**r) for r in data["relations"]]
            except Exception:
                parsed = []
            valid = validate_relation_sources(parsed, result.relation_candidates)
            if valid:
                result.relations = valid
                result.field_hits["relations"] = True
            if len(valid) != len(parsed):
                result.field_reasons["relations"] = (
                    result.field_reasons.get("relations", "") + "；LLM 发明关系已过滤"
                )
        if data.get("entities") and not result.entities:
            try:
                parsed = [EntityMention(**e) for e in data["entities"]]
            except Exception:
                parsed = []
            if parsed:
                result.entities = parsed
                result.field_hits["entities"] = True
        if "constraints" in missing and isinstance(data.get("constraints"), dict):
            if data["constraints"]:
                result.constraints = data["constraints"]
                result.field_hits["constraints"] = True
        if "time" in missing and isinstance(data.get("time"), dict):
            t = data["time"]
            result.time = TimeConstraint(
                kind=t.get("kind") if t.get("kind") in ("absolute", "relative", "none") else "none",
                expression=t.get("expression"),
            )
            result.field_hits["time"] = True
    except Exception:
        logger.warning("upgrade_with_llm: LLM 输出 merge 失败，保持规则结果", exc_info=True)

    # 重算置信度（补命中后；LLM 补丁不计歧义 penalty 变化）
    n_relevant = max(1, len(result.relevant_fields))
    n_hit = sum(1 for f in result.relevant_fields if result.field_hits.get(f))
    result.confidence = round(
        max(0.0, min(1.0, n_hit / n_relevant - 0.2 * len(result.ambiguity_fields))), 3
    )
    return result
