"""Case A Planning Blueprint persistence and StepType registry schema.

All Blueprint aggregate children belong to a concrete BlueprintVersion.  Composite
tenant/version foreign keys make cross-tenant and cross-version references invalid
at the database boundary.

Revision ID: 0036_blueprint_registry_schema
Revises: 0035_causal_source_schema
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

revision: str = "0036_blueprint_registry_schema"
down_revision: str = "0035_causal_source_schema"
branch_labels: None = None
depends_on: None = None


TENANT_TABLES = (
    "blueprint_compile_records",
    "planning_blueprints",
    "planning_blueprint_versions",
    "blueprint_source_models",
    "blueprint_intents",
    "blueprint_constraints",
    "blueprint_output_contracts",
    "blueprint_goal_skeletons",
    "blueprint_steps",
    "blueprint_step_deps",
    "blueprint_step_sources",
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
        CREATE TABLE step_types (
            type_id    VARCHAR(32) PRIMARY KEY,
            type_name  VARCHAR(64) NOT NULL UNIQUE,
            is_core    BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE step_type_versions (
            step_type_version_id      VARCHAR(64) PRIMARY KEY,
            type_id                   VARCHAR(32) NOT NULL REFERENCES step_types (type_id),
            version                   VARCHAR(32) NOT NULL,
            handler_version           VARCHAR(32) NOT NULL,
            handler_hash              VARCHAR(64) NOT NULL,
            params_schema             JSONB NOT NULL DEFAULT '{}'::jsonb,
            semantic_contract_version VARCHAR(16) NOT NULL,
            status                    VARCHAR(16) NOT NULL CHECK (status IN ('active','deprecated')),
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_step_type_versions UNIQUE (type_id, version)
        )
        """
    )
    op.execute("GRANT SELECT ON step_types, step_type_versions TO earp_app")

    op.execute(
        """
        CREATE TABLE blueprint_compile_records (
            tenant_id              VARCHAR(64) NOT NULL,
            compile_id             VARCHAR(64) NOT NULL,
            primary_model_type     VARCHAR(16) NOT NULL
                                   CHECK (primary_model_type IN ('causal','decision','scenario')),
            primary_model_id       VARCHAR(64) NOT NULL,
            primary_model_version  VARCHAR(32) NOT NULL,
            source_models_snapshot JSONB NOT NULL,
            source_model_hashes    JSONB NOT NULL,
            compiler_version       VARCHAR(16) NOT NULL,
            compiler_config        JSONB NOT NULL DEFAULT '{}'::jsonb,
            input_snapshot         JSONB NOT NULL,
            validation_result      JSONB NOT NULL DEFAULT '{}'::jsonb,
            status                 VARCHAR(16) NOT NULL DEFAULT 'running'
                                   CHECK (status IN ('running','success','failed')),
            error_log              JSONB NOT NULL DEFAULT '[]'::jsonb,
            started_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at            TIMESTAMPTZ,
            CONSTRAINT pk_blueprint_compile_records PRIMARY KEY (tenant_id, compile_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE planning_blueprints (
            tenant_id          VARCHAR(64) NOT NULL,
            blueprint_id       VARCHAR(64) NOT NULL,
            primary_model_type VARCHAR(16) NOT NULL
                               CHECK (primary_model_type IN ('causal','decision','scenario')),
            primary_model_id   VARCHAR(64) NOT NULL,
            name               VARCHAR(128) NOT NULL,
            description        TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_planning_blueprints PRIMARY KEY (tenant_id, blueprint_id),
            CONSTRAINT uq_planning_blueprints_primary_model
                UNIQUE (tenant_id, primary_model_type, primary_model_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE planning_blueprint_versions (
            tenant_id              VARCHAR(64) NOT NULL,
            blueprint_version_id   VARCHAR(64) NOT NULL,
            blueprint_id           VARCHAR(64) NOT NULL,
            version                VARCHAR(32) NOT NULL,
            status                 VARCHAR(16) NOT NULL
                                   CHECK (status IN ('compiled','superseded','withdrawn')),
            compile_record_id      VARCHAR(64) NOT NULL,
            compiler_version       VARCHAR(16) NOT NULL,
            source_fingerprint     VARCHAR(64),
            intent_signature       JSONB NOT NULL,
            validation_contract    JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_contract        JSONB,
            fallback_policy        VARCHAR(16) NOT NULL DEFAULT 'allowed'
                                   CHECK (fallback_policy IN ('allowed','restricted','forbidden')),
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_planning_blueprint_versions PRIMARY KEY (tenant_id, blueprint_version_id),
            CONSTRAINT fk_planning_blueprint_versions_blueprint
                FOREIGN KEY (tenant_id, blueprint_id)
                REFERENCES planning_blueprints (tenant_id, blueprint_id),
            CONSTRAINT fk_planning_blueprint_versions_compile_record
                FOREIGN KEY (tenant_id, compile_record_id)
                REFERENCES blueprint_compile_records (tenant_id, compile_id),
            CONSTRAINT uq_planning_blueprint_versions_version
                UNIQUE (tenant_id, blueprint_id, version),
            CONSTRAINT uq_planning_blueprint_versions_aggregate_identity
                UNIQUE (tenant_id, blueprint_version_id, blueprint_id),
            CONSTRAINT uq_planning_blueprint_versions_source_fingerprint
                UNIQUE (tenant_id, blueprint_id, source_fingerprint)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_planning_blueprint_current_compiled
        ON planning_blueprint_versions (tenant_id, blueprint_id)
        WHERE status = 'compiled'
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_source_models (
            tenant_id             VARCHAR(64) NOT NULL,
            source_ref_id         VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            model_type            VARCHAR(16) NOT NULL
                                  CHECK (model_type IN ('causal','decision','scenario')),
            model_id              VARCHAR(64) NOT NULL,
            model_version         VARCHAR(32) NOT NULL,
            source_snapshot_id    VARCHAR(64) NOT NULL,
            source_content_hash   VARCHAR(64) NOT NULL,
            model_role            VARCHAR(16) NOT NULL
                                  CHECK (model_role IN ('primary_model','supporting_model')),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_blueprint_source_models PRIMARY KEY (tenant_id, source_ref_id),
            CONSTRAINT fk_blueprint_source_models_version
                FOREIGN KEY (tenant_id, blueprint_version_id)
                REFERENCES planning_blueprint_versions (tenant_id, blueprint_version_id),
            CONSTRAINT uq_blueprint_source_models_version_identity
                UNIQUE (tenant_id, blueprint_version_id, source_ref_id),
            CONSTRAINT uq_blueprint_source_models_snapshot_role
                UNIQUE (tenant_id, blueprint_version_id, source_snapshot_id, model_role)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_intents (
            tenant_id             VARCHAR(64) NOT NULL,
            intent_id             VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            entry_point           VARCHAR(128) NOT NULL,
            direction             VARCHAR(8) NOT NULL
                                  CHECK (direction IN ('up','down','change','neutral','any')),
            domain                VARCHAR(64) NOT NULL,
            business_objective    VARCHAR(16) NOT NULL
                                  CHECK (business_objective IN ('diagnose','predict','optimize','recommend')),
            CONSTRAINT pk_blueprint_intents PRIMARY KEY (tenant_id, intent_id),
            CONSTRAINT fk_blueprint_intents_version
                FOREIGN KEY (tenant_id, blueprint_version_id)
                REFERENCES planning_blueprint_versions (tenant_id, blueprint_version_id),
            CONSTRAINT uq_blueprint_intents_signature
                UNIQUE (
                    tenant_id, blueprint_version_id, entry_point, direction, domain, business_objective
                )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_constraints (
            tenant_id             VARCHAR(64) NOT NULL,
            constraint_id         VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            constraint_class      VARCHAR(16) NOT NULL CHECK (constraint_class IN ('hard','soft')),
            constraint_type       VARCHAR(32) NOT NULL CHECK (constraint_type IN (
                                      'mandatory_check','prohibition','mandatory_capability',
                                      'minimum_evidence','compliance_rule','priority',
                                      'scheduling_weight','cost_vs_speed','explain_level',
                                      'recommendation_count'
                                  )),
            constraint_value      JSONB NOT NULL,
            source_ref            TEXT,
            rationale             TEXT,
            CONSTRAINT pk_blueprint_constraints PRIMARY KEY (tenant_id, constraint_id),
            CONSTRAINT fk_blueprint_constraints_version
                FOREIGN KEY (tenant_id, blueprint_version_id)
                REFERENCES planning_blueprint_versions (tenant_id, blueprint_version_id),
            CONSTRAINT uq_blueprint_constraints_version_identity
                UNIQUE (tenant_id, blueprint_version_id, constraint_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_output_contracts (
            tenant_id             VARCHAR(64) NOT NULL,
            output_id             VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            output_type           VARCHAR(32) NOT NULL CHECK (output_type IN (
                                      'cause_ranking','report','recommendation','workflow_recommendation'
                                  )),
            output_schema         JSONB NOT NULL,
            CONSTRAINT pk_blueprint_output_contracts PRIMARY KEY (tenant_id, output_id),
            CONSTRAINT fk_blueprint_output_contracts_version
                FOREIGN KEY (tenant_id, blueprint_version_id)
                REFERENCES planning_blueprint_versions (tenant_id, blueprint_version_id),
            CONSTRAINT uq_blueprint_output_contracts_version_identity
                UNIQUE (tenant_id, blueprint_version_id, output_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_goal_skeletons (
            tenant_id             VARCHAR(64) NOT NULL,
            goal_skeleton_id      VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            objective             VARCHAR(16) NOT NULL
                                  CHECK (objective IN ('diagnose','predict','optimize','recommend')),
            goal_template         TEXT NOT NULL,
            required_bindings     JSONB NOT NULL DEFAULT '[]'::jsonb,
            optional_bindings     JSONB NOT NULL DEFAULT '[]'::jsonb,
            constraint_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,
            output_contract_ref   VARCHAR(64),
            CONSTRAINT pk_blueprint_goal_skeletons PRIMARY KEY (tenant_id, goal_skeleton_id),
            CONSTRAINT fk_blueprint_goal_skeletons_version
                FOREIGN KEY (tenant_id, blueprint_version_id)
                REFERENCES planning_blueprint_versions (tenant_id, blueprint_version_id),
            CONSTRAINT fk_blueprint_goal_skeletons_output_contract
                FOREIGN KEY (tenant_id, blueprint_version_id, output_contract_ref)
                REFERENCES blueprint_output_contracts (tenant_id, blueprint_version_id, output_id),
            CONSTRAINT uq_blueprint_goal_skeletons_version_identity
                UNIQUE (tenant_id, blueprint_version_id, goal_skeleton_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_steps (
            tenant_id             VARCHAR(64) NOT NULL,
            step_id               VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            step_seq              INTEGER NOT NULL,
            step_type_version_id  VARCHAR(64) NOT NULL REFERENCES step_type_versions (step_type_version_id),
            step_type             VARCHAR(32),
            step_name             VARCHAR(128) NOT NULL,
            params                JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_field          VARCHAR(128),
            CONSTRAINT pk_blueprint_steps PRIMARY KEY (tenant_id, step_id),
            CONSTRAINT fk_blueprint_steps_version
                FOREIGN KEY (tenant_id, blueprint_version_id)
                REFERENCES planning_blueprint_versions (tenant_id, blueprint_version_id),
            CONSTRAINT uq_blueprint_steps_version_identity
                UNIQUE (tenant_id, blueprint_version_id, step_id),
            CONSTRAINT uq_blueprint_steps_version_sequence
                UNIQUE (tenant_id, blueprint_version_id, step_seq)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_step_deps (
            tenant_id             VARCHAR(64) NOT NULL,
            dep_id                VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            from_step_id          VARCHAR(64) NOT NULL,
            to_step_id            VARCHAR(64) NOT NULL,
            dep_type              VARCHAR(16) NOT NULL
                                  CHECK (dep_type IN ('sequential','conditional','data_flow')),
            condition             JSONB,
            condition_eval_phase  VARCHAR(16)
                                  CHECK (condition_eval_phase IS NULL OR
                                         condition_eval_phase IN ('planning','execution')),
            CONSTRAINT pk_blueprint_step_deps PRIMARY KEY (tenant_id, dep_id),
            CONSTRAINT fk_blueprint_step_deps_from_step
                FOREIGN KEY (tenant_id, blueprint_version_id, from_step_id)
                REFERENCES blueprint_steps (tenant_id, blueprint_version_id, step_id),
            CONSTRAINT fk_blueprint_step_deps_to_step
                FOREIGN KEY (tenant_id, blueprint_version_id, to_step_id)
                REFERENCES blueprint_steps (tenant_id, blueprint_version_id, step_id),
            CONSTRAINT ck_blueprint_step_deps_not_self CHECK (from_step_id <> to_step_id),
            CONSTRAINT uq_blueprint_step_deps_edge
                UNIQUE (tenant_id, blueprint_version_id, from_step_id, to_step_id, dep_type)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE blueprint_step_sources (
            tenant_id             VARCHAR(64) NOT NULL,
            step_source_id        VARCHAR(64) NOT NULL,
            blueprint_version_id  VARCHAR(64) NOT NULL,
            step_id               VARCHAR(64) NOT NULL,
            source_model_ref_id   VARCHAR(64) NOT NULL,
            element_type          VARCHAR(16) NOT NULL
                                  CHECK (element_type IN ('node','relation','rule','requirement')),
            element_key           VARCHAR(128) NOT NULL,
            element_path          TEXT,
            role                  VARCHAR(16) NOT NULL CHECK (role IN ('primary','supporting','optional')),
            CONSTRAINT pk_blueprint_step_sources PRIMARY KEY (tenant_id, step_source_id),
            CONSTRAINT fk_blueprint_step_sources_step
                FOREIGN KEY (tenant_id, blueprint_version_id, step_id)
                REFERENCES blueprint_steps (tenant_id, blueprint_version_id, step_id),
            CONSTRAINT fk_blueprint_step_sources_model
                FOREIGN KEY (tenant_id, blueprint_version_id, source_model_ref_id)
                REFERENCES blueprint_source_models (tenant_id, blueprint_version_id, source_ref_id),
            CONSTRAINT uq_blueprint_step_sources_reference
                UNIQUE (
                    tenant_id, blueprint_version_id, step_id, source_model_ref_id,
                    element_type, element_key, role
                )
        )
        """
    )

    # ``blueprint_source_models`` is intentionally polymorphic so future
    # Decision/Scenario model tables can use the same Blueprint aggregate.
    # Case A is causal-only, however, and a bare ``source_snapshot_id`` would
    # otherwise allow a causal Blueprint to pin another tenant's snapshot (or
    # a snapshot belonging to a different model/version/hash).  PostgreSQL
    # cannot express that conditional, cross-table polymorphic reference as a
    # normal FK, so keep the tenant-scoped causal reference at the database
    # boundary with a constraint trigger.  T04 deliberately does not invent
    # Decision/Scenario tables; their migrations must extend this guard before
    # enabling their respective model types.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_causal_blueprint_source_model()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.model_type = 'causal' AND NOT EXISTS (
                SELECT 1
                FROM causal_model_snapshots AS snapshot
                JOIN causal_model_versions AS model_version
                  ON model_version.tenant_id = snapshot.tenant_id
                 AND model_version.model_version_id = snapshot.model_version_id
                WHERE snapshot.tenant_id = NEW.tenant_id
                  AND snapshot.snapshot_id = NEW.source_snapshot_id
                  AND snapshot.content_hash = NEW.source_content_hash
                  AND model_version.model_id = NEW.model_id
                  AND model_version.version = NEW.model_version
            ) THEN
                RAISE EXCEPTION
                    'causal Blueprint source snapshot must match tenant, model, version, and content hash';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER blueprint_source_models_causal_snapshot_guard
        BEFORE INSERT OR UPDATE ON blueprint_source_models
        FOR EACH ROW EXECUTE FUNCTION validate_causal_blueprint_source_model()
        """
    )

    for table in TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")

    op.execute("DROP TRIGGER IF EXISTS blueprint_source_models_causal_snapshot_guard ON blueprint_source_models")
    op.execute("DROP FUNCTION IF EXISTS validate_causal_blueprint_source_model()")
    op.execute("DROP TABLE IF EXISTS blueprint_step_sources")
    op.execute("DROP TABLE IF EXISTS blueprint_step_deps")
    op.execute("DROP TABLE IF EXISTS blueprint_steps")
    op.execute("DROP TABLE IF EXISTS blueprint_goal_skeletons")
    op.execute("DROP TABLE IF EXISTS blueprint_output_contracts")
    op.execute("DROP TABLE IF EXISTS blueprint_constraints")
    op.execute("DROP TABLE IF EXISTS blueprint_intents")
    op.execute("DROP TABLE IF EXISTS blueprint_source_models")
    op.execute("DROP TABLE IF EXISTS planning_blueprint_versions")
    op.execute("DROP TABLE IF EXISTS planning_blueprints")
    op.execute("DROP TABLE IF EXISTS blueprint_compile_records")
    op.execute("DROP TABLE IF EXISTS step_type_versions")
    op.execute("DROP TABLE IF EXISTS step_types")
