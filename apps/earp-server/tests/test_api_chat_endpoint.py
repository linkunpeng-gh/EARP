"""对外 API 端点测试（tech-debt #18 Task 3，D3/D4/D5）。

覆盖：auto SSE 端点接线（stub chat_sse，形状验证）/ flow 挂起 202 → conversation_id 续调恢复 /
未发布 404 / 密钥绑定不匹配 403 / 吊销 401 / 缺密钥 401 / D5 服务角色解析（应用创建者角色或空）。
"""

from __future__ import annotations

import asyncio

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation.chat_app_service import create_chat_app, publish_chat_app
from earp_server.gateway import api_keys as keys
from earp_server.infra.db import tenant_session
from earp_server.main import _service_role, create_app

SECRET = "earp-dev-secret-change-in-production"
TENANT = "apikey-ep-t1"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def _approval_flow() -> dict:
    """start → h1(human_approval) → end（无 LLM 节点——端点级测试不依赖 Ollama）。"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            {"id": "h1", "type": "human_approval", "data": {"question": "确认派单？"}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"source": "start", "target": "h1"},
            {"source": "h1", "target": "end"},
        ],
    }


async def _seed(
    engine: AsyncEngine,
    name: str,
    *,
    orchestration: str = "auto",
    flow_schema: dict | None = None,
    publish: bool = True,
) -> str:
    """建应用（+发布）→ 返回 chat_app_id。"""
    app = await create_chat_app(
        engine, TENANT, "u-seed", name, orchestration=orchestration, flow_schema=flow_schema
    )
    app_id = app["chat_app_id"]
    if publish:
        await publish_chat_app(engine, TENANT, "u-seed", app_id, category="财务")
    return app_id


async def _create_key(engine: AsyncEngine, app_id: str) -> str:
    return await keys.create_api_key(engine, TENANT, app_id, "端点测试密钥")


def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def _token() -> str:
    return jwt.encode(
        {"sub": "u-seed", "tenant_id": TENANT, "role_id": "r-ep", "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


# ── auto SSE ─────────────────────────────────────────────────────────────────


def test_auto_sse_stream_via_api_key(migrated: str, app_url: str, monkeypatch) -> None:
    """auto 应用：Bearer app-key → SSE 流（200 + text/event-stream）。

    chat_sse 本体由 test_chat.py 以 FakeLLM 覆盖；此处 stub 仅验证端点接线
    （密钥绑定 + 已发布 + 分发到 SSE 分支 + 流式响应头）。
    """
    import earp_server.main as main_mod

    async def _stub_sse(*args, **kwargs):
        yield 'data: {"type": "token", "content": "你好"}\n\n'
        yield 'data: {"type": "done", "message_id": "m-1"}\n\n'

    monkeypatch.setattr(main_mod, "chat_sse", _stub_sse)

    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed(engine, "对外 auto 应用"))
    plaintext = asyncio.run(_create_key(engine, app_id))
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/chat-apps/{app_id}/chat",
            json={"query": "你好"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "token" in resp.text and "done" in resp.text
    asyncio.run(engine.dispose())


# ── flow：挂起 202 → 续调恢复 ────────────────────────────────────────────────


def test_flow_waiting_human_202_then_resume_completed(migrated: str, app_url: str) -> None:
    """flow 应用：human_approval 挂起 202（waiting_human + pending_node_id）→
    同 conversation_id 续调 → completed 200（命令审批在 API 调用下语义不变，D5）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed(engine, "对外 flow 审批应用", orchestration="flow", flow_schema=_approval_flow()))
    plaintext = asyncio.run(_create_key(engine, app_id))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {plaintext}"}
        first = c.post(f"/api/v1/chat-apps/{app_id}/chat", json={"query": "报销审批"}, headers=h)
        assert first.status_code == 202, first.text
        body = first.json()
        assert body["status"] == "waiting_human"
        assert body["pending_node_id"] == "h1"
        assert body["question"]
        conv_id = body["conversation_id"]

        done = c.post(
            f"/api/v1/chat-apps/{app_id}/chat",
            json={"query": "同意", "conversation_id": conv_id},
            headers=h,
        )
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "completed"
    asyncio.run(engine.dispose())


# ── 门禁：未发布 / 绑定不匹配 / 吊销 / 缺密钥 ────────────────────────────────


def test_unpublished_app_returns_404(migrated: str, app_url: str) -> None:
    """仅已发布应用可被密钥调用（D3）；draft → 404（不暴露存在性）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed(engine, "未发布应用", publish=False))
    plaintext = asyncio.run(_create_key(engine, app_id))
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/chat-apps/{app_id}/chat",
            json={"query": "hi"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 404, resp.text
    asyncio.run(engine.dispose())


def test_key_not_bound_to_path_app_returns_403(migrated: str, app_url: str) -> None:
    """密钥绑定 == 路径应用（D4）：A 的密钥调 B → 403。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_a = asyncio.run(_seed(engine, "应用A"))
    app_b = asyncio.run(_seed(engine, "应用B"))
    plaintext = asyncio.run(_create_key(engine, app_a))
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/chat-apps/{app_b}/chat",
            json={"query": "hi"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 403, resp.text
    asyncio.run(engine.dispose())


def test_revoked_key_returns_401_at_endpoint(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed(engine, "吊销测试"))
    plaintext = asyncio.run(_create_key(engine, app_id))

    async def _revoke() -> None:
        info = await keys.verify_api_key(engine, plaintext)
        assert info is not None
        assert await keys.revoke_api_key(engine, TENANT, info["api_key_id"]) is True

    asyncio.run(_revoke())
    app = _make_app(app_url)
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/chat-apps/{app_id}/chat",
            json={"query": "hi"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 401, resp.text
    asyncio.run(engine.dispose())


def test_missing_or_garbage_key_returns_401(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed(engine, "无密钥测试"))
    app = _make_app(app_url)
    with TestClient(app) as c:
        url = f"/api/v1/chat-apps/{app_id}/chat"
        assert c.post(url, json={"query": "hi"}).status_code == 401
        assert (
            c.post(
                url,
                json={"query": "hi"},
                headers={"Authorization": "Bearer app-deadbeefdeadbeefdeadbeefdeadbeef"},
            ).status_code
            == 401
        )
    asyncio.run(engine.dispose())


# ── D5：服务角色解析（应用创建者当前角色或空） ────────────────────────────────


async def test_service_role_resolution(app_engine: AsyncEngine) -> None:
    """created_by 有 current_role_id → 取其角色；无 join / 无 created_by → 空。"""
    # 1) created_by 有 join
    app = await create_chat_app(app_engine, TENANT, "creator-u1", "角色解析应用")
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_account_joins (tenant_id, user_id, role_ids, current_role_id) "
                "VALUES (:t, 'creator-u1', ARRAY['r-creator'], 'r-creator') "
                "ON CONFLICT (tenant_id, user_id) DO UPDATE SET current_role_id = 'r-creator'"
            ),
            {"t": TENANT},
        )
    assert await _service_role(app_engine, TENANT, app) == "r-creator"

    # 2) created_by 无 join → 空
    app2 = await create_chat_app(app_engine, TENANT, "no-join-user", "无角色应用")
    assert await _service_role(app_engine, TENANT, app2) == ""

    # 3) 无 created_by → 空（不触库）
    assert await _service_role(app_engine, TENANT, {"created_by": None}) == ""
