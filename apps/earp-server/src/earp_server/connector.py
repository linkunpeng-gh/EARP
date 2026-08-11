"""Capability execution + LLM planning channels.

M1: Connector.execute (capability call)
M3/M8: LLMConnector.plan — structured output via Ollama + Redis cache
M11: Dynamic capability injection in system prompt + plan validation
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
    from earp_server.infra.langfuse_tracer import LangfuseTracer
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


# ── LLMConnector (M3, Phase 2/3 enhanced) ────────────────────────────────────


def _build_plan_system_prompt(capabilities: list[dict[str, Any]] | None = None) -> str:
    """Build a system prompt dynamically from available capabilities.

    When capabilities are provided, lists them in the prompt.
    Falls back to a minimal default if none provided.
    """
    base = (
        "You are an intent-to-action planner. Given a user intent, output a JSON plan "
        'with exactly this structure: {"steps": [{"capability_id": "...", "input": {...}}]}. '
    )
    if capabilities:
        cap_list = ", ".join(f"{c['name']} ({c['capability_id']})" for c in capabilities)
        base += f"Available capabilities: {cap_list}. "
    else:
        base += (
            "Available capabilities: echo (cap-demo-echo), query users (cap-query-users), "
            "create alarm (cap-create-alarm), query alarms (cap-query-alarms). "
        )
    base += "Output ONLY valid JSON, no explanation."
    return base


class LLMConnector:
    """LLM integration with structured output + rate limiting + cache.

    Interface finalized in M3 (5 hooks).
    Phase 2: cache (Redis+memory) + real Ollama structured output.
    Phase 3 (M11): dynamic capability injection + plan validation.
    Remaining: bind_tools, stream toggle.
    """

    def __init__(
        self,
        settings: Settings,
        rate_limiter=None,
        model_override: dict | None = None,
    ) -> None:
        """model_override: {provider, model_name, base_url, api_key, ...} from DB model_config
        (PRD-2026-031) — DB 优先，env 兜底。"""
        self._settings = settings
        self._model_override = model_override or {}
        self._provider = self._model_override.get("provider") or "ollama"
        self._model = self._model_override.get("model_name") or settings.ollama_chat_model
        self._base_url = self._model_override.get("base_url") or settings.ollama_base_url
        self._api_key = self._model_override.get("api_key") or ""
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

    # M15: Langfuse tracer — set by lifespan
    tracer: LangfuseTracer | None = None

    async def _call_ollama(
        self,
        prompt: str,
        *,
        capabilities: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Call Ollama /api/chat with JSON format, return parsed steps."""
        system = _build_plan_system_prompt(capabilities)
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
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

    async def plan(
        self,
        prompt: str,
        *,
        tools: list[dict] | None = None,
        capabilities: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate a Plan via LLM with structured output + cache.

        Phase 2: real Ollama call with JSON mode + Redis/memory cache.
        Phase 3: dynamic capability injection + plan validation.
        Falls back to RuleIntentPlanner if Ollama is unreachable.
        """
        # 1. Check cache
        cache_key = f"{self._model}||{prompt}||{json.dumps(capabilities or [])}"
        if self._cache:
            cached = await self._cache.get(self._model, cache_key)
            if cached is not None:
                logger.info("LLMConnector.plan: cache hit")
                return cached

        # 2. Try Ollama structured output (skip if capabilities list is explicitly empty)
        if capabilities is not None and len(capabilities) == 0:
            logger.info("LLMConnector.plan: empty capabilities list, skipping Ollama")
        else:
            try:
                import time

                t0 = time.monotonic()
                steps = await self._call_ollama(prompt, capabilities=capabilities)
                latency_ms = int((time.monotonic() - t0) * 1000)
                if self.tracer:
                    self.tracer.trace_llm(
                        "plan",
                        self._model,
                        prompt[:200],
                        output=json.dumps(steps)[:500],
                        latency_ms=latency_ms,
                        usage={"output_tokens": len(json.dumps(steps).split())},
                    )
                # Validate: capability_ids must exist in provided capabilities list
                if capabilities:
                    valid_ids = {c["capability_id"] for c in capabilities}
                    for s in steps:
                        cid = s.get("capability_id", "")
                        if cid not in valid_ids:
                            logger.warning(
                                "LLMConnector.plan: unknown capability_id %r, discarding step",
                                cid,
                            )
                    steps = [s for s in steps if s.get("capability_id", "") in valid_ids]
                    if not steps:
                        raise ConnectorError("LLM returned steps with no valid capability_ids")
                # Cache the result
                if self._cache:
                    await self._cache.set(self._model, cache_key, steps)
                return steps
            except ConnectorError:
                logger.warning("LLMConnector.plan: Ollama failed, falling back to RuleIntentPlanner")
                if self.tracer:
                    self.tracer.trace_llm(
                        "plan",
                        self._model,
                        prompt[:200],
                        error="Ollama failed — fell back to RuleIntentPlanner",
                        latency_ms=0,
                    )
            except Exception:
                logger.exception("LLMConnector.plan: unexpected error, falling back")
                if self.tracer:
                    self.tracer.trace_llm(
                        "plan",
                        self._model,
                        prompt[:200],
                        error="unexpected error",
                        latency_ms=0,
                    )

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

    async def _stream_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[TokenEvent, None]:
        """Stream tokens for a full message list from /api/chat with stream=true.

        Uses model_override (DB model_configs, PRD-2026-031) when configured:
        base_url/model from the override, api_key header for non-ollama providers.
        Yields TokenEvent per token; handles Ollama NDJSON streaming.
        """
        from earp_server.orchestrator.types import TokenEvent

        # FIX（评审已实证）：旧实现直接用 settings.ollama_base_url，忽略构造器算好的
        # self._base_url（model_override）—— 统一改走 self._base_url
        url = f"{self._base_url}/api/chat"
        headers = {}
        if self._api_key and self._provider != "ollama":
            headers["Authorization"] = f"Bearer {self._api_key}"
        options: dict[str, Any] = {"temperature": temperature}
        if top_p is not None:
            options["top_p"] = top_p
        if max_tokens:
            options["num_predict"] = max_tokens  # Ollama num_predict = max_tokens
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "options": options,
        }
        index = 0
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
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

    async def stream(self, prompt: str, *, system: str = "") -> AsyncGenerator[TokenEvent, None]:
        """Stream tokens from Ollama /api/chat with stream=true.

        Yields TokenEvent for each token chunk from the LLM.
        Handles Ollama's NDJSON streaming format.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for ev in self._stream_messages(messages):
            yield ev

    async def chat_stream(
        self,
        system: str,
        history: list[dict[str, str]],
        query: str,
        *,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[TokenEvent, None]:
        """RAG chat streaming — full message list (system + history + current query).

        history: [{"role": "user"|"assistant", "content": ...}]（最近 N 对，已配对）
        temperature/top_p/max_tokens: 应用级生成参数（chat_apps.generation）
        """
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})
        async for ev in self._stream_messages(messages, temperature=temperature, top_p=top_p, max_tokens=max_tokens):
            yield ev
