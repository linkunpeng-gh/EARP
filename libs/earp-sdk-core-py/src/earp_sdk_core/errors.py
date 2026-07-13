"""EARP SDK shared error types.

All EARP SDK packages (capability, runtime, connector, plugin) share
these error codes and exception types.

ConnectorError codes align with L2-03 §C.6 (6 codes).
CapabilityError codes align with L2-03 §8.4.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


# ── Connector Errors (L2-03 §C.6) ──


class ConnectorErrorCode(StrEnum):
    """Connector error codes — aligns with L2-03 §C.6 (6 codes)."""

    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SYSTEM_ERROR = "SYSTEM_ERROR"


CONNECTOR_RETRYABLE: dict[ConnectorErrorCode, bool] = {
    ConnectorErrorCode.CONNECTION_FAILED: True,
    ConnectorErrorCode.TIMEOUT: True,
    ConnectorErrorCode.RATE_LIMITED: True,
    ConnectorErrorCode.AUTH_EXPIRED: False,
    ConnectorErrorCode.INVALID_RESPONSE: False,
    ConnectorErrorCode.SYSTEM_ERROR: True,
}


class ConnectorError(Exception):
    """Raised when a Connector operation fails.

    Attributes:
        code: One of the 6 ConnectorErrorCode values.
        message: Human-readable description.
        retryable: Whether the caller should retry.
        retry_after: Seconds to wait before retry (RATE_LIMITED only).
        cause: Original exception, if any.
    """

    def __init__(
        self,
        code: str | ConnectorErrorCode,
        message: str = "",
        *,
        retryable: bool | None = None,
        retry_after: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.code = ConnectorErrorCode(code) if isinstance(code, str) else code
        self.message = message or self._default_message()
        if retryable is not None:
            self._retryable = retryable
        else:
            self._retryable = CONNECTOR_RETRYABLE.get(self.code, False)
        self.retry_after = retry_after
        self.cause = cause
        super().__init__(str(self))

    @property
    def retryable(self) -> bool:
        return self._retryable

    def _default_message(self) -> str:
        return {
            ConnectorErrorCode.CONNECTION_FAILED: "Connection to external system failed",
            ConnectorErrorCode.TIMEOUT: "Connector operation timed out",
            ConnectorErrorCode.RATE_LIMITED: "Rate limit exceeded for external system",
            ConnectorErrorCode.AUTH_EXPIRED: "Authentication credentials expired",
            ConnectorErrorCode.INVALID_RESPONSE: "Invalid response from external system",
            ConnectorErrorCode.SYSTEM_ERROR: "Connector internal system error",
        }.get(self.code, "Unknown connector error")

    def __str__(self) -> str:
        base = f"[{self.code.value}] {self.message}"
        if self.retry_after is not None:
            base += f" (retry after {self.retry_after}s)"
        return base


# ── Capability Errors (L2-03 §8.4) ──


class CapabilityErrorCode(StrEnum):
    """Capability error codes — aligns with L2-03 §8.4."""

    CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CONNECTOR_ERROR = "CONNECTOR_ERROR"
    BUSINESS_ERROR = "BUSINESS_ERROR"
    TIMEOUT = "TIMEOUT"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class CapabilityError(Exception):
    """Raised when a Capability execution fails.

    Attributes:
        code: One of the CapabilityErrorCode values.
        message: Human-readable description.
        details: Structured error details (e.g., schema validation failures).
        cause: Original exception, if any.
    """

    def __init__(
        self,
        code: str | CapabilityErrorCode,
        message: str = "",
        *,
        details: list[dict[str, Any]] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.code = CapabilityErrorCode(code) if isinstance(code, str) else code
        self.message = message
        self.details = details or []
        self.cause = cause
        super().__init__(str(self))

    def __str__(self) -> str:
        base = f"[{self.code.value}]"
        if self.message:
            base += f" {self.message}"
        if self.cause:
            base += f" (caused by: {self.cause})"
        return base


# ── Runtime SDK Error subclasses ──


class CapabilityNotFoundError(CapabilityError):
    """Capability ID not found. Not retryable.

    Maps to HTTP 404 and CapabilityErrorCode.CAPABILITY_NOT_FOUND.
    """

    def __init__(self, capability_id: str = "", message: str = ""):
        msg = message or f"Capability '{capability_id}' not found"
        super().__init__(CapabilityErrorCode.CAPABILITY_NOT_FOUND, msg)


class PermissionDeniedError(CapabilityError):
    """User lacks permission. Not retryable.

    Maps to HTTP 403 and CapabilityErrorCode.PERMISSION_DENIED.
    """

    def __init__(self, capability_id: str = "", message: str = ""):
        msg = message or f"Permission denied for capability '{capability_id}'"
        super().__init__(CapabilityErrorCode.PERMISSION_DENIED, msg)


class RateLimitExceededError(CapabilityError):
    """Rate limit exceeded. Retryable after waiting.

    Maps to HTTP 429 and CapabilityErrorCode.RATE_LIMIT_EXCEEDED.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: int | None = None,
    ):
        super().__init__(CapabilityErrorCode.RATE_LIMIT_EXCEEDED, message)
        self.retry_after = retry_after
