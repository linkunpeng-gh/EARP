"""Capability base classes.

Defines the abstract base classes for all EARP Capabilities:
- Capability[InputT, OutputT] — generic base
- QueryCapability[InputT, OutputT] — read-only capabilities
- CommandCapability[InputT, OutputT] — state-changing capabilities with compensation
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class Capability(ABC, Generic[InputT, OutputT]):
    """Base class for all EARP Capabilities.

    Subclass QueryCapability or CommandCapability instead of this directly.
    """

    # ── Required fields (MUST be set by developer) ──
    capability_id: str = ""
    name: str = ""
    description: str = ""
    domain: str = ""
    capability_type: str = ""  # "query" | "command"

    # ── Optional fields ──
    version: str = "0.1.0"
    tags: list[str] = []

    @abstractmethod
    async def execute(self, ctx: "CapabilityContext", params: InputT) -> OutputT:
        """Execute the capability business logic."""
        ...

    # ── Lifecycle hooks (optional) ──
    async def on_register(self) -> None:
        """Called before registration."""

    async def on_activate(self) -> None:
        """Called when the capability transitions to active."""


class QueryCapability(Capability[InputT, OutputT]):
    """Read-only capability. No side effects. Idempotent by nature."""

    capability_type = "query"


class CommandCapability(Capability[InputT, OutputT]):
    """State-changing capability. Can participate in Saga rollback."""

    capability_type = "command"

    async def compensate(
        self,
        ctx: "CapabilityContext",
        params: InputT,
        result: OutputT,
    ) -> None:
        """Compensation logic for Saga rollback.

        Default is a no-op. Override to implement compensation.
        The packager sets supports_compensation=True only when overridden.
        """
