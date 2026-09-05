"""PRD-2026-030 M1 — ontology TBox/ABox CRUD + lookup + graph + profile."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.ontology import abox_service, tbox_service


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def test_init_tenant_tbox_seeds(app_engine: AsyncEngine) -> None:
    await tbox_service.init_tenant_tbox(app_engine, "ont-t1")

    types = await tbox_service.list_entity_types(app_engine, "ont-t1")
    assert len(types) == 13
    ids = {t["entity_type_id"] for t in types}
    assert {"equipment", "component", "supplier", "work_order"} <= ids

    rels = await tbox_service.list_relation_types(app_engine, "ont-t1")
    assert len(rels) == 12
    rel_ids = {r["relation_type_id"] for r in rels}
    assert {"located_in", "manufactured_by", "caused_by"} <= rel_ids

    # idempotent re-seed
    await tbox_service.init_tenant_tbox(app_engine, "ont-t1")
    assert len(await tbox_service.list_entity_types(app_engine, "ont-t1")) == 13

    # RLS: other tenant sees nothing
    assert await tbox_service.list_entity_types(app_engine, "ont-other") == []


async def test_create_deprecate_entity_type(app_engine: AsyncEngine) -> None:
    created = await tbox_service.create_entity_type(
        app_engine, "ont-t1", "custom_asset", "自定义资产", kind="object", data_domain_id="equipment_data"
    )
    assert created["entity_type_id"] == "custom_asset"

    deprecated = await tbox_service.deprecate_entity_type(app_engine, "ont-t1", "custom_asset")
    assert deprecated is not None and deprecated["status"] == "deprecated"
    # active list excludes it
    assert all(
        t["entity_type_id"] != "custom_asset" for t in await tbox_service.list_entity_types(app_engine, "ont-t1")
    )


async def test_upsert_entity_idempotent_and_lookup(app_engine: AsyncEngine) -> None:
    await tbox_service.init_tenant_tbox(app_engine, "ont-t1")

    e1 = await abox_service.upsert_entity(
        app_engine, "ont-t1", "equipment", "CNC-01", business_code="CNC-01", attributes={"model": "M80"}
    )
    assert e1["merged"] is False

    e2 = await abox_service.upsert_entity(
        app_engine, "ont-t1", "equipment", "CNC-01 (updated)", business_code="CNC-01", attributes={"model": "M80+"}
    )
    assert e2["merged"] is True
    assert e2["entity_id"] == e1["entity_id"]

    # lookup by name / business_code prefix
    hits = await abox_service.lookup_entities(app_engine, "ont-t1", "CNC")
    assert len(hits) == 1
    assert hits[0]["business_code"] == "CNC-01"
    assert hits[0]["attributes"] == {"model": "M80+"}


async def test_facts_graph_and_profile(app_engine: AsyncEngine) -> None:
    await tbox_service.init_tenant_tbox(app_engine, "ont-t1")
    sup = await abox_service.upsert_entity(app_engine, "ont-t1", "supplier", "上海某精机", business_code="SUP-1")
    equip = await abox_service.upsert_entity(app_engine, "ont-t1", "equipment", "CNC-01", business_code="CNC-01")
    comp = await abox_service.upsert_entity(app_engine, "ont-t1", "component", "主轴轴承", business_code="CPN-1")
    alarm = await abox_service.upsert_entity(app_engine, "ont-t1", "alarm", "高温报警")

    await abox_service.add_fact(app_engine, "ont-t1", equip["entity_id"], "manufactured_by", sup["entity_id"])
    f2 = await abox_service.add_fact(app_engine, "ont-t1", comp["entity_id"], "belongs_to", equip["entity_id"])
    await abox_service.add_fact(app_engine, "ont-t1", alarm["entity_id"], "caused_by", comp["entity_id"])

    # graph traversal: alarm → component → equipment → supplier (3 hops)
    hops = await abox_service.graph_query(app_engine, "ont-t1", alarm["entity_id"], max_hops=3)
    target_names = {h["target_name"] for h in hops}
    assert {"主轴轴承", "CNC-01", "上海某精机"} <= target_names

    # revoke a fact → excluded from graph
    await abox_service.revoke_fact(app_engine, "ont-t1", f2["fact_id"])
    hops2 = await abox_service.graph_query(app_engine, "ont-t1", alarm["entity_id"], max_hops=3)
    assert "CNC-01" not in {h["target_name"] for h in hops2}

    # cycle protection: self-referencing fact does not loop forever
    await abox_service.add_fact(app_engine, "ont-t1", sup["entity_id"], "located_in", sup["entity_id"])
    hops3 = await abox_service.graph_query(app_engine, "ont-t1", sup["entity_id"], max_hops=5)
    assert len(hops3) <= 5

    # Compiled Truth profile
    profile = await abox_service.compile_profile(app_engine, "ont-t1", equip["entity_id"])
    assert profile is not None
    assert profile["profile"]["name"] == "CNC-01"
    assert profile["profile"]["stats"]["fact_count"] >= 1

    cached = await abox_service.get_entity_profile(app_engine, "ont-t1", equip["entity_id"])
    assert cached is not None and cached["profile_version"] >= 1


async def test_capability_entity_map_reverse_lookup(app_engine: AsyncEngine) -> None:
    await tbox_service.init_tenant_tbox(app_engine, "ont-t1")

    async with tenant_session(app_engine, "ont-t1") as session:
        await session.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                "VALUES ('cap-query-alarms', 'ont-t1', 'equipment', 'query_alarms', 'query', "
                "'{}', '{}', '{alarm:read}', '1.0.0') ON CONFLICT (capability_id, tenant_id) DO NOTHING"
            )
        )

    await tbox_service.map_capability_entity(app_engine, "ont-t1", "cap-query-alarms", "equipment", "read")
    await tbox_service.map_capability_entity(app_engine, "ont-t1", "cap-query-alarms", "alarm", "read")

    caps = await tbox_service.find_capabilities_by_entity_type(app_engine, "ont-t1", "equipment")
    assert any(c["capability_id"] == "cap-query-alarms" for c in caps)


async def test_graph_query_backward(app_engine: AsyncEngine) -> None:
    """反向遍历（QU §12 例 4 Phase D2 缺口闭合）：工厂 ← located_in ← 设备。

    forward 视角工厂无出边（located_in 方向 equipment→plant）；backward 应
    找到位于该厂的全部设备。
    """
    await tbox_service.init_tenant_tbox(app_engine, "ont-t2")
    plant = await abox_service.upsert_entity(app_engine, "ont-t2", "plant", "华东一厂", business_code="PL-1")
    e1 = await abox_service.upsert_entity(app_engine, "ont-t2", "equipment", "CNC-01", business_code="CNC-01")
    e2 = await abox_service.upsert_entity(app_engine, "ont-t2", "equipment", "CNC-02", business_code="CNC-02")
    await abox_service.add_fact(app_engine, "ont-t2", e1["entity_id"], "located_in", plant["entity_id"])
    await abox_service.add_fact(app_engine, "ont-t2", e2["entity_id"], "located_in", plant["entity_id"])

    # forward（默认）：工厂无出边 → 空
    fwd = await abox_service.graph_query(app_engine, "ont-t2", plant["entity_id"], max_hops=1)
    assert fwd == []

    # backward：华东一厂 → 位于该厂的设备
    bw = await abox_service.graph_query(app_engine, "ont-t2", plant["entity_id"], max_hops=1, direction="backward")
    names = {h["target_name"] for h in bw}
    assert {"CNC-01", "CNC-02"} == names
    assert all(h["relation_type_id"] == "located_in" for h in bw)
    # 邻居实体以 target_* 呈现（消费方无需感知方向）
    assert all(h["target_type"] == "equipment" for h in bw)


async def test_list_deprecate_and_fact_id(app_engine: AsyncEngine) -> None:
    """M4 admin：实体分页列表 + 过滤 + 软停用；graph 返回 fact_id 供撤销。"""
    await tbox_service.init_tenant_tbox(app_engine, "ont-t3")
    e1 = await abox_service.upsert_entity(app_engine, "ont-t3", "equipment", "CNC-01", business_code="CNC-01")
    e2 = await abox_service.upsert_entity(app_engine, "ont-t3", "equipment", "CNC-02", business_code="CNC-02")
    sup = await abox_service.upsert_entity(app_engine, "ont-t3", "supplier", "上海某精机", business_code="SUP-1")
    await abox_service.add_fact(app_engine, "ont-t3", e1["entity_id"], "manufactured_by", sup["entity_id"])

    # 分页列表（过滤 equipment）
    rows, total = await abox_service.list_entities(app_engine, "ont-t3", entity_type_ids=["equipment"], page_size=10)
    assert total == 2 and len(rows) == 2
    rows2, total2 = await abox_service.list_entities(app_engine, "ont-t3", page_size=1, page=1)
    assert len(rows2) == 1 and total2 == 3  # 分页截断但 total 全量

    # 软停用：不再出现在 active 列表
    await abox_service.deprecate_entity(app_engine, "ont-t3", e2["entity_id"])
    rows3, total3 = await abox_service.list_entities(app_engine, "ont-t3", page_size=10)
    assert total3 == 2  # CNC-01 + supplier（CNC-02 已停用）
    dep = await abox_service.deprecate_entity(app_engine, "ont-t3", e2["entity_id"])
    assert dep is None  # 已停用 → 幂等返回 None

    # graph 返回 fact_id（供前端撤销）
    hops = await abox_service.graph_query(app_engine, "ont-t3", e1["entity_id"], max_hops=1)
    assert hops and all(h.get("fact_id") for h in hops)
    fid = hops[0]["fact_id"]
    revoked = await abox_service.revoke_fact(app_engine, "ont-t3", fid)
    assert revoked["status"] == "revoked"


async def test_list_entities_keyword_search(app_engine: AsyncEngine) -> None:
    """M4：list_entities 支持 q 关键字搜索（名称/业务编码 ILIKE）。"""
    await tbox_service.init_tenant_tbox(app_engine, "ont-t4")
    await abox_service.upsert_entity(app_engine, "ont-t4", "equipment", "CNC-01", business_code="CNC-01")
    await abox_service.upsert_entity(app_engine, "ont-t4", "equipment", "CNC-02", business_code="CNC-02")
    await abox_service.upsert_entity(app_engine, "ont-t4", "supplier", "上海某精机", business_code="SUP-1")

    rows, total = await abox_service.list_entities(app_engine, "ont-t4", q="CNC", page_size=10)
    assert total == 2
    rows2, total2 = await abox_service.list_entities(app_engine, "ont-t4", q="精机", page_size=10)
    assert total2 == 1 and rows2[0]["name"] == "上海某精机"


async def test_lookup_entities_reverse_substring(app_engine: AsyncEngine) -> None:
    """实体名是查询子串 → 命中（2026-08-16 修复「纯中文实体长查询不命中」）。

    「主变压器是哪个公司生产的」→ 命中实体「主变压器」；原方向（实体名包含
    查询串）不回归。
    """
    await tbox_service.init_tenant_tbox(app_engine, "ont-t5")
    await abox_service.upsert_entity(app_engine, "ont-t5", "equipment", "主变压器", business_code="TX-01")

    # 反向：查询包含实体名
    hits = await abox_service.lookup_entities(app_engine, "ont-t5", "主变压器是哪个公司生产的")
    assert any(h["name"] == "主变压器" for h in hits)
    # 正向（原有）：实体名包含查询串
    hits2 = await abox_service.lookup_entities(app_engine, "ont-t5", "主变压")
    assert any(h["name"] == "主变压器" for h in hits2)
    # 无关查询不误命中
    hits3 = await abox_service.lookup_entities(app_engine, "ont-t5", "报销标准")
    assert hits3 == []


async def test_deprecate_relation_type(app_engine: AsyncEngine) -> None:
    """M4 补充：关系类型软停用（对称 deprecate_entity_type）。"""
    await tbox_service.init_tenant_tbox(app_engine, "ont-t6")
    await tbox_service.create_relation_type(
        app_engine, "ont-t6", "connected_to", "连接至", "equipment", "equipment", "N:M"
    )
    rel = await tbox_service.deprecate_relation_type(app_engine, "ont-t6", "connected_to")
    assert rel is not None and rel["status"] == "deprecated"
    # 幂等：已停用 → 返回 None
    assert await tbox_service.deprecate_relation_type(app_engine, "ont-t6", "connected_to") is None
    # active 列表不再含它
    active = await tbox_service.list_relation_types(app_engine, "ont-t6")
    assert all(r["relation_type_id"] != "connected_to" for r in active)


async def test_tbox_create_duplicate_and_deprecate_idempotent(app_engine: AsyncEngine) -> None:
    """TBox 停用修复（2026-08-16）：
    ① create 重复 → ValueError（409），已停用不再允许重新启用；
    ② deprecate 幂等（已停用再停用返回 None）。
    """
    await tbox_service.init_tenant_tbox(app_engine, "ont-t7")
    # create 已存在（seed 的 equipment）→ 拒绝
    import pytest

    with pytest.raises(ValueError, match="已存在"):
        await tbox_service.create_entity_type(app_engine, "ont-t7", "equipment", "设备")
    # 新建 → 停用 → 再 create 同名 → 拒绝（不再允许重新启用）
    await tbox_service.create_entity_type(app_engine, "ont-t7", "inverter", "逆变器", data_domain_id="equipment_data")
    assert await tbox_service.deprecate_entity_type(app_engine, "ont-t7", "inverter") is not None
    assert await tbox_service.deprecate_entity_type(app_engine, "ont-t7", "inverter") is None  # 幂等
    with pytest.raises(ValueError, match="已停用"):
        await tbox_service.create_entity_type(app_engine, "ont-t7", "inverter", "逆变器2")
    # 关系类型同语义
    with pytest.raises(ValueError, match="已存在"):
        await tbox_service.create_relation_type(
            app_engine, "ont-t7", "manufactured_by", "制造", "equipment", "supplier", "N:1"
        )


async def test_list_entities_status_all(app_engine: AsyncEngine) -> None:
    """list_entities status='all' 含 deprecated（配合「显示已停用」）。"""
    await tbox_service.init_tenant_tbox(app_engine, "ont-t8")
    e1 = await abox_service.upsert_entity(app_engine, "ont-t8", "equipment", "CNC-D1", business_code="CNC-D1")
    await abox_service.deprecate_entity(app_engine, "ont-t8", e1["entity_id"])
    _, total_all = await abox_service.list_entities(app_engine, "ont-t8", status="all", page_size=50)
    rows_all, _ = await abox_service.list_entities(app_engine, "ont-t8", status="all", page_size=50)
    assert any(r["status"] == "deprecated" for r in rows_all)
    _, total_active = await abox_service.list_entities(app_engine, "ont-t8", status="active")
    assert total_all == total_active + 1  # deprecated 只出现在 all


async def test_get_entity_deprecated_viewable(app_engine: AsyncEngine) -> None:
    """停用实体详情可查看（管理追溯）：get_entity 返回 deprecated；profile 可重编。"""
    await tbox_service.init_tenant_tbox(app_engine, "ont-t9")
    e1 = await abox_service.upsert_entity(app_engine, "ont-t9", "equipment", "CNC-D2", business_code="CNC-D2")
    await abox_service.deprecate_entity(app_engine, "ont-t9", e1["entity_id"])
    ent = await abox_service.get_entity(app_engine, "ont-t9", e1["entity_id"])
    assert ent is not None and ent["status"] == "deprecated"
    # profile 可编译（不因 deprecated 返回 None）
    prof = await abox_service.compile_profile(app_engine, "ont-t9", e1["entity_id"])
    assert prof is not None
    # 检索路径仍排除 deprecated（lookup_entities）
    hits = await abox_service.lookup_entities(app_engine, "ont-t9", "CNC-D2")
    assert hits == []


async def test_upsert_entity_domain_follows_type(app_engine: AsyncEngine) -> None:
    """2026-09（设计 2026-09-04 §4.4）：实例数据域以所属类型为唯一事实——
    省略自动取类型域；显式一致放行；显式不一致拒绝；merge-update 顺带纠正历史不一致。"""
    await tbox_service.init_tenant_tbox(app_engine, "ont-t10")

    # 省略 → 自动取类型域（equipment → equipment_data）
    e1 = await abox_service.upsert_entity(app_engine, "ont-t10", "equipment", "CNC-01", business_code="CNC-01")
    assert (await abox_service.get_entity(app_engine, "ont-t10", e1["entity_id"]))["data_domain_id"] == "equipment_data"

    # 显式传一致 → 放行
    e2 = await abox_service.upsert_entity(
        app_engine, "ont-t10", "equipment", "CNC-02", business_code="CNC-02", data_domain_id="equipment_data"
    )
    assert (await abox_service.get_entity(app_engine, "ont-t10", e2["entity_id"]))["data_domain_id"] == "equipment_data"

    # 显式不一致 → fail-fast 拒绝（不静默覆盖）
    with pytest.raises(ValueError, match="不一致"):
        await abox_service.upsert_entity(
            app_engine, "ont-t10", "equipment", "X", business_code="CNC-03", data_domain_id="finance_data"
        )
    # 类型未配置域 + 显式传值 → 拒绝
    await tbox_service.create_entity_type(app_engine, "ont-t10", "plain_type", "无域类型")
    with pytest.raises(ValueError, match="不一致"):
        await abox_service.upsert_entity(
            app_engine, "ont-t10", "plain_type", "P1", business_code="P1", data_domain_id="equipment_data"
        )

    # merge-update 路径：历史不一致（手工置错域）在下一次 upsert 时纠正为类型域
    async with tenant_session(app_engine, "ont-t10") as s:
        await s.execute(
            text("UPDATE entities SET data_domain_id = 'finance_data' WHERE entity_id = :e"), {"e": e1["entity_id"]}
        )
    assert (await abox_service.get_entity(app_engine, "ont-t10", e1["entity_id"]))["data_domain_id"] == "finance_data"
    await abox_service.upsert_entity(app_engine, "ont-t10", "equipment", "CNC-01 更名", business_code="CNC-01")
    assert (await abox_service.get_entity(app_engine, "ont-t10", e1["entity_id"]))["data_domain_id"] == "equipment_data"
