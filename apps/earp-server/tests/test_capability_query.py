"""Phase D — capability 执行器 / resolve_with_query / 角色层测试（Task 6）。

覆盖：resolve_with_query（§6.5 matched_entity_ids）/ execute_capability_query
（COUNT + 关系计数 + 权限）/ 角色层（§8.2 主/佐 + §9.2 冲突消解）。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.ontology import abox_service, tbox_service
from earp_server.ontology.capability_query import execute_capability_query
from earp_server.ontology.planning import EvidenceChannel, apply_role_layer
from earp_server.ontology.search import resolve_with_query
from earp_server.ontology.understanding import (
    EntityMention,
    Intent,
    Operation,
    RelationMention,
    StructuredQuery,
)


async def _seed(engine: AsyncEngine, tid: str, suffix: str = "") -> dict:
    """角色（equipment_data 权限）+ 实体图 + facts + capability map。"""
    await tbox_service.init_tenant_tbox(engine, tid)
    role_all = f"r-cap{suffix}"
    cap_id = f"cap-cap{suffix}"
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) "
                "VALUES ('equipment_data', :tid, '设备数据', '设备报警', 'internal', 'active') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'cap-all', '{}', 'all', "
                '\'[{"data_domain_id": "equipment_data"}]\') ON CONFLICT DO NOTHING'
            ),
            {"rid": role_all, "tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                f"VALUES ('{cap_id}', :tid, 'equipment', 'query_equipment_alarm', 'query', "
                "'{}', '{}', '{{alarm:read}}', '1.0.0') ON CONFLICT (capability_id, tenant_id) DO NOTHING"
            ),
            {"tid": tid},
        )
    await tbox_service.map_capability_entity(engine, tid, cap_id, "equipment", "read")

    equip = await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
    )
    alarm = await abox_service.upsert_entity(engine, tid, "alarm", "高温报警", data_domain_id="equipment_data")
    await abox_service.add_fact(engine, tid, alarm["entity_id"], "caused_by", equip["entity_id"])
    # 无权限实体（other_data 域）——权限过滤验证
    await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-X1", business_code="CNC-X1", data_domain_id="other_data"
    )
    return {"equip": equip["entity_id"], "alarm": alarm["entity_id"], "role": role_all, "cap": cap_id}


# ── resolve_with_query（§6.5）────────────────────────────────────────────────


async def test_resolve_with_query_matched_entity_ids(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "cap-t1"
    scene = await _seed(engine, tid, suffix="-t1")

    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.9,
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    cands = await resolve_with_query(engine, tid, q)
    assert cands
    assert cands[0]["entity_type_id"] == "equipment"
    assert scene["equip"] in cands[0]["matched_entity_ids"]


async def test_resolve_with_query_empty_entities(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "cap-t2"
    await _seed(engine, tid, suffix="-t2")

    q = StructuredQuery(intent=Intent.AGGREGATION, confidence=0.9, entities=[])
    assert await resolve_with_query(engine, tid, q) == []


# ── execute_capability_query（D1b 执行器）────────────────────────────────────


async def test_execute_count_entities_with_permission(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "cap-t3"
    scene = await _seed(engine, tid, suffix="-t3")

    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.9,
        operation=Operation(aggregate="COUNT"),
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    out = await execute_capability_query(engine, tid, {"capability_id": scene["cap"]}, q, role_id=scene["role"])
    assert out is not None
    assert out["aggregate"]["count"] == 1  # equipment 域内 equipment 实体仅 CNC-01（CNC-X1 在 other_data）
    assert not out.get("permission_denied")


async def test_execute_admin_role_bypasses_domain_filter(migrated: str, app_url: str) -> None:
    """tech-debt #9：is_admin 角色全权限——other_data 实体也计入（不过滤）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "cap-t3b"
    scene = await _seed(engine, tid, suffix="-t3b")
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text("UPDATE roles SET is_admin = TRUE WHERE role_id = :rid AND tenant_id = :tid"),
            {"rid": scene["role"], "tid": tid},
        )
        await conn.commit()

    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.9,
        operation=Operation(aggregate="COUNT"),
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    out = await execute_capability_query(engine, tid, {"capability_id": scene["cap"]}, q, role_id=scene["role"])
    assert out is not None
    assert out["aggregate"]["count"] == 2  # admin 全权限：CNC-01 + CNC-X1 都计入


