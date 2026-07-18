"""Tests for MockRuntime and MockConnector."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from earp_sdk_capability import (
    QueryCapability,
    CommandCapability,
    capability,
)
from earp_sdk_capability.testing.mock_runtime import MockRuntime
from earp_sdk_capability.testing.mock_connector import MockConnector, ConnectorRegistry
from earp_sdk_core import ConnectorError


# ── Test models ──


class PingInput(BaseModel):
    message: str


class PingOutput(BaseModel):
    echo: str
    status: str = "ok"


# ── Test capabilities ──


@capability(
    capability_id="ping",
    name="Ping",
    description="A simple ping capability for testing",
    domain="test",
)
class PingCap(QueryCapability[PingInput, PingOutput]):
    async def execute(self, ctx, params: PingInput) -> PingOutput:
        ctx.logger.info(f"Ping: {params.message}")
        return PingOutput(echo=params.message)


@capability(
    capability_id="weather_query",
    name="Weather Query",
    description="Query weather via connector",
    domain="weather",
)
class WeatherCap(QueryCapability[PingInput, PingOutput]):
    async def execute(self, ctx, params: PingInput) -> PingOutput:
        result = await ctx.connectors.weather.execute("get_forecast", {"city": params.message})
        return PingOutput(echo=str(result))


@capability(
    capability_id="orchestrator",
    name="Orchestrator",
    description="Invokes another capability internally",
    domain="test",
)
class OrchestratorCap(QueryCapability[PingInput, PingOutput]):
    async def execute(self, ctx, params: PingInput) -> PingOutput:
        intermediate = await ctx.capabilities.invoke("ping", {"message": f"nested:{params.message}"})
        return PingOutput(echo=f"orchestrated:{intermediate['echo']}")


class NoOpCmd(CommandCapability[PingInput, PingOutput]):
    capability_id = "noop_cmd"
    name = "NoOp Command"
    description = "A command for testing"
    domain = "test"

    async def execute(self, ctx, params: PingInput) -> PingOutput:
        return PingOutput(echo=params.message)


# ── Tests: MockConnector ──


class TestMockConnector:
    async def test_sync_handler(self):
        """Sync handler works."""
        conn = MockConnector({"ping": lambda p: {"ok": True}})
        result = await conn.execute("ping")
        assert result == {"ok": True}

    async def test_async_handler(self):
        """Async handler works."""
        async def handler(params):
            return {"echo": params.get("msg", "")}

        conn = MockConnector({"async_op": handler})
        result = await conn.execute("async_op", {"msg": "hello"})
        assert result == {"echo": "hello"}

    async def test_missing_operation_raises(self):
        """Unknown operation raises ConnectorError."""
        conn = MockConnector()
        with pytest.raises(ConnectorError, match="not registered"):
            await conn.execute("unknown_op")

    async def test_register_after_init(self):
        """Register handler after construction."""
        conn = MockConnector()
        conn.register("foo", lambda p: 42)
        result = await conn.execute("foo")
        assert result == 42


class TestConnectorRegistry:
    def test_dot_access(self):
        """ConnectorRegistry supports dot-access."""
        reg = ConnectorRegistry()
        conn = MockConnector({"op": lambda p: "ok"})
        reg.register("my_conn", conn)
        assert reg.my_conn is conn

    def test_missing_connector_raises(self):
        """Missing connector raises AttributeError."""
        reg = ConnectorRegistry()
        with pytest.raises(AttributeError, match="not registered"):
            _ = reg.unknown


# ── Tests: MockRuntime ──


class TestMockRuntime:
    async def test_execute_simple_cap(self):
        """Execute a simple Capability via MockRuntime."""
        runtime = MockRuntime()
        runtime.register(PingCap)
        result = await runtime.execute("ping", {"message": "hello"})
        assert result.echo == "hello"
        assert result.status == "ok"

    async def test_execute_with_connector(self):
        """Execute a Capability that uses a connector."""
        runtime = MockRuntime()
        runtime.connectors.register(
            "weather",
            MockConnector({"get_forecast": lambda p: f'sunny in {p["city"]}'}),
        )
        runtime.register(WeatherCap)
        result = await runtime.execute("weather_query", {"message": "Beijing"})
        assert "sunny" in result.echo

    async def test_cross_capability_invoke(self):
        """Cross-capability invocation works via ctx.capabilities.invoke."""
        runtime = MockRuntime()
        runtime.register(PingCap)
        runtime.register(OrchestratorCap)
        result = await runtime.execute("orchestrator", {"message": "test"})
        assert "nested:test" in result.echo

    async def test_unregistered_capability_raises(self):
        """Executing an unregistered Capability raises ValueError."""
        runtime = MockRuntime()
        with pytest.raises(ValueError, match="not registered"):
            await runtime.execute("nonexistent", {})

    async def test_set_env_override(self):
        """set_env() scoped to runtime."""
        runtime = MockRuntime()
        runtime.set_env("MY_VAR", "override_value")
        assert runtime.get_env("MY_VAR") == "override_value"

    async def test_set_env_does_not_affect_os(self):
        """set_env does not modify os.environ."""
        import os
        runtime = MockRuntime()
        runtime.set_env("SHOULD_NOT_LEAK", "test")
        assert os.environ.get("SHOULD_NOT_LEAK") is None

    async def test_async_context_manager(self):
        """MockRuntime supports async with."""
        async with MockRuntime() as runtime:
            runtime.register(PingCap)
            result = await runtime.execute("ping", {"message": "ctx"})
            assert result.echo == "ctx"

    async def test_capability_type_preserved(self):
        """Query/Command type is preserved in mock execution."""
        runtime = MockRuntime()
        runtime.register(NoOpCmd)
        # Should execute without error
        result = await runtime.execute("noop_cmd", {"message": "cmd"})
        assert result.echo == "cmd"
