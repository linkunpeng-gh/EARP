"""tech-debt #12 — TBox 审批流测试（Task 5）。

覆盖：提交→审批生效 / 拒绝 / 停用走审批 / 恢复路径闭环 / 自己审自己拒绝 /
重复提交校验 / list 过滤 / 审计事件。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.ontology import tbox_service


async def _purge_roles(migration_url: str) -> None:
    """固定语义 role_id 单列主键（debt #7 模式）：migration 角色（BYPASSRLS）全局清理。"""
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM roles WHERE role_id = ANY(ARRAY['r-approver','r-nogate','r-admin'])"))
    await eng.dispose()


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    await tbox_service.init_tenant_tbox(engine, tid)
    await _purge_roles(migration_url)
    # tech-debt #9 审批人角色门禁：审批需 tbox.approve 权限或 is_admin
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-approver', :t, '审批员', ARRAY['tbox.approve'], 'all', '[]', FALSE), "
                "('r-nogate', :t, '普通角色', '{}', 'all', '[]', FALSE), "
                "('r-admin', :t, 'Admin', '{}', 'all', '[]', TRUE) "
                "ON CONFLICT (role_id) DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()


# ── 审批主链路 ───────────────────────────────────────────────────────────────


async def test_submit_and_approve_create_entity_type(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t1"
    await _seed(engine, migrated, tid)

    c = await tbox_service.submit_change(
        engine,
        tid,
        "u1",
        change_type="entity_type",
        action="create",
        target_id="new_equip",
        payload={"name": "新设备", "kind": "object", "data_domain_id": "equipment_data"},
    )
    assert c["status"] == "pending"
    # approve 前类型不存在
    types = await tbox_service.list_entity_types(engine, tid, status="all")
    assert all(t["entity_type_id"] != "new_equip" for t in types)

    r = await tbox_service.approve_change(engine, tid, "u2", c["change_id"], role_id="r-approver")
    assert r["status"] == "applied"
    types = await tbox_service.list_entity_types(engine, tid, status="all")
    assert any(t["entity_type_id"] == "new_equip" and t["status"] == "active" for t in types)


async def test_submit_and_reject(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t2"
    await _seed(engine, migrated, tid)

    c = await tbox_service.submit_change(
        engine,
        tid,
        "u1",
        change_type="relation_type",
        action="create",
        target_id="new_rel",
        payload={"name": "新关系", "source_type": "equipment", "target_type": "supplier"},
    )
    r = await tbox_service.reject_change(engine, tid, "u2", c["change_id"], "命名不合规", role_id="r-approver")
    assert r["status"] == "rejected"
    rels = await tbox_service.list_relation_types(engine, tid, status="all")
    assert all(x["relation_type_id"] != "new_rel" for x in rels)
    detail = await tbox_service.list_changes(engine, tid)
    c2 = next(x for x in detail if x["change_id"] == c["change_id"])
    assert c2["review_reason"] == "命名不合规"
    assert c2["reviewed_by"] == "u2"


async def test_deprecate_via_approval(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t3"
    await _seed(engine, migrated, tid)

    c = await tbox_service.submit_change(
        engine,
        tid,
        "u1",
        change_type="entity_type",
        action="deprecate",
        target_id="equipment",
    )
    assert c["status"] == "pending"
    # approve 前未停用
    assert any(
        t["entity_type_id"] == "equipment" and t["status"] == "active"
        for t in await tbox_service.list_entity_types(engine, tid, status="all")
    )

    await tbox_service.approve_change(engine, tid, "u2", c["change_id"], role_id="r-approver")
    types = await tbox_service.list_entity_types(engine, tid, status="all")
    assert any(t["entity_type_id"] == "equipment" and t["status"] == "deprecated" for t in types)


async def test_reactivate_restore_path(migrated: str, app_url: str) -> None:
    """恢复路径闭环：停用 → 恢复 → active（D5）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t4"
    await _seed(engine, migrated, tid)

    # 停用
    d = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="deprecate", target_id="equipment"
    )
    await tbox_service.approve_change(engine, tid, "u2", d["change_id"], role_id="r-approver")
    # 恢复
    r = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="reactivate", target_id="equipment"
    )
    assert r["status"] == "pending"
    await tbox_service.approve_change(engine, tid, "u2", r["change_id"], role_id="r-approver")
    types = await tbox_service.list_entity_types(engine, tid, status="all")
    assert any(t["entity_type_id"] == "equipment" and t["status"] == "active" for t in types)


async def test_reactivate_relation_type(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t5"
    await _seed(engine, migrated, tid)

    d = await tbox_service.submit_change(
        engine, tid, "u1", change_type="relation_type", action="deprecate", target_id="manufactured_by"
    )
    await tbox_service.approve_change(engine, tid, "u2", d["change_id"], role_id="r-approver")
    r = await tbox_service.submit_change(
        engine, tid, "u1", change_type="relation_type", action="reactivate", target_id="manufactured_by"
    )
    await tbox_service.approve_change(engine, tid, "u2", r["change_id"], role_id="r-approver")
    rels = await tbox_service.list_relation_types(engine, tid, status="all")
    assert any(x["relation_type_id"] == "manufactured_by" and x["status"] == "active" for x in rels)


# ── 门禁与校验 ───────────────────────────────────────────────────────────────


async def test_cannot_approve_own_change(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t6"
    await _seed(engine, migrated, tid)

    c = await tbox_service.submit_change(
        engine,
        tid,
        "u1",
        change_type="entity_type",
        action="create",
        target_id="own_equip",
        payload={"name": "自助类型"},
    )
    with pytest.raises(PermissionError):
        await tbox_service.approve_change(engine, tid, "u1", c["change_id"], role_id="r-approver")
    # 请求仍 pending
    detail = await tbox_service.list_changes(engine, tid, status="pending")
    assert any(x["change_id"] == c["change_id"] for x in detail)


async def test_submit_duplicate_create_rejected(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t7"
    await _seed(engine, migrated, tid)

    with pytest.raises(ValueError):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="create",
            target_id="equipment",  # 已存在（active）
            payload={"name": "重复类型"},
        )
    # deprecated 类型提示走恢复
    d = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="deprecate", target_id="equipment"
    )
    await tbox_service.approve_change(engine, tid, "u2", d["change_id"], role_id="r-approver")
    with pytest.raises(ValueError, match="恢复"):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="create",
            target_id="equipment",
            payload={"name": "重复"},
        )


async def test_approve_non_pending_fails(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t8"
    await _seed(engine, migrated, tid)

    c = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="x1", payload={"name": "X1"}
    )
    await tbox_service.approve_change(engine, tid, "u2", c["change_id"], role_id="r-approver")
    with pytest.raises(ValueError):
        await tbox_service.approve_change(engine, tid, "u2", c["change_id"], role_id="r-approver")  # 二次审批


async def test_list_changes_status_filter(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t9"
    await _seed(engine, migrated, tid)

    c1 = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="a1", payload={"name": "A1"}
    )
    c2 = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="a2", payload={"name": "A2"}
    )
    await tbox_service.approve_change(engine, tid, "u2", c1["change_id"], role_id="r-approver")

    pending = await tbox_service.list_changes(engine, tid, status="pending")
    assert {x["change_id"] for x in pending} == {c2["change_id"]}
    all_changes = await tbox_service.list_changes(engine, tid)
    assert len(all_changes) == 2
    # pending 优先
    assert all_changes[0]["change_id"] == c2["change_id"]


# ── tech-debt #9 审批人角色门禁 ───────────────────────────────────────────────
async def test_approve_requires_tbox_approve_permission(migrated: str, app_url: str) -> None:
    """无 tbox.approve 权限（且非 admin）→ 403（PermissionError）；不改变请求状态。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-gate1"
    await _seed(engine, migrated, tid)

    c = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="g1", payload={"name": "G1"}
    )
    with pytest.raises(PermissionError, match="tbox.approve"):
        await tbox_service.approve_change(engine, tid, "u2", c["change_id"], role_id="r-nogate")
    # 请求仍 pending，未被改动
    pending = await tbox_service.list_changes(engine, tid, status="pending")
    assert c["change_id"] in {x["change_id"] for x in pending}
    with pytest.raises(PermissionError, match="tbox.approve"):
        await tbox_service.reject_change(engine, tid, "u2", c["change_id"], "无权限", role_id="r-nogate")
    pending = await tbox_service.list_changes(engine, tid, status="pending")
    assert c["change_id"] in {x["change_id"] for x in pending}


async def test_admin_role_bypasses_approval_gate(migrated: str, app_url: str) -> None:
    """is_admin 角色无 tbox.approve 权限也可审批（Admin 全权限通用机制）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-gate2"
    await _seed(engine, migrated, tid)

    c = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="g2", payload={"name": "G2"}
    )
    r = await tbox_service.approve_change(engine, tid, "u2", c["change_id"], role_id="r-admin")
    assert r["status"] == "applied"


# ── 2026-09 修复：list 路由逐项审批能力 + 自审 403（路由层，回归 bug：本体审批点批准 403）─


def test_list_changes_route_flags_and_self_approval_403(migrated: str, app_url: str) -> None:
    """GET /tbox/changes 逐项返回 own/can_approve/can_reject——自己提交行 can_approve=false
    （提交者不能自审，与 approve 403 语义一致，前端据此不渲染「批准」）；
    自审 approve → 403；他人审批 → 200 applied；无门禁角色全 false（fail-closed）。"""
    import asyncio

    import jwt
    from fastapi.testclient import TestClient

    from earp_server.config import Settings
    from earp_server.main import create_app

    tid = "tb-rt1"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))

    c_own = asyncio.run(
        tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="create",
            target_id="rt_x",
            payload={"name": "X"},
        )
    )
    c_other = asyncio.run(
        tbox_service.submit_change(
            engine,
            tid,
            "u2",
            change_type="entity_type",
            action="create",
            target_id="rt_y",
            payload={"name": "Y"},
        )
    )

    app = create_app(Settings(database_url=app_url, app_env="test"))
    SECRET = "earp-dev-secret-change-in-production"

    def _tok(user: str, role: str) -> str:
        return jwt.encode(
            {"sub": user, "tenant_id": tid, "role_id": role, "exp": 9999999999},
            SECRET,
            algorithm="HS256",
        )

    with TestClient(app) as c:
        # u1（提交者 + 审批员角色）：自己的请求 can_approve=false / own=true / can_reject=true；
        # 他人的请求 can_approve=true
        h_own = {"Authorization": f"Bearer {_tok('u1', 'r-approver')}"}
        rows = c.get("/v1/ontology/tbox/changes", headers=h_own).json()
        mine = next(x for x in rows if x["change_id"] == c_own["change_id"])
        assert mine["own"] is True and mine["can_approve"] is False and mine["can_reject"] is True, mine
        theirs = next(x for x in rows if x["change_id"] == c_other["change_id"])
        assert theirs["own"] is False and theirs["can_approve"] is True and theirs["can_reject"] is True, theirs

        # u1 自审自己的请求 → 403（detail 含原因）
        r = c.post(f"/v1/ontology/tbox/changes/{c_own['change_id']}/approve", headers=h_own)
        assert r.status_code == 403, r.text
        assert "自己" in r.json()["detail"]
        # u2 审批 u1 的请求 → 200 applied
        h_other = {"Authorization": f"Bearer {_tok('u2', 'r-approver')}"}
        r2 = c.post(f"/v1/ontology/tbox/changes/{c_own['change_id']}/approve", headers=h_other)
        assert r2.status_code == 200 and r2.json()["status"] == "applied", r2.text

        # 无门禁角色（r-nogate）：can_approve/can_reject 全 false；approve → 403
        h_nogate = {"Authorization": f"Bearer {_tok('u1', 'r-nogate')}"}
        rows2 = c.get("/v1/ontology/tbox/changes", headers=h_nogate).json()
        row2 = next(x for x in rows2 if x["change_id"] == c_other["change_id"])
        assert row2["can_approve"] is False and row2["can_reject"] is False, row2
        r3 = c.post(f"/v1/ontology/tbox/changes/{c_other['change_id']}/approve", headers=h_nogate)
        assert r3.status_code == 403, r3.text
    asyncio.run(engine.dispose())


# ── 2026-09：数据域变更（action='update'，设计 arch/design/2026-09-04 §4.2/§4.1）─────────


async def _seed_update_dds(engine: AsyncEngine, tid: str) -> None:
    """目标域必须存在且 active（与角色域授权同口径）。"""
    from sqlalchemy import text as _text

    async with engine.connect() as conn:
        await conn.execute(_text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            _text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, data_classification, status) "
                "VALUES ('finance_data', :t, '财务数据', 'internal', 'active'), "
                "('archive_data', :t, '归档数据', 'internal', 'deprecated') "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()


async def test_update_change_submit_prechecks(migrated: str, app_url: str) -> None:
    """update 提交预检：仅实体类型/类型存在且 active/同域 no-op/目标域 active。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-up1"
    await _seed(engine, migrated, tid)
    await _seed_update_dds(engine, tid)

    with pytest.raises(ValueError, match="仅支持实体类型"):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="relation_type",
            action="update",
            target_id="manufactured_by",
            payload={"data_domain_id": "finance_data"},
        )
    with pytest.raises(ValueError, match="实体类型不存在"):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="update",
            target_id="ghost",
            payload={"data_domain_id": "finance_data"},
        )
    # deprecated 类型不可改域（先 reactivate）
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(text("UPDATE entity_types SET status='deprecated' WHERE entity_type_id='equipment'"))
        await conn.commit()
    with pytest.raises(ValueError, match="已停用"):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="update",
            target_id="equipment",
            payload={"data_domain_id": "finance_data"},
        )
    await tbox_service.reactivate_entity_type(engine, tid, "equipment")
    # 同域 no-op
    with pytest.raises(ValueError, match="数据域未变更"):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="update",
            target_id="equipment",
            payload={"data_domain_id": "equipment_data"},
        )
    # 目标域不存在 / 非 active
    with pytest.raises(ValueError, match="不存在或未启用"):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="update",
            target_id="equipment",
            payload={"data_domain_id": "hr_data"},
        )
    with pytest.raises(ValueError, match="不存在或未启用"):
        await tbox_service.submit_change(
            engine,
            tid,
            "u1",
            change_type="entity_type",
            action="update",
            target_id="equipment",
            payload={"data_domain_id": "archive_data"},
        )
    # 缺 payload
    with pytest.raises(ValueError, match="缺少 data_domain_id"):
        await tbox_service.submit_change(
            engine, tid, "u1", change_type="entity_type", action="update", target_id="equipment", payload={}
        )
    await engine.dispose()


