"""Persist Catalog webhook replay and ordering evidence."""

from __future__ import annotations

from alembic import op

revision: str = "0045_catalog_webhook_events"
down_revision: str = "0044_catalog_governance_support"


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute(
        """CREATE TABLE catalog_webhook_events (
            tenant_id VARCHAR(64) NOT NULL,
            source_system VARCHAR(64) NOT NULL,
            event_id VARCHAR(128) NOT NULL,
            sequence_no BIGINT NOT NULL CHECK (sequence_no >= 0),
            payload_hash VARCHAR(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            status VARCHAR(32) NOT NULL CHECK (status IN ('accepted','processed','failed','ignored_out_of_order')),
            error_code VARCHAR(64),
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ,
            CONSTRAINT pk_catalog_webhook_events PRIMARY KEY (tenant_id, source_system, event_id),
            CONSTRAINT uq_catalog_webhook_events_sequence UNIQUE (tenant_id, source_system, sequence_no)
        )"""
    )
    op.execute("ALTER TABLE catalog_webhook_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog_webhook_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON catalog_webhook_events "
        "USING (tenant_id = current_setting('earp.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('earp.tenant_id', true))"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON catalog_webhook_events TO earp_app")


def downgrade() -> None:
    op.execute("DROP TABLE catalog_webhook_events")
