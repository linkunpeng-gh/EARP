"""LLM model config center — model_configs + system_model_settings (PRD-2026-031).

Layer 2 (tenant-scoped model credentials, AES-encrypted JSONB) and Layer 3
(default model settings per type). Layer 1 (provider catalog) is code constants
in infra/model_registry.py.

Revision ID: 0009_model_config
Revises: 0008
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision: str = "0009_model_config"
down_revision: str = "0008_ontology"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_configs (
            config_id    VARCHAR(64) PRIMARY KEY,
            tenant_id    VARCHAR(64) NOT NULL,
            provider     VARCHAR(32) NOT NULL,
            model_type   VARCHAR(16) NOT NULL
                         CHECK (model_type IN ('llm','embedding','rerank')),
            model_name   VARCHAR(128) NOT NULL,
            credentials  JSONB NOT NULL DEFAULT '{}',
            enabled      BOOLEAN NOT NULL DEFAULT TRUE,
            is_default   BOOLEAN NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, provider, model_type, model_name)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE system_model_settings (
            tenant_id       VARCHAR(64) NOT NULL,
            setting_type    VARCHAR(16) NOT NULL
                            CHECK (setting_type IN ('llm','embedding','rerank')),
            model_config_id VARCHAR(64) NOT NULL REFERENCES model_configs(config_id),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, setting_type)
        );
        """
    )

    op.execute("CREATE INDEX ix_model_configs_tenant_type ON model_configs (tenant_id, model_type)")
    op.execute("CREATE INDEX ix_system_model_settings_tenant ON system_model_settings (tenant_id)")

    for tbl in ("model_configs", "system_model_settings"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            f"USING (tenant_id = current_setting('earp.tenant_id', true))"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_model_settings CASCADE")
    op.execute("DROP TABLE IF EXISTS model_configs CASCADE")
