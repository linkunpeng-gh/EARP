"""Simple Task Planner — produce sequential Plan (list[Step]) from intent.

M3: single-step Plans only (RuleIntentPlanner exact match).
Phase 2: optional LLMConnector for structured output (Ollama) with cache.
M5 extends to multi-step workflows with DSL compilation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from earp_server.orchestrator.types import Step
from earp_server.planner.business_dictionary import RuleIntentPlanner

if TYPE_CHECKING:
    from earp_server.connector import LLMConnector

logger = logging.getLogger(__name__)


class PlanError(Exception):
    """Raised when a plan cannot be constructed."""


class SimpleTaskPlanner:
    """Convert intent to executable Plan (list[Step]).

    Phase 2: tries LLM structured output first (if connector provided),
    falls back to RuleIntentPlanner exact match.
    """

    def __init__(self, llm: LLMConnector | None = None) -> None:
        self._rules = RuleIntentPlanner()
        self._llm = llm

    async def plan(self, intent: str, *, capabilities: list[dict[str, Any]] | None = None) -> list[Step]:
        """Resolve intent → list[Step]. LLM first, rules fallback.

        capabilities: if provided, injected into LLM system prompt for dynamic planning.
        """
        if self._llm is not None:
            try:
                steps_raw = await self._llm.plan(intent, capabilities=capabilities)
                return [
                    Step(
                        step_id=f"step-{s['capability_id']}",
                        capability_call={
                            "capability_id": s["capability_id"],
                            # Derive adapter_type from capability_id:
                            # "cap-demo-echo" → strip "cap-" → "demo-echo" → replace "-" → "demo.echo"
                            "adapter_type": _cap_id_to_adapter(s["capability_id"]),
                            "input": s.get("input", {}),
                        },
                    )
                    for s in steps_raw
                ]
            except Exception:
                logger.warning("SimpleTaskPlanner: LLM plan failed, falling back to rules", exc_info=True)

        # Fallback: RuleIntentPlanner (exact match with explicit adapter_type)
        match = self._rules.resolve(intent)
        if match is None:
            raise PlanError(f"intent not found: {intent}")
        return [
            Step(
                step_id=f"step-{match.capability_id}",
                capability_call={
                    "capability_id": match.capability_id,
                    "adapter_type": match.adapter_type,
                    "input": match.input,
                },
            )
        ]


def _cap_id_to_adapter(capability_id: str) -> str:
    """Convert capability_id to adapter_type.

    Convention: capability_id = "cap-{domain}-{name}", adapter_type = "{domain}.{name}" ({domain} = Business Domain).
    Only replaces hyphen between domain and name (the last segment boundary).
    """
    if capability_id.startswith("cap-"):
        rest = capability_id[4:]  # strip "cap-" prefix
    else:
        rest = capability_id
    # Replace last "-" → ".": "demo-echo" → "demo.echo"
    idx = rest.rfind("-")
    if idx != -1:
        return f"{rest[:idx]}.{rest[idx + 1:]}"
    return rest
