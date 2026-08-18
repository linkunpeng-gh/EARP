"""tech-debt #9 — 角色域权限：roles CRUD + Admin 全权限通用机制 + 权限门禁测试。

覆盖：role_domain_access 三态（admin 全量/白名单/缺失 fail-closed）/ check_permission
（tbox.approve / admin 旁路）/ CRUD 校验（重复、非法 scope、幽灵域拒绝）/ 最后 admin
保护 / 跨租户隔离。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.policy import roles_service


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    # role_id 单列主键（debt #7 模式）：固定语义 id 跨测试租户冲突 → migration 角色全局 purge
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(
            text("DELETE FROM roles WHERE role_id = ANY(ARRAY['r-admin','r-ops','r-view'])")
        )
    await eng.dispose()
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) VALUES "
                "('dd-a', :t, '域A', 'x', 'internal', 'active'), "
                "('dd-b', :t, '域B', 'x', 'internal', 'active'), "
                "('dd-dead', :t, '停用域', 'x', 'internal', 'deprecated') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-admin', :t, 'Admin', ARRAY['tbox.approve'], 'all', '[]', TRUE), "
                "('r-ops', :t, '运营', ARRAY['tbox.approve'], 'all', "
                "'[{\"data_domain_id\": \"dd-a\"}]', FALSE), "
                "('r-view', :t, '只读', '{}', 'self', '[]', FALSE) ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()


# ── role_domain_access 三态 ───────────────────────────────────────────────────
async def test_domain_access_admin_returns_all(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rl-admin"
    await _seed(engine, migrated, tid)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        out = await roles_service.role_domain_access(conn, tid, "r-admin", ["dd-a", "dd-b", "dd-new"])
    assert out == {"dd-a", "dd-b", "dd-new"}  # admin 全权限：新建 DD 也自动可见


async def test_domain_access_whitelist_subset(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rl-ops"
    await _seed(engine, migrated, tid)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        out = await roles_service.role_domain_access(conn, tid, "r-ops", ["dd-a", "dd-b"])
    assert out == {"dd-a"}


async def test_domain_access_missing_role_fail_closed(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rl-miss"
    await _seed(engine, migrated, tid)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        out = await roles_service.role_domain_access(conn, tid, "r-nope", ["dd-a", "dd-b"])
    assert out == set()


# ── check_permission 门禁 ─────────────────────────────────────────────────────
async def test_check_permission_permission_and_admin_bypass(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rl-perm"
    await _seed(engine, migrated, tid)
    assert await roles_service.check_permission(engine, tid, "r-ops", "tbox.approve") is True
    assert await roles_service.check_permission(engine, tid, "r-ops", "other.perm") is False
    assert await roles_service.check_permission(engine, tid, "r-view", "tbox.approve") is False
    # admin 无权限串也通过（全权限旁路）
    await roles_service.update_role(engine, tid, "r-admin", permissions=[])
    assert await roles_service.check_permission(engine, tid, "r-admin", "tbox.approve") is True
    assert await roles_service.check_permission(engine, tid, "r-nope", "tbox.approve") is False


# ── CRUD + 校验 ───────────────────────────────────────────────────────────────
async def test_create_role_and_validation(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rl-create"
    await _seed(engine, migrated, tid)

    r = await roles_service.create_role(
        engine, tid, name="新角色", role_id="r-new", data_scope="org",
        data_domain_access=[{"data_domain_id": "dd-b"}],
    )
    assert r["role_id"] == "r-new" and r["is_admin"] is False
    assert r["data_domain_access"] == [{"data_domain_id": "dd-b"}]

    with pytest.raises(ValueError, match="已存在"):
        await roles_service.create_role(engine, tid, name="重复", role_id="r-new")
    with pytest.raises(ValueError, match="data_scope"):
        await roles_service.create_role(engine, tid, name="x", data_scope="super")
    with pytest.raises(ValueError, match="数据域"):
        await roles_service.create_role(
            engine, tid, name="幽灵域", data_domain_access=[{"data_domain_id": "dd-ghost"}]
        )
    # deprecated 域不可授权（fail-closed 安全校验）
    with pytest.raises(ValueError, match="数据域"):
        await roles_service.create_role(
            engine, tid, name="停用域", data_domain_access=[{"data_domain_id": "dd-dead"}]
        )


async def test_update_role(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rl-upd"
    await _seed(engine, migrated, tid)

    r = await roles_service.update_role(
        engine, tid, "r-view", name="运营助理", permissions=["query.alarms"], data_scope="org",
        data_domain_access=[{"data_domain_id": "dd-a"}, {"data_domain_id": "dd-b"}],
    )
    assert r["name"] == "运营助理" and r["permissions"] == ["query.alarms"]
    assert len(r["data_domain_access"]) == 2
    # 不存在 → None
    assert await roles_service.update_role(engine, tid, "r-nope", name="x") is None
    # 最后一名 admin 不可降级
    with pytest.raises(ValueError, match="admin"):
        await roles_service.update_role(engine, tid, "r-admin", is_admin=False)


async def test_delete_role_and_last_admin_guard(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "rl-del"
    await _seed(engine, migrated, tid)

    assert await roles_service.delete_role(engine, tid, "r-view") is True
    assert await roles_service.get_role(engine, tid, "r-view") is None
    assert await roles_service.delete_role(engine, tid, "r-view") is False  # 幂等
    with pytest.raises(ValueError, match="admin"):
        await roles_service.delete_role(engine, tid, "r-admin")  # 最后一名 admin


async def test_cross_tenant_isolation(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    await _seed(engine, migrated, "rl-iso-a")
    assert await roles_service.get_role(engine, "rl-iso-b", "r-admin") is None  # RLS
    # A 的 admin 在 B 视角不可见 → 无法删除/更新
    assert await roles_service.update_role(engine, "rl-iso-b", "r-admin", name="hack") is None
    assert await roles_service.delete_role(engine, "rl-iso-b", "r-admin") is False
