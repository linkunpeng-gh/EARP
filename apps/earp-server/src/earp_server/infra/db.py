"""Async database engine/session helpers.

tenant_session implements contract "A" (L3 design section 1.4):
entering opens a transaction and applies SET LOCAL earp.tenant_id;
normal exit commits, exceptions roll back. One context = one transaction.

Preferred pattern for data-access functions:
    async with tenant_session(engine, tenant_id) as session:
        result = await session.execute(...)

Alternative (legacy, still valid): manual engine.connect() + SET LOCAL.
Both patterns are functionally equivalent — tenant_session() is recommended
for new code as it guarantees GUC is set without relying on developer memory.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from earp_server.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_db(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness probe swallows all failures by design
        return False


@asynccontextmanager
async def tenant_session(engine: AsyncEngine, tenant_id: str) -> AsyncGenerator[AsyncSession]:
    """Contract A: one context manager = one transaction with tenant GUC applied."""
    if not tenant_id or not tenant_id.strip():
        # Self-defense (Gate C P1-2): SET LOCAL earp.tenant_id = '' would make RLS
        # silently match nothing; refuse early instead.
        raise ValueError("tenant_id must be non-empty")
    factory = build_session_factory(engine)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('earp.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            yield session
