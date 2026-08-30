"""T04: real PostgreSQL contracts for Case A causal/Blueprint/reasoning persistence."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session

TENANT = "t04-schema-a"
OTHER_TENANT = "t04-schema-b"


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def seeded_schema(migrated: str, migration_url: str) -> str:
    """Seed platform registries and two Blueprint versions with the migration role."""
    dsn = _raw(migration_url)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO reasoning_algorithms (algorithm_id, name) "
            "VALUES ('t04-sign', 'T04 Sign') ON CONFLICT DO NOTHING"
        )
        conn.execute(
            """
            INSERT INTO reasoning_algorithm_versions (
                algorithm_version_id, algorithm_id, version, contract_version,
                profile_version, profile_json, params_schema, handler,
                implementation_hash, status
            ) VALUES (
                't04-sign-v1', 't04-sign', '1.0', '1', '1', '{}', '{}',
                'tests.t04', 'algorithm-hash', 'active'
            ) ON CONFLICT DO NOTHING
            """
        )
        conn.execute(
            "INSERT INTO step_types (type_id, type_name, is_core) "
            "VALUES ('t04-query', 'T04 Query', true) ON CONFLICT DO NOTHING"
        )
        conn.execute(
            """
            INSERT INTO step_type_versions (
                step_type_version_id, type_id, version, handler_version,
                handler_hash, semantic_contract_version, status
            ) VALUES (
                't04-query-v1', 't04-query', '1.0', '1.0', 'handler-hash', '1', 'active'
            ) ON CONFLICT DO NOTHING
            """
        )

        for tenant in (TENANT, OTHER_TENANT):
            conn.execute(
                """
                INSERT INTO causal_models (tenant_id, model_id, data_domain_id, name)
                VALUES (%s, 'shared-model-id', 'production', %s)
                ON CONFLICT DO NOTHING
                """,
                (tenant, f"model-{tenant}"),
            )
        conn.execute(
            """
            INSERT INTO causal_model_versions (
                tenant_id, model_version_id, model_id, version, status
            ) VALUES (%s, 'model-v1', 'shared-model-id', '1.0', 'testing')
            """,
            (TENANT,),
        )
        conn.execute(
            """
            INSERT INTO causal_model_versions (
                tenant_id, model_version_id, model_id, version, status
            ) VALUES (%s, 'model-v1', 'shared-model-id', '1.0', 'testing')
            """,
            (OTHER_TENANT,),
        )
        conn.execute(
            """
            INSERT INTO causal_model_snapshots (
                tenant_id, snapshot_id, model_version_id, content_hash,
                nodes_json, edges_json, rules_json, requirements_json
            ) VALUES (%s, 'snapshot-v1', 'model-v1', 'snapshot-hash', '[]', '[]', '[]', '[]')
            """,
            (TENANT,),
        )
        conn.execute(
            """
            INSERT INTO causal_model_snapshots (
                tenant_id, snapshot_id, model_version_id, content_hash,
                nodes_json, edges_json, rules_json, requirements_json
            ) VALUES (%s, 'snapshot-other', 'model-v1', 'other-snapshot-hash', '[]', '[]', '[]', '[]')
            """,
            (OTHER_TENANT,),
        )

        for suffix, status in (("1", "success"), ("2", "success"), ("failed", "failed")):
            conn.execute(
                """
                INSERT INTO blueprint_compile_records (
                    tenant_id, compile_id, primary_model_type, primary_model_id,
                    primary_model_version, source_models_snapshot, source_model_hashes,
                    compiler_version, input_snapshot, status
                ) VALUES (%s, %s, 'causal', 'shared-model-id', '1.0', '[]', '{}', '1', '{}', %s)
                """,
                (TENANT, f"compile-{suffix}", status),
            )
        conn.execute(
            """
            INSERT INTO blueprint_compile_records (
                tenant_id, compile_id, primary_model_type, primary_model_id,
                primary_model_version, source_models_snapshot, source_model_hashes,
                compiler_version, input_snapshot
            ) VALUES (%s, 'compile-running', 'causal', 'shared-model-id', '1.0', '[]', '{}', '1', '{}')
            """,
            (TENANT,),
        )
        conn.execute(
            """
            INSERT INTO planning_blueprints (
                tenant_id, blueprint_id, primary_model_type, primary_model_id, name
            ) VALUES (%s, 'blueprint-1', 'causal', 'shared-model-id', 'T04 Blueprint')
            """,
            (TENANT,),
        )
        conn.execute(
            """
            INSERT INTO planning_blueprint_versions (
                tenant_id, blueprint_version_id, blueprint_id, version, status,
                compile_record_id, compiler_version, intent_signature
            ) VALUES
                (%s, 'blueprint-v1', 'blueprint-1', '1', 'compiled', 'compile-1', '1', '{}'),
                (%s, 'blueprint-v2', 'blueprint-1', '2', 'superseded', 'compile-2', '1', '{}')
            """,
            (TENANT, TENANT),
        )
        conn.execute(
            """
            INSERT INTO blueprint_source_models (
                tenant_id, source_ref_id, blueprint_version_id, model_type, model_id,
                model_version, source_snapshot_id, source_content_hash, model_role
            ) VALUES
                (%s, 'source-v1', 'blueprint-v1', 'causal', 'shared-model-id',
                 '1.0', 'snapshot-v1', 'snapshot-hash', 'primary_model'),
                (%s, 'source-v2', 'blueprint-v2', 'causal', 'shared-model-id',
                 '1.0', 'snapshot-v1', 'snapshot-hash', 'primary_model')
            """,
            (TENANT, TENANT),
        )
        conn.execute(
            """
            INSERT INTO blueprint_steps (
                tenant_id, step_id, blueprint_version_id, step_seq,
                step_type_version_id, step_type, step_name
            ) VALUES
                (%s, 'step-v1', 'blueprint-v1', 1, 't04-query-v1', 'knowledge_query', 'query v1'),
                (%s, 'step-v2', 'blueprint-v2', 1, 't04-query-v1', 'knowledge_query', 'query v2')
            """,
            (TENANT, TENANT),
        )
        conn.execute(
            """
            INSERT INTO reasoning_contexts (
                tenant_id, prepare_id, model_version_id, snapshot_id, snapshot_hash,
                target_json, time_window_json, instance_snapshot, evidence_requirements,
                scope_meta, algorithm_version_id, algorithm_profile_version,
                algorithm_params_json, algorithm_config_hash, context_hash, expires_at
            ) VALUES (
                %s, 'prepare-1', 'model-v1', 'snapshot-v1', 'snapshot-hash', '{}', '{}',
                '{}', '[]', '{}', 't04-sign-v1', '1', '{}', 'config-hash', 'context-hash',
                now() + interval '1 day'
            )
            """,
            (TENANT,),
        )
        conn.commit()
    return dsn


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def test_tenant_scoped_identity_and_parent_fk(seeded_schema: str) -> None:
    """The same bare ID may exist per tenant, but a child cannot borrow another tenant's parent."""
    with psycopg.connect(seeded_schema) as conn:
        count = conn.execute("SELECT count(*) FROM causal_models WHERE model_id = 'shared-model-id'").fetchone()
        assert count is not None and count[0] == 2

        with pytest.raises(errors.ForeignKeyViolation):
            conn.execute(
                """
                INSERT INTO causal_model_versions (
                    tenant_id, model_version_id, model_id, version, status
                ) VALUES ('t04-no-parent', 'cross-tenant-version', 'shared-model-id', '1', 'draft')
                """
            )


