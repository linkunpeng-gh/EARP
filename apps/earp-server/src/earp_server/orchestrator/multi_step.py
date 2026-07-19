"""Multi-step execution loop — Pregel skeleton: plan -> execute -> update -> checkpoint.

M5 extends M1's single-Step invoke to multi-step Plan execution with
checkpoint-after-each-step, recovery from checkpoint, and retry integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.checkpoint import CheckpointStore
from earp_server.infra.eventbus import EventBus
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


class MultiStepExecutor:
    """Execute a Plan (list[Step]) with checkpoint-after-each-step and recovery."""

    def __init__(self, engine: AsyncEngine, bus: EventBus | None = None) -> None:
        self._runner = StepRunner(engine)
        self._checkpoint = CheckpointStore(engine)
        self._bus = bus

    async def execute(
        self,
        steps: list[Step],
        ctx: InvokeContext,
        layers: list[Layer],
        *,
        resume_from_checkpoint_id: str | None = None,
        durability: str = "async",
    ) -> list[StepResult]:
        """Execute plan steps sequentially with checkpoint between each step."""
        results: list[StepResult] = []
        start_index = 0

        # Recovery: skip completed steps from checkpoint
        if resume_from_checkpoint_id:
            start_index = await self._get_completed_count(ctx.tenant_id, resume_from_checkpoint_id)

        for i in range(start_index, len(steps)):
            step = steps[i]
            result = await self._runner.invoke(step, layers=layers, ctx=ctx)
            results.append(result)

            # Write checkpoint after each step
            state = {
                "current_step_index": i + 1,
                "completed_step_ids": [r.step_id for r in results if r.status == "completed"],
                "last_result_status": result.status,
            }
            _ = await self._checkpoint.write(
                execution_id=ctx.execution_id,
                session_id=ctx.session_id,
                tenant_id=ctx.tenant_id,
                state=state,
                channels={"step_results": str(results).encode()},
            )

            if durability == "sync":
                # sync mode: already waited (write is synchronous in M1 CheckpointStore)
                pass

            if result.status == "failed":
                break

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
