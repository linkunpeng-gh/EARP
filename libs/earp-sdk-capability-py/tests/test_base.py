"""Tests for Capability base class v1.3 additions: status, fallback_capability_id, CapabilityResult."""

import pytest
from pydantic import BaseModel

from earp_sdk_capability import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    CapabilityUsage,
    CommandCapability,
    QueryCapability,
    capability,
)


class TestStatusField:
    """AC-01: status field."""

    def test_default_status_draft(self):
        class MyCap(QueryCapability):
            capability_id = "test_status"
            name = "test"
            description = "test"

            async def execute(self, ctx, params):
                return params

        cap = MyCap()
        assert cap.status == "draft"

    def test_custom_status(self):
        class MyCap(QueryCapability):
            capability_id = "test_status"
            name = "test"
            description = "test"
            status = "active"

            async def execute(self, ctx, params):
                return params

        cap = MyCap()
        assert cap.status == "active"

    def test_decorator_status(self):
        @capability(capability_id="test_dec", name="test", status="deprecated")
        class MyCap(QueryCapability):
            async def execute(self, ctx, params):
                return params

        assert MyCap.status == "deprecated"

    def test_status_valid_values(self):
        for val in ("draft", "active", "deprecated", "retired"):
            cap_cls = type(
                f"Test{val}",
                (QueryCapability,),
                {"capability_id": f"test_{val}", "name": val, "description": val, "status": val, "execute": lambda s,c,p: p},
            )
            assert cap_cls.status == val


class TestFallbackCapabilityId:
    """AC-02: fallback_capability_id field."""

    def test_default_fallback(self):
        class MyCap(QueryCapability):
            capability_id = "test_fb"
            name = "test"
            description = "test"

            async def execute(self, ctx, params):
                return params

        cap = MyCap()
        assert cap.fallback_capability_id == ""

    def test_set_fallback(self):
        class MyCap(QueryCapability):
            capability_id = "test_fb"
            name = "test"
            description = "test"
            fallback_capability_id = "backup_cap"

            async def execute(self, ctx, params):
                return params

        cap = MyCap()
        assert cap.fallback_capability_id == "backup_cap"

    def test_decorator_fallback(self):
        @capability(capability_id="test_fb_dec", name="t", fallback_capability_id="backup_001")
        class MyCap(QueryCapability):
            async def execute(self, ctx, params):
                return params

        assert MyCap.fallback_capability_id == "backup_001"


class TestCapabilityResult:
    """AC-03: CapabilityResult dataclass."""

    def test_ok_result(self):
        r = CapabilityResult(status="ok", output={"x": 1})
        assert r.is_ok()
        assert not r.is_retriable()

    def test_error_result(self):
        r = CapabilityResult(status="error", error="timeout", error_code="TIMEOUT")
        assert not r.is_ok()

    def test_retry_result(self):
        r = CapabilityResult(status="retry")
        assert r.is_retriable()

    def test_usage_tracking(self):
        u = CapabilityUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, duration_ms=1200)
        assert u.total_tokens == 150
        r = CapabilityResult(status="ok", usage=u)
        assert r.usage.total_tokens == 150

    def test_paused_result(self):
        r = CapabilityResult(status="paused", error="awaiting approval")
        assert r.status == "paused"
        assert not r.is_ok()
