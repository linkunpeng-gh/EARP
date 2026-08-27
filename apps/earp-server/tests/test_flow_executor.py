"""Chatflow F2 — flow 执行器（compile_flow_schema + 模板 + 对话节点适配器 + flow_chat 编排）。

覆盖：对话节点编译映射 / 未实现类型报错 / 变量引用模板 / Connector 适配器
（FakeLLM / 真 DB history / monkeypatch knowledge）/ flow_chat 端到端（含条件分支）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.connector import Connector, ConnectorError
from earp_server.conversation import chat_app_service
from earp_server.conversation.chat_service import ChatError, flow_chat
from earp_server.conversation.conversation_service import add_message, create_conversation
from earp_server.orchestrator.multi_step import ExecutionStatus
from earp_server.orchestrator.types import InvokeContext, Step, StepResult
from earp_server.orchestrator.workflow_dsl import (
    StepExec,
    WorkflowValidationError,
    compile_flow_schema,
    compile_workflow,
    resolve_templates,
)


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def _seed_users(app_engine: AsyncEngine) -> None:
    """conversations.user_id 有 FK → users；f2-t1 租户需 seed（镜像 test_chat_apps）。"""
    import asyncio

    async def _seed() -> None:
        async with app_engine.begin() as conn:
            await conn.execute(text("SET LOCAL earp.tenant_id = 'f2-t1'"))
            await conn.execute(
                text(
                    "INSERT INTO users (user_id, tenant_id, name, email) "
                    "VALUES ('u1', 'f2-t1', 'u1', 'u1@e.io') ON CONFLICT DO NOTHING"
                )
            )

    asyncio.run(_seed())


class FakeLLM:
    """LLMConnector 替身：记录 complete 调用，返回固定文本。"""

    def __init__(self, text: str = "flow-answer") -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int | None = None):
        self.calls.append({"prompt": prompt, "system": system, "temperature": temperature, "max_tokens": max_tokens})
        return self.text


def _ctx() -> InvokeContext:
    return InvokeContext(
        tenant_id="f2-t1",
        execution_id="exec-1",
        session_id="conv-1",
        user_id="u1",
        role_id="r1",
        step=Step(step_id="start", capability_call={}),
    )


def _flow_graph(*nodes: dict, edges: list[dict]) -> dict:
    return {"nodes": list(nodes), "edges": edges}


def _llm_node(nid: str, prompt: str, system: str = "") -> dict:
    return {"id": nid, "type": "llm", "data": {"prompt": prompt, "system": system}}


# ── 编译层（纯函数）──────────────────────────────────────────────────────────


class TestCompileFlowSchema:
    def test_dialogue_nodes_mapped_to_adapters(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "h1", "type": "chat_history", "data": {"turns": 4}},
            _llm_node("l1", "q={{query}}"),
            {"id": "k1", "type": "knowledge", "data": {"query": "{{query}}", "top_k": 3}},
            {"id": "end", "type": "end", "data": {}},
            edges=[
                {"source": "start", "target": "h1"},
                {"source": "h1", "target": "l1"},
                {"source": "l1", "target": "k1"},
                {"source": "k1", "target": "end"},
            ],
        )
        plan = compile_flow_schema(g)
        by_id = {item.node_id: item for item in plan.sequence}
        assert isinstance(by_id["h1"], StepExec)
        assert by_id["h1"].step.capability_call == {"adapter_type": "chat.history", "input": {"turns": 4}}
        assert by_id["l1"].step.capability_call["adapter_type"] == "llm.prompt"
        assert by_id["l1"].step.capability_call["input"]["prompt"] == "q={{query}}"
        assert by_id["k1"].step.capability_call == {
            "adapter_type": "knowledge.search",
            "input": {"query": "{{query}}", "top_k": 3},
        }

    # F7 (Task 3 D5): flow_schema 顶层 answer_from（显式答案节点）
    def test_compile_answer_from_passthrough(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            _llm_node("l1", "p"),
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        g["answer_from"] = "l1"
        plan = compile_flow_schema(g)
        assert plan.answer_from == "l1"
        # 缺省（存量 flow_schema 无该字段）→ None（回落原语义）
        g2 = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            _llm_node("l1", "p"),
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        assert compile_flow_schema(g2).answer_from is None

    def test_compile_answer_from_unknown_node_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            _llm_node("l1", "p"),
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        g["answer_from"] = "nope"
        with pytest.raises(WorkflowValidationError, match="answer_from"):
            compile_flow_schema(g)

    def test_unimplemented_types_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "m1", "type": "mcp", "data": {}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "m1"}, {"source": "m1", "target": "end"}],
        )
        with pytest.raises(WorkflowValidationError, match="未实现"):
            compile_flow_schema(g)

    def test_condition_gate_in_flow(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "n1", "type": "step", "data": {"capability_call": {"adapter_type": "demo.echo"}}},
            {
                "id": "c1",
                "type": "condition",
                "data": {"condition": {"left": "n1.output.echo.msg", "op": "==", "right": "x"}},
            },
            _llm_node("l1", "then"),
            _llm_node("l2", "else"),
            {"id": "end", "type": "end", "data": {}},
            edges=[
                {"source": "start", "target": "n1"},
                {"source": "n1", "target": "c1"},
                {"source": "c1", "target": "l1", "sourceHandle": "true"},
                {"source": "c1", "target": "l2", "sourceHandle": "false"},
                {"source": "l1", "target": "end"},
                {"source": "l2", "target": "end"},
            ],
        )
        plan = compile_flow_schema(g)
        gates = {item.node_id: item.gate for item in plan.sequence if isinstance(item, StepExec)}
        assert gates["l1"] == frozenset({("cond:c1", "then")})
        assert gates["l2"] == frozenset({("cond:c1", "else")})

    def test_f0_compile_unchanged(self) -> None:
        """F0 compile_workflow 默认白名单：llm 节点仍被拒。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            _llm_node("l1", "hi"),
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        with pytest.raises(WorkflowValidationError, match="unknown type"):
            compile_workflow(g)


