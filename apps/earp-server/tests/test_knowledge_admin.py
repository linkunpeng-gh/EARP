"""Knowledge admin API tests (PRD-2026-028 §6.5/§6.6) — KB CRUD + DD aggregates.

Exercises admin_service against the real schema (post-0007 alignment).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.knowledge.admin_service import (
    create_data_domain,
    create_kb,
    delete_document,
    delete_kb,
    list_data_domains,
    list_documents,
    list_kbs,
    update_document_classification,
)
from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import create_document


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def test_kb_crud_and_aggregates(app_engine: AsyncEngine) -> None:
    tid = "kadm-t1"
    async with tenant_session(app_engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, data_classification, status) "
                "VALUES ('equipment_data', :tid, '设备数据', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )

    # create KB + seed one document with chunks
    kb = await create_kb(app_engine, tid, "设备手册", "equipment_data")
    doc = await create_document(app_engine, tid, kb["knowledge_base_id"], "主轴轴承每 6 个月更换", "CNC Manual")
    await create_chunks(app_engine, tid, doc["document_id"], "主轴轴承每 6 个月更换")

    # list with aggregates
    kbs = await list_kbs(app_engine, tid)
    assert len(kbs) == 1
    assert kbs[0]["doc_count"] == 1
    assert kbs[0]["chunk_count"] == 1
    assert kbs[0]["data_domain_id"] == "equipment_data"

    # documents listing
    docs = await list_documents(app_engine, tid, kb["knowledge_base_id"])
    assert len(docs) == 1
    assert docs[0]["chunk_count"] == 1
    assert docs[0]["data_classification"] == "internal"

    # classification update
    updated = await update_document_classification(app_engine, tid, doc["document_id"], "confidential")
    assert updated is not None and updated["data_classification"] == "confidential"

    # delete document → kb aggregate drops to 0 docs
    assert await delete_document(app_engine, tid, doc["document_id"]) == 1
    kbs = await list_kbs(app_engine, tid)
    assert kbs[0]["doc_count"] == 0

    # delete kb
    assert await delete_kb(app_engine, tid, kb["knowledge_base_id"]) == 1
    assert await list_kbs(app_engine, tid) == []


async def test_data_domains_aggregates(app_engine: AsyncEngine) -> None:
    tid = "kadm-t2"
    async with tenant_session(app_engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, data_classification, status) "
                "VALUES ('equipment_data', :tid, '设备数据', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )

    await create_kb(app_engine, tid, "设备手册 A", "equipment_data")
    await create_kb(app_engine, tid, "设备手册 B", "equipment_data")

    domains = await list_data_domains(app_engine, tid)
    assert len(domains) == 1
    assert domains[0]["kb_count"] == 2

    # other tenant sees nothing (RLS)
    assert await list_data_domains(app_engine, "kadm-other") == []


async def test_create_data_domain_idempotent(app_engine: AsyncEngine) -> None:
    tid = "kadm-t3"
    created = await create_data_domain(app_engine, tid, "hr_data", "人事数据", "confidential")
    assert created["data_classification"] == "confidential"
    again = await create_data_domain(app_engine, tid, "hr_data", "人事数据", "confidential")
    assert again["data_domain_id"] == "hr_data"
    assert len(await list_data_domains(app_engine, tid)) == 1