async def test_update_approve_cascades_entities(migrated: str, app_url: str) -> None:
    """批准 update：类型域 + active/deprecated 实例级联迁移；merged 不随迁；
    entity_count/domain_from 随提交响应；自审 403；profile 读时 freshness 覆盖。"""
    from earp_server.ontology import abox_service

    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-up2"
    await _seed(engine, migrated, tid)
    await _seed_update_dds(engine, tid)

    act = await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01", business_code="CNC-01")
    dep = await abox_service.upsert_entity(engine, tid, "equipment", "CNC-02", business_code="CNC-02")
    mer = await abox_service.upsert_entity(engine, tid, "equipment", "CNC-03", business_code="CNC-03")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(text("UPDATE entities SET status='deprecated' WHERE entity_id=:e"), {"e": dep["entity_id"]})
        await conn.execute(text("UPDATE entities SET status='merged' WHERE entity_id=:e"), {"e": mer["entity_id"]})
        await conn.commit()
    # 审批前 profile 编译（读时 freshness 覆盖验证前置）
    await abox_service.compile_profile(engine, tid, act["entity_id"])

    c = await tbox_service.submit_change(
        engine,
        tid,
        "u1",
        change_type="entity_type",
        action="update",
        target_id="equipment",
        payload={"data_domain_id": "finance_data"},
    )
    assert c["status"] == "pending"
    assert c["domain_from"] == "equipment_data"
    assert c["entity_count"] == 2  # active + deprecated；merged 不计

    # 自审 403（沿用）
    with pytest.raises(PermissionError, match="自己"):
        await tbox_service.approve_change(engine, tid, "u1", c["change_id"], role_id="r-approver")

    # 提交后、批准前域未变
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        t = (
            await conn.execute(text("SELECT data_domain_id FROM entity_types WHERE entity_type_id='equipment'"))
        ).fetchone()
    assert t.data_domain_id == "equipment_data"

    r = await tbox_service.approve_change(engine, tid, "u2", c["change_id"], role_id="r-approver")
    assert r["status"] == "applied"
    assert r["domain_from"] == "equipment_data" and r["domain_to"] == "finance_data"
    assert r["entity_count"] == 2

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        t = (
            await conn.execute(text("SELECT data_domain_id, status FROM entity_types WHERE entity_type_id='equipment'"))
        ).fetchone()
        assert t.data_domain_id == "finance_data" and t.status == "active"
        rows = await conn.execute(
            text("SELECT entity_id, data_domain_id, status FROM entities WHERE entity_type_id='equipment'")
        )
        by_id = {r.entity_id: (r.data_domain_id, r.status) for r in rows}
        assert by_id[act["entity_id"]] == ("finance_data", "active")
        assert by_id[dep["entity_id"]] == ("finance_data", "deprecated")
        assert by_id[mer["entity_id"]] == ("equipment_data", "merged")  # merged 不随迁
        # profile 读时 freshness：域变更 bump updated_at → 下次读取自动重编译
        chg = (
            await conn.execute(
                text(
                    "SELECT compiled_at < updated_at AS stale FROM entities e "
                    "JOIN entity_profiles p ON p.entity_id = e.entity_id "
                    "WHERE e.entity_id = :eid"
                ),
                {"eid": act["entity_id"]},
            )
        ).fetchone()
    assert chg is not None and chg.stale is True
    fresh = await abox_service.get_entity_profile(engine, tid, act["entity_id"])
    assert fresh is not None and fresh["profile_version"] >= 1
    await engine.dispose()


