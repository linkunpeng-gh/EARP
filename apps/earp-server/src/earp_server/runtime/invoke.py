"""POST /v1/sessions/{id}/invoke - end-to-end demo capability execution.

Transaction boundary note (holistic review P0-4): the invoke flow spans 3+
independent DB transactions (session lookup / execution row insert + StepRunner /
checkpoint write). Mid-crash orphan recovery: M5+ periodic cleanup via
'DELETE FROM executions WHERE status = "pending" AND created_at < NOW() - 1h'.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.capability.registry import discover
from earp_server.infra.eventbus import EventBus
from earp_server.orchestrator.layers import AuditLayer, PolicyLayer
from earp_server.orchestrator.step_runner import StepRunner
from earp_server.orchestrator.types import InvokeContext, Step

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class InvokeRequest(BaseModel):
    capability_id: str
    input: dict[str, str] = {}


class InvokeResponse(BaseModel):
    execution_id: str
    status: str
    result: dict | None = None
    error: dict | None = None
    checkpoint_id: str | None = None


@router.post("/{session_id}/invoke", response_model=InvokeResponse, status_code=200)
async def invoke(session_id: str, request_invoke: InvokeRequest, request: Request) -> InvokeResponse:
    engine: AsyncEngine = request.app.state.engine
    bus: EventBus = request.app.state.eventbus
    ctx = request.state

    # M2 rate limiter: per-tenant token bucket (pass-through if Redis unavailable)
    limiter = request.app.state.rate_limiter
    if not await limiter.is_allowed(ctx.tenant_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{ctx.tenant_id}'"))
        row = await conn.execute(text("SELECT status FROM sessions WHERE session_id = :sid"), {"sid": session_id})
        sess = row.fetchone()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.status == "closed":
        raise HTTPException(status_code=400, detail="Session is closed")

    caps = await discover(engine, ctx.tenant_id, query=request_invoke.capability_id)
    cap = next((c for c in caps if c["capability_id"] == request_invoke.capability_id), None)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"Capability not found: {request_invoke.capability_id}")

    execution_id = f"exec-{uuid.uuid4().hex[:12]}"
    step = Step(
        step_id=f"step-{uuid.uuid4().hex[:8]}",
        capability_call={
            "capability_id": cap["capability_id"],
            "adapter_type": f"{cap['domain']}.{cap['name']}",
            "input": request_invoke.input,
        },
    )

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{ctx.tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO executions (execution_id, tenant_id, session_id, role_id, status) "
                "VALUES (:eid, :tid, :sid, :rid, 'pending')"
            ),
            {"eid": execution_id, "tid": ctx.tenant_id, "sid": session_id, "rid": ctx.role_id},
        )
        await conn.commit()

    runner = StepRunner(engine)
    ctx_ = InvokeContext(
        tenant_id=ctx.tenant_id,
        execution_id=execution_id,
        session_id=session_id,
        user_id=ctx.user_id,
        role_id=ctx.role_id,
        step=step,
    )
    result = await runner.invoke(
        step, layers=[AuditLayer(bus), PolicyLayer(engine, bus)], ctx=ctx_
    )

    exec_status = "completed" if result.status == "completed" else "failed"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{ctx.tenant_id}'"))
        await conn.execute(
            text("UPDATE executions SET status = :st, result = :res, error = :err WHERE execution_id = :eid"),
            {"st": exec_status, "res": result.output, "err": result.error, "eid": execution_id},
        )
        await conn.commit()

    return InvokeResponse(
        execution_id=execution_id,
        status=exec_status,
        result=result.output,
        error={"message": result.error} if result.error else None,
        checkpoint_id=result.checkpoint_id,
    )
