"""Redis Streams EventBus — M6: XADD/XREADGROUP with fallback to in-process.

Keeps the M1 EventBus interface unchanged (publish/subscribe).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from earp_server.infra.eventbus import CloudEvent, EventBus

logger = logging.getLogger(__name__)

STREAM_KEY = "earp:events"
GROUP_NAME = "earp-consumers"
CONSUMER_NAME = "earp-audit"


class RedisStreamsEventBus:
    """EventBus backed by Redis Streams with in-process fallback."""

    def __init__(self, host: str = "localhost", port: int = 6380) -> None:
        self._host = host
        self._port = port
        self._redis = None
        self._fallback = EventBus()  # in-process fallback
        self._redis_available = False

    async def _ensure_redis(self) -> bool:
        if self._redis is not None:
            return self._redis_available
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.Redis(host=self._host, port=self._port, socket_connect_timeout=2)
            await self._redis.ping()
            # create consumer group (idempotent via MKSTREAM)
            try:
                await self._redis.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
            except Exception:
                pass  # group already exists
            self._redis_available = True
            logger.info("RedisStreamsEventBus: connected to %s:%d", self._host, self._port)
            return True
        except Exception:
            logger.warning("RedisStreamsEventBus: Redis unavailable, using in-process fallback")
            self._redis = None
            self._redis_available = False
            return False

    def publish(self, event: CloudEvent) -> None:
        """Publish event to Redis Stream (async fire-and-forget). Falls back to in-process."""
        asyncio.create_task(self._publish_async(event))

    async def _publish_async(self, event: CloudEvent) -> None:
        ok = await self._ensure_redis()
        if ok and self._redis:
            try:
                payload = {
                    "type": event.type,
                    "source": event.source,
                    "tenant_id": event.tenant_id,
                    "data": json.dumps(event.data),
                    "time": event.time,
                }
                await self._redis.xadd(STREAM_KEY, payload, maxlen=10000)
            except Exception:
                logger.warning("RedisStreamsEventBus: xadd failed, falling back to in-process")
                self._fallback.publish(event)
        else:
            self._fallback.publish(event)

    def subscribe(self, event_type: str, handler: Callable[[CloudEvent], Awaitable[None]]) -> None:
        self._fallback.subscribe(event_type, handler)

    async def start_consumer(self) -> None:
        """Background consumer: read from Redis Stream, route to fallback subscribers."""
        ok = await self._ensure_redis()
        if not ok or not self._redis:
            logger.warning("RedisStreamsEventBus: consumer skipped (no Redis)")
            return
        while True:
            try:
                messages = await self._redis.xreadgroup(
                    GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"}, count=10, block=1000,
                )
                for _stream, entries in messages:
                    for entry_id, fields in entries:
                        event = CloudEvent(
                            type=fields.get(b"type", b"").decode(),
                            source=fields.get(b"source", b"").decode(),
                            tenant_id=fields.get(b"tenant_id", b"").decode(),
                            data=json.loads(fields.get(b"data", b"{}").decode()),
                        )
                        self._fallback.publish(event)
                        await self._redis.xack(STREAM_KEY, GROUP_NAME, entry_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("RedisStreamsEventBus: consumer error")
                await asyncio.sleep(1)