async def test_execute_relation_count(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "cap-t4"
    scene = await _seed(engine, tid, suffix="-t4")

    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.9,
        operation=Operation(aggregate="COUNT"),
        entities=[EntityMention(mention="高温报警", semantic_type="alarm")],
        relations=[RelationMention(subject="高温报警", relation="caused_by")],
    )
    out = await execute_capability_query(engine, tid, {"capability_id": scene["cap"]}, q, role_id=scene["role"])
    assert out is not None
    assert out["aggregate"]["count"] == 1  # facts: 高温报警 caused_by CNC-01


async def test_execute_no_permission_fail_closed(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "cap-t5"
    scene = await _seed(engine, tid, suffix="-t5")

    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'no-dd', '{}', 'all', '[]') ON CONFLICT DO NOTHING"
            ),
            {"rid": f"r-nodd{tid}", "tid": tid},
        )

    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.9,
        operation=Operation(aggregate="COUNT"),
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    out = await execute_capability_query(engine, tid, {"capability_id": scene["cap"]}, q, role_id=f"r-nodd{tid}")
    assert out is not None
    assert out["aggregate"]["count"] == 0
    assert out.get("permission_denied") is True


async def test_execute_group_by(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "cap-t6"
    scene = await _seed(engine, tid, suffix="-t6")
    # 再插一个 equipment 实体（equipment_data 域）→ group_by 应显示 2
    await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-02", business_code="CNC-02", data_domain_id="equipment_data"
    )

    q = StructuredQuery(
        intent=Intent.AGGREGATION,
        confidence=0.9,
        operation=Operation(aggregate="COUNT", group_by=["entity_type_id"]),
        entities=[EntityMention(mention="CNC-01", semantic_type="equipment")],
    )
    out = await execute_capability_query(engine, tid, {"capability_id": scene["cap"]}, q, role_id=scene["role"])
    assert out is not None
    assert out["aggregate"]["count"] == 2
    assert out["aggregate"]["by"][0]["by_key"] == "equipment"
    assert out["aggregate"]["by"][0]["n"] == 2


# ── 角色层（§8.2/§9.2，纯函数）──────────────────────────────────────────────


def test_role_layer_fact_chunk_primary() -> None:
    from earp_server.ontology.planning import _mk_evidence

    evs = [
        _mk_evidence(EvidenceChannel.CHUNK, content="c", source="doc", source_ref="d1", confidence=0.8),
        _mk_evidence(EvidenceChannel.GRAPH, content="g", source="e", source_ref="f1", confidence=0.9),
        _mk_evidence(EvidenceChannel.PROFILE, content="p", source="e", source_ref="e1", confidence=1.0),
    ]
    out = apply_role_layer(evs, Intent.FACT)
    assert out[0].channel == EvidenceChannel.CHUNK  # primary 在前
    assert out[0].role == "primary"
    assert all(e.role == "auxiliary" for e in out[1:])


def test_role_layer_relation_graph_primary() -> None:
    from earp_server.ontology.planning import _mk_evidence

    evs = [
        _mk_evidence(EvidenceChannel.CHUNK, content="c", source="doc", source_ref="d1", confidence=0.8),
        _mk_evidence(EvidenceChannel.GRAPH, content="g", source="e", source_ref="f1", confidence=0.7),
    ]
    out = apply_role_layer(evs, Intent.RELATION)
    assert out[0].channel == EvidenceChannel.GRAPH
    assert out[0].role == "primary"
    assert out[1].role == "auxiliary"


def test_role_layer_conflict_resolution() -> None:
    """§9.2：同 (channel, source_ref) 冲突 → confidence 高者保留，低者 conflict=true。"""
    from earp_server.ontology.planning import _mk_evidence

    evs = [
        _mk_evidence(EvidenceChannel.GRAPH, content="旧事实", source="e", source_ref="fact-1", confidence=0.5),
        _mk_evidence(EvidenceChannel.GRAPH, content="新事实", source="e", source_ref="fact-1", confidence=0.9),
    ]
    out = apply_role_layer(evs, Intent.RELATION)
    assert any(e.conflict for e in out)
    primary = [e for e in out if not e.conflict][0]
    assert primary.content == "新事实"
