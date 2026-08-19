"""Multi-step execution loop — Pregel skeleton: plan -> execute -> update -> checkpoint.

M5 extends M1's single-Step invoke to multi-step Plan execution with
checkpoint-after-each-step, recovery from checkpoint, and retry integration.
M12 adds Saga compensation: register undo actions, rollback on failure.
"""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.checkpoint import CheckpointStore
from earp_server.infra.eventbus import EventBus
from earp_server.orchestrator.compensation import SagaCompensation
from earp_server.orchestrator.step_runner import StepResult, StepRunner
from earp_server.orchestrator.types import InvokeContext, Layer, Step
from earp_server.orchestrator.workflow_dsl import (
    CompiledWorkflow,
    CondExec,
    ConditionEvaluationError,
    evaluate_condition,
)

logger = logging.getLogger(__name__)


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REPLANNING = "replanning"
    INTERRUPTED = "interrupted"
    ROLLED_BACK = "rolled_back"


@dataclass
class ExecutionState:
    execution_id: str
    session_id: str
    tenant_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    current_step_index: int = 0
    completed_steps: list[str] = field(default_factory=list)  # step_ids that succeeded
    last_checkpoint_id: str | None = None
    checkpoint_mode: str = "async"  # sync / async / exit
    rollback_results: list[dict] = field(default_factory=list)  # M12: compensation outputs


