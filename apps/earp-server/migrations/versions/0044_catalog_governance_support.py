"""Catalog Phase 1 signing evidence, outbox, cursor and immutability guards."""

from __future__ import annotations

from alembic import op

revision: str = "0044_catalog_governance_support"
down_revision: str = "0043_catalog_profiles"

_TABLES = ("catalog_signoffs", "catalog_outbox", "catalog_sync_cursors")


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
    op.execute(
        """CREATE TABLE catalog_signoffs (
            tenant_id VARCHAR(64) NOT NULL, signoff_id VARCHAR(64) NOT NULL,
            manifest_id VARCHAR(128) NOT NULL, manifest_revision INTEGER NOT NULL,
            signoff_tag VARCHAR(128) NOT NULL, change_order VARCHAR(128) NOT NULL,
            attestation JSONB NOT NULL, envelope_hash VARCHAR(64) NOT NULL
              CHECK (envelope_hash ~ '^[0-9a-f]{64}$'),
            signed_at TIMESTAMPTZ NOT NULL, effective_from TIMESTAMPTZ NOT NULL,
            effective_until TIMESTAMPTZ, signers JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_signoffs PRIMARY KEY (tenant_id, signoff_id),
            CONSTRAINT uq_catalog_signoffs_manifest UNIQUE (tenant_id, manifest_id, manifest_revision),
            CONSTRAINT fk_catalog_signoffs_manifest FOREIGN KEY
              (tenant_id, manifest_id, manifest_revision)
              REFERENCES catalog_manifests (tenant_id, manifest_id, manifest_revision),
            CONSTRAINT ck_catalog_signoffs_window CHECK
              (effective_until IS NULL OR effective_until > effective_from)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_outbox (
            tenant_id VARCHAR(64) NOT NULL, event_id VARCHAR(64) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL, event_type VARCHAR(48) NOT NULL
              CHECK (event_type IN ('cache_invalidate','git_archive')),
            resource_type VARCHAR(48) NOT NULL, resource_id VARCHAR(128) NOT NULL,
            payload JSONB NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','processing','succeeded','failed')),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            next_retry_at TIMESTAMPTZ, last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), processed_at TIMESTAMPTZ,
            CONSTRAINT pk_catalog_outbox PRIMARY KEY (tenant_id, event_id),
            CONSTRAINT uq_catalog_outbox_idempotency UNIQUE (tenant_id, idempotency_key)
        )"""
    )
    op.execute(
        """CREATE TABLE catalog_sync_cursors (
            tenant_id VARCHAR(64) NOT NULL, source_system VARCHAR(64) NOT NULL,
            cursor VARCHAR(512), last_sync_at TIMESTAMPTZ, last_object_id VARCHAR(256),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_sync_cursors PRIMARY KEY (tenant_id, source_system)
        )"""
    )
    for table in _TABLES:
        _rls(table)

    op.execute(
        """CREATE FUNCTION catalog_pack_immutable_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              RAISE EXCEPTION 'published Catalog Pack versions are immutable';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status <> 'draft' AND (
            NEW.pack_id IS DISTINCT FROM OLD.pack_id OR
            NEW.version IS DISTINCT FROM OLD.version OR
            NEW.layer IS DISTINCT FROM OLD.layer OR
            NEW.name IS DISTINCT FROM OLD.name OR
            NEW.owner_role IS DISTINCT FROM OLD.owner_role OR
            NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
            NEW.revision IS DISTINCT FROM OLD.revision
          ) THEN
            RAISE EXCEPTION 'published Catalog Pack versions are immutable';
          END IF;
          RETURN NEW;
        END;
        $$"""
    )
    op.execute(
        """CREATE TRIGGER catalog_packs_immutable_guard
        BEFORE UPDATE OR DELETE ON catalog_packs
        FOR EACH ROW EXECUTE FUNCTION catalog_pack_immutable_guard()"""
    )
    op.execute(
        """CREATE FUNCTION catalog_manifest_immutable_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              RAISE EXCEPTION 'published Catalog Manifest revisions are immutable';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status <> 'draft' AND (
            NEW.manifest_id IS DISTINCT FROM OLD.manifest_id OR
            NEW.manifest_revision IS DISTINCT FROM OLD.manifest_revision OR
            NEW.profile_id IS DISTINCT FROM OLD.profile_id OR
            NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash OR
            NEW.envelope_hash IS DISTINCT FROM OLD.envelope_hash OR
            NEW.manifest_schema_version IS DISTINCT FROM OLD.manifest_schema_version OR
            NEW.canonicalizer_version IS DISTINCT FROM OLD.canonicalizer_version OR
            NEW.resolver_identity IS DISTINCT FROM OLD.resolver_identity OR
            NEW.scope IS DISTINCT FROM OLD.scope OR
            NEW.pack_lock IS DISTINCT FROM OLD.pack_lock OR
            NEW.owners IS DISTINCT FROM OLD.owners OR
            NEW.signoff IS DISTINCT FROM OLD.signoff
          ) THEN
            RAISE EXCEPTION 'published Catalog Manifest revisions are immutable';
          END IF;
          RETURN NEW;
        END;
        $$"""
    )
    op.execute(
        """CREATE TRIGGER catalog_manifests_immutable_guard
        BEFORE UPDATE OR DELETE ON catalog_manifests
        FOR EACH ROW EXECUTE FUNCTION catalog_manifest_immutable_guard()"""
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER catalog_manifests_immutable_guard ON catalog_manifests")
    op.execute("DROP TRIGGER catalog_packs_immutable_guard ON catalog_packs")
    op.execute("DROP FUNCTION catalog_manifest_immutable_guard()")
    op.execute("DROP FUNCTION catalog_pack_immutable_guard()")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE {table}")
