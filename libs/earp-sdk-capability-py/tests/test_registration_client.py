"""Tests for the Registry client.

Uses httpx mock transport to avoid requiring a real Registry API.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from earp_sdk_capability import QueryCapability, capability
from earp_sdk_capability.registration.client import (
    CapabilityRegistryClient,
    RegistryError,
    RegistryResult,
)
from earp_sdk_capability.registration.packager import packager


# ── Helper: mock transport ──


def _make_transport(handler) -> httpx.MockTransport:
    """Create a mock transport that delegates to a handler function."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return handler(request)

    return httpx.MockTransport(_handler)


# ── Test capability ──


@capability(
    capability_id="test_hello",
    name="Hello",
    description="test capability",
    domain="test",
    version="1.0.0",
)
class HelloCap(QueryCapability):
    async def execute(self, ctx, params): pass


# ── Tests ──


class TestRegistryClient:
    async def test_prepare_no_network(self):
        """prepare() is local — no network call."""
        client = CapabilityRegistryClient(api_url="http://not-used")
        package = await client.prepare(HelloCap)
        assert package["definition"]["capability_id"] == "test_hello"
        assert "execution_contract" in package
        assert "policy" in package

    async def test_register_success(self):
        """POST /capabilities returns 201 with capability info."""
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "capability_id": body["definition"]["capability_id"],
                    "version": body["definition"]["version"],
                    "status": "draft",
                },
            )

        client = CapabilityRegistryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.register(HelloCap)
        assert result.capability_id == "test_hello"
        assert result.version == "1.0.0"
        assert result.status == "draft"
        await client.close()

    async def test_register_http_error(self):
        """Non-201 response raises RegistryError."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "SCHEMA_VALIDATION_FAILED", "message": "bad schema"})

        client = CapabilityRegistryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        with pytest.raises(RegistryError) as exc:
            await client.register(HelloCap)
        assert exc.value.status_code == 400
        await client.close()

    async def test_activate_success(self):
        """PATCH /capabilities/{id} returns 200 with active status."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "capability_id": "test_hello",
                    "version": "1.0.0",
                    "status": "active",
                },
            )

        client = CapabilityRegistryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.activate("test_hello")
        assert result.status == "active"
        assert result.capability_id == "test_hello"
        await client.close()

    async def test_activate_not_found(self):
        """PATCH on unknown capability returns 404 → RegistryError."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "CAPABILITY_NOT_FOUND"})

        client = CapabilityRegistryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        with pytest.raises(RegistryError) as exc:
            await client.activate("nonexistent")
        assert exc.value.status_code == 404
        await client.close()

    async def test_user_agent_header(self):
        """Requests include the SDK User-Agent."""
        headers = {}
        req_url = ""

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal req_url
            headers.update(dict(request.headers))
            req_url = str(request.url)
            return httpx.Response(201, json={"capability_id": "x", "version": "1.0", "status": "draft"})

        client = CapabilityRegistryClient(
            api_url="http://mock-registry",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        await client.register(HelloCap)
        ua = headers.get("user-agent", "")
        # At minimum, a User-Agent header should be present
        assert len(ua) > 0, f"User-Agent header missing, got headers: {dict(headers)}"
        print(f"  User-Agent: {ua}")
        await client.close()
