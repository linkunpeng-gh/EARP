"""Chatflow F4 — human_approval 节点（pool 序列化 + 执行器挂起/恢复 + flow_chat 集成）。

覆盖：serialize_pool/deserialize_pool 往返、执行器挂起（WAITING_HUMAN + pending 信息）、
恢复（resume_pool + 答复注入 {{#node.output.reply#}}）、多挂起点顺序恢复、flow_chat
挂起 202 → 同 conversation 恢复 → 完成（flow_runs 状态流转）、超时惰性检查。

基线：F0 33 + F1 17 + F2 17 + F3 21（回归在各自文件）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation import chat_app_service
from earp_server.conversation.chat_service import flow_chat
from earp_server.orchestrator.multi_step import ExecutionStatus, MultiStepExecutor
from earp_server.orchestrator.types import InvokeContext, Step, StepResult
from earp_server.orchestrator.workflow_dsl import (
    StepExec,
    compile_flow_schema,
    deserialize_pool,
    serialize_pool,
)

TENANT = "f4-t1"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def _seed_f4(app_engine: AsyncEngine) -> None:
    """f4-t1 基线：users（conversations FK）。"""
    import asyncio

    async def _seed() -> None:
        async with app_engine.begin() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            await conn.execute(
                text(
                    "INSERT INTO users (user_id, tenant_id, name, email) "
                    "VALUES ('f4-u1', :t, 'f4-u1', 'f4-u1@e.io') ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )

    asyncio.run(_seed())


class FakeLLM:
    def __init__(self, text: str = "f4-answer") -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int | None = None):
        self.calls.append({"prompt": prompt, "system": system, "temperature": temperature, "max_tokens": max_tokens})
        return self.text


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://x/x", app_env="test")


def _ctx(execution_id: str | None = None, session_id: str = "conv-f4") -> InvokeContext:
    # checkpoint_blobs PK = (thread_id, ns)——execution_id 必须每次唯一（同一测试库持久化）
    execution_id = execution_id or uuid.uuid4().hex
    return InvokeContext(
        tenant_id=TENANT,
        execution_id=execution_id,
        session_id=session_id,
        user_id="f4-u1",
        role_id="r-f4",
        step=Step(step_id="start", capability_call={}),
    )


def _flow_graph(*nodes: dict, edges: list[dict]) -> dict:
    return {"nodes": list(nodes), "edges": edges}


def _approval_flow(question: str = "确认继续？", *, extra_llm_after: bool = True) -> dict:
    """start → h1(human_approval) → [l1(llm 引用答复)] → end。"""
    nodes = [
        {"id": "start", "type": "start", "data": {}},
        {"id": "h1", "type": "human_approval", "data": {"question": question}},
    ]
    edges = [{"source": "start", "target": "h1"}]
    if extra_llm_after:
        nodes.append({"id": "l1", "type": "llm", "data": {"prompt": "答复：{{#h1.output.reply#}}"}})
        edges.append({"source": "h1", "target": "l1"})
    nodes.append({"id": "end", "type": "end", "data": {}})
    edges.append({"source": nodes[-2]["id"], "target": "end"})
    return _flow_graph(*nodes, edges=edges)


# ── pool 序列化（纯函数）────────────────────────────────────────────────────


class TestPoolSerialization:
    def test_roundtrip(self) -> None:
        pool = {
            "n1": StepResult(step_id="n1", status="completed", output={"text": "hi", "citations": [{"c": 1}]}),
            "n2": StepResult(step_id="n2", status="completed", output={"count": 3}),
        }
        restored = deserialize_pool(serialize_pool(pool))
        assert set(restored) == {"n1", "n2"}
        assert restored["n1"].output == {"text": "hi", "citations": [{"c": 1}]}
        assert restored["n2"].output == {"count": 3}

    def test_empty_and_none(self) -> None:
        assert deserialize_pool(None) == {}
        assert deserialize_pool({}) == {}
        assert serialize_pool({}) == {}


# ── 执行器挂起/恢复 ─────────────────────────────────────────────────────────


class TestApprovalExecutor:
    async def test_execute_suspends_at_human_approval(self, app_engine: AsyncEngine) -> None:
        plan = compile_flow_schema(_approval_flow(question="确认派单？"))
        h1 = next(i for i in plan.sequence if i.node_id == "h1")
        assert isinstance(h1, StepExec)
        assert h1.step.capability_call == {"adapter_type": "human.approval", "input": {"question": "确认派单？"}}

        executor = MultiStepExecutor(app_engine, llm=FakeLLM())
        ctx = _ctx()
        results, state = await executor.execute(plan.steps, ctx, layers=[], plan=plan, flow_input={"query": "q"})
        assert state.status == ExecutionStatus.WAITING_HUMAN
        assert state.pending_node_id == "h1"
        assert state.pending_question == "确认派单？"
        assert "l1" not in {r.step_id for r in results}  # 下游未执行

    async def test_resume_injects_reply_and_continues(self, app_engine: AsyncEngine) -> None:
        plan = compile_flow_schema(_approval_flow())
        llm = FakeLLM(text="ok")
        executor = MultiStepExecutor(app_engine, llm=llm)

        ctx = _ctx()
        results, state = await executor.execute(plan.steps, ctx, layers=[], plan=plan, flow_input={"query": "q"})
        assert state.status == ExecutionStatus.WAITING_HUMAN
        pool = {r.step_id: r for r in results if r.status == "completed"}

        results2, state2 = await executor.execute(
            plan.steps,
            ctx,
            layers=[],
            plan=plan,
            flow_input={"query": "q"},
            resume_pool=pool,
            resume_pending_node=state.pending_node_id,
            resume_reply="同意",
        )
        assert state2.status == ExecutionStatus.COMPLETED
        assert results2[-1].step_id == "l1"
        assert "同意" in llm.calls[0]["prompt"]  # {{#h1.output.reply#}} → 答复

    async def test_multiple_suspension_points_resumed_in_order(self, app_engine: AsyncEngine) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "h1", "type": "human_approval", "data": {}},
            {"id": "h2", "type": "human_approval", "data": {"question": "二次确认？"}},
            {"id": "l1", "type": "llm", "data": {"prompt": "a={{#h1.output.reply#}} b={{#h2.output.reply#}}"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[
                {"source": "start", "target": "h1"},
                {"source": "h1", "target": "h2"},
                {"source": "h2", "target": "l1"},
                {"source": "l1", "target": "end"},
            ],
        )
        plan = compile_flow_schema(g)
        llm = FakeLLM()
        executor = MultiStepExecutor(app_engine, llm=llm)
        ctx = _ctx()

        results, state = await executor.execute(plan.steps, ctx, layers=[], plan=plan, flow_input={"query": "q"})
        assert state.status == ExecutionStatus.WAITING_HUMAN and state.pending_node_id == "h1"
        pool = {r.step_id: r for r in results if r.status == "completed"}

        results, state = await executor.execute(
            plan.steps,
            ctx,
            layers=[],
            plan=plan,
            flow_input={"query": "q"},
            resume_pool=pool,
            resume_pending_node="h1",
            resume_reply="第一轮",
        )
        assert state.status == ExecutionStatus.WAITING_HUMAN and state.pending_node_id == "h2"
        pool = {r.step_id: r for r in results if r.status == "completed"}

        results, state = await executor.execute(
            plan.steps,
            ctx,
            layers=[],
            plan=plan,
            flow_input={"query": "q"},
            resume_pool=pool,
            resume_pending_node="h2",
            resume_reply="第二轮",
        )
        assert state.status == ExecutionStatus.COMPLETED
        assert "a=第一轮 b=第二轮" in llm.calls[0]["prompt"]


# ── flow_chat 集成（挂起 → 恢复 → 完成）────────────────────────────────────


async def _flow_app(app_engine: AsyncEngine, schema: dict, name: str = "f4-app") -> dict:
    return await chat_app_service.create_chat_app(
        app_engine, TENANT, "f4-u1", name, orchestration="flow", flow_schema=schema
    )


async def _run_statuses(engine: AsyncEngine, conversation_id: str) -> list[str]:
    """flow_runs 该 conversation 的状态序列（按 created_at）。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
        rows = (
            await conn.execute(
                text("SELECT status FROM flow_runs WHERE tenant_id = :t AND conversation_id = :c ORDER BY created_at"),
                {"t": TENANT, "c": conversation_id},
            )
        ).fetchall()
    return [r.status for r in rows]


