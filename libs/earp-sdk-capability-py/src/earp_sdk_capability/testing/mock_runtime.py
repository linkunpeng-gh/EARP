"""MockRuntime — execute Capabilities locally without any external services.

The primary developer testing tool. No network calls, no Policy Center,
no Resolution Engine — just direct class instantiation and method calls.

Usage:

    runtime = MockRuntime()
    runtime.connectors.register("mes", MockConnector({...}))
    runtime.register(QueryEquipmentAlarm)
    result = await runtime.execute("query_equipment_alarm", params)
"""

from __future__ import annotations

import os
from typing import Any, Callable

from pydantic import BaseModel

from earp_sdk_capability.base import Capability
from earp_sdk_capability.context import CapabilityContext, CapLogger
from earp_sdk_capability.testing.mock_connector import ConnectorRegistry
from earp_sdk_core import CapabilityError, CapabilityErrorCode


class CapabilityRegistry:
    """Internal registry for mock capabilities.

    Supports dot-access via ctx.capabilities and invoke() for cross-capability calls.
    """

    def __init__(self) -> None:
        self._caps: dict[str, type[Capability]] = {}
        self._context_factory: Callable[[], CapabilityContext] | None = None

    def register(self, cap_cls: type[Capability], context_factory: Callable[[], CapabilityContext] | None = None) -> None:
        self._caps[cap_cls.capability_id] = cap_cls
        if context_factory:
            self._context_factory = context_factory

    async def invoke(self, capability_id: str, params: dict[str, Any]) -> Any:
        """Invoke another capability within the mock runtime.

        Simplified dispatch (no Resolution Engine, no Policy check).
        This is a KNOWN LIMITATION — see PRD-2026-001 US-04.
        """
        if capability_id not in self._caps:
            raise ValueError(
                f"Capability '{capability_id}' not registered in MockRuntime. "
                f"Registered: {list(self._caps.keys())}"
            )

        cap_cls = self._caps[capability_id]
        cap_instance = cap_cls()

        ctx = self._context_factory() if self._context_factory else CapabilityContext(
            connectors=ConnectorRegistry(),
            capabilities=self,
            logger=CapLogger(capability_id),
        )

        input_type = self._resolve_input_type(cap_cls)
        if input_type and isinstance(params, dict):
            parsed = input_type(**params)
        else:
            parsed = params

        try:
            result = await cap_instance.execute(ctx, parsed)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(
                CapabilityErrorCode.SYSTEM_ERROR,
                f"Unhandled exception in invoke('{capability_id}')",
                cause=e,
            ) from e

        if isinstance(result, BaseModel):
            return result.model_dump()
        return result

    @staticmethod
    def _resolve_input_type(cap_cls: type[Capability]) -> type[BaseModel] | None:
        from earp_sdk_capability.registration.packager import packager
        input_model, _ = packager._resolve_io_types(cap_cls)
        return input_model

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"Capability '{name}' not registered")


class MockRuntime:
    """Local development runtime for testing Capabilities.

    Features:
        - Register Capability classes and Connector mocks
        - Execute Capabilities locally (no external dependencies)
        - ctx.capabilities.invoke() for cross-capability calls
        - set_env() for overriding config variables in tests
        - Context manager support (async with)
    """

    def __init__(self) -> None:
        self.connectors = ConnectorRegistry()
        self._capability_registry = CapabilityRegistry()
        self._env_overrides: dict[str, str] = {}
        self._session_id: str = "mock-session"

    # ── Capability management ──

    def register(self, cap_cls: type[Capability]) -> None:
        """Register a Capability class for testing."""
        self._capability_registry.register(cap_cls, context_factory=self._build_context)

    async def execute(
        self,
        capability_id: str,
        params: Any,
    ) -> Any:
        """Execute a registered Capability with the given params.

        Unhandled exceptions from the capability are wrapped as CapabilityError
        to match the production Runtime behavior (PRD US-02 / AC-14).
        """
        if capability_id not in self._capability_registry._caps:
            raise ValueError(
                f"Capability '{capability_id}' not registered. "
                f"Use runtime.register() first."
            )

        cap_cls = self._capability_registry._caps[capability_id]
        cap_instance = cap_cls()
        ctx = self._build_context()

        input_type = CapabilityRegistry._resolve_input_type(cap_cls)
        if input_type and isinstance(params, dict):
            parsed_params = input_type(**params)
        else:
            parsed_params = params

        try:
            return await cap_instance.execute(ctx, parsed_params)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(
                CapabilityErrorCode.SYSTEM_ERROR,
                f"Unhandled exception in capability '{capability_id}'",
                cause=e,
            ) from e

    # ── Context building ──

    def _build_context(self) -> CapabilityContext:
        return CapabilityContext(
            session_id=self._session_id,
            request_id=f"mock-req-{id(self)}",
            connectors=self.connectors,
            capabilities=self._capability_registry,
            logger=CapLogger("mock"),
        )

    # ── Environment variable overrides (for testing) ──

    def set_env(self, key: str, value: str) -> None:
        """Set a configuration variable override.

        Overrides are scoped to this MockRuntime instance.
        Use during test setup instead of modifying os.environ.
        """
        self._env_overrides[key] = value

    def get_env(self, key: str, default: str | None = None) -> str | None:
        """Get an environment variable, checking overrides first."""
        if key in self._env_overrides:
            return self._env_overrides[key]
        return os.environ.get(key, default)

    # ── Context manager ──

    async def __aenter__(self) -> "MockRuntime":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass
