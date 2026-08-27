"""能力中心：注册 / 管理（tech-debt #14）+ 复合主键（tech-debt #7）+ execution 声明。

覆盖：service 层 create/get/update/deprecate + 校验（type/schema/permissions/execution）
+ 跨租户同名能力隔离 + 审计事件 earp.capability.*；HTTP 端点 admin 门禁 / 422 / 200-201。
"""

from __future__ import annotations

import asyncio

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.audit.consumer import audit_handler_factory
from earp_server.capability import service as cap_service
from earp_server.config import Settings
from earp_server.infra.eventbus import EventBus
from earp_server.main import create_app

SECRET = "earp-dev-secret-change-in-production"
TENANT_A = "capadmin-ta"
TENANT_B = "capadmin-tb"


async def _seed_tenant(engine: AsyncEngine, tid: str) -> None:
    # 单列 PK 跨租户污染防护（tech-debt #13）：users/roles 均按租户派生唯一 id
    admin_rid = f"{tid}-admin"
    view_rid = f"{tid}-view"
    uid = f"{tid}-u1"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES (:u, :t, 'u1', 'u1@e.io') ON CONFLICT DO NOTHING"
            ),
            {"u": uid, "t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, is_admin) "
                "VALUES (:admin, :t, 'Admin', '{}', 'all', TRUE), "
                "(:view, :t, '普通', '{}', 'all', FALSE) "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": tid, "admin": admin_rid, "view": view_rid},
        )
        await conn.commit()


