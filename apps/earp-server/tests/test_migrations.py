"""AC-03: baseline migration is repeatable, downgradable, and seeds work under BYPASSRLS."""

from __future__ import annotations

import psycopg
import pytest
from alembic import command

from tests.conftest import alembic_config

EXPECTED_TABLES = 44  # tenants+baseline+0005/6/8/9/14+0018(tbox_changes)+0019(eval 4 表)+0025(import_rules)


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

    command.downgrade(cfg, "0014_chat_apps")
    # head=0025：回退 0025(import_rules 表) + 0024(列) + 0023(表) + 0022(列) + 0021(列) + 0020(CHECK) +
    # 0019(eval 4 表) + 0018(tbox_changes 表) + 0017(加列) + 0016(纯 UPDATE) + 0015(加列) → 0014；
    # 表被回退（import_rules 1 + tbox_changes 1 + eval 4）= 6 → 表数 = EXPECTED_TABLES - 6
    assert _table_count(fresh_db_url) == EXPECTED_TABLES - 6

    command.upgrade(cfg, "head")
    assert _table_count(fresh_db_url) == EXPECTED_TABLES


def test_queue_schema_idempotent(migrated: str, migration_url: str) -> None:
    """P0-3/F5: queue_schema.apply() is safe to call twice (idempotent)."""
    import asyncio

    from earp_server.config import Settings
    from earp_server.infra.queue_schema import apply

    asyncio.run(apply(Settings(migration_database_url=migration_url)))
    raw = migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(raw) as conn:
        row = conn.execute("SELECT to_regclass('public.procrastinate_jobs')").fetchone()
        assert row is not None and row[0] is not None
