"""CapabilityInvoker — invoke Capabilities and search/resolve them."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from earp_sdk_core import (
    CapabilityError,
    CapabilityErrorCode,
    CapabilityNotFoundError,
    PermissionDeniedError,
    RateLimitExceededError,
)
from earp_sdk_runtime import USER_AGENT
from earp_sdk_runtime.models import (
    CapabilityInfo,
    ResolvedCapability,
    SearchResponse,
)


# Maps HTTP status to Runtime SDK exceptions
_STATUS_ERROR_MAP: dict[int, type[CapabilityError]] = {
    404: CapabilityNotFoundError,
    403: PermissionDeniedError,
    429: RateLimitExceededError,
}


class CapabilityInvoker:
    """Invoke Capabilities via the EARP Runtime endpoint.

    Each invoke() call goes through the Resolution Engine
    (semantic match → graph traversal → policy filtering → availability check).
    This is the production counterpart of Capability SDK's MockRuntime.
    """

    def __init__(
        self,
        session_id: str,
        client: httpx.AsyncClient,
        endpoint: str,
    ) -> None:
        self._session_id = session_id
        self._client = client
        self._endpoint = endpoint

    async def invoke(
        self,
        capability_id: str,
        params: dict[str, Any],
        *,
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a Capability.

        Args:
            capability_id: The Capability to invoke.
            params: Input parameters (aligned with input_schema).
            timeout_seconds: Request timeout.
            idempotency_key: Idempotency key for safe retry.
                Strongly recommended for Command-type Capabilities
                (e.g. idempotency_key=f"wo-{order_id}").

        Returns:
            Dict result (structure defined by the Capability's output_schema).

        Raises:
            CapabilityNotFoundError: capability_id does not exist.
            PermissionDeniedError: No access.
            RateLimitExceededError: Rate limited (retryable).
            CapabilityError: Other execution failures.
        """
        headers = {"X-Trace-Id": str(uuid.uuid4())}

        body: dict[str, Any] = {
            "capability_id": capability_id,
            "params": params,
            "session_id": self._session_id,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key

        response = await self._client.post(
            f"{self._endpoint}/v1/executions",
            json=body,
            headers=headers,
            timeout=timeout_seconds,
        )

        if response.is_success:
            data = response.json()
            return data.get("result", data)

        # Map HTTP errors to typed exceptions
        if response.status_code == 429:
            raise RateLimitExceededError()
        error_cls = _STATUS_ERROR_MAP.get(response.status_code)
        if error_cls is not None:
            raise error_cls(capability_id=capability_id)

        # Generic CapabilityError for other failures
        try:
            err_body = response.json()
            code = err_body.get("error", "SYSTEM_ERROR")
            message = err_body.get("message", response.text)
        except Exception:
            code = "SYSTEM_ERROR"
            message = response.text

        raise CapabilityError(code, message)

    async def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SearchResponse:
        """Search for Capabilities (keyword-based)."""
        params: dict[str, Any] = {"q": query, "page": page, "page_size": page_size}
        if domain:
            params["domain"] = domain

        response = await self._client.get(
            f"{self._endpoint}/v1/capabilities/search",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        results_list = data.get("results", data.get("data", []))
        results = [
            CapabilityInfo(
                capability_id=r.get("capability_id", ""),
                name=r.get("name", ""),
                description=r.get("description", ""),
                domain=r.get("domain", ""),
                version=r.get("version", ""),
                capability_type=r.get("capability_type", ""),
                tags=r.get("tags", []),
            )
            for r in results_list
        ]
        return SearchResponse(
            results=results,
            page=data.get("page", page),
            page_size=data.get("page_size", page_size),
            total=data.get("total", len(results)),
        )

    async def resolve(
        self,
        intent: str,
        domain: str | None = None,
    ) -> list[ResolvedCapability]:
        """Resolve a natural language intent to matching Capabilities.

        Unlike search() (keyword match), resolve() uses the Resolution Engine
        for semantic understanding + graph traversal + policy filtering.

        Results are sorted by confidence (descending).
        """
        body: dict[str, Any] = {"intent": intent}
        if domain:
            body["domain"] = domain

        response = await self._client.post(
            f"{self._endpoint}/v1/resolve",
            json=body,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("results", data.get("capabilities", []))
        return [
            ResolvedCapability(
                capability_id=item.get("capability_id", ""),
                confidence=item.get("confidence", 0.0),
                reason=item.get("reason", ""),
                fallback_capabilities=item.get("fallback_capabilities", []),
            )
            for item in items
        ]