def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def _token(tid: str, role_id: str) -> str:
    return jwt.encode(
        {"sub": f"{tid}-u1", "tenant_id": tid, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


# ── Service 层 ────────────────────────────────────────────────────────────────


async def test_create_and_get_capability(app_engine: AsyncEngine) -> None:
    await _seed_tenant(app_engine, TENANT_A)
    cap = await cap_service.create_capability(
        app_engine,
        TENANT_A,
        domain="equipment",
        name="query_alarm",
        type="query",
        required_permissions=["alarm:read"],
        execution={"adapter": "tool.fetch", "params": {"connector_id": "cn-1"}},
        capability_id="cap-query-alarm",
    )
    assert cap["capability_id"] == "cap-query-alarm"
    assert cap["required_permissions"] == ["alarm:read"]
    assert cap["execution"] == {"adapter": "tool.fetch", "params": {"connector_id": "cn-1"}}
    assert cap["status"] == "active"

    got = await cap_service.get_capability(app_engine, TENANT_A, "cap-query-alarm")
    assert got is not None
    assert got["domain"] == "equipment"


async def test_create_requires_permissions(app_engine: AsyncEngine) -> None:
    with pytest.raises(ValueError, match="required_permissions"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="x",
            name="y",
            type="query",
            required_permissions=[],
            capability_id="cap-noperm",
        )


async def test_create_invalid_type(app_engine: AsyncEngine) -> None:
    with pytest.raises(ValueError, match="type"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="x",
            name="y",
            type="magic",
            required_permissions=["p"],
            capability_id="cap-badtype",
        )


async def test_create_invalid_schema(app_engine: AsyncEngine) -> None:
    with pytest.raises(ValueError, match="properties"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="x",
            name="y",
            type="query",
            required_permissions=["p"],
            input_schema={"type": "object"},
            capability_id="cap-badschema",
        )


async def test_create_unknown_adapter_warns_but_allows(app_engine: AsyncEngine) -> None:
    """执行器任务书 D6：未知 adapter 仅 warning 不阻断（执行时再严判）。"""
    cap = await cap_service.create_capability(
        app_engine,
        TENANT_A,
        domain="x",
        name="y",
        type="query",
        required_permissions=["p"],
        execution={"adapter": "ghost.adapter"},
        capability_id="cap-ghost",
    )
    assert cap["execution"] == {"adapter": "ghost.adapter"}


async def test_cross_tenant_same_capability_id(app_engine: AsyncEngine) -> None:
    """tech-debt #7：复合主键 (capability_id, tenant_id) —— 跨租户同名能力各自隔离。"""
    await _seed_tenant(app_engine, TENANT_B)
    for tid in (TENANT_A, TENANT_B):
        cap = await cap_service.create_capability(
            app_engine,
            tid,
            domain="shared",
            name="echo",
            type="query",
            required_permissions=["p"],
            capability_id="cap-shared",
        )
        assert cap is not None
    # 租户 A 的能力在 B 不可见
    assert await cap_service.get_capability(app_engine, TENANT_B, "cap-query-alarm") is None
    assert await cap_service.get_capability(app_engine, TENANT_A, "cap-shared") is not None
    assert await cap_service.get_capability(app_engine, TENANT_B, "cap-shared") is not None


async def test_update_and_deprecate(app_engine: AsyncEngine) -> None:
    await cap_service.create_capability(
        app_engine,
        TENANT_A,
        domain="d",
        name="n",
        type="query",
        required_permissions=["p"],
        capability_id="cap-upd",
        version="1.0.0",
    )
    updated = await cap_service.update_capability(
        app_engine,
        TENANT_A,
        "cap-upd",
        version="2.0.0",
        execution={"adapter": "demo.echo"},
    )
    assert updated["version"] == "2.0.0"
    assert updated["execution"] == {"adapter": "demo.echo"}

    dead = await cap_service.deprecate_capability(app_engine, TENANT_A, "cap-upd")
    assert dead["status"] == "deprecated"
    # 已停用不可更新
    with pytest.raises(ValueError, match="已停用"):
        await cap_service.update_capability(app_engine, TENANT_A, "cap-upd", version="3.0.0")
    # 停用幂等
    again = await cap_service.deprecate_capability(app_engine, TENANT_A, "cap-upd")
    assert again["status"] == "deprecated"


async def test_audit_events_on_capability_lifecycle(app_engine: AsyncEngine) -> None:
    bus = EventBus()
    bus.subscribe("earp.capability.*", audit_handler_factory(app_engine))
    await cap_service.create_capability(
        app_engine,
        TENANT_A,
        domain="d",
        name="n",
        type="query",
        required_permissions=["p"],
        capability_id="cap-audit",
        bus=bus,
        user_id="u1",
    )
    await cap_service.update_capability(app_engine, TENANT_A, "cap-audit", version="2.0.0", bus=bus, user_id="u1")
    await cap_service.deprecate_capability(app_engine, TENANT_A, "cap-audit", bus=bus, user_id="u1")

    async with app_engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT_A}'"))
        rows = (
            await conn.execute(
                text(
                    "SELECT event_type FROM audit_logs WHERE tenant_id = :t "
                    "AND entity_type = 'capability' AND entity_id = 'cap-audit' ORDER BY event_type"
                ),
                {"t": TENANT_A},
            )
        ).fetchall()
    types = [r[0] for r in rows]
    assert "earp.capability.registered" in types
    assert "earp.capability.updated" in types
    assert "earp.capability.deprecated" in types
    # 清理，避免污染其它测试
    async with app_engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT_A}'"))
        await conn.execute(text("DELETE FROM audit_logs WHERE tenant_id = :t"), {"t": TENANT_A})
        await conn.commit()


# ── HTTP 端点 ────────────────────────────────────────────────────────────────


