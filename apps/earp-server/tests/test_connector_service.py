"""M3 A1 — connector_configs 管理：CRUD + 加密脱敏 + 引用保护 + admin 门禁 + RLS。

背景（M3 任务书 A1）：connector_configs（0001 建表）零代码引用，M3 补最小
CRUD 作为数据源注册的前置设施；配置 AES-256-GCM 加密落库（config_payload），
列表/详情脱敏；被 import_rules 引用时不可删（防悬空数据源）。
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.main import create_app
from earp_server.ontology import connector_service

SECRET = "earp-dev-secret-change-in-production"


def _engine(app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    # connector_id 单列主键（debt #7 模式）：固定语义 id 跨测试租户冲突 → migration 角色全局 purge
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM import_rules WHERE data_source_id LIKE 'ds-t%'"))
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
                "('equipment', :t, '设备', 'object', 'dd-a', '{}') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()


async def _add_import_rule(engine: AsyncEngine, tid: str, cid: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO import_rules (data_source_id, tenant_id, connector_id, "
                "entity_type_id, source_mode, field_mapping) VALUES "
                "('ds-t1', :t, :cid, 'equipment', 'synced', '{}')"
            ),
            {"t": tid, "cid": cid},
        )
        await conn.commit()


# ── service 层 ────────────────────────────────────────────────────────────────
async def test_create_and_get_connector_masked(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t1"
        out = await connector_service.create_connector(
            engine, tid, connector_id="cn-t1", adapter_type="rest",
            config={"base_url": "http://mid-platform/api", "token": "secret-abc"},
        )
        assert out is not None
        assert out["connector_id"] == "cn-t1"
        assert out["config"] == {"credential_masked": True}  # 脱敏：不含明文
        got = await connector_service.get_connector(engine, tid, "cn-t1")
        assert got is not None
        assert got["adapter_type"] == "rest"
        assert "secret-abc" not in str(got)
        assert "mid-platform" not in str(got)  # URL 也不泄露
    finally:
        await engine.dispose()


async def test_connector_duplicate_returns_none(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t2"
        await connector_service.create_connector(
            engine, tid, connector_id="cn-t2", adapter_type="rest", config={}
        )
        dup = await connector_service.create_connector(
            engine, tid, connector_id="cn-t2", adapter_type="db", config={}
        )
        assert dup is None
    finally:
        await engine.dispose()


async def test_adapter_type_validation(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t3"
        try:
            await connector_service.create_connector(engine, tid, adapter_type="ftp", config={})
            raise AssertionError("ftp should be rejected")
        except ValueError as e:
            assert "adapter_type" in str(e)
    finally:
        await engine.dispose()


async def test_list_connectors_masked(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t4"
        await connector_service.create_connector(
            engine, tid, adapter_type="rest", config={"base_url": "http://a"}
        )
        await connector_service.create_connector(
            engine, tid, adapter_type="db", config={"conn_url": "postgresql://x"}
        )
        rows = await connector_service.list_connectors(engine, tid)
        assert len(rows) == 2
        assert all(r["config"] == {"credential_masked": True} for r in rows)
    finally:
        await engine.dispose()


async def test_update_connector_reencrypt(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t5"
        await connector_service.create_connector(
            engine, tid, connector_id="cn-t5", adapter_type="rest",
            config={"base_url": "http://old"},
        )
        upd = await connector_service.update_connector(
            engine, tid, "cn-t5", config={"base_url": "http://new", "token": "t2"}
        )
        assert upd is not None
        assert upd["config"] == {"credential_masked": True}
        cfg = await connector_service.decrypt_config(engine, tid, "cn-t5")
        assert cfg["base_url"] == "http://new"
        assert cfg["token"] == "t2"
    finally:
        await engine.dispose()


async def test_decrypt_config_roundtrip_and_missing(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t6"
        await connector_service.create_connector(
            engine, tid, connector_id="cn-t6", adapter_type="rest",
            config={"username": "u", "password": "p@ss"},
        )
        cfg = await connector_service.decrypt_config(engine, tid, "cn-t6")
        assert cfg == {"username": "u", "password": "p@ss", "adapter_type": "rest"}
        missing = await connector_service.decrypt_config(engine, tid, "cn-nope")
        assert missing == {}
    finally:
        await engine.dispose()


async def test_delete_connector_with_import_rule_ref_blocked(migrated: str, app_url: str, migration_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t7"
        await _seed(engine, migration_url, tid)
        await connector_service.create_connector(
            engine, tid, connector_id="cn-t7", adapter_type="rest", config={}
        )
        await _add_import_rule(engine, tid, "cn-t7")
        ok = await connector_service.delete_connector(engine, tid, "cn-t7")
        assert ok is False  # 被引用 → 拒绝
        assert await connector_service.get_connector(engine, tid, "cn-t7") is not None
    finally:
        await engine.dispose()


async def test_delete_connector_ok(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid = "cn-t8"
        await connector_service.create_connector(
            engine, tid, connector_id="cn-t8", adapter_type="rest", config={}
        )
        ok = await connector_service.delete_connector(engine, tid, "cn-t8")
        assert ok is True
        assert await connector_service.get_connector(engine, tid, "cn-t8") is None
    finally:
        await engine.dispose()


async def test_connector_tenant_isolation(migrated: str, app_url: str) -> None:
    engine = _engine(app_url)
    try:
        tid_a, tid_b = "cn-ta", "cn-tb"
        await connector_service.create_connector(
            engine, tid_a, connector_id="cn-ta", adapter_type="rest", config={}
        )
        assert await connector_service.list_connectors(engine, tid_b) == []  # RLS：跨租户不可见
        assert await connector_service.get_connector(engine, tid_b, "cn-ta") is None
    finally:
        await engine.dispose()


# ── API 层：admin 门禁 ────────────────────────────────────────────────────────
def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def _token(tid: str, role_id: str) -> str:
    return jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def test_connector_api_admin_gate(migrated: str, app_url: str) -> None:
    """connector 写端点仅 admin：非 admin 全 403；只读列表开放；admin 全流程通。"""
    tid = "cn-api"
    engine = _engine(app_url)
    asyncio.run(_seed(engine, migrated, tid))

    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid, 'r-ops')}"}
        assert c.get("/v1/ontology/connectors", headers=h).status_code == 200  # 只读开放
        assert (
            c.post(
                "/v1/ontology/connectors",
                json={"connector_id": "cn-api1", "adapter_type": "rest", "config": {"base_url": "x"}},
                headers=h,
            ).status_code
            == 403
        )
        h_a = {"Authorization": f"Bearer {_token(tid, 'r-admin')}"}
        r = c.post(
            "/v1/ontology/connectors",
            json={"connector_id": "cn-api1", "adapter_type": "rest", "config": {"base_url": "x"}},
            headers=h_a,
        )
        assert r.status_code == 201, r.text
        # 重复 409
        assert (
            c.post(
                "/v1/ontology/connectors",
                json={"connector_id": "cn-api1", "adapter_type": "rest", "config": {}},
                headers=h_a,
            ).status_code
            == 409
        )
        # 非法 adapter_type 400
        assert (
            c.post(
                "/v1/ontology/connectors",
                json={"adapter_type": "ftp", "config": {}},
                headers=h_a,
            ).status_code
            == 400
        )
        # 非 admin PATCH/DELETE 403
        assert c.patch("/v1/ontology/connectors/cn-api1", json={"status": "deprecated"}, headers=h).status_code == 403
        assert c.delete("/v1/ontology/connectors/cn-api1", headers=h).status_code == 403
        # admin PATCH/DELETE 通过
        assert c.patch("/v1/ontology/connectors/cn-api1", json={"status": "deprecated"}, headers=h_a).status_code == 200
        assert c.delete("/v1/ontology/connectors/cn-api1", headers=h_a).status_code == 200
        assert c.delete("/v1/ontology/connectors/cn-api1", headers=h_a).status_code == 404
    asyncio.run(engine.dispose())