def test_snapshot_is_database_immutable(seeded_schema: str) -> None:
    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.RaiseException, match="immutable"):
            conn.execute(
                "UPDATE causal_model_snapshots SET content_hash = 'changed' "
                "WHERE tenant_id = %s AND snapshot_id = 'snapshot-v1'",
                (TENANT,),
            )


def test_unbuilt_algorithm_keeps_config_hash_distinct_from_artifact_hash(seeded_schema: str) -> None:
    """0038: an unbuilt fixture must not forge an executable artifact hash."""
    with psycopg.connect(seeded_schema) as conn:
        conn.execute(
            """
            INSERT INTO reasoning_algorithms (algorithm_id, name)
            VALUES ('t05-unbuilt', 'T05 Unbuilt') ON CONFLICT DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO reasoning_algorithm_versions (
                algorithm_version_id, algorithm_id, version, contract_version,
                profile_version, profile_json, params_schema, handler,
                implementation_hash, algorithm_config_hash, algorithm_config_json, status
            ) VALUES (
                't05-unbuilt-v1', 't05-unbuilt', '1.0-fixture', 'fixture',
                'fixture/v1', '{}', '{}', 'tests.unbuilt',
                NULL, 'fixture-config-hash', '{"implementation_artifact":{"status":"not_built"}}', 'beta'
            )
            """
        )
        row = conn.execute(
            "SELECT implementation_hash, algorithm_config_hash FROM reasoning_algorithm_versions "
            "WHERE algorithm_version_id = 't05-unbuilt-v1'"
        ).fetchone()
        assert row == (None, "fixture-config-hash")
    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.RaiseException, match="immutable"):
            conn.execute(
                "DELETE FROM causal_model_snapshots WHERE tenant_id = %s AND snapshot_id = 'snapshot-v1'",
                (TENANT,),
            )