def test_capability_create_requires_admin(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed_tenant(engine, "capapi-t1"))
    app = _make_app(app_url)
    body = {
        "domain": "equipment",
        "name": "query_alarm",
        "type": "query",
        "required_permissions": ["alarm:read"],
        "capability_id": "cap-api-1",
        "execution": {"adapter": "tool.fetch", "params": {"connector_id": "cn-1"}},
    }
    with TestClient(app) as c:
        h_user = {"Authorization": f"Bearer {_token('capapi-t1', 'capapi-t1-view')}"}
        # 非 admin：POST 注册 403（门禁 D4）
        r = c.post("/capabilities", json=body, headers=h_user)
        assert r.status_code == 403, r.text
        # 非 admin：PATCH/DELETE 同样 403
        assert c.patch("/capabilities/cap-api-1", json={"version": "2.0.0"}, headers=h_user).status_code == 403
        assert c.delete("/capabilities/cap-api-1", headers=h_user).status_code == 403

        h_admin = {"Authorization": f"Bearer {_token('capapi-t1', 'capapi-t1-admin')}"}
        # admin 注册 201
        r = c.post("/capabilities", json=body, headers=h_admin)
        assert r.status_code == 201, r.text
        assert r.json()["capability_id"] == "cap-api-1"
        assert r.json()["execution"] == {"adapter": "tool.fetch", "params": {"connector_id": "cn-1"}}
        # 详情 200
        assert c.get("/capabilities/cap-api-1", headers=h_admin).status_code == 200
        # 更新 200
        r = c.patch("/capabilities/cap-api-1", json={"version": "2.0.0"}, headers=h_admin)
        assert r.status_code == 200
        assert r.json()["version"] == "2.0.0"
        # 停用 200（soft-disable）
        r = c.delete("/capabilities/cap-api-1", headers=h_admin)
        assert r.status_code == 200
        assert r.json()["status"] == "deprecated"
        # 详情已停用仍可见
        assert c.get("/capabilities/cap-api-1", headers=h_admin).json()["status"] == "deprecated"
    asyncio.run(engine.dispose())


def test_capability_create_validation_422(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed_tenant(engine, "capapi-t2"))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h_admin = {"Authorization": f"Bearer {_token('capapi-t2', 'capapi-t2-admin')}"}
        # 缺 required_permissions → 422
        r = c.post(
            "/capabilities",
            json={"domain": "x", "name": "y", "type": "query", "capability_id": "cap-bad"},
            headers=h_admin,
        )
        assert r.status_code == 422, r.text
        # 非法 type → 422
        r = c.post(
            "/capabilities",
            json={
                "domain": "x",
                "name": "y",
                "type": "magic",
                "required_permissions": ["p"],
                "capability_id": "cap-bad2",
            },
            headers=h_admin,
        )
        assert r.status_code == 422, r.text
    asyncio.run(engine.dispose())


def test_capability_get_missing_404(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed_tenant(engine, "capapi-t3"))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h_admin = {"Authorization": f"Bearer {_token('capapi-t3', 'capapi-t3-admin')}"}
        assert c.get("/capabilities/nope", headers=h_admin).status_code == 404
    asyncio.run(engine.dispose())


# ── Review 修复回归（2026-08-21 #1/#3/#5/#2/#4）──────────────────────────────


async def test_create_field_length_and_charset_validated(app_engine: AsyncEngine) -> None:
    """review #1/#3：长度/字符校验 422 化（不再 DB DataError → 500）。"""
    # capability_id 超长
    with pytest.raises(ValueError, match="长度"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="d",
            name="n",
            type="query",
            required_permissions=["p"],
            capability_id="c" * 100,
        )
    # capability_id 字符白名单（XSS/SQL 注入面根治）
    with pytest.raises(ValueError, match="小写字母"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="d",
            name="n",
            type="query",
            required_permissions=["p"],
            capability_id="x');alert(1);//",
        )
    # version 超长（DDL VARCHAR(16)）
    with pytest.raises(ValueError, match="长度"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="d",
            name="n",
            type="query",
            required_permissions=["p"],
            version="9" * 30,
            capability_id="cap-vlen",
        )
    # domain 超长（DDL VARCHAR(64)）
    with pytest.raises(ValueError, match="长度"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="d" * 100,
            name="n",
            type="query",
            required_permissions=["p"],
            capability_id="cap-dlen",
        )
    # 空域名
    with pytest.raises(ValueError, match="不能为空"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="  ",
            name="n",
            type="query",
            required_permissions=["p"],
            capability_id="cap-empty",
        )


async def test_create_duplicate_raises_conflict(app_engine: AsyncEngine) -> None:
    """review #5：重复创建 → CapabilityConflictError（端点 409），且并发安全由 ON CONFLICT 保证。"""
    from earp_server.capability.service import CapabilityConflictError

    await cap_service.create_capability(
        app_engine,
        TENANT_A,
        domain="d",
        name="n",
        type="query",
        required_permissions=["p"],
        capability_id="cap-dup",
    )
    with pytest.raises(CapabilityConflictError, match="已存在"):
        await cap_service.create_capability(
            app_engine,
            TENANT_A,
            domain="d",
            name="n",
            type="query",
            required_permissions=["p"],
            capability_id="cap-dup",
        )


