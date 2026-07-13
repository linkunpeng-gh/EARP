"""Tests for the Discovery client.

Uses httpx mock transport to avoid requiring a real Registry API.
"""

from __future__ import annotations

import json

import httpx
import pytest

from earp_sdk_capability.discovery.client import (
    CapabilityDiscoveryClient,
    DiscoveryError,
    SearchResult,
    SearchResponse,
)


# ── Helper: mock transport ──


def _make_transport(handler) -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        return handler(request)
    return httpx.MockTransport(_handler)


# ── Test data ──

SAMPLE_RESULTS = [
    {
        "capability_id": "query_equipment_alarm",
        "name": "查询设备报警",
        "version": "1.0.0",
        "description": "根据设备ID查询当前报警信息",
        "confidence": 0.95,
        "domain": "equipment",
        "tags": ["equipment", "alarm"],
    },
    {
        "capability_id": "query_equipment_status",
        "name": "查询设备状态",
        "version": "1.0.0",
        "description": "查询设备运行状态",
        "confidence": 0.82,
        "domain": "equipment",
        "tags": ["equipment", "status"],
    },
]

SAMPLE_RESPONSE = {
    "results": SAMPLE_RESULTS,
    "page": 1,
    "page_size": 20,
    "total": 2,
}

EMPTY_RESPONSE = {
    "results": [],
    "page": 1,
    "page_size": 20,
    "total": 0,
}


# ── Tests ──


class TestDiscoveryClient:
    async def test_search_basic(self):
        """search() returns matching capabilities."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "q=alarm" in str(request.url)
            return httpx.Response(200, json=SAMPLE_RESPONSE)

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.search("alarm")
        assert len(result.results) == 2
        assert result.results[0].capability_id == "query_equipment_alarm"
        assert result.results[0].confidence == 0.95
        assert result.page == 1
        assert result.total == 2
        await client.close()

    async def test_search_with_domain(self):
        """search() passes domain filter as query param."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "domain=equipment" in str(request.url)
            return httpx.Response(200, json=SAMPLE_RESPONSE)

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.search("alarm", domain="equipment")
        assert len(result.results) == 2
        await client.close()

    async def test_search_with_pagination(self):
        """search() passes pagination params."""

        captured_url = ""

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json={
                "results": [SAMPLE_RESULTS[0]],
                "page": 2,
                "page_size": 1,
                "total": 2,
            })

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.search("alarm", page=2, page_size=1)
        assert "page=2" in captured_url
        assert "page_size=1" in captured_url
        assert result.page == 2
        assert result.page_size == 1
        assert result.total == 2
        assert len(result.results) == 1
        await client.close()

    async def test_search_empty_results(self):
        """Empty results return SearchResponse with empty list."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=EMPTY_RESPONSE)

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.search("nonexistent")
        assert len(result.results) == 0
        assert result.total == 0
        await client.close()

    async def test_search_http_error(self):
        """Non-200 raises DiscoveryError."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "INTERNAL_ERROR"})

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        with pytest.raises(DiscoveryError) as exc:
            await client.search("test")
        assert exc.value.status_code == 500
        await client.close()

    async def test_list_by_domain(self):
        """list_by_domain() filters by domain."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "domain=equipment" in str(request.url)
            return httpx.Response(200, json=SAMPLE_RESPONSE)

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.list_by_domain("equipment")
        assert len(result.results) == 2
        await client.close()

    async def test_list_by_domain_empty(self):
        """list_by_domain() on empty domain returns empty."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=EMPTY_RESPONSE)

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.list_by_domain("nonexistent")
        assert len(result.results) == 0
        await client.close()

    async def test_search_result_dataclass(self):
        """SearchResult fields are populated correctly."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SAMPLE_RESPONSE)

        client = CapabilityDiscoveryClient(
            api_url="http://mock",
            client=httpx.AsyncClient(transport=_make_transport(handler)),
        )
        result = await client.search("alarm")
        sr = result.results[0]
        assert sr.capability_id == "query_equipment_alarm"
        assert sr.name == "查询设备报警"
        assert sr.version == "1.0.0"
        assert sr.description != ""
        assert sr.confidence == 0.95
        assert sr.domain == "equipment"
        assert "alarm" in sr.tags
        await client.close()
