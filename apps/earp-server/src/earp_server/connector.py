"""Capability execution + LLM planning channels.

M1: Connector.execute (capability call)
M3: LLMConnector.plan (structured output → Pydantic Plan schema)
"""

from __future__ import annotations

import logging
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Raised when a capability adapter fails after exhausting retries."""


class Connector:
    """Execute a capability call with retry. M1 demo: echo adapter only."""

    def __init__(self, eventbus=None) -> None:
        self._bus = eventbus

    @retry(
        retry=retry_if_exception_type(ConnectorError),
        wait=wait_exponential_jitter(),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def execute(self, capability_call: dict[str, Any]) -> dict[str, Any]:
        adapter_type = capability_call.get("adapter_type", "demo.echo")
        logger.debug("connector execute adapter=%s", adapter_type)
        if adapter_type == "demo.echo":
            return {"echo": capability_call.get("input", {})}
        raise ConnectorError(f"unknown adapter: {adapter_type}")

    def _on_retry(self, retry_state) -> None:
        if self._bus is not None:
            from earp_server.infra.eventbus import CloudEvent

            self._bus.publish(
                CloudEvent(
                    type="earp.connector.retrying",
                    source="earp-server/connector",
                    tenant_id="",
                    data={
                        "attempt": retry_state.attempt_number,
                        "exception": str(retry_state.outcome.exception()) if retry_state.outcome else "",
                    },
                )
            )


# ── LLMConnector (M3) ────────────────────────────────────────────────────────

class LLMConnector:
    """LLM integration with structured output + rate limiting + tool binding.

    Interface finalized in M3 (5 hooks). Implementation of cache / bind_tools /
    stream toggle deferred to Phase 2/3.
    """

    def __init__(self, model: str = "deepseek-v4-flash", rate_limiter=None) -> None:
        self._model = model
        self._rate_limiter = rate_limiter
        # M3: only rate_limiter wired. Remaining 4 hooks declared for interface stability.
        self._cache: dict | None = None  # Phase 2: LLM response cache
        self._bind_tools: bool = False   # Phase 3: inject Capability candidates as tools
        self._structured_output: bool = False  # Phase 3: enforce Pydantic Plan schema
        self._stream_enabled: bool = False     # M6: token streaming toggle

    async def plan(self, prompt: str, *, tools: list[dict] | None = None) -> list[dict[str, Any]]:
        """Generate a Plan via LLM with structured output.

        M3 implementation: uses RuleIntentPlanner as fallback (LLM not wired).
        Phase 3 adds real LLM call with structured output (Pydantic Plan schema).
        """
        # Phase 3: call LLM with prompt, parse response via Pydantic Plan model.
        # M3 fallback: delegate to RuleIntentPlanner as documented degradation path.
        from earp_server.planner.business_dictionary import RuleIntentPlanner

        logger.info("LLMConnector.plan: using RuleIntentPlanner fallback (LLM not wired)")
        resolver = RuleIntentPlanner()
        match = resolver.resolve(prompt)
        if match is None:
            raise ConnectorError(f"LLMConnector.plan: no match for prompt '{prompt}'")
        return [{"capability_id": match.capability_id, "input": match.input}]

    async def plan_structured(self, prompt: str) -> list[dict[str, Any]]:
        """Phase 3: LLM call with Pydantic Plan schema enforcement.

        M3 placeholder — delegates to plan(). Phase 3 adds:
          - Pydantic Plan model validation
          - ERR-PL-VALIDATION-001 on schema mismatch
          - LLM retry on validation failure
        """
        return await self.plan(prompt)
