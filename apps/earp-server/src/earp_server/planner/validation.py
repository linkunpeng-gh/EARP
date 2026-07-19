"""Plan Validation — schema + depth + permissions checks.

ERR-PL-VALIDATION-001: plan schema violation (missing capability_id).
"""

from __future__ import annotations

from earp_server.orchestrator.types import Step

MAX_PLAN_DEPTH = 5


class PlanValidationError(Exception):
    """Raised when a plan fails validation (ERR-PL-VALIDATION-001 or depth exceeded)."""


def validate_plan(steps: list[Step]) -> None:
    """Validate plan schema and depth. Raises PlanValidationError on failure.

    M3 checks:
    - Schema: every step must have a non-empty capability_id
    - Depth: steps count must not exceed MAX_PLAN_DEPTH
    """
    if not steps:
        raise PlanValidationError("plan is empty")

    if len(steps) > MAX_PLAN_DEPTH:
        raise PlanValidationError(
            f"plan depth {len(steps)} exceeds max {MAX_PLAN_DEPTH}"
        )

    for step in steps:
        capability_id = step.capability_call.get("capability_id", "")
        if not capability_id:
            raise PlanValidationError(
                f"step {step.step_id}: missing capability_id (ERR-PL-VALIDATION-001)"
            )
