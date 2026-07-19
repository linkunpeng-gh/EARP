"""StepRunner — step execution engine with 3-form interface (invoke/stream/batch).

M1: only invoke() is implemented. stream()/batch() raise NotImplementedError.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.checkpoint import CheckpointStore
from earp_server.orchestrator.types import InvokeContext, Layer, Step, StepEvent, StepResult


class StepRunner:
    def __init__(self, engine: AsyncEngine) -> None:
        self._checkpoint = CheckpointStore(engine)

    async def invoke(self, step: Step, *, layers: list[Layer], ctx: InvokeContext) -> StepResult:
        for layer in layers:
            await layer.before_step(ctx)

        t0 = time.monotonic()
        error: str | None = None
        output: dict | None = None
        status: str = "failed"
        try:
            output = await self._execute_step(step, ctx)
            status = "completed"
        except Exception as exc:
            error = str(exc)
        latency_ms = int((time.monotonic() - t0) * 1000)

        state = {
            "step_id": step.step_id,
            "status": status,
            "latency_ms": latency_ms,
            "output_summary": str(output)[:500] if output else None,
            "error": error,
        }
        channels = {"raw_output": str(output).encode() if output else b"{}"}
        checkpoint_id = await self._checkpoint.write(
            execution_id=ctx.execution_id,
            session_id=ctx.session_id,
            tenant_id=ctx.tenant_id,
            state=state,
            channels=channels,
        )

        result = StepResult(
            step_id=step.step_id,
            status=status,
            output=output,
            error=error,
            latency_ms=latency_ms,
            checkpoint_id=checkpoint_id,
        )

        for layer in layers:
            await layer.after_step(ctx, result)

        return result

    async def _execute_step(self, step: Step, ctx: InvokeContext) -> dict[str, Any]:
        from earp_server.connector import Connector

        connector = Connector()
        return await connector.execute(step.capability_call)

    async def stream(self, step: Step) -> AsyncGenerator[StepEvent, None]:
        raise NotImplementedError("M6 streaming")

    async def batch(self, steps: list[Step]) -> list[StepResult]:
        raise NotImplementedError("M7+: parallel batch execution (M5 uses for-loop)")
