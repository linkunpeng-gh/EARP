"""PRD-2026-023 #1 — Data Domain routing (planner-spec v1.1 §5.1.2).

Rule-based routing: intent keywords → candidate Data Domains → intersect with
tenant-registered active domains. Empty result must not block BD routing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.knowledge.routing import match_data_domains
from earp_server.planner.service import resolve_data_domains


def test_match_data_domains_zh_keywords() -> None:
    assert "equipment_data" in match_data_domains("查询设备报警")
    assert "hr_data" in match_data_domains("休假政策是什么")
    assert "production_data" in match_data_domains("创建工单")


def test_match_data_domains_en_keywords() -> None:
    assert "equipment_data" in match_data_domains("query alarms")
    assert "hr_data" in match_data_domains("leave policy")


def test_match_data_domains_no_hit() -> None:
    assert match_data_domains("hello world") == []


def test_match_data_domains_multi_hit() -> None:
    hits = match_data_domains("设备工单")
    assert "equipment_data" in hits
    assert "production_data" in hits


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def test_resolve_registered_only(app_engine: AsyncEngine) -> None:
    """Only domains registered for the tenant are returned (RLS-scoped)."""
    async with tenant_session(app_engine, "dd-t1") as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, data_classification, status) "
                "VALUES ('equipment_data', 'dd-t1', '设备数据', 'internal', 'active') "
                "ON CONFLICT DO NOTHING"
            )
        )

    # equipment_data registered → resolved; production_data not registered → filtered
    domains = await resolve_data_domains(app_engine, "dd-t1", "设备报警工单")
    assert domains == ["equipment_data"]

    # other tenant has no data_domains → empty (RLS isolation)
    domains2 = await resolve_data_domains(app_engine, "dd-t2", "设备报警")
    assert domains2 == []


async def test_resolve_no_keyword_hit(app_engine: AsyncEngine) -> None:
    assert await resolve_data_domains(app_engine, "dd-t1", "hello world") == []