def test_compile_record_lifecycle_and_failure_without_version(seeded_schema: str) -> None:
    with psycopg.connect(seeded_schema) as conn:
        running = conn.execute(
            "SELECT status FROM blueprint_compile_records WHERE tenant_id = %s AND compile_id = 'compile-running'",
            (TENANT,),
        ).fetchone()
        assert running == ("running",)
        failed_versions = conn.execute(
            """
            SELECT count(*) FROM planning_blueprint_versions
            WHERE tenant_id = %s AND compile_record_id = 'compile-failed'
            """,
            (TENANT,),
        ).fetchone()
        assert failed_versions == (0,)


def test_only_one_current_compiled_version(seeded_schema: str) -> None:
    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.UniqueViolation, match="uq_planning_blueprint_current_compiled"):
            conn.execute(
                """
                INSERT INTO planning_blueprint_versions (
                    tenant_id, blueprint_version_id, blueprint_id, version, status,
                    compile_record_id, compiler_version, intent_signature
                ) VALUES (%s, 'blueprint-v3', 'blueprint-1', '3', 'compiled', 'compile-2', '1', '{}')
                """,
                (TENANT,),
            )


def test_cross_version_step_dependency_rejected(seeded_schema: str) -> None:
    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.ForeignKeyViolation, match="fk_blueprint_step_deps_to_step"):
            conn.execute(
                """
                INSERT INTO blueprint_step_deps (
                    tenant_id, dep_id, blueprint_version_id, from_step_id, to_step_id, dep_type
                ) VALUES (%s, 'bad-dep', 'blueprint-v1', 'step-v1', 'step-v2', 'sequential')
                """,
                (TENANT,),
            )


def test_cross_version_step_source_rejected(seeded_schema: str) -> None:
    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.ForeignKeyViolation, match="fk_blueprint_step_sources_model"):
            conn.execute(
                """
                INSERT INTO blueprint_step_sources (
                    tenant_id, step_source_id, blueprint_version_id, step_id,
                    source_model_ref_id, element_type, element_key, role
                ) VALUES (
                    %s, 'bad-source', 'blueprint-v1', 'step-v1',
                    'source-v2', 'node', 'production_output', 'primary'
                )
                """,
                (TENANT,),
            )


