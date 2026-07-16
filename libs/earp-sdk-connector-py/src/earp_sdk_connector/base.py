import asyncio, logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from earp_sdk_core import ConnectorConfig, ConnectorError, ConnectorErrorCode
from earp_sdk_connector.models import ConnectorResult, ConnectorCapability

logger = logging.getLogger(__name__)


class ConnectorStatus(str, Enum):
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
    tenant_id: str = ""

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
            except ConnectorError as ce:
                if not ce.retryable:
                    return False
            except Exception:
                pass
            if attempt < max_attempts - 1:
                await asyncio.sleep(2 ** attempt)
        return False

    async def _on_connect(self) -> None: pass
    async def _on_disconnect(self) -> None: pass

    async def _on_error(self, error: Exception) -> None:
        if isinstance(error, ConnectorError):
            ce = error
            if ce.code in (ConnectorErrorCode.AUTH_EXPIRED, ConnectorErrorCode.INVALID_RESPONSE):
                logger.error("Non-retryable error [%s]: %s (connector=%s)",
                             ce.code.value, ce.message, self.connector_id)
            # AC-05: Structured audit log for AUTH_EXPIRED
            if ce.code == ConnectorErrorCode.AUTH_EXPIRED:
                # Phase 2: publish audit event via standardized channel
                try:
                    from earp_sdk_core import AuditEvent, publish_audit_event
                    publish_audit_event(AuditEvent(
                        source="security",
                        event_type="AUTH_EXPIRED",
                        tenant_id=self.tenant_id,
                        user_id="",
                        action="connector_auth",
                        result="failure",
                        subject=f"connector:{self.connector_id}" if self.connector_id else None,
                        detail={"connector_id": self.connector_id, "reason": str(ce)},
                    ))
                except Exception:
                    pass  # audit failure must not break error handling
                # Phase 1 fallback: local critical log
                record = logger.makeRecord(
                    logger.name, logging.CRITICAL, __file__, 109,
                    "Security audit: AUTH_EXPIRED", (), None,
                )
                record.audit_type = "AUTH_EXPIRED"
                record.connector_id = self.connector_id
                record.timestamp = datetime.now(timezone.utc).isoformat()
                logger.handle(record)
        else:
            logger.error("Connector error (connector=%s): %s", self.connector_id, error)
