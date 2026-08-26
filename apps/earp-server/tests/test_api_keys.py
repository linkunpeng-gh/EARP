"""API 密钥 service 单测（对外 API 服务 Task 1，tech-debt #18）。

验证：生成/校验/吊销闭环 + 明文不可复得（仅 key_hash 落库）+ RLS 鸡生蛋与
SECURITY DEFINER 函数的边界行为（app 角色未设 GUC 时表不可见，但函数可查）。
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.conversation.chat_app_service import create_chat_app
from earp_server.gateway import api_keys as keys
from earp_server.infra.db import tenant_session

TENANT = "apikey-t1"
OTHER_TENANT = "apikey-t2"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _seed_app(engine: AsyncEngine, tenant_id: str, user_id: str = "u-apikey") -> str:
    app = await create_chat_app(engine, tenant_id, user_id, "API 测试应用")
    return app["chat_app_id"]


async def test_create_verify_cycle(app_engine: AsyncEngine) -> None:
    app_id = await _seed_app(app_engine, TENANT)
    plaintext = await keys.create_api_key(app_engine, TENANT, app_id, "测试密钥")
    assert plaintext.startswith("app-")
    assert len(plaintext) == len("app-") + 32  # app- + 32 hex

    info = await keys.verify_api_key(app_engine, plaintext)
    assert info is not None
    assert info["tenant_id"] == TENANT
    assert info["chat_app_id"] == app_id
    assert len(info["api_key_id"]) == 32


async def test_plaintext_not_recoverable(app_engine: AsyncEngine) -> None:
    """落库仅 key_hash（sha256），明文不可复得；且无明文列。"""
    app_id = await _seed_app(app_engine, TENANT)
    plaintext = await keys.create_api_key(app_engine, TENANT, app_id, "明文不可复得")
    async with tenant_session(app_engine, TENANT) as session:
        row = await session.execute(
            text("SELECT key_hash FROM api_keys WHERE chat_app_id = :app_id"),
            {"app_id": app_id},
        )
        rows = [dict(r) for r in row.mappings()]
    assert len(rows) == 1
    assert rows[0]["key_hash"] == hashlib.sha256(plaintext.encode()).hexdigest()
    assert rows[0]["key_hash"] != plaintext
    # 表结构无明文列（列清单核对——key_hash 是唯一密钥载体）
    async with tenant_session(app_engine, TENANT) as session:
        cols = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'api_keys' ORDER BY ordinal_position"
            )
        )
        names = [r[0] for r in cols.fetchall()]
    assert "key_hash" in names
    assert "plaintext" not in names and "secret" not in names and "key" not in names


async def test_create_creates_service_user_row(app_engine: AsyncEngine) -> None:
    """D5 FK 修复：会话/消息 user_id → users FK，密钥创建时同步建 service:api:<key_id> 用户行。"""
    app_id = await _seed_app(app_engine, TENANT)
    plaintext = await keys.create_api_key(app_engine, TENANT, app_id, "服务身份")
    info = await keys.verify_api_key(app_engine, plaintext)
    assert info is not None
    async with tenant_session(app_engine, TENANT) as session:
        row = await session.execute(
            text("SELECT user_id FROM users WHERE user_id = :uid"),
            {"uid": f"service:api:{info['api_key_id']}"},
        )
        assert row.fetchone() is not None


async def test_revoke_takes_effect_immediately(app_engine: AsyncEngine) -> None:
    app_id = await _seed_app(app_engine, TENANT)
    plaintext = await keys.create_api_key(app_engine, TENANT, app_id, "待吊销")
    assert await keys.verify_api_key(app_engine, plaintext) is not None

    info = await keys.verify_api_key(app_engine, plaintext)
    assert info is not None
    assert await keys.revoke_api_key(app_engine, TENANT, info["api_key_id"]) is True
    assert await keys.verify_api_key(app_engine, plaintext) is None  # 吊销即时生效
    assert await keys.revoke_api_key(app_engine, TENANT, info["api_key_id"]) is False  # 二次吊销无行


async def test_verify_garbage_key_returns_none(app_engine: AsyncEngine) -> None:
    assert await keys.verify_api_key(app_engine, "app-deadbeefdeadbeefdeadbeefdeadbeef") is None
    assert await keys.verify_api_key(app_engine, "not-an-app-key") is None


async def test_create_rejects_cross_tenant_app_and_empty_name(app_engine: AsyncEngine) -> None:
    other_app = await _seed_app(app_engine, OTHER_TENANT)
    with pytest.raises(ValueError, match="chat app not found"):
        await keys.create_api_key(app_engine, TENANT, other_app, "跨租户应拒绝")
    with pytest.raises(ValueError, match="name is required"):
        app_id = await _seed_app(app_engine, TENANT)
        await keys.create_api_key(app_engine, TENANT, app_id, "   ")


async def test_list_api_keys_hides_hash(app_engine: AsyncEngine) -> None:
    app_id = await _seed_app(app_engine, TENANT)
    await keys.create_api_key(app_engine, TENANT, app_id, "列表密钥A")
    await keys.create_api_key(app_engine, TENANT, app_id, "列表密钥B")
    rows = await keys.list_api_keys(app_engine, TENANT, app_id)
    assert len(rows) == 2
    assert all("key_hash" not in r for r in rows)
    assert {r["name"] for r in rows} == {"列表密钥A", "列表密钥B"}
    # 其它应用/租户看不到
    assert await keys.list_api_keys(app_engine, OTHER_TENANT, app_id) == []


async def test_rls_hides_table_without_tenant_guc(app_engine: AsyncEngine) -> None:
    """RLS 鸡生蛋复现：app 角色未设 GUC 时 api_keys 不可见（FORCE RLS）——
    这正是 SECURITY DEFINER 函数存在的理由（verify_api_key 在上文已证明可穿透）。"""
    app_id = await _seed_app(app_engine, TENANT)
    await keys.create_api_key(app_engine, TENANT, app_id, "RLS 证明")
    async with app_engine.connect() as conn:
        # 未设 earp.tenant_id → USING (tenant_id = NULL) 恒假 → 0 行
        count = await conn.execute(text("SELECT count(*) FROM api_keys"))
        assert int(count.scalar_one()) == 0
