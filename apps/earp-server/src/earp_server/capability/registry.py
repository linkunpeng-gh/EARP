"""Capability registration + exact-match discovery. pgvector semantic search deferred to M4."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_DEMO_CAPABILITY = {
    "capability_id": "cap-demo-echo",
    "domain": "demo",
    "name": "echo",
    "type": "query",
    "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}},
    "version": "1.0.0",
}


async def register_demo(engine: AsyncEngine, tenant_id: str) -> None:
    """Register the built-in 'echo' demo capability (idempotent)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
                "input_schema, output_schema, version) "
                "VALUES (:cid, :tid, :domain, :name, :type, :inp, '{}', :ver) "
                "ON CONFLICT (capability_id) DO NOTHING"
            ),
            {
                "cid": _DEMO_CAPABILITY["capability_id"],
                "tid": tenant_id,
                "domain": _DEMO_CAPABILITY["domain"],
                "name": _DEMO_CAPABILITY["name"],
                "type": _DEMO_CAPABILITY["type"],
                "inp": json.dumps(_DEMO_CAPABILITY["input_schema"]),
                "ver": _DEMO_CAPABILITY["version"],
            },
        )
        await conn.commit()


async def discover(engine: AsyncEngine, tenant_id: str, query: str | None = None) -> list[dict[str, Any]]:
    """Exact-match discovery by capability name (LIKE). pgvector semantic search in M4."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        if query:
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
