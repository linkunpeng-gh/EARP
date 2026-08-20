"""M3 B2/B3 — 同步任务：执行语义（幂等/facts 去重/事件）+ 卡死恢复 + job 状态机。

B3：sync_from_connector 经 adapter 取数 → 幂等 upsert → relations 生成 facts（活跃去重）
→ runtime.knowledge.synced 事件；二次同步不重复行/不重复 facts。
B2：recover_interrupted_sync 卡死恢复；sync job 状态机（running→completed/failed）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.ontology import connector_service, import_service, sync_jobs

FM = {
    "name_field": "equip_name",
    "business_code_field": "equip_code",
    "attr_fields": {"model": "model"},
    "relations": [{"relation_type": "manufactured_by", "target_field": "supplier_code"}],
}


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(
            text("DELETE FROM import_rules WHERE connector_id LIKE 'cn-s%' OR connector_id = 'cn-sync'")
        )
        await conn.execute(text("DELETE FROM connector_configs WHERE connector_id LIKE 'cn-s%'"))
        await conn.execute(text("DELETE FROM entities WHERE entity_id LIKE 'ent-sync%'"))
        await conn.execute(text("DELETE FROM roles WHERE role_id = 'r-admin'"))
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
                "('r-admin', :t, 'Admin', '{}', 'all', '[]', TRUE) ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        # equipment(object) + supplier(object) + oee(metric) + manufactured_by 关系
        await conn.execute(
            text(
                "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, "
                "data_domain_id, attributes) VALUES "
                "('equipment', :t, '设备', 'object', 'dd-a', '{\"model\":\"string\"}'), "
                "('supplier', :t, '供应商', 'object', 'dd-a', '{}'), "
                "('oee', :t, 'OEE', 'metric', 'dd-a', '{}') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO relation_types (relation_type_id, tenant_id, name, source_type, "
                "target_type, cardinality) VALUES "
                "('manufactured_by', :t, '由…制造', 'equipment', 'supplier', 'N:1') "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()


async def _make_connector_and_ds(
    engine: AsyncEngine, tid: str, *, cid: str = "cn-s1", adapter_type: str = "rest"
) -> dict:
    await connector_service.create_connector(
        engine, tid, connector_id=cid, adapter_type=adapter_type,
        config={"base_url": "http://mid/api", "token": "t"},
    )
    ds = await import_service.register_data_source(
        engine, tid, connector_id=cid, entity_type_id="equipment",
        source_mode="synced", field_mapping=FM,
    )
    assert ds is not None
    return ds


async def _mock_fetch(monkeypatch, rows: list[dict]):
    async def fake_fetch(cfg, params=None):
        return rows

    monkeypatch.setattr(import_service.data_adapter, "fetch", fake_fetch)


async def test_sync_creates_entities_and_facts(
    migrated: str, app_url: str, migration_url: str, monkeypatch
) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "sync-t1"
        await _seed(engine, migration_url, tid)
        ds = await _make_connector_and_ds(engine, tid)
        await _mock_fetch(monkeypatch, [
            {"equip_code": "CNC-01", "equip_name": "加工中心", "model": "XK-500", "supplier_code": "SUP-1"},
            {"equip_code": "CNC-02", "equip_name": "车床", "model": "CK-200", "supplier_code": "SUP-2"},
        ])
        events: list[str] = []
        bus = type("Bus", (), {"publish": lambda self, ev: events.append(ev.type)})()

        out = await import_service.sync_from_connector(engine, tid, ds["data_source_id"], bus=bus)
        assert out["rows"] == 2
        assert out["created"] == 2 and out["merged"] == 0
        assert out["facts_added"] == 2  # 每台设备 → manufactured_by 供应商
        assert out["errors"] == []
        assert "runtime.knowledge.synced" in events

        # 供应商实体被自动创建（A3 §4.3：目标实体不存在按编码建）
        sup = await import_service._find_by_code(engine, tid, "supplier", "SUP-1")
        assert sup is not None
    finally:
        await engine.dispose()


async def test_sync_idempotent_second_run(
    migrated: str, app_url: str, migration_url: str, monkeypatch
) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "sync-t2"
        await _seed(engine, migration_url, tid)
        ds = await _make_connector_and_ds(engine, tid)
        rows = [{"equip_code": "CNC-01", "equip_name": "加工中心", "model": "XK-500", "supplier_code": "SUP-1"}]
        await _mock_fetch(monkeypatch, rows)

        out1 = await import_service.sync_from_connector(engine, tid, ds["data_source_id"])
        out2 = await import_service.sync_from_connector(engine, tid, ds["data_source_id"])
        assert out1["created"] == 1 and out1["merged"] == 0
        assert out2["created"] == 0 and out2["merged"] == 1  # 幂等合并
        assert out2["facts_added"] == 0  # 活跃事实去重：二次同步不重复 facts

        # 实体只有 1 行 + 供应商 1 行
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
            r = await conn.execute(text("SELECT count(*) AS c FROM entities WHERE tenant_id = :t"), {"t": tid})
            assert r.mappings().first()["c"] == 2
            r = await conn.execute(
                text("SELECT count(*) AS c FROM facts WHERE tenant_id = :t AND status = 'active'"),
                {"t": tid},
            )
            assert r.mappings().first()["c"] == 1
    finally:
        await engine.dispose()


async def test_sync_row_error_collected_not_fatal(
    migrated: str, app_url: str, migration_url: str, monkeypatch
) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "sync-t3"
        await _seed(engine, migration_url, tid)
        ds = await _make_connector_and_ds(engine, tid)
        await _mock_fetch(monkeypatch, [
            {"equip_code": "", "equip_name": "缺编码"},  # business_code 为空 → 跳过
            {"equip_code": "CNC-03", "equip_name": "正常设备"},
        ])
        out = await import_service.sync_from_connector(engine, tid, ds["data_source_id"])
        assert out["created"] == 1
        assert len(out["errors"]) == 1
        assert "business_code" in out["errors"][0]["reason"]
    finally:
        await engine.dispose()


async def test_sync_fetch_failure_raises(migrated: str, app_url: str, migration_url: str, monkeypatch) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "sync-t4"
        await _seed(engine, migration_url, tid)
        ds = await _make_connector_and_ds(engine, tid)

        async def boom(cfg, params=None):
            raise import_service.data_adapter.ConnectorFetchError("超时")

        monkeypatch.setattr(import_service.data_adapter, "fetch", boom)
        with pytest.raises(import_service.data_adapter.ConnectorFetchError):
            await import_service.sync_from_connector(engine, tid, ds["data_source_id"])
    finally:
        await engine.dispose()


async def test_recover_interrupted_sync(
    migrated: str, app_url: str, migration_url: str, monkeypatch
) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "sync-t5"
        await _seed(engine, migration_url, tid)
        ds = await _make_connector_and_ds(engine, tid)
        # 伪造 running + 旧心跳（2h 前）
        old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        await import_service.mark_sync_state(engine, tid, ds["data_source_id"], status="running", synced_at=old)

        recovered = await sync_jobs.recover_interrupted_sync(engine, tid, ds["data_source_id"], ttl_seconds=1800)
        assert recovered is True
        got = await import_service.get_data_source(engine, tid, ds["data_source_id"])
        assert got["last_sync_status"] == "interrupted"

        # 心跳新鲜 → 不恢复（并发 409）
        await import_service.mark_sync_state(
            engine, tid, ds["data_source_id"],
            status="running", synced_at=datetime.now(UTC).isoformat(),
        )
        recovered2 = await sync_jobs.recover_interrupted_sync(
            engine, tid, ds["data_source_id"], ttl_seconds=1800
        )
        assert recovered2 is False
        got2 = await import_service.get_data_source(engine, tid, ds["data_source_id"])
        assert got2["last_sync_status"] == "running"
    finally:
        await engine.dispose()


async def test_sync_job_status_machine(
    migrated: str, app_url: str, migration_url: str, monkeypatch
) -> None:
    """job 直调：正常 → completed；取数失败 → failed。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "sync-t6"
        await _seed(engine, migration_url, tid)
        ds = await _make_connector_and_ds(engine, tid)

        async def fake_sync(engine, tenant_id, ds_id, *, heartbeat=None, bus=None):
            if heartbeat:
                await heartbeat()
            return {"rows": 1}

        monkeypatch.setattr(import_service, "sync_from_connector", fake_sync)
        # job 内部 build_engine(Settings()) 连 env 默认库——monkeypatch 指向测试库
        monkeypatch.setattr(sync_jobs, "build_engine", lambda settings: engine)
        # 直调 job 函数（FakeQueue 模拟 queue.task 注册）
        class FakeQueue:
            fn = None

            def task(self, **kw):
                def deco(f):
                    self.fn = f
                    return f

                return deco

        q = FakeQueue()
        sync_jobs.register(q)  # type: ignore[arg-type]
        job_fn = q.fn

        await job_fn(tid, ds["data_source_id"])
        got = await import_service.get_data_source(engine, tid, ds["data_source_id"])
        assert got["last_sync_status"] == "completed"
        assert got["last_synced_at"] is not None

        # 失败路径
        async def boom(engine, tenant_id, ds_id, *, heartbeat=None, bus=None):
            raise RuntimeError("取数失败")

        monkeypatch.setattr(import_service, "sync_from_connector", boom)
        await job_fn(tid, ds["data_source_id"])
        got2 = await import_service.get_data_source(engine, tid, ds["data_source_id"])
        assert got2["last_sync_status"] == "failed"
    finally:
        await engine.dispose()
