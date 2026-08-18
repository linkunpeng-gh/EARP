"""AC-04: RLS policies exist on every tenant-scoped table; cross-tenant reads return nothing."""

from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import build_session_factory, tenant_session

TENANT_TABLE_COUNT = 42  # 0018 tbox_changes + 0019 eval 4 表（RLS 三件套）  # baseline(24) + 0005(2) + 0006(1) + 0008(7 ontology) + 0009(2 model) + 0014(1 chat_apps)


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def test_policy_exists_on_all_tenant_tables(migrated: str, migration_url: str) -> None:
    raw = migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(raw) as conn:
        row = conn.execute("SELECT count(*) FROM pg_policies WHERE policyname = 'tenant_isolation'").fetchone()
        assert row is not None and int(row[0]) == TENANT_TABLE_COUNT


async def test_cross_tenant_isolation_on_four_tables(app_engine: AsyncEngine) -> None:
    # arrange under t1 (earp_app role, FORCE RLS active)
    async with tenant_session(app_engine, "rls-t1") as session:
        await session.execute(
            text(
                "INSERT INTO sessions (session_id, tenant_id, user_id, role_id) "
                "VALUES ('rls-s1', 'rls-t1', 'u1', 'r1') ON CONFLICT DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO executions (execution_id, tenant_id, session_id, role_id) "
                "VALUES ('rls-e1', 'rls-t1', 'rls-s1', 'r1') ON CONFLICT DO NOTHING"
            )
        )
        await session.execute(
            text("INSERT INTO audit_logs (tenant_id, event_type, detail) VALUES ('rls-t1', 'SESSION_CREATED', '{}')")
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name) "
                "VALUES ('rls-kb1', 'rls-t1', 'kb') ON CONFLICT DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO documents (document_id, tenant_id, knowledge_base_id, name) "
                "VALUES ('rls-d1', 'rls-t1', 'rls-kb1', 'doc') ON CONFLICT DO NOTHING"
            )
        )

    # same tenant sees its rows
    async with tenant_session(app_engine, "rls-t1") as session:
        count = await session.execute(text("SELECT count(*) FROM sessions WHERE session_id = 'rls-s1'"))
        assert int(count.scalar_one()) == 1

    # other tenant sees nothing in any of the four tables
    async with tenant_session(app_engine, "rls-t2") as session:
        for table in ("sessions", "executions", "audit_logs", "documents"):
            count = await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert int(count.scalar_one()) == 0, f"tenant rls-t2 must not see {table} rows of rls-t1"


async def test_update_delete_cross_tenant_blocked(app_engine: AsyncEngine) -> None:
    """UPDATE/DELETE from another tenant must affect zero rows (Gate C P1-8)."""
    async with tenant_session(app_engine, "rls-t2") as session:
        updated = await session.execute(text("UPDATE sessions SET status = 'hijacked' WHERE session_id = 'rls-s1'"))
        assert updated.rowcount == 0
        deleted = await session.execute(text("DELETE FROM sessions WHERE session_id = 'rls-s1'"))
        assert deleted.rowcount == 0


async def test_unset_tenant_guc_sees_nothing(app_engine: AsyncEngine) -> None:
    """Without SET LOCAL earp.tenant_id the policy matches nothing (Gate C P1-8)."""
    factory = build_session_factory(app_engine)
    async with factory() as session:
        count = await session.execute(text("SELECT count(*) FROM sessions"))
        assert int(count.scalar_one()) == 0


async def test_empty_tenant_id_rejected(app_engine: AsyncEngine) -> None:
    """tenant_session self-defense (Gate C P1-2)."""
    with pytest.raises(ValueError, match="non-empty"):
        async with tenant_session(app_engine, "  "):
            pass  # pragma: no cover


async def test_full_table_rls_matrix(app_engine: AsyncEngine) -> None:
    """P0-3: all 24 tenant-scoped tables enforce cross-tenant isolation (SELECT+UPDATE+DELETE)."""
    tables = [
        "org_units",
        "users",
        "roles",
        "service_accounts",
        "tenant_account_joins",
        "sessions",
        "executions",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "business_capabilities",
        "capability_calls",
        "connector_bindings",
        "policies",
        "policy_bindings",
        "audit_logs",
        "encrypted_credentials",
        "api_keys",
        "knowledge_bases",
        "documents",
        "chunks",
        "conversations",
        "messages",
        "connector_configs",
    ]
    async with tenant_session(app_engine, "rls-t1") as session:
        for table in tables:
            count = await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert int(count.scalar_one()) >= 0, f"{table}: SELECT failed under RLS"
    async with tenant_session(app_engine, "rls-t2") as session:
        for table in tables:
            count = await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert int(count.scalar_one()) == 0, f"{table}: t2 must see 0 rows"
            # UPDATE must affect 0 rows (cross-tenant write blocked by RLS)
            updated = await session.execute(
                text(f"UPDATE {table} SET tenant_id = 'hijacked' WHERE tenant_id = 'rls-t1'")
            )
            assert updated.rowcount == 0, f"{table}: UPDATE must affect 0 rows"
            # DELETE must affect 0 rows (cross-tenant write blocked by RLS)
            deleted = await session.execute(text(f"DELETE FROM {table} WHERE tenant_id = 'rls-t1'"))
            assert deleted.rowcount == 0, f"{table}: DELETE must affect 0 rows"


async def test_insert_with_mismatched_tenant_rejected(app_engine: AsyncEngine) -> None:
    with pytest.raises(Exception, match="row.level security"):
        async with tenant_session(app_engine, "rls-t2") as session:
            await session.execute(
                text(
                    "INSERT INTO sessions (session_id, tenant_id, user_id, role_id) "
                    "VALUES ('rls-bad', 'rls-t1', 'u1', 'r1')"
                )
            )
