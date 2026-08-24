"""业务分类词表 service（应用中心：租户级预设词表）。

设计：docs/superpowers/specs/2026-08-24-agent-center-design.md §3.2/§4。

- category 存 `app_categories.name` 快照于 chat_apps（非 id）；rename 需同事务同步 chat_apps。
- 默认词表按租户惰性 seed（`ensure_default_categories`）——保证任意租户（含测试/新建租户）发布时
  必有基线分类可选，满足「发布校验分类必填」。
- RLS 租户隔离；分类行仅租户内可见。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import CloudEvent

# 设计 §R20 / §3.2：种子词表
DEFAULT_CATEGORIES = ["财务", "人事", "客服", "IT 运维", "数据分析", "其他"]


def _category_id() -> str:
    return f"cat-{uuid.uuid4().hex[:10]}"


def _audit(bus, event_type: str, tenant_id: str, user_id: str, extra: dict | None = None) -> None:
    if bus is None:
        return
    bus.publish(
        CloudEvent(
            type=event_type,
            source="earp-server/conversation",
            tenant_id=tenant_id,
            data={"entity_type": "app_category", "user_id": user_id, **(extra or {})},
        )
    )


async def ensure_default_categories(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    """租户无任何分类时惰性 seed 默认词表；返回当前词表（含数据库已有行）。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        count = (
            await conn.execute(text("SELECT count(*) FROM app_categories WHERE tenant_id = :tid"), {"tid": tenant_id})
        ).scalar()
        if not count:
            for name in DEFAULT_CATEGORIES:
                await conn.execute(
                    text(
                        "INSERT INTO app_categories (category_id, tenant_id, name, sort_order) "
                        "VALUES (:cid, :tid, :name, :sort) "
                        "ON CONFLICT (tenant_id, name) DO NOTHING"
                    ),
                    {"cid": _category_id(), "tid": tenant_id, "name": name, "sort": len(DEFAULT_CATEGORIES)},
                )
            await conn.commit()
    return await list_categories(engine, tenant_id)


async def list_categories(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT category_id, name, sort_order, created_at "
                "FROM app_categories WHERE tenant_id = :tid "
                "ORDER BY sort_order, name"
            ),
            {"tid": tenant_id},
        )
        return [dict(r._mapping) for r in rows]


async def is_valid_category(engine: AsyncEngine, tenant_id: str, name: str) -> bool:
    """分类名是否在租户有效词表内（autocreate 默认词表兜底）。"""
    categories = await ensure_default_categories(engine, tenant_id)
    return any(c["name"] == name for c in categories)


async def create_category(
    engine: AsyncEngine, tenant_id: str, user_id: str, name: str, *, sort_order: int = 0, bus=None
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("分类名不能为空")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        dup = (
            await conn.execute(
                text("SELECT 1 FROM app_categories WHERE tenant_id = :tid AND name = :name"),
                {"tid": tenant_id, "name": name},
            )
        ).first()
        if dup:
            raise ValueError(f"分类已存在: {name}")
        cid = _category_id()
        await conn.execute(
            text(
                "INSERT INTO app_categories (category_id, tenant_id, name, sort_order) "
                "VALUES (:cid, :tid, :name, :sort)"
            ),
            {"cid": cid, "tid": tenant_id, "name": name, "sort": int(sort_order)},
        )
        await conn.commit()
    _audit(bus, "earp.app_category.created", tenant_id, user_id, {"name": name})
    return {"category_id": cid, "name": name, "sort_order": int(sort_order)}


async def rename_category(
    engine: AsyncEngine, tenant_id: str, user_id: str, category_id: str, name: str, *, bus=None
) -> dict[str, Any] | None:
    """rename：同一事务内同步 `chat_apps.category` 快照（name 引用于 chat_apps）。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("分类名不能为空")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text("SELECT category_id, name FROM app_categories WHERE category_id = :cid AND tenant_id = :tid"),
                {"cid": category_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            return None
        old = row[1]
        dup = (
            await conn.execute(
                text("SELECT 1 FROM app_categories WHERE tenant_id = :tid AND name = :name AND category_id <> :cid"),
                {"tid": tenant_id, "name": name, "cid": category_id},
            )
        ).first()
        if dup:
            raise ValueError(f"分类已存在: {name}")
        # 同事务：更新词表名 + 同步 chat_apps.category 快照引用
        await conn.execute(
            text("UPDATE app_categories SET name = :name WHERE category_id = :cid AND tenant_id = :tid"),
            {"name": name, "cid": category_id, "tid": tenant_id},
        )
        await conn.execute(
            text("UPDATE chat_apps SET category = :new, updated_at = now() WHERE category = :old AND tenant_id = :tid"),
            {"new": name, "old": old, "tid": tenant_id},
        )
        await conn.commit()
    _audit(bus, "earp.app_category.updated", tenant_id, user_id, {"category_id": category_id, "old": old, "new": name})
    return {"category_id": category_id, "name": name}


async def delete_category(
    engine: AsyncEngine, tenant_id: str, user_id: str, category_id: str, *, bus=None
) -> dict[str, Any] | None:
    """删除分类：被 chat_apps 引用的应用 category 置空；返回受影响应用数。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text("SELECT name FROM app_categories WHERE category_id = :cid AND tenant_id = :tid"),
                {"cid": category_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            return None
        name = row[0]
        affected = int(
            (
                await conn.execute(
                    text("SELECT count(*) FROM chat_apps WHERE category = :name AND tenant_id = :tid"),
                    {"name": name, "tid": tenant_id},
                )
            ).scalar()
            or 0
        )
        await conn.execute(
            text(
                "UPDATE chat_apps SET category = NULL, updated_at = now() WHERE category = :name AND tenant_id = :tid"
            ),
            {"name": name, "tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM app_categories WHERE category_id = :cid AND tenant_id = :tid"),
            {"cid": category_id, "tid": tenant_id},
        )
        await conn.commit()
    _audit(
        bus,
        "earp.app_category.deleted",
        tenant_id,
        user_id,
        {"category_id": category_id, "name": name, "affected": affected},
    )
    return {"category_id": category_id, "deleted": True, "affected_apps": affected}
