"""add embedding column to business_capabilities for pgvector semantic discovery.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("ALTER TABLE business_capabilities ADD COLUMN IF NOT EXISTS embedding vector(1536);")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("ALTER TABLE business_capabilities DROP COLUMN IF EXISTS embedding;")
