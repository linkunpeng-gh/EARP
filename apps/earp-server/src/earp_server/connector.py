"""Capability execution + LLM planning channels.

M1: Connector.execute (capability call)
M3/M8: LLMConnector.plan — structured output via Ollama + Redis cache
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from earp_server.config import Settings

if TYPE_CHECKING:
    from earp_server.infra.llm_cache import LLMCache
    from earp_server.orchestrator.types import TokenEvent

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


# ── LLMConnector (M3, Phase 2 enhanced) ──────────────────────────────────────

_PLAN_SYSTEM_PROMPT = (
    "You are an intent-to-action planner. Given a user intent, output a JSON plan "
    'with exactly this structure: {"steps": [{"capability_id": "...", "input": {...}}]}. '
    "Available capabilities: echo (cap-demo-echo), query users (cap-query-users), "
    "create alarm (cap-create-alarm), query alarms (cap-query-alarms). "
    "Output ONLY valid JSON, no explanation."
)


class LLMConnector:
    """LLM integration with structured output + rate limiting + cache.

    Interface finalized in M3 (5 hooks).
    Phase 2: cache (Redis+memory) + real Ollama structured output.
    Phase 3 remaining: bind_tools, stream toggle.
    """

    def __init__(
        self,
        settings: Settings,
        rate_limiter=None,
    ) -> None:
        self._settings = settings
        self._model = settings.ollama_chat_model
        self._rate_limiter = rate_limiter
        # Phase 2: wired
        self._cache: LLMCache | None = None  # set via .cache setter
        self._structured_output: bool = True
        # Phase 3: deferred
        self._bind_tools: bool = False
        self._stream_enabled: bool = False

    @property
    def cache(self):
        return self._cache

    @cache.setter
    def cache(self, c: LLMCache | None) -> None:
        self._cache = c

    async def _call_ollama(self, prompt: str) -> list[dict[str, Any]]:
        """Call Ollama /api/chat with JSON format, return parsed steps."""
        url = f"{self._settings.ollama_base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("LLMConnector: Ollama chat failed: %s", exc)
            raise ConnectorError(f"Ollama chat call failed: {exc}") from exc

        content = data.get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLMConnector: non-JSON response, attempting substring parse")
            # attempt to extract the first complete JSON object from the response
            # find first '{' and its matching '}' via bracket counting
            start = content.find("{")
            if start != -1:
                depth = 0
                end = start
                for i in range(start, len(content)):
                    if content[i] == "{":
                        depth += 1
                    elif content[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if depth == 0:
                    parsed = json.loads(content[start:end])
                else:
                    raise ConnectorError(f"LLM returned unbalanced JSON: {content[:200]}") from None
            else:
                raise ConnectorError(f"LLM returned non-JSON: {content[:200]}") from None

        steps = parsed.get("steps", [])
        if not steps:
            raise ConnectorError("LLM returned empty steps")
        return steps

    async def plan(self, prompt: str, *, tools: list[dict] | None = None) -> list[dict[str, Any]]:
        """Generate a Plan via LLM with structured output + cache.

        Phase 2: real Ollama call with JSON mode + Redis/memory cache.
        Falls back to RuleIntentPlanner if Ollama is unreachable.
        """
        # 1. Check cache
        if self._cache:
            cached = await self._cache.get(self._model, prompt)
            if cached is not None:
                logger.info("LLMConnector.plan: cache hit")
                return cached

        # 2. Try Ollama structured output
        try:
            steps = await self._call_ollama(prompt)
            # Cache the result
            if self._cache:
                await self._cache.set(self._model, prompt, steps)
            return steps
        except ConnectorError:
            logger.warning("LLMConnector.plan: Ollama failed, falling back to RuleIntentPlanner")
        except Exception:
            logger.exception("LLMConnector.plan: unexpected error, falling back")

        # 3. Fallback: RuleIntentPlanner
        from earp_server.planner.business_dictionary import RuleIntentPlanner

        resolver = RuleIntentPlanner()
        match = resolver.resolve(prompt)
        if match is None:
            raise ConnectorError(f"LLMConnector.plan: no match for prompt '{prompt}'")
        return [{"capability_id": match.capability_id, "input": match.input}]

    async def plan_structured(self, prompt: str) -> list[dict[str, Any]]:
        """Phase 2: LLM call with JSON structured output enforced.

        Identical to plan() — the JSON format is enforced at the Ollama API level
        via ``format: "json"``. plan() and plan_structured() share the same path.
        """
        return await self.plan(prompt)

    async def stream(self, prompt: str, *, system: str = "") -> AsyncGenerator[TokenEvent, None]:
        """Stream tokens from Ollama /api/chat with stream=true.

        Yields TokenEvent for each token chunk from the LLM.
        Handles Ollama's NDJSON streaming format.
        """
        from earp_server.orchestrator.types import TokenEvent

        url = f"{self._settings.ollama_base_url}/api/chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.7},
        }
        index = 0
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("done"):
                            break
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield TokenEvent(token=content, index=index)
                            index += 1
        except httpx.HTTPError as exc:
            logger.error("LLMConnector.stream: Ollama streaming failed: %s", exc)
            raise ConnectorError(f"Ollama streaming failed: {exc}") from exc
