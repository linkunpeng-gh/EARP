from __future__ import annotations
from enum import StrEnum
from typing import Any

class ConnectorErrorCode(StrEnum):
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SYSTEM_ERROR = "SYSTEM_ERROR"

CONNECTOR_RETRYABLE = {
    ConnectorErrorCode.CONNECTION_FAILED: True,
    ConnectorErrorCode.TIMEOUT: True,
    ConnectorErrorCode.RATE_LIMITED: True,
    ConnectorErrorCode.AUTH_EXPIRED: False,
    ConnectorErrorCode.INVALID_RESPONSE: False,
    ConnectorErrorCode.SYSTEM_ERROR: True,
}

class ConnectorError(Exception):
    def __init__(self, code, message="", *, retryable=None, retry_after=None, cause=None):
        self.code = ConnectorErrorCode(code) if isinstance(code, str) else code
        self.message = message or self._default_message()
        self._retryable = retryable if retryable is not None else CONNECTOR_RETRYABLE.get(self.code, False)
        self.retry_after = retry_after; self.cause = cause
        super().__init__(str(self))

    @property
    def retryable(self): return self._retryable

    def _default_message(self):
        return {ConnectorErrorCode.CONNECTION_FAILED: "Connection failed",
                ConnectorErrorCode.TIMEOUT: "Timeout", ConnectorErrorCode.RATE_LIMITED: "Rate limited",
                ConnectorErrorCode.AUTH_EXPIRED: "Auth expired", ConnectorErrorCode.INVALID_RESPONSE: "Invalid response",
                ConnectorErrorCode.SYSTEM_ERROR: "System error"}.get(self.code, "Unknown")

    def __str__(self):
        b = f"[{self.code.value}] {self.message}"; return b if self.retry_after is None else f"{b} (retry after {self.retry_after}s)"

class CapabilityErrorCode(StrEnum):
    CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CONNECTOR_ERROR = "CONNECTOR_ERROR"
    BUSINESS_ERROR = "BUSINESS_ERROR"
    TIMEOUT = "TIMEOUT"
    SYSTEM_ERROR = "SYSTEM_ERROR"

class CapabilityError(Exception):
    def __init__(self, code, message="", *, details=None, cause=None):
        self.code = CapabilityErrorCode(code) if isinstance(code, str) else code
        self.message = message; self.details = details or []; self.cause = cause
        super().__init__(str(self))
    def __str__(self):
        b = f"[{self.code.value}]"
        if self.message: b += f" {self.message}"
        if self.cause: b += f" (caused by: {self.cause})"
        return b

class CapabilityNotFoundError(CapabilityError):
    def __init__(self, capability_id="", message=""):
        super().__init__(CapabilityErrorCode.CAPABILITY_NOT_FOUND, message or f"Capability '{capability_id}' not found")

class PermissionDeniedError(CapabilityError):
    def __init__(self, capability_id="", message=""):
        super().__init__(CapabilityErrorCode.PERMISSION_DENIED, message or f"Permission denied for '{capability_id}'")

class RateLimitExceededError(CapabilityError):
    def __init__(self, message="Rate limit exceeded", *, retry_after=None):
        super().__init__(CapabilityErrorCode.RATE_LIMIT_EXCEEDED, message)
        self.retry_after = retry_after
