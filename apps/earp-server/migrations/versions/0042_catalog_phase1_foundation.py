"""Catalog Phase 1 runtime registry, Pack and Manifest persistence.

Extends (rather than replaces) the existing N01A change-request state machine.
All Catalog semantic payloads remain in their authoritative source systems;
these tables store immutable exact-reference pins and governance metadata only.
"""

from __future__ import annotations

from alembic import op

revision: str = "0042_catalog_phase1_foundation"
down_revision: str = "0041_widen_idempotency_operation"

_TABLES = (
    "catalog_refs",
    "catalog_packs",
    "catalog_pack_entries",
    "catalog_manifests",
    "catalog_manifest_entries",
    "catalog_active_manifests",
    "catalog_approvals",
    "catalog_sync_runs",
    "catalog_audit_logs",
)


def _rls(table: str) -> None:
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
    op.execute("ALTER TABLE catalog_change_requests DROP CONSTRAINT catalog_change_requests_request_type_check")
    op.execute(
        "ALTER TABLE catalog_change_requests ADD CONSTRAINT catalog_change_requests_request_type_check CHECK "
        "(request_type IN ('data_domain','entity_type','relation_type','metric','unit','aggregation',"
        "'time_window_schema','binding_template','capability_contract','rule_schema',"
        "'pack_publish','manifest_publish','manifest_revoke','manifest_rollback'))"
    )
    op.execute("ALTER TABLE catalog_change_requests ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128)")
    op.execute("ALTER TABLE catalog_change_requests ADD COLUMN IF NOT EXISTS resource_type VARCHAR(48)")
    op.execute("ALTER TABLE catalog_change_requests ADD COLUMN IF NOT EXISTS resource_id VARCHAR(128)")
    op.execute(
        "CREATE UNIQUE INDEX uq_catalog_change_requests_idempotency "
        "ON catalog_change_requests (tenant_id, requester_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        """CREATE TABLE catalog_refs (
            tenant_id VARCHAR(64) NOT NULL, ref_id VARCHAR(64) NOT NULL,
            kind VARCHAR(32) NOT NULL, stable_id VARCHAR(128) NOT NULL, version VARCHAR(128) NOT NULL,
            content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
            semantic_schema_version VARCHAR(64) NOT NULL, canonicalizer_version VARCHAR(64) NOT NULL,
            source_system VARCHAR(64) NOT NULL, source_identity VARCHAR(256) NOT NULL,
            data_domain_id VARCHAR(64) NOT NULL, status VARCHAR(24) NOT NULL CHECK
              (status IN ('active','deprecated','inactive','suspected_missing')),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb, revoked_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_refs PRIMARY KEY (tenant_id, ref_id),
            CONSTRAINT uq_catalog_refs_exact UNIQUE (tenant_id, kind, stable_id, version)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_packs (
            tenant_id VARCHAR(64) NOT NULL, pack_id VARCHAR(128) NOT NULL, version VARCHAR(32) NOT NULL,
            layer VARCHAR(16) NOT NULL CHECK (layer IN ('platform','industry','enterprise')),
            name VARCHAR(256) NOT NULL, owner_role VARCHAR(128) NOT NULL, content_hash VARCHAR(64),
            status VARCHAR(24) NOT NULL CHECK (status IN ('draft','published','deprecated','revoked')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0), deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), published_at TIMESTAMPTZ,
            CONSTRAINT pk_catalog_packs PRIMARY KEY (tenant_id, pack_id, version),
            CONSTRAINT ck_catalog_packs_hash CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$')
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_pack_entries (
            tenant_id VARCHAR(64) NOT NULL, pack_id VARCHAR(128) NOT NULL, pack_version VARCHAR(32) NOT NULL,
            kind VARCHAR(32) NOT NULL, stable_id VARCHAR(128) NOT NULL, version VARCHAR(128) NOT NULL,
            content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT pk_catalog_pack_entries PRIMARY KEY (tenant_id, pack_id, pack_version, kind, stable_id, version),
            CONSTRAINT fk_catalog_pack_entries_pack FOREIGN KEY (tenant_id, pack_id, pack_version)
              REFERENCES catalog_packs (tenant_id, pack_id, version)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_manifests (
            tenant_id VARCHAR(64) NOT NULL, manifest_id VARCHAR(128) NOT NULL, manifest_revision INTEGER NOT NULL,
            profile_id VARCHAR(128) NOT NULL,
            manifest_hash VARCHAR(64) NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
            envelope_hash VARCHAR(64), manifest_schema_version VARCHAR(64) NOT NULL,
            canonicalizer_version VARCHAR(64) NOT NULL, resolver_identity VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL CHECK (status IN (
              'draft','pending_activation','active','fully_signed','active_archive_pending','revoked'
            )),
            scope JSONB NOT NULL, pack_lock JSONB NOT NULL, owners JSONB NOT NULL, signoff JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), revoked_at TIMESTAMPTZ,
            CONSTRAINT pk_catalog_manifests PRIMARY KEY (tenant_id, manifest_id, manifest_revision),
            CONSTRAINT uq_catalog_manifests_profile_revision UNIQUE (tenant_id, profile_id, manifest_revision)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_manifest_entries (
            tenant_id VARCHAR(64) NOT NULL, manifest_id VARCHAR(128) NOT NULL, manifest_revision INTEGER NOT NULL,
            kind VARCHAR(32) NOT NULL, stable_id VARCHAR(128) NOT NULL, version VARCHAR(128) NOT NULL,
            content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
            status VARCHAR(24) NOT NULL CHECK (status IN ('active','deprecated','inactive')),
            data_domain_id VARCHAR(64) NOT NULL, semantic_schema_version VARCHAR(64) NOT NULL,
            source_pack_id VARCHAR(128), projection JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_catalog_manifest_entries PRIMARY KEY
              (tenant_id, manifest_id, manifest_revision, kind, stable_id, version),
            CONSTRAINT fk_catalog_manifest_entries_manifest FOREIGN KEY (tenant_id, manifest_id, manifest_revision)
              REFERENCES catalog_manifests (tenant_id, manifest_id, manifest_revision)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_active_manifests (
            tenant_id VARCHAR(64) NOT NULL, profile_id VARCHAR(128) NOT NULL, manifest_id VARCHAR(128),
            manifest_revision INTEGER, active_revision_generation BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_active_manifests PRIMARY KEY (tenant_id, profile_id),
            CONSTRAINT ck_catalog_active_manifests_pointer CHECK ((manifest_id IS NULL) = (manifest_revision IS NULL))
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_approvals (
            tenant_id VARCHAR(64) NOT NULL, approval_id VARCHAR(64) NOT NULL, request_id VARCHAR(64) NOT NULL,
            approver_id VARCHAR(64) NOT NULL, decision VARCHAR(16) NOT NULL CHECK (decision IN ('approved','rejected')),
            reason TEXT, emergency BOOLEAN NOT NULL DEFAULT false, expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_approvals PRIMARY KEY (tenant_id, approval_id),
            CONSTRAINT fk_catalog_approvals_request FOREIGN KEY (tenant_id, request_id)
              REFERENCES catalog_change_requests (tenant_id, request_id),
            CONSTRAINT uq_catalog_approvals_actor UNIQUE (tenant_id, request_id, approver_id)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_sync_runs (
            tenant_id VARCHAR(64) NOT NULL, sync_run_id VARCHAR(64) NOT NULL, source_system VARCHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL CHECK (status IN ('running','succeeded','failed','partial')),
            cursor_before VARCHAR(512), cursor_after VARCHAR(512), seen_count INTEGER NOT NULL DEFAULT 0,
            missing_count INTEGER NOT NULL DEFAULT 0, error_code VARCHAR(64),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ, CONSTRAINT pk_catalog_sync_runs PRIMARY KEY (tenant_id, sync_run_id)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_audit_logs (
            tenant_id VARCHAR(64) NOT NULL, audit_id VARCHAR(64) NOT NULL, actor_id VARCHAR(64) NOT NULL,
            subject_id VARCHAR(64), resource_type VARCHAR(48) NOT NULL, resource_id VARCHAR(128) NOT NULL,
            operation VARCHAR(64) NOT NULL, before_hash VARCHAR(64), after_hash VARCHAR(64),
            status VARCHAR(32) NOT NULL,
            reason TEXT, correlation_id VARCHAR(128) NOT NULL, emergency BOOLEAN NOT NULL DEFAULT false,
            detail JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_audit_logs PRIMARY KEY (tenant_id, audit_id)
        )"""
    )
    for table in _TABLES:
        _rls(table)


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP INDEX uq_catalog_change_requests_idempotency")
    op.execute(
        "ALTER TABLE catalog_change_requests DROP COLUMN resource_id, "
        "DROP COLUMN resource_type, DROP COLUMN idempotency_key"
    )
    op.execute("ALTER TABLE catalog_change_requests DROP CONSTRAINT catalog_change_requests_request_type_check")
    op.execute(
        "ALTER TABLE catalog_change_requests ADD CONSTRAINT catalog_change_requests_request_type_check CHECK "
        "(request_type IN ('data_domain','entity_type','relation_type','metric','unit','aggregation',"
        "'time_window_schema','binding_template','capability_contract','rule_schema'))"
    )
