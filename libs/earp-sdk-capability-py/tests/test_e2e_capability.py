"""End-to-end test: a real Capability through the full SDK workflow.

Tests the complete developer experience:
    1. Define a Capability with @capability decorator
    2. Register connectors in MockRuntime
    3. Execute with MockRuntime (happy path + error path)
    4. Package into three-layer structure via Packager
    5. Cross-capability invocation
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from earp_sdk_capability import capability, QueryCapability, CommandCapability, CapabilityError
from earp_sdk_capability.registration.packager import packager
from earp_sdk_capability.testing.mock_runtime import MockRuntime
from earp_sdk_capability.testing.mock_connector import MockConnector


# ── 1. Define a Capability ──


class EchoInput(BaseModel):
    message: str


class EchoOutput(BaseModel):
    echo: str


@capability(
    capability_id="echo",
    name="Echo",
    description="A simple echo capability for end-to-end testing",
    domain="test",
    version="1.0.0",
    tags=["test"],
)
class EchoCap(QueryCapability[EchoInput, EchoOutput]):
    async def execute(self, ctx, params: EchoInput) -> EchoOutput:
        ctx.logger.info(f"Echoing: {params.message}")
        return EchoOutput(echo=params.message)


# ── 2. A Capability that uses a Connector ──


class WeatherInput(BaseModel):
    city: str


class WeatherOutput(BaseModel):
    forecast: str


@capability(
    capability_id="weather",
    name="Weather Query",
    description="Get weather forecast via connector",
    domain="weather",
    version="1.0.0",
)
class WeatherCap(QueryCapability[WeatherInput, WeatherOutput]):
    async def execute(self, ctx, params: WeatherInput) -> WeatherOutput:
        result = await ctx.connectors.weather.execute(
            "get_forecast",
            {"city": params.city},
        )
        return WeatherOutput(forecast=result["forecast"])


# ── 3. A Command Capability with compensation ──


class OrderInput(BaseModel):
    item: str
    quantity: int


class OrderOutput(BaseModel):
    order_id: str
    total: float


@capability(
    capability_id="place_order",
    name="Place Order",
    description="Place an order with compensation support",
    domain="ordering",
    version="1.0.0",
)
class PlaceOrderCap(CommandCapability[OrderInput, OrderOutput]):
    async def execute(self, ctx, params: OrderInput) -> OrderOutput:
        result = await ctx.connectors.order.execute("reserve", {
            "item": params.item,
            "qty": params.quantity,
        })
        return OrderOutput(order_id=result["order_id"], total=result["total"])

    async def compensate(self, ctx, params: OrderInput, result: OrderOutput) -> None:
        await ctx.connectors.order.execute("cancel", {"order_id": result.order_id})


# ── 4. A Capability that invokes another capability ──


@capability(
    capability_id="weather_reporter",
    name="Weather Reporter",
    description="Gets weather and formats a report using another capability",
    domain="weather",
    version="1.0.0",
)
class WeatherReporterCap(QueryCapability[WeatherInput, EchoOutput]):
    async def execute(self, ctx, params: WeatherInput) -> EchoOutput:
        # Cross-capability call
        weather = await ctx.capabilities.invoke("weather", {"city": params.city})
        return EchoOutput(echo=f"Weather in {params.city}: {weather['forecast']}")


# ── Tests ──


class TestE2ECapability:
    """End-to-end Capability development workflow."""

    async def test_basic_execution(self):
        """A simple Capability executes correctly via MockRuntime."""
        runtime = MockRuntime()
        runtime.register(EchoCap)
        result = await runtime.execute("echo", {"message": "hello earp"})
        assert result.echo == "hello earp"

    async def test_with_connector(self):
        """Capability using a connector returns correct data."""
        runtime = MockRuntime()
        runtime.connectors.register(
            "weather",
            MockConnector({
                "get_forecast": lambda p: {"forecast": f"Sunny in {p['city']}"},
            }),
        )
        runtime.register(WeatherCap)
        result = await runtime.execute("weather", {"city": "Beijing"})
        assert "Sunny" in result.forecast
        assert "Beijing" in result.forecast

    async def test_connector_error(self):
        """Connector failures are wrapped as CapabilityError in MockRuntime."""
        runtime = MockRuntime()
        runtime.connectors.register(
            "weather",
            MockConnector({}),  # No handlers registered
        )
        runtime.register(WeatherCap)
        with pytest.raises(CapabilityError) as exc_info:
            await runtime.execute("weather", {"city": "Beijing"})
        # The original ConnectorError should be preserved as the cause
        assert exc_info.value.cause is not None
        assert "not registered" in str(exc_info.value.cause)

    async def test_command_compensation(self):
        """Command capability with compensation works."""
        runtime = MockRuntime()
        runtime.connectors.register(
            "order",
            MockConnector({
                "reserve": lambda p: {"order_id": "ORD-001", "total": 99.99},
                "cancel": lambda p: {"ok": True},
            }),
        )
        runtime.register(PlaceOrderCap)
        result = await runtime.execute("place_order", {"item": "widget", "quantity": 5})
        assert result.order_id == "ORD-001"
        assert result.total == 99.99

    async def test_cross_capability_invoke(self):
        """Cross-capability invoke works end-to-end."""
        runtime = MockRuntime()
        runtime.connectors.register(
            "weather",
            MockConnector({
                "get_forecast": lambda p: {"forecast": f"Cloudy in {p['city']}"},
            }),
        )
        runtime.register(WeatherCap)
        runtime.register(WeatherReporterCap)

        result = await runtime.execute("weather_reporter", {"city": "Shanghai"})
        assert "Shanghai" in result.echo
        assert "Cloudy" in result.echo

    async def test_packager_output(self):
        """Packager produces valid L2-03 three-layer structure."""
        package = packager.pack(EchoCap)
        assert package["definition"]["capability_id"] == "echo"
        assert package["definition"]["capability_type"] == "query"
        assert package["execution_contract"]["idempotent"] is True
        assert package["policy"]["auth_required"] is True

    async def test_async_context_manager(self):
        """MockRuntime context manager works."""
        async with MockRuntime() as runtime:
            runtime.register(EchoCap)
            result = await runtime.execute("echo", {"message": "context test"})
            assert result.echo == "context test"

    async def test_empty_result(self):
        """Capability returning empty/zero data works."""
        @capability(
            capability_id="empty_ping",
            name="Empty Ping",
            description="Returns empty data",
            domain="test",
        )
        class EmptyPing(QueryCapability[EchoInput, EchoOutput]):
            async def execute(self, ctx, params):
                return EchoOutput(echo="")

        runtime = MockRuntime()
        runtime.register(EmptyPing)
        result = await runtime.execute("empty_ping", {"message": "anything"})
        assert result.echo == ""
