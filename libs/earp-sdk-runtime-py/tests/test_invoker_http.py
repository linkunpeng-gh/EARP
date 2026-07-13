"""Integration tests for HTTP client paths using httpx MockTransport.

Covers CapabilityInvoker.invoke(), search(), resolve() and Session lifecycle.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from earp_sdk_core import (
    CapabilityNotFoundError,
    PermissionDeniedError,
    RateLimitExceededError,
)


# ── Helper ──


def _make_transport(handler) -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        return handler(request)
    return httpx.MockTransport(_handler)


# ── Tests: CapabilityInvoker ──


class TestInvokerHTTP:
    async def _make_invoker(self, handler) -> Any:
        """Create a CapabilityInvoker backed by a mock HTTP transport."""
        from earp_sdk_runtime.invoker import CapabilityInvoker

        client = httpx.AsyncClient(transport=_make_transport(handler))
        return CapabilityInvoker(
            session_id="test-session",
            client=client,
            endpoint="http://mock",
        )

    async def test_invoke_success(self):
        """Successful invoke returns result dict."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["capability_id"] == "ping"
            assert "session_id" in body
            return httpx.Response(200, json={"result": {"echo": body["params"]["message"]}})

        invoker = await self._make_invoker(handler)
        result = await invoker.invoke("ping", {"message": "hello"})
        assert result == {"echo": "hello"}

    async def test_invoke_with_idempotency_key(self):
        """idempotency_key is passed in request body."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["idempotency_key"] == "key-001"
            return httpx.Response(200, json={"result": {"ok": True}})

        invoker = await self._make_invoker(handler)
        result = await invoker.invoke("ping", {}, idempotency_key="key-001")
        assert result["ok"] is True

    async def test_invoke_not_found(self):
        """404 response raises CapabilityNotFoundError."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "CAPABILITY_NOT_FOUND"})

        invoker = await self._make_invoker(handler)
        with pytest.raises(CapabilityNotFoundError) as exc:
            await invoker.invoke("missing", {})
        assert "missing" in str(exc.value)

    async def test_invoke_permission_denied(self):
        """403 response raises PermissionDeniedError."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "PERMISSION_DENIED"})

        invoker = await self._make_invoker(handler)
        with pytest.raises(PermissionDeniedError):
            await invoker.invoke("secret", {})

    async def test_invoke_rate_limited(self):
        """429 response raises RateLimitExceededError."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "RATE_LIMIT_EXCEEDED"})

        invoker = await self._make_invoker(handler)
        with pytest.raises(RateLimitExceededError):
            await invoker.invoke("ping", {})

    async def test_invoke_trace_id_header(self):
        """X-Trace-Id header is injected on every request."""
        captured_headers = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={"result": {}})

        invoker = await self._make_invoker(handler)
        await invoker.invoke("ping", {})
        assert "x-trace-id" in captured_headers
        trace_id = captured_headers["x-trace-id"]
        assert len(trace_id) > 0
        assert isinstance(trace_id, str)

    async def test_invoke_system_error(self):
        """500 response raises generic CapabilityError."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "SYSTEM_ERROR", "message": "DB down"})

        invoker = await self._make_invoker(handler)
        from earp_sdk_core import CapabilityError

        with pytest.raises(CapabilityError) as exc:
            await invoker.invoke("ping", {})
        assert "SYSTEM_ERROR" in str(exc.value)

    async def test_search_success(self):
        """search() returns paginated results."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "q=alarm" in str(request.url)
            return httpx.Response(200, json={
                "results": [{"capability_id": "a", "name": "Alarm Query"}],
                "page": 1, "page_size": 20, "total": 1,
            })

        invoker = await self._make_invoker(handler)
        result = await invoker.search("alarm")
        assert len(result.results) == 1
        assert result.results[0].capability_id == "a"

    async def test_resolve_success(self):
        """resolve() returns ResolvedCapability list."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["intent"] == "find alarm"
            return httpx.Response(200, json={
                "results": [
                    {"capability_id": "query_alarm", "confidence": 0.95, "reason": "best match"},
                ],
            })

        invoker = await self._make_invoker(handler)
        results = await invoker.resolve("find alarm")
        assert len(results) == 1
        assert results[0].capability_id == "query_alarm"
        assert results[0].confidence == 0.95

    async def test_search_with_domain(self):
        """search() passes domain filter."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "domain=equipment" in str(request.url)
            return httpx.Response(200, json={"results": [], "page": 1, "page_size": 20, "total": 0})

        invoker = await self._make_invoker(handler)
        result = await invoker.search("alarm", domain="equipment")
        assert result.total == 0


# ── Tests: Session lifecycle ──


class TestSessionHTTP:
    async def test_status_info(self):
        """Session.status_info() calls GET /v1/sessions/{id}."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "session_id": "s-001",
                "status": "active",
                "created_at": "2026-07-12T00:00:00Z",
                "execution_count": 5,
                "active_executions": 1,
            })

        from earp_sdk_runtime.session import Session

        client = httpx.AsyncClient(transport=_make_transport(handler))
        session = Session(
            session_id="s-001",
            tenant_id="",
            user_id="u-001",
            _client=client,
            _endpoint="http://mock",
        )
        status = await session.status_info()
        assert status.session_id == "s-001"
        assert status.execution_count == 5

    async def test_close(self):
        """Session.close() calls PATCH /v1/sessions/{id}."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["status"] == "completed"
            return httpx.Response(200, json={"status": "completed"})

        from earp_sdk_runtime.session import Session

        client = httpx.AsyncClient(transport=_make_transport(handler))
        session = Session(
            session_id="s-001",
            tenant_id="",
            user_id="u-001",
            _client=client,
            _endpoint="http://mock",
        )
        await session.close()
        assert session.status == "completed"
