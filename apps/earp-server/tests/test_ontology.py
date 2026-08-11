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
                "'{}', '{}', '{alarm:read}', '1.0.0') ON CONFLICT (capability_id) DO NOTHING"
            )
        )

    await tbox_service.map_capability_entity(app_engine, "ont-t1", "cap-query-alarms", "equipment", "read")
    await tbox_service.map_capability_entity(app_engine, "ont-t1", "cap-query-alarms", "alarm", "read")

    caps = await tbox_service.find_capabilities_by_entity_type(app_engine, "ont-t1", "equipment")
    assert any(c["capability_id"] == "cap-query-alarms" for c in caps)