def test_causal_blueprint_source_snapshot_must_match_tenant_model_version_and_hash(seeded_schema: str) -> None:
    """A causal source pin cannot borrow another tenant's snapshot or alter its hash."""
    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.RaiseException, match="must match tenant"):
            conn.execute(
                """
                INSERT INTO blueprint_source_models (
                    tenant_id, source_ref_id, blueprint_version_id, model_type, model_id,
                    model_version, source_snapshot_id, source_content_hash, model_role
                ) VALUES (
                    %s, 'source-cross-tenant', 'blueprint-v1', 'causal', 'shared-model-id',
                    '1.0', 'snapshot-other', 'other-snapshot-hash', 'supporting_model'
                )
                """,
                (TENANT,),
            )

    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.RaiseException, match="must match tenant"):
            conn.execute(
                """
                INSERT INTO blueprint_source_models (
                    tenant_id, source_ref_id, blueprint_version_id, model_type, model_id,
                    model_version, source_snapshot_id, source_content_hash, model_role
                ) VALUES (
                    %s, 'source-bad-hash', 'blueprint-v1', 'causal', 'shared-model-id',
                    '1.0', 'snapshot-v1', 'different-hash', 'supporting_model'
                )
                """,
                (TENANT,),
            )


def test_reasoning_trace_idempotency_key_and_single_consumption(seeded_schema: str) -> None:
    with psycopg.connect(seeded_schema) as conn:
        conn.execute(
            """
            INSERT INTO reasoning_traces (
                tenant_id, trace_id, prepare_id, evaluation_input_hash,
                model_version_id, snapshot_id, observations_json, result_snapshot, status
            ) VALUES (%s, 'trace-1', 'prepare-1', 'input-hash-1',
                      'model-v1', 'snapshot-v1', '[]', '{}', 'complete')
            """,
            (TENANT,),
        )
        conn.commit()

    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO reasoning_traces (
                    tenant_id, trace_id, prepare_id, evaluation_input_hash,
                    model_version_id, snapshot_id, observations_json, result_snapshot, status
                ) VALUES (%s, 'trace-retry', 'prepare-1', 'input-hash-1',
                          'model-v1', 'snapshot-v1', '[]', '{}', 'complete')
                """,
                (TENANT,),
            )
    with psycopg.connect(seeded_schema) as conn:
        with pytest.raises(errors.UniqueViolation, match="uq_reasoning_traces_one_per_prepare"):
            conn.execute(
                """
                INSERT INTO reasoning_traces (
                    tenant_id, trace_id, prepare_id, evaluation_input_hash,
                    model_version_id, snapshot_id, observations_json, result_snapshot, status
                ) VALUES (%s, 'trace-different', 'prepare-1', 'input-hash-2',
                          'model-v1', 'snapshot-v1', '[]', '{}', 'complete')
                """,
                (TENANT,),
            )


async def test_rls_isolates_new_schema_and_rejects_mismatched_insert(
    seeded_schema: str, app_engine: AsyncEngine
) -> None:
    async with tenant_session(app_engine, TENANT) as session:
        causal_count = await session.execute(text("SELECT count(*) FROM causal_models"))
        compile_count = await session.execute(text("SELECT count(*) FROM blueprint_compile_records"))
        assert int(causal_count.scalar_one()) == 1
        assert int(compile_count.scalar_one()) == 4

    async with tenant_session(app_engine, OTHER_TENANT) as session:
        causal_count = await session.execute(text("SELECT count(*) FROM causal_model_versions"))
        compile_count = await session.execute(text("SELECT count(*) FROM blueprint_compile_records"))
        # OTHER_TENANT has its own identically named model version.  RLS must
        # expose that row, but not the first tenant's model/compile rows.
        assert int(causal_count.scalar_one()) == 1
        assert int(compile_count.scalar_one()) == 0

    with pytest.raises(Exception, match="row.level security"):
        async with tenant_session(app_engine, OTHER_TENANT) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO blueprint_compile_records (
                        tenant_id, compile_id, primary_model_type, primary_model_id,
                        primary_model_version, source_models_snapshot, source_model_hashes,
                        compiler_version, input_snapshot
                    ) VALUES (:tenant, 'rls-bad', 'causal', 'model', '1', '[]', '{}', '1', '{}')
                    """
                ),
                {"tenant": TENANT},
            )
