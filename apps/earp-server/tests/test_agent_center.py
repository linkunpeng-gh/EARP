"""应用中心（智能体）后端测试：搜索/筛选/排序/收藏/可见性 + 分类词表 + 权限矩阵。

设计：docs/superpowers/specs/2026-08-24-agent-center-design.md §6.1。
覆盖：q 多字段模糊、type/category/tag 筛选、sort=hot 聚合、fav=1、收藏幂等、
删除 CASCADE、回草稿隐藏-重发布恢复、access_mode 四态、is_admin 兜底、分类 CRUD/rename 同步/删除置空。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.conversation import category_service
from earp_server.conversation import chat_app_service as svc
from earp_server.policy import app_access_service


class MockBus:
    def __init__(self) -> None:
        self.events: list = []

    def publish(self, ev) -> None:
        self.events.append(ev)


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _seed_user(app_engine: AsyncEngine, tid: str, uid: str) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) VALUES (:uid, :tid, :uname, :em) "
                "ON CONFLICT DO NOTHING"
            ),
            {"uid": uid, "tid": tid, "uname": uid, "em": uid + "@e.io"},
        )


async def _seed_role(app_engine: AsyncEngine, tid: str, rid: str, *, is_admin: bool = False) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, is_admin) "
                "VALUES (:rid, :tid, :rname, '{}', 'self', :adm) ON CONFLICT DO NOTHING"
            ),
            {"rid": rid, "tid": tid, "rname": rid, "adm": is_admin},
        )


async def _make_published(
    app_engine: AsyncEngine, tid: str, uid: str, name: str, *, category="财务", tags=None
) -> dict:
    if tags is None:
        tags = ["标签A"]
    app = await svc.create_chat_app(app_engine, tid, uid, name, "desc", category=category, tags=tags, bus=None)
    await svc.publish_chat_app(app_engine, tid, uid, app["chat_app_id"], category=category, tags=tags)
    return await svc.get_chat_app(app_engine, tid, app["chat_app_id"])


# ── 字段 / 发布校验 ──────────────────────────────────────────────────────────
async def test_create_sets_category_tags_created_by(app_engine: AsyncEngine) -> None:
    tid, uid = "ac-t1", "u-cat"
    await _seed_user(app_engine, tid, uid)
    app = await svc.create_chat_app(app_engine, tid, uid, "助手", category="财务", tags=["报销", "制度"])
    assert app["category"] == "财务"
    assert sorted(app["tags"]) == ["制度", "报销"]
    assert app["created_by"] == uid


async def test_create_invalid_category_rejected(app_engine: AsyncEngine) -> None:
    tid, uid = "ac-t2", "u-cat"
    await _seed_user(app_engine, tid, uid)
    with pytest.raises(ValueError):
        await svc.create_chat_app(app_engine, tid, uid, "助手", category="不存在的分类")


async def test_publish_requires_category(app_engine: AsyncEngine) -> None:
    tid, uid = "ac-t3", "u-cat"
    await _seed_user(app_engine, tid, uid)
    app = await svc.create_chat_app(app_engine, tid, uid, "助手")
    with pytest.raises(ValueError):
        await svc.publish_chat_app(app_engine, tid, uid, app["chat_app_id"])
    # 发布时补 category 可发布
    pub = await svc.publish_chat_app(app_engine, tid, uid, app["chat_app_id"], category="人事")
    assert pub["status"] == "published" and pub["category"] == "人事"


# ── 搜索 / 筛选 / 排序 / 收藏 ────────────────────────────────────────────────
async def test_search_by_name_desc_creator_tag(app_engine: AsyncEngine) -> None:
    tid = "ac-s1"
    uid, rid = "u-s", "r-s"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, rid)
    await _make_published(app_engine, tid, uid, "财务报销助手", tags=["报销"])
    await _make_published(app_engine, tid, uid, "人事制度", category="人事", tags=["制度"])
    # name 模糊
    q_names = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, q="报销", status="published")
    assert [a["name"] for a in q_names] == ["财务报销助手"]
    # created_by 模糊
    assert len(await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, q="u-s", status="published")) == 2
    # tag 模糊
    tag_q = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, q="制度", status="published")
    assert [a["name"] for a in tag_q] == ["人事制度"]
    # type 筛选
    assert (
        len(await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, app_type="chat", status="published"))
        == 2
    )
    # category 筛选
    cat_q = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, category="人事", status="published")
    assert [a["name"] for a in cat_q] == ["人事制度"]
    # tag 精确筛选
    tag_q2 = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, tag="报销", status="published")
    assert [a["name"] for a in tag_q2] == ["财务报销助手"]


async def test_list_only_published_and_favorite_flag(app_engine: AsyncEngine) -> None:
    tid, uid, rid = "ac-s2", "u-s", "r-s"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, rid)
    pub = await _make_published(app_engine, tid, uid, "已发布")
    await svc.create_chat_app(app_engine, tid, uid, "草稿")
    lst = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, status="published")
    assert {a["chat_app_id"] for a in lst} == {pub["chat_app_id"]}
    assert all(a["favorite"] is False for a in lst)
    # 收藏
    await svc.favorite_app(app_engine, tid, uid, pub["chat_app_id"])
    lst2 = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, status="published")
    pub_row = next(a for a in lst2 if a["chat_app_id"] == pub["chat_app_id"])
    assert pub_row["favorite"] is True
    assert pub_row["favorite_count"] == 1
    # fav=1 只返回收藏
    favs = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, fav=True, status="published")
    assert [a["chat_app_id"] for a in favs] == [pub["chat_app_id"]]
    # 取消收藏
    await svc.unfavorite_app(app_engine, tid, uid, pub["chat_app_id"])
    favs2 = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, fav=True, status="published")
    assert favs2 == []


async def test_default_returns_all_statuses_workbench(app_engine: AsyncEngine) -> None:
    """工作台编排页语义：缺省 status 返回全部（草稿 + 已发布），草稿不消失。"""
    tid, uid, rid = "ac-s6", "u-s", "r-s"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, rid)
    pub = await _make_published(app_engine, tid, uid, "已发布应用")
    draft = await svc.create_chat_app(app_engine, tid, uid, "草稿应用")
    all_rows = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid)
    ids = {a["chat_app_id"] for a in all_rows}
    assert pub["chat_app_id"] in ids and draft["chat_app_id"] in ids
    # 应用中心语义：显式 published 只返回已发布
    pub_only = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, status="published")
    assert {a["chat_app_id"] for a in pub_only} == {pub["chat_app_id"]}


async def test_favorite_idempotent_and_non_existent(app_engine: AsyncEngine) -> None:
    tid, uid = "ac-s3", "u-s"
    await _seed_user(app_engine, tid, uid)
    app = await _make_published(app_engine, tid, uid, "收藏幂等")
    assert await svc.favorite_app(app_engine, tid, uid, app["chat_app_id"]) is True
    assert await svc.favorite_app(app_engine, tid, uid, app["chat_app_id"]) is True  # 幂等
    assert await svc.favorite_app(app_engine, tid, "u-x", app["chat_app_id"]) is True  # 任意用户
    assert await svc.favorite_app(app_engine, tid, uid, "app-nope") is False


async def test_favorite_survives_unpublish_and_delete_cascade(app_engine: AsyncEngine) -> None:
    tid, uid = "ac-s4", "u-s"
    await _seed_user(app_engine, tid, uid)
    app = await _make_published(app_engine, tid, uid, "下架测试")
    await svc.favorite_app(app_engine, tid, uid, app["chat_app_id"])
    # 回草稿 → 列表隐藏（fav=1 不再出现）但收藏行保留
    await svc.update_chat_app(app_engine, tid, uid, app["chat_app_id"], {"description": "改一下"})
    assert await svc.search_chat_apps(app_engine, tid, role_id="r", user_id=uid, fav=True, status="published") == []
    # 重新发布 → 自动恢复
    await svc.publish_chat_app(app_engine, tid, uid, app["chat_app_id"], category="财务")
    favs_back = await svc.search_chat_apps(app_engine, tid, role_id="r", user_id=uid, fav=True, status="published")
    assert [a["chat_app_id"] for a in favs_back] == [app["chat_app_id"]]
    # 删除 → CASCADE 清收藏
    await svc.delete_chat_app(app_engine, tid, uid, app["chat_app_id"])
    async with app_engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        cnt = (
            await conn.execute(
                text("SELECT count(*) FROM user_app_favorites WHERE chat_app_id = :id"), {"id": app["chat_app_id"]}
            )
        ).scalar()
        assert cnt == 0


async def test_sort_hot_by_favorite_count(app_engine: AsyncEngine) -> None:
    tid, uid, rid = "ac-s5", "u-s", "r-s"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, rid)
    a = await _make_published(app_engine, tid, uid, "热门应用")
    await _make_published(app_engine, tid, uid, "冷门应用")
    await svc.favorite_app(app_engine, tid, uid, a["chat_app_id"])
    for u in ("u2", "u3", "u4"):
        await _seed_user(app_engine, tid, u)
        await svc.favorite_app(app_engine, tid, u, a["chat_app_id"])
    hot = await svc.search_chat_apps(app_engine, tid, role_id=rid, user_id=uid, sort="hot", status="published")
    assert hot[0]["name"] == "热门应用" and hot[0]["favorite_count"] == 4


# ── 权限矩阵（access_mode）───────────────────────────────────────────────────
async def test_access_default_open(app_engine: AsyncEngine) -> None:
    tid = "ac-a1"
    uid, rid = "u-a", "r-a"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, rid)
    await _make_published(app_engine, tid, uid, "开放应用")
    assert [a["name"] for a in await svc.search_chat_apps(app_engine, tid, role_id=rid)] == ["开放应用"]


async def test_access_restricted_whitelist_and_is_admin(app_engine: AsyncEngine) -> None:
    tid = "ac-a2"
    uid = "u-a"
    r_view, r_hidden, r_admin = "r-view", "r-hidden", "r-admin"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, r_view)
    await _seed_role(app_engine, tid, r_hidden)
    await _seed_role(app_engine, tid, r_admin, is_admin=True)
    app = await _make_published(app_engine, tid, uid, "受限应用")
    # 白名单只授权 r_view
    await app_access_service.set_app_access(app_engine, tid, uid, app["chat_app_id"], mode="restricted", roles=[r_view])
    rows_view = await svc.search_chat_apps(app_engine, tid, role_id=r_view, is_admin=False)
    assert [a["chat_app_id"] for a in rows_view] == [app["chat_app_id"]]
    assert await svc.search_chat_apps(app_engine, tid, role_id=r_hidden, is_admin=False) == []
    # is_admin 兜底可见
    rows_admin = await svc.search_chat_apps(app_engine, tid, role_id=r_admin, is_admin=True)
    assert [a["chat_app_id"] for a in rows_admin] == [app["chat_app_id"]]


async def test_access_fail_closed_after_role_removed(app_engine: AsyncEngine) -> None:
    tid = "ac-a3"
    uid, r1, r2 = "u-a", "r-1", "r-2"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, r1)
    await _seed_role(app_engine, tid, r2)
    app = await _make_published(app_engine, tid, uid, "仅一角色")
    await app_access_service.set_app_access(app_engine, tid, uid, app["chat_app_id"], mode="restricted", roles=[r1])
    # 删除角色 r1（模拟 roles 页删除 → ON DELETE CASCADE 清矩阵行）
    async with app_engine.begin() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(text("DELETE FROM roles WHERE role_id = :rid"), {"rid": r1})
    # fail-closed：mode 仍 restricted、无授权行 → 非 admin 均不可见
    acc = await app_access_service.get_app_access(app_engine, tid, app["chat_app_id"])
    assert acc["mode"] == "restricted" and acc["roles"] == []
    assert await svc.search_chat_apps(app_engine, tid, role_id=r2, is_admin=False) == []


async def test_set_access_back_to_open_clears_rows(app_engine: AsyncEngine) -> None:
    tid = "ac-a4"
    uid, r1 = "u-a", "r-1"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, r1)
    app = await _make_published(app_engine, tid, uid, "开关应用")
    await app_access_service.set_app_access(app_engine, tid, uid, app["chat_app_id"], mode="restricted", roles=[r1])
    await app_access_service.set_app_access(app_engine, tid, uid, app["chat_app_id"], mode="open", roles=[])
    acc = await app_access_service.get_app_access(app_engine, tid, app["chat_app_id"])
    assert acc["mode"] == "open" and acc["roles"] == []
    rows = await svc.search_chat_apps(app_engine, tid, role_id=r1)
    assert [a["chat_app_id"] for a in rows] == [app["chat_app_id"]]


async def test_set_access_rejects_admin_role_and_missing(app_engine: AsyncEngine) -> None:
    tid = "ac-a5"
    uid, r_admin = "u-a", "r-admin"
    await _seed_user(app_engine, tid, uid)
    await _seed_role(app_engine, tid, r_admin, is_admin=True)
    app = await _make_published(app_engine, tid, uid, "门禁应用")
    with pytest.raises(ValueError):
        await app_access_service.set_app_access(
            app_engine, tid, uid, app["chat_app_id"], mode="restricted", roles=[r_admin]
        )
    with pytest.raises(ValueError):
        await app_access_service.set_app_access(
            app_engine, tid, uid, app["chat_app_id"], mode="restricted", roles=["r-nope"]
        )


# ── 分类词表 ─────────────────────────────────────────────────────────────────
async def test_default_categories_seeded_per_tenant(app_engine: AsyncEngine) -> None:
    tid = "ac-c1"
    cats = await category_service.ensure_default_categories(app_engine, tid)
    names = [c["name"] for c in cats]
    for d in ["财务", "人事", "客服", "IT 运维", "数据分析", "其他"]:
        assert d in names
    # 幂等：再次调用不重复（唯一约束）
    cats2 = await category_service.ensure_default_categories(app_engine, tid)
    assert len(names) == len([c["name"] for c in cats2])


async def test_category_crud_rename_syncs_chat_apps(app_engine: AsyncEngine) -> None:
    tid, uid = "ac-c2", "u-c"
    await _seed_user(app_engine, tid, uid)
    cat = await category_service.create_category(app_engine, tid, uid, "我自建", bus=None)
    # 应用到分类
    app = await _make_published(app_engine, tid, uid, "用我自建", category="我自建")
    assert app["category"] == "我自建"
    # rename → chat_apps.category 同步
    renamed = await category_service.rename_category(app_engine, tid, uid, cat["category_id"], "更名分类", bus=None)
    assert renamed["name"] == "更名分类"
    updated = await svc.get_chat_app(app_engine, tid, app["chat_app_id"])
    assert updated["category"] == "更名分类"
    # duplicate name 拒绝：先建一个不同名分类，再尝试 rename 到该名
    other = await category_service.create_category(app_engine, tid, uid, "再分类", bus=None)
    with pytest.raises(ValueError):
        await category_service.rename_category(app_engine, tid, uid, cat["category_id"], "再分类", bus=None)
    await category_service.delete_category(app_engine, tid, uid, other["category_id"], bus=None)
    # delete → 应用 category 置空（此时 cat 名已是 更名分类）
    res = await category_service.delete_category(app_engine, tid, uid, cat["category_id"], bus=None)
    assert res["affected_apps"] == 1
    updated2 = await svc.get_chat_app(app_engine, tid, app["chat_app_id"])
    assert updated2["category"] is None


async def test_category_tenant_isolation(app_engine: AsyncEngine) -> None:
    tid1, tid2, uid = "ac-c3", "ac-c4", "u-c"
    await category_service.create_category(app_engine, tid1, uid, "租户1专属")
    cats2 = await category_service.ensure_default_categories(app_engine, tid2)
    assert "租户1专属" not in [c["name"] for c in cats2]
