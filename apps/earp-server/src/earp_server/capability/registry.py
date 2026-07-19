"""Capability registration + role-aware discovery + Redis token-bucket rate limiter."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_DEMO_CAPABILITY = {
    "capability_id": "cap-demo-echo",
    "domain": "demo",
    "name": "echo",
    "type": "query",
    "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}},
    "required_permissions": ["demo:echo"],
    "version": "1.0.0",
}


async def register_demo(engine: AsyncEngine, tenant_id: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, required_permissions, version) "
                "VALUES (:cid, :tid, :domain, :name, :type, :inp, '{}', :perms, :ver) "
                "ON CONFLICT (capability_id) DO NOTHING"
            ),
            {
                "cid": _DEMO_CAPABILITY["capability_id"],
                "tid": tenant_id,
                "domain": _DEMO_CAPABILITY["domain"],
                "name": _DEMO_CAPABILITY["name"],
                "type": _DEMO_CAPABILITY["type"],
                "inp": json.dumps(_DEMO_CAPABILITY["input_schema"]),
                "perms": "{demo:echo}",
                "ver": _DEMO_CAPABILITY["version"],
            },
        )
        await conn.commit()


async def discover(
    engine: AsyncEngine, tenant_id: str, *, role_id: str | None = None, query: str | None = None
) -> list[dict[str, Any]]:
    """Role-aware discovery. If role_id given, filter to capabilities the role can access."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        if role_id:
            rows = await conn.execute(
                text(
                    "SELECT c.capability_id, c.domain, c.name, c.type, c.version "
                    "FROM business_capabilities c, roles r "
                    "WHERE c.tenant_id = :tid AND r.role_id = :rid "
                    "AND (:query IS NULL OR c.name LIKE :q) "
                    "AND c.required_permissions <@ r.permissions"
                ),
                {"tid": tenant_id, "rid": role_id, "query": query, "q": f"%{query}%" if query else None},
            )
        elif query:
            rows = await conn.execute(
                text(
                    "SELECT capability_id, domain, name, type, version FROM business_capabilities "
                    "WHERE tenant_id = :tid AND name LIKE :q"
                ),
                {"tid": tenant_id, "q": f"%{query}%"},
            )
        else:
            rows = await conn.execute(
                text(
                    "SELECT capability_id, domain, name, type, version FROM business_capabilities "
                    "WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        return [dict(r._mapping) for r in rows]


# ── Redis Token Bucket Rate Limiter ───────────────────────────────────────────

class TokenBucketRateLimiter:
    """Per-tenant token bucket rate limiter backed by Redis.

    Algorithm: INCR key + EXPIRE on first request in each second window.
    Falls back to pass-through if Redis is unavailable (logged warning).
    """

    def __init__(self, host: str = "localhost", port: int = 6380, rps: int = 100) -> None:
        self._rps = rps
        self._host = host
        self._port = port
        self._redis = None

    async def _ensure_redis(self):
        if self._redis is not None:
            return
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.Redis(host=self._host, port=self._port, socket_connect_timeout=2)
        except Exception:
            logger.warning("Redis unavailable, rate limiter disabled")
            self._redis = False

    async def is_allowed(self, tenant_id: str) -> bool:
        await self._ensure_redis()
        if self._redis is False:
            return True  # pass-through on Redis failure
        key = f"rate:{tenant_id}:{int(time.time())}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, 2)
            return count <= self._rps
        except Exception:
            logger.warning("Redis rate-limit check failed", exc_info=True)
            return True