# ── 模板替换（纯函数）───────────────────────────────────────────────────────


class TestResolveTemplates:
    POOL = {
        "n1": StepResult(step_id="n1", status="completed", output={"echo": {"msg": "hello"}, "count": 5}),
    }

    def test_query_and_node_output(self) -> None:
        out = resolve_templates("q={{query}} whole={{#n1.output#}}", self.POOL, {"query": "CNC-01"})
        assert out == 'q=CNC-01 whole={"echo": {"msg": "hello"}, "count": 5}'

    def test_nested_path(self) -> None:
        out = resolve_templates("msg={{#n1.output.echo.msg#}} count={{#n1.output.count#}}", self.POOL)
        assert out == "msg=hello count=5"

    def test_missing_reference_kept(self) -> None:
        assert (
            resolve_templates("{{#n9.output.x#}} {{unknown}}", self.POOL, {"query": "q"})
            == "{{#n9.output.x#}} {{unknown}}"
        )

    def test_recursive_dict_list(self) -> None:
        value = {"prompt": "q={{query}}", "items": ["{{#n1.output.echo.msg#}}", 1, None]}
        out = resolve_templates(value, self.POOL, {"query": "Q"})
        assert out == {"prompt": "q=Q", "items": ["hello", 1, None]}


# ── Connector 适配器 ─────────────────────────────────────────────────────────


