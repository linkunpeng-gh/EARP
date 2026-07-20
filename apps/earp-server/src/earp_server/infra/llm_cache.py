"""LLM response cache — Redis-backed with in-memory fallback.

Key: SHA256(model || prompt), value: JSON response, TTL: configurable.
Redis unavailable → in-memory dict (no expiry, per-process lifetime).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "earp:llm:cache:"


class LLMCache:
    """Dual-stack LLM response cache."""

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6380, ttl: int = 3600) -> None:
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._ttl = ttl
        self._redis: Any = None  # aioredis client or None
        self._mem: dict[str, tuple[float, str]] = {}  # fallback: {key: (expiry_ts, value)}

    async def _ensure_redis(self) -> bool:
        if self._redis is not None:
            return True
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.Redis(
                host=self._redis_host, port=self._redis_port, socket_connect_timeout=2,
            )
            await self._redis.ping()
            logger.info("LLMCache: connected to Redis %s:%d", self._redis_host, self._redis_port)
            return True
        except Exception:
            logger.info("LLMCache: Redis unavailable, using in-memory fallback")
            self._redis = None
            return False

    @staticmethod
    def _make_key(model: str, prompt: str) -> str:
        h = hashlib.sha256(f"{model}||{prompt}".encode()).hexdigest()[:32]
        return f"{_REDIS_KEY_PREFIX}{h}"

    async def get(self, model: str, prompt: str) -> Any | None:
        """Return cached response or None on miss."""
        key = self._make_key(model, prompt)
        if await self._ensure_redis() and self._redis:
            try:
                raw = await self._redis.get(key)
                if raw:
                    logger.debug("LLMCache: Redis hit %s", key)
                    return json.loads(raw)
            except Exception:
                logger.warning("LLMCache: Redis get failed", exc_info=True)
        # fallback: in-memory
        entry = self._mem.get(key)
        if entry:
            expiry, val = entry
            if expiry > time.monotonic():
                logger.debug("LLMCache: memory hit %s", key)
                return json.loads(val)
            del self._mem[key]
        return None

    async def set(self, model: str, prompt: str, response: Any) -> None:
        """Cache a response."""
        key = self._make_key(model, prompt)
        raw = json.dumps(response)
        if await self._ensure_redis() and self._redis:
            try:
                await self._redis.setex(key, self._ttl, raw)
            except Exception:
                logger.warning("LLMCache: Redis set failed", exc_info=True)
        # always write to memory fallback
        self._mem[key] = (time.monotonic() + self._ttl, raw)
