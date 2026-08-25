"""Phase B — Query Understanding 规则层测试（Task 10）。

覆盖：schema 冻结 / 时间约束提取 / 实体提及（含纯中文长查询与指代消解）/
intent 分类（可靠子集 + 显式回落）/ relation 提取（动词 + 方向 + TBox 合规）/
置信度（§6.4 机械计算）/ derive_needs（§7 各推导规则）。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.ontology import abox_service, tbox_service
from earp_server.ontology.understanding import (
    EntityMention,
    Intent,
    Operation,
    RelationMention,
    StructuredQuery,
    TimeConstraint,
    _classify_intent,
    _extract_operation,
    _extract_time,
    build_structured_query,
    derive_needs,
    understand,
    upgrade_with_llm,
    validate_relation_sources,
)


def _test_settings(app_url: str) -> Settings:
    """Phase B 测试用 Settings（DB 指向 session 容器，LLM 走 env 兜底）。"""
    return Settings(database_url=app_url, app_env="test")


async def _seed_entity_graph(engine: AsyncEngine, tid: str) -> None:
    """最小实体图：CNC-01(equipment) —manufactured_by→ 上海某精机(supplier)；
    高温报警(alarm) —caused_by→ CNC-01。"""
    await tbox_service.init_tenant_tbox(engine, tid)
    sup = await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-1")
    equip = await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01", business_code="CNC-01")
    alarm = await abox_service.upsert_entity(engine, tid, "alarm", "高温报警")
    await abox_service.add_fact(engine, tid, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.add_fact(engine, tid, alarm["entity_id"], "caused_by", equip["entity_id"])


def _engine(app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


# ── schema 冻结（§6.2 逐字段）────────────────────────────────────────────────


def test_intent_enum_has_10_values() -> None:
    assert {i.value for i in Intent} == {
        "FACT", "ATTRIBUTE", "RELATION", "MULTI_HOP", "LIST",
        "AGGREGATION", "COMPARISON", "TREND", "CAUSAL", "MIXED",
    }


def test_time_constraint_fields() -> None:
    t = TimeConstraint()
    assert t.kind == "none"
    assert t.expression is None
    assert t.resolved_start is None and t.resolved_end is None
    t2 = TimeConstraint(kind="relative", expression="yesterday")
    assert t2.kind == "relative"


def test_structured_query_field_defaults() -> None:
    q = StructuredQuery(intent=Intent.FACT, confidence=0.8)
    assert q.entities == [] and q.relations == []
    assert q.constraints == {} and q.context == {}
    assert q.operation.aggregate is None
    assert q.answer_requirement.answer_type == "summary"
    assert q.answer_requirement.citation_required is True


def test_structured_query_confidence_range_enforced() -> None:
    with pytest.raises(ValidationError):
        StructuredQuery(intent=Intent.FACT, confidence=1.5)
    with pytest.raises(ValidationError):
        StructuredQuery(intent=Intent.FACT, confidence=-0.1)


# ── 时间/约束提取（§5.5/§6.3，D9）────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,kind,expr,constraints",
    [
        ("昨天华东一厂的报警", "relative", "yesterday", {}),
        ("最近三个月有多少次高温报警", "relative", "recent_三_months", {}),
        ("最近2周设备报警", "relative", "recent_2_weeks", {}),
        ("2024 年财务部的报销制度是什么", "none", None, {"year": 2024}),
        ("报销制度是什么", "none", None, {}),
        ("2024-03 的报销标准", "none", None, {"year": 2024, "month": 3}),
    ],
)
def test_extract_time(query, kind, expr, constraints) -> None:
    t, c, hit = _extract_time(query)
    assert t.kind == kind
    assert t.expression == expr
    assert c == constraints
    if kind != "none" or constraints:
        assert hit is True


# ── intent 分类（§5.4/QP-14，D3）─────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,expected",
    [
        ("报销制度是什么", Intent.FACT),
        ("设备维护标准有哪些", Intent.FACT),
        ("CNC-01 由哪家供应商制造", Intent.RELATION),
        ("谁负责 A产线", Intent.RELATION),
        ("昨天有多少次报警", Intent.AGGREGATION),
        ("最近三个月平均故障率", Intent.AGGREGATION),
    ],
)
def test_classify_intent_reliable_subset(query, expected) -> None:
    intent, cands = _classify_intent(query)
    assert intent == expected
    assert expected in cands


@pytest.mark.parametrize(
    "query",
    [
        "A产线和B产线的设备故障率对比",  # COMPARISON —— 不建关键词，显式回落
        "为什么主轴轴承最近故障变多",  # CAUSAL —— 回落
        "近一年设备故障的趋势如何",  # TREND —— 回落
        "设备、物料、产品的供应商列表",  # LIST —— 回落
    ],
)
def test_classify_intent_fallback_non_reliable(query) -> None:
    """其余 7 类不建关键词（QP-14）——规则层返回 None，由 LLM 升级/Phase C 显式回落。"""
    intent, cands = _classify_intent(query)
    assert intent is None
    assert cands == []


# ── operation 提取（§5.6）────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,agg",
    [
        ("有多少台设备", "COUNT"),
        ("平均故障率", "AVG"),
        ("最多报警的设备", "MAX"),
        ("报销制度是什么", None),
    ],
)
def test_extract_operation(query, agg) -> None:
    op, hit = _extract_operation(query)
    assert op.aggregate == agg
    assert hit is (agg is not None)


# ── derive_needs（§7，单一来源 = §8.2）───────────────────────────────────────


def test_derive_needs_fact_document_only() -> None:
    q = StructuredQuery(
        intent=Intent.FACT,
        confidence=0.9,
        constraints={"year": 2024},
        time=TimeConstraint(kind="relative", expression="yesterday"),
    )
    needs = derive_needs(q)
    assert needs["document_evidence"] is True
    assert needs["structured_data"] is False
    assert needs["metadata_filter"] is True
    assert needs["real_time"] is False  # 时间相关但非结构化查询


def test_derive_needs_aggregation_structured() -> None:
    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.8,
        operation=Operation(aggregate="COUNT"),
        time=TimeConstraint(kind="relative", expression="yesterday"),
        entities=[EntityMention(mention="CNC-01")],
    )
    needs = derive_needs(q)
    assert needs["document_evidence"] is False
    assert needs["structured_data"] is True
    assert needs["aggregation"] is True
    assert needs["entity_resolution"] is True
    assert needs["real_time"] is True


def test_derive_needs_relation() -> None:
    q = StructuredQuery(
        intent=Intent.RELATION,
        confidence=0.8,
        relations=[RelationMention(subject="CNC-01", relation="manufactured_by")],
    )
    needs = derive_needs(q)
    assert needs["relation_reasoning"] is True
    assert needs["document_evidence"] is True  # RELATION 的 chunk 佐证（graph 无事实时）


# ── relation schema 合规（D2 动态候选）───────────────────────────────────────


def test_validate_relation_sources_filters_non_tbox() -> None:
    cands = [
        {"relation_type_id": "manufactured_by", "source_type": "equipment", "target_type": "supplier"},
        {"relation_type_id": "located_in", "source_type": "equipment", "target_type": "plant"},
    ]
    from earp_server.ontology.understanding import RelationMention

    ok = validate_relation_sources(
        [
            RelationMention(subject="CNC-01", relation="manufactured_by"),
            RelationMention(subject="CNC-01", relation="made_up_rel"),  # LLM 发明场景
        ],
        cands,
    )
    assert [r.relation for r in ok] == ["manufactured_by"]


# ── 规则层 DB 路径（understand 主入口）───────────────────────────────────────


async def test_understand_entity_relation_query(migrated: str, app_url: str) -> None:
    """「CNC-01 由哪家供应商制造」→ 实体命中 + RELATION + manufactured_by（方向校验）。"""
    engine = _engine(app_url)
    tid = "qu-t1"
    await _seed_entity_graph(engine, tid)

    r = await understand(engine, tid, "CNC-01 由哪家供应商制造")
    assert r.intent == Intent.RELATION
    assert any(e.mention == "CNC-01" and e.semantic_type == "equipment" for e in r.entities)
    rels = [rel for rel in r.relations if rel.relation == "manufactured_by"]
    assert rels and rels[0].subject == "CNC-01"
    assert rels[0].object_type == "supplier"
    assert r.confidence >= 0.5  # intent+entities+relations 命中
    q = build_structured_query(r)
    assert q.intent == Intent.RELATION
    assert q.relations[0].relation == "manufactured_by"


async def test_understand_pure_chinese_entity_query(migrated: str, app_url: str) -> None:
    """纯中文实体长查询（2026-08-16 已修反向子串）：「高温报警由什么引起」→ 实体命中。"""
    engine = _engine(app_url)
    tid = "qu-t2"
    await _seed_entity_graph(engine, tid)

    r = await understand(engine, tid, "高温报警由什么引起")
    assert any(e.mention == "高温报警" and e.semantic_type == "alarm" for e in r.entities)
    # caused_by 动词命中 + subject=高温报警（alarm ∈ caused_by.source_type）
    assert any(rel.relation == "caused_by" and rel.subject == "高温报警" for rel in r.relations)


async def test_understand_fact_document_query(migrated: str, app_url: str) -> None:
    """纯文档查询（无实体）→ FACT、零实体、置信度不受实体 miss 拖累（相关字段判定）。"""
    engine = _engine(app_url)
    tid = "qu-t3"
    await _seed_entity_graph(engine, tid)

    r = await understand(engine, tid, "2024 年财务部的报销制度是什么")
    assert r.intent == Intent.FACT
    assert r.entities == []
    assert r.constraints == {"year": 2024}
    assert r.confidence >= 0.7  # intent+constraints+time 命中，实体/关系不相关
    assert "entities" not in r.relevant_fields


async def test_understand_coreference_resolution(migrated: str, app_url: str) -> None:
    """指代消解（D8）：「它」+ context.last_entities → 映射上文实体 semantic_type。"""
    engine = _engine(app_url)
    tid = "qu-t4"
    await _seed_entity_graph(engine, tid)

    ctx = {"conversation_id": "c1", "last_entities": [{"mention": "CNC-01", "semantic_type": "equipment"}]}
    r = await understand(engine, tid, "它是哪家供应商生产的", context=ctx)
    assert any(e.mention == "CNC-01" and e.semantic_type == "equipment" for e in r.entities)
    assert any(rel.relation == "manufactured_by" and rel.subject == "CNC-01" for rel in r.relations)


async def test_understand_confidence_ambiguity_penalty(migrated: str, app_url: str) -> None:
    """置信度（§6.4）：多候选 intent → 0.2 penalty。"""
    engine = _engine(app_url)
    tid = "qu-t5"
    await _seed_entity_graph(engine, tid)

    # "有多少台设备是哪个供应商制造的" —— AGGREGATION(多少) + RELATION(哪个/供应商) 双候选
    r = await understand(engine, tid, "有多少台设备是哪个供应商制造的")
    assert len(r.intent_candidates) >= 2
    assert "intent" in r.ambiguity_fields
    # 与无歧义版本对比：同命中数下 penalty 使置信度低 0.2
    r2 = await understand(engine, tid, "哪个供应商制造了 CNC-01")
    assert r2.ambiguity_fields == []
    assert r.confidence <= r2.confidence


# ── Task 7: LLM 低置信度升级（D4 方案 A）──────────────────────────────────────


async def test_upgrade_with_llm_high_confidence_no_llm_call(
    migrated: str, app_url: str, monkeypatch
) -> None:
    """高置信度（≥0.7）→ 零 LLM 调用（§6.1 规则优先）。"""
    engine = _engine(app_url)
    tid = "qu-t7"
    await _seed_entity_graph(engine, tid)

    r = await understand(engine, tid, "2024 年财务部的报销制度是什么")
    assert r.confidence >= 0.7
    called = False

    async def _boom(*a, **k):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr("earp_server.connector.LLMConnector.json_complete", _boom)
    out = await upgrade_with_llm(engine, tid, "2024 年财务部的报销制度是什么", r, settings=_test_settings(app_url))
    assert called is False
    assert out.llm_upgraded is False


async def test_upgrade_with_llm_low_confidence_fills_missing(
    migrated: str, app_url: str, monkeypatch
) -> None:
    """低置信度 → LLM 只补未命中字段（intent）；relation ∈ TBox 过滤（发明关系拒绝）。"""
    engine = _engine(app_url)
    tid = "qu-t8"
    await _seed_entity_graph(engine, tid)

    # 无关键词可命中 → intent miss + 低置信 → LLM 补
    r = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    assert r.intent is None
    assert r.confidence < 0.7

    async def _fake_complete(self, system, prompt, **kw):
        return {
            "intent": "CAUSAL",
            "relations": [
                {"subject": "主轴轴承", "relation": "caused_by"},  # 合法（caused_by ∈ TBox）
                {"subject": "主轴轴承", "relation": "invented_rel"},  # 发明 → 应过滤
            ],
        }

    monkeypatch.setattr("earp_server.connector.LLMConnector.json_complete", _fake_complete)
    out = await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r, settings=_test_settings(app_url))
    assert out.llm_upgraded is True
    assert out.intent == Intent.CAUSAL
    assert out.field_hits["intent"] is True
    rel_ids = [rel.relation for rel in out.relations]
    assert "caused_by" in rel_ids
    assert "invented_rel" not in rel_ids  # schema 合规 100%


async def test_upgrade_with_llm_llm_failure_falls_back(
    migrated: str, app_url: str, monkeypatch
) -> None:
    """LLM 不可达（None）→ 保持规则结果（回落），不抛异常。"""
    engine = _engine(app_url)
    tid = "qu-t9"
    await _seed_entity_graph(engine, tid)

    r = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    async def _no_llm(self, system, prompt, **kw):
        return None

    monkeypatch.setattr("earp_server.connector.LLMConnector.json_complete", _no_llm)
    out = await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r, settings=_test_settings(app_url))
    assert out.llm_upgraded is True  # 尝试过
    assert out.intent is None  # 规则结果保留
    assert "llm" in out.field_reasons


# ── Task 9: debug 端点 ────────────────────────────────────────────────────────


def test_understanding_debug_endpoint(migrated: str, app_url: str, monkeypatch) -> None:
    """POST /v1/ontology/understanding/debug：StructuredQuery + derive_needs + 命中明细。"""
    import asyncio

    import jwt
    from fastapi.testclient import TestClient

    from earp_server.config import Settings
    from earp_server.main import create_app

    tid = "qu-t10"
    engine = _engine(app_url)
    asyncio.run(_seed_entity_graph(engine, tid))

    app = create_app(Settings(database_url=app_url, app_env="test"))
    token = jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": "r-any", "exp": 9999999999},
        "earp-dev-secret-change-in-production",
        algorithm="HS256",
    )
    with TestClient(app) as c:
        resp = c.post(
            "/v1/ontology/understanding/debug",
            json={"query": "CNC-01 由哪家供应商制造"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sq = body["structured_query"]
        assert sq["intent"] == "RELATION"
        assert any(e["mention"] == "CNC-01" for e in sq["entities"])
        assert any(r["relation"] == "manufactured_by" for r in sq["relations"])
        assert body["derive_needs"]["relation_reasoning"] is True
        assert body["rule_fields"]["intent"] == "hit"
        assert body["relation_candidates_used"]  # 溯源非空


def test_understanding_debug_endpoint_fact_rule_only(migrated: str, app_url: str, monkeypatch) -> None:
    """高置信 FACT → llm_upgraded=false（零 LLM）；端点可配 threshold 覆盖。"""
    import asyncio

    import jwt
    from fastapi.testclient import TestClient

    from earp_server.config import Settings
    from earp_server.main import create_app

    tid = "qu-t11"
    engine = _engine(app_url)
    asyncio.run(_seed_entity_graph(engine, tid))

    app = create_app(Settings(database_url=app_url, app_env="test"))
    token = jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": "r-any", "exp": 9999999999},
        "earp-dev-secret-change-in-production",
        algorithm="HS256",
    )
    with TestClient(app) as c:
        resp = c.post(
            "/v1/ontology/understanding/debug",
            json={"query": "2024 年财务部的报销制度是什么"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["structured_query"]["intent"] == "FACT"
        assert body["structured_query"]["constraints"] == {"year": 2024}
        assert body["llm_upgraded"] is False  # 高置信（测试环境 LLM 不可达也会走规则）
        assert body["confidence"] >= 0.7


# ── Chatflow QU 提速：LLM 升级超时预算 + 结果缓存 ──────────────────────────────


async def test_upgrade_with_llm_passes_timeout_budget(migrated: str, app_url: str, monkeypatch) -> None:
    """升级用 settings.qu_upgrade_timeout_seconds 作 json_complete 超时（默认 8s，防 30s 超时拖垮 QU 节点）。"""
    engine = _engine(app_url)
    tid = "qu-t10"
    await _seed_entity_graph(engine, tid)

    r = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    seen: dict = {}

    async def _fake(self, system, prompt, **kw):
        seen["timeout"] = kw.get("timeout")
        return None

    monkeypatch.setattr("earp_server.connector.LLMConnector.json_complete", _fake)
    await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r, settings=_test_settings(app_url))
    assert seen.get("timeout") == 8.0  # 默认 8s 预算（曾实测吃满 30s 超时）


async def test_upgrade_with_llm_cache_reuses_second_same_query(migrated: str, app_url: str, monkeypatch) -> None:
    """同 (tenant, query) 第二次升级命中 LRU 缓存 → 零 LLM 调用（重复问题不再等模型）。"""
    engine = _engine(app_url)
    tid = "qu-t11"
    await _seed_entity_graph(engine, tid)

    r1 = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    calls: list[int] = []

    async def _fake(self, system, prompt, **kw):
        calls.append(1)
        return {"intent": "CAUSAL", "relations": []}

    monkeypatch.setattr("earp_server.connector.LLMConnector.json_complete", _fake)
    await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r1, settings=_test_settings(app_url))
    r2 = await understand(engine, tid, "主轴轴承最近为什么故障增加")  # 规则层确定性 → 新鲜等置信结果
    o2 = await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r2, settings=_test_settings(app_url))
    assert len(calls) == 1  # 第二次命中缓存，未再调 LLM
    assert o2.intent == Intent.CAUSAL


async def test_upgrade_with_llm_negative_cache_skips_retry(migrated: str, app_url: str, monkeypatch) -> None:
    """升级超时/失败后同问题第二次不再调 LLM（负缓存 → 直接规则回落，不再白等预算）。"""
    engine = _engine(app_url)
    tid = "qu-t12"
    await _seed_entity_graph(engine, tid)

    r1 = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    calls: list[int] = []

    async def _no_llm(self, system, prompt, **kw):
        calls.append(1)
        return None  # 模拟弱模型超时/失败

    monkeypatch.setattr("earp_server.connector.LLMConnector.json_complete", _no_llm)
    await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r1, settings=_test_settings(app_url))
    r2 = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    o2 = await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r2, settings=_test_settings(app_url))
    assert len(calls) == 1  # 第二次负缓存命中，零 LLM 调用
    assert o2.intent is None  # 规则回落保持一致


async def test_upgrade_with_llm_attaches_shared_llm_cache(migrated: str, app_url: str, monkeypatch) -> None:
    """F7 (Task 1 D1): upgrade_with_llm 构造的 connector 挂共享缓存（json_complete 才能命中）。"""
    from earp_server.ontology import understanding as U

    engine = _engine(app_url)
    tid = "qu-t13"
    await _seed_entity_graph(engine, tid)

    r = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    sentinel = object()
    monkeypatch.setattr(U, "_shared_llm_cache", lambda settings: sentinel)
    seen: dict = {}

    class _Recorder:
        def __init__(self, settings, *, model_override=None) -> None:
            self.cache = None

        async def json_complete(self, system, prompt, **kw):
            seen["cache"] = self.cache
            return {"intent": "CAUSAL", "relations": []}

    monkeypatch.setattr("earp_server.connector.LLMConnector", _Recorder)
    await U.upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r, settings=_test_settings(app_url))
    assert seen.get("cache") is sentinel  # fresh connector 已挂共享缓存


async def test_upgrade_with_llm_connector_cache_hit_across_tenants(migrated: str, app_url: str, monkeypatch) -> None:
    """F7 (Task 1 D1): 跨租户同 prompt 第二次升级命中 connector 缓存 → 零 LLM 调用。

    _UPGRADE_CACHE（tenant+query LRU）跨租户不命中；connector 缓存键 = model+messages
    （同 query+missing+context）→ 第二次直接命中，不再重复全量 LLM 调用。
    """
    from earp_server.ontology import understanding as U

    class _FakeCache:
        """内存版 LLMCache 替身（同 test_connector_timeout 模式）。"""

        def __init__(self) -> None:
            self.store: dict = {}

        async def get(self, model: str, key: str):
            return self.store.get(key)

        async def set(self, model: str, key: str, value) -> None:
            self.store[key] = value

    engine = _engine(app_url)
    cache = _FakeCache()
    calls: list[int] = []
    monkeypatch.setattr(U, "_shared_llm_cache", lambda settings: cache)

    async def _fake_json_complete(self, system, prompt, **kw):
        # 模拟真实 json_complete 的缓存读写（真实实现见 connector.json_complete）
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        key = f"{self._model}||json_complete||{json.dumps(msgs, ensure_ascii=False, sort_keys=True)}"
        cached = await cache.get(self._model, key)
        if cached is not None:
            return cached
        calls.append(1)
        data = {"intent": "CAUSAL", "relations": []}
        await cache.set(self._model, key, data)
        return data

    monkeypatch.setattr("earp_server.connector.LLMConnector.json_complete", _fake_json_complete)
    await _seed_entity_graph(engine, "qu-t14")
    r1 = await understand(engine, "qu-t14", "主轴轴承最近为什么故障增加")
    await upgrade_with_llm(engine, "qu-t14", "主轴轴承最近为什么故障增加", r1, settings=_test_settings(app_url))
    await _seed_entity_graph(engine, "qu-t15")
    r2 = await understand(engine, "qu-t15", "主轴轴承最近为什么故障增加")
    o2 = await upgrade_with_llm(engine, "qu-t15", "主轴轴承最近为什么故障增加", r2, settings=_test_settings(app_url))
    assert len(calls) == 1  # 第二租户同 prompt 命中 connector 缓存
    assert o2.intent == Intent.CAUSAL


# ── Part 2：QU 升级 prompt 模板（可配置） ─────────────────────────────────────


def test_upgrade_template_render() -> None:
    from earp_server.ontology.understanding import _render_upgrade_template

    out = _render_upgrade_template(
        "你是{角色}。查：{query}｜缺：{missing}｜候选：{relation_candidates}｜ctx：{context}",
        query="Q", missing="entities", rel_desc="has_part(A→B)", context="{}",
    )
    assert out == "你是{角色}。查：Q｜缺：entities｜候选：has_part(A→B)｜ctx：{}"
    # 未知占位符原样保留（便于排查自定义模板笔误）


def test_default_upgrade_prompt_keeps_json_braces() -> None:
    from earp_server.ontology.understanding import _default_upgrade_prompt

    p = _default_upgrade_prompt(missing="entities", rel_desc="has_part(A→B)", query="Q", context="{}")
    assert "\"mention\"" in p and "1. intent 枚举之一" in p and "查询：Q" in p


async def test_qu_prompt_template_get_set_roundtrip(migrated: str, app_url: str) -> None:
    """get/set 模板往返；无 llm 系统设置行 → set 拒绝。"""
    from earp_server.admin import model_service
    from earp_server.admin.model_service import create_model_config, set_system_model_settings

    engine = _engine(app_url)
    tid = "qu-t20"
    mc = await create_model_config(engine, tid, "ollama", "llm", f"qwen-tpl-{tid}", {"base_url": "http://x"})
    await set_system_model_settings(engine, tid, {"llm": mc["config_id"]})
    assert await model_service.get_qu_prompt_template(engine, tid) is None
    await model_service.set_qu_prompt_template(engine, tid, "模板A {query} {missing}")
    assert await model_service.get_qu_prompt_template(engine, tid) == "模板A {query} {missing}"
    await model_service.set_qu_prompt_template(engine, tid, "")  # 空串=清除
    assert await model_service.get_qu_prompt_template(engine, tid) is None
    # 无 llm 行 → 拒绝
    tid2 = "qu-t21"
    try:
        await model_service.set_qu_prompt_template(engine, tid2, "x")
        raise AssertionError("应拒绝")
    except ValueError:
        pass


async def test_upgrade_uses_tenant_template(migrated: str, app_url: str, monkeypatch) -> None:
    """配置了模板 → 升级 prompt 走模板（含占位符替换），未配置 → 内置压缩默认。"""
    from earp_server.admin import model_service
    from earp_server.admin.model_service import create_model_config, set_system_model_settings
    from earp_server.connector import LLMConnector

    engine = _engine(app_url)
    tid = "qu-t22"
    mc = await create_model_config(engine, tid, "ollama", "llm", f"qwen-tpl2-{tid}", {"base_url": "http://x"})
    await set_system_model_settings(engine, tid, {"llm": mc["config_id"]})
    tpl = "你是专家。查：{query}｜缺：{missing}｜候选：{relation_candidates}"
    await model_service.set_qu_prompt_template(engine, tid, tpl)

    r = await understand(engine, tid, "主轴轴承最近为什么故障增加")
    captured = {}
    orig = LLMConnector.json_complete

    async def _fake(self, system, prompt, **kw):
        captured["prompt"] = prompt
        return None

    monkeypatch.setattr(LLMConnector, "json_complete", _fake)
    await upgrade_with_llm(engine, tid, "主轴轴承最近为什么故障增加", r, settings=_test_settings(app_url))
    monkeypatch.setattr(LLMConnector, "json_complete", orig)
    assert captured["prompt"].startswith("你是专家。查：主轴轴承最近为什么故障增加｜缺：")  # 模板生效


def test_default_template_equals_tenant_template_rendering() -> None:
    """「载入默认」的文本（DEFAULT_UPGRADE_PROMPT_TEMPLATE）作为租户模板保存 → 渲染结果与内置默认一致。"""
    from earp_server.ontology.understanding import (
        DEFAULT_UPGRADE_PROMPT_TEMPLATE,
        _default_upgrade_prompt,
        _render_upgrade_template,
    )

    kwargs = dict(missing="entities", rel_desc="has_part(A→B)", query="Q", context="{}")
    assert _default_upgrade_prompt(**kwargs) == _render_upgrade_template(
        DEFAULT_UPGRADE_PROMPT_TEMPLATE, **kwargs
    )
    assert "{relation_candidates}" in DEFAULT_UPGRADE_PROMPT_TEMPLATE  # 与租户模板同占位符
    assert "{rel_desc}" not in DEFAULT_UPGRADE_PROMPT_TEMPLATE
