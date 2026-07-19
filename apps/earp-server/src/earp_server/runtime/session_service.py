"""Session CRUD — scope to tenant (RLS-enforced at DB layer)."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.schemas.sessions import SessionResponse


async def create_session(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    role_id: str,
    metadata: dict | None = None,
) -> SessionResponse:
    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    meta_json = json.dumps(metadata or {})
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO sessions (session_id, tenant_id, user_id, role_id, metadata) "
                "VALUES (:sid, :tid, :uid, :rid, :meta)"
            ),
            {"sid": session_id, "tid": tenant_id, "uid": user_id, "rid": role_id, "meta": meta_json},
        )
        await conn.commit()
    return SessionResponse(session_id=session_id, tenant_id=tenant_id, user_id=user_id)


async def get_session(engine: AsyncEngine, session_id: str, tenant_id: str) -> SessionResponse | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT session_id, tenant_id, user_id, status FROM sessions WHERE session_id = :sid"),
            {"sid": session_id},
        )
        result = row.fetchone()
    if result is None:
        return None
    return SessionResponse(
        session_id=result.session_id,
        tenant_id=result.tenant_id,
        user_id=result.user_id,
        status=result.status,
    )


async def close_session(engine: AsyncEngine, session_id: str, tenant_id: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text("UPDATE sessions SET status = 'closed' WHERE session_id = :sid"),
            {"sid": session_id},
        )
        await conn.commit()
