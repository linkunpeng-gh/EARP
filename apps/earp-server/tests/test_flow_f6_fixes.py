"""Chatflow F6 — 评估发现的最小修复回归（任务书 D3/D5：pytest 只补摸底/修复用例）。

四项修复（均在评估过程中发现，见 docs/chatflow-f6-evaluation-report.md 问题清单）：
1. 条件求值列表索引：`<node_id>.output.rows.0.status`（workflow_dsl._resolve）——
   此前仅支持 dict 路径，场景 A（设备状态行）/ B（chunk 首条）分支需要
2. 模板解析列表索引：`{{#node.output.rows.0.status#}}` / `{{#node.entities.0.mention#}}`
   （workflow_dsl.resolve_templates）——capability 节点取 qu/knowledge 输出首元素
3. qu.answer 输出 entities + 会话上下文最小接入（connector._execute_qu_answer /
   _history_context）——D3 摸底结论 (b) 档：指代消解「它→CNC-01」在 flow 内生效
4. checkpoint_blobs 幂等写（infra.checkpoint upsert）——resume 重放时 else 分支
   skipped 节点重写同名命名空间 → 唯一键冲突（唯一约束 500）
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.connector import Connector
from earp_server.orchestrator.multi_step import ExecutionStatus, MultiStepExecutor
from earp_server.orchestrator.types import InvokeContext, Step, StepResult
from earp_server.orchestrator.workflow_dsl import (
    ConditionEvaluationError,
    compile_flow_schema,
    evaluate_condition,
    resolve_templates,
)

TENANT = "f6-fix-t1"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def _seed_f6(app_engine: AsyncEngine) -> None:
    """f6-fix-t1 基线：user + CNC-01 设备实体（qu 实体识别 / 指代消解素材）。"""
    async def _seed() -> None:
        async with app_engine.begin() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
            await conn.execute(
                text(
                    "INSERT INTO users (user_id, tenant_id, name, email) "
                    "VALUES ('f6-u1', :t, 'f6-u1', 'f6-u1@e.io') ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )
            await conn.execute(
                text(
                    "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, attributes) "
                    "VALUES ('equipment', :t, '设备', 'object', '{}') ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )
            await conn.execute(
                text(
                    "INSERT INTO entities (entity_id, tenant_id, entity_type_id, name, business_code, "
                    "source_mode, status) VALUES "
                    "('ent-f6-cnc01', :t, 'equipment', 'CNC-01 数控机床', 'CNC-01', 'extracted', 'active') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"t": TENANT},
            )

    asyncio.run(_seed())


class FakeLLM:
    def __init__(self, text: str = "f6-answer") -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int | None = None):
        self.calls.append({"prompt": prompt, "system": system, "temperature": temperature, "max_tokens": max_tokens})
        return self.text


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://x/x", app_env="test")


def _ctx(session_id: str = "conv-f6") -> InvokeContext:
    return InvokeContext(
        tenant_id=TENANT,
        execution_id=uuid.uuid4().hex,
        session_id=session_id,
        user_id="f6-u1",
        role_id="r-f6",
        step=Step(step_id="start", capability_call={}),
    )


# ── 修复 1+2：条件 / 模板列表索引 ──────────────────────────────────────────


class TestListIndexPaths:
    POOL = {
        "c1": StepResult(
            step_id="c1",
            status="completed",
            output={
                "rows": [{"equipment_id": "CNC-01", "status": "faulty", "temperature": 78.5}],
                "count": 1,
                "domain_filtered": False,
            },
        ),
        "k1": StepResult(
            step_id="k1",
            status="completed",
            output={"chunks": [{"content": "x", "metadata": {"vip": True, "customer": "张伟"}}]},
        ),
    }

    def test_condition_list_index(self) -> None:
        """场景 A 分支：c1.output.rows.0.status == 'faulty'。"""
        assert evaluate_condition(
            {"left": "c1.output.rows.0.status", "op": "==", "right": "faulty"}, self.POOL
        )
        assert not evaluate_condition(
            {"left": "c1.output.rows.0.status", "op": "==", "right": "ok"}, self.POOL
        )

    def test_condition_list_index_nested_metadata(self) -> None:
        """场景 B 分支：k1.output.chunks.0.metadata.vip == true。"""
        assert evaluate_condition(
            {"left": "k1.output.chunks.0.metadata.vip", "op": "==", "right": True}, self.POOL
        )

    def test_condition_list_index_out_of_range_returns_none(self) -> None:
        """越界索引 → 路径解析 None → ConditionEvaluationError（不 crash）。"""
        with pytest.raises(ConditionEvaluationError):
            evaluate_condition({"left": "c1.output.rows.9.status", "op": "==", "right": "x"}, self.POOL)

    def test_template_list_index(self) -> None:
        """capability 节点取 qu 输出首实体：{{#c1.rows.0.equipment_id#}}（F3 简写）。"""
        out = resolve_templates("equip={{#c1.rows.0.equipment_id#}}", self.POOL)
        assert out == "equip=CNC-01"

    def test_template_list_index_dotted_metadata(self) -> None:
        out = resolve_templates("vip={{#k1.chunks.0.metadata.vip#}}", self.POOL)
        assert out == "vip=True"

    def test_template_list_index_out_of_range_kept_literal(self) -> None:
        """越界/缺失 → 原样保留（适配器/上游兜底，不静默吞掉）。"""
        out = resolve_templates("x={{#c1.rows.9.status#}}", self.POOL)
        assert out == "x={{#c1.rows.9.status#}}"


# ── 修复 3：qu.answer entities 输出 + 历史上下文（指代） ───────────────────


class TestQuAnswerF6:
    async def test_qu_answer_exposes_entities(self, app_engine: AsyncEngine, monkeypatch) -> None:
        """规则层实体提及透出：capability 节点 {{#qu.entities.0.mention#}} 取设备引用。"""
        import earp_server.ontology.planning as planning_mod
        import earp_server.ontology.understanding as understanding_mod
        from earp_server.ontology.understanding import EntityMention, Intent, RuleResult

        async def _fake_understand(engine, tenant_id, query, **kwargs):
            return RuleResult(
                intent=Intent.FACT,
                confidence=0.5,
                entities=[EntityMention(mention="CNC-01 数控机床", semantic_type="equipment")],
            )

        async def _fake_execute_plan(engine, tenant_id, role_id, query, structured_query, **kwargs):
            from earp_server.ontology.planning import PlanResult, PlanSelection

            return PlanSelection("plan_fact", lambda *a, **k: None), PlanResult(
                plan_name="plan_fact", evidence=[], citations=[]
            )

        monkeypatch.setattr(understanding_mod, "understand", _fake_understand)
        monkeypatch.setattr(planning_mod, "execute_plan", _fake_execute_plan)

        connector = Connector(engine=app_engine)
        out = await connector.execute(
            {"adapter_type": "qu.answer", "input": {"query": "CNC-01 温度异常"}}, ctx=_ctx()
        )
        assert out["entities"] == [{"mention": "CNC-01 数控机床", "semantic_type": "equipment"}]

    async def test_qu_answer_history_context_anaphora(self, app_engine: AsyncEngine) -> None:
        """D3 (b) 档最小实现：qu.answer 从会话历史推导 last_entities → 指代消解。

        会话历史含「CNC-01 温度异常」，本轮「它刚才还报警了」应映射到 CNC-01 实体。
        """
        from earp_server.conversation.conversation_service import add_message, create_conversation

        conv = await create_conversation(app_engine, TENANT, "f6-u1", "t")
        conv_id = str(conv["conversation_id"])
        # 第一轮用户消息（真实 understand 提取 CNC-01 实体——种子实体在库）
        await add_message(app_engine, TENANT, conv_id, "user", "CNC-01 温度异常", "f6-u1")
        await add_message(app_engine, TENANT, conv_id, "assistant", "已记录", "f6-u1")

        connector = Connector(engine=app_engine)
        ctx = _ctx(session_id=conv_id)
        # 直接调 _history_context（不 mock 理解链）：上一轮用户消息的规则实体
        context = await connector._history_context(ctx)
        assert context, "历史上下文应推导出 last_entities"
        assert any("CNC-01" in e["mention"] for e in context["last_entities"])

        # 端到端：本轮「它刚才还报警了」→ 指代解析到 CNC-01（真实 understand 规则层）
        out = await connector.execute(
            {"adapter_type": "qu.answer", "input": {"query": "它刚才还报警了"}}, ctx=ctx
        )
        mentions = [e["mention"] for e in out["entities"]]
        assert any("CNC-01" in m for m in mentions), f"指代未解析：{mentions}"


# ── 修复 4：checkpoint_blobs 幂等写（resume 重放） ─────────────────────────


class TestCheckpointResumeIdempotent:
    def _flow(self) -> dict:
        """复现场景 A 拓扑：start → s1 → cond1 → [true: c2 → h1] / [false: l2]。

        拓扑序：start, s1, cond1, c2, l2, h1, l1, end——turn1 挂起前 l2（else 分支）
        已产出 skipped + 写 checkpoint（plan:l2）；resume 重放时 l2 再次 skipped →
        同名命名空间重写 → 修复前 checkpoint_blobs 唯一键冲突（500）。
        """
        return {
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                {"id": "s1", "type": "step",
                 "data": {"capability_call": {"adapter_type": "demo.echo", "input": {"msg": "ok"}}}},
                {"id": "cond1", "type": "condition",
                 "data": {"condition": {"left": "s1.output.echo.msg", "op": "==", "right": "ok"}}},
                {"id": "c2", "type": "step",
                 "data": {"capability_call": {"adapter_type": "demo.echo", "input": {"msg": "pre"}}}},
                {"id": "h1", "type": "human_approval", "data": {"question": "确认？"}},
                {"id": "l1", "type": "llm", "data": {"prompt": "答复：{{#h1.output.reply#}}"}},
                {"id": "l2", "type": "llm", "data": {"prompt": "未命中分支：{{#s1.output.echo.msg#}}"}},
                {"id": "end", "type": "end", "data": {}},
            ],
            "edges": [
                {"source": "start", "target": "s1"},
                {"source": "s1", "target": "cond1"},
                {"source": "cond1", "target": "c2", "sourceHandle": "true"},
                {"source": "c2", "target": "h1"},
                {"source": "h1", "target": "l1"},
                {"source": "l1", "target": "end"},
                {"source": "cond1", "target": "l2", "sourceHandle": "false"},
                {"source": "l2", "target": "end"},
            ],
        }

    async def test_resume_replay_skipped_branch_no_conflict(self, app_engine: AsyncEngine) -> None:
        """turn1 挂起（else 分支 l2 已 skipped 写 checkpoint）→ resume 重放 l2 不冲突。"""
        plan = compile_flow_schema(self._flow())
        llm = FakeLLM()
        executor = MultiStepExecutor(app_engine, llm=llm)
        ctx = _ctx()

        results, state = await executor.execute(plan.steps, ctx, layers=[], plan=plan, flow_input={"query": "q"})
        assert state.status == ExecutionStatus.WAITING_HUMAN
        # else 分支 l2 已在挂起前产出 skipped（拓扑序先于 h1）——修复前 resume 重放会撞唯一键
        l2 = next(r for r in results if r.step_id == "l2")
        assert l2.status == "skipped"
        pool = {r.step_id: r for r in results if r.status == "completed"}
        assert "s1" in pool and "c2" in pool

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
        assert "同意" in llm.calls[0]["prompt"]  # {{#h1.output.reply#}} → 答复注入
