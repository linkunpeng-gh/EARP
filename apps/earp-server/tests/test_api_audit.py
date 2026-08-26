"""对外 API 审计 + last_used_at 测试（tech-debt #18 Task 4，D6）。

覆盖：API 调用后 audit_logs 可查到 earp.api.chat.{started,completed,failed}（含
app_id/key_id/http_status/耗时；flow 完成带 execution_id）+ api_keys.last_used_at 已更新
（端点完成时一次，防热路径写放大）；被拒调用（未发布 404）不发审计事件、不 touch。

注意：in-process EventBus 为 fire-and-forget（asyncio.create_task）——audit handler 跑在
TestClient 的 event loop 上，with 块退出即随 lifespan 销毁。轮询必须放在 with 块内。
每测试独立租户，避免跨测试事件串扰。
"""

from __future__ import annotations

import asyncio
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation.chat_app_service import create_chat_app, publish_chat_app
from earp_server.gateway import api_keys as keys
from earp_server.infra.db import tenant_session
from earp_server.main import create_app

SECRET = "earp-dev-secret-change-in-production"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def _approval_flow() -> dict:
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


async def _seed_flow_app(engine: AsyncEngine, tenant: str, name: str, publish: bool = True) -> str:
    app = await create_chat_app(engine, tenant, "u-seed", name, orchestration="flow", flow_schema=_approval_flow())
    if publish:
        await publish_chat_app(engine, tenant, "u-seed", app["chat_app_id"], category="财务")
    return app["chat_app_id"]


async def _wait_audit(engine: AsyncEngine, tenant: str, event_type: str, max_wait: float = 6.0) -> dict | None:
    """audit handler 为 fire-and-forget 后台任务——轮询等待落库。"""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        async with tenant_session(engine, tenant) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT detail FROM audit_logs WHERE tenant_id = :t AND event_type = :e "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"t": tenant, "e": event_type},
                )
            ).fetchone()
        if row:
            detail = row[0]
            return detail if isinstance(detail, dict) else json.loads(detail)
        await asyncio.sleep(0.1)
    return None


async def _last_used(engine: AsyncEngine, tenant: str, app_id: str):
    async with tenant_session(engine, tenant) as session:
        row = (
            await session.execute(
                text("SELECT last_used_at FROM api_keys WHERE tenant_id = :t AND chat_app_id = :a"),
                {"t": tenant, "a": app_id},
            )
        ).fetchone()
    return row[0] if row else None


def _token(tenant: str) -> str:
    return jwt.encode(
        {"sub": "u-seed", "tenant_id": tenant, "role_id": "r-ep", "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def test_api_call_emits_audit_and_touches_last_used(migrated: str, app_url: str) -> None:
    """flow 挂起 202：started + completed(202) 落 audit_logs；last_used_at 已更新。"""
    tenant = "apikey-audit-t1"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed_flow_app(engine, tenant, "审计-挂起"))
    plaintext = asyncio.run(keys.create_api_key(engine, tenant, app_id, "审计密钥"))

    app = create_app(Settings(database_url=app_url, app_env="test"))
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/chat-apps/{app_id}/chat",
            json={"query": "报销审批"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 202, resp.text

        started = asyncio.run(_wait_audit(engine, tenant, "earp.api.chat.started"))
        assert started is not None, "earp.api.chat.started 未落库"
        assert started["api_key_id"] and started["chat_app_id"] == app_id
        assert started["user_id"].startswith("service:api:")
        assert started["http_status"] == 200

        completed = asyncio.run(_wait_audit(engine, tenant, "earp.api.chat.completed"))
        assert completed is not None, "earp.api.chat.completed 未落库"
        assert completed["http_status"] == 202
        assert completed["chat_app_id"] == app_id
        assert completed["api_key_id"] == started["api_key_id"]
        assert isinstance(completed.get("elapsed_ms"), int)
        assert completed.get("execution_id"), "flow 完成事件应带 execution_id 关联"

        last_used = asyncio.run(_last_used(engine, tenant, app_id))
        assert last_used is not None, "last_used_at 未更新（端点完成时应 touch 一次）"
    asyncio.run(engine.dispose())


def test_failed_call_emits_failed_event(migrated: str, app_url: str, monkeypatch) -> None:
    """分发失败（flow 执行错误 → 422）：earp.api.chat.failed + last_used_at 仍 touch。"""
    import earp_server.main as main_mod
    from earp_server.conversation.chat_service import ChatError

    async def _boom(*args, **kwargs):
        raise ChatError("连接失败")

    monkeypatch.setattr(main_mod, "flow_chat", _boom)

    tenant = "apikey-audit-t2"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed_flow_app(engine, tenant, "审计-失败"))
    plaintext = asyncio.run(keys.create_api_key(engine, tenant, app_id, "失败密钥"))

    app = create_app(Settings(database_url=app_url, app_env="test"))
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/chat-apps/{app_id}/chat",
            json={"query": "q"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 422, resp.text

        failed = asyncio.run(_wait_audit(engine, tenant, "earp.api.chat.failed"))
        assert failed is not None, "earp.api.chat.failed 未落库"
        assert failed["http_status"] == 422
        assert failed["chat_app_id"] == app_id
        assert failed.get("error")
        assert asyncio.run(_last_used(engine, tenant, app_id)) is not None  # finally 分支仍 touch
    asyncio.run(engine.dispose())


def test_rejected_call_no_audit_no_touch(migrated: str, app_url: str) -> None:
    """未发布 404（准入前拒绝）：不发 earp.api.* 事件、不 touch（密钥出示但未获准调用）。"""
    tenant = "apikey-audit-t3"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app_id = asyncio.run(_seed_flow_app(engine, tenant, "审计-未发布", publish=False))
    plaintext = asyncio.run(keys.create_api_key(engine, tenant, app_id, "未发布密钥"))

    app = create_app(Settings(database_url=app_url, app_env="test"))
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/chat-apps/{app_id}/chat",
            json={"query": "q"},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 404, resp.text
        # 等一拍确认无事件落库（准入前拒绝不发审计）
        assert asyncio.run(_wait_audit(engine, tenant, "earp.api.chat.started", max_wait=1.0)) is None
        assert asyncio.run(_last_used(engine, tenant, app_id)) is None
    asyncio.run(engine.dispose())
