"""add org_unit_id to users for department/org data_scope filtering.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS org_unit_id VARCHAR(64) REFERENCES org_units (org_unit_id);")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS org_unit_id;")
