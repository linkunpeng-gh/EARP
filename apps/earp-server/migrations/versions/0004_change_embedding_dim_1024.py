"""change embedding dimension 1536→1024 for bge-m3.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-20
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    # pgvector supports ALTER COLUMN TYPE for vector dimension changes.
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024);")
    op.execute("ALTER TABLE business_capabilities ALTER COLUMN embedding TYPE vector(1024);")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536);")
    op.execute("ALTER TABLE business_capabilities ALTER COLUMN embedding TYPE vector(1536);")
