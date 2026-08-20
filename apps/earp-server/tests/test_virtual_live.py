"""M3 C1 — virtual metric 实体实时取数（GET /entities/{id}/live）。

G1 边界：仅 source_mode='virtual' 且 kind=metric 放行；object virtual 实体 → 400；
取数失败 → 503（不假造值）；非 virtual → 400。
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.main import create_app
from earp_server.ontology import connector_service, data_adapter

SECRET = "earp-dev-secret-change-in-production"


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM connector_configs WHERE connector_id = 'cn-v1'"))
        await conn.execute(text("DELETE FROM entities WHERE entity_id IN ('ent-v1','ent-v2','ent-v3')"))
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
                "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, "
                "data_domain_id, attributes) VALUES "
                "('equipment', :t, '设备', 'object', 'dd-a', '{}'), "
                "('oee', :t, 'OEE', 'metric', 'dd-a', '{}') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO entities (entity_id, tenant_id, entity_type_id, name, "
                "business_code, source_mode, source_ref, data_domain_id) VALUES "
                "('ent-v1', :t, 'oee', 'CNC-01 OEE', 'CNC-01', 'virtual', 'cn-v1', 'dd-a'), "
                "('ent-v2', :t, 'equipment', 'CNC-02', 'CNC-02', 'virtual', 'cn-v1', 'dd-a'), "
                "('ent-v3', :t, 'equipment', 'CNC-03', 'CNC-03', 'extracted', NULL, 'dd-a') "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()


def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def _token(tid: str, role_id: str = "r-all") -> str:
    return jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def test_live_virtual_metric_ok(migrated: str, app_url: str, migration_url: str, monkeypatch) -> None:
    tid = "cv-t1"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))
    asyncio.run(
        connector_service.create_connector(
            engine, tid, connector_id="cn-v1", adapter_type="rest",
            config={"base_url": "http://mid/api", "token": "t"},
        )
    )

    async def fake_fetch(cfg, params=None):
        assert params == {"business_code": "CNC-01"}  # business_code 透传
        return [{"equip_code": "CNC-01", "oee": 0.87}]

    monkeypatch.setattr(data_adapter, "fetch", fake_fetch)
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid)}"}
        r = c.get("/v1/ontology/entities/ent-v1/live", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["entity_id"] == "ent-v1"
        assert body["data"] == {"equip_code": "CNC-01", "oee": 0.87}
        assert body["connector_id"] == "cn-v1"
        assert body["fetched_at"]
    asyncio.run(engine.dispose())


def test_live_virtual_object_rejected(migrated: str, app_url: str, migration_url: str) -> None:
    """object 类型 virtual 实体 → 400（G1：object virtual 留二期）。"""
    tid = "cv-t2"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid)}"}
        r = c.get("/v1/ontology/entities/ent-v2/live", headers=h)
        assert r.status_code == 400
        assert "metric" in r.json()["detail"]
    asyncio.run(engine.dispose())


def test_live_non_virtual_rejected(migrated: str, app_url: str) -> None:
    tid = "cv-t3"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid)}"}
        r = c.get("/v1/ontology/entities/ent-v3/live", headers=h)
        assert r.status_code == 400
        assert "virtual" in r.json()["detail"]
    asyncio.run(engine.dispose())


def test_live_fetch_failure_503(migrated: str, app_url: str, migration_url: str, monkeypatch) -> None:
    """取数失败 → 503（不假造值）。"""
    tid = "cv-t4"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))
    asyncio.run(
        connector_service.create_connector(
            engine, tid, connector_id="cn-v1", adapter_type="rest",
            config={"base_url": "http://mid/api"},
        )
    )

    async def boom(cfg, params=None):
        raise data_adapter.ConnectorFetchError("超时")

    monkeypatch.setattr(data_adapter, "fetch", boom)
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid)}"}
        r = c.get("/v1/ontology/entities/ent-v1/live", headers=h)
        assert r.status_code == 503
        assert "取数失败" in r.json()["detail"]
    asyncio.run(engine.dispose())


def test_live_entity_not_found(migrated: str, app_url: str) -> None:
    tid = "cv-t5"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid)}"}
        assert c.get("/v1/ontology/entities/ent-nope/live", headers=h).status_code == 404
    asyncio.run(engine.dispose())


def test_live_missing_connector_ref_400(migrated: str, app_url: str, migration_url: str) -> None:
    tid = "cv-t6"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))
    # 改 source_ref 为空 → 400
    async def _null_ref() -> None:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
            await conn.execute(
                text("UPDATE entities SET source_ref = NULL WHERE entity_id = 'ent-v1'")
            )
            await conn.commit()

    asyncio.run(_null_ref())
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid)}"}
        r = c.get("/v1/ontology/entities/ent-v1/live", headers=h)
        assert r.status_code == 400
        assert "source_ref" in r.json()["detail"]
    asyncio.run(engine.dispose())
