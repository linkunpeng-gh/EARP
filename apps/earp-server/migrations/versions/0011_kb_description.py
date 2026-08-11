"""add knowledge_bases.description — KB basic attributes editing.

create_kb accepted a description param but the column never existed; add it so
KB editing (PATCH /knowledge/bases/{id}) can store the description.

Revision ID: 0011_kb_description
Revises: 0010_recall_count
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision: str = "0011_kb_description"
down_revision: str = "0010_recall_count"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS description TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS description")
