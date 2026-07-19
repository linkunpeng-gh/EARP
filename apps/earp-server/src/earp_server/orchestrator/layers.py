"""Orchestrator Layer Protocol + AuditLayer. PolicyLayer placeholder for M2."""

from __future__ import annotations

from earp_server.infra.eventbus import CloudEvent, EventBus
from earp_server.orchestrator.types import InvokeContext, StepResult


class AuditLayer:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def before_step(self, ctx: InvokeContext) -> None:
        self._bus.publish(
            CloudEvent(
                type="earp.execution.started",
                source="earp-server/orchestrator",
                tenant_id=ctx.tenant_id,
                data={"execution_id": ctx.execution_id, "session_id": ctx.session_id},
            )
        )

    async def after_step(self, ctx: InvokeContext, result: StepResult) -> None:
        event_type = "earp.execution.completed" if result.status == "completed" else "earp.execution.failed"
        self._bus.publish(
            CloudEvent(
                type=event_type,
                source="earp-server/orchestrator",
                tenant_id=ctx.tenant_id,
                data={
                    "execution_id": ctx.execution_id,
                    "session_id": ctx.session_id,
                    "user_id": ctx.user_id,
                    "entity_type": "execution",
                    "entity_id": ctx.execution_id,
                    "checkpoint_id": result.checkpoint_id or "",
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                },
            )
        )


class PolicyLayer:
    """Placeholder - M2 (PRD-2026-023) implements permissions/data_scope/rate-limit evaluation.

    Registered in StepRunner.invoke() layers=[..., PolicyLayer()].
    before_step -> check required_permissions vs role capabilities.
    after_step -> inject PERMISSION_DENIED audit event on policy rejection.
    """

    async def before_step(self, ctx: InvokeContext) -> None:  # noqa: ARG002
        pass

    async def after_step(self, ctx: InvokeContext, result: StepResult) -> None:  # noqa: ARG002
        pass
