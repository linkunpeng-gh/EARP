"""Capability performance feedback model for Planner optimization.

Tracks per-capability success rate, latency, and error patterns
to enable Feedback-Driven Plan generation (Closed-loop Phase 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CapabilityFeedback:
    """Aggregated performance metrics for a single Capability."""

    capability_id: str = ""
    tenant_id: str = ""

    # Execution stats
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0

    # Latency (ms)
    avg_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    _latency_count: int = field(default=0, repr=False)  # internal counter for p99 decay

    # Scores
    success_rate: float = 0.0          # success_count / total_calls
    health_score: float = 0.0           # composite 0-1, used by Planner

    # Window
    window_start: str = ""              # ISO 8601
    window_end: str = ""

    def record_success(self, latency_ms: int) -> None:
        self.total_calls += 1
        self.success_count += 1
        self._update_latency(latency_ms)
        self._recalc()

    def record_failure(self, error_code: str = "") -> None:
        self.total_calls += 1
        self.failure_count += 1
        if error_code == "TIMEOUT":
            self.timeout_count += 1
        self._recalc()

    def _update_latency(self, latency_ms: int) -> None:
        n = self.success_count
        self.avg_latency_ms = (self.avg_latency_ms * (n - 1) + latency_ms) / n
        self._latency_count += 1
        # p99 approximation: exponential decay toward observed max
        alpha = 0.01  # decay factor
        if self.p99_latency_ms == 0:
            self.p99_latency_ms = float(latency_ms)
        elif latency_ms > self.p99_latency_ms:
            self.p99_latency_ms = latency_ms  # spike: immediate update
        else:
            self.p99_latency_ms = (1 - alpha) * self.p99_latency_ms + alpha * float(latency_ms)

    def _recalc(self) -> None:
        if self.total_calls > 0:
            self.success_rate = self.success_count / self.total_calls
        # Health score: weighted composite (70% success_rate + 30% 1/(1+avg_latency_s))
        latency_penalty = 1.0 / (1.0 + self.avg_latency_ms / 1000.0)
        self.health_score = 0.7 * self.success_rate + 0.3 * latency_penalty


@dataclass
class PlannerFeedback:
    """Feedback snapshot for Planner optimization.

    Collected after each Execution completes. The Planner uses
    aggregated feedback to prefer higher-health Capabilities when
    multiple options exist for the same intent.
    """

    execution_id: str = ""
    session_id: str = ""
    plan_id: str = ""
    capability_feedbacks: list[CapabilityFeedback] = field(default_factory=list)
    overall_success: bool = False
    total_duration_ms: int = 0
    replan_count: int = 0      # how many times RePlan was triggered
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
