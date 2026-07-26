"""StepRunner — step execution engine with 3-form interface (invoke/stream/batch).

M1: only invoke() is implemented. stream()/batch() raise NotImplementedError.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.checkpoint import CheckpointStore
from earp_server.orchestrator.types import InvokeContext, Layer, Step, StepEvent, StepResult

if TYPE_CHECKING:
    from earp_server.connector import LLMConnector


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
            checkpoint_ns=step.step_id,  # unique namespace per step
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

    async def stream(
        self,
        step: Step,
        *,
        ctx: InvokeContext | None = None,
        llm: LLMConnector | None = None,
    ) -> AsyncGenerator[StepEvent, None]:
        """M8: token-by-token streaming execution.

        For LLM-prompt capabilities: streams tokens from Ollama via LLMConnector.
        For other capabilities: executes normally and yields start/completed events.
        """
        if ctx is None:
            ctx = InvokeContext(
                tenant_id="",
                execution_id="",
                session_id="",
                user_id="",
                role_id="",
                step=step,
            )
        step_id = step.step_id
        yield StepEvent(event_type="step_started", step_id=step_id)

        adapter_type = step.capability_call.get("adapter_type", "")
        # LLM streaming path: adapter_type starts with "llm."
        if adapter_type.startswith("llm.") and llm is not None:
            prompt = step.capability_call.get("input", {}).get("prompt", "")
            system = step.capability_call.get("input", {}).get("system", "")
            try:
                async for token in llm.stream(prompt, system=system):
                    yield StepEvent(
                        event_type="token",
                        step_id=step_id,
                        data={"token": token.token, "index": token.index},
                    )
                yield StepEvent(
                    event_type="step_completed",
                    step_id=step_id,
                    data={"status": "completed"},
                )
            except Exception as e:
                yield StepEvent(
                    event_type="step_failed",
                    step_id=step_id,
                    data={"error": str(e)},
                )
            return

        # Non-LLM path: normal execution
        try:
            result = await self._execute_step(step, ctx)
            checkpoint_id = uuid.uuid4().hex
            yield StepEvent(
                event_type="step_completed",
                step_id=step_id,
                data={"result": result, "checkpoint_id": checkpoint_id},
            )
        except Exception as e:
            yield StepEvent(
                event_type="step_failed",
                step_id=step_id,
                data={"error": str(e)},
            )

    async def batch(self, steps: list[Step]) -> list[StepResult]:
        """DEPRECATED since M5. Multi-step execution uses for-loop via MultiStepExecutor.

        This interface is kept for API stability. Use MultiStepExecutor.execute() instead.
        """
        raise NotImplementedError("DEPRECATED: use MultiStepExecutor.execute() (M5 for-loop)")
