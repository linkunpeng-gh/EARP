"""Multi-step execution loop — Pregel skeleton: plan -> execute -> update -> checkpoint.

M5 extends M1's single-Step invoke to multi-step Plan execution with
checkpoint-after-each-step, recovery from checkpoint, and retry integration.
M12 adds Saga compensation: register undo actions, rollback on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.checkpoint import CheckpointStore
from earp_server.infra.eventbus import EventBus
from earp_server.orchestrator.compensation import SagaCompensation
from earp_server.orchestrator.step_runner import StepResult, StepRunner
from earp_server.orchestrator.types import InvokeContext, Layer, Step

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
    ) -> tuple[list[StepResult], ExecutionState]:
        """Execute plan steps sequentially with checkpoint + Saga compensation.

        Returns (results, execution_state).
        On step failure: rolls back completed steps via SagaCompensation.
        """
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
                    execution_id=ctx.execution_id, session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id, state={
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

                    saga.register(step.step_id, _compensate, {
                        "compensate_call": step.compensate_call,
                        "step_id": step.step_id,
                    })
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
                        step.step_id, saga.count,
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
