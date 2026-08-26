"""gateway 密钥鉴权分支测试（对外 API 服务 Task 2，tech-debt #18 D2）。

覆盖：app-key 放行并注入服务身份 / 吊销 401 / 非法 app-key 401 /
非 app- 前缀回 JWT 路径 / JWT 零回归 / 缺 Authorization 401。
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation.chat_app_service import create_chat_app
from earp_server.gateway import api_keys as keys
from earp_server.main import create_app

SECRET = "earp-dev-secret-change-in-production"
TENANT = "apikey-auth-t1"


async def _seed(engine: AsyncEngine) -> tuple[str, str]:
    """一个应用 + 一把密钥 → (chat_app_id, 明文)。"""
    app = await create_chat_app(engine, TENANT, "u-apikey", "鉴权测试应用")
    plaintext = await keys.create_api_key(engine, TENANT, app["chat_app_id"], "测试密钥")
    return app["chat_app_id"], plaintext


def _make_app(app_url: str):
    app = create_app(Settings(database_url=app_url, app_env="test"))

    @app.get("/test/echo-state")  # 仅测试用：回显 request.state 验证中间件注入
    async def echo_state(req: Request):
        return {
            "user_id": getattr(req.state, "user_id", None),
            "tenant_id": getattr(req.state, "tenant_id", None),
            "role_id": getattr(req.state, "role_id", None),
            "chat_app_id": getattr(req.state, "chat_app_id", None),
            "api_key_id": getattr(req.state, "api_key_id", None),
        }

    return app


def _token(tid: str, role_id: str) -> str:
    return jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def test_app_key_injects_service_identity(migrated: str, app_url: str) -> None:
    """app-key 放行：注入 tenant/chat_app/api_key_id + service 身份（D5）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id, plaintext = asyncio.run(_seed(engine))
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.get("/test/echo-state", headers={"Authorization": f"Bearer {plaintext}"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tenant_id"] == TENANT
        assert body["chat_app_id"] == app_id
        assert body["user_id"].startswith("service:api:")
        assert body["role_id"] == ""  # D5: 服务调用无角色（端点侧按应用创建者补）
        assert len(body["api_key_id"]) == 32
    asyncio.run(engine.dispose())


def test_revoked_key_returns_401(migrated: str, app_url: str) -> None:
    """吊销即时生效：verify 拿 key_id → revoke → HTTP 401。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    _, plaintext = asyncio.run(_seed(engine))

    async def _revoke() -> None:
        info = await keys.verify_api_key(engine, plaintext)
        assert info is not None
        assert await keys.revoke_api_key(engine, TENANT, info["api_key_id"]) is True

    asyncio.run(_revoke())
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.get("/test/echo-state", headers={"Authorization": f"Bearer {plaintext}"})
        assert resp.status_code == 401, resp.text
    asyncio.run(engine.dispose())


def test_invalid_app_key_returns_401(migrated: str, app_url: str) -> None:
    """app- 前缀但查表不中 → 401（密钥无中生有/跨租户猜测均不可行）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.get(
            "/test/echo-state",
            headers={"Authorization": "Bearer app-deadbeefdeadbeefdeadbeefdeadbeef"},
        )
        assert resp.status_code == 401, resp.text
    asyncio.run(engine.dispose())


def test_non_app_prefix_uses_jwt_path(migrated: str, app_url: str) -> None:
    """非 app- 前缀：不走密钥分支——非 JWT 乱串 401（JWT 解码失败），JWT 正常放行。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.get("/test/echo-state", headers={"Authorization": "Bearer not-a-jwt-token"})
        assert resp.status_code == 401, resp.text
    asyncio.run(engine.dispose())


def test_valid_jwt_zero_regression(migrated: str, app_url: str) -> None:
    """JWT 路径零改动：合法 JWT 注入原身份（sub/tenant/role 来自 token 而非密钥）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.get("/test/echo-state", headers={"Authorization": f"Bearer {_token(TENANT, 'r-x')}"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_id"] == "u1"
        assert body["tenant_id"] == TENANT
        assert body["role_id"] == "r-x"
        assert body["chat_app_id"] is None and body["api_key_id"] is None  # JWT 路径不注入密钥字段
    asyncio.run(engine.dispose())


def test_missing_authorization_401(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app = _make_app(app_url)
    with TestClient(app) as c:
        assert c.get("/test/echo-state").status_code == 401
    asyncio.run(engine.dispose())
