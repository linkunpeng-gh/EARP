"""M3 中台 importer — connector_configs 管理（数据源注册的前置设施）。

connector_configs（0001 建表）此前零代码引用——M3 补最小 CRUD：
REST/DB 取数 adapter（data_adapter.py）的连接配置载体（A2/B3/C1 消费）。

配置加密复用 credential_crypto（AES-256-GCM），存 config_payload JSONB
（0001 的 config_ciphertext BYTEA 从未写入，保留不动）；列表/详情一律脱敏
（只回 credential_masked 标记，不泄露凭据/URL——2026-08-18 模型配置门禁先例）。

一期支持 adapter_type: rest | db（A3 数据契约规范定义各自 config 字段）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra import credential_crypto
from earp_server.infra.db import tenant_session

logger = logging.getLogger(__name__)

SUPPORTED_ADAPTER_TYPES = ("rest", "db")

# connector_configs（0001）无 updated_at 列——只有 created_at
_COLS = "connector_id, tenant_id, adapter_type, config_payload, status, created_at"


def _public(row) -> dict:
    """脱敏视图——不泄露配置明文（凭据/URL），只给 masked 标记。"""
    return {
        "connector_id": row["connector_id"],
        "adapter_type": row["adapter_type"],
        "status": row["status"],
        "config": credential_crypto.masked(row["config_payload"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def create_connector(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    connector_id: str | None = None,
    adapter_type: str,
    config: dict,
    status: str = "active",
) -> dict | None:
    """注册 connector：配置加密落库 config_payload。connector_id 已存在 → None（调用方 409）。"""
    if adapter_type not in SUPPORTED_ADAPTER_TYPES:
        raise ValueError(f"adapter_type must be one of {SUPPORTED_ADAPTER_TYPES}")
    cid = connector_id or f"cn-{uuid.uuid4().hex[:12]}"
    payload = credential_crypto.encrypt(config or {})
    async with tenant_session(engine, tenant_id) as session:
        exists = await session.execute(
            text("SELECT 1 FROM connector_configs WHERE connector_id = :cid AND tenant_id = :tid"),
            {"cid": cid, "tid": tenant_id},
        )
        if exists.first():
            return None
        row = await session.execute(
            text(
                f"INSERT INTO connector_configs (connector_id, tenant_id, adapter_type, "
                f"config_payload, status) VALUES (:cid, :tid, :atype, :payload, :status) "
                f"RETURNING {_COLS}"
            ),
            {"cid": cid, "tid": tenant_id, "atype": adapter_type,
             "payload": __import__("json").dumps(payload), "status": status},
        )
        return _public(row.mappings().first())


async def list_connectors(engine: AsyncEngine, tenant_id: str) -> list[dict]:
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(f"SELECT {_COLS} FROM connector_configs WHERE tenant_id = :tid ORDER BY created_at"),
            {"tid": tenant_id},
        )
        return [_public(r) for r in rows.mappings()]


async def get_connector(engine: AsyncEngine, tenant_id: str, connector_id: str) -> dict | None:
    async with tenant_session(engine, tenant_id) as session:
        row = await session.execute(
            text(f"SELECT {_COLS} FROM connector_configs WHERE connector_id = :cid AND tenant_id = :tid"),
            {"cid": connector_id, "tid": tenant_id},
        )
        r = row.mappings().first()
        return _public(r) if r else None


async def update_connector(
    engine: AsyncEngine,
    tenant_id: str,
    connector_id: str,
    *,
    config: dict | None = None,
    status: str | None = None,
) -> dict | None:
    """更新 connector：config 传则重加密覆盖；status 传则更新。不存在 → None（调用方 404）。"""
    sets: list[str] = []
    params: dict = {"cid": connector_id, "tid": tenant_id}
    if config is not None:
        payload = credential_crypto.encrypt(config)
        sets.append("config_payload = :payload")
        params["payload"] = __import__("json").dumps(payload)
    if status is not None:
        sets.append("status = :status")
        params["status"] = status
    if not sets:
        return await get_connector(engine, tenant_id, connector_id)
    async with tenant_session(engine, tenant_id) as session:
        row = await session.execute(
            text(
                f"UPDATE connector_configs SET {', '.join(sets)} "
                f"WHERE connector_id = :cid AND tenant_id = :tid RETURNING {_COLS}"
            ),
            params,
        )
        r = row.mappings().first()
        return _public(r) if r else None


async def delete_connector(engine: AsyncEngine, tenant_id: str, connector_id: str) -> bool:
    """删除 connector。被 import_rules 引用 → False（调用方 409，防悬空数据源）。"""
    async with tenant_session(engine, tenant_id) as session:
        ref = await session.execute(
            text("SELECT 1 FROM import_rules WHERE connector_id = :cid AND tenant_id = :tid LIMIT 1"),
            {"cid": connector_id, "tid": tenant_id},
        )
        if ref.first():
            return False
        res = await session.execute(
            text(
                "DELETE FROM connector_configs WHERE connector_id = :cid AND tenant_id = :tid "
                "RETURNING connector_id"
            ),
            {"cid": connector_id, "tid": tenant_id},
        )
        return res.mappings().first() is not None


async def decrypt_config(engine: AsyncEngine, tenant_id: str, connector_id: str) -> dict:
    """内部用：解密 connector 配置（data_adapter 消费）。不存在/解密失败 → {}（调用方兜底）。"""
    async with tenant_session(engine, tenant_id) as session:
        row = await session.execute(
            text(
                "SELECT adapter_type, config_payload FROM connector_configs "
                "WHERE connector_id = :cid AND tenant_id = :tid"
            ),
            {"cid": connector_id, "tid": tenant_id},
        )
        r = row.mappings().first()
    if not r:
        return {}
    payload = r["config_payload"] or {}
    cfg = credential_crypto.decrypt(payload) if isinstance(payload, dict) else {}
    cfg.setdefault("adapter_type", r["adapter_type"])
    return cfg
