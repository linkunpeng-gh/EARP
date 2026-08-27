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
