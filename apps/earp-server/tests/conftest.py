"""Shared fixtures: one PG16+pgvector container per test session (L3 design section 6).

- scope="session", startup timeout 60s, tests run serially (no xdist in M0)
- migration role = container superuser (BYPASSRLS by nature)
- app role = earp_app (created by 0001_baseline, no BYPASSRLS -> FORCE RLS effective)
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    # testcontainers-python waits for readiness internally (default timeout 120s,
    # tunable via TC_MAX_TRIES/TC_POOLING_INTERVAL env if CI ever needs it).
    container = PostgresContainer("pgvector/pgvector:pg16", username="postgres", password="postgres", dbname="earp")
    with container as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_host_port(pg_container: PostgresContainer) -> tuple[str, int]:
    return pg_container.get_container_host_ip(), int(pg_container.get_exposed_port(5432))


@pytest.fixture(scope="session")
def migration_url(pg_host_port: tuple[str, int]) -> str:
    host, port = pg_host_port
    return f"postgresql+psycopg://postgres:postgres@{host}:{port}/earp"


@pytest.fixture(scope="session")
def app_url(pg_host_port: tuple[str, int]) -> str:
    host, port = pg_host_port
    return f"postgresql+psycopg://earp_app:earp_app@{host}:{port}/earp"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    os.environ["EARP_MIGRATION_DATABASE_URL"] = url
    return cfg


@pytest.fixture(scope="session")
def migrated(migration_url: str) -> str:
    """Upgrade the session database to head + apply procrastinate schema. Returns app URL base."""
    command.upgrade(alembic_config(migration_url), "head")

    import asyncio

    from earp_server.config import Settings
    from earp_server.infra.queue_schema import apply

    asyncio.run(apply(Settings(migration_database_url=migration_url)))
    return migration_url
