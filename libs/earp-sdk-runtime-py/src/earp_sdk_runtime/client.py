"""RuntimeClient — main entry point for the EARP Runtime SDK."""

from __future__ import annotations

from typing import Any

import httpx

from earp_sdk_runtime import USER_AGENT
from earp_sdk_runtime.models import RetryConfig
from earp_sdk_runtime.session import Session

USER_AGENT = "earp-sdk-runtime/0.1.0.dev0"


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

    # ── Session management ──

    async def create_session(
        self,
        *,
        user_id: str,
        tenant_id: str = "",
        ttl_seconds: int = 3600,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new EARP Session.

        Args:
            user_id: (MUST) Creator user identifier. Aligns with L2-01 §6.3.
            tenant_id: Tenant scope.
            ttl_seconds: Session TTL in seconds.
            metadata: Extended metadata.

        Returns:
            A Session instance bound to this client.
        """
        if not user_id:
            raise ValueError("user_id is required (L2-01 §6.3 MUST)")

        response = await self._client.post(
            f"{self.endpoint}/v1/sessions",
            json={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "ttl_seconds": ttl_seconds,
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
        tenant_id: str = "",
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
            timeout_seconds: Request timeout.
            idempotency_key: (Command) Idempotency key for safe retry.

        Returns:
            Dict result (structure defined by the Capability's output_schema).
        """
        session = await self.create_session(
            user_id=user_id or "anonymous",
            tenant_id=tenant_id,
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

    # ── Lifecycle ──

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "RuntimeClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
