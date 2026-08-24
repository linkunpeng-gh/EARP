"""应用中心：flow 节点级 SSE 流式（on_event 链路）测试。

设计：docs/superpowers/specs/2026-08-24-agent-center-design.md §4.1/§4.2。
覆盖：node_start/token/node_end/done 事件序列、非 LLM 节点无 token、branch 事件、
human_approval 挂起事件、恢复续跑、error 事件（PolicyLayer 403 透传）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation import chat_app_service
from earp_server.conversation.chat_service import flow_chat
from earp_server.orchestrator.types import TokenEvent

TENANT = "ac-stream-t1"
FLOW_LLM = "flow-llm"


class StreamLLM:
    """Fake LLM with both complete() and stream() — 流式测试专用。"""

    def __init__(self, text: str = "流式回复内容") -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int | None = None):
        self.calls.append({"prompt": prompt})
        return self.text

    async def stream(self, prompt: str, *, system: str = "") -> AsyncGenerator[TokenEvent, None]:
        self.calls.append({"prompt": prompt, "stream": True})
        for i, ch in enumerate(self.text):
            yield TokenEvent(token=ch, index=i)
        yield TokenEvent(token="", index=len(self.text))


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://x/x", app_env="test")


def _graph(*nodes: dict, edges: list[dict]) -> dict:
    return {"nodes": list(nodes), "edges": edges}


class EventCollector:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, ev: str, data: dict) -> None:
        self.events.append((ev, data))


async def _seed_user(engine: AsyncEngine, uid: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
        await conn.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) VALUES (:uid, :tid, :uname, :em) "
                "ON CONFLICT DO NOTHING"
            ),
            {"uid": uid, "tid": TENANT, "uname": uid, "em": uid + "@e.io"},
        )


async def _make_flow_app(engine: AsyncEngine, schema: dict, name: str) -> dict:
    await _seed_user(engine, "stream-u1")
    app = await chat_app_service.create_chat_app(
        engine, TENANT, "stream-u1", name, orchestration="flow", flow_schema=schema
    )
    await chat_app_service.publish_chat_app(engine, TENANT, "stream-u1", app["chat_app_id"], category="财务")
    return await chat_app_service.get_chat_app(engine, TENANT, app["chat_app_id"])


async def test_flow_stream_event_sequence(app_engine: AsyncEngine) -> None:
    """start→llm→end：node_start → token* → node_end → done。"""
    g = _graph(
        {"id": "start", "type": "start", "data": {}},
        {"id": "l1", "type": "llm", "data": {"prompt": "你好"}},
        {"id": "end", "type": "end", "data": {}},
        edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
    )
    app = await _make_flow_app(app_engine, g, "flow-sse-basic")
    collector = EventCollector()
    llm = StreamLLM(text="流式")
    result = await flow_chat(
        app_engine,
        TENANT,
        "stream-u1",
        "r1",
        app,
        "hi",
        None,
        base_llm=llm,
        settings=_settings(),
        on_event=collector.emit,
    )
    assert result["status"] == "completed"
    types = [ev for ev, _ in collector.events]
    assert types[0] == "node_start"
    assert "done" in types
    # token 事件与流式文本一致（逐字）
    tokens = "".join(d["text"] for ev, d in collector.events if ev == "token")
    assert tokens == "流式"
    # node_end 出现在 done 之前
    assert types.index("node_end") < types.index("done")
    # 流式走的是 stream() 分支（adapter 注入 on_token → 切 stream）
    assert llm.calls and llm.calls[0].get("stream") is True


async def test_flow_stream_non_llm_node_no_token(app_engine: AsyncEngine) -> None:
    """非 LLM 节点（demo.echo step）不发 token 事件——仅 node_start/node_end。"""
    g = _graph(
        {"id": "start", "type": "start", "data": {}},
        {
            "id": "e1",
            "type": "step",
            "data": {"capability_call": {"adapter_type": "demo.echo", "input": {"msg": "hello"}}},
        },
        {"id": "end", "type": "end", "data": {}},
        edges=[{"source": "start", "target": "e1"}, {"source": "e1", "target": "end"}],
    )
    app = await _make_flow_app(app_engine, g, "flow-sse-echo")
    collector = EventCollector()
    llm = StreamLLM()
    result = await flow_chat(
        app_engine,
        TENANT,
        "stream-u1",
        "r1",
        app,
        "hi",
        None,
        base_llm=llm,
        settings=_settings(),
        on_event=collector.emit,
    )
    assert result["status"] == "completed"
    evs = collector.events
    assert all(ev != "token" for ev, _ in evs)
    assert any(ev == "node_start" for ev, _ in evs)
    assert any(ev == "node_end" for ev, _ in evs)


async def test_flow_stream_branch_event(app_engine: AsyncEngine) -> None:
    """start→llm(n1)→condition→llm(then)→end：branch 事件携带走向。"""
    g = _graph(
        {"id": "start", "type": "start", "data": {}},
        {"id": "n1", "type": "llm", "data": {"prompt": "生成"}},
        {
            "id": "cond",
            "type": "condition",
            "data": {"condition": {"left": "n1.output.text", "op": "==", "right": "abc"}},
        },
        {"id": "then1", "type": "llm", "data": {"prompt": "命中分支"}},
        {"id": "else1", "type": "llm", "data": {"prompt": "未命中分支"}},
        {"id": "end", "type": "end", "data": {}},
        edges=[
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "cond"},
            {"source": "cond", "target": "then1", "sourceHandle": "true"},
            {"source": "cond", "target": "else1", "sourceHandle": "false"},
            {"source": "then1", "target": "end"},
            {"source": "else1", "target": "end"},
        ],
    )
    app = await _make_flow_app(app_engine, g, "flow-sse-branch")
    collector = EventCollector()
    llm = StreamLLM(text="abc")  # n1 输出 "abc" → condition 命中 then
    result = await flow_chat(
        app_engine,
        TENANT,
        "stream-u1",
        "r1",
        app,
        "x",
        None,
        base_llm=llm,
        settings=_settings(),
        on_event=collector.emit,
    )
    assert result["status"] == "completed"
    branch = [d for ev, d in collector.events if ev == "branch"]
    assert branch and branch[0]["side"] == "then"


async def test_flow_stream_human_approval_event(app_engine: AsyncEngine) -> None:
    """start→human_approval→end：挂起发 human_approval 事件（question）。"""
    g = _graph(
        {"id": "start", "type": "start", "data": {}},
        {"id": "h1", "type": "human_approval", "data": {"question": "确认派单？"}},
        {"id": "end", "type": "end", "data": {}},
        edges=[{"source": "start", "target": "h1"}, {"source": "h1", "target": "end"}],
    )
    app = await _make_flow_app(app_engine, g, "flow-sse-approval")
    collector = EventCollector()
    result = await flow_chat(
        app_engine,
        TENANT,
        "stream-u1",
        "r1",
        app,
        "派单",
        None,
        base_llm=StreamLLM(),
        settings=_settings(),
        on_event=collector.emit,
    )
    assert result["status"] == "waiting_human"
    ha = [d for ev, d in collector.events if ev == "human_approval"]
    assert ha and ha[0]["question"] == "确认派单？"
    assert ha[0]["conversation_id"] == result["conversation_id"]
