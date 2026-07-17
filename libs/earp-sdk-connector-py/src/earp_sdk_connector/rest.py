import httpx, json as json_lib
from typing import Any
from earp_sdk_core import ConnectorConfig, ConnectorError, ConnectorErrorCode
from earp_sdk_connector.base import BaseConnector
from earp_sdk_connector.models import ConnectorResult

class RESTConnector(BaseConnector):
    endpoints: dict[str, dict] = {}
    health_path: str = "/health"

    def __init__(self, transport: httpx.AsyncClient | None = None):
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._auth_headers: dict[str, str] = {}

    @property
    def base_url(self) -> str:
        return self.config.base_url if self.config else ""

    def set_transport(self, client: httpx.AsyncClient) -> None:
        self._transport = client

    async def test_connection(self) -> dict[str, Any]:
        if not self.base_url:
            return {"status": "failed", "latency_ms": 0, "error": "base_url not configured"}
        import time; start = time.monotonic()
        try:
            client = self._get_client()
            resp = await client.get(f"{self.base_url}{self.health_path}", timeout=self._timeout())
            delta = int((time.monotonic() - start) * 1000)
            return {"status": "ok" if resp.is_success else "failed", "latency_ms": delta, "error": None}
        except Exception as e:
            delta = int((time.monotonic() - start) * 1000)
            return {"status": "failed", "latency_ms": delta, "error": str(e)}

    async def execute(self, operation: str, params: dict[str, Any]) -> ConnectorResult:
        endpoint = self._get_endpoint(operation)
        required = endpoint.get("required_params", [])
        missing = [p for p in required if p not in params]
        if missing:
            return ConnectorResult(status="error", error=f"Missing required params: {missing}")
        method = endpoint["method"]
        path = endpoint["path"]
        query_params = endpoint.get("query_params", [])
        body_type = endpoint.get("body_type")
        query = {k: str(params[k]) for k in query_params if k in params}
        url = self.base_url + path
        self._ensure_auth_headers()
        try:
            client = self._get_client()
            if method == "GET":
                resp = await client.get(url, params=query, headers=self._auth_headers, timeout=self._timeout())
            elif method == "POST":
                body = self._build_body(params, endpoint, body_type)
                resp = await client.post(url, json=body, params=query, headers=self._auth_headers, timeout=self._timeout())
            elif method == "PATCH":
                body = self._build_body(params, endpoint, body_type)
                resp = await client.patch(url, json=body, params=query, headers=self._auth_headers, timeout=self._timeout())
            elif method == "DELETE":
                resp = await client.delete(url, params=query, headers=self._auth_headers, timeout=self._timeout())
            else:
                return ConnectorResult(status="error", error=f"Unsupported method: {method}")
            if resp.is_success:
                try: data = resp.json()
                except Exception: data = resp.text
                return ConnectorResult(status="ok", data=data)
            else:
                raise self._map_error(resp)
        except ConnectorError:
            raise
        except httpx.TimeoutException:
            raise ConnectorError(ConnectorErrorCode.TIMEOUT, "Request timed out")
        except httpx.ConnectError:
            raise ConnectorError(ConnectorErrorCode.CONNECTION_FAILED, "Connection failed")
        except Exception as e:
            raise ConnectorError(ConnectorErrorCode.SYSTEM_ERROR, str(e))

    async def health_check(self) -> str:
        try:
            result = await self.test_connection()
            return "healthy" if result["status"] == "ok" else "degraded"
        except Exception:
            return "unreachable"

    async def __aenter__(self):
        self._client = httpx.AsyncClient(); return self
    async def __aexit__(self, *args):
        await self.close()

    def _get_client(self) -> httpx.AsyncClient:
        if self._transport: return self._transport
        if self._client is None: self._client = httpx.AsyncClient()
        return self._client

    def _timeout(self) -> float:
        return self.config.timeout_ms / 1000.0 if self.config else 5.0

    def _get_endpoint(self, operation: str) -> dict:
        ep = self.endpoints.get(operation)
        if ep is None:
            raise ConnectorError(ConnectorErrorCode.OPERATION_NOT_FOUND,
                f"Operation '{operation}' not defined. Valid: {list(self.endpoints.keys())}")
        return ep

    def _ensure_auth_headers(self) -> None:
        if not self._auth_headers:
            if self.config and self.config.auth.token:
                if self.config.auth.type == "bearer":
                    self._auth_headers["Authorization"] = f"Bearer {self.config.auth.token}"
                elif self.config.auth.type == "basic":
                    import base64
                    creds = base64.b64encode(f"{self.config.auth.username}:{self.config.auth.password}".encode()).decode()
                    self._auth_headers["Authorization"] = f"Basic {creds}"
        # Tenant header: always refresh (may change at runtime, not cached)
        if self.tenant_id:
            self._auth_headers["X-EARP-Tenant-Id"] = self.tenant_id

    @staticmethod
    def _build_body(params: dict, endpoint: dict, body_type: str | None) -> Any:
        body_fields = endpoint.get("body_fields")
        if body_fields: return {k: params[k] for k in body_fields if k in params}
        return params if body_type == "json" else None

    @staticmethod
    def _map_error(response: httpx.Response) -> ConnectorError:
        status = response.status_code
        if status == 429: return ConnectorError(ConnectorErrorCode.RATE_LIMITED, "Rate limited", retry_after=60)
        if status == 401: return ConnectorError(ConnectorErrorCode.AUTH_EXPIRED, "Authentication expired")
        if status == 403: return ConnectorError(ConnectorErrorCode.SYSTEM_ERROR, "Permission denied (403)")
        if 500 <= status < 600: return ConnectorError(ConnectorErrorCode.SYSTEM_ERROR, f"Server error: {status}")
        return ConnectorError(ConnectorErrorCode.INVALID_RESPONSE, f"HTTP {status}")

    async def close(self) -> None:
        if self._client: await self._client.aclose(); self._client = None
