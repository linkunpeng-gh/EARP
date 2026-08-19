"""Orchestrator shared types — no inter-submodule imports to avoid circular deps."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class Step:
    step_id: str
    capability_call: dict[str, Any]
    retry_config: dict | None = None
    timeout_seconds: int | None = None
    # M12 Saga: optional compensation (undo) capability call for rollback
    compensate_call: dict[str, Any] | None = None


@dataclass
class StepResult:
    step_id: str
    # F0: "skipped" = 未命中分支的步（不 invoke、无副作用，见 workflow_dsl）
    status: Literal["completed", "failed", "retrying", "skipped"]
    output: dict | None = None
    error: str | None = None
    latency_ms: int = 0
    checkpoint_id: str | None = None


@dataclass
class StepEvent:
    step_id: str
    event_type: Literal["step_started", "step_completed", "step_failed", "checkpoint_written", "token"]
    data: dict | None = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())


@dataclass
class TokenEvent:
    """Streaming token event — yielded by LLMConnector.stream()."""

    token: str
    step_id: str = ""
    index: int = 0


@dataclass
class InvokeContext:
    """Passed to every Layer. Fields stable across M1-M5."""

    tenant_id: str
    execution_id: str
    session_id: str
    user_id: str
    role_id: str
    step: Step


class Layer(Protocol):
    async def before_step(self, ctx: InvokeContext) -> None: ...
    async def after_step(self, ctx: InvokeContext, result: StepResult) -> None: ...
