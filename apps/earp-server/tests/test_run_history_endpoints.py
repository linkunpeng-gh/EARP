"""运行历史查询端点测试（tech-debt #17 Task 3，D4）。

覆盖：应用维度分页 / 会话维度展开 / 权限（非 admin 按 chat_app 可见性过滤——restricted
白名单外 404）/ 不存在 404 / admin 全可见。写入侧（终态落 trace）由 Task 2 覆盖。
"""

from __future__ import annotations

import asyncio
import uuid

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation import flow_runs
from earp_server.conversation.chat_app_service import create_chat_app, publish_chat_app
from earp_server.infra.db import tenant_session
from earp_server.main import create_app

SECRET = "earp-dev-secret-change-in-production"
TENANT = "runhist-ep-t1"
ROLE_ADMIN = "r-runhist-admin"
ROLE_VIEW = "r-runhist-view"
TRACE = [
    {"node_id": "start", "status": "completed", "branch": None, "input": None, "output": {}, "error": None,
     "error_code": None, "latency_ms": 1},
    {"node_id": "l1", "status": "completed", "branch": None, "input": {"q": "hi"}, "output": {"text": "ok"},
     "error": None, "error_code": None, "latency_ms": 12},
]


def _token(role_id: str) -> str:
    return jwt.encode(
        {"sub": "u-seed", "tenant_id": TENANT, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


async def _seed(engine: AsyncEngine, *, restricted: bool = False) -> tuple[str, str, str]:
    """建应用（+发布，access_mode 可选 restricted）+ 角色 + 用户 + 会话 + 一条终态 run。"""
    async with tenant_session(engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, is_admin) "
                "VALUES (:ra, :t, 'Admin', '{}', 'all', TRUE), (:rv, :t, 'View', '{}', 'all', FALSE) "
                "ON CONFLICT (role_id) DO NOTHING"
            ),
            {"ra": ROLE_ADMIN, "rv": ROLE_VIEW, "t": TENANT},
        )
        await session.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES ('u-seed', :t, 'seed', NULL) ON CONFLICT (user_id) DO NOTHING"
            ),
            {"t": TENANT},
        )
    app = await create_chat_app(engine, TENANT, "u-seed", "运行历史端点应用")
    await publish_chat_app(engine, TENANT, "u-seed", app["chat_app_id"], category="财务")
    app_id = app["chat_app_id"]
    if restricted:
        async with tenant_session(engine, TENANT) as session:
            await session.execute(
                text("UPDATE chat_apps SET access_mode = 'restricted' WHERE chat_app_id = :a"), {"a": app_id}
            )
            await session.execute(
                text(
                    "INSERT INTO app_role_access (chat_app_id, role_id, tenant_id) "
                    "VALUES (:a, :ra, :t) ON CONFLICT DO NOTHING"
                ),
                {"a": app_id, "ra": ROLE_VIEW, "t": TENANT},
            )
    conv_id = f"conv-{uuid.uuid4().hex[:10]}"
    async with tenant_session(engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id, title, chat_app_id) "
                "VALUES (:c, :t, 'u-seed', '运行历史会话', :a)"
            ),
            {"c": conv_id, "t": TENANT, "a": app_id},
        )
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    await flow_runs.create_run(
        engine, TENANT, execution_id=run_id, chat_app_id=app_id, conversation_id=conv_id,
        flow_input={"query": "q"},
    )
    await flow_runs.finish_run(engine, TENANT, run_id, status="completed", trace=TRACE)
    return app_id, conv_id, run_id


def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def test_app_dimension_runs_pagination_and_visibility(migrated: str, app_url: str) -> None:
    """应用维度：admin/白名单角色可见 trace；白名单外角色 404；不存在应用 404。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id, _, run_id = asyncio.run(_seed(engine, restricted=True))
    app = _make_app(app_url)
    with TestClient(app) as c:
        url = f"/chat_apps/{app_id}/runs"
        # 白名单角色（r-runhist-view）→ 200 + trace
        resp = c.get(url, headers={"Authorization": f"Bearer {_token(ROLE_VIEW)}"})
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["execution_id"] == run_id
        assert rows[0]["status"] == "completed"
        assert rows[0]["trace"] == TRACE
        assert "node_state" not in rows[0]  # 列表摘要

        # 白名单外角色（伪造非 admin 角色）→ 404（应用不可见，不暴露存在性）
        outsider = jwt.encode(
            {"sub": "u-x", "tenant_id": TENANT, "role_id": "r-none", "exp": 9999999999},
            SECRET, algorithm="HS256",
        )
        assert c.get(url, headers={"Authorization": f"Bearer {outsider}"}).status_code == 404
        # admin → 200
        assert c.get(url, headers={"Authorization": f"Bearer {_token(ROLE_ADMIN)}"}).status_code == 200
        # 不存在应用 → 404
        assert (
            c.get("/chat_apps/app-nope/runs", headers={"Authorization": f"Bearer {_token(ROLE_ADMIN)}"}).status_code
            == 404
        )
    asyncio.run(engine.dispose())


def test_conversation_dimension_runs(migrated: str, app_url: str) -> None:
    """会话维度：admin 可见完整 run；不可见会话 404。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id, conv_id, _ = asyncio.run(_seed(engine, restricted=True))
    app = _make_app(app_url)
    with TestClient(app) as c:
        url = f"/conversations/{conv_id}/runs"
        # admin → 200 + trace
        resp = c.get(url, headers={"Authorization": f"Bearer {_token(ROLE_ADMIN)}"})
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["chat_app_id"] == app_id
        assert rows[0]["trace"] == TRACE
        # 白名单外角色 → 404（会话归属应用不可见）
        outsider = jwt.encode(
            {"sub": "u-x", "tenant_id": TENANT, "role_id": "r-none", "exp": 9999999999},
            SECRET, algorithm="HS256",
        )
        assert c.get(url, headers={"Authorization": f"Bearer {outsider}"}).status_code == 404
        # 不存在会话 → 404
        assert (
            c.get(
                "/conversations/conv-nope/runs", headers={"Authorization": f"Bearer {_token(ROLE_ADMIN)}"}
            ).status_code
            == 404
        )
    asyncio.run(engine.dispose())


def test_open_app_runs_visible_to_all(migrated: str, app_url: str) -> None:
    """access_mode=open：任意非 admin 角色可见运行历史。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id, _, _ = asyncio.run(_seed(engine, restricted=False))
    app = _make_app(app_url)
    with TestClient(app) as c:
        outsider = jwt.encode(
            {"sub": "u-x", "tenant_id": TENANT, "role_id": "r-anyone", "exp": 9999999999},
            SECRET, algorithm="HS256",
        )
        resp = c.get(f"/chat_apps/{app_id}/runs", headers={"Authorization": f"Bearer {outsider}"})
        assert resp.status_code == 200, resp.text
        assert resp.json()[0]["trace"] == TRACE
    asyncio.run(engine.dispose())