async def test_auto_generated_id_never_exceeds_limit(app_engine: AsyncEngine) -> None:
    """自动生成 id 截断到安全长度（超长 name/domain 不再 500）。"""
    cap = await cap_service.create_capability(
        app_engine,
        TENANT_A,
        domain="d",
        name="很长的能力名称" * 30,
        type="query",
        required_permissions=["p"],
    )
    assert len(cap["capability_id"]) <= 64


def test_capability_crud_http_semantics(migrated: str, app_url: str) -> None:
    """review 修复 HTTP 语义：重复创建 409 / 长度校验 422 / legacy 无 body POST 兼容。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed_tenant(engine, "capapi-t4"))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h_admin = {"Authorization": f"Bearer {_token('capapi-t4', 'capapi-t4-admin')}"}
        body = {
            "domain": "equipment",
            "name": "q",
            "type": "query",
            "required_permissions": ["alarm:read"],
            "capability_id": "cap-t4",
        }
        assert c.post("/capabilities", json=body, headers=h_admin).status_code == 201
        # 重复创建 → 409（非 422/500）
        r = c.post("/capabilities", json=body, headers=h_admin)
        assert r.status_code == 409, r.text
        # 超长 capability_id → 422（非 500）
        r = c.post(
            "/capabilities",
            json={**body, "capability_id": "c" * 100},
            headers=h_admin,
        )
        assert r.status_code == 422, r.text
        # 恶意 capability_id → 422（字符白名单）
        r = c.post(
            "/capabilities",
            json={**body, "capability_id": "x');alert(1);//"},
            headers=h_admin,
        )
        assert r.status_code == 422, r.text
        # legacy 无 body POST → 201 seed 语义（老 Register Demo 按钮兼容路径，锁住行为）
        r = c.post("/capabilities", headers=h_admin)
        assert r.status_code == 201
        assert r.json() == {"capability_id": "cap-demo-echo", "status": "registered"}
    asyncio.run(engine.dispose())


def test_capability_detail_role_visibility(migrated: str, app_url: str) -> None:
    """review #4：详情端点角色可见性 —— 无权能力 → 404（不暴露存在性），admin 可见。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed_tenant(engine, "capapi-t5"))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h_admin = {"Authorization": f"Bearer {_token('capapi-t5', 'capapi-t5-admin')}"}
        h_view = {"Authorization": f"Bearer {_token('capapi-t5', 'capapi-t5-view')}"}
        r = c.post(
            "/capabilities",
            json={
                "domain": "equipment",
                "name": "q",
                "type": "query",
                "required_permissions": ["alarm:read"],
                "capability_id": "cap-t5",
            },
            headers=h_admin,
        )
        assert r.status_code == 201
        # viewer 无 alarm:read → 列表不可见（discover 角色过滤）
        listing = c.get("/capabilities", headers=h_view).json()
        assert all(item["capability_id"] != "cap-t5" for item in listing)
        # 详情 → 404（不暴露存在性；不再回全量声明含 execution.params）
        r = c.get("/capabilities/cap-t5", headers=h_view)
        assert r.status_code == 404, r.text
        # admin（is_admin 豁免）→ 200 全量声明可见
        r = c.get("/capabilities/cap-t5", headers=h_admin)
        assert r.status_code == 200
        assert r.json()["execution"] == {}
    asyncio.run(engine.dispose())


async def test_discover_no_role_branch_returns_declared_columns(app_engine: AsyncEngine) -> None:
    """review #6：discover 六个 SELECT 分支统一 —— role_id=None 路径也返回
    required_permissions / execution / status（前端列表不因分支不同而静默缺列）。"""
    from earp_server.capability.registry import discover

    rows = await discover(app_engine, TENANT_A, role_id=None)
    assert rows, "seeded capabilities expected"
    for r in rows:
        assert "required_permissions" in r, f"missing column in discover(no role): {sorted(r)}"
        assert "execution" in r
        assert "status" in r
