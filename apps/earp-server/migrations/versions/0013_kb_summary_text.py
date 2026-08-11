"""add knowledge_bases.summary_text — manual KB retrieval summary override.

KB parity with data_domains.routing_description (2026-08-09): NULL/empty =
auto-aggregated summary (KB name + description + doc titles); non-empty =
manual override used for the Level-2 summary embedding.

Revision ID: 0013_kb_summary_text
Revises: 0012_routing
Create Date: 2026-08-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0013_kb_summary_text"
down_revision: str = "0012_routing"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS summary_text TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS summary_text")