async def test_update_reject_leaves_domain_unchanged(migrated: str, app_url: str) -> None:
    """拒绝 update：pending → rejected，类型与实例域不变。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-up3"
    await _seed(engine, migrated, tid)
    await _seed_update_dds(engine, tid)

    c = await tbox_service.submit_change(
        engine,
        tid,
        "u1",
        change_type="entity_type",
        action="update",
        target_id="equipment",
        payload={"data_domain_id": "finance_data"},
    )
    r = await tbox_service.reject_change(engine, tid, "u2", c["change_id"], "暂缓", role_id="r-approver")
    assert r["status"] == "rejected"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        t = (
            await conn.execute(text("SELECT data_domain_id FROM entity_types WHERE entity_type_id='equipment'"))
        ).fetchone()
    assert t.data_domain_id == "equipment_data"
    await engine.dispose()


async def test_domain_migration_vs_concurrent_upsert_never_leaves_stale_instance(migrated: str, app_url: str) -> None:
    """upsert_entity 对类型行的 FOR SHARE 锁：与 update 审批并发时，实例域要么读到迁移后
    的新域、要么先于迁移提交（审批随后级联覆盖），终态类型域 == 实例域恒成立。

    无锁（READ COMMITTED）时存在 TOCTOU：upsert 读到旧域 → 审批迁移并提交 → upsert
    把旧域写回实例行（merge-UPDATE 覆盖已迁移实例 / INSERT 在迁移后落旧域新行）。
    """
    import asyncio
    import uuid

    from earp_server.ontology import abox_service

    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = f"tb-toctou-{uuid.uuid4().hex[:6]}"
    await _seed(engine, migrated, tid)
    await _seed_update_dds(engine, tid)
    # 轮换目标域需 equipment_data 作为 active 数据域行存在（init_tenant_tbox 只建类型）。
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, data_classification, status) "
                "VALUES ('equipment_data', :t, '设备数据', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()
    targets = ("finance_data", "equipment_data")
    codes = [f"CNC-TOCTOU-{i}" for i in range(3)]
    try:
        for round_no in range(8):
            target = targets[round_no % 2]
            change = await tbox_service.submit_change(
                engine,
                tid,
                "u1",
                change_type="entity_type",
                action="update",
                target_id="equipment",
                payload={"data_domain_id": target},
            )
            # 并发：域迁移审批（类型行排他锁 + 实例级联） vs 既有实例 merge-upsert（首轮为
            # INSERT，后续轮次走 merge-UPDATE 路径）——覆盖两条写入路径的 TOCTOU 窗口。
            tasks = [
                tbox_service.approve_change(engine, tid, "u2", change["change_id"], role_id="r-approver"),
                *[abox_service.upsert_entity(engine, tid, "equipment", code, business_code=code) for code in codes],
            ]
            await asyncio.gather(*tasks)
        # 终态不变量：类型域 == 每个 active 实例域（无残留旧域写回）。
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
            type_dd = (
                await conn.execute(text("SELECT data_domain_id FROM entity_types WHERE entity_type_id='equipment'"))
            ).scalar_one()
            instance_dds = set(
                (
                    await conn.execute(
                        text("SELECT data_domain_id FROM entities WHERE entity_type_id='equipment' AND status='active'")
                    )
                ).scalars()
            )
        assert instance_dds == {type_dd}, f"实例域 {instance_dds} 与类型域 {type_dd} 不一致（旧域被写回）"
    finally:
        await engine.dispose()
