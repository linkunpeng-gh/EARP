"""add dataset_process_rules, doc process_rule_id, kb retrieval_model.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")

    # 1. DatasetProcessRule table (matches Dify's dataset_process_rules)
    op.create_table(
        "dataset_process_rules",
        sa.Column("process_rule_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=True, comment="FK to knowledge_bases.knowledge_base_id"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="custom",
                  comment="automatic | custom | hierarchical"),
        sa.Column("rules", sa.JSON, nullable=True, comment="pre_processing + segmentation + parent_mode"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("CREATE INDEX ix_process_rules_tenant ON dataset_process_rules (tenant_id)")
    op.execute("CREATE INDEX ix_process_rules_dataset ON dataset_process_rules (dataset_id)")

    # 2. documents.process_rule_id (FK — each doc can override KB process rule)
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS process_rule_id VARCHAR(64) REFERENCES dataset_process_rules(process_rule_id)")

    # 3. knowledge_bases.retrieval_model (KB-level retrieval config)
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS retrieval_model JSONB DEFAULT NULL")

    # 4. knowledge_bases.indexing_technique
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS indexing_technique VARCHAR(32) DEFAULT 'high_quality' CHECK (indexing_technique IN ('high_quality','economy'))")

    # 5. RLS on new table
    op.execute("ALTER TABLE dataset_process_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dataset_process_rules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON dataset_process_rules "
        "USING (tenant_id = current_setting('earp.tenant_id', true))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS process_rule_id")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS retrieval_model")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS indexing_technique")
    op.drop_table("dataset_process_rules")
