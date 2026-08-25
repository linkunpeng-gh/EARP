"""Chatflow F3 — qu/capability/tool 节点（编译 + 适配器 + flow_chat 集成）。

覆盖：compile_flow_schema 对 qu/capability/tool 可编译（human_approval/mcp 仍报错）、
qu.answer 适配器（mock understand/execute_plan，citations/selection/chunks 透传）、
capability.call（注册表校验 + 权限门禁 + demo.echo 真实执行）、tool.fetch（真加密
connector 配置 + mock data_fetch）、flow_chat 集成（qu→llm citations 引用 / capability
权限+审计落 audit_logs / tool 取数 / PolicyLayer 权限拒绝 403）。

基线：F2 17 + F1 17 + F0 33（回归在各自文件）。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.audit.consumer import audit_handler_factory
from earp_server.config import Settings
from earp_server.connector import Connector, ConnectorError
from earp_server.conversation import chat_app_service
from earp_server.conversation.chat_service import flow_chat
from earp_server.infra.eventbus import EventBus
from earp_server.ontology.planning import Evidence, EvidenceChannel, PlanResult, PlanSelection
from earp_server.ontology.understanding import Intent, RuleResult
from earp_server.orchestrator.multi_step import ExecutionStatus
from earp_server.orchestrator.types import InvokeContext, Step
from earp_server.orchestrator.workflow_dsl import StepExec, WorkflowValidationError, compile_flow_schema

TENANT = "f3-t1"
CAP_ID = "cap-f3-echo"  # 独立 capability_id（cap-demo-echo 可能被其它测试以 tenant-demo 占用——PK 全局唯一）
CN_ID = "cn-f3-rest"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _register_cap(engine: AsyncEngine, tenant_id: str, *, permissions: list[str]) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                "VALUES (:cid, :tid, 'demo', 'echo', 'query', '{}', '{}', :perms, '1.0.0') "
                "ON CONFLICT (capability_id, tenant_id) DO NOTHING"
            ),
            {"cid": CAP_ID, "tid": tenant_id, "perms": permissions},
        )
        await conn.commit()


async def _register_cap_exec(
    engine: AsyncEngine,
    tenant_id: str,
    capability_id: str,
    *,
    execution: dict,
    permissions: list[str],
    domain: str = "demo",
    name: str = "echo",
) -> None:
    """通用执行器任务书：注册带 execution 声明的能力（复合主键 tenant 隔离）。"""
    import json

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO business_capabilities "
                "(capability_id, tenant_id, domain, name, type, input_schema, output_schema, "
                "required_permissions, version, execution) "
                "VALUES (:cid, :tid, :domain, :name, 'query', '{}', '{}', :perms, '1.0.0', :exec) "
                "ON CONFLICT (capability_id, tenant_id) DO NOTHING"
            ),
            {
                "cid": capability_id,
                "tid": tenant_id,
                "domain": domain,
                "name": name,
                "perms": permissions,
                "exec": json.dumps(execution),
            },
        )
        await conn.commit()


async def _register_role(engine: AsyncEngine, tenant_id: str, role_id: str, permissions: list[str]) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, is_admin) "
                "VALUES (:rid, :tid, :name, :perms, 'all', FALSE) ON CONFLICT (role_id) DO NOTHING"
            ),
            {"rid": role_id, "tid": tenant_id, "name": role_id, "perms": permissions},
        )
        await conn.commit()


@pytest.fixture(scope="module", autouse=True)
def _seed_f3(app_engine: AsyncEngine) -> None:
    """f3-t1 基线：users（conversations FK）+ roles（f3-r1 有 demo.echo / f3-r2 无）+ cap-f3-echo。"""
    import asyncio

    async def _seed() -> None:
        async with app_engine.begin() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            await conn.execute(
                text(
                    "INSERT INTO users (user_id, tenant_id, name, email) "
                    "VALUES ('f3-u1', :t, 'f3-u1', 'f3-u1@e.io') ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )
        await _register_role(app_engine, TENANT, "f3-r1", ["demo.echo"])
        await _register_role(app_engine, TENANT, "f3-r2", [])
        await _register_cap(app_engine, TENANT, permissions=["demo.echo"])

    asyncio.run(_seed())


class FakeLLM:
    def __init__(self, text: str = "f3-answer") -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int | None = None):
        self.calls.append({"prompt": prompt, "system": system, "temperature": temperature, "max_tokens": max_tokens})
        return self.text


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://x/x", app_env="test")


def _ctx(role_id: str = "f3-r1") -> InvokeContext:
    return InvokeContext(
        tenant_id=TENANT,
        execution_id="exec-f3",
        session_id="conv-f3",
        user_id="f3-u1",
        role_id=role_id,
        step=Step(step_id="start", capability_call={}),
    )


def _flow_graph(*nodes: dict, edges: list[dict]) -> dict:
    return {"nodes": list(nodes), "edges": edges}


# ── 编译层（纯函数）──────────────────────────────────────────────────────────


class TestCompileF3:
    def test_qu_node_maps_to_qu_answer(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "q1", "type": "qu", "data": {"context_turns": 2}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "q1"}, {"source": "q1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        q1 = next(i for i in plan.sequence if i.node_id == "q1")
        assert isinstance(q1, StepExec)
        assert q1.step.capability_call == {
            "adapter_type": "qu.answer",
            "input": {"query": "{{query}}", "context_turns": 2},
        }

    def test_qu_node_custom_query(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "q1", "type": "qu", "data": {"query": "解析：{{query}}"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "q1"}, {"source": "q1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        q1 = next(i for i in plan.sequence if i.node_id == "q1")
        assert q1.step.capability_call["input"]["query"] == "解析：{{query}}"

    def test_qu_node_non_string_query_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "q1", "type": "qu", "data": {"query": 42}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "q1"}, {"source": "q1", "target": "end"}],
        )
        with pytest.raises(WorkflowValidationError, match="query"):
            compile_flow_schema(g)

    def test_capability_node_step_shape(self) -> None:
        """step 别名（F2 形状）：capability_call = {capability_id, input} → capability.call。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {
                "id": "c1",
                "type": "capability",
                "data": {"capability_call": {"capability_id": CAP_ID, "input": {"msg": "hi"}}},
            },
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "c1"}, {"source": "c1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        c1 = next(i for i in plan.sequence if i.node_id == "c1")
        assert isinstance(c1, StepExec)
        assert c1.step.capability_call == {
            "adapter_type": "capability.call",
            "capability_id": CAP_ID,
            "input": {"msg": "hi"},
        }

    def test_capability_node_input_shape(self) -> None:
        """D4 新形状：data.input = {capability_id, input}。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "c1", "type": "capability", "data": {"input": {"capability_id": CAP_ID, "input": {"msg": "x"}}}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "c1"}, {"source": "c1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        c1 = next(i for i in plan.sequence if i.node_id == "c1")
        assert c1.step.capability_call["adapter_type"] == "capability.call"
        assert c1.step.capability_call["capability_id"] == CAP_ID
        assert c1.step.capability_call["input"] == {"msg": "x"}

    def test_capability_node_explicit_adapter_kept(self) -> None:
        """显式 adapter_type（demo.echo 等）保持 step 行为（F2 兼容）。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "c1", "type": "capability", "data": {"capability_call": {"adapter_type": "demo.echo"}}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "c1"}, {"source": "c1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        c1 = next(i for i in plan.sequence if i.node_id == "c1")
        assert c1.step.capability_call == {"adapter_type": "demo.echo"}

    def test_capability_node_missing_capability_id_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "c1", "type": "capability", "data": {"capability_call": {"input": {"msg": "x"}}}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "c1"}, {"source": "c1", "target": "end"}],
        )
        with pytest.raises(WorkflowValidationError, match="capability_id"):
            compile_flow_schema(g)

    def test_tool_node_maps_to_tool_fetch(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "t1", "type": "tool", "data": {"connector_id": CN_ID, "params": {"region": "{{query}}"}}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "t1"}, {"source": "t1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        t1 = next(i for i in plan.sequence if i.node_id == "t1")
        assert isinstance(t1, StepExec)
        assert t1.step.capability_call == {
            "adapter_type": "tool.fetch",
            "input": {"connector_id": CN_ID, "params": {"region": "{{query}}"}},
        }

    def test_tool_node_missing_connector_id_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "t1", "type": "tool", "data": {}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "t1"}, {"source": "t1", "target": "end"}],
        )
        with pytest.raises(WorkflowValidationError, match="connector_id"):
            compile_flow_schema(g)

    def test_human_approval_node_compiles(self) -> None:
        """Chatflow F4: human_approval 节点可编译（挂起/恢复）。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "h1", "type": "human_approval", "data": {"question": "确认派单？{{query}}"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "h1"}, {"source": "h1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        h1 = next(i for i in plan.sequence if i.node_id == "h1")
        assert isinstance(h1, StepExec)
        assert h1.step.capability_call == {
            "adapter_type": "human.approval",
            "input": {"question": "确认派单？{{query}}"},
        }

    def test_mcp_still_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "x1", "type": "mcp", "data": {}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "x1"}, {"source": "x1", "target": "end"}],
        )
        with pytest.raises(WorkflowValidationError, match="未实现"):
            compile_flow_schema(g)


# ── Connector 适配器 ─────────────────────────────────────────────────────────


def _fake_qu_chain(monkeypatch, *, citations: list[dict]) -> None:
    """mock understand/execute_plan（connector 内部 import 发生在调用时——patch 生效）。"""
    import earp_server.ontology.planning as planning_mod
    import earp_server.ontology.understanding as understanding_mod

    async def _fake_understand(engine, tenant_id, query, **kwargs):
        return RuleResult(intent=Intent.FACT, confidence=1.0)

    async def _fake_execute_plan(engine, tenant_id, role_id, query, structured_query, **kwargs):
        ev = Evidence(
            evidence_id="ev-1",
            channel=EvidenceChannel.CHUNK,
            content="正文内容",
            source="设备手册",
            source_ref="doc-1",
            confidence=0.9,
            payload={"chunk_id": "c1", "similarity": 0.9},
        )
        pr = PlanResult(plan_name="plan_fact", evidence=[ev], citations=citations)
        return PlanSelection("plan_fact", lambda *a, **k: None), pr

    monkeypatch.setattr(understanding_mod, "understand", _fake_understand)
    monkeypatch.setattr(planning_mod, "execute_plan", _fake_execute_plan)


class TestF3Adapters:
    async def test_qu_answer_outputs_citations(self, app_engine: AsyncEngine, monkeypatch) -> None:
        citations = [{"chunk_id": "c1", "title": "设备手册", "document_id": "doc-1"}]
        _fake_qu_chain(monkeypatch, citations=citations)
        connector = Connector(engine=app_engine)
        out = await connector.execute(
            {"adapter_type": "qu.answer", "input": {"query": "CNC-01 是什么设备"}},
            ctx=_ctx(),
        )
        assert out["selection"] == {"plan_name": "plan_fact", "fallback_reason": None}
        assert out["citations"] == citations
        assert out["chunks"][0]["chunk_id"] == "c1"
        assert out["chunks"][0]["title"] == "设备手册"
        assert out["evidence"][0]["channel"] == "chunk"

    async def test_qu_answer_missing_query_raises(self, app_engine: AsyncEngine) -> None:
        connector = Connector(engine=app_engine)
        with pytest.raises(ConnectorError, match="query"):
            await connector.execute({"adapter_type": "qu.answer", "input": {}}, ctx=_ctx())

    async def test_capability_call_executes_demo_echo(self, app_engine: AsyncEngine) -> None:
        connector = Connector(engine=app_engine)
        out = await connector.execute(
            {"adapter_type": "capability.call", "capability_id": CAP_ID, "input": {"msg": "hi"}},
            ctx=_ctx(role_id="f3-r1"),
        )
        assert out == {"echo": {"msg": "hi"}}

    async def test_capability_call_unknown_capability_raises(self, app_engine: AsyncEngine) -> None:
        connector = Connector(engine=app_engine)
        with pytest.raises(ConnectorError, match="不存在"):
            await connector.execute(
                {"adapter_type": "capability.call", "capability_id": "cap-nope", "input": {}},
                ctx=_ctx(role_id="f3-r1"),
            )

    async def test_capability_call_permission_denied_raises(self, app_engine: AsyncEngine) -> None:
        connector = Connector(engine=app_engine)
        with pytest.raises(ConnectorError, match="缺少权限"):
            await connector.execute(
                {"adapter_type": "capability.call", "capability_id": CAP_ID, "input": {}},
                ctx=_ctx(role_id="f3-r2"),
            )

    # ── 通用执行器：execution 声明分派（任务书 D2）────────────────────────────
    async def test_execution_declared_demo_echo_dispatches(self, app_engine: AsyncEngine) -> None:
        """execution.adapter=demo.echo 显式声明 → 按声明分派。

        domain=custom（非 demo）——回退猜测路径 domain.name="custom.echo" 不命中任何 adapter，
        本用例只有声明分派路径能过（review 修复 #12：用默认 demo/echo 的话删掉声明代码也照绿，零区分度）。
        """
        await _register_cap_exec(
            app_engine, TENANT, "cap-exec-echo",
            execution={"adapter": "demo.echo"}, permissions=[], domain="custom", name="echo",
        )
        connector = Connector(engine=app_engine)
        out = await connector.execute(
            {"adapter_type": "capability.call", "capability_id": "cap-exec-echo", "input": {"msg": "hi"}},
            ctx=_ctx(role_id="f3-r1"),
        )
        assert out == {"echo": {"msg": "hi"}}

    async def test_execution_declared_tool_fetch_dispatches(self, app_engine: AsyncEngine, monkeypatch) -> None:
        """execution.adapter=tool.fetch + params → 真实走 tool.fetch（mock fetch）。

        params 合并双方向断言（review 修复 #14）：
        - connector_id 仅在 execution.params → 固定默认生效
        - params.region 两边都有 → capability input 覆写 execution.params（D3 优先级）
        """
        from earp_server.ontology import connector_service, data_adapter

        await connector_service.create_connector(
            app_engine, TENANT, connector_id="cn-exec-rest", adapter_type="rest",
            config={"base_url": "http://x.example", "path": "/api", "method": "GET"},
        )
        await _register_cap_exec(
            app_engine, TENANT, "cap-exec-tool",
            execution={
                "adapter": "tool.fetch",
                "params": {"connector_id": "cn-exec-rest", "params": {"region": "默认值"}},
            },
            permissions=[],
        )
        captured: dict = {}

        async def _fake_fetch(cfg, params=None):
            captured["cfg"] = cfg
            captured["params"] = params
            return [{"id": 9}]

        monkeypatch.setattr(data_adapter, "fetch", _fake_fetch)
        connector = Connector(engine=app_engine)
        out = await connector.execute(
            {
                "adapter_type": "capability.call",
                "capability_id": "cap-exec-tool",
                "input": {"params": {"region": "华东"}},
            },
            ctx=_ctx(),
        )
        assert out["count"] == 1
        # connector_id：execution.params 固定默认（input 未提供）
        assert captured["cfg"] is not None
        # region：input 覆写 execution.params 默认（D3：params 默认 < input 调用方覆写）
        assert captured["params"] == {"region": "华东"}

    async def test_malformed_execution_coerced_not_crash(self, app_engine: AsyncEngine) -> None:
        """畸形 execution（非 dict JSONB，直插 DB）→ 防御归一为 {} 走回退，不 AttributeError 500。"""
        async with app_engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            await conn.execute(
                text(
                    "INSERT INTO business_capabilities "
                    "(capability_id, tenant_id, domain, name, type, input_schema, output_schema, "
                    "required_permissions, version, execution) "
                    "VALUES ('cap-exec-bad', :t, 'demo', 'echo', 'query', '{}', '{}', '{}', '1.0.0', :exec) "
                    "ON CONFLICT (capability_id, tenant_id) DO NOTHING"
                ),
                {"t": TENANT, "exec": '\"not-a-dict\"'},
            )
            await conn.commit()
        connector = Connector(engine=app_engine)
        # execution 非对象 → 归一 {} → 无声明 → 回退 domain.name=demo.echo
        out = await connector.execute(
            {"adapter_type": "capability.call", "capability_id": "cap-exec-bad", "input": {"m": 1}},
            ctx=_ctx(),
        )
        assert out == {"echo": {"m": 1}}

    async def test_execution_unknown_adapter_raises(self, app_engine: AsyncEngine) -> None:
        """显式声明但 adapter 未知 → 明确报错（执行器任务书 D5）。"""
        await _register_cap_exec(
            app_engine, TENANT, "cap-exec-unknown", execution={"adapter": "ghost.adapter"}, permissions=[]
        )
        connector = Connector(engine=app_engine)
        with pytest.raises(ConnectorError, match="未实现"):
            await connector.execute(
                {"adapter_type": "capability.call", "capability_id": "cap-exec-unknown", "input": {}},
                ctx=_ctx(),
            )

    async def test_deprecated_capability_raises_disabled(self, app_engine: AsyncEngine) -> None:
        """已停用能力 → 「已停用」明确报错（能力中心 soft-disable 衔接）。"""
        await _register_cap_exec(
            app_engine, TENANT, "cap-exec-dead", execution={"adapter": "demo.echo"}, permissions=[]
        )
        async with app_engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            await conn.execute(
                text(
                    "UPDATE business_capabilities SET status = 'deprecated' "
                    "WHERE capability_id = 'cap-exec-dead' AND tenant_id = :t"
                ),
                {"t": TENANT},
            )
            await conn.commit()
        connector = Connector(engine=app_engine)
        with pytest.raises(ConnectorError, match="已停用"):
            await connector.execute(
                {"adapter_type": "capability.call", "capability_id": "cap-exec-dead", "input": {}},
                ctx=_ctx(),
            )

    async def test_tool_fetch_real_encrypted_connector(self, app_engine: AsyncEngine, monkeypatch) -> None:
        from earp_server.ontology import connector_service, data_adapter

        created = await connector_service.create_connector(
            app_engine,
            TENANT,
            connector_id=CN_ID,
            adapter_type="rest",
            config={"base_url": "http://internal.example", "path": "/api/items", "method": "GET"},
        )
        assert created is not None  # 幂等：同会话重复跑 ON CONFLICT 语义由 create_connector 返回 None

        async def _fake_fetch(cfg, params=None):
            assert cfg["base_url"] == "http://internal.example"  # 解密后明文配置
            assert params == {"region": "华东"}
            return [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]

        monkeypatch.setattr(data_adapter, "fetch", _fake_fetch)
        connector = Connector(engine=app_engine)
        out = await connector.execute(
            {"adapter_type": "tool.fetch", "input": {"connector_id": CN_ID, "params": {"region": "华东"}}},
            ctx=_ctx(),
        )
        assert out["count"] == 2
        assert out["rows"][0]["name"] == "A"
        assert out["domain_filtered"] is False  # 一期标注：raw rows 未按角色域过滤

    async def test_tool_fetch_unknown_connector_raises(self, app_engine: AsyncEngine) -> None:
        connector = Connector(engine=app_engine)
        with pytest.raises(ConnectorError, match="不存在"):
            await connector.execute(
                {"adapter_type": "tool.fetch", "input": {"connector_id": "cn-missing"}},
                ctx=_ctx(),
            )


# ── F7 (Task 2): 失败语义归一 + 错误分类 ─────────────────────────────────────


def test_connector_fetch_error_normalized_to_connector_error() -> None:
    """F7 (Task 2 D3): ConnectorFetchError ⊂ ConnectorError（code=connection）——
    chat_ep 422 名单（except ConnectorError）自动收口，连接类不再 fallthrough 500。"""
    from earp_server.connector import ConnectorError
    from earp_server.ontology.data_adapter import ConnectorFetchError

    assert issubclass(ConnectorFetchError, ConnectorError)
    err = ConnectorFetchError("REST 取数连接失败")
    assert err.code == "connection"


async def test_connector_error_codes_classify_failures(app_engine: AsyncEngine) -> None:
    """F7 (Task 2 D4): 错误分类码——unknown_capability / permission / 默认 validation。"""
    connector = Connector(engine=app_engine)
    with pytest.raises(ConnectorError) as ei:
        await connector.execute(
            {"adapter_type": "capability.call", "capability_id": "cap-nope", "input": {}},
            ctx=_ctx(role_id="f3-r1"),
        )
    assert ei.value.code == "unknown_capability"
    with pytest.raises(ConnectorError) as ei:
        await connector.execute(
            {"adapter_type": "capability.call", "capability_id": CAP_ID, "input": {}},
            ctx=_ctx(role_id="f3-r2"),
        )
    assert ei.value.code == "permission"
    with pytest.raises(ConnectorError) as ei:
        await connector.execute({"adapter_type": "qu.answer", "input": {}}, ctx=_ctx())
    assert ei.value.code == "validation"  # 默认分类（输入缺失）


async def test_flow_tool_fetch_connection_error_classified(app_engine: AsyncEngine, monkeypatch) -> None:
    """F7 (Task 2 D4): flow 内 tool.fetch 连接失败 → 200+status=failed 语义保持（不
    fallthrough 500），trace error_code=connection——前端可精确提示「连接失败」。"""
    from earp_server.conversation.chat_service import flow_chat
    from earp_server.ontology import data_adapter
    from earp_server.ontology.connector_service import create_connector

    await create_connector(
        app_engine,
        TENANT,
        connector_id="cn-f7-conn",
        adapter_type="rest",
        config={"base_url": "http://internal.example", "path": "/x", "method": "GET"},
    )

    async def _boom(cfg, params=None):
        raise data_adapter.ConnectorFetchError("REST 取数连接失败: http://internal.example/x")

    monkeypatch.setattr(data_adapter, "fetch", _boom)
    g = _flow_graph(
        {"id": "start", "type": "start", "data": {}},
        {"id": "t1", "type": "tool", "data": {"connector_id": "cn-f7-conn"}},
        {"id": "end", "type": "end", "data": {}},
        edges=[{"source": "start", "target": "t1"}, {"source": "t1", "target": "end"}],
    )
    app = await _flow_app(app_engine, g, "f7-tool-conn")
    result = await flow_chat(
        app_engine, TENANT, "f3-u1", "f3-r1", app, "q", None,
        base_llm=FakeLLM(), settings=_settings(),
    )
    assert result["status"] == ExecutionStatus.FAILED.value  # 200+failed 语义保持
    t1 = next(t for t in result["trace"] if t["node_id"] == "t1")
    assert t1["status"] == "failed"
    assert t1["error_code"] == "connection"
    assert "REST 取数连接失败" in (t1["error"] or "")


async def test_flow_capability_unknown_classified(app_engine: AsyncEngine) -> None:
    """F7 (Task 2 D4): flow 内 capability 不存在 → status=failed + error_code=unknown_capability。"""
    from earp_server.conversation.chat_service import flow_chat

    g = _flow_graph(
        {"id": "start", "type": "start", "data": {}},
        {
            "id": "c1",
            "type": "capability",
            "data": {"capability_call": {"capability_id": "cap-nope", "input": {}}},
        },
        {"id": "end", "type": "end", "data": {}},
        edges=[{"source": "start", "target": "c1"}, {"source": "c1", "target": "end"}],
    )
    app = await _flow_app(app_engine, g, "f7-cap-unknown")
    result = await flow_chat(
        app_engine, TENANT, "f3-u1", "f3-r1", app, "q", None,
        base_llm=FakeLLM(), settings=_settings(),
    )
    assert result["status"] == ExecutionStatus.FAILED.value
    c1 = next(t for t in result["trace"] if t["node_id"] == "c1")
    assert c1["error_code"] == "unknown_capability"


# ── flow_chat 集成 ──────────────────────────────────────────────────────────


async def _flow_app(app_engine: AsyncEngine, schema: dict, name: str) -> dict:
    return await chat_app_service.create_chat_app(
        app_engine, TENANT, "f3-u1", name, orchestration="flow", flow_schema=schema
    )


async def _wait_audit(engine: AsyncEngine, event_type: str, timeout_s: float = 3.0) -> bool:
    """轮询 audit_logs（EventBus fire-and-forget，handler 异步落库）。"""
    deadline = time.monotonic() + timeout_s
    while True:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            row = (
                await conn.execute(
                    text("SELECT 1 FROM audit_logs WHERE tenant_id = :t AND event_type = :et LIMIT 1"),
                    {"t": TENANT, "et": event_type},
                )
            ).first()
        if row:
            return True
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.05)


class TestFlowChatF3:
    async def test_flow_qu_to_llm_citations(self, app_engine: AsyncEngine, monkeypatch) -> None:
        """start→qu→llm→end：qu 输出 citations 供下游 {{#q1.citations#}} 引用。"""
        citations = [{"chunk_id": "c1", "title": "设备手册", "document_id": "doc-1"}]
        _fake_qu_chain(monkeypatch, citations=citations)
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "q1", "type": "qu", "data": {}},
            {"id": "l1", "type": "llm", "data": {"prompt": "引用资料：{{#q1.citations#}}"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[
                {"source": "start", "target": "q1"},
                {"source": "q1", "target": "l1"},
                {"source": "l1", "target": "end"},
            ],
        )
        app = await _flow_app(app_engine, g, "f3-qu-chain")
        llm = FakeLLM(text="已引用")
        result = await flow_chat(
            app_engine, TENANT, "f3-u1", "f3-r1", app, "CNC-01 是什么设备", None,
            base_llm=llm, settings=_settings(),
        )
        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["outputs"]["q1"]["selection"]["plan_name"] == "plan_fact"
        assert result["outputs"]["q1"]["citations"] == citations
        # 下游 llm 节点 prompt 中 {{#q1.citations#}} 已被 qu 输出替换
        assert "设备手册" in llm.calls[0]["prompt"]

    async def test_flow_capability_audit_events(self, app_engine: AsyncEngine) -> None:
        """start→capability→end：真实执行 + 审计事件（earp.capability.call.*）落 audit_logs。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {
                "id": "c1",
                "type": "capability",
                "data": {"capability_call": {"capability_id": CAP_ID, "input": {"msg": "hello"}}},
            },
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "c1"}, {"source": "c1", "target": "end"}],
        )
        app = await _flow_app(app_engine, g, "f3-cap-audit")
        bus = EventBus()
        bus.subscribe("earp.capability.*", audit_handler_factory(app_engine))
        result = await flow_chat(
            app_engine, TENANT, "f3-u1", "f3-r1", app, "q", None,
            base_llm=FakeLLM(), settings=_settings(), bus=bus,
        )
        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["outputs"]["c1"] == {"echo": {"msg": "hello"}}
        assert await _wait_audit(app_engine, "earp.capability.call.started")
        assert await _wait_audit(app_engine, "earp.capability.call.completed")

    async def test_flow_capability_permission_denied_403(self, app_engine: AsyncEngine) -> None:
        """PolicyLayer 权限门禁：角色无 required_permissions → HTTPException 403（透传非 500）。"""
        from fastapi import HTTPException

        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {
                "id": "c1",
                "type": "capability",
                "data": {"capability_call": {"capability_id": CAP_ID, "input": {"msg": "x"}}},
            },
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "c1"}, {"source": "c1", "target": "end"}],
        )
        app = await _flow_app(app_engine, g, "f3-cap-deny")
        bus = EventBus()
        bus.subscribe("earp.capability.*", audit_handler_factory(app_engine))
        with pytest.raises(HTTPException) as exc_info:
            await flow_chat(
                app_engine, TENANT, "f3-u1", "f3-r2", app, "q", None,
                base_llm=FakeLLM(), settings=_settings(), bus=bus,
            )
        assert exc_info.value.status_code == 403

    async def test_flow_tool_fetch(self, app_engine: AsyncEngine, monkeypatch) -> None:
        """start→tool→end：M3 连接体系取数（真加密配置 + mock fetch + params 模板替换）。"""
        from earp_server.ontology import connector_service, data_adapter

        await connector_service.create_connector(
            app_engine,
            TENANT,
            connector_id=CN_ID,
            adapter_type="rest",
            config={"base_url": "http://internal.example", "path": "/api/items", "method": "GET"},
        )

        async def _fake_fetch(cfg, params=None):
            return [{"id": 1, "name": f"item-{params.get('region')}"}]

        monkeypatch.setattr(data_adapter, "fetch", _fake_fetch)
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "t1", "type": "tool", "data": {"connector_id": CN_ID, "params": {"region": "{{query}}"}}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "t1"}, {"source": "t1", "target": "end"}],
        )
        app = await _flow_app(app_engine, g, "f3-tool-fetch")
        result = await flow_chat(
            app_engine, TENANT, "f3-u1", "f3-r1", app, "华东", None,
            base_llm=FakeLLM(), settings=_settings(),
        )
        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["outputs"]["t1"]["rows"] == [{"id": 1, "name": "item-华东"}]  # {{query}} 已替换
        assert result["outputs"]["t1"]["count"] == 1


# ── LLM 节点模型选择（model_config_id）──────────────────────────────────────


class TestLlmNodeModelSelect:
    def test_compile_llm_node_model_config_id_passes_through(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {
                "id": "l1", "type": "llm",
                "data": {"prompt": "p", "system": "你是设备助手", "model_config_id": "mc-node"},
            },
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        l1 = next(i for i in plan.sequence if i.node_id == "l1")
        assert l1.step.capability_call == {
            "adapter_type": "llm.prompt",
            "input": {"prompt": "p", "system": "你是设备助手", "model_config_id": "mc-node"},
        }

    async def test_resolve_model_override_roundtrip(self, app_engine: AsyncEngine) -> None:
        from earp_server.admin.model_service import create_model_config
        from earp_server.conversation.chat_service import resolve_model_override

        mc = await create_model_config(
            app_engine, TENANT, "ollama", "llm", "qwen-node", {"api_key": "k-123", "base_url": "http://internal.example"}
        )
        ov = await resolve_model_override(app_engine, TENANT, mc["config_id"])
        assert ov is not None
        assert ov["provider"] == "ollama"
        assert ov["model_name"] == "qwen-node"
        assert ov["api_key"] == "k-123"  # credentials 加密落库 → 解析后明文
        assert await resolve_model_override(app_engine, TENANT, "mc-missing") is None

    async def test_llm_prompt_uses_selected_model_config(self, app_engine: AsyncEngine, monkeypatch) -> None:
        from earp_server.admin.model_service import create_model_config

        mc = await create_model_config(
            app_engine, TENANT, "ollama", "llm", "qwen-node-select", {"api_key": "k-123", "base_url": "http://internal.example"}
        )
        created_overrides: list[dict] = []

        class _FakeModelLLM:
            def __init__(self, settings, *, model_override=None) -> None:
                created_overrides.append(model_override or {})

            async def complete(self, prompt, *, system="", temperature=0.7, max_tokens=None):
                return "node-answer"

        monkeypatch.setattr("earp_server.connector.LLMConnector", _FakeModelLLM)
        connector = Connector(engine=app_engine, settings=_settings())
        out = await connector.execute(
            {"adapter_type": "llm.prompt", "input": {"prompt": "hi", "model_config_id": mc["config_id"]}},
            ctx=_ctx(),
        )
        assert out == {"text": "node-answer"}
        assert created_overrides and created_overrides[0]["model_name"] == "qwen-node-select"
        assert created_overrides[0]["api_key"] == "k-123"  # 节点级 override 带上了解密凭据

    async def test_llm_prompt_unknown_model_config_raises(self, app_engine: AsyncEngine) -> None:
        connector = Connector(engine=app_engine, settings=_settings())
        with pytest.raises(ConnectorError, match="不存在"):
            await connector.execute(
                {"adapter_type": "llm.prompt", "input": {"prompt": "hi", "model_config_id": "mc-missing"}},
                ctx=_ctx(),
            )

    async def test_llm_prompt_no_model_config_uses_injected_llm(self, app_engine: AsyncEngine) -> None:
        llm = FakeLLM(text="default-answer")
        connector = Connector(engine=app_engine, llm=llm, settings=_settings())
        out = await connector.execute(
            {"adapter_type": "llm.prompt", "input": {"prompt": "hi", "system": "你是设备助手"}},
            ctx=_ctx(),
        )
        assert out == {"text": "default-answer"}
        assert llm.calls[0]["prompt"] == "hi"
        assert llm.calls[0]["system"] == "你是设备助手"  # 应用默认模型路径：system 透传


# ── note（注释）节点：纯标注、不连线、不执行 ──────────────────────────────────


class TestNoteNode:
    def test_note_node_compiles_and_skips_execution(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "n1", "type": "note", "data": {"text": "此处人工确认后需通知设备负责人"}},
            {"id": "l1", "type": "llm", "data": {"prompt": "p"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        plan = compile_flow_schema(g)  # note 断开 → 校验通过（可达性豁免）
        assert all(i.node_id != "n1" for i in plan.sequence)  # note 不产出执行项

    def test_note_node_with_edge_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "n1", "type": "note", "data": {"text": "t"}},
            {"id": "l1", "type": "llm", "data": {"prompt": "p"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[
                {"source": "start", "target": "l1"},
                {"source": "l1", "target": "n1"},
                {"source": "l1", "target": "end"},
            ],
        )
        with pytest.raises(WorkflowValidationError, match="注释节点不可有入边"):
            compile_flow_schema(g)

    def test_note_node_in_flow_node_types(self) -> None:
        from earp_server.orchestrator import workflow_dsl

        assert "note" in workflow_dsl.FLOW_NODE_TYPES
        # 空文本也允许（纯占位）；文本可选
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "n1", "type": "note", "data": {}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        assert plan is not None


class TestNodePosition:
    def test_node_position_accepted_and_not_in_execution(self) -> None:
        """节点 position{x,y}（ReactFlow 兼容）可保存、不影响执行序列。"""
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}, "position": {"x": 40, "y": 80}},
            {"id": "l1", "type": "llm", "data": {"prompt": "p"}, "position": {"x": 300, "y": 150}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "l1"}, {"source": "l1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        assert [i.node_id for i in plan.sequence] == ["l1"]  # 位置仅布局元数据


# ── 方案 C：QU 节点 use_llm 开关（false = 纯规则，跳过 LLM 升级） ──────────────


class TestQuNodeUseLlm:
    def test_compile_qu_use_llm_false(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "q1", "type": "qu", "data": {"use_llm": False}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "q1"}, {"source": "q1", "target": "end"}],
        )
        plan = compile_flow_schema(g)
        q1 = next(i for i in plan.sequence if i.node_id == "q1")
        assert q1.step.capability_call["input"]["use_llm"] is False
        assert q1.step.capability_call["input"]["query"] == "{{query}}"

    def test_compile_qu_use_llm_non_bool_rejected(self) -> None:
        g = _flow_graph(
            {"id": "start", "type": "start", "data": {}},
            {"id": "q1", "type": "qu", "data": {"use_llm": "yes"}},
            {"id": "end", "type": "end", "data": {}},
            edges=[{"source": "start", "target": "q1"}, {"source": "q1", "target": "end"}],
        )
        with pytest.raises(WorkflowValidationError, match="use_llm 必须是布尔值"):
            compile_flow_schema(g)

    async def test_qu_answer_use_llm_false_skips_upgrade(self, app_engine: AsyncEngine, monkeypatch) -> None:
        """use_llm=false → 不调 upgrade_with_llm（纯规则理解）。"""
        _fake_qu_chain(monkeypatch, citations=[{"chunk_id": "c1", "title": "t", "document_id": "d"}])

        async def _boom(*a, **k):
            raise AssertionError("upgrade_with_llm should not be called")

        monkeypatch.setattr("earp_server.ontology.understanding.upgrade_with_llm", _boom)
        connector = Connector(engine=app_engine, settings=_settings())
        out = await connector.execute(
            {"adapter_type": "qu.answer", "input": {"query": "CNC-01 是什么设备", "use_llm": False}},
            ctx=_ctx(),
        )
        assert out["selection"]["plan_name"] == "plan_fact"  # 纯规则链路出结果
