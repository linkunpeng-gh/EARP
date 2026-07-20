"""RuntimeClient — main entry point for the EARP Runtime SDK."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx

from earp_sdk_runtime import USER_AGENT
from earp_sdk_runtime.models import RetryConfig
from earp_sdk_runtime.session import Session

USER_AGENT = "earp-sdk-runtime/0.1.0.dev0"
_UNSET = object()


class RuntimeClient:
    """Application entry point for connecting to the EARP Runtime.

    Args:
        endpoint: Runtime HTTP endpoint (e.g. http://runtime:8080).
        token: JWT Bearer token for authentication.
        retry_config: Retry policy. Default: 3 attempts, exponential backoff.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:8080",
        token: str = "",
        retry_config: RetryConfig | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.retry_config = retry_config or RetryConfig()

        headers = {"User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.AsyncClient(headers=headers)
        self._tenant_id: str | None = None
        self._role_id: str | None = None

    def set_tenant_id(self, tenant_id: str) -> None:
        """Switch tenant context for subsequent create_session() calls.

        Aligns with Dify Account._current_tenant setter pattern.
        """
        self._tenant_id = tenant_id

    def switch_role(self, role_id: str) -> None:
        """Switch current role for subsequent create_session() calls.

        Raises ValueError if role_id is empty.
        """
        if not role_id:
            raise ValueError("role_id must not be empty")
        self._role_id = role_id

    # ── Session management ──

    async def create_session(
        self,
        *,
        user_id: str,
        tenant_id: str | object = _UNSET,
        role_id: str | object = _UNSET,
        ttl_seconds: int = 3600,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new EARP Session.

        Args:
            user_id: (MUST) Creator user identifier. Aligns with L2-01 §6.3.
            tenant_id: (MUST) Tenant scope — Multi-Tenant Spec §3.2.
            role_id: (MUST) Current role — Policy Center Spec §5.1.
            ttl_seconds: Session TTL in seconds.
            metadata: Extended metadata.

        Returns:
            A Session instance bound to this client.
        """
        if not user_id:
            raise ValueError("user_id is required (L2-01 §6.3 MUST)")
        if tenant_id is _UNSET:
            if self._tenant_id:
                tenant_id = self._tenant_id
            else:
                raise ValueError("tenant_id is required — call set_tenant_id() or pass explicitly (Multi-Tenant Spec §3.2 MUST)")
        if role_id is _UNSET:
            if self._role_id:
                role_id = self._role_id
            else:
                raise ValueError("role_id is required — call switch_role() or pass explicitly (Policy Center Spec §5.1 MUST)")

        response = await self._client.post(
            f"{self.endpoint}/v1/sessions",
            json={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "role_id": role_id,
                "metadata": metadata or {},
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        return Session(
            session_id=data["session_id"],
            tenant_id=data.get("tenant_id", tenant_id),
            user_id=data["user_id"],
            status=data.get("status", "active"),
            _client=self._client,
            _endpoint=self.endpoint,
        )

    # ── Shortcut: create session → invoke → close ──

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any],
        *,
        user_id: str = "",
        tenant_id: str | object = _UNSET,
        role_id: str | object = _UNSET,
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a Capability with an auto-managed temporary Session.

        Suitable for one-off Query calls.
        For Command calls or multiple invocations, use create_session() + invoke().

        Args:
            capability_id: The Capability to invoke.
            params: Input parameters (aligned with input_schema).
            user_id: User identity for the ad-hoc session.
            tenant_id: Tenant scope.
            role_id: Current role — Policy Center Spec §5.1. (MUST) from set_role_id() callback
            timeout_seconds: Request timeout.
            idempotency_key: (Command) Idempotency key for safe retry.

        Returns:
            Dict result (structure defined by the Capability's output_schema).
        """
        session = await self.create_session(
            user_id=user_id or "anonymous",
            tenant_id=tenant_id,
            role_id=role_id,
        )
        try:
            return await session.capabilities.invoke(
                capability_id,
                params,
                timeout_seconds=timeout_seconds,
                idempotency_key=idempotency_key,
            )
        finally:
            await session.close()

    # ── Streaming (M8) ──

    async def stream_invoke(
        self,
        prompt: str,
        *,
        system: str = "",
        session_id: str = "",
    ) -> "AsyncGenerator[dict[str, Any], None]":
        """Stream LLM tokens via SSE from POST /stream/invoke.

        Yields dicts: {"token": str, "index": int} or {"error": str} on failure.
        Final event is {"token": "[DONE]", "index": -1}.
        """
        import json

        async with httpx.AsyncClient(timeout=300) as sse_client:
            async with sse_client.stream(
                "POST",
                f"{self.endpoint}/stream/invoke",
                json={"prompt": prompt, "system": system, "session_id": session_id},
                headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]  # strip "data: " prefix
                    if data_str == "[DONE]":
                        yield {"token": "[DONE]", "index": -1}
                        return
                    try:
                        yield json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

    # ── Planning (M11) ──

    async def plan(self, intent: str) -> list[dict[str, Any]]:
        """Call POST /plan to resolve intent → capability steps.

        Returns list of {"capability_id": str, "adapter_type": str, "input": dict}.
        """
        response = await self._client.post(
            f"{self.endpoint}/plan",
            json={"intent": intent},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("steps", [])

    # ── Lifecycle ──

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "RuntimeClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
