"""应用中心：应用级使用权限 service（角色×应用矩阵，白名单语义 + fail-closed）。

设计：docs/superpowers/specs/2026-08-24-agent-center-design.md §3.3/§4（D2/D3）。

- `chat_apps.access_mode` 为权威开关：open（默认，所有人可见可运行）/ restricted（白名单）。
- `app_role_access` 仅存 restricted 应用的授权行；role FK ON DELETE CASCADE。
- is_admin 角色始终可见可运行（沿用 roles_service 通用机制）。
- fail-closed：restricted + 无授权行 → 非 admin 均不可访问；restricted + roles=[] 为合法防御态。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import CloudEvent
from earp_server.policy.roles_service import is_admin_role

_MODES = ("open", "restricted")


async def _audit(bus, tenant_id: str, user_id: str, chat_app_id: str, extra: dict | None = None) -> None:
    if bus is None:
        return
    bus.publish(
        CloudEvent(
            type="earp.app_access.updated",
            source="earp-server/policy",
            tenant_id=tenant_id,
            data={"entity_type": "chat_app", "entity_id": chat_app_id, "user_id": user_id, **(extra or {})},
        )
    )


async def get_app_access(engine: AsyncEngine, tenant_id: str, chat_app_id: str) -> dict[str, Any] | None:
    """返回 {mode, roles:[{role_id,name}]}；chat_app 不存在返回 None。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        app = (
            await conn.execute(
                text("SELECT access_mode FROM chat_apps WHERE chat_app_id = :id AND tenant_id = :tid"),
                {"id": chat_app_id, "tid": tenant_id},
            )
        ).first()
        if app is None:
            return None
        rows = await conn.execute(
            text(
                "SELECT ar.role_id, r.name AS role_name "
                "FROM app_role_access ar LEFT JOIN roles r ON r.role_id = ar.role_id AND r.tenant_id = ar.tenant_id "
                "WHERE ar.chat_app_id = :id AND ar.tenant_id = :tid"
            ),
            {"id": chat_app_id, "tid": tenant_id},
        )
        return {
            "chat_app_id": chat_app_id,
            "mode": app[0],
            "roles": [{"role_id": r[0], "name": r[1]} for r in rows],
        }


async def set_app_access(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    chat_app_id: str,
    *,
    mode: str,
    roles: list[str],
    bus=None,
) -> dict[str, Any]:
    """设置应用使用权限（治理中心矩阵）。

    - mode=open → 清行 + access_mode='open'
    - mode=restricted → 先清后插授权行 + access_mode='restricted'（roles 可为空 = 合法 fail-closed 防御态）
    """
    mode = (mode or "").strip().lower()
    if mode not in _MODES:
        raise ValueError(f"access_mode must be one of {_MODES}")
    roles = list(dict.fromkeys(roles or []))  # 去重保序
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        app = (
            await conn.execute(
                text("SELECT 1 FROM chat_apps WHERE chat_app_id = :id AND tenant_id = :tid"),
                {"id": chat_app_id, "tid": tenant_id},
            )
        ).first()
        if app is None:
            raise ValueError("chat_app not found")
        # 校验 roles 存在且非 admin（矩阵不授权 admin 角色——admin 天然兜底）
        if roles:
            valid = {
                r[0]
                for r in await conn.execute(
                    text("SELECT role_id FROM roles WHERE tenant_id = :tid AND role_id = ANY(:rids) AND NOT is_admin"),
                    {"tid": tenant_id, "rids": roles},
                )
            }
            missing = [r for r in roles if r not in valid]
            if missing:
                raise ValueError(f"角色不存在或为 admin：{missing}")
        await conn.execute(
            text(
                "UPDATE chat_apps SET access_mode = :mode, updated_at = now() "
                "WHERE chat_app_id = :id AND tenant_id = :tid"
            ),
            {"mode": mode, "id": chat_app_id, "tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM app_role_access WHERE chat_app_id = :id AND tenant_id = :tid"),
            {"id": chat_app_id, "tid": tenant_id},
        )
        if mode == "restricted":
            for rid in roles:
                await conn.execute(
                    text(
                        "INSERT INTO app_role_access (chat_app_id, role_id, tenant_id) VALUES (:id, :rid, :tid) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"id": chat_app_id, "rid": rid, "tid": tenant_id},
                )
        await conn.commit()
    await _audit(bus, tenant_id, user_id, chat_app_id, {"mode": mode, "roles": roles})
    return await get_app_access(engine, tenant_id, chat_app_id) or {
        "chat_app_id": chat_app_id,
        "mode": mode,
        "roles": [],
    }


async def is_is_admin(engine: AsyncEngine, tenant_id: str, role_id: str) -> bool:
    """薄包装：判定角色是否管理员（可见性过滤用）。"""
    return await is_admin_role(engine, tenant_id, role_id)
