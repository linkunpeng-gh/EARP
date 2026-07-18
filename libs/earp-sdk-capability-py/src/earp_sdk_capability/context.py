"""Capability execution context.

Injected into every execute() call. Provides access to connectors,
other capabilities, logging, and session metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from earp_sdk_capability.testing.mock_runtime import CapabilityRegistry
    from earp_sdk_capability.testing.mock_connector import ConnectorRegistry


class CapLogger:
    """Structured logger pre-scoped to a capability_id."""

    def __init__(self, capability_id: str) -> None:
        self._cap_id = capability_id

    def info(self, message: str, **extra: Any) -> None:
        self._log("INFO", message, extra)

    def warn(self, message: str, **extra: Any) -> None:
        self._log("WARN", message, extra)

    def error(self, message: str, **extra: Any) -> None:
        self._log("ERROR", message, extra)

    def _log(self, level: str, message: str, extra: dict[str, Any]) -> None:
        parts = f"[{level}] [{self._cap_id}] {message}"
        if extra:
            parts += f" {extra}"
        print(parts)


@dataclass
class CapabilityContext:
    """Runtime context injected into every execute() call."""

    session_id: str = ""
    request_id: str = ""
    user_id: str | None = None
    tenant_id: str | None = None
    connectors: ConnectorRegistry | None = None
    capabilities: CapabilityRegistry | None = None
    logger: CapLogger | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_tenant(self, tenant_id: str) -> None:
        """Switch tenant context. Aligns with Dify Account.set_tenant_id()."""
        self.tenant_id = tenant_id
