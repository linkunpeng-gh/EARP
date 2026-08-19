"""管理端门禁（2026-08-18 越权修复）— 角色/数据域/模型配置变更仅 Admin 角色可执行。

背景（FDE 反馈）：任意登录角色（如 r3）可直接在 roles 页面修改权限（含自提 admin）。
修复：/api/roles*（router 级）+ /api/data-domains 变更 + /api/model-configs 变更
+ /api/system-model-settings 均要求 is_admin（403）；只读端点保持开放。
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.main import create_app

SECRET = "earp-dev-secret-change-in-production"


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    # role_id 单列主键（debt #7 模式）：固定语义 id 跨测试租户冲突 → migration 角色全局 purge
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
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
        await conn.commit()


def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def _token(tid: str, role_id: str) -> str:
    return jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def test_roles_api_admin_only(migrated: str, app_url: str) -> None:
    """/api/roles* 仅 admin：非 admin 列表/新建/改/删全 403；admin 正常。"""
    tid = "ag-t1"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))

    app = _make_app(app_url)
    with TestClient(app) as c:
        # 非 admin：全部 403
        h = {"Authorization": f"Bearer {_token(tid, 'r-ops')}"}
        assert c.get("/api/roles", headers=h).status_code == 403
        assert c.post("/api/roles", json={"name": "x"}, headers=h).status_code == 403
        assert c.put("/api/roles/r-admin", json={"name": "y"}, headers=h).status_code == 403
        assert c.delete("/api/roles/r-ops", headers=h).status_code == 403
        # admin：列表 200 + 新建 201
        h_a = {"Authorization": f"Bearer {_token(tid, 'r-admin')}"}
        assert c.get("/api/roles", headers=h_a).status_code == 200
        r = c.post("/api/roles", json={"name": "新角色", "role_id": "r-ag-new"}, headers=h_a)
        assert r.status_code == 201, r.text
    asyncio.run(engine.dispose())


def test_data_domain_mutations_admin_only(migrated: str, app_url: str) -> None:
    """/api/data-domains 变更仅 admin；只读列表保持开放。"""
    tid = "ag-t2"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))

    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid, 'r-ops')}"}
        assert c.get("/api/data-domains", headers=h).status_code == 200  # 只读开放
        assert c.post("/api/data-domains", json={"data_domain_id": "dd-x", "name": "X"}, headers=h).status_code == 403
        assert c.delete("/api/data-domains/dd-a", headers=h).status_code == 403
        assert c.patch("/api/data-domains/dd-a", json={"name": "改名"}, headers=h).status_code == 403
        h_a = {"Authorization": f"Bearer {_token(tid, 'r-admin')}"}
        assert c.post("/api/data-domains", json={"data_domain_id": "dd-x", "name": "X"}, headers=h_a).status_code == 201
    asyncio.run(engine.dispose())


def test_model_config_mutations_admin_only(migrated: str, app_url: str) -> None:
    """/api/model-configs 变更 + system-model-settings 仅 admin；只读开放。"""
    tid = "ag-t3"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))

    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token(tid, 'r-ops')}"}
        assert c.get("/api/model-configs", headers=h).status_code == 200
        assert (
            c.post(
                "/api/model-configs",
                json={"provider": "ollama", "model_type": "llm", "model_name": "x"},
                headers=h,
            ).status_code
            == 403
        )
        assert c.put("/api/system-model-settings", json={"llm": "cfg-1"}, headers=h).status_code == 403
        h_a = {"Authorization": f"Bearer {_token(tid, 'r-admin')}"}
        assert (
            c.post(
                "/api/model-configs",
                json={"provider": "ollama", "model_type": "llm", "model_name": "x"},
                headers=h_a,
            ).status_code
            == 201
        )
    asyncio.run(engine.dispose())
