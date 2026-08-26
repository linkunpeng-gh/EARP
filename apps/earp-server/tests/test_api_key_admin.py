"""应用「API 访问」密钥管理端点测试（tech-debt #18 Task 5，内部 JWT 管理面）。

覆盖：列表（不含 key_hash）/ 生成（明文一次返回）/ 吊销（即时生效，列表状态翻转）。
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation.chat_app_service import create_chat_app
from earp_server.main import create_app

SECRET = "earp-dev-secret-change-in-production"
TENANT = "apikey-admin-t1"


async def _seed_app(engine: AsyncEngine) -> str:
    app = await create_chat_app(engine, TENANT, "u-seed", "密钥管理测试应用")
    return app["chat_app_id"]


def _token() -> str:
    return jwt.encode(
        {"sub": "u-seed", "tenant_id": TENANT, "role_id": "r-admin", "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def test_key_management_endpoints(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed_app(engine))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {_token()}"}
        base = f"/chat_apps/{app_id}/api-keys"

        # 空列表
        resp = c.get(base, headers=h)
        assert resp.status_code == 200 and resp.json() == []

        # 生成：明文一次返回
        resp = c.post(base, json={"name": "prod-报销助手"}, headers=h)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["plaintext"].startswith("app-")
        assert len(body["plaintext"]) == len("app-") + 32

        # 列表：不含 key_hash，状态 active
        resp = c.get(base, headers=h)
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["name"] == "prod-报销助手" and rows[0]["status"] == "active"
        assert "key_hash" not in rows[0]

        # 空名称 → 422
        assert c.post(base, json={"name": "  "}, headers=h).status_code == 422

        # 吊销 → 列表状态翻转；重复吊销幂等 revoked=false
        key_id = rows[0]["api_key_id"]
        resp = c.post(f"{base}/{key_id}/revoke", headers=h)
        assert resp.status_code == 200 and resp.json()["revoked"] is True
        assert c.post(f"{base}/{key_id}/revoke", headers=h).json()["revoked"] is False
        rows = c.get(base, headers=h).json()
        assert rows[0]["status"] == "revoked"

        # 不存在的应用 → 404
        assert c.get("/chat_apps/app-nope/api-keys", headers=h).status_code == 404
    asyncio.run(engine.dispose())
