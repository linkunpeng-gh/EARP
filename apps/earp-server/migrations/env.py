"""Alembic environment - async engine (psycopg3) with offline --sql support.

URL source: EARP_MIGRATION_DATABASE_URL (BYPASSRLS-capable role, L3 design
"dual-role strategy"). The application role earp_app must NOT run migrations.
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

DEFAULT_URL = "postgresql+psycopg://postgres:postgres@localhost:5433/earp"


def _url() -> str:
    return os.environ.get("EARP_MIGRATION_DATABASE_URL", DEFAULT_URL)


def run_migrations_offline() -> None:
    """Emit SQL script (used by `alembic upgrade head --sql` -> squawk lint)."""
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
