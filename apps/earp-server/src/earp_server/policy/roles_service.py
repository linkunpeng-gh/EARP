"""Roles 管理服务（tech-debt #9）：CRUD + Admin 全权限通用机制 + 权限门禁。

通用机制（读侧，替代 seed 特判）：`is_admin` 角色跳过 data_domain_access 域过滤
（全权限）——新建 DD 无需同步任何角色（seed_demo_tenant 特判移除）。其余角色
按 data_domain_access 白名单过滤（fail-closed：角色缺失/空访问 → 无权限）。

`role_domain_access` 接收 **SQLAlchemy AsyncConnection**（非 engine）——knowledge.routing
在既有事务内调用（P2 先例：routing 原内联实现镜像本函数）；policy_service /
capability_query 自行开连接并 SET LOCAL 后复用同一实现，消除三处重复。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

_DATA_SCOPES = ("self", "department", "org", "all")


async def role_domain_access(
    conn, tenant_id: str, role_id: str, requested: list[str]
) -> set[str]:
    """角色可用数据域集合（requested 的子集）。

    is_admin → 全部 requested（全权限通用机制）；角色缺失 → 空集（fail-closed）。
    """
    if not requested:
        return set()
    row = await conn.execute(
        text(
            "SELECT is_admin, data_domain_access FROM roles "
            "WHERE role_id = :rid AND tenant_id = :tid"
        ),
        {"rid": role_id, "tid": tenant_id},
    )
    r = row.fetchone()
    if r is None:
        return set()
    if r.is_admin:
        return set(requested)
    access_list = r.data_domain_access or []
    allowed = {entry["data_domain_id"] for entry in access_list if "data_domain_id" in entry}
    return {did for did in requested if did in allowed}

async def check_permission(
    engine, tenant_id: str, role_id: str, permission: str
) -> bool:
    """角色门禁：is_admin 或 permissions 含该权限串（审批人角色门禁等通用检查）。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT is_admin, permissions FROM roles WHERE role_id = :rid AND tenant_id = :tid"),
            {"rid": role_id, "tid": tenant_id},
        )
        r = row.fetchone()
        if r is None:
            return False
        return bool(r.is_admin) or permission in (r.permissions or [])


