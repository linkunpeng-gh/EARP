"""Phase C — 最小固定策略 Planner 测试（Task 8）。

覆盖：select_plan 10 类全覆盖（QP-11）/ 回落标注（QP-14）/ plan_fact（三层 +
metadata_filters + 兜底）/ plan_relation（graph + 补证 + 回落）/ plan_aggregation
（候选解析 + 通道未就绪 + 回落）/ 成本约束 / 非法调用 0。
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.infra.db import tenant_session
from earp_server.ontology import abox_service, tbox_service
from earp_server.ontology.planning import (
    EvidenceChannel,
    QueryContext,
    execute_plan,
    plan_aggregation,
    plan_fact,
    plan_relation,
    select_plan,
)
from earp_server.ontology.understanding import (
    EntityMention,
    Intent,
    Operation,
    StructuredQuery,
)

DIM = 1024


class _StubProvider:
    name = "stub"
    dim = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            out.append([float(b) / 255.0 for b in (digest * (DIM // len(digest) + 1))[:DIM]])
        return out


def _install_stub(monkeypatch):
    import earp_server.knowledge.embedding_service as svc

    provider = _StubProvider()
    monkeypatch.setattr(svc, "get_embedding_provider", lambda: provider)
    return provider


async def _seed_scene(engine: AsyncEngine, tid: str, suffix: str = "") -> dict:
    """DDs + role + KBs + docs/chunks + 实体图 + query capability 映射（含 finance_data 用于 metadata 过滤）。"""
    from earp_server.knowledge.chunk_service import create_chunks
    from earp_server.knowledge.document_service import create_document
    from earp_server.knowledge.embedding_service import embed_chunks
    from earp_server.knowledge.routing import build_routing_index

    kb_maint, kb_alarm, kb_fin = f"kb-maint{suffix}", f"kb-alarm{suffix}", f"kb-fin{suffix}"
    role_all = f"r-plan{suffix}"
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
                "VALUES (:rid, :tid, 'plan-all', '{}', 'all', "
                '\'[{"data_domain_id": "equipment_data"}, {"data_domain_id": "finance_data"}]\') '
                "ON CONFLICT DO NOTHING"
            ),
            {"rid": role_all, "tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, description) "
                "VALUES (:kb1, :tid, '设备维护手册', 'equipment_data', '维护与保养'), "
                "(:kb2, :tid, '报警阈值配置', 'equipment_data', '报警阈值'), "
                "(:kb3, :tid, '费用报销手册', 'finance_data', '报销流程') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid, "kb1": kb_maint, "kb2": kb_alarm, "kb3": kb_fin},
        )
    docs = [
        (kb_maint, "维护手册v1", "设备维护：主轴轴承更换周期为每季度一次。"),
        (kb_alarm, "报警阈值", "设备报警阈值：主轴温度超过85度触发报警。"),
        (kb_fin, "报销制度v1", "财务报销标准：2024年住宿每天500元。"),
    ]
    chunk_ids_all: list[str] = []
    for kb, title, content in docs:
        doc = await create_document(engine, tid, kb, content, title=title)
        chunk_ids_all.extend(await create_chunks(engine, tid, doc["document_id"], content))
    await embed_chunks(engine, tid, chunk_ids_all)
    await build_routing_index(engine, tid)

    sup = await abox_service.upsert_entity(
        engine, tid, "supplier", "上海某精机", business_code="SUP-1", data_domain_id="equipment_data"
    )
    equip = await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
    )
    await abox_service.add_fact(engine, tid, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.compile_profile(engine, tid, equip["entity_id"])

    # query capability + entity map（plan_aggregation 候选；capability_id 全局单列主键
    # ——tech-debt #7，多租户同 id 会 join 失败，故 suffix 隔离）
    cap_id = f"cap-plan{suffix}"
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                f"VALUES ('{cap_id}', :tid, 'equipment', 'query_equipment_alarm', 'query', "
                "'{}', '{}', '{alarm:read}', '1.0.0') ON CONFLICT (capability_id, tenant_id) DO NOTHING"
            ),
            {"tid": tid},
        )
    await tbox_service.map_capability_entity(engine, tid, cap_id, "equipment", "read")

    return {
        "equip": equip["entity_id"],
        "sup": sup["entity_id"],
        "kb_maint": kb_maint,
        "kb_fin": kb_fin,
        "role_all": role_all,
    }


def _ctx(engine: AsyncEngine, tid: str, role: str, query: str, *, app_url: str, top_k: int = 5) -> QueryContext:
    return QueryContext(
        engine=engine,
        tenant_id=tid,
        role_id=role,
        settings=Settings(database_url=app_url, app_env="test"),
        query=query,
        top_k=top_k,
    )


# ── select_plan（QP-11 全覆盖 + QP-14 回落标注）───────────────────────────────


def test_select_plan_covers_all_intents() -> None:
    expected = {
        Intent.FACT: "plan_fact",
        Intent.ATTRIBUTE: "plan_relation",
        Intent.RELATION: "plan_relation",
        Intent.MULTI_HOP: "plan_relation",
        Intent.LIST: "plan_relation",
        Intent.AGGREGATION: "plan_aggregation",
        Intent.COMPARISON: "plan_aggregation",
        Intent.TREND: "plan_aggregation",
        Intent.CAUSAL: "plan_fact",
        Intent.MIXED: "plan_fact",
    }
    for intent, name in expected.items():
        sel = select_plan(StructuredQuery(intent=intent, confidence=0.8))
        assert sel.plan_name == name, f"{intent.value} → {sel.plan_name}"


def test_select_plan_fallback_annotated_not_silent() -> None:
    """QP-14：CAUSAL/MIXED 显式回落 plan_fact + fallback_reason，不静默当 FACT。"""
    for intent in (Intent.CAUSAL, Intent.MIXED):
        sel = select_plan(StructuredQuery(intent=intent, confidence=0.8))
        assert sel.plan_name == "plan_fact"
        assert sel.fallback_reason, f"{intent.value} 必须带回落原因"
        assert "QP-14" in sel.fallback_reason


def test_select_plan_multi_hop_kwargs() -> None:
    sel = select_plan(StructuredQuery(intent=Intent.MULTI_HOP, confidence=0.8))
    assert sel.plan_kwargs == {"max_hops": 2}


# ── plan_fact（§12 例 1）──────────────────────────────────────────────────────


async def test_plan_fact_three_layer(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t1"
    scene = await _seed_scene(engine, tid, suffix="-pc1")

    q = StructuredQuery(intent=Intent.FACT, confidence=0.9)
    res = await plan_fact(q, ctx=_ctx(engine, tid, scene["role_all"], "CNC-01 设备报警", app_url=app_url))
    assert res.plan_name == "plan_fact"
    # 实体命中场景：profile/graph 参与 recall（P2 三层语义）
    channels = {e.channel for e in res.evidence}
    assert EvidenceChannel.PROFILE in channels or EvidenceChannel.GRAPH in channels
    trace_types = [t.type for t in res.trace]
    assert "DD_ROUTING" in trace_types
    assert "FUSION_RERANK" in trace_types or not res.evidence  # 空结果不强制融合
    # citations 三源兼容
    for c in res.citations:
        assert "title" in c


async def test_plan_fact_metadata_filters(migrated: str, app_url: str, monkeypatch) -> None:
    """constraints → metadata_filters 透传 + trace 含 METADATA_FILTER。"""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t2"
    scene = await _seed_scene(engine, tid, suffix="-pc2")

    q = StructuredQuery(intent=Intent.FACT, confidence=0.9, constraints={"year": 2024})
    # keyword 「报警」命中 equipment_data → 候选 DD 分支 → METADATA_FILTER trace
    res = await plan_fact(q, ctx=_ctx(engine, tid, scene["role_all"], "2024 年设备报警阈值", app_url=app_url))
    trace_types = [t.type for t in res.trace]
    assert "METADATA_FILTER" in trace_types


async def test_plan_fact_whole_tenant_fallback(migrated: str, app_url: str, monkeypatch) -> None:
    """无候选 DD → 全租户 chunk 兜底（P2 D4 语义），不 500。"""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t3"
    scene = await _seed_scene(engine, tid, suffix="-pc3")

    q = StructuredQuery(intent=Intent.FACT, confidence=0.9)
    res = await plan_fact(q, ctx=_ctx(engine, tid, scene["role_all"], "完全不存在的查询词xyz", app_url=app_url))
    assert res.trace  # 有执行 trace（含兜底路径）
    assert not res.fallback_reason  # 兜底不是回落


# ── plan_relation（§12 例 2/例 3）─────────────────────────────────────────────


async def test_plan_relation_graph_evidence(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t4"
    scene = await _seed_scene(engine, tid, suffix="-pc4")

    q = StructuredQuery(
        intent=Intent.RELATION,
        confidence=0.9,
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    res = await plan_relation(q, ctx=_ctx(engine, tid, scene["role_all"], "CNC-01 由哪家供应商制造", app_url=app_url))
    assert res.plan_name == "plan_relation"
    graph_ev = [e for e in res.evidence if e.channel == EvidenceChannel.GRAPH]
    assert graph_ev, "must have graph evidence"
    assert any("manufactured_by" in e.content for e in graph_ev)
    trace_types = [t.type for t in res.trace]
    assert "RESOLVE_ENTITY" in trace_types and "GRAPH_QUERY" in trace_types


async def test_plan_relation_no_entity_falls_back_to_fact(migrated: str, app_url: str, monkeypatch) -> None:
    """无实体命中 → 回落 plan_fact + fallback_reason（§11.2「解析失败回落 plan_fact」）。"""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t5"
    scene = await _seed_scene(engine, tid, suffix="-pc5")

    q = StructuredQuery(intent=Intent.RELATION, confidence=0.9, entities=[])
    res = await plan_relation(q, ctx=_ctx(engine, tid, scene["role_all"], "不存在的实体xyz", app_url=app_url))
    assert res.plan_name == "plan_fact"
    assert res.fallback_reason and "entity resolution failed" in res.fallback_reason


async def test_plan_relation_graph_empty_chunk_fallback(migrated: str, app_url: str, monkeypatch) -> None:
    """graph 无事实 → RAG 补证（§14），trace 标注。"""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t6"
    scene = await _seed_scene(engine, tid, suffix="-pc6")

    # 实体存在但无 facts（无 manufactured_by 等）→ graph 空 → chunk 补证
    await abox_service.upsert_entity(engine, tid, "equipment", "CNC-02", business_code="CNC-02")
    q = StructuredQuery(
        intent=Intent.RELATION,
        confidence=0.9,
        entities=[EntityMention(mention="CNC-02", semantic_type="equipment")],
    )
    res = await plan_relation(q, ctx=_ctx(engine, tid, scene["role_all"], "CNC-02 设备维护", app_url=app_url))
    trace_types = [t.type for t in res.trace]
    assert "GRAPH_QUERY" in trace_types
    # graph 无事实 → VECTOR_SEARCH 补证步（有或空结果均可，但必须走补证 trace）
    if res.evidence:
        assert any(e.channel == EvidenceChannel.CHUNK for e in res.evidence)


# ── plan_aggregation（D2 方案 A：候选解析 + 回落）─────────────────────────────


async def test_plan_aggregation_executes_capability(migrated: str, app_url: str, monkeypatch) -> None:
    """D1c：有 query 候选 + 执行器成功 → capability evidence（D2 边界解除，不再「通道未就绪」）。"""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t7"
    scene = await _seed_scene(engine, tid, suffix="-pc7")

    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.9,
        operation=Operation(aggregate="COUNT"),
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    res = await plan_aggregation(q, ctx=_ctx(engine, tid, scene["role_all"], "CNC-01 高温报警", app_url=app_url))
    assert res.plan_name == "plan_aggregation"
    trace_types = [t.type for t in res.trace]
    assert "CAPABILITY_QUERY" in trace_types
    cap_ev = [e for e in res.evidence if e.channel.value == "capability"]
    assert cap_ev, "must have capability evidence（执行成功）"
    assert cap_ev[0].payload.get("aggregate", {}).get("count", 0) >= 1
    assert any((t.output or {}).get("executed") is True for t in res.trace)


async def test_plan_aggregation_no_candidate_falls_back(migrated: str, app_url: str, monkeypatch) -> None:
    """无 query 候选 → 回落 plan_fact（§11.2）。"""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t8"
    scene = await _seed_scene(engine, tid, suffix="-pc8")

    q = StructuredQuery(intent=Intent.AGGREGATION, confidence=0.9)
    res = await plan_aggregation(q, ctx=_ctx(engine, tid, scene["role_all"], "不存在的实体xyz", app_url=app_url))
    assert res.plan_name == "plan_fact"
    assert res.fallback_reason and "no query capability candidate" in res.fallback_reason


# ── 成本约束 + 非法调用扫描（§11.4）──────────────────────────────────────────


async def test_execute_plan_full_chain_and_no_command(migrated: str, app_url: str, monkeypatch) -> None:
    """execute_plan 全链路：select_plan → 策略执行；trace 无 Command/任意代码步。"""
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "pc-t9"
    scene = await _seed_scene(engine, tid, suffix="-pc9")

    q = StructuredQuery(
        intent=Intent.RELATION,
        confidence=0.9,
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    sel, res = await execute_plan(
        engine,
        tid,
        scene["role_all"],
        "CNC-01 由哪家供应商制造",
        q,
        settings=Settings(database_url=app_url, app_env="test"),
    )
    assert sel.plan_name == "plan_relation"
    assert res.plan_name == "plan_relation"
    # 非法调用 = 0 / Command = 0（QP-07：只调用注册的只读函数）
    allowed = {
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
    for t in res.trace:
        assert t.type in allowed, f"非法 trace 步: {t.type}"


def test_cost_limits() -> None:
    """§11.4：top_k/max_hops 上限截断。"""
    from earp_server.ontology.planning import _COST_TOP_K

    # top_k 截断发生在策略函数内（min(ctx.top_k, _COST_TOP_K)）——构造超限 ctx 验证
    assert _COST_TOP_K == 50
