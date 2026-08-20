"""Orchestrator Layer chain — AuditLayer + PolicyLayer (M2).

Layer execution order in StepRunner.invoke():
  [AuditLayer.before_step, PolicyLayer.before_step, ...execute...,
   PolicyLayer.after_step(OutputFilter), AuditLayer.after_step]
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import CloudEvent, EventBus
from earp_server.orchestrator.types import InvokeContext, Step, StepResult

logger = logging.getLogger(__name__)


# ── AuditLayer ────────────────────────────────────────────────────────────────


class AuditLayer:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    @staticmethod
    def _event_prefix(ctx: InvokeContext) -> str:
        """Chatflow F3: capability.call 步骤走 earp.capability.call.*（设计稿 §3 审计命名空间），
        其余（orchestrator invoke 路径）保持 earp.execution.*。"""
        if ctx.step.capability_call.get("adapter_type") == "capability.call":
            return "earp.capability.call"
        return "earp.execution"

    async def before_step(self, ctx: InvokeContext) -> None:
        prefix = self._event_prefix(ctx)
        data: dict[str, Any] = {
            "execution_id": ctx.execution_id,
            "session_id": ctx.session_id,
            "user_id": ctx.user_id,
            "role_id": ctx.role_id,
        }
        if prefix == "earp.capability.call":
            data["entity_type"] = "capability"
            data["entity_id"] = ctx.step.capability_call.get("capability_id", "")
        self._bus.publish(
            CloudEvent(
                type=f"{prefix}.started",
                source="earp-server/orchestrator",
                tenant_id=ctx.tenant_id,
                data=data,
            )
        )

    async def after_step(self, ctx: InvokeContext, result: StepResult) -> None:
        prefix = self._event_prefix(ctx)
        event_type = f"{prefix}.completed" if result.status == "completed" else f"{prefix}.failed"
        self._bus.publish(
            CloudEvent(
                type=event_type,
                source="earp-server/orchestrator",
                tenant_id=ctx.tenant_id,
                data={
                    "execution_id": ctx.execution_id,
                    "session_id": ctx.session_id,
                    "user_id": ctx.user_id,
                    "role_id": ctx.role_id,
                    "entity_type": "capability" if prefix == "earp.capability.call" else "execution",
                    "entity_id": (
                        ctx.step.capability_call.get("capability_id", "")
                        if prefix == "earp.capability.call"
                        else ctx.execution_id
                    ),
                    "checkpoint_id": result.checkpoint_id or "",
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                },
            )
        )


# ── PolicyLayer (M2) ──────────────────────────────────────────────────────────


class PolicyLayer:
    """M2: RBAC permissions check (before_step) + data_scope filtering (after_step).

    Requires engine (DB lookup) and eventbus (PERMISSION_DENIED events).
    """

    def __init__(self, engine: AsyncEngine, bus: EventBus) -> None:
        self._engine = engine
        self._bus = bus

    # ── before_step: permissions check ────────────────────────────────────────

    async def before_step(self, ctx: InvokeContext) -> None:
        required_permissions = await self._get_required_permissions(ctx.step, ctx.tenant_id)
        if not required_permissions:
            return  # no permissions required → allow (e2e/test bypass)

        role_permissions = await self._get_role_permissions(ctx)
        if not self._is_subset(required_permissions, role_permissions):
            self._bus.publish(
                CloudEvent(
                    type="earp.execution.denied",
                    source="earp-server/policy",
                    tenant_id=ctx.tenant_id,
                    data={
                        "execution_id": ctx.execution_id,
                        "user_id": ctx.user_id,
                        "role_id": ctx.role_id,
                        "entity_type": "execution",
                        "entity_id": ctx.execution_id,
                        "denied_capability": ctx.step.capability_call.get("capability_id", ""),
                        "required_permissions": required_permissions,
                        "role_permissions": role_permissions,
                    },
                )
            )
            raise HTTPException(
                status_code=403,
                detail=f"Role {ctx.role_id} lacks required permissions: {required_permissions}",
            )

    async def _get_required_permissions(self, step: Step, tenant_id: str) -> list[str]:
        capability_id = step.capability_call.get("capability_id", "")
        if not capability_id:
            return []
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = await conn.execute(
                text("SELECT required_permissions FROM business_capabilities WHERE capability_id = :cid"),
                {"cid": capability_id},
            )
            result = row.fetchone()
            if result and result.required_permissions:
                return list(result.required_permissions) if isinstance(result.required_permissions, list) else []
            return []

    async def _get_role_permissions(self, ctx: InvokeContext) -> list[str]:
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{ctx.tenant_id}'"))
            row = await conn.execute(
                text("SELECT permissions FROM roles WHERE role_id = :rid"),
                {"rid": ctx.role_id},
            )
            result = row.fetchone()
            if result and result.permissions:
                return list(result.permissions) if isinstance(result.permissions, list) else []
            return []

    @staticmethod
    def _is_subset(required: list[str], granted: list[str]) -> bool:
        granted_set = set(granted)
        return all(p in granted_set for p in required)

    # ── after_step: data_scope filtering (OutputFilter) ───────────────────────

    async def after_step(self, ctx: InvokeContext, result: StepResult) -> None:
        scope = await self._get_data_scope(ctx.role_id, ctx.tenant_id)
        if scope == "all":
            return  # no filtering needed
        if result.output is None:
            return

        if scope == "self":
            filtered = {}
            for key, value in result.output.items():
                if isinstance(value, dict) and value.get("created_by") == ctx.user_id:
                    filtered[key] = value
            result.output = filtered
        elif scope in ("department", "org"):
            user_org = await self._get_user_org_unit(ctx.user_id, ctx.tenant_id)
            if user_org is None:
                return
            filtered = {}
            for key, value in result.output.items():
                if isinstance(value, dict):
                    target_org = value.get("org_unit_id", "")
                    if scope == "department" and target_org == user_org:
                        filtered[key] = value
                    elif scope == "org":
                        # org scope: self + all descendants of user's org_unit
                        allowed = [user_org] + await self._get_descendant_orgs(user_org, ctx.tenant_id)
                        if target_org in allowed:
                            filtered[key] = value
            result.output = filtered

    async def _get_user_org_unit(self, user_id: str, tenant_id: str) -> str | None:
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = await conn.execute(
                text("SELECT org_unit_id FROM users WHERE user_id = :uid"),
                {"uid": user_id},
            )
            r = row.fetchone()
            return r.org_unit_id if r else None

    async def _get_descendant_orgs(self, org_unit_id: str, tenant_id: str) -> list[str]:
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            rows = await conn.execute(
                text("SELECT org_unit_id FROM org_units WHERE parent_id = :pid"),
                {"pid": org_unit_id},
            )
            return [r.org_unit_id for r in rows]

    async def _get_data_scope(self, role_id: str, tenant_id: str) -> str:
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = await conn.execute(
                text("SELECT data_scope FROM roles WHERE role_id = :rid"),
                {"rid": role_id},
            )
            result = row.fetchone()
            return (result.data_scope or "all") if result else "all"
