"""N01A causal model governance, candidate artifacts, activation and outbox.

This revision extends the Case A source/Blueprint schema in place.  Legacy
``testing`` fixture rows remain readable and keep their original semantics;
the stricter Artifact and draft-write guards apply to rows explicitly created
through the N01A production path.

Revision ID: 0040_n01_causal_model_management
Revises: 0039_ctx_profile_pin
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op

revision: str = "0040_n01_causal_model_management"
down_revision: str = "0039_ctx_profile_pin"
branch_labels: None = None
depends_on: None = None


NEW_TENANT_TABLES = (
    "causal_model_reviews",
    "causal_model_validation_runs",
    "blueprint_capability_requirements",
    "catalog_change_requests",
    "catalog_fulfillment_attempts",
    "idempotency_records",
    "outbox_events",
    "outbox_deliveries",
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

    # Logical model identity and its sole runtime active pointer.
    op.execute(
        """
        ALTER TABLE causal_models
          ADD COLUMN diagnostic_target_signature VARCHAR(64),
          ADD COLUMN active_model_version_id VARCHAR(64),
          ADD COLUMN active_snapshot_id VARCHAR(64),
          ADD COLUMN revision INTEGER NOT NULL DEFAULT 1,
          ADD CONSTRAINT ck_causal_models_active_pointer_pair CHECK (
            (active_model_version_id IS NULL AND active_snapshot_id IS NULL) OR
            (active_model_version_id IS NOT NULL AND active_snapshot_id IS NOT NULL)
          ),
          ADD CONSTRAINT ck_causal_models_revision_positive CHECK (revision > 0)
        """
    )
    op.execute(
        """
        ALTER TABLE causal_model_versions
          DROP CONSTRAINT causal_model_versions_status_check,
          ADD CONSTRAINT causal_model_versions_status_check CHECK (
            status IN ('draft','in_review','published','superseded','archived','testing','deprecated')
          ),
          ADD COLUMN diagnostic_target JSONB,
          ADD COLUMN diagnostic_target_signature VARCHAR(64),
          ADD COLUMN revision INTEGER NOT NULL DEFAULT 1,
          ADD COLUMN created_by VARCHAR(64),
          ADD COLUMN updated_by VARCHAR(64),
          ADD COLUMN submitted_at TIMESTAMPTZ,
          ADD COLUMN submitted_by VARCHAR(64),
          ADD COLUMN reviewed_at TIMESTAMPTZ,
          ADD COLUMN reviewed_by VARCHAR(64),
          ADD COLUMN derived_from_model_version_id VARCHAR(64),
          ADD COLUMN legacy_fixture BOOLEAN NOT NULL DEFAULT false,
          ADD CONSTRAINT ck_causal_model_versions_revision_positive CHECK (revision > 0),
          ADD CONSTRAINT fk_causal_model_versions_derived_from
            FOREIGN KEY (tenant_id, derived_from_model_version_id)
            REFERENCES causal_model_versions (tenant_id, model_version_id)
        """
    )
    op.execute(
        """
        ALTER TABLE causal_models
          ADD CONSTRAINT fk_causal_models_active_version
            FOREIGN KEY (tenant_id, active_model_version_id, model_id)
            REFERENCES causal_model_versions (tenant_id, model_version_id, model_id)
            DEFERRABLE INITIALLY DEFERRED,
          ADD CONSTRAINT fk_causal_models_active_snapshot
            FOREIGN KEY (tenant_id, active_model_version_id, active_snapshot_id)
            REFERENCES causal_model_snapshots (tenant_id, model_version_id, snapshot_id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )

    # Structured CatalogRefs coexist with the frozen Case A scalar fixture
    # projection.  N01A services write the structured columns exclusively.
    op.execute(
        """
        ALTER TABLE causal_nodes
          ADD COLUMN entity_type_catalog_ref JSONB,
          ADD COLUMN observability VARCHAR(32) NOT NULL DEFAULT 'observable',
          ADD COLUMN business_name VARCHAR(128),
          ADD COLUMN notes TEXT,
          ADD CONSTRAINT ck_causal_nodes_observability CHECK (
            observability IN ('observable','indirectly_observable','latent_hypothesis')
          )
        """
    )
    op.execute("ALTER TABLE causal_edges ALTER COLUMN strength TYPE NUMERIC(38,18) USING strength::numeric")
    op.execute("ALTER TABLE causal_edges ALTER COLUMN confidence TYPE NUMERIC(38,18) USING confidence::numeric")
    op.execute("ALTER TABLE causal_edges ADD COLUMN relation_type_catalog_ref JSONB")
    op.execute("ALTER TABLE causal_rules ALTER COLUMN node_key DROP NOT NULL")
    op.execute("ALTER TABLE causal_rules ADD COLUMN rule_schema_ref JSONB, ADD COLUMN rationale TEXT")
    op.execute(
        """
        ALTER TABLE causal_data_bindings
          ADD COLUMN metric_ref JSONB,
          ADD COLUMN unit_ref JSONB,
          ADD COLUMN aggregation_ref JSONB,
          ADD COLUMN time_window_ref JSONB,
          ADD COLUMN binding_template_ref JSONB,
          ADD COLUMN binding_params JSONB,
          ADD COLUMN business_description TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE causal_capability_bindings
          DROP CONSTRAINT uq_causal_capability_bindings_role,
          ADD COLUMN capability_contract_catalog_ref JSONB,
          ADD CONSTRAINT uq_causal_capability_bindings_contract UNIQUE
            (tenant_id, model_version_id, node_key, requirement_key,
             capability_role, capability_contract_ref)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_causal_capability_bindings_primary
        ON causal_capability_bindings (tenant_id, model_version_id, node_key, requirement_key)
        WHERE capability_role = 'primary'
        """
    )

    op.execute(
        """
        ALTER TABLE causal_model_snapshots
          ADD COLUMN canonical_payload JSONB,
          ADD COLUMN canonicalizer_version VARCHAR(32),
          ADD COLUMN diagnostic_target JSONB,
          ADD COLUMN catalog_resolutions JSONB NOT NULL DEFAULT '[]'::jsonb,
          ADD COLUMN semantic_schema_versions JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )

    # Append-only governance history and draft validation history.
    op.execute(
        """
        CREATE TABLE causal_model_reviews (
            tenant_id       VARCHAR(64) NOT NULL,
            review_id       VARCHAR(64) NOT NULL,
            model_id        VARCHAR(64) NOT NULL,
            model_version_id VARCHAR(64) NOT NULL,
            action          VARCHAR(24) NOT NULL CHECK (
              action IN ('submit','reject','publish','archive')
            ),
            decision        VARCHAR(24) NOT NULL,
            reason          TEXT,
            actor_id        VARCHAR(64) NOT NULL,
            role_id         VARCHAR(64) NOT NULL,
            policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_model_reviews PRIMARY KEY (tenant_id, review_id),
            CONSTRAINT fk_causal_model_reviews_version FOREIGN KEY
              (tenant_id, model_version_id, model_id)
              REFERENCES causal_model_versions (tenant_id, model_version_id, model_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE causal_model_validation_runs (
            tenant_id       VARCHAR(64) NOT NULL,
            validation_run_id VARCHAR(64) NOT NULL,
            model_id        VARCHAR(64) NOT NULL,
            model_version_id VARCHAR(64) NOT NULL,
            draft_revision  INTEGER NOT NULL,
            input_hash      VARCHAR(64) NOT NULL,
            validator_version VARCHAR(32) NOT NULL,
            mode            VARCHAR(16) NOT NULL CHECK (mode IN ('incremental','full','final')),
            result          VARCHAR(16) NOT NULL CHECK (result IN ('passed','failed')),
            issues          JSONB NOT NULL DEFAULT '[]'::jsonb,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_causal_model_validation_runs PRIMARY KEY (tenant_id, validation_run_id),
            CONSTRAINT fk_causal_model_validation_runs_version FOREIGN KEY
              (tenant_id, model_version_id, model_id)
              REFERENCES causal_model_versions (tenant_id, model_version_id, model_id),
            CONSTRAINT ck_causal_model_validation_hash CHECK (input_hash ~ '^[0-9a-f]{64}$')
        )
        """
    )

    op.execute(
        """
        CREATE TABLE blueprint_capability_requirements (
            tenant_id          VARCHAR(64) NOT NULL,
            capability_requirement_id VARCHAR(64) NOT NULL,
            blueprint_version_id VARCHAR(64) NOT NULL,
            requirement_key    VARCHAR(128) NOT NULL,
            step_key           VARCHAR(64),
            contract_ref       JSONB NOT NULL,
            requirement_schema_version VARCHAR(32) NOT NULL,
            required           BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT pk_blueprint_capability_requirements PRIMARY KEY
              (tenant_id, capability_requirement_id),
            CONSTRAINT fk_blueprint_capability_requirements_version FOREIGN KEY
              (tenant_id, blueprint_version_id)
              REFERENCES planning_blueprint_versions (tenant_id, blueprint_version_id),
            CONSTRAINT uq_blueprint_capability_requirements_key UNIQUE
              (tenant_id, blueprint_version_id, requirement_key)
        )
        """
    )

    # Candidate Artifact holder.  n01a_attempt separates the production N01A
    # contract from historical Case A compiler rows, which remain fixtures.
    op.execute(
        """
        ALTER TABLE blueprint_compile_records
          ADD COLUMN model_version_id VARCHAR(64),
          ADD COLUMN snapshot_id VARCHAR(64),
          ADD COLUMN compiled_artifact_json JSONB,
          ADD COLUMN compiled_artifact_hash VARCHAR(64),
          ADD COLUMN artifact_schema_version VARCHAR(32),
          ADD COLUMN retry_of_compile_id VARCHAR(64),
          ADD COLUMN requested_by VARCHAR(64),
          ADD COLUMN n01a_attempt BOOLEAN NOT NULL DEFAULT false,
          ADD CONSTRAINT fk_blueprint_compile_records_version FOREIGN KEY
            (tenant_id, model_version_id)
            REFERENCES causal_model_versions (tenant_id, model_version_id),
          ADD CONSTRAINT fk_blueprint_compile_records_snapshot FOREIGN KEY
            (tenant_id, model_version_id, snapshot_id)
            REFERENCES causal_model_snapshots (tenant_id, model_version_id, snapshot_id),
          ADD CONSTRAINT fk_blueprint_compile_records_retry FOREIGN KEY
            (tenant_id, retry_of_compile_id)
            REFERENCES blueprint_compile_records (tenant_id, compile_id),
          ADD CONSTRAINT ck_blueprint_compile_records_artifact_hash CHECK (
            compiled_artifact_hash IS NULL OR compiled_artifact_hash ~ '^[0-9a-f]{64}$'
          ),
          ADD CONSTRAINT ck_blueprint_compile_records_n01a_artifact CHECK (
            NOT n01a_attempt OR
            (status = 'success' AND compiled_artifact_json IS NOT NULL
              AND compiled_artifact_hash IS NOT NULL AND artifact_schema_version IS NOT NULL) OR
            (status IN ('running','failed') AND compiled_artifact_json IS NULL
              AND compiled_artifact_hash IS NULL AND artifact_schema_version IS NULL)
          )
        """
    )
    op.execute(
        """
        ALTER TABLE planning_blueprint_versions
          ADD COLUMN compiled_artifact_hash VARCHAR(64),
          ADD COLUMN artifact_schema_version VARCHAR(32),
          ADD COLUMN n01a_activation BOOLEAN NOT NULL DEFAULT false,
          ADD CONSTRAINT ck_planning_blueprint_versions_n01a_artifact CHECK (
            NOT n01a_activation OR
            (compiled_artifact_hash IS NOT NULL AND artifact_schema_version IS NOT NULL)
          ),
          ADD CONSTRAINT ck_planning_blueprint_versions_artifact_hash CHECK (
            compiled_artifact_hash IS NULL OR compiled_artifact_hash ~ '^[0-9a-f]{64}$'
          )
        """
    )
    op.execute(
        """
        ALTER TABLE blueprint_source_models
          ADD COLUMN source_stable_key VARCHAR(64),
          ADD CONSTRAINT uq_blueprint_source_models_stable_key UNIQUE
            (tenant_id, blueprint_version_id, source_stable_key);
        ALTER TABLE blueprint_intents
          ADD COLUMN intent_stable_key VARCHAR(64),
          ADD CONSTRAINT uq_blueprint_intents_stable_key UNIQUE
            (tenant_id, blueprint_version_id, intent_stable_key);
        ALTER TABLE blueprint_constraints
          ADD COLUMN constraint_stable_key VARCHAR(64),
          ADD CONSTRAINT uq_blueprint_constraints_stable_key UNIQUE
            (tenant_id, blueprint_version_id, constraint_stable_key);
        ALTER TABLE blueprint_output_contracts
          ADD COLUMN output_stable_key VARCHAR(64),
          ADD CONSTRAINT uq_blueprint_output_contracts_stable_key UNIQUE
            (tenant_id, blueprint_version_id, output_stable_key);
        ALTER TABLE blueprint_goal_skeletons
          ADD COLUMN goal_skeleton_stable_key VARCHAR(64),
          ADD CONSTRAINT uq_blueprint_goal_skeletons_stable_key UNIQUE
            (tenant_id, blueprint_version_id, goal_skeleton_stable_key);
        ALTER TABLE blueprint_steps
          ADD COLUMN step_stable_key VARCHAR(64),
          ADD CONSTRAINT uq_blueprint_steps_stable_key UNIQUE
            (tenant_id, blueprint_version_id, step_stable_key)
        """
    )

    # Catalog requests never write catalog tables directly.  Fulfillment
    # attempts preserve retry/error lineage without storing credentials or
    # physical provider data.
    op.execute(
        """
        CREATE TABLE catalog_change_requests (
            tenant_id       VARCHAR(64) NOT NULL,
            request_id      VARCHAR(64) NOT NULL,
            request_type    VARCHAR(32) NOT NULL CHECK (request_type IN (
              'data_domain','entity_type','relation_type','metric','unit','aggregation',
              'time_window_schema','binding_template','capability_contract','rule_schema'
            )),
            target_data_domain_ref JSONB NOT NULL,
            rationale       TEXT NOT NULL,
            proposed_definition JSONB NOT NULL,
            status          VARCHAR(40) NOT NULL CHECK (status IN (
              'draft','submitted','approved_pending_fulfillment','fulfilled',
              'rejected','cancelled','fulfillment_failed'
            )),
            requester_id    VARCHAR(64) NOT NULL,
            revision        INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            decision_reason TEXT,
            decided_by      VARCHAR(64),
            resolved_ref    JSONB,
            fulfillment_error JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_change_requests PRIMARY KEY (tenant_id, request_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE catalog_fulfillment_attempts (
            tenant_id       VARCHAR(64) NOT NULL,
            attempt_id      VARCHAR(64) NOT NULL,
            request_id      VARCHAR(64) NOT NULL,
            attempt_no      INTEGER NOT NULL CHECK (attempt_no > 0),
            status          VARCHAR(16) NOT NULL CHECK (status IN ('pending','success','failed')),
            requested_by    VARCHAR(64) NOT NULL,
            resolved_ref    JSONB,
            sanitized_error JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at     TIMESTAMPTZ,
            CONSTRAINT pk_catalog_fulfillment_attempts PRIMARY KEY (tenant_id, attempt_id),
            CONSTRAINT fk_catalog_fulfillment_attempts_request FOREIGN KEY
              (tenant_id, request_id)
              REFERENCES catalog_change_requests (tenant_id, request_id),
            CONSTRAINT uq_catalog_fulfillment_attempt_no UNIQUE (tenant_id, request_id, attempt_no)
        )
        """
    )

    # Generic command idempotency and minimal relational outbox.
    op.execute(
        """
        CREATE TABLE idempotency_records (
            tenant_id       VARCHAR(64) NOT NULL,
            actor_id        VARCHAR(64) NOT NULL,
            operation       VARCHAR(96) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            request_hash    VARCHAR(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            response_status INTEGER NOT NULL,
            response_body   JSONB NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_idempotency_records PRIMARY KEY
              (tenant_id, actor_id, operation, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE outbox_events (
            tenant_id       VARCHAR(64) NOT NULL,
            event_id        VARCHAR(64) NOT NULL,
            event_type      VARCHAR(96) NOT NULL,
            aggregate_type  VARCHAR(48) NOT NULL,
            aggregate_id    VARCHAR(64) NOT NULL,
            payload         JSONB NOT NULL,
            correlation_id  VARCHAR(128) NOT NULL,
            idempotency_key VARCHAR(128),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_outbox_events PRIMARY KEY (tenant_id, event_id),
            CONSTRAINT uq_outbox_event_idempotency UNIQUE
              (tenant_id, event_type, aggregate_id, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE outbox_deliveries (
            tenant_id       VARCHAR(64) NOT NULL,
            delivery_id     VARCHAR(64) NOT NULL,
            event_id        VARCHAR(64) NOT NULL,
            destination     VARCHAR(96) NOT NULL,
            status          VARCHAR(24) NOT NULL DEFAULT 'pending_delivery' CHECK (status IN (
              'pending_delivery','queued','delivered','retrying','dead_letter'
            )),
            attempt_count   INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_error      JSONB,
            lease_owner     VARCHAR(128),
            lease_expires_at TIMESTAMPTZ,
            next_attempt_at TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_outbox_deliveries PRIMARY KEY (tenant_id, delivery_id),
            CONSTRAINT fk_outbox_deliveries_event FOREIGN KEY (tenant_id, event_id)
              REFERENCES outbox_events (tenant_id, event_id),
            CONSTRAINT uq_outbox_delivery_destination UNIQUE (tenant_id, event_id, destination)
        )
        """
    )

    # Database guards protect invariants from future routes and ad-hoc scripts.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_n01a_model_signature()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE expected_signature VARCHAR(64);
        BEGIN
          IF TG_TABLE_NAME = 'causal_models' THEN
            IF TG_OP = 'UPDATE' AND OLD.diagnostic_target_signature IS NOT NULL
               AND NEW.diagnostic_target_signature IS DISTINCT FROM OLD.diagnostic_target_signature THEN
              RAISE EXCEPTION 'causal model diagnostic target signature is immutable';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.diagnostic_target_signature IS NOT NULL THEN
            SELECT diagnostic_target_signature INTO expected_signature
              FROM causal_models WHERE tenant_id = NEW.tenant_id AND model_id = NEW.model_id;
            IF expected_signature IS NULL OR expected_signature <> NEW.diagnostic_target_signature THEN
              RAISE EXCEPTION 'causal model version diagnostic target signature mismatch';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER causal_models_signature_guard BEFORE UPDATE ON causal_models "
        "FOR EACH ROW EXECUTE FUNCTION guard_n01a_model_signature()"
    )
    op.execute(
        "CREATE TRIGGER causal_model_versions_signature_guard BEFORE INSERT OR UPDATE ON causal_model_versions "
        "FOR EACH ROW EXECUTE FUNCTION guard_n01a_model_signature()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_n01a_draft_child_write()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE version_status VARCHAR(16); target_signature VARCHAR(64); selected_version VARCHAR(64);
        BEGIN
          selected_version := COALESCE(NEW.model_version_id, OLD.model_version_id);
          SELECT status, diagnostic_target_signature INTO version_status, target_signature
            FROM causal_model_versions
           WHERE tenant_id = COALESCE(NEW.tenant_id, OLD.tenant_id)
             AND model_version_id = selected_version;
          IF target_signature IS NOT NULL AND version_status <> 'draft' THEN
            RAISE EXCEPTION 'N01A causal model children are writable only in draft state';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    for table in (
        "causal_nodes",
        "causal_edges",
        "causal_rules",
        "causal_data_bindings",
        "causal_capability_bindings",
        "causal_applicability",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_n01a_draft_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION guard_n01a_draft_child_write()"
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_n01a_compile_attempt()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_status VARCHAR(16);
        BEGIN
          IF TG_OP = 'INSERT' AND NEW.n01a_attempt AND NEW.status <> 'running' THEN
            RAISE EXCEPTION 'N01A compile attempt must start running';
          END IF;
          IF TG_OP = 'INSERT' AND NEW.retry_of_compile_id IS NOT NULL THEN
            SELECT status INTO parent_status FROM blueprint_compile_records
             WHERE tenant_id = NEW.tenant_id AND compile_id = NEW.retry_of_compile_id;
            IF parent_status IS DISTINCT FROM 'failed' THEN
              RAISE EXCEPTION 'retry parent must be a failed compile attempt';
            END IF;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.n01a_attempt THEN
            IF OLD.status IN ('success','failed') THEN
              RAISE EXCEPTION 'terminal N01A compile attempts are immutable';
            END IF;
            IF NEW.status NOT IN ('running','success','failed') THEN
              RAISE EXCEPTION 'invalid N01A compile transition';
            END IF;
            IF OLD.compiled_artifact_json IS NOT NULL OR OLD.compiled_artifact_hash IS NOT NULL
               OR OLD.artifact_schema_version IS NOT NULL THEN
              RAISE EXCEPTION 'N01A candidate artifact is immutable';
            END IF;
          END IF;
          IF TG_OP = 'DELETE' AND OLD.n01a_attempt THEN
            RAISE EXCEPTION 'N01A compile attempts are append-only';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER blueprint_compile_records_n01a_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON blueprint_compile_records "
        "FOR EACH ROW EXECUTE FUNCTION guard_n01a_compile_attempt()"
    )

    for table in NEW_TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM blueprint_compile_records WHERE n01a_attempt)
             OR EXISTS (SELECT 1 FROM planning_blueprint_versions WHERE n01a_activation)
             OR EXISTS (SELECT 1 FROM catalog_change_requests)
          THEN RAISE EXCEPTION 'cannot downgrade 0040 while N01A production data exists';
          END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS blueprint_compile_records_n01a_guard ON blueprint_compile_records")
    op.execute("DROP FUNCTION IF EXISTS guard_n01a_compile_attempt()")
    for table in (
        "causal_nodes",
        "causal_edges",
        "causal_rules",
        "causal_data_bindings",
        "causal_capability_bindings",
        "causal_applicability",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_n01a_draft_guard ON {table}")
    op.execute("DROP FUNCTION IF EXISTS guard_n01a_draft_child_write()")
    op.execute("DROP TRIGGER IF EXISTS causal_model_versions_signature_guard ON causal_model_versions")
    op.execute("DROP TRIGGER IF EXISTS causal_models_signature_guard ON causal_models")
    op.execute("DROP FUNCTION IF EXISTS guard_n01a_model_signature()")

    for table in reversed(NEW_TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")

    op.execute("ALTER TABLE planning_blueprint_versions DROP CONSTRAINT ck_planning_blueprint_versions_artifact_hash")
    op.execute("ALTER TABLE planning_blueprint_versions DROP CONSTRAINT ck_planning_blueprint_versions_n01a_artifact")
    op.execute(
        "ALTER TABLE planning_blueprint_versions DROP COLUMN n01a_activation, "
        "DROP COLUMN artifact_schema_version, DROP COLUMN compiled_artifact_hash"
    )
    op.execute(
        """
        ALTER TABLE blueprint_steps DROP CONSTRAINT uq_blueprint_steps_stable_key,
          DROP COLUMN step_stable_key;
        ALTER TABLE blueprint_goal_skeletons DROP CONSTRAINT uq_blueprint_goal_skeletons_stable_key,
          DROP COLUMN goal_skeleton_stable_key;
        ALTER TABLE blueprint_output_contracts DROP CONSTRAINT uq_blueprint_output_contracts_stable_key,
          DROP COLUMN output_stable_key;
        ALTER TABLE blueprint_constraints DROP CONSTRAINT uq_blueprint_constraints_stable_key,
          DROP COLUMN constraint_stable_key;
        ALTER TABLE blueprint_intents DROP CONSTRAINT uq_blueprint_intents_stable_key,
          DROP COLUMN intent_stable_key;
        ALTER TABLE blueprint_source_models DROP CONSTRAINT uq_blueprint_source_models_stable_key,
          DROP COLUMN source_stable_key
        """
    )
    op.execute("ALTER TABLE blueprint_compile_records DROP CONSTRAINT ck_blueprint_compile_records_n01a_artifact")
    op.execute("ALTER TABLE blueprint_compile_records DROP CONSTRAINT ck_blueprint_compile_records_artifact_hash")
    op.execute("ALTER TABLE blueprint_compile_records DROP CONSTRAINT fk_blueprint_compile_records_retry")
    op.execute("ALTER TABLE blueprint_compile_records DROP CONSTRAINT fk_blueprint_compile_records_snapshot")
    op.execute("ALTER TABLE blueprint_compile_records DROP CONSTRAINT fk_blueprint_compile_records_version")
    op.execute(
        """
        ALTER TABLE blueprint_compile_records
          DROP COLUMN n01a_attempt, DROP COLUMN requested_by, DROP COLUMN retry_of_compile_id,
          DROP COLUMN artifact_schema_version, DROP COLUMN compiled_artifact_hash,
          DROP COLUMN compiled_artifact_json, DROP COLUMN snapshot_id, DROP COLUMN model_version_id
        """
    )
    op.execute(
        """
        ALTER TABLE causal_model_snapshots
          DROP COLUMN semantic_schema_versions, DROP COLUMN catalog_resolutions,
          DROP COLUMN diagnostic_target, DROP COLUMN canonicalizer_version, DROP COLUMN canonical_payload
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_causal_capability_bindings_primary")
    op.execute("ALTER TABLE causal_capability_bindings DROP CONSTRAINT uq_causal_capability_bindings_contract")
    op.execute("ALTER TABLE causal_capability_bindings DROP COLUMN capability_contract_catalog_ref")
    op.execute(
        "ALTER TABLE causal_capability_bindings ADD CONSTRAINT uq_causal_capability_bindings_role UNIQUE "
        "(tenant_id, model_version_id, node_key, requirement_key, capability_role)"
    )
    op.execute(
        """
        ALTER TABLE causal_data_bindings
          DROP COLUMN business_description, DROP COLUMN binding_params, DROP COLUMN binding_template_ref,
          DROP COLUMN time_window_ref, DROP COLUMN aggregation_ref, DROP COLUMN unit_ref, DROP COLUMN metric_ref
        """
    )
    op.execute("ALTER TABLE causal_rules DROP COLUMN rationale, DROP COLUMN rule_schema_ref")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM causal_rules WHERE node_key IS NULL) THEN "
        "RAISE EXCEPTION 'cannot restore causal_rules.node_key NOT NULL'; END IF; END $$"
    )
    op.execute("ALTER TABLE causal_rules ALTER COLUMN node_key SET NOT NULL")
    op.execute("ALTER TABLE causal_edges DROP COLUMN relation_type_catalog_ref")
    op.execute("ALTER TABLE causal_edges ALTER COLUMN strength TYPE DOUBLE PRECISION USING strength::double precision")
    op.execute(
        "ALTER TABLE causal_edges ALTER COLUMN confidence TYPE DOUBLE PRECISION "
        "USING confidence::double precision"
    )
    op.execute(
        """
        ALTER TABLE causal_nodes
          DROP CONSTRAINT ck_causal_nodes_observability,
          DROP COLUMN notes, DROP COLUMN business_name, DROP COLUMN observability,
          DROP COLUMN entity_type_catalog_ref
        """
    )
    op.execute("ALTER TABLE causal_models DROP CONSTRAINT fk_causal_models_active_snapshot")
    op.execute("ALTER TABLE causal_models DROP CONSTRAINT fk_causal_models_active_version")
    op.execute("ALTER TABLE causal_model_versions DROP CONSTRAINT fk_causal_model_versions_derived_from")
    op.execute("ALTER TABLE causal_model_versions DROP CONSTRAINT ck_causal_model_versions_revision_positive")
    op.execute("ALTER TABLE causal_model_versions DROP CONSTRAINT causal_model_versions_status_check")
    op.execute(
        """
        ALTER TABLE causal_model_versions
          DROP COLUMN legacy_fixture, DROP COLUMN derived_from_model_version_id,
          DROP COLUMN reviewed_by, DROP COLUMN reviewed_at, DROP COLUMN submitted_by, DROP COLUMN submitted_at,
          DROP COLUMN updated_by, DROP COLUMN created_by, DROP COLUMN revision,
          DROP COLUMN diagnostic_target_signature, DROP COLUMN diagnostic_target,
          ADD CONSTRAINT causal_model_versions_status_check CHECK (
            status IN ('draft','testing','published','deprecated')
          )
        """
    )
    op.execute("ALTER TABLE causal_models DROP CONSTRAINT ck_causal_models_revision_positive")
    op.execute("ALTER TABLE causal_models DROP CONSTRAINT ck_causal_models_active_pointer_pair")
    op.execute(
        "ALTER TABLE causal_models DROP COLUMN revision, DROP COLUMN active_snapshot_id, "
        "DROP COLUMN active_model_version_id, DROP COLUMN diagnostic_target_signature"
    )
