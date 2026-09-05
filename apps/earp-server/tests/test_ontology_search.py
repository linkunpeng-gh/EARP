"""PRD-2026-030 M2 — three-layer knowledge_search (RRF) + resolve_with_entities."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.ontology import abox_service, search, tbox_service

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


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def _install_stub(monkeypatch):
    import earp_server.knowledge.embedding_service as svc

    provider = _StubProvider()
    monkeypatch.setattr(svc, "get_embedding_provider", lambda: provider)
    return provider


async def _seed_entity_graph(engine: AsyncEngine, migration_url: str, tid: str) -> dict:
    """CNC-01 (equipment) —manufactured_by→ 上海某精机 (supplier); 高温报警 → CNC-01.

    2026-08-18 实体层域门禁后：实体需带 data_domain_id + seed 角色（role_id 单列
    主键 → migration 引擎 purge）。
    """
    await tbox_service.init_tenant_tbox(engine, tid)
    from sqlalchemy import text as _t

    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(_t("DELETE FROM roles WHERE role_id = 'r-any'"))
    await eng.dispose()

    async with engine.connect() as conn:
        await conn.execute(_t(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            _t(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) VALUES "
                "('equipment_data', :t, '设备数据', '设备', 'internal', 'active'), "
                "('quality_data', :t, '质量数据', '报警质量', 'internal', 'active'), "
                "('supply_chain_data', :t, '供应链数据', '供应商', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            _t(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-any', :t, 'tester', '{}', 'all', "
                '\'[{"data_domain_id": "equipment_data"}, {"data_domain_id": "quality_data"}, {"data_domain_id": "supply_chain_data"}]\', FALSE) ON CONFLICT DO NOTHING'  # noqa: E501 — 授权 JSON 单行（SQL 内嵌）
            ),
            {"t": tid},
        )
        await conn.commit()
    sup = await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-1")
    equip = await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
    )
    alarm = await abox_service.upsert_entity(engine, tid, "alarm", "高温报警")
    await abox_service.add_fact(engine, tid, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.add_fact(engine, tid, alarm["entity_id"], "caused_by", equip["entity_id"])
    await abox_service.compile_profile(engine, tid, equip["entity_id"])
    return {"equip": equip["entity_id"], "sup": sup["entity_id"], "alarm": alarm["entity_id"]}


async def test_knowledge_search_profile_layer(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "osr-t1"
    await _seed_entity_graph(engine, migrated, tid)

    # query matches entity name → profile layer hit first
    hits = await search.knowledge_search(engine, tid, "CNC-01", role_id="r-any", top_k=5, embedding_dim=DIM)
    assert hits, "must return hits"
    top = hits[0]
    assert top["source"] in ("profile", "graph")
    # graph layer must surface the supplier fact via traversal
    sources = {h["source"] for h in hits}
    assert "graph" in sources


async def test_knowledge_search_fallback_no_embedding(migrated: str, app_url: str, monkeypatch) -> None:
    """No embedding provider → profile/graph layers still work (vector degrades)."""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "osr-t2"
    await _seed_entity_graph(engine, migrated, tid)

    hits = await search.knowledge_search(engine, tid, "上海某精机", role_id="r-any", top_k=5)
    assert hits
    assert any(h["source"] == "profile" for h in hits)


async def test_graph_lane_dedup_selfcycle_and_relevance(app_engine: AsyncEngine, migrated: str) -> None:
    """2026-09 修复：图谱 lane 回环重复行不再给 RRF 重复计票 + 自指回环不入 lane。

    场景（对齐「3号矿有哪些运输系统」）：中心 hub has_subsystem→transport（直连答案）、
    has_coal_face→face；face located_in→hub（深度2 自指回环）；transport transports_for→face
    （face 深度2 重复出现）。修复前：face/中心靠重复票堆分，transport（单次出现）可能被
    挤出融合 top；修复后：自指回环剔除、同目标去重（face 只 1 票）、相关度重排 transport 在前。
    """
    tid = "osr-t4"
    await tbox_service.init_tenant_tbox(app_engine, tid)
    from sqlalchemy import text as _t

    purge = create_async_engine(migrated)
    async with purge.begin() as conn:
        await conn.execute(_t("DELETE FROM roles WHERE role_id = 'r-admin'"))
    await purge.dispose()
    async with app_engine.connect() as conn:
        await conn.execute(_t(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            _t(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-admin', :t, 'tester', '{}', 'all', '[]', TRUE) ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()

    hub = await abox_service.upsert_entity(app_engine, tid, "equipment", "3号矿", business_code="M-3")
    face = await abox_service.upsert_entity(app_engine, tid, "sensor", "3号矿综采一队工作面", business_code="F-1")
    truck = await abox_service.upsert_entity(app_engine, tid, "component", "3号矿矿卡运输系统", business_code="T-1")
    await abox_service.add_fact(app_engine, tid, hub["entity_id"], "has_subsystem", truck["entity_id"])
    await abox_service.add_fact(app_engine, tid, hub["entity_id"], "has_coal_face", face["entity_id"])
    await abox_service.add_fact(app_engine, tid, face["entity_id"], "located_in", hub["entity_id"])
    await abox_service.add_fact(app_engine, tid, truck["entity_id"], "transports_for", face["entity_id"])

    hits = await search.knowledge_search(
        app_engine, tid, "3号矿有哪些运输系统", role_id="r-admin", top_k=5, embedding=None
    )
    assert hits, "must return hits"
    # 自指回环（g:hub）不入融合
    assert not any(h["key"] == f"g:{hub['entity_id']}" for h in hits), [h["key"] for h in hits]
    # 直连答案 transport 在融合 top 且排在 face 前
    truck_hits = [h for h in hits if h["entity_id"] == truck["entity_id"]]
    assert truck_hits, [h["title"] for h in hits]
    truck_rank = hits.index(truck_hits[0])
    face_rank = next(i for i, h in enumerate(hits) if h["entity_id"] == face["entity_id"])
    assert truck_rank < face_rank, [h["title"] for h in hits]
    # 去重：face 只保留 1 票（深度1 has_coal_face）——rrf=1/(60+2)，不再累加 transports_for 深度2
    face_hit = next(h for h in hits if h["entity_id"] == face["entity_id"])
    assert abs(float(face_hit["rrf_score"]) - 1.0 / 62.0) < 1e-9, face_hit["rrf_score"]


async def test_graph_lane_two_hop_answer_surfaces(app_engine: AsyncEngine, migrated: str) -> None:
    """2026-09 A1：多跳答案不被一跳中间节点压住——「3号矿有多少台采煤机」。

    图谱 lane 用「残差查询」重排（扣掉已命中实体名 3号矿 → 剩「有多少台采煤机」）：
    一跳中间节点（综采设备组/工作面，只有前缀命中）rel→0，2 跳的采煤机（命中采煤/煤机）
    rel>0 排到 lane 前列并进入融合 top；修复前两者同分、tiebreak depth 把答案压到 lane 底部。
    """
    tid = "osr-t5"
    await tbox_service.init_tenant_tbox(app_engine, tid)
    from sqlalchemy import text as _t

    purge = create_async_engine(migrated)
    async with purge.begin() as conn:
        await conn.execute(_t("DELETE FROM roles WHERE role_id = 'r-admin'"))
    await purge.dispose()
    async with app_engine.connect() as conn:
        await conn.execute(_t(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            _t(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-admin', :t, 'tester', '{}', 'all', '[]', TRUE) ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()

    hub = await abox_service.upsert_entity(app_engine, tid, "equipment", "3号矿", business_code="M-3")
    grp = await abox_service.upsert_entity(app_engine, tid, "equipment_group", "3号矿综采设备组", business_code="EG-3")
    face = await abox_service.upsert_entity(app_engine, tid, "sensor", "3号矿综采一队工作面", business_code="F-3")
    s1 = await abox_service.upsert_entity(app_engine, tid, "shearer", "采煤机SL-301", business_code="SL-301")
    s2 = await abox_service.upsert_entity(app_engine, tid, "shearer", "采煤机SL-302", business_code="SL-302")
    await abox_service.add_fact(app_engine, tid, hub["entity_id"], "has_equipment_group", grp["entity_id"])
    await abox_service.add_fact(app_engine, tid, hub["entity_id"], "has_coal_face", face["entity_id"])
    await abox_service.add_fact(app_engine, tid, grp["entity_id"], "equipped_with", s1["entity_id"])
    await abox_service.add_fact(app_engine, tid, grp["entity_id"], "equipped_with", s2["entity_id"])
    await abox_service.add_fact(app_engine, tid, face["entity_id"], "located_in", hub["entity_id"])

    hits = await search.knowledge_search(
        app_engine, tid, "3号矿有多少台采煤机", role_id="r-admin", top_k=5, embedding=None
    )
    # 两个 2 跳采煤机进入融合 top（修复前被 3号矿XXX 前缀的一跳邻居按 depth 压到 lane 尾部）
    shearer_ids = {s1["entity_id"], s2["entity_id"]}
    fused_ids = {h["entity_id"] for h in hits if h.get("entity_id")}
    assert shearer_ids & fused_ids, [h["title"] for h in hits]
    # 直连中间节点（综采设备组）不出现在采煤机之前
    grp_idx = next((i for i, h in enumerate(hits) if h.get("entity_id") == grp["entity_id"]), None)
    s1_idx = next(i for i, h in enumerate(hits) if h.get("entity_id") == s1["entity_id"])
    if grp_idx is not None:
        assert s1_idx < grp_idx, [h["title"] for h in hits]


def test_rrf_merge_ordering() -> None:
    lane_a = [
        {"key": "x1", "source": "profile", "content": "a"},
        {"key": "x2", "source": "profile", "content": "b"},
    ]
    lane_b = [
        {"key": "x2", "source": "graph", "content": "c"},
        {"key": "x3", "source": "graph", "content": "d"},
    ]
    merged = search._rrf_merge([lane_a, lane_b], top_k=3)
    # x2 appears in both lanes → highest RRF score
    assert merged[0]["key"] == "x2"
    assert len(merged) == 3


async def test_resolve_with_entities_narrows_candidates(app_engine: AsyncEngine) -> None:
    tid = "osr-t3"
    await tbox_service.init_tenant_tbox(app_engine, tid)

    from sqlalchemy import text

    async with tenant_session(app_engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                "VALUES ('cap-osr-query', :tid, 'equipment', 'query_alarms', 'query', "
                "'{}', '{}', '{alarm:read}', '1.0.0') ON CONFLICT (capability_id, tenant_id) DO NOTHING"
            ),
            {"tid": tid},
        )
    await tbox_service.map_capability_entity(app_engine, tid, "cap-osr-query", "equipment", "read")

    # intent mentions an entity that exists → narrowed candidates include the mapped capability
    await abox_service.upsert_entity(app_engine, tid, "equipment", "CNC-01", business_code="CNC-01")
    caps = await search.resolve_with_entities(app_engine, tid, "CNC-01 高温报警")
    assert any(c["capability_id"] == "cap-osr-query" for c in caps)

    # intent with no entity match → empty (caller falls back to full discovery)
    assert await search.resolve_with_entities(app_engine, tid, "不存在的实体关键词xyz") == []


# ── P2: ontology 接入软路由（Task 5）──────────────────────────────────────────
# 验证 knowledge_search 新参数（knowledge_base_ids 透传 / title / chunk 字段保留）
# + /knowledge/search 无 scope 路径三层生效 + 权限限域。


async def _seed_p2_routing_scene(engine: AsyncEngine, tid: str, suffix: str = "") -> dict:
    """DDs + role + KB + docs + entity graph（CNC-01/上海某精机 in equipment_data、
    财务系统 in finance_data）——P2 软路由场景种子。suffix 隔离全局唯一 id
    （knowledge_base_id / role_id 非复合主键，跨租户复用会冲突）。"""
    from sqlalchemy import text

    from earp_server.knowledge.chunk_service import create_chunks
    from earp_server.knowledge.document_service import create_document
    from earp_server.knowledge.embedding_service import embed_chunks
    from earp_server.knowledge.routing import build_routing_index

    kb_maint, kb_alarm, kb_fin = f"kb-maint{suffix}", f"kb-alarm{suffix}", f"kb-fin{suffix}"
    role_eq, role_all = f"r-p2-eq{suffix}", f"r-p2-all{suffix}"
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
                "VALUES (:rid, :tid, 'eq-only', '{}', 'all', "
                '\'[{"data_domain_id": "equipment_data"}]\') ON CONFLICT DO NOTHING'
            ),
            {"rid": role_eq, "tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'all', '{}', 'all', "
                '\'[{"data_domain_id": "equipment_data"}, '
                '{"data_domain_id": "finance_data"}]\') ON CONFLICT DO NOTHING'
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
        (kb_fin, "报销制度v1", "财务报销标准：住宿每天500元。"),
    ]
    chunk_ids_all: list[str] = []
    for kb, title, content in docs:
        doc = await create_document(engine, tid, kb, content, title=title)
        chunk_ids_all.extend(await create_chunks(engine, tid, doc["document_id"], content))
    await embed_chunks(engine, tid, chunk_ids_all)
    await build_routing_index(engine, tid)

    sup = await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-1")
    equip = await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
    )
    await abox_service.add_fact(engine, tid, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.compile_profile(engine, tid, equip["entity_id"])
    fin = await abox_service.upsert_entity(engine, tid, "employee", "财务系统", business_code="FIN-SYS")
    return {
        "equip": equip["entity_id"],
        "sup": sup["entity_id"],
        "fin": fin["entity_id"],
        "kb_maint": kb_maint,
        "kb_alarm": kb_alarm,
        "kb_fin": kb_fin,
        "role_eq": role_eq,
        "role_all": role_all,
    }


async def test_knowledge_search_pure_chunk_regression(migrated: str, app_url: str, monkeypatch) -> None:
    """无实体命中 → 全 chunk（原行为回归）；chunk item 保留 kb_id/kb_name/title/metadata/similarity。"""
    provider = _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "p2-t1"
    scene = await _seed_p2_routing_scene(engine, tid, suffix="-t1")

    emb = (await provider.embed(["报销标准"]))[0]
    hits = await search.knowledge_search(
        engine,
        tid,
        "报销标准",
        embedding=emb,
        role_id=scene["role_all"],
        top_k=5,
        data_domain_ids=["finance_data"],
        embedding_dim=DIM,
    )
    assert hits, "must return chunk hits"
    assert all(h["source"] == "chunk" for h in hits)
    first = hits[0]
    assert first["kb_id"] == scene["kb_fin"]  # 限域 finance_data → 只有 kb-fin 的 chunk
    assert first["kb_name"]
    assert first["title"]
    assert "similarity" in first


async def test_knowledge_search_kb_limit_layer3(migrated: str, app_url: str, monkeypatch) -> None:
    """knowledge_base_ids 透传：L3 chunk 限定到指定 KB；L1/L2 实体层不受 KB 限制。"""
    provider = _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "p2-t2"
    scene = await _seed_p2_routing_scene(engine, tid, suffix="-t2")

    emb = (await provider.embed(["CNC-01 设备维护"]))[0]
    hits = await search.knowledge_search(
        engine,
        tid,
        "CNC-01 设备维护",
        embedding=emb,
        role_id=scene["role_eq"],
        top_k=10,
        data_domain_ids=["equipment_data"],
        knowledge_base_ids=[scene["kb_maint"]],
        embedding_dim=DIM,
    )
    sources = {h["source"] for h in hits}
    assert "profile" in sources  # 实体层不受 KB 限制
    for h in hits:
        if h["source"] == "chunk":
            assert h["kb_id"] == scene["kb_maint"]  # L3 限定


async def test_knowledge_search_dd_permission_scope(migrated: str, app_url: str, monkeypatch) -> None:
    """候选 DD（已权限过滤）限定实体层：无权限 DD 的实体不进 profile 结果（决策 D1）。"""
    provider = _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "p2-t3"
    scene = await _seed_p2_routing_scene(engine, tid, suffix="-t3")

    emb = (await provider.embed(["CNC-01 财务系统"]))[0]
    hits = await search.knowledge_search(
        engine,
        tid,
        "CNC-01 财务系统",
        embedding=emb,
        role_id=scene["role_eq"],
        top_k=10,
        data_domain_ids=["equipment_data"],  # 模拟 route_query 权限过滤后的候选 DD
        embedding_dim=DIM,
    )
    assert hits
    profile_ids = {h["entity_id"] for h in hits if h["source"] == "profile"}
    assert scene["equip"] in profile_ids
    assert scene["fin"] not in profile_ids  # finance 域实体不在候选 DD → 不返回


def test_knowledge_search_endpoint_soft_route_three_layer(
    migrated: str,
    app_url: str,
    monkeypatch,
) -> None:
    """/knowledge/search 无 scope：keyword 命中 equipment_data → 三层检索，profile/graph 参与。"""
    import asyncio

    import jwt
    from fastapi.testclient import TestClient

    from earp_server.config import Settings
    from earp_server.main import create_app

    _install_stub(monkeypatch)
    tid = "p2-t4"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    scene = asyncio.run(_seed_p2_routing_scene(engine, tid, suffix="-t4"))

    app = create_app(Settings(database_url=app_url, app_env="test"))
    token = jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": scene["role_eq"], "exp": 9999999999},
        "earp-dev-secret-change-in-production",
        algorithm="HS256",
    )
    with TestClient(app) as c:
        resp = c.post(
            "/knowledge/search",
            json={"query": "CNC-01 设备报警", "top_k": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert items
        sources = {i.get("source") for i in items}
        assert "profile" in sources or "graph" in sources


async def test_entity_lane_scoped_by_role_domains_not_routing(migrated: str, app_url: str, monkeypatch) -> None:
    """2026-08-18 FDE 修复：实体层按角色允许域（非路由候选 DD）限定。

    路由候选错选 finance_data（文档层信号），但实体 CNC-01 在 equipment_data
    → 修复前 profile/graph 被候选 DD 滤掉不生效；修复后实体层按角色域独立生效。
    跨域实体（财务系统，finance_data）对 role_eq 仍 fail-closed。
    """
    provider = _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "p2-t6"
    scene = await _seed_p2_routing_scene(engine, tid, suffix="-t6")

    emb = (await provider.embed(["CNC-01 设备"]))[0]
    hits = await search.knowledge_search(
        engine,
        tid,
        "CNC-01",
        embedding=emb,
        role_id=scene["role_eq"],
        top_k=5,
        data_domain_ids=["finance_data"],
        embedding_dim=DIM,
    )
    assert hits, "must return hits"
    assert any(h["source"] == "profile" for h in hits), "实体层应脱离路由候选生效"

    # 跨域实体 fail-closed：role_eq 无 finance 权限 → 财务系统不可出现在实体层
    emb2 = (await provider.embed(["财务系统"]))[0]
    hits2 = await search.knowledge_search(
        engine,
        tid,
        "财务系统",
        embedding=emb2,
        role_id=scene["role_eq"],
        top_k=5,
        embedding_dim=DIM,
    )
    assert not any(h["source"] in ("profile", "graph") for h in hits2), "跨域实体应被角色域过滤"
