#!/usr/bin/env python3
"""Dev-only routing eval with the REAL embedding provider (bge-m3 via Ollama).

CI uses the bigram stub (mechanism); this script measures semantic accuracy
against the live stack: seed DDs/KBs/docs → embed with the configured provider
→ run routing_eval.md cases → report pass rate (acceptance ≥90%, design §7).

Usage (from apps/earp-server, with services up):
    uv run python scripts/verify_routing.py

Requires: Postgres migrated + embedding provider reachable (EARP_OLLAMA_*).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from earp_server.config import Settings  # noqa: E402
from earp_server.infra.db import build_engine, tenant_session  # noqa: E402
from earp_server.infra.ext.ext_embedding import init_app as _init_embedding  # noqa: E402
from earp_server.knowledge.document_service import create_document  # noqa: E402
from earp_server.knowledge.embedding_service import embed_query  # noqa: E402
from earp_server.knowledge.routing import build_routing_index, route_query  # noqa: E402

EVAL_MD = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "routing_eval.md"
TENANT = "verify-routing"
ROLE = "verify-role"

SEED = [
    # (dd_id, dd_name, dd_desc, kb_id, kb_name, kb_desc)
    ("finance_data", "财务数据", "财务制度、报销与成本管理", "kb-fin", "费用报销流程手册", "报销标准与流程说明"),
    ("equipment_data", "设备数据", "设备运行、报警与维护", "kb-alarm", "报警阈值配置", "设备报警阈值设定"),
    ("equipment_data", "设备数据", "设备运行、报警与维护", "kb-manual", "设备手册", "设备结构、主轴轴承更换周期"),
    ("hr_data", "人力资源", "员工、休假与公司政策", "kb-policy", "公司政策", "员工休假政策"),
]

DOCS = [
    ("kb-fin", "报销制度v1", "财务部报销制度：差旅报销标准与流程。"),
    ("kb-fin", "2024报销标准", "2024年报销标准：住宿每天500元，餐饮每天100元。"),
    ("kb-alarm", "报警阈值配置说明", "设备报警阈值：主轴温度超过85度触发报警。"),
    ("kb-manual", "主轴轴承更换周期", "主轴轴承更换周期：每运行8000小时更换一次。"),
    ("kb-policy", "员工休假政策", "员工年假10天，病假凭证明，产假按国家规定。"),
]


def _parse_cases() -> list[dict]:
    cases = []
    for line in EVAL_MD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or "query" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        cases.append({"query": cells[1], "expected_dd": cells[2], "expected_kb": cells[3]})
    return cases


async def main() -> int:
    settings = Settings()
    _init_embedding(settings)  # real provider (bge-m3) for semantic eval
    # dev tool: use the migration (superuser) engine — BYPASSRLS so we can purge
    # cross-tenant same-id rows (data_domains PK is single-column, known debt #7)
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.migration_database_url)

    # reset: purge same-id rows across ALL tenants (demo seeds reuse these ids)
    ids = [dd[0] for dd in SEED]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM chunks WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await conn.execute(
            text(
                "DELETE FROM documents WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        await conn.execute(text("DELETE FROM knowledge_bases WHERE data_domain_id = ANY(:ids)"), {"ids": ids})
        await conn.execute(text("DELETE FROM data_domains WHERE data_domain_id = ANY(:ids)"), {"ids": ids})
        await conn.execute(text("DELETE FROM roles WHERE role_id = :rid"), {"rid": ROLE})

    async with tenant_session(engine, TENANT) as session:
        seen_dds: set[str] = set()
        for dd_id, dd_name, dd_desc, kb_id, kb_name, kb_desc in SEED:
            if dd_id not in seen_dds:
                await session.execute(
                    text(
                        "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                        "data_classification, status) VALUES (:id, :tid, :name, :desc, 'internal', 'active')"
                    ),
                    {"id": dd_id, "tid": TENANT, "name": dd_name, "desc": dd_desc},
                )
                seen_dds.add(dd_id)
            await session.execute(
                text(
                    "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, "
                    "description, metadata_schema) VALUES (:kid, :tid, :name, :dd, :desc, '[]')"
                ),
                {"kid": kb_id, "tid": TENANT, "name": kb_name, "dd": dd_id, "desc": kb_desc},
            )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'verify', '{}', 'all', "
                "'[{\"data_domain_id\": \"finance_data\"}, {\"data_domain_id\": \"equipment_data\"}, "
                "{\"data_domain_id\": \"hr_data\"}]')"
            ),
            {"rid": ROLE, "tid": TENANT},
        )
        await session.commit()

    for kb, title, content in DOCS:
        await create_document(engine, TENANT, kb, content, title=title)
    stats = await build_routing_index(engine, TENANT)
    print(f"routing index: {stats}")

    cases = _parse_cases()
    hits = 0
    for case in cases:
        q_emb = await embed_query(case["query"])
        routed = await route_query(engine, TENANT, case["query"], q_emb, ROLE, top_n=5, top_k=3)
        dd_ids = [c["data_domain_id"] for c in routed["candidate_dds"]]
        ok = case["expected_dd"] in dd_ids
        hits += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['query']:<18} -> {dd_ids}  (expect {case['expected_dd']})")
    rate = hits / len(cases)
    print(f"\npass rate: {hits}/{len(cases)} = {rate:.0%}  (acceptance ≥ 90%)")
    return 0 if rate >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
