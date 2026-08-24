"""Chat 智能体 CRUD / 发布状态机 / RLS / 审计 / 删除保留对话（设计 §8.1）。"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.conversation import chat_app_service as svc
from earp_server.conversation.conversation_service import create_conversation


class MockBus:
    def __init__(self) -> None:
        self.events: list = []

    def publish(self, ev) -> None:
        self.events.append(ev)


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _seed_user(app_engine: AsyncEngine, tid: str, uid: str = "u1") -> None:
    """conversations.user_id 有 FK → users；自定义租户需 seed。"""
    async with app_engine.begin() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES (:uid, :tid, CAST(:uname AS TEXT), :email) ON CONFLICT DO NOTHING"
            ),
            {"uid": uid, "tid": tid, "uname": uid, "email": uid + "@e.io"},
        )


async def test_create_defaults_draft_with_template_prompt(app_engine: AsyncEngine) -> None:
    tid = "ca-t1"
    bus = MockBus()
    app = await svc.create_chat_app(app_engine, tid, "u1", "财务制度助手", "报销/制度问答", bus=bus)
    assert app["chat_app_id"].startswith("app-")
    assert app["status"] == "draft"
    assert app["system_prompt"]  # migration 默认模板非空
    assert app["kb_scope"] == []
    assert app["retrieval"] == {"mode": "hybrid", "top_k": 5, "threshold": 0.0}
    assert app["context_turns"] == 6
    assert bus.events[-1].type == "earp.chat_app.created"
    assert bus.events[-1].data["entity_type"] == "chat_app"


async def test_create_name_required(app_engine: AsyncEngine) -> None:
    with pytest.raises(ValueError):
        await svc.create_chat_app(app_engine, "ca-t1", "u1", "   ")


async def test_publish_then_edit_reverts_to_draft(app_engine: AsyncEngine) -> None:
    tid = "ca-t2"
    bus = MockBus()
    app = await svc.create_chat_app(app_engine, tid, "u1", "发布测试", bus=bus)

    pub = await svc.publish_chat_app(app_engine, tid, "u1", app["chat_app_id"], category="财务", bus=bus)
    assert pub["status"] == "published"
    assert bus.events[-1].type == "earp.chat_app.published"

    # publish 幂等
    pub2 = await svc.publish_chat_app(app_engine, tid, "u1", app["chat_app_id"], category="财务", bus=bus)
    assert pub2["status"] == "published"

    # 编辑已发布 → 回 draft
    upd = await svc.update_chat_app(
        app_engine, tid, "u1", app["chat_app_id"], {"system_prompt": "你是财务部助手。"}, bus=bus
    )
    assert upd is not None and upd["status"] == "draft"
    assert upd["system_prompt"] == "你是财务部助手。"
    assert bus.events[-1].type == "earp.chat_app.updated"
    assert bus.events[-1].data["reverted_to_draft"] is True


async def test_update_validation(app_engine: AsyncEngine) -> None:
    tid = "ca-t3"
    app = await svc.create_chat_app(app_engine, tid, "u1", "校验测试")
    aid = app["chat_app_id"]

    with pytest.raises(ValueError):
        await svc.update_chat_app(app_engine, tid, "u1", aid, {"retrieval": {"mode": "bogus"}})
    with pytest.raises(ValueError):
        await svc.update_chat_app(app_engine, tid, "u1", aid, {"kb_scope": "not-a-list"})
    with pytest.raises(ValueError):
        await svc.update_chat_app(app_engine, tid, "u1", aid, {"name": "  "})
    # model_config_id 引用不存在 → 422 前置校验
    with pytest.raises(ValueError):
        await svc.update_chat_app(app_engine, tid, "u1", aid, {"model_config_id": "mc-missing"})

    # None 字段不覆盖（如 system_prompt 显式 null 应跳过）
    upd = await svc.update_chat_app(app_engine, tid, "u1", aid, {"system_prompt": None, "context_turns": 3})
    assert upd is not None and upd["context_turns"] == 3 and upd["system_prompt"]

    # generation 参数：超范围 clamp（temperature 0-2 / top_p 0-1 / max_tokens 128-8192）
    upd2 = await svc.update_chat_app(
        app_engine, tid, "u1", aid,
        {"generation": {"temperature": 5, "top_p": -1, "max_tokens": 10}},
    )
    assert upd2 is not None
    assert upd2["generation"]["temperature"] == 2.0
    assert upd2["generation"]["top_p"] == 0.0
    assert upd2["generation"]["max_tokens"] == 128


async def test_rls_cross_tenant_isolation(app_engine: AsyncEngine) -> None:
    tid = "ca-t4"
    app = await svc.create_chat_app(app_engine, tid, "u1", "隔离测试")
    assert await svc.get_chat_app(app_engine, "other-tenant", app["chat_app_id"]) is None
    assert await svc.list_chat_apps(app_engine, "other-tenant") == []


async def test_delete_preserves_conversations_set_null(app_engine: AsyncEngine) -> None:
    """N1：删除含会话的 app → 会话保留，chat_app_id 置 NULL。"""
    tid = "ca-t5"
    await _seed_user(app_engine, tid)
    app = await svc.create_chat_app(app_engine, tid, "u1", "删除测试")
    conv = await create_conversation(app_engine, tid, "u1", "会话一", chat_app_id=app["chat_app_id"])
    cid = conv["conversation_id"]

    assert await svc.delete_chat_app(app_engine, tid, "u1", app["chat_app_id"]) is True
    assert await svc.get_chat_app(app_engine, tid, app["chat_app_id"]) is None

    async with app_engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        row = (await conn.execute(text("SELECT chat_app_id FROM conversations WHERE conversation_id = :cid"), {"cid": cid})).first()
        assert row is not None and row.chat_app_id is None


async def test_list_order_and_update_fields(app_engine: AsyncEngine) -> None:
    tid = "ca-t6"
    await svc.create_chat_app(app_engine, tid, "u1", "B 应用")
    await svc.create_chat_app(app_engine, tid, "u1", "A 应用")
    lst = await svc.list_chat_apps(app_engine, tid)
    assert len(lst) == 2
    assert sorted(a["name"] for a in lst) == ["A 应用", "B 应用"]  # 同毫秒创建顺序不稳定，集合断言

    app = lst[-1]
    upd = await svc.update_chat_app(
        app_engine, tid, "u1", app["chat_app_id"],
        {"kb_scope": ["kb-x", "kb-y"], "retrieval": {"mode": "vector", "top_k": 3}, "context_turns": 10},
    )
    assert upd is not None
    assert upd["kb_scope"] == ["kb-x", "kb-y"]
    assert upd["retrieval"]["mode"] == "vector" and upd["retrieval"]["top_k"] == 3
    assert upd["context_turns"] == 10
