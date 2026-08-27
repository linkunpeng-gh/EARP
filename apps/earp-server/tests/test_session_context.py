"""Chatflow C 系列（会话上下文）— 落库读写 + 指代消解 + 会话元数据。

任务书：tasks/chatflow-c-session-context-task-breakdown.md（Task 1-3）
设计稿：arch/design/2026-08-18-chat-session-context-design.md §2/§3

覆盖：
- Task 1/2：update_conversation_context / read_conversation_context 读写往返；
  空实体轮次不覆写 last_entities（审批「确认」轮防污染，任务书风险 1）；
  add_message 维护 message_count / last_active_at
- Task 2：chat_sse（auto 软路由）两轮 → conversations.context 已写 last_entities（含 entity_id）
- Task 3：understand() 指代消解 — context.last_entities entity_id 回填 + references
  trace（kind=coref，可溯源非 LLM 盲猜，设计稿 §2.4）
- Task 3：flow qu.answer 两轮 → context 落库 + 下一轮指代解析（F6 缺口 #9 双路径补齐）
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.conversation.chat_app_service import create_chat_app
from earp_server.conversation.chat_service import chat_sse
from earp_server.conversation.conversation_service import (
    add_message,
    create_conversation,
    get_messages,
    list_conversations,
    read_conversation_context,
    update_conversation_context,
)
from earp_server.ontology.understanding import understand

TENANT = "c-sess-t1"
DIM = 1024


class _BigramStubProvider:
    """与 test_chat.py 相同的 bigram stub embedding（chat_sse 软路由/检索需要）。"""

    name = "bigram-stub"
    dim = DIM

    def _bigrams(self, t: str) -> set[str]:
        chars = re.findall(r"[\w\u4e00-\u9fff]", t.lower())
        return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * DIM
            for bg in self._bigrams(t):
                vec[hashlib.md5(bg.encode()).digest()[0] % DIM] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


def _install_stub(monkeypatch) -> None:
    import earp_server.knowledge.embedding_service as embedding_service
    import earp_server.knowledge.routing as routing

    provider = _BigramStubProvider()
    monkeypatch.setattr(routing, "get_embedding_provider", lambda: provider)
    monkeypatch.setattr(embedding_service, "get_embedding_provider", lambda: provider)


class FakeLLM:
    def __init__(self, tokens=("C", "系列", "回答")) -> None:
        self.tokens = tokens

    async def chat_stream(self, system, history, query, **kwargs):
        for i, t in enumerate(self.tokens):
            yield SimpleNamespace(token=t, index=i)


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def _seed_c(app_engine: AsyncEngine) -> None:
    """c-sess-t1 基线：user + role(all/equipment_data) + CNC-01/高温报警 实体。"""

    async def _seed() -> None:
        async with app_engine.begin() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            await conn.execute(
                text(
                    "INSERT INTO users (user_id, tenant_id, name, email) "
                    "VALUES ('c-u1', :t, 'c-u1', 'c-u1@e.io') ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )
            await conn.execute(
                text(
                    "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                    "VALUES ('c-r1', :t, 'all', '{}', 'all', "
                    '\'[{"data_domain_id": "equipment_data"}]\') ON CONFLICT DO NOTHING'
                ),
                {"t": TENANT},
            )
            await conn.execute(
                text(
                    "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, attributes) "
                    "VALUES ('equipment', :t, '设备', 'object', '{}'), "
                    "('alarm', :t, '报警', 'object', '{}') ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )
            await conn.execute(
                text(
                    "INSERT INTO entities (entity_id, tenant_id, entity_type_id, name, business_code, "
                    "source_mode, status) VALUES "
                    "('ent-cnc01', :t, 'equipment', 'CNC-01 数控机床', 'CNC-01', 'extracted', 'active'), "
                    "('ent-alarm', :t, 'alarm', '高温报警', 'ALM-1', 'extracted', 'active') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )

    asyncio.run(_seed())


# ── Task 1/2: context 读写 helper + 元数据 ───────────────────────────────


async def test_context_write_read_roundtrip(app_engine: AsyncEngine) -> None:
    conv = await create_conversation(app_engine, TENANT, "c-u1", "t1")
    cid = conv["conversation_id"]
    await update_conversation_context(
        app_engine,
        TENANT,
        cid,
        entities=[{"mention": "CNC-01", "entity_id": "ent-cnc01", "semantic_type": "equipment"}],
        intent="RELATION",
        relations=[{"subject": "CNC-01", "relation": "manufactured_by"}],
    )
    ctx = await read_conversation_context(app_engine, TENANT, cid)
    assert ctx["last_entities"] == [{"mention": "CNC-01", "entity_id": "ent-cnc01", "semantic_type": "equipment"}]
    assert ctx["last_intent"] == "RELATION"
    assert ctx["last_relations"] == [{"subject": "CNC-01", "relation": "manufactured_by"}]
    assert ctx.get("updated_at"), "context 应带 updated_at"


async def test_context_empty_entities_not_overwritten(app_engine: AsyncEngine) -> None:
    """审批「确认」轮防污染（任务书风险 1）：空实体轮次不覆写 last_entities。"""
    conv = await create_conversation(app_engine, TENANT, "c-u1", "t2")
    cid = conv["conversation_id"]
    await update_conversation_context(
        app_engine,
        TENANT,
        cid,
        entities=[{"mention": "CNC-01", "entity_id": "ent-cnc01", "semantic_type": "equipment"}],
    )
    ctx1 = await read_conversation_context(app_engine, TENANT, cid)
    # 无实体轮次（如审批「确认」）→ context 不覆写
    await update_conversation_context(app_engine, TENANT, cid, entities=[])
    ctx2 = await read_conversation_context(app_engine, TENANT, cid)
    assert ctx2["last_entities"] == ctx1["last_entities"]
    assert ctx2.get("updated_at") == ctx1.get("updated_at")


async def test_add_message_maintains_metadata(app_engine: AsyncEngine) -> None:
    conv = await create_conversation(app_engine, TENANT, "c-u1", "t3")
    cid = conv["conversation_id"]
    await add_message(app_engine, TENANT, cid, "user", "hi", "c-u1")
    await add_message(app_engine, TENANT, cid, "assistant", "yo", "c-u1")
    async with app_engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
        row = (
            await conn.execute(
                text("SELECT message_count, last_active_at FROM conversations WHERE conversation_id = :cid"),
                {"cid": cid},
            )
        ).first()
    assert row is not None and row.message_count == 2
    assert row.last_active_at is not None


# ── Task 3: 规则层指代消解（entity_id 回填 + references trace）──────────────


async def test_understand_coref_entity_id_and_trace(app_engine: AsyncEngine) -> None:
    """「它的更换周期呢」→ context.last_entities 映射（含 entity_id 回填 + trace）。"""
    r = await understand(
        app_engine,
        TENANT,
        "它的更换周期呢",
        context={"last_entities": [{"mention": "CNC-01", "entity_id": "ent-cnc01", "semantic_type": "equipment"}]},
    )
    assert r.entities, "指代应解析出实体"
    e = r.entities[0]
    assert e.mention == "CNC-01"
    assert e.entity_id == "ent-cnc01"  # entity_id 回填（非仅 mention）
    assert e.semantic_type == "equipment"
    coref = [x for x in r.references if x.get("kind") == "coref"]
    assert coref, "references 应记录 coref 映射（可溯源）"
    assert coref[0]["trigger"] == "它"
    assert coref[0]["entity_id"] == "ent-cnc01"


async def test_understand_coref_without_entity_id(app_engine: AsyncEngine) -> None:
    """context.last_entities 无 entity_id（旧格式/F6 兜底）→ mention 映射仍可用。"""
    r = await understand(
        app_engine,
        TENANT,
        "它的更换周期呢",
        context={"last_entities": [{"mention": "CNC-01", "semantic_type": "equipment"}]},
    )
    assert r.entities and r.entities[0].mention == "CNC-01"
    assert r.entities[0].entity_id is None


async def test_understand_lookup_records_reference(app_engine: AsyncEngine) -> None:
    """直接命中实体也进 references（kind=lookup）。"""
    r = await understand(app_engine, TENANT, "CNC-01 由谁制造", context={})
    assert any(x.get("kind") == "lookup" and x.get("entity_id") == "ent-cnc01" for x in r.references)


# ── Task 2: auto 路径（chat_sse）两轮 → context 落库 + 指代 ─────────────────


async def test_chat_sse_two_turn_writes_context(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    app = await create_chat_app(engine, TENANT, "c-u1", "C系列会话")
    settings = SimpleNamespace(embedding_dim=DIM)

    async def _run(query: str, cid: str | None) -> list[dict]:
        events = []
        async for line in chat_sse(
            engine,
            TENANT,
            "c-u1",
            "c-r1",
            app,
            query,
            cid,
            base_llm=FakeLLM(),
            settings=settings,
        ):
            assert line.startswith("data: ")
            events.append(json.loads(line[len("data: ") :]))
        return events

    # 第一轮：CNC-01 温度异常 → context 已写 last_entities（含 entity_id）
    events1 = await _run("CNC-01 温度异常", None)
    done1 = [e for e in events1 if e["type"] == "done"]
    assert done1, f"第一轮应 done：{events1}"
    cid = done1[0]["conversation_id"]
    ctx = await read_conversation_context(engine, TENANT, cid)
    assert any("CNC-01" in e["mention"] for e in ctx.get("last_entities", []))
    assert ctx["last_entities"][0].get("entity_id") == "ent-cnc01"

    # 第二轮（指代）：context 读出 → 规则层解析到 CNC-01
    events2 = await _run("它的供应商呢", cid)
    assert any(e["type"] == "done" for e in events2)
    ctx2 = await read_conversation_context(engine, TENANT, cid)
    assert any("CNC-01" in e["mention"] for e in ctx2["last_entities"])


# ── Task 3: flow 路径（qu.answer）两轮 → context 落库 + 指代 ───────────────


async def test_flow_qu_answer_two_turn_writes_context(app_engine: AsyncEngine) -> None:
    from earp_server.connector import Connector
    from earp_server.orchestrator.types import InvokeContext, Step

    conv = await create_conversation(app_engine, TENANT, "c-u1", "flow")
    cid = str(conv["conversation_id"])
    connector = Connector(engine=app_engine)
    ctx = InvokeContext(
        tenant_id=TENANT,
        execution_id="e-c1",
        session_id=cid,
        user_id="c-u1",
        role_id="c-r1",
        step=Step(step_id="start", capability_call={}),
    )
    # 第一轮：CNC-01 供应商 → context 落库
    out1 = await connector.execute(
        {"adapter_type": "qu.answer", "input": {"query": "CNC-01 供应商", "use_llm": False}}, ctx=ctx
    )
    assert out1["entities"], "第一轮应提取实体"
    cctx = await read_conversation_context(app_engine, TENANT, cid)
    assert any("CNC-01" in e["mention"] for e in cctx["last_entities"])
    assert cctx["last_entities"][0].get("entity_id") == "ent-cnc01"

    # 第二轮：它的供应商呢 → 指代解析到 CNC-01（context 落库驱动，非即时推导）
    out2 = await connector.execute(
        {"adapter_type": "qu.answer", "input": {"query": "它的供应商呢", "use_llm": False}}, ctx=ctx
    )
    mentions = [e["mention"] for e in out2["entities"]]
    assert any("CNC-01" in m for m in mentions), f"flow 指代未解析：{mentions}"


# ── Task 5: 会话查询统一走 chat_app 可见性（防缝隙）────────────────────────
# 应用级角色可见性由 0029 agent_center（access_mode + app_role_access）承载；
# 本组测试覆盖 C 系列新增的「会话不可枚举缝隙闭合」。


async def _seed_role_c2(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES ('c-r2', :t, 'noaccess', '{}', 'all', '[]') ON CONFLICT DO NOTHING"
            ),
            {"t": TENANT},
        )


async def test_conversation_visibility_gap_closed(app_engine: AsyncEngine) -> None:
    """应用对角色不可见 → 其对话不可枚举（list + messages 双路径）；admin 兜底。"""
    from earp_server.conversation.chat_app_service import create_chat_app
    from earp_server.policy.app_access_service import set_app_access

    await _seed_role_c2(app_engine)

    # restricted 应用：仅 c-r1 白名单可见
    app = await create_chat_app(app_engine, TENANT, "c-u1", "C系列受限应用")
    await set_app_access(app_engine, TENANT, "c-u1", app["chat_app_id"], mode="restricted", roles=["c-r1"])
    conv = await create_conversation(app_engine, TENANT, "c-u1", "受限会话", chat_app_id=app["chat_app_id"])
    cid = conv["conversation_id"]
    await add_message(app_engine, TENANT, cid, "user", "hi", "c-u1")

    # 白名单角色 c-r1 → 可见（list + messages）
    lst_ok = await list_conversations(app_engine, TENANT, user_id="c-u1", role_id="c-r1", is_admin=False)
    assert any(c["conversation_id"] == cid for c in lst_ok), "白名单角色应看到受限应用会话"
    assert await get_messages(app_engine, TENANT, cid, role_id="c-r1", is_admin=False), "白名单角色可读消息"

    # 非白名单角色 c-r2 → 不可枚举（list 不含 + messages 空）
    lst_hidden = await list_conversations(app_engine, TENANT, user_id="c-u1", role_id="c-r2", is_admin=False)
    assert not any(c["conversation_id"] == cid for c in lst_hidden), "非白名单角色不可枚举受限应用会话"
    assert await get_messages(app_engine, TENANT, cid, role_id="c-r2", is_admin=False) == []

    # admin → 全员可见（兜底）
    lst_admin = await list_conversations(app_engine, TENANT, user_id="c-u1", role_id="c-r2", is_admin=True)
    assert any(c["conversation_id"] == cid for c in lst_admin), "admin 应看到受限应用会话"
    assert await get_messages(app_engine, TENANT, cid, role_id="c-r2", is_admin=True), "admin 可读消息"

    # open 应用 → 任意角色可见
    app_open = await create_chat_app(app_engine, TENANT, "c-u1", "C系列开放应用")
    conv_open = await create_conversation(app_engine, TENANT, "c-u1", "开放会话", chat_app_id=app_open["chat_app_id"])
    lst_open = await list_conversations(app_engine, TENANT, user_id="c-u1", role_id="c-r2", is_admin=False)
    assert any(c["conversation_id"] == conv_open["conversation_id"] for c in lst_open)

    # 直建会话（chat_app_id NULL）→ 不受应用可见性约束
    conv_direct = await create_conversation(app_engine, TENANT, "c-u1", "直建会话")
    lst_direct = await list_conversations(app_engine, TENANT, user_id="c-u1", role_id="c-r2", is_admin=False)
    assert any(c["conversation_id"] == conv_direct["conversation_id"] for c in lst_direct)
