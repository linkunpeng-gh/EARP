"""File-backed scenario datasets and immutable revisions."""

from __future__ import annotations

from alembic import op

revision: str = "0046_file_datasets"
down_revision: str = "0045_catalog_webhook_events"


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute(
        """CREATE TABLE file_datasets (
            tenant_id VARCHAR(64) NOT NULL,
            dataset_id VARCHAR(64) NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            latest_staged_hash VARCHAR(64),
            latest_published_hash VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_file_datasets PRIMARY KEY (tenant_id, dataset_id)
        )"""
    )
    op.execute(
        """CREATE TABLE file_dataset_revisions (
            tenant_id VARCHAR(64) NOT NULL,
            dataset_id VARCHAR(64) NOT NULL,
            content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
            status VARCHAR(16) NOT NULL CHECK (status IN ('staged','published')),
            manifest_json JSONB NOT NULL,
            files_json JSONB NOT NULL,
            validation_json JSONB NOT NULL,
            storage_relpath TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ,
            CONSTRAINT pk_file_dataset_revisions PRIMARY KEY (tenant_id, dataset_id, content_hash),
            CONSTRAINT fk_file_dataset_revisions_dataset FOREIGN KEY (tenant_id, dataset_id)
                REFERENCES file_datasets (tenant_id, dataset_id)
        )"""
    )
    for table in ("file_datasets", "file_dataset_revisions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('earp.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('earp.tenant_id', true))"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO earp_app")
    op.execute("CREATE INDEX ix_file_dataset_revisions_status ON file_dataset_revisions (tenant_id,status)")


def downgrade() -> None:
    op.execute("DROP TABLE file_dataset_revisions")
    op.execute("DROP TABLE file_datasets")
