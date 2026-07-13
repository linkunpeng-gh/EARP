"""EventSubscriber — subscribe to EventBus events via SSE."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from earp_sdk_runtime.models import RuntimeEvent


class EventSubscriber:
    """Subscribe to and publish EventBus events.

    Uses SSE (Server-Sent Events) protocol.
    Auto-reconnects on disconnect (exponential backoff, max 5 retries).
    """

    def __init__(
        self,
        session_id: str,
        client: httpx.AsyncClient,
        endpoint: str,
    ) -> None:
        self._session_id = session_id
        self._client = client
        self._endpoint = endpoint

    async def subscribe(
        self,
        event_types: list[str] | None = None,
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Subscribe to a stream of EventBus events.

        Args:
            event_types: Filter by event type (e.g. ["alarm.critical"]).
                         None = all events.
            session_id: Optional, scope to a specific Session.

        Yields:
            RuntimeEvent objects as they arrive.

        Cancel:
            Use `break` inside the async for loop, or
            call .aclose() on the returned async iterator.
        """
        params: dict[str, Any] = {}
        if event_types:
            params["event_types"] = ",".join(event_types)
        if session_id:
            params["session_id"] = session_id

        retries = 0
        max_retries = 5

        while retries <= max_retries:
            try:
                async with self._client.stream(
                    "GET",
                    f"{self._endpoint}/v1/events/subscribe",
                    params=params,
                    timeout=None,
                ) as response:
                    retries = 0  # Reset on successful connection
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            payload = json.loads(line[6:])
                            yield RuntimeEvent(
                                event_id=payload.get("event_id", ""),
                                event_type=payload.get("event_type", ""),
                                source=payload.get("source", ""),
                                data=payload.get("data", {}),
                                timestamp=payload.get("timestamp", ""),
                                session_id=payload.get("session_id"),
                            )
            except (httpx.TransportError, httpx.ConnectError) as e:
                retries += 1
                if retries > max_retries:
                    raise  # Give up
                import asyncio
                delay = min(2 ** retries, 30)
                await asyncio.sleep(delay)

    async def publish(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        source: str = "sdk",
    ) -> None:
        """Publish an event to the EventBus."""
        response = await self._client.post(
            f"{self._endpoint}/v1/events",
            json={
                "event_type": event_type,
                "source": source,
                "data": data,
            },
            timeout=30,
        )
        response.raise_for_status()
