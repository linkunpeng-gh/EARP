"""Decorators for defining Capabilities.

@capability — class decorator for Capability subclasses (recommended API).
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from earp_sdk_capability.base import Capability

T = TypeVar("T", bound=type[Capability])


def capability(
    *,
    capability_id: str = "",
    name: str = "",
    description: str = "",
    domain: str = "",
    version: str = "0.1.0",
    tags: list[str] | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """Class decorator that sets Capability metadata fields.

    Usage:

        @capability(
            capability_id="query_equipment_alarm",
            name="查询设备报警",
            domain="equipment",
        )
        class MyCap(QueryCapability[...]):
            async def execute(self, ctx, params):
                ...
    """
    tags = tags or []

    def decorator(cls: T) -> T:
        for key, value in [
            ("capability_id", capability_id),
            ("name", name),
            ("description", description),
            ("domain", domain),
            ("version", version),
            ("tags", tags),
        ]:
            if value:
                setattr(cls, key, value)
        for key, value in kwargs.items():
            setattr(cls, key, value)
        return cls

    return decorator
