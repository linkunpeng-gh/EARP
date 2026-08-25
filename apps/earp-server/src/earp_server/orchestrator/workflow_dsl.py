"""Workflow DSL — declarative graph JSON → compiled execution plan (Chatflow F0).

F0: 把死代码 DSL 真实化。graph-shaped schema（对齐 Dify/graphon + ReactFlow 兼容，
F1 flow_schema JSONB 直接存此形状）:

    {"nodes": [{"id", "type", "data"}],
     "edges": [{"source", "target", "sourceHandle"}]}

compile_workflow(graph) → CompiledWorkflow（线性执行序 + 分支门控元数据），由
MultiStepExecutor._execute_plan 消费：Conditional 运行时求值、未命中分支 skip
（不 invoke、无副作用）。

F0 节点白名单: start / end / step / condition（一期无循环/并行，非 condition 节点
出边 ≤1；condition 恰 2 出边，sourceHandle ∈ {true, false} 各一）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from earp_server.orchestrator.types import Step, StepResult

# ── JSON Schema（graph-shaped）────────────────────────────────────────────────


class WorkflowNode(BaseModel):
    id: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    # Chatflow 画布位置（ReactFlow 兼容 {x, y}）：缺省 → 前端自动拓扑布局
    position: dict[str, float] | None = None


class WorkflowEdge(BaseModel):
    source: str
    target: str
    sourceHandle: str | None = None


class WorkflowGraph(BaseModel):
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge] = Field(default_factory=list)
    # F7 (Task 3 D5): 显式指定答案节点（可选）——flow_chat 用其输出作最终答复；
    # 缺省 None → 回落「回答节点优先，兜底最后完成节点」（存量兼容）
    answer_from: str | None = None


class ConditionExpr(BaseModel):
    """Structured runtime condition. left = '<node_id>.output.<path>' (F0 无右值引用)."""

    left: str
    op: Literal["==", "!=", ">", ">=", "<", "<=", "contains", "exists"]
    right: Any = None


NODE_TYPES: frozenset[str] = frozenset({"start", "end", "step", "condition"})
# Chatflow F1 声明层白名单（设计稿 §3 全节点类型）：F0 执行引擎只实现 step/condition，
# 扩展类型（llm/knowledge/…）F1 可存（结构校验），F2+ 节点适配层各自实现执行。
FLOW_NODE_TYPES: frozenset[str] = NODE_TYPES | frozenset(
    # capability = step 的声明别名（设计稿 §3 Capability 节点，data.capability_call 同 step 校验）
    {"capability", "llm", "knowledge", "qu", "chat_history", "human_approval", "tool", "mcp", "note", "answer"}
)
CONDITION_HANDLES: frozenset[str] = frozenset({"true", "false"})
BranchSide = Literal["then", "else", "success", "error"]


class WorkflowValidationError(ValueError):
    """Raised by compile_workflow when the graph violates F0 invariants."""


class ConditionEvaluationError(RuntimeError):
    """Raised by evaluate_condition when a path cannot be resolved at runtime."""


# ── 编译产物 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StepExec:
    """A capability step in linear execution order."""

    node_id: str
    step: Step
    gate: frozenset[tuple[str, BranchSide]] = frozenset()


@dataclass(frozen=True)
class CondExec:
    """A runtime decision point: evaluate condition → choose then/else."""

    node_id: str
    branch_id: str
    condition: ConditionExpr
    gate: frozenset[tuple[str, BranchSide]] = frozenset()


ExecItem = StepExec | CondExec


@dataclass
class CompiledWorkflow:
    """Linear execution plan consumed by MultiStepExecutor._execute_plan.

    gate（分支上下文）: (branch_id, side) 集合——节点被条件 c 门控 ⟺ 所有路径
    都必须经过 c 的某分支边。运行时 chosen[branch_id] == side 全满足才执行。
    """

    sequence: list[ExecItem]
    steps: list[Step] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)
    step_index: dict[str, int] = field(default_factory=dict)
    # 应用中心：节点成功/失败双分支——step_id → branch_id（节点存在 sourceHandle='error' 出边）
    result_branches: dict[str, str] = field(default_factory=dict)
    # 应用中心：回答节点（answer）——flow_chat 优先取最后完成的回答节点文本作为最终答复
    answer_steps: frozenset[str] = frozenset()
    # F7 (Task 3 D5): 显式指定答案节点（可选）——flow_chat 用它取 answer（text 优先否则
    # JSON 摘要）；None → 缺省回落（answer_steps → 最后完成节点），存量兼容
    answer_from: str | None = None


# ── 校验 ─────────────────────────────────────────────────────────────────────


def validate_workflow(
    graph: dict[str, Any] | WorkflowGraph,
    *,
    allowed_types: frozenset[str] = NODE_TYPES,
) -> list[str]:
    """Return a list of validation errors (empty = valid). F5a 前端校验复用。

    allowed_types: 节点类型白名单。F0 默认 NODE_TYPES；F1 声明层（flow_schema）
    传 FLOW_NODE_TYPES（设计稿 §3 全量）——扩展类型只做通用图结构校验，
    节点级 data 校验由对应节点适配层（F2+）负责。
    """
    errors: list[str] = []
    if isinstance(graph, WorkflowGraph):
        g = graph
    else:
        try:
            g = WorkflowGraph.model_validate(graph)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                errors.append(f"schema error at {loc}: {err['msg']}")
            return errors

    node_ids = [n.id for n in g.nodes]
    by_id: dict[str, WorkflowNode] = {n.id: n for n in g.nodes}

    # F7 (Task 3 D5): answer_from 显式答案节点必须存在（编译期校验，发布门禁提前拦截）
    if g.answer_from is not None and g.answer_from not in by_id:
        errors.append(f"answer_from: 未知节点 {g.answer_from!r}（flow_schema 顶层 answer_from 需指向已有节点）")

    # node id 唯一
    seen: set[str] = set()
    for nid in node_ids:
        if nid in seen:
            errors.append(f"duplicate node id: {nid}")
        seen.add(nid)

    # 节点类型白名单
    for n in g.nodes:
        if n.type not in allowed_types:
            errors.append(f"node {n.id}: unknown type {n.type!r} (allowed: {sorted(allowed_types)})")

    # 恰一 start；终点 = end 或 answer（Dify 式：可仅以回答节点收尾，不强制 end）
    starts = [n.id for n in g.nodes if n.type == "start"]
    ends = [n.id for n in g.nodes if n.type == "end"]
    answers = [n.id for n in g.nodes if n.type == "answer"]
    if len(starts) != 1:
        errors.append(f"expected exactly one start node, got {len(starts)}")
    if len(ends) > 1:
        errors.append(f"expected at most one end node, got {len(ends)}")
    if not ends and not answers:
        errors.append("flow needs at least one terminal node (end 或 answer)")
    start_id = starts[0] if starts else None
    end_id = ends[0] if ends else None

    # 边引用存在 / 无自环 / 无重复边
    incoming: dict[str, list[WorkflowEdge]] = {nid: [] for nid in node_ids}
    outgoing: dict[str, list[WorkflowEdge]] = {nid: [] for nid in node_ids}
    edge_keys: set[tuple[str, str, str | None]] = set()
    missing_edge_ref = False
    for e in g.edges:
        if e.source not in by_id:
            errors.append(f"edge {e.source}->{e.target}: unknown source node")
            missing_edge_ref = True
        if e.target not in by_id:
            errors.append(f"edge {e.source}->{e.target}: unknown target node")
            missing_edge_ref = True
        if e.source not in by_id or e.target not in by_id:
            continue
        if e.source == e.target:
            errors.append(f"edge {e.source}->{e.target}: self-loop")
        key = (e.source, e.target, e.sourceHandle)
        if key in edge_keys:
            errors.append(f"duplicate edge: {key}")
        edge_keys.add(key)
        incoming[e.target].append(e)
        outgoing[e.source].append(e)

    # start/end 边约束
    if start_id is not None:
        if incoming[start_id]:
            errors.append("start node must have no incoming edges")
        if not outgoing[start_id] and len(node_ids) > 1:
            errors.append("start node must have an outgoing edge")
    if end_id is not None:
        if outgoing[end_id]:
            errors.append("end node must have no outgoing edges")
    # answer（回答）节点 = 终点：无出边；text 模板必填（字符串）
    for n in g.nodes:
        if n.type == "answer":
            if outgoing.get(n.id):
                errors.append(f"answer {n.id}: 回答节点是终点，不允许出边")
            text = n.data.get("text")
            if text is None or not isinstance(text, str) or not text.strip():
                errors.append(f"answer {n.id}: data.text (回答模板字符串) 必填")

    # note（注释）节点：纯标注、不参与执行——不可连线（无入边无出边）
    for n in g.nodes:
        if n.type == "note":
            if incoming.get(n.id):
                errors.append(f"note {n.id}: 注释节点不可有入边（纯标注，不连线）")
            if outgoing.get(n.id):
                errors.append(f"note {n.id}: 注释节点不可有出边（纯标注，不连线）")

    # 节点级约束（F0: 无并行 fan-out——所有非 condition 节点；condition 恰 2 分支边；
    # step 必带 capability_call；扩展类型只做通用结构校验）
    for n in g.nodes:
        outs = outgoing.get(n.id, [])
        if n.type == "condition":
            if any(e.sourceHandle is None for e in outs):
                errors.append(f"condition {n.id}: branch edges must declare sourceHandle true/false")
            handles = sorted(e.sourceHandle or "" for e in outs)
            if len(outs) != 2 or handles != ["false", "true"]:
                errors.append(
                    f"condition {n.id}: expected 2 outgoing edges with sourceHandle true/false, got {handles}"
                )
            cond = n.data.get("condition")
            if cond is None:
                errors.append(f"condition {n.id}: data.condition missing")
            elif not isinstance(cond, dict):
                errors.append(f"condition {n.id}: data.condition must be an object")
            else:
                try:
                    ConditionExpr.model_validate(cond)
                except ValidationError as exc:
                    for err in exc.errors():
                        loc = ".".join(str(p) for p in err["loc"])
                        errors.append(f"condition {n.id}: data.condition {loc}: {err['msg']}")
                left = cond.get("left", "")
                parts = left.split(".")
                if len(parts) < 2 or parts[1] != "output":
                    errors.append(f"condition {n.id}: left must be '<node_id>.output.<path>', got {left!r}")
        else:
            # 应用中心：可执行节点支持成功/失败双分支（sourceHandle ''=成功、'error'=失败）
            # 规则：出边 ≤2；2 条时必须一 '' 一 'error'；1 条时必须 ''（成功）——error-only 拒绝
            handles = sorted(e.sourceHandle or "" for e in outs)
            if len(outs) > 2:
                errors.append(f"{n.type} {n.id}: at most 2 outgoing edges (success/error), got {len(outs)}")
            elif len(outs) == 2 and handles != ["", "error"]:
                errors.append(f"{n.type} {n.id}: 双分支出边必须 sourceHandle ''(成功)+'error'(失败)，got {handles}")
            elif len(outs) == 1 and handles == ["error"]:
                errors.append(f"{n.type} {n.id}: 只有失败分支边（缺少成功边 ''）")
            if n.type == "step":
                if not isinstance(n.data.get("capability_call"), dict):
                    errors.append(f"step {n.id}: data.capability_call (dict) required")
            elif n.type == "capability":
                # F3: 兼容 step 别名（capability_call）与 D4 新形状（input）
                if not isinstance(n.data.get("capability_call"), dict) and not isinstance(n.data.get("input"), dict):
                    errors.append(f"capability {n.id}: data.capability_call 或 data.input (dict) required")

    # 无环 + 全节点可达（仅当引用/唯一性错误不存在时才有意义）
    if start_id and end_id and len(by_id) == len(node_ids) and not missing_edge_ref:
        order = _topo_order(node_ids, outgoing, incoming)
        if order is None:
            errors.append("graph contains a cycle (F0: DAG only)")
        else:
            from_start = _reachable(start_id, outgoing)
            # 终点集合 = end ∪ answer（回答节点也是终点）——反向可达性取并集
            terminals = [nid for nid in node_ids if by_id[nid].type in ("end", "answer")]
            to_terminal: set[str] = set()
            for tid in terminals:
                to_terminal |= _reachable_backward(tid, incoming)
            for nid in node_ids:
                if by_id[nid].type == "note":
                    continue  # 注释节点不与图相连，豁免可达性
                if nid not in from_start:
                    errors.append(f"node {nid}: not reachable from start")
                if nid not in to_terminal:
                    errors.append(f"node {nid}: cannot reach end/answer")

    return errors


def _topo_order(
    node_ids: list[str],
    outgoing: dict[str, list[WorkflowEdge]],
    incoming: dict[str, list[WorkflowEdge]],
) -> list[str] | None:
    """Kahn topological sort. Returns None when the graph has a cycle."""
    from collections import deque

    indeg = {nid: len(incoming[nid]) for nid in node_ids}
    queue: deque[str] = deque(nid for nid, deg in indeg.items() if deg == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for e in outgoing[nid]:
            indeg[e.target] -= 1
            if indeg[e.target] == 0:
                queue.append(e.target)
    return order if len(order) == len(node_ids) else None


def _reachable(start: str, outgoing: dict[str, list[WorkflowEdge]]) -> set[str]:
    from collections import deque

    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        nid = queue.popleft()
        if nid in seen:
            continue
        seen.add(nid)
        queue.extend(e.target for e in outgoing.get(nid, []))
    return seen


def _reachable_backward(end: str, incoming: dict[str, list[WorkflowEdge]]) -> set[str]:
    from collections import deque

    seen: set[str] = set()
    queue: deque[str] = deque([end])
    while queue:
        nid = queue.popleft()
        if nid in seen:
            continue
        seen.add(nid)
        queue.extend(e.source for e in incoming.get(nid, []))
    return seen


# ── 编译 ─────────────────────────────────────────────────────────────────────


def validate_flow_schema(schema: dict[str, Any]) -> list[str]:
    """Chatflow F1: flow_schema 声明层校验（节点类型白名单 = 设计稿 §3 全量）。

    仅结构校验（白名单/边/无环/可达）；节点级 data 校验由 F2+ 适配层负责。
    """
    return validate_workflow(schema, allowed_types=FLOW_NODE_TYPES)


NodeBuilder = Callable[[WorkflowNode, frozenset[tuple[str, BranchSide]]], ExecItem | None]

# Chatflow F2 对话节点适配器映射（编译为 StepExec → Connector 适配器）
_DIALOGUE_ADAPTERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "llm": ("llm.prompt", ("prompt", "system", "temperature", "max_tokens", "model_config_id")),
    "knowledge": ("knowledge.search", ("query", "kb_ids", "data_domain_ids", "top_k")),
    "chat_history": ("chat.history", ("turns",)),
}
# F1 声明可存、F2/F3 执行未实现的节点类型（F4 或后续适配层）
_UNIMPLEMENTED_NODE_TYPES: frozenset[str] = frozenset({"mcp"})


def _step_from_data(node: WorkflowNode) -> Step:
    data = node.data
    return Step(
        step_id=node.id,
        capability_call=data["capability_call"],
        retry_config=data.get("retry_config"),
        timeout_seconds=data.get("timeout_seconds"),
        compensate_call=data.get("compensate_call"),
    )


def _condition_exec(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> CondExec:
    return CondExec(
        node_id=node.id,
        branch_id=f"cond:{node.id}",
        condition=ConditionExpr.model_validate(node.data["condition"]),
        gate=gate,
    )


def _f0_node_builder(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> ExecItem | None:
    if node.type == "step":
        return StepExec(node_id=node.id, step=_step_from_data(node), gate=gate)
    if node.type == "condition":
        return _condition_exec(node, gate)
    return None  # start/end 不产出执行项


def _capability_exec(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> StepExec:
    """Chatflow F3: capability 节点 → capability.call 适配器（注册表校验 + 权限门禁 + 审计）。

    兼容两种 authoring 形状（D4）：
    - step 别名（F2）: data.capability_call = {capability_id, input}（显式 adapter_type 保持 step 行为）
    - 新形状: data.input = {capability_id, input}
    capability_id 归一化到顶层（PolicyLayer 权限查 capability_call.capability_id 免改）。
    """
    data = node.data
    call = data.get("capability_call")
    if isinstance(call, dict) and call.get("adapter_type") and call.get("adapter_type") != "capability.call":
        # 显式 adapter 形状（demo.echo 等）——保持 step 行为（F2 兼容）
        return StepExec(node_id=node.id, step=_step_from_data(node), gate=gate)
    cid = ""
    cap_input: dict[str, Any] = {}
    if isinstance(call, dict):
        cid = str(call.get("capability_id") or "")
        inner = call.get("input")
        cap_input = inner if isinstance(inner, dict) else {}
    elif isinstance(data.get("input"), dict):
        new_input = data["input"]
        cid = str(new_input.get("capability_id") or "")
        inner = new_input.get("input")
        cap_input = inner if isinstance(inner, dict) else {}
    if not cid:
        raise WorkflowValidationError(
            "workflow validation failed:\n"
            f"- node {node.id}: capability 节点需 capability_id（data.capability_call 或 data.input）"
        )
    return StepExec(
        node_id=node.id,
        step=Step(
            step_id=node.id,
            capability_call={"adapter_type": "capability.call", "capability_id": cid, "input": cap_input},
        ),
        gate=gate,
    )


def _qu_exec(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> StepExec:
    """Chatflow F3: qu 节点 → qu.answer 适配器（understand → select_plan → execute_plan）。"""
    query = node.data.get("query", "{{query}}")
    if not isinstance(query, str):
        raise WorkflowValidationError(f"workflow validation failed:\n- node {node.id}: qu data.query 必须是字符串模板")
    input_: dict[str, Any] = {"query": query}
    turns = node.data.get("context_turns")
    if turns is not None:
        try:
            input_["context_turns"] = int(turns)
        except (TypeError, ValueError):
            raise WorkflowValidationError(
                f"workflow validation failed:\n- node {node.id}: qu data.context_turns 必须是整数"
            ) from None
    # 方案 C：use_llm 开关（false = 纯规则理解，跳过 LLM 升级；缺省 = 启用/升级）
    use_llm = node.data.get("use_llm", True)
    if not isinstance(use_llm, bool):
        raise WorkflowValidationError(f"workflow validation failed:\n- node {node.id}: qu data.use_llm 必须是布尔值")
    if not use_llm:
        input_["use_llm"] = False
    return StepExec(
        node_id=node.id,
        step=Step(step_id=node.id, capability_call={"adapter_type": "qu.answer", "input": input_}),
        gate=gate,
    )


def _tool_exec(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> StepExec:
    """Chatflow F3: tool 节点 → tool.fetch 适配器（M3 连接体系取数）。"""
    connector_id = node.data.get("connector_id")
    if not isinstance(connector_id, str) or not connector_id.strip():
        raise WorkflowValidationError(
            f"workflow validation failed:\n- node {node.id}: tool 节点需 data.connector_id（非空字符串）"
        )
    input_: dict[str, Any] = {"connector_id": connector_id}
    params = node.data.get("params")
    if isinstance(params, dict):
        input_["params"] = params
    return StepExec(
        node_id=node.id,
        step=Step(step_id=node.id, capability_call={"adapter_type": "tool.fetch", "input": input_}),
        gate=gate,
    )


def _human_approval_exec(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> StepExec:
    """Chatflow F4: human_approval 节点 → human.approval 适配器（挂起等待人工答复）。

    data.question（模板表达式）可选——默认「请确认是否继续」；恢复时答复注入
    {{#node.output.reply#}} 供下游引用。
    """
    input_: dict[str, Any] = {}
    question = node.data.get("question")
    if question is not None:
        if not isinstance(question, str):
            raise WorkflowValidationError(
                f"workflow validation failed:\n- node {node.id}: human_approval data.question 必须是字符串模板"
            )
        input_["question"] = question
    return StepExec(
        node_id=node.id,
        step=Step(step_id=node.id, capability_call={"adapter_type": "human.approval", "input": input_}),
        gate=gate,
    )


def _answer_exec(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> StepExec:
    """应用中心：回答节点 → answer.output 适配器（Dify 式终点——输出模板文本）。

    data.text 为模板字符串（{{query}} / {{#node.output#}} / {{#node.error#}} 等），
    运行时 resolve_templates 解析；flow_chat 取最后完成的回答节点文本为最终答复。
    """
    return StepExec(
        node_id=node.id,
        step=Step(
            step_id=node.id,
            capability_call={"adapter_type": "answer.output", "input": {"text": node.data.get("text", "{{query}}")}},
        ),
        gate=gate,
    )


def _flow_node_builder(node: WorkflowNode, gate: frozenset[tuple[str, BranchSide]]) -> ExecItem | None:
    """Chatflow F2/F3: flow_schema 节点 → 执行项（节点映射为适配器 Step）。"""
    if node.type == "step":
        return StepExec(node_id=node.id, step=_step_from_data(node), gate=gate)
    if node.type == "capability":
        return _capability_exec(node, gate)
    if node.type in _DIALOGUE_ADAPTERS:
        adapter, keys = _DIALOGUE_ADAPTERS[node.type]
        input_: dict[str, Any] = {k: node.data[k] for k in keys if k in node.data}
        return StepExec(
            node_id=node.id,
            step=Step(step_id=node.id, capability_call={"adapter_type": adapter, "input": input_}),
            gate=gate,
        )
    if node.type == "qu":
        return _qu_exec(node, gate)
    if node.type == "tool":
        return _tool_exec(node, gate)
    if node.type == "human_approval":
        return _human_approval_exec(node, gate)
    if node.type == "answer":
        return _answer_exec(node, gate)
    if node.type == "condition":
        return _condition_exec(node, gate)
    if node.type in _UNIMPLEMENTED_NODE_TYPES:
        raise WorkflowValidationError(
            f"workflow validation failed:\n- node {node.id}: 节点类型 {node.type!r} 未实现（F4 或后续）"
        )
    return None  # start/end


def _compile_graph(
    g: WorkflowGraph,
    builder: NodeBuilder,
) -> CompiledWorkflow:
    """共享编译内核：拓扑序 + gate 门控前向计算 + 线性执行序。"""
    by_id = {n.id: n for n in g.nodes}
    incoming: dict[str, list[WorkflowEdge]] = {n.id: [] for n in g.nodes}
    outgoing: dict[str, list[WorkflowEdge]] = {n.id: [] for n in g.nodes}
    for e in g.edges:
        incoming[e.target].append(e)
        outgoing[e.source].append(e)

    node_ids = list(by_id.keys())
    order = _topo_order(node_ids, outgoing, incoming)
    if order is None:  # pragma: no cover — validate_workflow 已拒绝
        raise WorkflowValidationError("workflow validation failed:\n- graph contains a cycle")
    start_id = next(n.id for n in g.nodes if n.type == "start")

    # gate 前向计算：join（多入边）处取各入边上下文交集
    gate: dict[str, frozenset[tuple[str, BranchSide]]] = {start_id: frozenset()}

    def _is_result_branch_source(nid: str) -> bool:
        """节点存在 sourceHandle='error' 出边 → 结果双分支源（成功/失败）。"""
        return any(e.sourceHandle == "error" for e in outgoing.get(nid, []))

    for nid in order:
        if nid == start_id:
            continue
        contexts: list[frozenset[tuple[str, BranchSide]]] = []
        empty_gate: frozenset[tuple[str, BranchSide]] = frozenset()
        for e in incoming[nid]:
            ctx = gate.get(e.source, empty_gate)
            if by_id[e.source].type == "condition":
                side: BranchSide = "then" if e.sourceHandle == "true" else "else"
                branch_edge: frozenset[tuple[str, BranchSide]] = frozenset({(f"cond:{e.source}", side)})
                ctx = ctx | branch_edge
            elif _is_result_branch_source(e.source):
                rside: BranchSide = "error" if e.sourceHandle == "error" else "success"
                rbranch: frozenset[tuple[str, BranchSide]] = frozenset({(f"result:{e.source}", rside)})
                ctx = ctx | rbranch
            contexts.append(ctx)
        if not contexts:
            gate[nid] = frozenset[tuple[str, BranchSide]]()
            continue
        merged: frozenset[tuple[str, BranchSide]] = contexts[0]
        for other in contexts[1:]:
            merged = merged & other
        gate[nid] = merged

    # 线性执行序（start/end 不产出执行项）+ 结果双分支登记 + 回答节点登记
    sequence: list[ExecItem] = []
    result_branches: dict[str, str] = {}
    answer_steps: set[str] = set()
    for nid in order:
        node = by_id[nid]
        if _is_result_branch_source(nid):
            result_branches[nid] = f"result:{nid}"
        if node.type == "answer":
            answer_steps.add(nid)
        item = builder(node, gate[nid])
        if item is not None:
            sequence.append(item)

    # 命令能力审批门禁（D1）：flow 内显式含 human_approval 节点 → 该 flow 的所有 command
    # 能力视为「已人工把关」（能力层强制审批跳过，避免双审批——场景 A 的 c2/c3 兼容：
    # 显式 human_approval 即治理，即使其位于该命令能力之后也视为已把关）。
    # 无 human_approval 的 flow 调用 command 能力则交由能力层兜底强制审批（Task 1）。
    # 作者若已在能力节点显式声明 already_approved，保持原值。
    if any(n.type == "human_approval" for n in g.nodes):
        for item in sequence:
            if not isinstance(item, StepExec):
                continue
            call = item.step.capability_call
            if call.get("adapter_type") == "capability.call" and not call.get("already_approved"):
                call["already_approved"] = True

    steps = [item.step for item in sequence if isinstance(item, StepExec)]
    step_ids = [item.node_id for item in sequence if isinstance(item, StepExec)]
    return CompiledWorkflow(
        sequence=sequence,
        steps=steps,
        step_ids=step_ids,
        step_index={nid: i for i, nid in enumerate(step_ids)},
        result_branches=result_branches,
        answer_steps=frozenset(answer_steps),
        answer_from=g.answer_from,  # F7 (Task 3 D5): 显式答案节点透传给 flow_chat
    )


def compile_workflow(graph: dict[str, Any] | WorkflowGraph) -> CompiledWorkflow:
    """F0: Validate + compile a graph JSON into a linear execution plan（step/condition）。"""
    errors = validate_workflow(graph)
    if errors:
        raise WorkflowValidationError("workflow validation failed:\n" + "\n".join(f"- {e}" for e in errors))
    g = graph if isinstance(graph, WorkflowGraph) else WorkflowGraph.model_validate(graph)
    return _compile_graph(g, _f0_node_builder)


def compile_flow_schema(schema: dict[str, Any] | WorkflowGraph) -> CompiledWorkflow:
    """Chatflow F2/F3: 编译 flow_schema（设计稿 §3 全节点类型白名单）。

    对话节点（llm/knowledge/chat_history）映射为适配器 Step（Connector 执行）；
    F3：qu → qu.answer / capability → capability.call / tool → tool.fetch；
    condition 复用 F0 CondExec；human_approval/mcp 报「未实现（F4 或后续）」明确错误。
    """
    errors = validate_workflow(schema, allowed_types=FLOW_NODE_TYPES)
    if errors:
        raise WorkflowValidationError("workflow validation failed:\n" + "\n".join(f"- {e}" for e in errors))
    g = schema if isinstance(schema, WorkflowGraph) else WorkflowGraph.model_validate(schema)
    return _compile_graph(g, _flow_node_builder)


# ── 变量引用模板（F2）───────────────────────────────────────────────────────

_TEMPLATE_RE = re.compile(r"\{\{(?:#([\w.]+)#|([\w.]+))\}\}")


def resolve_templates(
    value: Any,
    pool: dict[str, StepResult],
    flow_input: dict[str, Any] | None = None,
) -> Any:
    """递归替换字符串中的变量引用（F2 对话节点输入）。

    - ``{{query}}`` → flow_input['query']（图输入）
    - ``{{#node_id.output#}}`` / ``{{#node_id.output.a.b#}}`` → pool 中已完成节点输出
    - ``{{#node_id.a#}}``（F3 简写，省略 .output. 段）→ 同一路径——两种形式均解析
    缺失引用原样保留（适配器/LLM 端兜底，不静默吞掉）。
    """
    flow_input = flow_input or {}
    if isinstance(value, str):

        def _replace(m: re.Match[str]) -> str:
            dotted = m.group(1)
            if dotted is not None:
                parts = dotted.split(".")
                if len(parts) < 2:
                    return m.group(0)
                result = pool.get(parts[0])
                if result is None or result.output is None:
                    # 失败节点池引用：{{#node.error#}}（错误消息）不依赖 output
                    if len(parts) == 2 and parts[1] == "error" and result is not None:
                        return str(result.error) if result.error else m.group(0)
                    return m.group(0)
                # F2 形式 {{#node.output.path#}} 与 F3 简写 {{#node.path#}} 兼容：
                # 显式 .output. 段跳过，其余键均为 output 内的路径
                if parts[1] == "error":
                    # {{#node.error#}} — 错误消息（error 为字符串，无子路径）
                    return str(result.error) if result.error else m.group(0)
                keys = parts[2:] if parts[1] == "output" else parts[1:]
                v: Any = result.output
                for key in keys:
                    if isinstance(v, dict) and key in v:
                        v = v[key]
                    elif isinstance(v, list) and key.isdigit() and int(key) < len(v):
                        # F6 修复：列表索引（{{#node.output.rows.0.status#}}）——场景 A/B 条件与
                        # capability 输入引用 qu/knowledge 输出的首元素需要（评估发现的最小缺口）
                        v = v[int(key)]
                    else:
                        return m.group(0)
                return _stringify(v)
            key = m.group(2)
            return _stringify(flow_input[key]) if key in flow_input else m.group(0)

        return _TEMPLATE_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: resolve_templates(v, pool, flow_input) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_templates(v, pool, flow_input) for v in value]
    return value


def _stringify(v: Any) -> str:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return "null"
    return str(v)


# ── pool 序列化（F4：挂起/恢复的 flow_runs 载体）───────────────────────────────


def serialize_pool(pool: dict[str, StepResult]) -> dict[str, Any]:
    """Chatflow F4: pool → JSON 可序列化 dict（只存 output/status/error，不存函数/句柄）。

    flow_runs.node_state 落库载体——下游模板/条件求值只需 output。
    """
    return {
        nid: {"status": r.status, "output": r.output, "error": r.error}
        for nid, r in pool.items()
        if r.output is not None or r.status != "completed"
    }


def deserialize_pool(data: dict[str, Any] | None) -> dict[str, StepResult]:
    """Chatflow F4: node_state JSON → pool（重建 StepResult 的 JSON 字段，供恢复重放）。"""
    pool: dict[str, StepResult] = {}
    for nid, entry in (data or {}).items():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if status not in ("completed", "failed", "retrying", "skipped"):
            status = "skipped"
        pool[str(nid)] = StepResult(
            step_id=str(nid),
            status=status,
            output=entry.get("output"),
            error=entry.get("error"),
        )
    return pool


# ── 运行时条件求值（纯函数，无 DB）──────────────────────────────────────────


def evaluate_condition(expr: ConditionExpr | dict[str, Any], pool: dict[str, StepResult]) -> bool:
    """Evaluate a ConditionExpr against the step-result pool.

    left = '<node_id>.output.<path>': first segment is the producing step node id,
    second must be 'output', the rest is a dot-path into the step's output dict.
    """
    if isinstance(expr, dict):
        expr = ConditionExpr.model_validate(expr)
    parts = expr.left.split(".")
    if len(parts) < 2 or parts[1] != "output":
        raise ConditionEvaluationError(f"invalid left path {expr.left!r} (expected <node_id>.output.<path>)")
    node_id = parts[0]

    if expr.op == "exists":
        return _resolve(expr.left, node_id, pool) is not None

    result = pool.get(node_id)
    if result is None:
        raise ConditionEvaluationError(f"condition references unknown/unexecuted node {node_id!r}")
    value = _resolve(expr.left, node_id, pool)
    if value is None:
        raise ConditionEvaluationError(f"path {expr.left!r} resolved to None")

    try:
        return _compare(value, expr.op, expr.right)
    except ConditionEvaluationError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConditionEvaluationError(f"cannot compare {value!r} {expr.op} {expr.right!r}: {exc}") from exc


def _resolve(left: str, node_id: str, pool: dict[str, StepResult]) -> Any:
    result = pool.get(node_id)
    if result is None:
        return None
    value: Any = result.output
    for key in left.split(".")[2:]:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            # F6 修复：列表索引（<node_id>.output.rows.0.status）——条件表达式此前只支持
            # dict 路径，场景 A（设备状态行）与场景 B（检索 chunk 首条）分支需要（评估发现）
            value = value[int(key)]
        else:
            return None
    return value


def _compare(value: Any, op: str, right: Any) -> bool:
    if op == "contains":
        if isinstance(value, str):
            return str(right) in value
        if isinstance(value, (list, tuple, set)):
            return right in value
        if isinstance(value, dict):
            return right in value
        return False

    a, b = _coerce_pair(value, right)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    raise ConditionEvaluationError(f"unknown op {op!r}")  # pragma: no cover — pydantic Literal 已校验


def _coerce_pair(value: Any, right: Any) -> tuple[Any, Any]:
    """Return a comparable pair: bool↔bool, number↔number, else str↔str.

    Numeric-looking strings compare numerically（如 "5" > 3 成立），让 JSON 输入更友好。
    """
    if isinstance(value, bool) or isinstance(right, bool):
        return bool(value), bool(right)
    if isinstance(value, (int, float)) and isinstance(right, (int, float)):
        return float(value), float(right)
    if isinstance(value, str) and isinstance(right, str):
        try:
            return float(value), float(right)
        except ValueError:
            return value, right
    return str(value), str(right)