class TestFlowAdapters:
    async def test_llm_prompt(self) -> None:
        llm = FakeLLM(text="answer-1")
        connector = Connector(llm=llm)
        out = await connector.execute(
            {"adapter_type": "llm.prompt", "input": {"prompt": "你好", "system": "sys", "temperature": 0.3}},
            ctx=_ctx(),
        )
        assert out == {"text": "answer-1"}
        assert llm.calls[0]["prompt"] == "你好"
        assert llm.calls[0]["system"] == "sys"
        assert llm.calls[0]["temperature"] == 0.3

    async def test_llm_prompt_without_llm_raises(self) -> None:
        connector = Connector()
        with pytest.raises(ConnectorError):
            await connector.execute({"adapter_type": "llm.prompt", "input": {"prompt": "x"}}, ctx=_ctx())

    async def test_llm_prompt_failure_raises(self) -> None:
        class _FailLLM:
            async def complete(self, prompt: str, **kwargs):
                return None

        connector = Connector(llm=_FailLLM())
        with pytest.raises(ConnectorError, match="LLM generation failed"):
            await connector.execute({"adapter_type": "llm.prompt", "input": {"prompt": "x"}}, ctx=_ctx())

    async def test_chat_history(self, app_engine: AsyncEngine) -> None:
        conv = await create_conversation(app_engine, "f2-t1", "u1", "历史")
        await add_message(app_engine, "f2-t1", conv["conversation_id"], "user", "问题一", "u1")
        await add_message(app_engine, "f2-t1", conv["conversation_id"], "assistant", "回答一", "u1")
        ctx = _ctx()
        ctx.session_id = conv["conversation_id"]
        connector = Connector(engine=app_engine)
        out = await connector.execute({"adapter_type": "chat.history", "input": {"turns": 4}}, ctx=ctx)
        assert out["messages"] == [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
        ]

    async def test_knowledge_search(self, app_engine: AsyncEngine, monkeypatch) -> None:
        from earp_server.knowledge import embedding_service
        from earp_server.ontology import search as ontology_search

        async def _fake_embed(query: str) -> list[float]:
            return [0.1, 0.2]

        async def _fake_search(engine, tenant_id, query, **kwargs):
            # 三层检索：profile/graph（ABox）+ chunk
            return [
                {"source": "profile", "entity_id": "e1", "title": "CNC-01（实体档案）", "content": "…"},
                {
                    "source": "graph",
                    "entity_id": "e2",
                    "title": "图谱：manufactured_by → 上海某精机",
                    "content": "…",
                },
                {
                    "source": "chunk",
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "title": "T",
                    "content": "正文",
                    "chunk_index": 0,
                },
            ]

        monkeypatch.setattr(embedding_service, "embed_query", _fake_embed)
        monkeypatch.setattr(ontology_search, "knowledge_search", _fake_search)
        connector = Connector(engine=app_engine)
        out = await connector.execute(
            {"adapter_type": "knowledge.search", "input": {"query": "设备", "top_k": 3}},
            ctx=_ctx(),
        )
        # 三源 citations：profile/graph 带 source/entity_id；chunk 带 chunk_id
        assert out["chunks"][0]["source"] == "profile"
        assert any(c.get("source") == "graph" for c in out["citations"])
        chunk_cit = next(c for c in out["citations"] if c.get("chunk_id") == "c1")
        assert chunk_cit["title"] == "T"


# ── flow_chat 编排（端到端，服务级）─────────────────────────────────────────


async def _flow_app(app_engine: AsyncEngine, schema: dict, name: str = "f2-app") -> dict:
    return await chat_app_service.create_chat_app(
        app_engine, "f2-t1", "u1", name, orchestration="flow", flow_schema=schema
    )


