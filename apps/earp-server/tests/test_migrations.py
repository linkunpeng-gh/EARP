"""AC-03: baseline migration is repeatable, downgradable, and seeds work under BYPASSRLS."""

from __future__ import annotations

import psycopg
import pytest
from alembic import command

from tests.conftest import alembic_config

EXPECTED_TABLES = 25  # tenants + 24 tenant-scoped tables (L3 design section 3)


@pytest.fixture(scope="module")
def fresh_db_url(pg_host_port: tuple[str, int], migration_url: str) -> str:
    host, port = pg_host_port
    with psycopg.connect(f"postgresql://postgres:postgres@{host}:{port}/earp", autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS earp_mig")
        conn.execute("CREATE DATABASE earp_mig")
    return f"postgresql+psycopg://postgres:postgres@{host}:{port}/earp_mig"


def _table_count(dsn: str) -> int:
    with psycopg.connect(dsn.replace("postgresql+psycopg://", "postgresql://", 1)) as conn:
        row = conn.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
        ).fetchone()
        return int(row[0]) if row else -1


def test_upgrade_idempotent_downgrade_and_seed(fresh_db_url: str) -> None:
    cfg = alembic_config(fresh_db_url)

    command.upgrade(cfg, "head")
    assert _table_count(fresh_db_url) == EXPECTED_TABLES

    # re-running upgrade head is a no-op (alembic version bookkeeping)
    command.upgrade(cfg, "head")
    assert _table_count(fresh_db_url) == EXPECTED_TABLES

    # seed under BYPASSRLS-capable migration role despite FORCE RLS (Gate B P0-2)
    raw = fresh_db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(raw) as conn:
        conn.execute("INSERT INTO tenants (tenant_id, name) VALUES ('t-seed', 'seed')")
        conn.execute(
            "INSERT INTO users (user_id, tenant_id, name, email) VALUES ('u-seed', 't-seed', 'seed', 's@e.io')"
        )
        conn.commit()
        row = conn.execute("SELECT count(*) FROM users").fetchone()
        assert row is not None and int(row[0]) == 1  # superuser bypasses RLS

    command.downgrade(cfg, "-1")
    assert _table_count(fresh_db_url) == 0

    command.upgrade(cfg, "head")
    assert _table_count(fresh_db_url) == EXPECTED_TABLES
