"""Simple Task Planner — produce sequential Plan (list[Step]) from intent.

M3: single-step Plans only. M5 extends to multi-step workflows with DSL compilation.
"""

from __future__ import annotations

from earp_server.orchestrator.types import Step
from earp_server.planner.business_dictionary import RuleIntentPlanner


class PlanError(Exception):
    """Raised when a plan cannot be constructed."""


class SimpleTaskPlanner:
    """Convert intent to executable Plan (list[Step]).

    M3 strategy: resolve intent via RuleIntentPlanner, wrap in single-Step Plan.
    """

    def __init__(self) -> None:
        self._rules = RuleIntentPlanner()

    def plan(self, intent: str) -> list[Step]:
        match = self._rules.resolve(intent)
        if match is None:
            raise PlanError(f"intent not found: {intent}")
        step = Step(
            step_id=f"step-{match.capability_id}",
            capability_call={
                "capability_id": match.capability_id,
                "adapter_type": match.capability_id.replace("cap-", "").replace("-", "."),
                "input": match.input,
            },
        )
        return [step]
