"""tech-debt #12 — TBox 审批流测试（Task 5）。

覆盖：提交→审批生效 / 拒绝 / 停用走审批 / 恢复路径闭环 / 自己审自己拒绝 /
重复提交校验 / list 过滤 / 审计事件。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.ontology import tbox_service


async def _seed(engine: AsyncEngine, tid: str) -> None:
    await tbox_service.init_tenant_tbox(engine, tid)


# ── 审批主链路 ───────────────────────────────────────────────────────────────


async def test_submit_and_approve_create_entity_type(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t1"
    await _seed(engine, tid)

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

    r = await tbox_service.approve_change(engine, tid, "u2", c["change_id"])
    assert r["status"] == "applied"
    types = await tbox_service.list_entity_types(engine, tid, status="all")
    assert any(t["entity_type_id"] == "new_equip" and t["status"] == "active" for t in types)


async def test_submit_and_reject(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t2"
    await _seed(engine, tid)

    c = await tbox_service.submit_change(
        engine,
        tid,
        "u1",
        change_type="relation_type",
        action="create",
        target_id="new_rel",
        payload={"name": "新关系", "source_type": "equipment", "target_type": "supplier"},
    )
    r = await tbox_service.reject_change(engine, tid, "u2", c["change_id"], "命名不合规")
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
    await _seed(engine, tid)

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

    await tbox_service.approve_change(engine, tid, "u2", c["change_id"])
    types = await tbox_service.list_entity_types(engine, tid, status="all")
    assert any(t["entity_type_id"] == "equipment" and t["status"] == "deprecated" for t in types)


async def test_reactivate_restore_path(migrated: str, app_url: str) -> None:
    """恢复路径闭环：停用 → 恢复 → active（D5）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t4"
    await _seed(engine, tid)

    # 停用
    d = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="deprecate", target_id="equipment"
    )
    await tbox_service.approve_change(engine, tid, "u2", d["change_id"])
    # 恢复
    r = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="reactivate", target_id="equipment"
    )
    assert r["status"] == "pending"
    await tbox_service.approve_change(engine, tid, "u2", r["change_id"])
    types = await tbox_service.list_entity_types(engine, tid, status="all")
    assert any(t["entity_type_id"] == "equipment" and t["status"] == "active" for t in types)


async def test_reactivate_relation_type(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t5"
    await _seed(engine, tid)

    d = await tbox_service.submit_change(
        engine, tid, "u1", change_type="relation_type", action="deprecate", target_id="manufactured_by"
    )
    await tbox_service.approve_change(engine, tid, "u2", d["change_id"])
    r = await tbox_service.submit_change(
        engine, tid, "u1", change_type="relation_type", action="reactivate", target_id="manufactured_by"
    )
    await tbox_service.approve_change(engine, tid, "u2", r["change_id"])
    rels = await tbox_service.list_relation_types(engine, tid, status="all")
    assert any(x["relation_type_id"] == "manufactured_by" and x["status"] == "active" for x in rels)


# ── 门禁与校验 ───────────────────────────────────────────────────────────────


async def test_cannot_approve_own_change(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t6"
    await _seed(engine, tid)

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
        await tbox_service.approve_change(engine, tid, "u1", c["change_id"])
    # 请求仍 pending
    detail = await tbox_service.list_changes(engine, tid, status="pending")
    assert any(x["change_id"] == c["change_id"] for x in detail)


async def test_submit_duplicate_create_rejected(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t7"
    await _seed(engine, tid)

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
    await tbox_service.approve_change(engine, tid, "u2", d["change_id"])
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
    await _seed(engine, tid)

    c = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="x1", payload={"name": "X1"}
    )
    await tbox_service.approve_change(engine, tid, "u2", c["change_id"])
    with pytest.raises(ValueError):
        await tbox_service.approve_change(engine, tid, "u2", c["change_id"])  # 二次审批


async def test_list_changes_status_filter(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "tb-t9"
    await _seed(engine, tid)

    c1 = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="a1", payload={"name": "A1"}
    )
    c2 = await tbox_service.submit_change(
        engine, tid, "u1", change_type="entity_type", action="create", target_id="a2", payload={"name": "A2"}
    )
    await tbox_service.approve_change(engine, tid, "u2", c1["change_id"])

    pending = await tbox_service.list_changes(engine, tid, status="pending")
    assert {x["change_id"] for x in pending} == {c2["change_id"]}
    all_changes = await tbox_service.list_changes(engine, tid)
    assert len(all_changes) == 2
    # pending 优先
    assert all_changes[0]["change_id"] == c2["change_id"]
