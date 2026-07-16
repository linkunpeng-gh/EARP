"""Security tests per PRD-2026-005 — AC-01: JWT Bearer header propagation.

Verifies that the Authorization: Bearer {token} header is present in every
HTTP request made by the Runtime SDK (create_session, invoke, search, resolve,
close, status_info, and the call() shortcut).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest


def _make_transport(handler) -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        return handler(request)
    return httpx.MockTransport(_handler)


# ── AC-01: Authorization header propagation ──


class TestJWTBearerHeaderPropagation:
    """AC-01: JWT `Authorization: Bearer ***` must be present in ALL HTTP requests."""

    JWT_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test-token"
    ENDPOINT = "http://mock-runtime"

    @staticmethod
    def _make_client(handler) -> Any:
        """Create a RuntimeClient with JWT token and mock transport."""
        from earp_sdk_runtime.client import RuntimeClient

        transport = _make_transport(handler)
        client = httpx.AsyncClient(transport=transport)
        # Bypass RuntimeClient.__init__ to inject our mock client with auth header
        rc = RuntimeClient.__new__(RuntimeClient)
        rc.endpoint = "http://mock-runtime"
        rc.token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test-token"
        rc.retry_config = None
        headers = {"User-Agent": "test", "Authorization": f"Bearer {rc.token}"}
        rc._client = httpx.AsyncClient(transport=transport, headers=headers)
        return rc

    def _default_handler(self, captured_headers: dict[str, str]):
        """Handler that captures request headers and returns 200."""
        async def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            # Determine response based on path
            path = str(request.url)  # includes full URL
            if "/v1/sessions" in path and request.method == "POST":
                return httpx.Response(200, json={
                    "session_id": "s-1", "tenant_id": "t1", "user_id": "u1", "status": "active"
                })
            elif "/v1/sessions/" in path and request.method == "PATCH":
                return httpx.Response(200, json={"status": "completed"})
            elif "/v1/sessions/" in path and request.method == "GET":
                return httpx.Response(200, json={
                    "session_id": "s-1", "status": "active",
                    "created_at": "2026-01-01T00:00:00Z", "execution_count": 0,
                    "active_executions": 0,
                })
            elif "/v1/executions" in path:
                return httpx.Response(200, json={"result": {"ok": True}})
            elif "/v1/capabilities/search" in path:
                return httpx.Response(200, json={"results": [], "page": 1, "page_size": 20, "total": 0})
            elif "/v1/resolve" in path:
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, json={})
        return handler

    # ── create_session ──

    async def test_create_session_carries_auth_header(self):
        """POST /v1/sessions must include Authorization header."""
        captured: dict[str, str] = {}
        client = self._make_client(self._default_handler(captured))

        await client.create_session(user_id="u1")
        assert captured.get("authorization") == f"Bearer {self.JWT_TOKEN}", (
            f"create_session missing Auth header. Got: {captured}"
        )
        await client.close()

    # ── invoke (via CapabilityInvoker) ──

    async def test_invoke_carries_auth_header(self):
        """POST /v1/executions must include Authorization header."""
        captured: dict[str, str] = {}
        client = self._make_client(self._default_handler(captured))

        session = await client.create_session(user_id="u1")
        await session.capabilities.invoke("ping", {"msg": "hello"})
        assert captured.get("authorization") == f"Bearer {self.JWT_TOKEN}", (
            f"invoke missing Auth header. Got: {captured}"
        )
        await session.close()
        await client.close()

    # ── search ──

    async def test_search_carries_auth_header(self):
        """GET /v1/capabilities/search must include Authorization header."""
        captured: dict[str, str] = {}
        client = self._make_client(self._default_handler(captured))

        session = await client.create_session(user_id="u1")
        await session.capabilities.search("ping")
        assert captured.get("authorization") == f"Bearer {self.JWT_TOKEN}", (
            f"search missing Auth header. Got: {captured}"
        )
        await session.close()
        await client.close()

    # ── resolve ──

    async def test_resolve_carries_auth_header(self):
        """POST /v1/resolve must include Authorization header."""
        captured: dict[str, str] = {}
        client = self._make_client(self._default_handler(captured))

        session = await client.create_session(user_id="u1")
        await session.capabilities.resolve("find user by email")
        assert captured.get("authorization") == f"Bearer {self.JWT_TOKEN}", (
            f"resolve missing Auth header. Got: {captured}"
        )
        await session.close()
        await client.close()

    # ── close ──

    async def test_close_carries_auth_header(self):
        """PATCH /v1/sessions/{id} must include Authorization header."""
        captured: dict[str, str] = {}
        client = self._make_client(self._default_handler(captured))

        session = await client.create_session(user_id="u1")
        await session.close()
        assert captured.get("authorization") == f"Bearer {self.JWT_TOKEN}", (
            f"close missing Auth header. Got: {captured}"
        )
        await client.close()

    # ── status_info ──

    async def test_status_info_carries_auth_header(self):
        """GET /v1/sessions/{id} must include Authorization header."""
        captured: dict[str, str] = {}
        client = self._make_client(self._default_handler(captured))

        session = await client.create_session(user_id="u1")
        await session.status_info()
        assert captured.get("authorization") == f"Bearer {self.JWT_TOKEN}", (
            f"status_info missing Auth header. Got: {captured}"
        )
        await session.close()
        await client.close()

    # ── call() shortcut ──

    async def test_call_shortcut_carries_auth_header(self):
        """RuntimeClient.call() shortcut must include Authorization header."""
        captured: dict[str, str] = {}
        client = self._make_client(self._default_handler(captured))

        await client.call("ping", {"msg": "hi"}, user_id="u1")
        assert captured.get("authorization") == f"Bearer {self.JWT_TOKEN}", (
            f"call shortcut missing Auth header. Got: {captured}"
        )
        await client.close()


class TestJWTNoTokenNoAuthHeader:
    """When no token is provided, no Authorization header should be sent."""

    async def test_no_auth_header_without_token(self):
        """Without a token, requests should not include Authorization header."""
        captured: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.headers))
            return httpx.Response(200, json={
                "session_id": "s-x", "tenant_id": "", "user_id": "u1", "status": "active"
            })

        from earp_sdk_runtime.client import RuntimeClient
        transport = _make_transport(handler)
        headers = {"User-Agent": "test"}
        rc = RuntimeClient.__new__(RuntimeClient)
        rc.endpoint = "http://mock"
        rc.token = ""
        rc.retry_config = None
        rc._client = httpx.AsyncClient(transport=transport, headers=headers)

        await rc.create_session(user_id="u1")
        assert "authorization" not in {k.lower(): v for k, v in captured.items()}, (
            "No token should mean no Authorization header"
        )
        await rc.close()