async def is_admin_role(engine, tenant_id: str, role_id: str) -> bool:
    """管理端门禁（2026-08-18 越权修复）：仅 is_admin 角色可执行管理操作
    （角色 CRUD / 数据域变更 / 模型配置变更）。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT is_admin FROM roles WHERE role_id = :rid AND tenant_id = :tid"),
            {"rid": role_id, "tid": tenant_id},
        )
        r = row.fetchone()
        return bool(r and r.is_admin)


async def list_roles(engine, tenant_id: str) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT role_id, name, permissions, data_scope, data_domain_access, is_admin, "
                "created_at FROM roles WHERE tenant_id = :tid ORDER BY (is_admin) DESC, created_at"
            ),
            {"tid": tenant_id},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def get_role(engine, tenant_id: str, role_id: str) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text(
                "SELECT role_id, name, permissions, data_scope, data_domain_access, is_admin, "
                "created_at FROM roles WHERE role_id = :rid AND tenant_id = :tid"
            ),
            {"rid": role_id, "tid": tenant_id},
        )
        r = row.fetchone()
        return dict(r._mapping) if r else None


async def _validate_domain_access(engine, tenant_id: str, access: list[dict] | None) -> list[dict]:
    """data_domain_access ⊆ 租户 active DD（fail-closed 安全校验，防幽灵域引用）。"""
    access = access or []
    wanted = {str(d.get("data_domain_id")) for d in access if d.get("data_domain_id")}
    if not wanted:
        return []
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT data_domain_id FROM data_domains "
                "WHERE tenant_id = :tid AND status = 'active'"
            ),
            {"tid": tenant_id},
        )
        active = {r.data_domain_id for r in rows.fetchall()}
    unknown = wanted - active
    if unknown:
        raise ValueError(f"data_domain_access 含不存在/非 active 数据域: {sorted(unknown)}")
    return [{"data_domain_id": did} for did in sorted(wanted)]


async def create_role(
    engine,
    tenant_id: str,
    *,
    name: str,
    role_id: str | None = None,
    permissions: list[str] | None = None,
    data_scope: str = "self",
    data_domain_access: list[dict] | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("角色名称不能为空")
    if data_scope not in _DATA_SCOPES:
        raise ValueError(f"非法 data_scope: {data_scope}（可选 {_DATA_SCOPES}）")
    rid = role_id or f"r-{uuid.uuid4().hex[:10]}"
    if await get_role(engine, tenant_id, rid) is not None:
        raise ValueError(f"角色已存在: {rid}")
    dd_access = await _validate_domain_access(engine, tenant_id, data_domain_access)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        try:
            await conn.execute(
                text(
                    "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                    "data_domain_access, is_admin) VALUES (:rid, :tid, :name, :perms, :scope, "
                    ":ddacc, :adm) ON CONFLICT (role_id) DO NOTHING"
                ),
                {
                    "rid": rid,
                    "tid": tenant_id,
                    "name": name.strip(),
                    "perms": permissions or [],
                    "scope": data_scope,
                    "ddacc": json.dumps(dd_access),
                    "adm": is_admin,
                },
            )
        except Exception as e:
            raise ValueError(f"角色创建失败: {e}") from e
        await conn.commit()
    got = await get_role(engine, tenant_id, rid)
    if got is None:
        raise ValueError(f"角色已存在: {rid}")
    return got


async def update_role(
    engine,
    tenant_id: str,
    role_id: str,
    *,
    name: str | None = None,
    permissions: list[str] | None = None,
    data_scope: str | None = None,
    data_domain_access: list[dict] | None = None,
    is_admin: bool | None = None,
) -> dict[str, Any] | None:
    existing = await get_role(engine, tenant_id, role_id)
    if existing is None:
        return None
    if name is not None and not name.strip():
        raise ValueError("角色名称不能为空")
    if data_scope is not None and data_scope not in _DATA_SCOPES:
        raise ValueError(f"非法 data_scope: {data_scope}（可选 {_DATA_SCOPES}）")
    dd_access = None
    if data_domain_access is not None:
        dd_access = await _validate_domain_access(engine, tenant_id, data_domain_access)

    sets: list[str] = []
    params: dict[str, Any] = {"rid": role_id, "tid": tenant_id}
    if name is not None:
        sets.append("name = :name")
        params["name"] = name.strip()
    if permissions is not None:
        sets.append("permissions = :perms")
        params["perms"] = permissions
    if data_scope is not None:
        sets.append("data_scope = :scope")
        params["scope"] = data_scope
    if dd_access is not None:
        sets.append("data_domain_access = :ddacc")
        params["ddacc"] = json.dumps(dd_access)
    if is_admin is not None:
        # 最后一名 admin 不可降级（避免租户锁死）
        if not is_admin and existing["is_admin"]:
            admins = await _count_admins(engine, tenant_id)
            if admins <= 1:
                raise ValueError("至少保留一名 admin 角色（不能取消最后一名 admin）")
        sets.append("is_admin = :adm")
        params["adm"] = is_admin

    if not sets:
        return existing
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                f"UPDATE roles SET {', '.join(sets)} "
                "WHERE role_id = :rid AND tenant_id = :tid"
            ),
            params,
        )
        await conn.commit()
    return await get_role(engine, tenant_id, role_id)


async def delete_role(engine, tenant_id: str, role_id: str) -> bool:
    existing = await get_role(engine, tenant_id, role_id)
    if existing is None:
        return False
    if existing["is_admin"]:
        admins = await _count_admins(engine, tenant_id)
        if admins <= 1:
            raise ValueError("不能删除最后一名 admin 角色")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text("DELETE FROM roles WHERE role_id = :rid AND tenant_id = :tid"),
            {"rid": role_id, "tid": tenant_id},
        )
        await conn.commit()
    return True


async def _count_admins(engine, tenant_id: str) -> int:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT count(*) AS n FROM roles WHERE tenant_id = :tid AND is_admin"),
            {"tid": tenant_id},
        )
        return int(row.scalar() or 0)