class TestFlowChatApproval:
    async def test_suspend_then_resume_to_completed(self, app_engine: AsyncEngine) -> None:
        """第一轮挂起（waiting_human）→ 第二轮同 conversation 恢复 → completed + 答复进 llm。"""
        app = await _flow_app(app_engine, _approval_flow(question="确认派单？"))
        llm = FakeLLM(text="已处理")

        first = await flow_chat(
            app_engine,
            TENANT,
            "f4-u1",
            "r-f4",
            app,
            "CNC-01 温度异常",
            None,
            base_llm=llm,
            settings=_settings(),
        )
        assert first["status"] == ExecutionStatus.WAITING_HUMAN.value
        assert first["pending_node_id"] == "h1"
        assert first["question"] == "确认派单？"
        conv_id = first["conversation_id"]
        exec_id = first["execution_id"]

        # flow_runs 已落 waiting_human
        assert await _run_statuses(app_engine, conv_id) == ["waiting_human"]

        second = await flow_chat(
            app_engine,
            TENANT,
            "f4-u1",
            "r-f4",
            app,
            "同意",
            conv_id,
            base_llm=llm,
            settings=_settings(),
        )
        assert second["status"] == ExecutionStatus.COMPLETED.value
        assert second["execution_id"] == exec_id  # 复用同一 run（D6 唯一性）
        assert second["outputs"]["l1"] == {"text": "已处理"}
        assert "同意" in llm.calls[0]["prompt"]  # 答复经 {{#h1.output.reply#}} 注入
        # run 终态化
        assert await _run_statuses(app_engine, conv_id) == ["completed"]

    async def test_suspend_message_persisted(self, app_engine: AsyncEngine) -> None:
        """挂起时 assistant 消息「⏸ 等待确认：…」落库。"""
        app = await _flow_app(app_engine, _approval_flow(question="人工把关"))
        first = await flow_chat(
            app_engine,
            TENANT,
            "f4-u1",
            "r-f4",
            app,
            "q",
            None,
            base_llm=FakeLLM(),
            settings=_settings(),
        )
        async with app_engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            rows = (
                await conn.execute(
                    text("SELECT role, content FROM messages WHERE conversation_id = :c ORDER BY seq"),
                    {"c": first["conversation_id"]},
                )
            ).fetchall()
        contents = [r.content for r in rows]
        assert any("⏸ 等待确认：人工把关" in c for c in contents)

    async def test_approval_timeout_lazy_expiry(self, app_engine: AsyncEngine) -> None:
        """D4 惰性检查：waiting_human 超时 → timeout 终态 + 消息；本轮按新建 run 处理。"""
        app = await _flow_app(app_engine, _approval_flow())
        first = await flow_chat(
            app_engine,
            TENANT,
            "f4-u1",
            "r-f4",
            app,
            "q1",
            None,
            base_llm=FakeLLM(),
            settings=_settings(),
        )
        conv_id = first["conversation_id"]
        # 人为把 run 的 updated_at 改到超时阈值之前
        async with app_engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            await conn.execute(
                text("UPDATE flow_runs SET updated_at = :old WHERE execution_id = :eid AND tenant_id = :t"),
                {"old": datetime.now(UTC) - timedelta(hours=2), "eid": first["execution_id"], "t": TENANT},
            )
            await conn.commit()
        second = await flow_chat(
            app_engine,
            TENANT,
            "f4-u1",
            "r-f4",
            app,
            "新问题",
            conv_id,
            base_llm=FakeLLM(),
            settings=_settings(),
        )
        # 超时 run 已终态化，新 run 执行同一张图（含 human_approval）→ 再次挂起
        assert second["status"] == ExecutionStatus.WAITING_HUMAN.value
        assert second["execution_id"] != first["execution_id"]  # 新建 run
        assert await _run_statuses(app_engine, conv_id) == ["timeout", "waiting_human"]
        # 超时消息落库
        async with app_engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            row = (
                await conn.execute(
                    text("SELECT 1 FROM messages WHERE conversation_id = :c AND content LIKE '⏰%' LIMIT 1"),
                    {"c": conv_id},
                )
            ).first()
        assert row is not None

    async def test_flow_without_approval_still_completes(self, app_engine: AsyncEngine) -> None:
        """无 human_approval 的图（回归）：正常完成 + flow_runs completed。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "l1", "type": "llm", "data": {"prompt": "q={{query}}"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        app = await _flow_app(app_engine, g, "f4-plain")
        llm = FakeLLM(text="plain")
        result = await flow_chat(
            app_engine,
            TENANT,
            "f4-u1",
            "r-f4",
            app,
            "hello",
            None,
            base_llm=llm,
            settings=_settings(),
        )
        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["outputs"]["l1"] == {"text": "plain"}
        assert await _run_statuses(app_engine, result["conversation_id"]) == ["completed"]


# ── 端点级：waiting_human → 202 ─────────────────────────────────────────────


class TestChatEndpoint202:
    async def test_chat_returns_202_when_waiting_human(self, migrated: str, app_url: str) -> None:
        """D2：执行到 human_approval → 端点 202（waiting_human + pending_node_id + question）。"""
        import jwt as _jwt
        from fastapi.testclient import TestClient

        from earp_server.main import create_app

        token = _jwt.encode(
            {"sub": "f4-u1", "tenant_id": TENANT, "role_id": "r-f4", "exp": 9999999999},
            "earp-dev-secret-change-in-production",
            algorithm="HS256",
        )
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app) as client:
            # The endpoint's normal composition root uses an LLMConnector.  The
            # flow behavior is already covered by this test; keep it hermetic.
            app.state.llm = FakeLLM(text="endpoint-answer")
            resp = client.post(
                "/chat_apps",
                json={"name": "f4-202", "orchestration": "flow", "flow_schema": _approval_flow()},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            app_id = resp.json()["chat_app_id"]
            chat = client.post(
                f"/chat_apps/{app_id}/chat",
                json={"query": "q"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert chat.status_code == 202
            body = chat.json()
            assert body["status"] == "waiting_human"
            assert body["pending_node_id"] == "h1"
            assert body["question"]
            conv_id = body["conversation_id"]
            # 第二轮（同 conversation）→ 恢复 → completed（200）
            done = client.post(
                f"/chat_apps/{app_id}/chat",
                json={"query": "同意", "conversation_id": conv_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert done.status_code == 200
            assert done.json()["status"] == "completed"
