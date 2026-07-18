"""Capability execution entities — CapabilityResult, usage tracking.

Inspired by Dify's NodeRunResult pattern: unified return type for all
Capability executions, covering success, failure, and LLM token usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class CapabilityUsage:
    """Token/resource usage from a Capability execution."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0


@dataclass
class CapabilityResult:
    """Unified result type for all Capability.execute() calls.

    Inspired by Dify core/workflow/node_runtime.py NodeRunResult.
    """

    status: Literal["ok", "error", "retry", "paused"] = "ok"
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    usage: CapabilityUsage = field(default_factory=CapabilityUsage)

    def is_ok(self) -> bool:
        return self.status == "ok"

    def is_retriable(self) -> bool:
        return self.status == "retry"
