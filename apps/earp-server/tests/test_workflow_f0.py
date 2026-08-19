"""Chatflow F0 — workflow 真实化：声明式 JSON → compile → MultiStepExecutor 执行。

覆盖：顺序/分支（命中与未命中副作用断言）/嵌套/空图 + 非法图校验 + 条件求值。
镜像 test_saga 的 app fixture 模式（PG16+pgvector 单容器 + earp_app 角色）。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from earp_server.config import Settings
from earp_server.main import create_app
from earp_server.orchestrator.multi_step import ExecutionState, ExecutionStatus, MultiStepExecutor
from earp_server.orchestrator.types import InvokeContext, Step, StepResult
from earp_server.orchestrator.workflow_dsl import (
    ConditionEvaluationError,
    WorkflowValidationError,
    compile_workflow,
    evaluate_condition,
    validate_workflow,
)


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


# ── 图构造 helper ────────────────────────────────────────────────────────────


def _step_node(nid: str, msg: str, compensate: bool = False) -> dict:
    node = {
        "id": nid,
        "type": "step",
        "data": {"capability_call": {"adapter_type": "demo.echo", "input": {"msg": msg}}},
    }
    if compensate:
        node["data"]["compensate_call"] = {"adapter_type": "demo.echo", "input": {"msg": f"undo-{nid}"}}
    return node


def _fail_node(nid: str) -> dict:
    return {
        "id": nid,
        "type": "step",
        "data": {"capability_call": {"adapter_type": "nonexistent.fail", "input": {}}},
    }


def _cond_node(nid: str, left: str, op: str = "==", right: object = "") -> dict:
    return {"id": nid, "type": "condition", "data": {"condition": {"left": left, "op": op, "right": right}}}


def _graph(nodes: list[dict], edges: list[dict]) -> dict:
    return {"nodes": nodes, "edges": edges}


def _seq_graph(*msgs: str) -> dict:
    nodes = [{"id": "start", "type": "start", "data": {}}]
    edges = []
    prev = "start"
    for i, msg in enumerate(msgs, start=1):
        nid = f"n{i}"
        nodes.append(_step_node(nid, msg))
        edges.append({"source": prev, "target": nid})
        prev = nid
    nodes.append({"id": "end", "type": "end", "data": {}})
    edges.append({"source": prev, "target": "end"})
    return _graph(nodes, edges)


def _branch_graph(condition: dict) -> dict:
    nodes = [
        {"id": "start", "type": "start", "data": {}},
        _step_node("n1", "hello"),
        {"id": "c1", "type": "condition", "data": {"condition": condition}},
        _step_node("n2", "hit-branch"),
        _step_node("n3", "skip-branch"),
        {"id": "end", "type": "end", "data": {}},
    ]
    edges = [
        {"source": "start", "target": "n1"},
        {"source": "n1", "target": "c1"},
        {"source": "c1", "target": "n2", "sourceHandle": "true"},
        {"source": "c1", "target": "n3", "sourceHandle": "false"},
        {"source": "n2", "target": "end"},
        {"source": "n3", "target": "end"},
    ]
    return _graph(nodes, edges)


def _nested_graph(condition: dict) -> dict:
    nodes = [
        {"id": "start", "type": "start", "data": {}},
        _step_node("n1", "hello"),
        {"id": "c1", "type": "condition", "data": {"condition": condition}},
        _step_node("n2", "inner"),
        _cond_node("c2", "n2.output.echo.msg", "==", "wrong"),
        _step_node("n4", "deep-false"),
        _step_node("n5", "deep-true"),
        _step_node("n3", "outer-false"),
        {"id": "end", "type": "end", "data": {}},
    ]
    edges = [
        {"source": "start", "target": "n1"},
        {"source": "n1", "target": "c1"},
        {"source": "c1", "target": "n2", "sourceHandle": "true"},
        {"source": "c1", "target": "n3", "sourceHandle": "false"},
        {"source": "n2", "target": "c2"},
        {"source": "c2", "target": "n5", "sourceHandle": "true"},
        {"source": "c2", "target": "n4", "sourceHandle": "false"},
        {"source": "n3", "target": "end"},
        {"source": "n5", "target": "end"},
        {"source": "n4", "target": "end"},
    ]
    return _graph(nodes, edges)


def _ctx(step: Step) -> InvokeContext:
    return InvokeContext(
        tenant_id="t1",
        execution_id=_uid("exec-"),
        session_id=_uid("sess-"),
        user_id="u1",
        role_id="r1",
        step=step,
    )


def _pool(n1_output: dict) -> dict[str, StepResult]:
    return {
        "n1": StepResult(step_id="n1", status="completed", output=n1_output),
        "n2": StepResult(step_id="n2", status="skipped"),
    }


# ── 编译层（纯函数）───────────────────────────────────────────────────────────


class TestCompile:
    def test_sequential_compile(self) -> None:
        plan = compile_workflow(_seq_graph("a", "b"))
        assert plan.step_ids == ["n1", "n2"]
        assert [s.step_id for s in plan.steps] == ["n1", "n2"]
        # 顺序图无任何分支门控
        assert all(item.gate == frozenset() for item in plan.sequence)

    def test_branch_compile_both_branches_present(self) -> None:
        plan = compile_workflow(_branch_graph({"left": "n1.output.echo.msg", "op": "==", "right": "hello"}))
        # 两分支都编译进扁平列表（F0 语义：运行时 skip 未命中分支）
        assert plan.step_ids == ["n1", "n2", "n3"]
        gates = {item.node_id: item.gate for item in plan.sequence}
        assert gates["n2"] == frozenset({("cond:c1", "then")})
        assert gates["n3"] == frozenset({("cond:c1", "else")})

    def test_nested_compile_gates(self) -> None:
        plan = compile_workflow(_nested_graph({"left": "n1.output.echo.msg", "op": "==", "right": "hello"}))
        gates = {item.node_id: item.gate for item in plan.sequence}
        assert gates["n2"] == frozenset({("cond:c1", "then")})
        assert gates["n3"] == frozenset({("cond:c1", "else")})
        # c2 自身被 c1.then 门控；其分支再叠加 c2
        assert gates["n4"] == frozenset({("cond:c1", "then"), ("cond:c2", "else")})
        assert gates["n5"] == frozenset({("cond:c1", "then"), ("cond:c2", "then")})

    def test_join_merge_node_not_gated(self) -> None:
        """condition 两分支汇合到同一节点 → 该节点不受 c1 门控（交集为空）。"""
        nodes = [
            {"id": "start", "type": "start", "data": {}},
            _step_node("n1", "hello"),
            _cond_node("c1", "n1.output.echo.msg", "==", "hello"),
            _step_node("n2", "branch-a"),
            _step_node("n3", "branch-b"),
            _step_node("join", "after"),
            {"id": "end", "type": "end", "data": {}},
        ]
        edges = [
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "c1"},
            {"source": "c1", "target": "n2", "sourceHandle": "true"},
            {"source": "c1", "target": "n3", "sourceHandle": "false"},
            {"source": "n2", "target": "join"},
            {"source": "n3", "target": "join"},
            {"source": "join", "target": "end"},
        ]
        plan = compile_workflow(_graph(nodes, edges))
        gates = {item.node_id: item.gate for item in plan.sequence}
        assert gates["n2"] == frozenset({("cond:c1", "then")})
        assert gates["n3"] == frozenset({("cond:c1", "else")})
        assert gates["join"] == frozenset()  # 汇合点无条件执行

    def test_empty_graph_compile(self) -> None:
        plan = compile_workflow(
            _graph(
                [{"id": "start", "type": "start", "data": {}}, {"id": "end", "type": "end", "data": {}}],
                [{"source": "start", "target": "end"}],
            )
        )
        assert plan.steps == []
        assert plan.sequence == []


class TestValidate:
    def _errors(self, graph: dict) -> list[str]:
        return validate_workflow(graph)

    def test_cycle_detected(self) -> None:
        nodes = [
            {"id": "start", "type": "start", "data": {}},
            _step_node("n1", "a"),
            _step_node("n2", "b"),
            {"id": "end", "type": "end", "data": {}},
        ]
        graph = _graph(
            nodes,
            [
                {"source": "start", "target": "n1"},
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n1"},
                {"source": "n2", "target": "end"},
            ],
        )
        errors = self._errors(graph)
        assert any("cycle" in e for e in errors)

    def test_unknown_node_type(self) -> None:
        graph = _seq_graph("a")
        graph["nodes"].insert(1, {"id": "x1", "type": "llm", "data": {}})
        graph["edges"].append({"source": "start", "target": "x1"})
        graph["edges"].append({"source": "x1", "target": "n1"})
        assert any("unknown type" in e for e in self._errors(graph))

    def test_missing_start_and_end(self) -> None:
        graph = _seq_graph("a")
        graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "start"]
        assert any("exactly one start" in e for e in self._errors(graph))
        graph = _seq_graph("a")
        graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "end"]
        assert any("exactly one end" in e for e in self._errors(graph))

    def test_dangling_edge(self) -> None:
        graph = _seq_graph("a")
        graph["edges"].append({"source": "n1", "target": "ghost"})
        assert any("unknown target node" in e for e in self._errors(graph))

    def test_condition_handle_count(self) -> None:
        nodes = [
            {"id": "start", "type": "start", "data": {}},
            _step_node("n1", "hello"),
            _cond_node("c1", "n1.output.echo.msg", "==", "hello"),
            _step_node("n2", "a"),
            {"id": "end", "type": "end", "data": {}},
        ]
        edges = [
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "c1"},
            {"source": "c1", "target": "n2", "sourceHandle": "true"},  # 只有一条出边
            {"source": "n2", "target": "end"},
        ]
        assert any("expected 2 outgoing edges" in e for e in self._errors(_graph(nodes, edges)))

    def test_condition_bad_op(self) -> None:
        nodes = [
            {"id": "start", "type": "start", "data": {}},
            _step_node("n1", "hello"),
            _cond_node("c1", "n1.output.echo.msg", "matches", "x"),
            _step_node("n2", "a"),
            {"id": "end", "type": "end", "data": {}},
        ]
        edges = [
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "c1"},
            {"source": "c1", "target": "n2", "sourceHandle": "true"},
            {"source": "c1", "target": "n2", "sourceHandle": "false"},
            {"source": "n2", "target": "end"},
        ]
        errors = self._errors(_graph(nodes, edges))
        # pydantic Literal 报错不带输入值，但 loc 前缀已标明是 condition 的 op 字段
        assert any("condition c1: data.condition" in e for e in errors)

    def test_step_without_capability_call(self) -> None:
        graph = _seq_graph("a")
        graph["nodes"][1]["data"] = {}
        assert any("capability_call" in e for e in self._errors(graph))

    def test_fanout_rejected(self) -> None:
        graph = _seq_graph("a", "b")
        graph["edges"] = [
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "n2"},
            {"source": "n1", "target": "end"},  # n1 fan-out > 1（F0 无并行）
        ]
        assert any("F0 无并行" in e for e in self._errors(graph))

    def test_unreachable_node(self) -> None:
        graph = _seq_graph("a")
        graph["nodes"].append(_step_node("orphan", "x"))
        graph["edges"].append({"source": "orphan", "target": "end"})
        assert any("not reachable from start" in e for e in self._errors(graph))

    def test_duplicate_node_id(self) -> None:
        graph = _seq_graph("a")
        graph["nodes"].append(graph["nodes"][1])  # n1 重复
        assert any("duplicate node id" in e for e in self._errors(graph))

    def test_self_loop(self) -> None:
        graph = _seq_graph("a")
        graph["edges"].append({"source": "n1", "target": "n1"})
        assert any("self-loop" in e for e in self._errors(graph))

    def test_condition_left_path_shape(self) -> None:
        graph = _branch_graph({"left": "n1.msg", "op": "==", "right": "x"})  # 缺 output 段
        assert any("left must be" in e for e in self._errors(graph))

    def test_compile_raises_on_invalid(self) -> None:
        with pytest.raises(WorkflowValidationError):
            compile_workflow(_graph([], []))


# ── 条件求值（纯函数）─────────────────────────────────────────────────────────


class TestEvaluateCondition:
    POOL = _pool({"echo": {"msg": "hello"}, "count": 5, "tags": ["a", "b"]})

    def test_equality_ops(self) -> None:
        assert evaluate_condition({"left": "n1.output.echo.msg", "op": "==", "right": "hello"}, self.POOL)
        assert not evaluate_condition({"left": "n1.output.echo.msg", "op": "==", "right": "world"}, self.POOL)
        assert evaluate_condition({"left": "n1.output.echo.msg", "op": "!=", "right": "world"}, self.POOL)

    def test_numeric_ops_and_coercion(self) -> None:
        assert evaluate_condition({"left": "n1.output.count", "op": ">", "right": 3}, self.POOL)
        assert evaluate_condition({"left": "n1.output.count", "op": ">=", "right": 5}, self.POOL)
        assert evaluate_condition({"left": "n1.output.count", "op": "<=", "right": 5}, self.POOL)
        # 字符串数字与数字比较（JSON 输入友好）
        pool = _pool({"echo": {}, "count": "7"})
        assert evaluate_condition({"left": "n1.output.count", "op": ">", "right": 3}, pool)

    def test_contains(self) -> None:
        assert evaluate_condition({"left": "n1.output.echo.msg", "op": "contains", "right": "ell"}, self.POOL)
        assert evaluate_condition({"left": "n1.output.tags", "op": "contains", "right": "a"}, self.POOL)
        assert not evaluate_condition({"left": "n1.output.tags", "op": "contains", "right": "z"}, self.POOL)

    def test_exists(self) -> None:
        assert evaluate_condition({"left": "n1.output.echo.msg", "op": "exists", "right": None}, self.POOL)
        assert not evaluate_condition({"left": "n1.output.ghost", "op": "exists", "right": None}, self.POOL)
        # 未执行节点 → exists False（语义：路径不存在）
        assert not evaluate_condition({"left": "n9.output.x", "op": "exists", "right": None}, self.POOL)

    def test_missing_node_raises(self) -> None:
        with pytest.raises(ConditionEvaluationError):
            evaluate_condition({"left": "n9.output.echo.msg", "op": "==", "right": "x"}, self.POOL)

    def test_invalid_left_path_raises(self) -> None:
        with pytest.raises(ConditionEvaluationError):
            evaluate_condition({"left": "n1.msg", "op": "==", "right": "x"}, self.POOL)

    def test_none_resolution_raises(self) -> None:
        with pytest.raises(ConditionEvaluationError):
            evaluate_condition({"left": "n2.output.echo.msg", "op": "==", "right": "x"}, self.POOL)


# ── 执行层（app + migrated fixture，镜像 test_saga）──────────────────────────


class TestExecute:
    async def _run(self, app_url: str, graph: dict) -> tuple[list[StepResult], ExecutionState]:
        """镜像 test_saga：TestClient 生命周期内执行（lifespan 起停引擎）。"""
        plan = compile_workflow(graph)
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app):
            executor = MultiStepExecutor(app.state.engine)
            ctx = _ctx(Step(step_id="start", capability_call={}))
            return await executor.execute(plan.steps, ctx, layers=[], plan=plan)

    async def test_sequential_execution(self, migrated: str, app_url: str) -> None:
        results, state = await self._run(app_url, _seq_graph("first", "second"))
        assert [r.step_id for r in results] == ["n1", "n2"]
        assert all(r.status == "completed" for r in results)
        assert state.status == ExecutionStatus.COMPLETED
        assert results[1].output == {"echo": {"msg": "second"}}

    async def test_branch_taken_skips_other_branch(self, migrated: str, app_url: str) -> None:
        """Conditional 只走命中分支：未命中分支不执行（无副作用）。"""
        graph = _branch_graph({"left": "n1.output.echo.msg", "op": "==", "right": "hello"})
        results, state = await self._run(app_url, graph)
        by_id = {r.step_id: r for r in results}
        assert by_id["n1"].status == "completed"
        assert by_id["n2"].status == "completed"
        assert by_id["n3"].status == "skipped"  # 未命中 → 未 invoke
        assert by_id["n3"].output is None
        # skip 分支的 echo 绝不出现（无副作用）
        outputs = [r.output for r in results if r.status == "completed"]
        assert not any("skip-branch" in str(o) for o in outputs)
        assert state.status == ExecutionStatus.COMPLETED
        assert state.completed_steps == ["n1", "n2"]

    async def test_branch_not_taken(self, migrated: str, app_url: str) -> None:
        graph = _branch_graph({"left": "n1.output.echo.msg", "op": "==", "right": "nope"})
        results, state = await self._run(app_url, graph)
        by_id = {r.step_id: r for r in results}
        assert by_id["n2"].status == "skipped"
        assert by_id["n3"].status == "completed"
        assert by_id["n3"].output == {"echo": {"msg": "skip-branch"}}
        assert state.status == ExecutionStatus.COMPLETED

    async def test_nested_conditional(self, migrated: str, app_url: str) -> None:
        """c1 true → n2 → c2 false → n4；c1 false → n3。n4 执行、n3/n5 skip。"""
        graph = _nested_graph({"left": "n1.output.echo.msg", "op": "==", "right": "hello"})
        results, state = await self._run(app_url, graph)
        by_id = {r.step_id: r for r in results}
        assert by_id["n1"].status == "completed"
        assert by_id["n2"].status == "completed"
        assert by_id["n4"].status == "completed"
        assert by_id["n5"].status == "skipped"
        assert by_id["n3"].status == "skipped"
        assert state.status == ExecutionStatus.COMPLETED

    async def test_nested_condition_inside_skipped_branch_not_evaluated(self, migrated: str, app_url: str) -> None:
        """c1 false → c2 位于未命中分支，不求值（其引用 n2 未执行，若求值必抛错）。"""
        graph = _nested_graph({"left": "n1.output.echo.msg", "op": "==", "right": "nope"})
        results, state = await self._run(app_url, graph)
        by_id = {r.step_id: r for r in results}
        assert by_id["n3"].status == "completed"
        assert by_id["n2"].status == "skipped"
        assert by_id["n4"].status == "skipped"
        assert by_id["n5"].status == "skipped"
        assert state.status == ExecutionStatus.COMPLETED  # 非 FAILED → c2 确实未被求值

    async def test_empty_graph_execution(self, migrated: str, app_url: str) -> None:
        graph = _graph(
            [{"id": "start", "type": "start", "data": {}}, {"id": "end", "type": "end", "data": {}}],
            [{"source": "start", "target": "end"}],
        )
        results, state = await self._run(app_url, graph)
        assert results == []
        assert state.status == ExecutionStatus.COMPLETED

    async def test_condition_eval_error_fails(self, migrated: str, app_url: str) -> None:
        graph = _branch_graph({"left": "ghost.output.echo.msg", "op": "==", "right": "x"})
        results, state = await self._run(app_url, graph)
        assert results[-1].status == "failed"
        assert "condition" in (results[-1].error or "")
        assert state.status == ExecutionStatus.FAILED

    async def test_plan_path_saga_compensation(self, migrated: str, app_url: str) -> None:
        """plan 路径复用 Saga：命中分支补偿 + 失败步触发回滚。"""
        nodes = [
            {"id": "start", "type": "start", "data": {}},
            _step_node("n1", "do", compensate=True),
            _fail_node("n2"),
            {"id": "end", "type": "end", "data": {}},
        ]
        edges = [
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "end"},
        ]
        results, state = await self._run(app_url, _graph(nodes, edges))
        by_id = {r.step_id: r for r in results}
        assert by_id["n1"].status == "completed"
        assert by_id["n2"].status == "failed"
        assert state.status == ExecutionStatus.ROLLED_BACK
        assert len(state.rollback_results) == 1
        assert state.rollback_results[0]["step_id"] == "n1"
        assert state.rollback_results[0]["status"] == "rolled_back"