class MultiStepExecutor:
    """Execute a Plan (list[Step]) with checkpoint + Saga compensation."""

    def __init__(self, engine: AsyncEngine, bus: EventBus | None = None) -> None:
        self._runner = StepRunner(engine)
        self._checkpoint = CheckpointStore(engine)
        self._bus = bus
        self._interrupted = False  # M5: interrupt flag for human_approval/REPLANNING

    def interrupt(self) -> None:
        """Signal the executor to stop after the current step completes."""
        self._interrupted = True

    def resume(self) -> None:
        """Clear the interrupt flag for recovery."""
        self._interrupted = False

    async def execute(
        self,
        steps: list[Step],
        ctx: InvokeContext,
        layers: list[Layer],
        *,
        resume_from_checkpoint_id: str | None = None,
        durability: str = "async",
        plan: CompiledWorkflow | None = None,
    ) -> tuple[list[StepResult], ExecutionState]:
        """Execute plan steps sequentially with checkpoint + Saga compensation.

        Chatflow F0: plan（compile_workflow 产物）提供时走声明式图执行——Conditional
        运行时求值、未命中分支 skip（不 invoke）。plan=None 时保持 legacy 行为不变。

        Returns (results, execution_state).
        On step failure: rolls back completed steps via SagaCompensation.
        """
        if plan is not None:
            return await self._execute_plan(plan, ctx, layers, resume_from_checkpoint_id)
        results: list[StepResult] = []
        saga = SagaCompensation()
        state = ExecutionState(
            execution_id=ctx.execution_id,
            session_id=ctx.session_id,
            tenant_id=ctx.tenant_id,
            status=ExecutionStatus.RUNNING,
        )
        start_index = 0

        # Recovery: skip completed steps from checkpoint
        if resume_from_checkpoint_id:
            start_index = await self._get_completed_count(ctx.tenant_id, resume_from_checkpoint_id)

        for i in range(start_index, len(steps)):
            # M5: interrupt check before executing next step
            if self._interrupted:
                state.status = ExecutionStatus.INTERRUPTED
                state.current_step_index = i
                state.completed_steps = [r.step_id for r in results if r.status == "completed"]
                await self._checkpoint.write(
                    execution_id=ctx.execution_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    state={
                        "status": ExecutionStatus.INTERRUPTED,
                        "current_step_index": i,
                        "completed_step_ids": state.completed_steps,
                    },
                    channels={"step_results": str(results).encode()},
                    checkpoint_ns="interrupt",
                )
                return results, state

            step = steps[i]
            result = await self._runner.invoke(step, layers=layers, ctx=ctx)
            results.append(result)

            if result.status == "completed":
                # M12: register compensation for rollback
                if step.compensate_call:

                    async def _compensate(ctx_dict: dict) -> None:
                        from earp_server.connector import Connector

                        connector = Connector()
                        await connector.execute(ctx_dict.get("compensate_call", {}))

                    saga.register(
                        step.step_id,
                        _compensate,
                        {
                            "compensate_call": step.compensate_call,
                            "step_id": step.step_id,
                        },
                    )
                    # Track which steps have compensations registered
                    state.completed_steps.append(step.step_id)

                # Write checkpoint after each successful step
                _ = await self._checkpoint.write(
                    execution_id=ctx.execution_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    state={
                        "current_step_index": i + 1,
                        "completed_step_ids": [r.step_id for r in results if r.status == "completed"],
                        "last_result_status": result.status,
                    },
                    channels={"step_results": str(results).encode()},
                    checkpoint_ns=f"plan:{step.step_id}",  # unique namespace per step (plan-level)
                )

            if result.status == "failed":
                # M12: rollback completed steps in reverse order
                if saga.count > 0:
                    logger.info(
                        "MultiStepExecutor: step %s failed, rolling back %d completed steps",
                        step.step_id,
                        saga.count,
                    )
                    await saga.rollback()
                    state.status = ExecutionStatus.ROLLED_BACK
                    state.rollback_results = [
                        {"step_id": sid, "status": "rolled_back"}
                        for sid in state.completed_steps  # only steps with compensate_call
                    ]
                else:
                    state.status = ExecutionStatus.FAILED
                state.current_step_index = i
                state.completed_steps = [r.step_id for r in results if r.status == "completed"]
                return results, state

        # All steps completed
        state.status = ExecutionStatus.COMPLETED
        state.current_step_index = len(steps)
        state.completed_steps = [r.step_id for r in results if r.status == "completed"]
        return results, state

    # ── F0: 声明式图执行（plan path）──────────────────────────────────────────

    async def _execute_plan(
        self,
        plan: CompiledWorkflow,
        ctx: InvokeContext,
        layers: list[Layer],
        resume_from_checkpoint_id: str | None,
    ) -> tuple[list[StepResult], ExecutionState]:
        """Execute a CompiledWorkflow with runtime conditional branch selection.

        - pool: node_id → StepResult（条件求值的数据源）
        - chosen: branch_id → "then"/"else"（运行时决策，确定性重放）
        - 未命中分支的 StepExec：产出 skipped 结果 + 轻量 checkpoint，不调 StepRunner
        - resume：从 step_results blob 重建 pool，决策可确定性重放
        """
        results: list[StepResult] = []
        saga = SagaCompensation()
        state = ExecutionState(
            execution_id=ctx.execution_id,
            session_id=ctx.session_id,
            tenant_id=ctx.tenant_id,
            status=ExecutionStatus.RUNNING,
        )
        pool: dict[str, StepResult] = {}
        chosen: dict[str, str] = {}
        processed = 0  # 已处理 StepExec 数（resume 游标，语义 = legacy current_step_index）
        prior_count = 0
        if resume_from_checkpoint_id:
            prior = await self._read_prior_results(ctx.tenant_id, resume_from_checkpoint_id)
            pool = {r.step_id: r for r in prior if r.status == "completed"}
            prior_count = len(prior)
            logger.info("MultiStepExecutor: resuming plan from checkpoint, %d steps prior", prior_count)

        for item in plan.sequence:
            if self._interrupted:
                state.status = ExecutionStatus.INTERRUPTED
                state.current_step_index = processed
                state.completed_steps = [r.step_id for r in results if r.status == "completed"]
                await self._checkpoint.write(
                    execution_id=ctx.execution_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    state={
                        "status": ExecutionStatus.INTERRUPTED,
                        "current_step_index": processed,
                        "completed_step_ids": state.completed_steps,
                    },
                    channels={"step_results": _serialize_results(results)},
                    checkpoint_ns="interrupt",
                )
                return results, state

            if isinstance(item, CondExec):
                # 被门控的条件（位于未命中分支内）不求值
                if self._gate_satisfied(item.gate, chosen):
                    try:
                        taken = evaluate_condition(item.condition, pool)
                    except ConditionEvaluationError as exc:
                        results.append(StepResult(step_id=item.node_id, status="failed", error=f"condition: {exc}"))
                        state.status = ExecutionStatus.FAILED
                        state.current_step_index = processed
                        return results, state
                    chosen[item.branch_id] = "then" if taken else "else"
                continue

            # StepExec
            processed += 1
            if resume_from_checkpoint_id and processed <= prior_count:
                # 前序 run 已处理的步：不重放（结果已在 pool，供后续条件确定性求值）
                continue

            if not self._gate_satisfied(item.gate, chosen):
                skipped = StepResult(step_id=item.node_id, status="skipped")
                results.append(skipped)
                state.completed_steps = [r.step_id for r in results if r.status == "completed"]
                await self._checkpoint.write(
                    execution_id=ctx.execution_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    state={
                        "status": "skipped",
                        "current_step_index": processed,
                        "completed_step_ids": state.completed_steps,
                    },
                    channels={"step_results": _serialize_results(results)},
                    checkpoint_ns=f"plan:{item.node_id}",
                )
                continue

            step_ctx = replace(ctx, step=item.step)
            result = await self._runner.invoke(item.step, layers=layers, ctx=step_ctx)
            results.append(result)
            pool[item.node_id] = result

            if result.status == "completed":
                if item.step.compensate_call:

                    async def _compensate(ctx_dict: dict) -> None:
                        from earp_server.connector import Connector

                        connector = Connector()
                        await connector.execute(ctx_dict.get("compensate_call", {}))

                    saga.register(
                        item.step.step_id,
                        _compensate,
                        {
                            "compensate_call": item.step.compensate_call,
                            "step_id": item.step.step_id,
                        },
                    )
                state.completed_steps.append(item.step.step_id)
                await self._checkpoint.write(
                    execution_id=ctx.execution_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    state={
                        "current_step_index": processed,
                        "completed_step_ids": [r.step_id for r in results if r.status == "completed"],
                        "last_result_status": result.status,
                    },
                    channels={"step_results": _serialize_results(results)},
                    checkpoint_ns=f"plan:{item.step.step_id}",
                )

            if result.status == "failed":
                if saga.count > 0:
                    logger.info(
                        "MultiStepExecutor: step %s failed, rolling back %d completed steps",
                        item.step.step_id,
                        saga.count,
                    )
                    await saga.rollback()
                    state.status = ExecutionStatus.ROLLED_BACK
                    state.rollback_results = [
                        {"step_id": sid, "status": "rolled_back"} for sid in state.completed_steps
                    ]
                else:
                    state.status = ExecutionStatus.FAILED
                state.current_step_index = processed
                state.completed_steps = [r.step_id for r in results if r.status == "completed"]
                return results, state

        state.status = ExecutionStatus.COMPLETED
        state.current_step_index = processed
        state.completed_steps = [r.step_id for r in results if r.status == "completed"]
        return results, state

    @staticmethod
    def _gate_satisfied(gate: frozenset[tuple[str, str]], chosen: dict[str, str]) -> bool:
        """gate 内所有 (branch_id, side) 都已被 chosen 命中才执行。"""
        return all(chosen.get(branch_id) == side for branch_id, side in gate)

    async def _read_prior_results(self, tenant_id: str, checkpoint_id: str) -> list[StepResult]:
        """Resume: 从 checkpoint step_results blob 重建 prior 结果（决策确定性重放）。

        解析 JSON dict 序列化（F0 plan 路径写入格式）；解析失败（含 legacy repr，
        其 StepResult(...) 调用无法 literal_eval）→ 返回空 prior，不阻塞执行。
        """
        from sqlalchemy import text

        async with self._checkpoint._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = await conn.execute(
                text("SELECT thread_id, checkpoint_ns FROM checkpoints WHERE checkpoint_id = :cid"),
                {"cid": checkpoint_id},
            )
            meta = row.fetchone()
            if not meta:
                return []
            blob_row = await conn.execute(
                text(
                    "SELECT blob FROM checkpoint_blobs WHERE thread_id = :tid "
                    "AND checkpoint_ns = :ns AND channel = 'step_results'"
                ),
                {"tid": meta.thread_id, "ns": meta.checkpoint_ns},
            )
            r = blob_row.fetchone()
        if not r or not r.blob:
            return []
        try:
            raw = ast.literal_eval(r.blob.decode())
        except (ValueError, SyntaxError):
            return []
        results: list[StepResult] = []
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict):
                continue
            status = entry.get("status", "skipped")
            results.append(
                StepResult(
                    step_id=str(entry.get("step_id", "")),
                    status=status if status in ("completed", "failed", "retrying", "skipped") else "skipped",
                    output=entry.get("output"),
                    error=entry.get("error"),
                    latency_ms=int(entry.get("latency_ms", 0) or 0),
                    checkpoint_id=entry.get("checkpoint_id"),
                )
            )
        return results

    async def _get_completed_count(self, tenant_id: str, checkpoint_id: str) -> int:
        """Return the number of steps that were completed in a previous run."""
        from sqlalchemy import text

        async with self._checkpoint._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = await conn.execute(
                text("SELECT checkpoint->>'current_step_index' AS idx FROM checkpoints WHERE checkpoint_id = :cid"),
                {"cid": checkpoint_id},
            )
            r = row.fetchone()
            return int(r.idx) if r and r.idx else 0


def _serialize_results(results: list[StepResult]) -> bytes:
    """step_results 通道序列化：JSON dict（输出非序列化时回退 repr，legacy 兼容）。"""
    try:
        payload = json.dumps([asdict(r) for r in results])
    except (TypeError, ValueError):
        payload = str(results)
    return payload.encode()
