"""add data_domains, bddm map, dd-related columns for v2.1 Data Domain.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")

    op.create_table(
        "data_domains",
        sa.Column("data_domain_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("data_classification", sa.String(16), nullable=False, server_default="internal"),
        sa.Column("owner", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("CREATE INDEX ix_data_domains_tenant ON data_domains (tenant_id)")
    op.execute(
        "ALTER TABLE data_domains ADD CONSTRAINT ck_data_domain_classification "
        "CHECK (data_classification IN ('public','internal','confidential','restricted'))"
    )

    op.create_table(
        "business_domain_data_domain_map",
        sa.Column("business_domain_id", sa.String(64), nullable=False),
        sa.Column("data_domain_id", sa.String(64), sa.ForeignKey("data_domains.data_domain_id"), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("business_domain_id", "data_domain_id", "tenant_id"),
    )
    op.execute("CREATE INDEX ix_bddm_tenant ON business_domain_data_domain_map (tenant_id)")

    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS data_domain_id VARCHAR(64) REFERENCES data_domains(data_domain_id)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS data_classification VARCHAR(16) DEFAULT 'internal'")
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT ck_document_classification "
        "CHECK (data_classification IN ('public','internal','confidential','restricted'))"
    )
    op.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS data_domain_access JSONB NOT NULL DEFAULT '[]'::jsonb")

    for tbl in ("data_domains", "business_domain_data_domain_map"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            f"USING (tenant_id = current_setting('earp.tenant_id', true))"
        )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS data_domain_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS data_classification")
    op.execute("ALTER TABLE roles DROP COLUMN IF EXISTS data_domain_access")
    op.drop_table("business_domain_data_domain_map")
    op.drop_table("data_domains")
