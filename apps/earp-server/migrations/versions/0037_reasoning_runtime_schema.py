"""Case A ReasoningContext and ReasoningTrace runtime persistence.

ReasoningContext is the durable Prepare/Evaluate bridge.  A prepare_id may produce
exactly one trace; the explicit evaluation-input key makes same-input retries
addressable while the one-trace constraint rejects a different input for the same
prepared context.

Revision ID: 0037_reasoning_runtime_schema
Revises: 0036_blueprint_registry_schema
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

revision: str = "0037_reasoning_runtime_schema"
down_revision: str = "0036_blueprint_registry_schema"
branch_labels: None = None
depends_on: None = None


TENANT_TABLES = ("reasoning_contexts", "reasoning_traces")


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        "USING (tenant_id = current_setting('earp.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('earp.tenant_id', true))"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO earp_app")


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")

    op.execute(
        """
        CREATE TABLE reasoning_contexts (
            tenant_id                  VARCHAR(64) NOT NULL,
            prepare_id                 VARCHAR(64) NOT NULL,
            model_version_id           VARCHAR(64) NOT NULL,
            snapshot_id                VARCHAR(64) NOT NULL,
            snapshot_hash              VARCHAR(64) NOT NULL,
            target_json                JSONB NOT NULL,
            time_window_json           JSONB NOT NULL,
            instance_snapshot          JSONB NOT NULL,
            evidence_requirements      JSONB NOT NULL,
            scope_meta                 JSONB NOT NULL,
            authz_scope_hash           VARCHAR(64),
            algorithm_version_id       VARCHAR(64) NOT NULL
                                       REFERENCES reasoning_algorithm_versions (algorithm_version_id),
            algorithm_profile_version VARCHAR(32) NOT NULL,
            algorithm_params_json      JSONB NOT NULL,
            algorithm_config_hash      VARCHAR(64) NOT NULL,
            context_hash               VARCHAR(64) NOT NULL,
            status                     VARCHAR(16) NOT NULL DEFAULT 'prepared'
                                       CHECK (status IN ('prepared','consumed','expired','cancelled')),
            prepared_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at                 TIMESTAMPTZ NOT NULL,
            CONSTRAINT pk_reasoning_contexts PRIMARY KEY (tenant_id, prepare_id),
            CONSTRAINT fk_reasoning_contexts_snapshot
                FOREIGN KEY (tenant_id, model_version_id, snapshot_id)
                REFERENCES causal_model_snapshots (tenant_id, model_version_id, snapshot_id),
            CONSTRAINT ck_reasoning_contexts_expiry CHECK (expires_at > prepared_at),
            CONSTRAINT uq_reasoning_contexts_trace_identity
                UNIQUE (tenant_id, prepare_id, model_version_id, snapshot_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE reasoning_traces (
            tenant_id             VARCHAR(64) NOT NULL,
            trace_id              VARCHAR(64) NOT NULL,
            prepare_id            VARCHAR(64) NOT NULL,
            evaluation_input_hash VARCHAR(64) NOT NULL,
            model_version_id      VARCHAR(64) NOT NULL,
            snapshot_id           VARCHAR(64) NOT NULL,
            observations_json     JSONB NOT NULL,
            evidence_items_json   JSONB NOT NULL DEFAULT '[]'::jsonb,
            result_snapshot       JSONB NOT NULL,
            status                VARCHAR(16) NOT NULL CHECK (status IN ('complete','partial','failed')),
            latency_ms            INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
            provenance_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_reasoning_traces PRIMARY KEY (tenant_id, trace_id),
            CONSTRAINT fk_reasoning_traces_context
                FOREIGN KEY (tenant_id, prepare_id, model_version_id, snapshot_id)
                REFERENCES reasoning_contexts
                    (tenant_id, prepare_id, model_version_id, snapshot_id),
            CONSTRAINT uq_reasoning_traces_evaluation_input
                UNIQUE (tenant_id, prepare_id, evaluation_input_hash),
            CONSTRAINT uq_reasoning_traces_one_per_prepare
                UNIQUE (tenant_id, prepare_id)
        )
        """
    )

    for table in TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute("DROP TABLE IF EXISTS reasoning_traces")
    op.execute("DROP TABLE IF EXISTS reasoning_contexts")
