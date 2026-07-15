from typing import Any
class ConnectorTestHarness:
    def __init__(self):
        self._responses: dict[str, Any] = {}
        self._errors: dict[str, Exception] = {}
    def register_response(self, operation: str, data: Any) -> None:
        self._responses[operation] = data
    def register_error(self, operation: str, error: Exception) -> None:
        self._errors[operation] = error
    def get_response(self, operation: str) -> Any:
        if operation in self._errors: raise self._errors[operation]
        if operation not in self._responses:
            raise KeyError(f"Operation '{operation}' not registered. Registered: {list(self._responses.keys())}")
        return self._responses[operation]
    def as_transport(self):
        import httpx
        harness = self
        def handler(request):
            return httpx.Response(200, json=harness._responses.get("default", {}))
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))
