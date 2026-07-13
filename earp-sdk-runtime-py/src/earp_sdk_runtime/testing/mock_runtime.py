"""MockRuntimeClient — local mock of the EARP Runtime for testing."""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from earp_sdk_runtime.models import CapabilityInfo, SearchResponse

Handler = Callable[[dict[str, Any]], dict[str, Any]] | Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class MockRuntimeClient:
    """Simulates the EARP Runtime locally for integration testing.

    No network calls, no real Runtime needed.
    Register mock handlers that return canned responses.

    Usage:
        mock = MockRuntimeClient()
        mock.register("ping", lambda p: {"echo": p["message"]})
        result = await mock.call("ping", {"message": "hello"})
        assert result["echo"] == "hello"
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._capabilities: dict[str, CapabilityInfo] = {}
        self._trace_id: str = ""

    def register(
        self,
        capability_id: str,
        handler: Handler,
        info: CapabilityInfo | None = None,
    ) -> None:
        """Register a mock handler for a Capability.

        Args:
            capability_id: The Capability ID.
            handler: Function receiving params(dict) and returning result(dict).
            info: Optional CapabilityInfo for search/resolve results.
        """
        self._handlers[capability_id] = handler
        if info:
            self._capabilities[capability_id] = info
        else:
            self._capabilities[capability_id] = CapabilityInfo(
                capability_id=capability_id,
                name=capability_id,
                description=f"Mock {capability_id}",
            )

    async def call(
        self,
        capability_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Invoke a mock handler (synchronous shortcut)."""
        return await self.invoke(capability_id, params)

    async def invoke(
        self,
        capability_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Invoke a mock handler.

        Args:
            capability_id: Registered Capability ID.
            params: Input parameters.

        Returns:
            Handler result dict.

        Raises:
            ValueError: If handler is not registered.
        """
        handler = self._handlers.get(capability_id)
        if handler is None:
            raise ValueError(
                f"Capability '{capability_id}' not registered. "
                f"Use mock.register() first. "
                f"Registered: {list(self._handlers.keys())}"
            )
        result = handler(params)
        if hasattr(result, "__await__"):
            result = await result
        return result

    async def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SearchResponse:
        """Search registered Capabilities by keyword."""
        results = [
            info for info in self._capabilities.values()
            if query.lower() in info.name.lower()
            or query.lower() in info.capability_id.lower()
            or query.lower() in info.description.lower()
        ]
        if domain:
            results = [r for r in results if r.domain == domain]
        # Simulate pagination
        total = len(results)
        start = (page - 1) * page_size
        end = start + page_size
        return SearchResponse(
            results=results[start:end],
            page=page,
            page_size=page_size,
            total=total,
        )

    def set_trace_id(self, trace_id: str) -> None:
        """Set the trace ID for the next invoke call (simulates SDKMUST-R-004)."""
        self._trace_id = trace_id

    async def create_session(self, *, user_id: str, **kwargs: Any) -> "MockRuntimeClient":
        """Mock session creation — returns self for method chaining."""
        return self

    async def close(self) -> None:
        """No-op."""
