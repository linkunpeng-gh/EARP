import asyncio, logging
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any
from earp_sdk_core import ConnectorConfig, ConnectorError, ConnectorErrorCode
from earp_sdk_connector.models import ConnectorResult, ConnectorCapability

logger = logging.getLogger(__name__)

class ConnectorStatus(StrEnum):
    REGISTERED = "registered"
    CONNECTED = "connected"
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    ERROR = "error"

class BaseConnector(ABC):
    connector_id: str = ""
    name: str = ""
    protocol: str = ""
    version: str = "0.1.0"
    status: ConnectorStatus = ConnectorStatus.REGISTERED
    config: ConnectorConfig | None = None

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]: ...
    @abstractmethod
    async def execute(self, operation: str, params: dict[str, Any]) -> ConnectorResult: ...
    @abstractmethod
    async def health_check(self) -> str: ...

    def get_capabilities(self) -> list[ConnectorCapability]:
        return []

    async def connect(self) -> ConnectorStatus:
        try:
            result = await self.test_connection()
            if result.get("status") == "ok":
                self.status = ConnectorStatus.ACTIVE
                await self._on_connect()
            else:
                self.status = ConnectorStatus.ERROR
                await self._on_error(RuntimeError(result.get("error", "unknown")))
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            await self._on_error(e)
            raise
        return self.status

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        await self._on_disconnect()

    async def _retry_connect(self, max_attempts: int = 3) -> bool:
        for attempt in range(max_attempts):
            if self.status == ConnectorStatus.ACTIVE:
                return True
            try:
                await self.connect()
                return True
            except Exception:
                if attempt == max_attempts - 1:
                    return False
                await asyncio.sleep(2 ** attempt)
        return False

    async def _on_connect(self) -> None: pass
    async def _on_disconnect(self) -> None: pass

    async def _on_error(self, error: Exception) -> None:
        if isinstance(error, ConnectorError):
            ce = error
            if ce.code in (ConnectorErrorCode.AUTH_EXPIRED, ConnectorErrorCode.INVALID_RESPONSE):
                logger.error("Non-retryable connector error [%s]: %s (connector=%s)",
                              ce.code.value, ce.message, self.connector_id)
        else:
            logger.error("Connector error: %s (connector=%s)", error, self.connector_id)
