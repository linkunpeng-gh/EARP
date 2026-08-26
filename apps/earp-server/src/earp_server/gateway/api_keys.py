"""API 密钥 service（Dify API Access 对标，tech-debt #18，Task 1/4）。

密钥形态（D1）：`app-` 前缀 + secrets.token_hex(16)（32 hex，~128 bit 熵）；
落库仅存 `key_hash = sha256(明文)`——明文绝不落库/日志回显，本模块的
create_api_key 返回值是唯一明文出口（一次性展示后丢弃）。

- create_api_key: 生成密钥（明文仅返回一次），绑定 chat_app_id（D4 密钥即授权）
- revoke_api_key: 吊销（status=revoked），即时生效
- verify_api_key: 鉴权查表——经 public.verify_api_key SECURITY DEFINER 函数
  （RLS 鸡生蛋：租户由密钥行携带，未设 GUC 时表不可见；函数绕过 RLS，earp_app 仅 EXECUTE）
- touch_api_key: last_used_at 更新（端点完成时调用，防热路径写放大，D4/Task 4）
- list_api_keys: 按应用列密钥（前端「API 访问」页签，Task 5；永不含 key_hash）
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session

_PREFIX = "app-"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def create_api_key(engine: AsyncEngine, tenant_id: str, chat_app_id: str, name: str) -> str:
    """生成并落库密钥，返回明文（仅此一次）。chat_app 必须属于本租户（FK+RLS 兜底）。

    同步创建服务身份 users 行（D5）：会话/消息 user_id 有 FK → users，服务调用
    的 user_id=service:api:<key_id> 必须存在；吊销后保留（历史会话仍引用）。
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    async with tenant_session(engine, tenant_id) as session:
        app = await session.execute(
            text("SELECT 1 FROM chat_apps WHERE chat_app_id = :id AND tenant_id = :tid"),
            {"id": chat_app_id, "tid": tenant_id},
        )
        if app.fetchone() is None:
            raise ValueError("chat app not found or not owned by tenant")
        plaintext = f"{_PREFIX}{secrets.token_hex(16)}"
        api_key_id = uuid.uuid4().hex
        await session.execute(
            text(
                "INSERT INTO api_keys (api_key_id, tenant_id, chat_app_id, name, key_hash, status) "
                "VALUES (:id, :tid, :app_id, :name, :hash, 'active')"
            ),
            {"id": api_key_id, "tid": tenant_id, "app_id": chat_app_id, "name": name, "hash": _hash(plaintext)},
        )
        service_user = f"service:api:{api_key_id}"
        await session.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES (:uid, :tid, :uname, NULL) ON CONFLICT (user_id) DO NOTHING"
            ),
            {"uid": service_user, "uname": service_user, "tid": tenant_id},
        )
    return plaintext


async def revoke_api_key(engine: AsyncEngine, tenant_id: str, api_key_id: str) -> bool:
    """吊销密钥（active → revoked），即时生效。返回是否真的有行被吊销。"""
    async with tenant_session(engine, tenant_id) as session:
        result = await session.execute(
            text(
                "UPDATE api_keys SET status = 'revoked' "
                "WHERE api_key_id = :id AND tenant_id = :tid AND status = 'active' "
                "RETURNING api_key_id"
            ),
            {"id": api_key_id, "tid": tenant_id},
        )
        return result.fetchone() is not None


async def verify_api_key(engine: AsyncEngine, key: str) -> dict[str, str] | None:
    """校验 Bearer app-key：命中 active 密钥 → {api_key_id, tenant_id, chat_app_id}；否则 None。

    经 SECURITY DEFINER 函数查表（migration 0033）——租户未知时 RLS 不可见，函数绕过。
    不更新 last_used_at（Task 4 由端点完成时 touch，防写放大）。
    """
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT api_key_id, tenant_id, chat_app_id, status FROM public.verify_api_key(:h)"),
            {"h": _hash(key)},
        )
        found = row.mappings().first()
    if found is None or found["status"] != "active":
        return None
    return {"api_key_id": found["api_key_id"], "tenant_id": found["tenant_id"], "chat_app_id": found["chat_app_id"]}


async def touch_api_key(engine: AsyncEngine, tenant_id: str, api_key_id: str) -> None:
    """端点完成时更新 last_used_at（单次 UPDATE，防逐 token 写放大）。"""
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text("UPDATE api_keys SET last_used_at = now() WHERE api_key_id = :id AND tenant_id = :tid"),
            {"id": api_key_id, "tid": tenant_id},
        )


async def list_api_keys(engine: AsyncEngine, tenant_id: str, chat_app_id: str) -> list[dict[str, Any]]:
    """按应用列密钥（不含 key_hash——hash 永不外泄，前端只见 name/status/last_used_at）。"""
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT api_key_id, name, status, created_at, last_used_at "
                "FROM api_keys WHERE tenant_id = :tid AND chat_app_id = :app_id "
                "ORDER BY created_at DESC"
            ),
            {"tid": tenant_id, "app_id": chat_app_id},
        )
        return [dict(r) for r in rows.mappings()]
