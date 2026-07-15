"""Tests for MockRuntimeClient and core Runtime SDK types."""

from __future__ import annotations

import pytest

from earp_sdk_core import (
    CapabilityNotFoundError,
    PermissionDeniedError,
    RateLimitExceededError,
    CapabilityErrorCode,
)
from earp_sdk_runtime import MockRuntimeClient
from earp_sdk_runtime.models import CapabilityInfo, SearchResponse, ResolvedCapability


# ── Tests: MockRuntimeClient ──


class TestMockRuntimeClient:
    async def test_invoke_basic(self):
        mock = MockRuntimeClient()
        mock.register("ping", lambda p: {"echo": p["message"]})
        result = await mock.invoke("ping", {"message": "hello"})
        assert result == {"echo": "hello"}

    async def test_call_shortcut(self):
        mock = MockRuntimeClient()
        mock.register("ping", lambda p: {"echo": p["message"]})
        result = await mock.call("ping", {"message": "world"})
        assert result["echo"] == "world"

    async def test_invoke_not_registered(self):
        mock = MockRuntimeClient()
        with pytest.raises(ValueError, match="not registered"):
            await mock.invoke("nonexistent", {})

    async def test_register_with_info(self):
        mock = MockRuntimeClient()
        info = CapabilityInfo(
            capability_id="query_alarm",
            name="Query Alarm",
            domain="equipment",
        )
        mock.register("query_alarm", lambda p: p, info=info)
        assert mock._capabilities["query_alarm"].domain == "equipment"

    async def test_search_by_name(self):
        mock = MockRuntimeClient()
        mock.register("ping", lambda p: p,
                      info=CapabilityInfo(capability_id="ping", name="Ping Service"))
        mock.register("echo", lambda p: p,
                      info=CapabilityInfo(capability_id="echo", name="Echo Service"))
        result = await mock.search("ping")
        assert result.total == 1
        assert result.results[0].capability_id == "ping"

    async def test_search_with_domain_filter(self):
        mock = MockRuntimeClient()
        mock.register("a", lambda p: p, info=CapabilityInfo(capability_id="a", name="A", domain="x"))
        mock.register("b", lambda p: p, info=CapabilityInfo(capability_id="b", name="B", domain="y"))
        result = await mock.search("", domain="x")
        assert result.total == 1
        assert result.results[0].capability_id == "a"

    async def test_search_empty(self):
        mock = MockRuntimeClient()
        result = await mock.search("nothing")
        assert result.total == 0
        assert len(result.results) == 0

    async def test_set_trace_id(self):
        mock = MockRuntimeClient()
        mock.set_trace_id("trace-123")
        assert mock._trace_id == "trace-123"

    async def test_create_session_returns_self(self):
        mock = MockRuntimeClient()
        result = await mock.create_session(user_id="test")
        assert result is mock


# ── Tests: Error types ──


class TestRuntimeErrors:
    def test_capability_not_found(self):
        err = CapabilityNotFoundError(capability_id="missing")
        assert "missing" in str(err)
        assert err.code == CapabilityErrorCode.CAPABILITY_NOT_FOUND

    def test_permission_denied(self):
        err = PermissionDeniedError(capability_id="secret")
        assert "secret" in str(err)
        assert err.code == CapabilityErrorCode.PERMISSION_DENIED

    def test_rate_limit_exceeded(self):
        err = RateLimitExceededError(retry_after=30)
        assert err.retry_after == 30
        assert err.code == CapabilityErrorCode.RATE_LIMIT_EXCEEDED

    def test_subclass_hierarchy(self):
        """All three are subclasses of CapabilityError."""
        from earp_sdk_core import CapabilityError
        assert issubclass(CapabilityNotFoundError, CapabilityError)
        assert issubclass(PermissionDeniedError, CapabilityError)
        assert issubclass(RateLimitExceededError, CapabilityError)


# ── Tests: Models ──


class TestModels:
    def test_capability_info_defaults(self):
        info = CapabilityInfo(capability_id="test", name="Test")
        assert info.version == ""
        assert info.tags == []

    def test_search_response_defaults(self):
        sr = SearchResponse()
        assert sr.results == []
        assert sr.page == 1
        assert sr.total == 0

    def test_resolved_capability(self):
        rc = ResolvedCapability(
            capability_id="test",
            confidence=0.95,
            reason="Best match",
        )
        assert rc.confidence == 0.95
        assert rc.fallback_capabilities == []
