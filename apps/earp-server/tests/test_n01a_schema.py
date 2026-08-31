"""PostgreSQL contracts introduced by 0040 N01A."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session

TENANT = "n01a-schema-tenant"
SIGNATURE = "a" * 64
SNAPSHOT_HASH = "b" * 64
ARTIFACT_HASH = "c" * 64


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _published_source(engine: AsyncEngine) -> None:
    async with tenant_session(engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO causal_models "
                "(tenant_id, model_id, data_domain_id, name, diagnostic_target_signature) "
                "VALUES (:tenant, 'cm-n01a-schema', 'production', 'N01A schema', :signature) "
                "ON CONFLICT (tenant_id, model_id) DO NOTHING"
            ),
            {"tenant": TENANT, "signature": SIGNATURE},
        )
        await session.execute(
            text(
                "INSERT INTO causal_model_versions "
                "(tenant_id, model_version_id, model_id, version, status, diagnostic_target, "
                " diagnostic_target_signature, created_by, updated_by) "
                "VALUES (:tenant, 'cmv-n01a-schema', 'cm-n01a-schema', '1', 'published', '{}'::jsonb, "
                " :signature, 'actor', 'actor') ON CONFLICT (tenant_id, model_version_id) DO NOTHING"
            ),
            {"tenant": TENANT, "signature": SIGNATURE},
        )
        await session.execute(
            text(
                "INSERT INTO causal_model_snapshots "
                "(tenant_id, snapshot_id, model_version_id, content_hash, nodes_json, edges_json, rules_json, "
                " requirements_json, schema_version, canonical_payload, canonicalizer_version) "
                "VALUES (:tenant, 'cms-n01a-schema', 'cmv-n01a-schema', :hash, '[]','[]','[]','[]', "
                " 'causal-snapshot/v1', '{}'::jsonb, 'n01a/v1') "
                "ON CONFLICT (tenant_id, snapshot_id) DO NOTHING"
            ),
            {"tenant": TENANT, "hash": SNAPSHOT_HASH},
        )
        await session.execute(
            text(
                "UPDATE causal_model_versions SET published_snapshot_id = 'cms-n01a-schema' "
                "WHERE model_version_id = 'cmv-n01a-schema'"
            )
        )


async def test_active_pointer_requires_exact_same_model_version_snapshot(app_engine: AsyncEngine) -> None:
    await _published_source(app_engine)
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "UPDATE causal_models SET active_model_version_id = 'cmv-n01a-schema', "
                "active_snapshot_id = 'cms-n01a-schema' WHERE model_id = 'cm-n01a-schema'"
            )
        )
    with pytest.raises(Exception, match="foreign key"):
        async with tenant_session(app_engine, TENANT) as session:
            await session.execute(
                text(
                    "INSERT INTO causal_models "
                    "(tenant_id, model_id, data_domain_id, name, diagnostic_target_signature, "
                    " active_model_version_id, active_snapshot_id) "
                    "VALUES (:tenant, 'cm-wrong-owner', 'production', 'wrong owner', :signature, "
                    " 'cmv-n01a-schema', 'cms-n01a-schema')"
                ),
                {"tenant": TENANT, "signature": SIGNATURE},
            )


async def test_n01a_children_are_draft_only_but_legacy_fixture_boundary_remains(app_engine: AsyncEngine) -> None:
    await _published_source(app_engine)
    with pytest.raises(Exception, match="writable only in draft"):
        async with tenant_session(app_engine, TENANT) as session:
            await session.execute(
                text(
                    "INSERT INTO causal_nodes "
                    "(tenant_id,node_row_id,model_version_id,node_key,node_seq,entity_type_ref) "
                    "VALUES (:tenant,'node-forbidden','cmv-n01a-schema','entry',1,'entity.mine')"
                ),
                {"tenant": TENANT},
            )


async def test_compile_attempt_terminal_artifact_and_retry_lineage(app_engine: AsyncEngine) -> None:
    await _published_source(app_engine)
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO blueprint_compile_records "
                "(tenant_id,compile_id,primary_model_type,primary_model_id,primary_model_version,"
                "source_models_snapshot,source_model_hashes,compiler_version,input_snapshot,status,"
                "model_version_id,snapshot_id,n01a_attempt,requested_by) "
                "VALUES (:tenant,'cr-failed','causal','cm-n01a-schema','1','[]','{}','n01a-v1','{}',"
                "'running','cmv-n01a-schema','cms-n01a-schema',true,'actor')"
            ),
            {"tenant": TENANT},
        )
        await session.execute(
            text(
                "UPDATE blueprint_compile_records SET status='failed', finished_at=now() "
                "WHERE compile_id='cr-failed'"
            )
        )
        await session.execute(
            text(
                "INSERT INTO blueprint_compile_records "
                "(tenant_id,compile_id,primary_model_type,primary_model_id,primary_model_version,"
                "source_models_snapshot,source_model_hashes,compiler_version,input_snapshot,status,"
                "model_version_id,snapshot_id,n01a_attempt,requested_by,retry_of_compile_id) "
                "VALUES (:tenant,'cr-retry','causal','cm-n01a-schema','1','[]','{}','n01a-v1','{}',"
                "'running','cmv-n01a-schema','cms-n01a-schema',true,'actor','cr-failed')"
            ),
            {"tenant": TENANT},
        )
        artifact = {"artifact_schema_version": "blueprint-ir/v1"}
        await session.execute(
            text(
                "UPDATE blueprint_compile_records SET status='success', compiled_artifact_json=:artifact, "
                "compiled_artifact_hash=:hash, artifact_schema_version='blueprint-ir/v1', finished_at=now() "
                "WHERE compile_id='cr-retry'"
            ),
            {"artifact": json.dumps(artifact), "hash": ARTIFACT_HASH},
        )
    with pytest.raises(Exception, match="terminal N01A compile attempts are immutable"):
        async with tenant_session(app_engine, TENANT) as session:
            await session.execute(
                text("UPDATE blueprint_compile_records SET status='running' WHERE compile_id='cr-retry'")
            )
    with pytest.raises(Exception, match="retry parent must be a failed"):
        async with tenant_session(app_engine, TENANT) as session:
            await session.execute(
                text(
                    "INSERT INTO blueprint_compile_records "
                    "(tenant_id,compile_id,primary_model_type,primary_model_id,primary_model_version,"
                    "source_models_snapshot,source_model_hashes,compiler_version,input_snapshot,status,"
                    "model_version_id,snapshot_id,n01a_attempt,requested_by,retry_of_compile_id) "
                    "VALUES (:tenant,'cr-bad-retry','causal','cm-n01a-schema','1','[]','{}','n01a-v1','{}',"
                    "'running','cmv-n01a-schema','cms-n01a-schema',true,'actor','cr-retry')"
                ),
                {"tenant": TENANT},
            )
