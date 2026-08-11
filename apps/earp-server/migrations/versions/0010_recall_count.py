"""add documents.recall_count — recall statistics for doc-level UI.

Recall counting: search_chunks increments documents.recall_count once per
matching query per document (deduped by query). Supports the doc list column
"召回次数" in the Knowledge Base page.

Revision ID: 0009_recall_count
Revises: 0009_model_config
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision: str = "0010_recall_count"
down_revision: str = "0009_model_config"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS recall_count INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS recall_count")
