"""tech-debt #11 — profile 过期管理测试（Task 4）。

覆盖：写时失效（add_fact/revoke_fact/upsert_entity → profile 自动重编译）/
读时 freshness（get_entity_profile 过期重编译）/ timeline 写入（recent_events）/
find_stale_profiles / scheduler enrichment 冒烟。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.ontology import abox_service, tbox_service


async def _profile(engine, tid: str, eid: str) -> dict:
    p = await abox_service.get_entity_profile(engine, tid, eid)
    assert p is not None
    return p


async def _seed(engine: AsyncEngine, tid: str) -> dict:
    """supplier + equipment + profile（equipment）。"""
    await tbox_service.init_tenant_tbox(engine, tid)
    sup = await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-1")
    equip = await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01", business_code="CNC-01")
    await abox_service.compile_profile(engine, tid, equip["entity_id"])
    return {"equip": equip["entity_id"], "sup": sup["entity_id"]}


# ── 写时失效（D1）────────────────────────────────────────────────────────────


async def test_add_fact_invalidates_profile(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t1"
    scene = await _seed(engine, tid)

    before = await _profile(engine, tid, scene["equip"])
    assert before is not None and before["profile"]["key_facts"] == []

    await abox_service.add_fact(engine, tid, scene["equip"], "manufactured_by", scene["sup"])
    after = await _profile(engine, tid, scene["equip"])
    # key_facts.relation 是 relation_types.name（中文），断言按 name 匹配
    assert any("制造" in f["relation"] for f in after["profile"]["key_facts"])


async def test_revoke_fact_invalidates_profile(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t2"
    scene = await _seed(engine, tid)
    f = await abox_service.add_fact(engine, tid, scene["equip"], "manufactured_by", scene["sup"])

    with_fact = await _profile(engine, tid, scene["equip"])
    assert any("制造" in x["relation"] for x in with_fact["profile"]["key_facts"])

    await abox_service.revoke_fact(engine, tid, f["fact_id"])
    after = await _profile(engine, tid, scene["equip"])
    assert all("制造" not in x["relation"] for x in after["profile"]["key_facts"])


async def test_upsert_entity_merge_invalidates_profile(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t3"
    scene = await _seed(engine, tid)

    await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01-改名", business_code="CNC-01")
    after = await _profile(engine, tid, scene["equip"])
    assert after["profile"]["name"] == "CNC-01-改名"


# ── 读时 freshness（D2，绕过钩子的存量变更）──────────────────────────────────


async def test_read_time_freshness_detects_external_change(migrated: str, app_url: str) -> None:
    """绕过钩子直接改 facts.updated_at（模拟存量变更）→ get_entity_profile 过期重编译（version 递增）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t4"
    scene = await _seed(engine, tid)
    f = await abox_service.add_fact(engine, tid, scene["equip"], "manufactured_by", scene["sup"])
    v1 = (await _profile(engine, tid, scene["equip"]))["profile_version"]

    # 绕过钩子：直接 touch facts.updated_at（模拟未走钩子的存量数据变更）
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text("UPDATE facts SET updated_at = now() + interval '1 second' WHERE fact_id = :fid"),
            {"fid": f["fact_id"]},
        )
        await conn.commit()

    after = await _profile(engine, tid, scene["equip"])
    assert after["profile_version"] > v1  # 过期 → 重编译 → version 递增


async def test_read_time_freshness_timeline_source(migrated: str, app_url: str) -> None:
    """timeline 为主 freshness 源：加 timeline 事件（模拟钩子写入）→ 重编译。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t5"
    scene = await _seed(engine, tid)
    v1 = (await _profile(engine, tid, scene["equip"]))["profile_version"]

    await abox_service._log_timeline(engine, tid, scene["equip"], "fact.added", {"x": 1}, "f-x")
    after = await _profile(engine, tid, scene["equip"])
    assert after["profile_version"] > v1


# ── timeline 写入（recent_events）────────────────────────────────────────────


async def test_timeline_events_written(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t6"
    scene = await _seed(engine, tid)
    f = await abox_service.add_fact(engine, tid, scene["equip"], "manufactured_by", scene["sup"])
    await abox_service.revoke_fact(engine, tid, f["fact_id"])
    await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01-b", business_code="CNC-01")

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        events = (
            await conn.execute(
                text("SELECT event_type FROM entity_timeline WHERE entity_id = :eid ORDER BY occurred_at"),
                {"eid": scene["equip"]},
            )
        ).fetchall()
    types = [e.event_type for e in events]
    assert "entity.created" in types
    assert "fact.added" in types
    assert "fact.revoked" in types
    assert "entity.updated" in types

    # recent_events 生效（compile_profile 的 stats）
    prof = await _profile(engine, tid, scene["equip"])
    assert prof["profile"]["stats"]["recent_events"] > 0


# ── find_stale_profiles + scheduler enrichment（D3）──────────────────────────


async def test_find_stale_profiles(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t7"
    scene = await _seed(engine, tid)
    # 无 profile 实体（新实体，未编译）
    fresh = await abox_service.upsert_entity(engine, tid, "equipment", "CNC-NEW", business_code="CNC-NEW")

    stale = await abox_service.find_stale_profiles(engine, tid)
    assert fresh["entity_id"] in stale  # 无 profile → 扫出
    assert scene["equip"] not in stale  # 刚编译 → 新鲜

    # 过期（touch updated_at）→ 扫出
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text("UPDATE entities SET updated_at = now() + interval '1 second' WHERE entity_id = :eid"),
            {"eid": scene["equip"]},
        )
        await conn.commit()
    stale2 = await abox_service.find_stale_profiles(engine, tid)
    assert scene["equip"] in stale2


async def test_scheduler_enrichment_once(migrated: str, app_url: str, migration_url: str) -> None:
    """_run_enrichment_once 冒烟：过期 profile 被重编译（需 tenants 行，无 RLS 顶层表）。"""
    from earp_server.entrypoints.scheduler import _run_enrichment_once

    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ps-t8"
    scene = await _seed(engine, tid)

    # 保证 tenants 表有该租户（enrichment 扫 tenants 遍历）
    from sqlalchemy.ext.asyncio import create_async_engine as _cae

    mig = _cae(migration_url)
    async with mig.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO tenants (tenant_id, name, status) VALUES (:t, 'PS', 'active') "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"t": tid},
        )
    await mig.dispose()

    # 使 profile 过期
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text("UPDATE entities SET updated_at = now() WHERE entity_id = :eid"),
            {"eid": scene["equip"]},
        )
        await conn.commit()

    n = await _run_enrichment_once(engine)
    assert n["profiles_recompiled"] >= 1  # 重编译了过期的 equip
    # 重编译后新鲜 → 不再扫出
    stale = await abox_service.find_stale_profiles(engine, tid)
    assert scene["equip"] not in stale
