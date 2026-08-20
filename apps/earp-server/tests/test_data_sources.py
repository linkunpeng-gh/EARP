"""M3 B1 — 数据源注册（import/connector + data-sources）：校验/幂等/virtual 边界/admin 门禁。

校验（任务书 B1）：connector 存在且 active；entity_type 存在；virtual → kind=metric（G1）；
field_mapping 必含 business_code_field + name_field；同 (connector, entity_type, source_mode) 重复 → 409。
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.main import create_app
from earp_server.ontology import connector_service, import_service

SECRET = "earp-dev-secret-change-in-production"

_DS_COLS = "data_source_id, tenant_id, connector_id, entity_type_id, source_mode, field_mapping"


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    # connector_id 单列主键（debt #7 模式）：固定语义 id 跨测试租户冲突 → migration 角色全局 purge
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        # data_source_id 随机生成（ds-xxx）——按 connector_id 前缀清引用
        await conn.execute(
            text("DELETE FROM import_rules WHERE connector_id LIKE 'cn-t%' OR connector_id = 'cn-api'")
        )
        await conn.execute(text("DELETE FROM connector_configs WHERE connector_id LIKE 'cn-t%'"))
        await conn.execute(text("DELETE FROM roles WHERE role_id IN ('r-admin','r-ops')"))
    await eng.dispose()
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) VALUES "
                "('dd-a', :t, '域A', 'x', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-admin', :t, 'Admin', '{}', 'all', '[]', TRUE), "
                "('r-ops', :t, '普通角色', '{}', 'all', '[{\"data_domain_id\": \"dd-a\"}]', FALSE) "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, "
                "data_domain_id, attributes) VALUES "
                "('equipment', :t, '设备', 'object', 'dd-a', '{}'), "
                "('oee', :t, '设备OEE', 'metric', 'dd-a', '{}') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()


async def _make_connector(engine: AsyncEngine, tid: str, cid: str) -> None:
    await connector_service.create_connector(
        engine, tid, connector_id=cid, adapter_type="rest", config={"base_url": "http://mid/api"}
    )


def _fm() -> dict:
    return {"name_field": "equip_name", "business_code_field": "equip_code", "attr_fields": {}}


# ── service 层 ────────────────────────────────────────────────────────────────
async def test_register_synced_data_source(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "ds-t1"
        await _seed(engine, migration_url, tid)
        await _make_connector(engine, tid, "cn-t1")
        out = await import_service.register_data_source(
            engine, tid, connector_id="cn-t1", entity_type_id="equipment",
            source_mode="synced", field_mapping=_fm(),
        )
        assert out is not None
        assert out["source_mode"] == "synced"
        assert out["entity_type_id"] == "equipment"
        assert out["field_mapping"]["business_code_field"] == "equip_code"
        got = await import_service.get_data_source(engine, tid, out["data_source_id"])
        assert got is not None
        assert got["last_sync_status"] is None
    finally:
        await engine.dispose()


async def test_register_virtual_requires_metric(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "ds-t2"
        await _seed(engine, migration_url, tid)
        await _make_connector(engine, tid, "cn-t2")
        try:
            await import_service.register_data_source(
                engine, tid, connector_id="cn-t2", entity_type_id="equipment",
                source_mode="virtual", field_mapping=_fm(),
            )
            raise AssertionError("object 类型 virtual 应被拒绝（G1）")
        except ValueError as e:
            assert "metric" in str(e)
    finally:
        await engine.dispose()


async def test_register_virtual_metric_ok(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "ds-t3"
        await _seed(engine, migration_url, tid)
        await _make_connector(engine, tid, "cn-t3")
        out = await import_service.register_data_source(
            engine, tid, connector_id="cn-t3", entity_type_id="oee",
            source_mode="virtual", field_mapping=_fm(),
        )
        assert out is not None and out["source_mode"] == "virtual"
    finally:
        await engine.dispose()


async def test_register_missing_connector(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "ds-t4"
        await _seed(engine, migration_url, tid)
        try:
            await import_service.register_data_source(
                engine, tid, connector_id="cn-nope", entity_type_id="equipment",
                source_mode="synced", field_mapping=_fm(),
            )
            raise AssertionError("connector 不存在应报错")
        except ValueError as e:
            assert "connector" in str(e)
    finally:
        await engine.dispose()


async def test_register_missing_field_mapping(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "ds-t5"
        await _seed(engine, migration_url, tid)
        await _make_connector(engine, tid, "cn-t5")
        try:
            await import_service.register_data_source(
                engine, tid, connector_id="cn-t5", entity_type_id="equipment",
                source_mode="synced", field_mapping={"name_field": "x"},
            )
            raise AssertionError("缺 business_code_field 应报错")
        except ValueError as e:
            assert "business_code_field" in str(e)
    finally:
        await engine.dispose()


async def test_register_duplicate_returns_none(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "ds-t6"
        await _seed(engine, migration_url, tid)
        await _make_connector(engine, tid, "cn-t6")
        await import_service.register_data_source(
            engine, tid, connector_id="cn-t6", entity_type_id="equipment",
            source_mode="synced", field_mapping=_fm(),
        )
        dup = await import_service.register_data_source(
            engine, tid, connector_id="cn-t6", entity_type_id="equipment",
            source_mode="synced", field_mapping=_fm(),
        )
        assert dup is None
    finally:
        await engine.dispose()


async def test_list_data_sources(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "ds-t7"
        await _seed(engine, migration_url, tid)
        await _make_connector(engine, tid, "cn-t7")
        await import_service.register_data_source(
            engine, tid, connector_id="cn-t7", entity_type_id="equipment",
            source_mode="synced", field_mapping=_fm(),
        )
        await import_service.register_data_source(
            engine, tid, connector_id="cn-t7", entity_type_id="oee",
            source_mode="virtual", field_mapping=_fm(),
        )
        rows = await import_service.list_data_sources(engine, tid)
        assert len(rows) == 2
    finally:
        await engine.dispose()


# ── API 层 ────────────────────────────────────────────────────────────────────
def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def _token(tid: str, role_id: str) -> str:
    return jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def test_data_source_api_admin_gate(migrated: str, app_url: str, migration_url: str) -> None:
    """注册写端点仅 admin；只读列表开放；virtual object 400；重复 409。"""
    tid = "ds-api"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))
    asyncio.run(_make_connector(engine, tid, "cn-api"))

    app = _make_app(app_url)
    body = {
        "connector_id": "cn-api",
        "entity_type_id": "equipment",
        "source_mode": "synced",
        "field_mapping": _fm(),
    }
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid, 'r-ops')}"}
        assert c.get("/v1/ontology/data-sources", headers=h).status_code == 200  # 只读开放
        assert c.post("/v1/ontology/import/connector", json=body, headers=h).status_code == 403
        h_a = {"Authorization": f"Bearer {_token(tid, 'r-admin')}"}
        r = c.post("/v1/ontology/import/connector", json=body, headers=h_a)
        assert r.status_code == 201, r.text
        ds_id = r.json()["data_source_id"]
        # 重复 409
        assert c.post("/v1/ontology/import/connector", json=body, headers=h_a).status_code == 409
        # virtual + object 400（G1）
        bad = {**body, "source_mode": "virtual", "entity_type_id": "equipment"}
        assert c.post("/v1/ontology/import/connector", json=bad, headers=h_a).status_code == 400
        # connector 不存在 400
        bad2 = {**body, "connector_id": "cn-nope"}
        assert c.post("/v1/ontology/import/connector", json=bad2, headers=h_a).status_code == 400
        # GET 详情
        assert c.get(f"/v1/ontology/data-sources/{ds_id}", headers=h_a).status_code == 200
        assert c.get("/v1/ontology/data-sources/ds-nope", headers=h_a).status_code == 404
    asyncio.run(engine.dispose())
