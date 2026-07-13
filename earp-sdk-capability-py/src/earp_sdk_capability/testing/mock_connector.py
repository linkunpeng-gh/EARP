"""MockConnector — simulates external system connections for local testing.

Developers register mock handlers that return canned data,
allowing Capabilities to be tested without real external systems.

Example:

    runtime = MockRuntime()
    runtime.connectors.register("mes", MockConnector({
        "query_alarms": lambda params: {"alarms": []},
    }))
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from earp_sdk_core import ConnectorError, ConnectorErrorCode

Handler = Callable[..., Any] | Callable[..., Coroutine[Any, Any, Any]]


class MockConnector:
    """A fake connector that returns canned responses.

    Args:
        handlers: A dict mapping operation names to handler functions.
                  Handlers can be sync or async.
    """

    def __init__(self, handlers: dict[str, Handler] | None = None) -> None:
        self._handlers: dict[str, Handler] = {}
        if handlers:
            for name, handler in handlers.items():
                self.register(name, handler)

    def register(self, operation: str, handler: Handler) -> None:
        """Register a handler for a specific operation."""
        self._handlers[operation] = handler

    async def execute(self, operation: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a mocked operation.

        Args:
            operation: Operation name.
            params: Parameters passed to the handler.

        Returns:
            Whatever the handler returns.

        Raises:
            ConnectorError: If the operation is not registered.
        """
        handler = self._handlers.get(operation)
        if handler is None:
            raise ConnectorError(
                ConnectorErrorCode.INVALID_RESPONSE,
                f"Operation '{operation}' not registered in MockConnector. "
                f"Registered: {list(self._handlers.keys())}",
            )
        params = params or {}
        result = handler(params)
        if asyncio.iscoroutine(result):
            result = await result
        return result


class ConnectorRegistry:
    """Holds all registered mock connectors for a MockRuntime session."""

    def __init__(self) -> None:
        self._connectors: dict[str, MockConnector] = {}

    def register(self, name: str, connector: MockConnector) -> None:
        """Register a connector by name."""
        self._connectors[name] = connector

    def __getattr__(self, name: str) -> MockConnector:
        """Allow dot-access: runtime.connectors.mes.execute(...)"""
        if name in self._connectors:
            return self._connectors[name]
        raise AttributeError(
            f"Connector '{name}' not registered. "
            f"Registered: {list(self._connectors.keys())}"
        )
