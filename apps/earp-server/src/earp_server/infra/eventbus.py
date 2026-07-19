"""In-process EventBus — CloudEvents 1.0, fire-and-forget publish via asyncio.create_task.

M6 replaces with RabbitMQ/Redis Streams implementation behind the same interface.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CloudEvent:
    type: str
    source: str
    tenant_id: str
    data: dict[str, Any]
    specversion: str = "1.0"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    datacontenttype: str = "application/json"


Handler = Callable[[CloudEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = {}

    def publish(self, event: CloudEvent) -> None:
        """Fire-and-forget: dispatch to all matching subscribers as background tasks."""
        import fnmatch

        for pattern, handlers in self._subscribers.items():
            if fnmatch.fnmatch(event.type, pattern):
                for handler in handlers:
                    asyncio.create_task(self._safe_invoke(event, handler))

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def _safe_invoke(self, event: CloudEvent, handler: Handler) -> None:
        try:
            await handler(event)
        except Exception:  # noqa: BLE001 — fire-and-forget must not propagate to publish caller
            logger.exception("EventBus handler failed: type=%s source=%s", event.type, event.source)
