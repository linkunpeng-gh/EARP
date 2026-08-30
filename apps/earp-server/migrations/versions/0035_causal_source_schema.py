"""Case A causal source model, immutable snapshot, and algorithm registry schema.

This is the first of three deliberately small T04 revisions.  Source/model tables
live here; Blueprint persistence is in 0036 and runtime reasoning state in 0037.
Every tenant-owned identity, unique constraint, and parent-child reference carries
tenant_id.  Algorithm registry rows are platform-global and therefore do not use
tenant RLS.

Revision ID: 0035_causal_source_schema
Revises: 0034_flow_runs_trace
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

revision: str = "0035_causal_source_schema"
down_revision: str = "0034_flow_runs_trace"
branch_labels: None = None
depends_on: None = None


TENANT_TABLES = (
    "causal_models",
    "causal_model_versions",
    "causal_nodes",
    "causal_edges",
    "causal_rules",
    "causal_data_bindings",
    "causal_capability_bindings",
    "causal_applicability",
    "causal_model_snapshots",
    "causal_snapshot_validation_runs",
)


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
        CREATE TABLE causal_models (
            tenant_id      VARCHAR(64) NOT NULL,
            model_id       VARCHAR(64) NOT NULL,
            data_domain_id VARCHAR(64) NOT NULL,
            name           VARCHAR(128) NOT NULL,
            description    TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_models PRIMARY KEY (tenant_id, model_id),
            CONSTRAINT uq_causal_models_domain_name UNIQUE (tenant_id, data_domain_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_model_versions (
            tenant_id             VARCHAR(64) NOT NULL,
            model_version_id      VARCHAR(64) NOT NULL,
            model_id              VARCHAR(64) NOT NULL,
            version               VARCHAR(32) NOT NULL,
            status                VARCHAR(16) NOT NULL
                                  CHECK (status IN ('draft','testing','published','deprecated')),
            dependency_resolution JSONB NOT NULL DEFAULT '{}'::jsonb,
            applicability         JSONB NOT NULL DEFAULT '{}'::jsonb,
            published_snapshot_id VARCHAR(64),
            owner                 VARCHAR(64),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at          TIMESTAMPTZ,
            CONSTRAINT pk_causal_model_versions PRIMARY KEY (tenant_id, model_version_id),
            CONSTRAINT fk_causal_model_versions_model
                FOREIGN KEY (tenant_id, model_id)
                REFERENCES causal_models (tenant_id, model_id),
            CONSTRAINT uq_causal_model_versions_model_version
                UNIQUE (tenant_id, model_id, version),
            CONSTRAINT uq_causal_model_versions_identity_model
                UNIQUE (tenant_id, model_version_id, model_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_nodes (
            tenant_id                  VARCHAR(64) NOT NULL,
            node_row_id                VARCHAR(64) NOT NULL,
            model_version_id           VARCHAR(64) NOT NULL,
            node_key                   VARCHAR(64) NOT NULL,
            node_seq                   INTEGER NOT NULL,
            entity_type_ref            VARCHAR(64) NOT NULL,
            entry_point                BOOLEAN NOT NULL DEFAULT false,
            entry_direction            VARCHAR(8)
                                       CHECK (entry_direction IS NULL OR entry_direction IN ('up','down')),
            entry_description          TEXT,
            aggregation_mode           VARCHAR(16) NOT NULL DEFAULT 'per_instance'
                                       CHECK (aggregation_mode IN ('per_instance','aggregate')),
            aggregation_operator       VARCHAR(16),
            aggregation_predicate      JSONB,
            aggregation_weight_ref     VARCHAR(64),
            observation_window         JSONB,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_nodes PRIMARY KEY (tenant_id, node_row_id),
            CONSTRAINT fk_causal_nodes_version
                FOREIGN KEY (tenant_id, model_version_id)
                REFERENCES causal_model_versions (tenant_id, model_version_id),
            CONSTRAINT uq_causal_nodes_version_key
                UNIQUE (tenant_id, model_version_id, node_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_edges (
            tenant_id        VARCHAR(64) NOT NULL,
            edge_row_id      VARCHAR(64) NOT NULL,
            edge_key         VARCHAR(64) NOT NULL,
            model_version_id VARCHAR(64) NOT NULL,
            source_node_key  VARCHAR(64) NOT NULL,
            target_node_key  VARCHAR(64) NOT NULL,
            relation_type_ref VARCHAR(64) NOT NULL,
            effect           VARCHAR(1) NOT NULL CHECK (effect IN ('+','-')),
            strength         DOUBLE PRECISION NOT NULL DEFAULT 0.5 CHECK (strength BETWEEN 0 AND 1),
            lag              VARCHAR(16),
            confidence       DOUBLE PRECISION NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_edges PRIMARY KEY (tenant_id, edge_row_id),
            CONSTRAINT fk_causal_edges_version
                FOREIGN KEY (tenant_id, model_version_id)
                REFERENCES causal_model_versions (tenant_id, model_version_id),
            CONSTRAINT fk_causal_edges_source_node
                FOREIGN KEY (tenant_id, model_version_id, source_node_key)
                REFERENCES causal_nodes (tenant_id, model_version_id, node_key),
            CONSTRAINT fk_causal_edges_target_node
                FOREIGN KEY (tenant_id, model_version_id, target_node_key)
                REFERENCES causal_nodes (tenant_id, model_version_id, node_key),
            CONSTRAINT uq_causal_edges_version_key
                UNIQUE (tenant_id, model_version_id, edge_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_rules (
            tenant_id        VARCHAR(64) NOT NULL,
            rule_row_id      VARCHAR(64) NOT NULL,
            rule_key         VARCHAR(64) NOT NULL,
            model_version_id VARCHAR(64) NOT NULL,
            node_key         VARCHAR(64) NOT NULL,
            rule_type        VARCHAR(16) NOT NULL
                             CHECK (rule_type IN ('predicate','threshold','direction_rule')),
            rule_spec        JSONB NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_rules PRIMARY KEY (tenant_id, rule_row_id),
            CONSTRAINT fk_causal_rules_node
                FOREIGN KEY (tenant_id, model_version_id, node_key)
                REFERENCES causal_nodes (tenant_id, model_version_id, node_key),
            CONSTRAINT uq_causal_rules_version_key
                UNIQUE (tenant_id, model_version_id, rule_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_data_bindings (
            tenant_id                  VARCHAR(64) NOT NULL,
            binding_row_id             VARCHAR(64) NOT NULL,
            model_version_id           VARCHAR(64) NOT NULL,
            node_key                   VARCHAR(64) NOT NULL,
            requirement_key            VARCHAR(128) NOT NULL,
            requirement_level          VARCHAR(16) NOT NULL DEFAULT 'required'
                                       CHECK (requirement_level IN ('required','optional')),
            metric_binding             JSONB,
            instance_binding_expr      JSONB,
            instance_key_field         VARCHAR(64),
            instance_observation       VARCHAR(64),
            output_mapping             JSONB,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_data_bindings PRIMARY KEY (tenant_id, binding_row_id),
            CONSTRAINT fk_causal_data_bindings_node
                FOREIGN KEY (tenant_id, model_version_id, node_key)
                REFERENCES causal_nodes (tenant_id, model_version_id, node_key),
            CONSTRAINT uq_causal_data_bindings_requirement
                UNIQUE (tenant_id, model_version_id, node_key, requirement_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_capability_bindings (
            tenant_id               VARCHAR(64) NOT NULL,
            cap_binding_row_id       VARCHAR(64) NOT NULL,
            model_version_id        VARCHAR(64) NOT NULL,
            node_key                VARCHAR(64) NOT NULL,
            requirement_key         VARCHAR(128) NOT NULL,
            capability_role         VARCHAR(16) NOT NULL
                                    CHECK (capability_role IN ('primary','supporting')),
            read_only_required      BOOLEAN NOT NULL DEFAULT true,
            capability_contract_ref VARCHAR(128) NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_capability_bindings PRIMARY KEY (tenant_id, cap_binding_row_id),
            CONSTRAINT fk_causal_capability_bindings_requirement
                FOREIGN KEY (tenant_id, model_version_id, node_key, requirement_key)
                REFERENCES causal_data_bindings
                    (tenant_id, model_version_id, node_key, requirement_key),
            CONSTRAINT uq_causal_capability_bindings_role
                UNIQUE (tenant_id, model_version_id, node_key, requirement_key, capability_role)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_applicability (
            tenant_id        VARCHAR(64) NOT NULL,
            app_id           VARCHAR(64) NOT NULL,
            model_version_id VARCHAR(64) NOT NULL,
            scope_type       VARCHAR(32) NOT NULL
                             CHECK (scope_type IN ('entity_instances','industries','tenant_scope')),
            scope_value      JSONB NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_applicability PRIMARY KEY (tenant_id, app_id),
            CONSTRAINT fk_causal_applicability_version
                FOREIGN KEY (tenant_id, model_version_id)
                REFERENCES causal_model_versions (tenant_id, model_version_id),
            CONSTRAINT uq_causal_applicability_scope
                UNIQUE (tenant_id, model_version_id, scope_type, app_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_model_snapshots (
            tenant_id             VARCHAR(64) NOT NULL,
            snapshot_id           VARCHAR(64) NOT NULL,
            model_version_id      VARCHAR(64) NOT NULL,
            content_hash          VARCHAR(64) NOT NULL,
            nodes_json            JSONB NOT NULL,
            edges_json            JSONB NOT NULL,
            rules_json            JSONB NOT NULL,
            requirements_json     JSONB NOT NULL,
            applicability_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            schema_version        VARCHAR(32) NOT NULL DEFAULT '1',
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_model_snapshots PRIMARY KEY (tenant_id, snapshot_id),
            CONSTRAINT fk_causal_model_snapshots_version
                FOREIGN KEY (tenant_id, model_version_id)
                REFERENCES causal_model_versions (tenant_id, model_version_id),
            CONSTRAINT uq_causal_model_snapshots_content
                UNIQUE (tenant_id, model_version_id, content_hash),
            CONSTRAINT uq_causal_model_snapshots_version_identity
                UNIQUE (tenant_id, model_version_id, snapshot_id)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE causal_model_versions
        ADD CONSTRAINT fk_causal_model_versions_published_snapshot
        FOREIGN KEY (tenant_id, model_version_id, published_snapshot_id)
        REFERENCES causal_model_snapshots (tenant_id, model_version_id, snapshot_id)
        DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        CREATE TABLE causal_snapshot_validation_runs (
            tenant_id    VARCHAR(64) NOT NULL,
            run_id       VARCHAR(64) NOT NULL,
            snapshot_id  VARCHAR(64) NOT NULL,
            result       VARCHAR(16) NOT NULL CHECK (result IN ('running','passed','failed')),
            detail       JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at  TIMESTAMPTZ,
            CONSTRAINT pk_causal_snapshot_validation_runs PRIMARY KEY (tenant_id, run_id),
            CONSTRAINT fk_causal_snapshot_validation_runs_snapshot
                FOREIGN KEY (tenant_id, snapshot_id)
                REFERENCES causal_model_snapshots (tenant_id, snapshot_id),
            CONSTRAINT uq_causal_snapshot_validation_runs_identity
                UNIQUE (tenant_id, snapshot_id, run_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE reasoning_algorithms (
            algorithm_id VARCHAR(32) PRIMARY KEY,
            name         VARCHAR(64) NOT NULL UNIQUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE reasoning_algorithm_versions (
            algorithm_version_id VARCHAR(64) PRIMARY KEY,
            algorithm_id         VARCHAR(32) NOT NULL REFERENCES reasoning_algorithms (algorithm_id),
            version              VARCHAR(32) NOT NULL,
            contract_version     VARCHAR(16) NOT NULL,
            profile_version      VARCHAR(32) NOT NULL,
            profile_json         JSONB NOT NULL,
            params_schema        JSONB NOT NULL,
            handler              VARCHAR(128) NOT NULL,
            implementation_hash  VARCHAR(64) NOT NULL,
            status               VARCHAR(16) NOT NULL CHECK (status IN ('active','beta','deprecated')),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_reasoning_algorithm_versions UNIQUE (algorithm_id, version)
        )
        """
    )
    op.execute("GRANT SELECT ON reasoning_algorithms, reasoning_algorithm_versions TO earp_app")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_causal_snapshot_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'causal model snapshots are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER causal_model_snapshots_immutable
        BEFORE UPDATE OR DELETE ON causal_model_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_causal_snapshot_mutation()
        """
    )

    for table in TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")

    op.execute("DROP TABLE IF EXISTS reasoning_algorithm_versions")
    op.execute("DROP TABLE IF EXISTS reasoning_algorithms")
    op.execute("DROP TABLE IF EXISTS causal_snapshot_validation_runs")
    op.execute(
        "ALTER TABLE causal_model_versions DROP CONSTRAINT IF EXISTS fk_causal_model_versions_published_snapshot"
    )
    op.execute("DROP TRIGGER IF EXISTS causal_model_snapshots_immutable ON causal_model_snapshots")
    op.execute("DROP FUNCTION IF EXISTS reject_causal_snapshot_mutation()")
    op.execute("DROP TABLE IF EXISTS causal_model_snapshots")
    op.execute("DROP TABLE IF EXISTS causal_applicability")
    op.execute("DROP TABLE IF EXISTS causal_capability_bindings")
    op.execute("DROP TABLE IF EXISTS causal_data_bindings")
    op.execute("DROP TABLE IF EXISTS causal_rules")
    op.execute("DROP TABLE IF EXISTS causal_edges")
    op.execute("DROP TABLE IF EXISTS causal_nodes")
    op.execute("DROP TABLE IF EXISTS causal_model_versions")
    op.execute("DROP TABLE IF EXISTS causal_models")