class TestFlowChat:
    def _graph(self, prompt: str, *, condition: bool = False) -> dict:
        nodes = [
            {"id": "start", "type": "start", "data": {}},
            {"id": "h1", "type": "chat_history", "data": {"turns": 2}},
            _llm_node("l1", prompt),
            {"id": "end", "type": "end", "data": {}},
        ]
        edges = [
            {"source": "start", "target": "h1"},
            {"source": "h1", "target": "l1"},
            {"source": "l1", "target": "end"},
        ]
        return _flow_graph(*nodes, edges=edges)

    async def test_flow_chat_end_to_end(self, app_engine: AsyncEngine) -> None:
        app = await _flow_app(app_engine, self._graph("用户问：{{query}}"))
        llm = FakeLLM(text="图执行回答")
        result = await flow_chat(
            app_engine,
            "f2-t1",
            "u1",
            "r1",
            app,
            "CNC-01 温度异常",
            None,
            base_llm=llm,
            settings=Settings(database_url="postgresql+psycopg://x/x", app_env="test"),
        )
        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["outputs"]["l1"] == {"text": "图执行回答"}
        assert result["answer"] == "图执行回答"
        assert "CNC-01 温度异常" in llm.calls[0]["prompt"]  # {{query}} 已替换
        assert result["conversation_id"]
        # 消息落库：user + assistant
        async with app_engine.connect() as conn:
            await conn.execute(text("SET LOCAL earp.tenant_id = 'f2-t1'"))
            rows = (
                await conn.execute(
                    text("SELECT role FROM messages WHERE conversation_id = :cid ORDER BY seq"),
                    {"cid": result["conversation_id"]},
                )
            ).fetchall()
        assert [r.role for r in rows] == ["user", "assistant"]

    # ── F7 (Task 3 D5): 显式指定答案节点（answer_from）─────────────────────────

    class _PromptLLM:
        """按 prompt 返回不同文本——区分多 LLM 节点输出。"""

        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def complete(
            self, prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int | None = None
        ):
            self.calls.append({"prompt": prompt})
            return f"answer:{prompt}"

    async def test_flow_chat_answer_from_explicit_node(self, app_engine: AsyncEngine) -> None:
        """answer_from 指向 l1 → 答复取 l1 输出（即使副作用节点 l2 在最后执行）。"""
        g = {
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                _llm_node("l1", "主答复"),
                _llm_node("l2", "副作用处理"),
                {"id": "end", "type": "end", "data": {}},
            ],
            "edges": [
                {"source": "start", "target": "l1"},
                {"source": "l1", "target": "l2"},
                {"source": "l2", "target": "end"},
            ],
            "answer_from": "l1",
        }
        app = await _flow_app(app_engine, g, "f7-answer-from")
        llm = self._PromptLLM()
        result = await flow_chat(
            app_engine,
            "f2-t1",
            "u1",
            "r1",
            app,
            "q",
            None,
            base_llm=llm,
            settings=Settings(database_url="postgresql+psycopg://x/x", app_env="test"),
        )
        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["answer"] == "answer:主答复"  # 非最后一个执行节点的输出
        assert result["outputs"]["l2"] == {"text": "answer:副作用处理"}  # l2 仍正常执行

    async def test_flow_chat_answer_from_json_summary(self, app_engine: AsyncEngine) -> None:
        """answer_from 节点输出无 text → JSON 摘要兜底（output.text 优先，否则 JSON 摘要）。"""
        g = {
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                {"id": "h1", "type": "chat_history", "data": {"turns": 2}},
                {"id": "end", "type": "end", "data": {}},
            ],
            "edges": [
                {"source": "start", "target": "h1"},
                {"source": "h1", "target": "end"},
            ],
            "answer_from": "h1",  # chat.history 输出 {"messages": [...]}，无 text 键
        }
        app = await _flow_app(app_engine, g, "f7-answer-json")
        result = await flow_chat(
            app_engine,
            "f2-t1",
            "u1",
            "r1",
            app,
            "q",
            None,
            base_llm=FakeLLM(),
            settings=Settings(database_url="postgresql+psycopg://x/x", app_env="test"),
        )
        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["answer"].startswith('{"messages":')  # JSON 摘要

    async def test_flow_chat_answer_from_failed_node_falls_back(self, app_engine: AsyncEngine) -> None:
        """answer_from 节点运行失败（未完成）→ 回落默认语义（最后完成节点）。"""
        g = {
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                _llm_node("l1", "主答复"),
                {
                    "id": "c1",
                    "type": "capability",
                    "data": {"capability_call": {"capability_id": "cap-nope", "input": {}}},
                },
                {"id": "end", "type": "end", "data": {}},
            ],
            "edges": [
                {"source": "start", "target": "l1"},
                {"source": "l1", "target": "c1"},
                {"source": "c1", "target": "end"},
            ],
            "answer_from": "c1",  # 节点存在但运行失败（capability 未注册）→ 回落
        }
        app = await _flow_app(app_engine, g, "f7-answer-fail")
        result = await flow_chat(
            app_engine,
            "f2-t1",
            "u1",
            "r1",
            app,
            "q",
            None,
            base_llm=FakeLLM(text="兜底答复"),
            settings=Settings(database_url="postgresql+psycopg://x/x", app_env="test"),
        )
        assert result["status"] == ExecutionStatus.FAILED.value
        assert result["answer"] == "兜底答复"  # 回落最后完成节点（l1）

    async def test_flow_chat_condition_only_hit_branch(self, app_engine: AsyncEngine) -> None:
        """condition 只走命中分支：未命中分支的 llm 节点不 invoke。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {
                "id": "n1",
                "type": "step",
                "data": {"capability_call": {"adapter_type": "demo.echo", "input": {"msg": "hello"}}},
            },
            {
                "id": "c1",
                "type": "condition",
                "data": {"condition": {"left": "n1.output.echo.msg", "op": "==", "right": "hello"}},
            },
            _llm_node("l1", "then-branch"),
            _llm_node("l2", "else-branch"),
            {"id": "end", "type": "end", "data": {}},
            edges=[
                {"source": "start", "target": "n1"},
                {"source": "n1", "target": "c1"},
                {"source": "c1", "target": "l1", "sourceHandle": "true"},
                {"source": "c1", "target": "l2", "sourceHandle": "false"},
                {"source": "l1", "target": "end"},
                {"source": "l2", "target": "end"},
            ],
        )
        app = await _flow_app(app_engine, g, name="f2-branch")
        llm = FakeLLM(text="hit")
        result = await flow_chat(
            app_engine,
            "f2-t1",
            "u1",
            "r1",
            app,
            "q",
            None,
            base_llm=llm,
            settings=Settings(database_url="postgresql+psycopg://x/x", app_env="test"),
        )
        assert result["outputs"]["l1"] == {"text": "hit"}
        assert "l2" not in result["outputs"]
        assert len(llm.calls) == 1  # 未命中分支未 invoke
        assert llm.calls[0]["prompt"] == "then-branch"
        # Chatflow 调试 trace：分支决策 + 节点实际输入（模板解析后）可见
        trace = {t["node_id"]: t for t in result["trace"]}
        assert trace["c1"]["status"] == "completed" and trace["c1"]["branch"] == "then"
        assert trace["l2"]["status"] == "skipped"  # 未命中分支节点也在轨迹中（不 invoke）
        assert trace["n1"]["input"] == {"msg": "hello"}
        assert trace["l1"]["input"]["prompt"] == "then-branch"
        assert "latency_ms" in trace["l1"]  # 节点耗时透出（StepRunner 已统计）

    async def test_flow_chat_missing_query_rejected(self, app_engine: AsyncEngine) -> None:
        app = await _flow_app(app_engine, self._graph("p"))
        with pytest.raises(ChatError):
            await flow_chat(
                app_engine,
                "f2-t1",
                "u1",
                "r1",
                app,
                "  ",
                None,
                base_llm=FakeLLM(),
                settings=Settings(database_url="postgresql+psycopg://x/x", app_env="test"),
            )

    async def test_flow_chat_unimplemented_node_rejected(self, app_engine: AsyncEngine) -> None:
        """发布门禁外改库 → 编译明确报错（防静默跳过节点）。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "m1", "type": "mcp", "data": {}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "m1"}, {"source": "m1", "target": "end"}],
        )
        app = await _flow_app(app_engine, g, name="f2-unimpl")
        with pytest.raises(WorkflowValidationError, match="未实现"):
            await flow_chat(
                app_engine,
                "f2-t1",
                "u1",
                "r1",
                app,
                "q",
                None,
                base_llm=FakeLLM(),
                settings=Settings(database_url="postgresql+psycopg://x/x", app_env="test"),
            )
