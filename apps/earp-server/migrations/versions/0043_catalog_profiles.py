"""Catalog Phase 1 runtime Profiles and active-Manifest binding."""

from __future__ import annotations

from alembic import op

revision: str = "0043_catalog_profiles"
down_revision: str = "0042_catalog_phase1_foundation"


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute(
        """CREATE TABLE catalog_profiles (
            tenant_id VARCHAR(64) NOT NULL,
            profile_id VARCHAR(128) NOT NULL,
            catalog_profile_id VARCHAR(128) NOT NULL,
            profile_schema_version VARCHAR(64) NOT NULL,
            industry_scope VARCHAR(128) NOT NULL,
            enterprise_scope VARCHAR(128) NOT NULL,
            data_domain_id VARCHAR(64) NOT NULL,
            roles JSONB NOT NULL,
            backup_approver VARCHAR(128) NOT NULL,
            status VARCHAR(24) NOT NULL CHECK (status IN ('draft','active','deprecated')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_catalog_profiles PRIMARY KEY (tenant_id, profile_id),
            CONSTRAINT uq_catalog_profiles_identity UNIQUE (tenant_id, catalog_profile_id)
        )"""
    )
    op.execute("ALTER TABLE catalog_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog_profiles FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON catalog_profiles "
        "USING (tenant_id = current_setting('earp.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('earp.tenant_id', true))"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON catalog_profiles TO earp_app")
    op.execute(
        "ALTER TABLE catalog_active_manifests ADD CONSTRAINT fk_catalog_active_manifests_profile "
        "FOREIGN KEY (tenant_id, profile_id) REFERENCES catalog_profiles (tenant_id, profile_id)"
    )
    op.execute(
        "ALTER TABLE catalog_manifests ADD CONSTRAINT fk_catalog_manifests_profile "
        "FOREIGN KEY (tenant_id, profile_id) REFERENCES catalog_profiles (tenant_id, profile_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE catalog_manifests DROP CONSTRAINT fk_catalog_manifests_profile")
    op.execute("ALTER TABLE catalog_active_manifests DROP CONSTRAINT fk_catalog_active_manifests_profile")
    op.execute("DROP TABLE catalog_profiles")
