"""Keep the durable ReasoningContext profile pin as wide as its registry source.

T05's fixture profile identity is intentionally longer than the original T04
runtime column.  Truncating it would make a recovered Context point to a
different algorithm profile, so the persistence contract must match the
registry's 0038 width.

Revision ID: 0039_ctx_profile_pin
Revises: 0038_algorithm_fixture_contract
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

revision: str = "0039_ctx_profile_pin"
down_revision: str = "0038_algorithm_fixture_contract"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute("ALTER TABLE reasoning_contexts ALTER COLUMN algorithm_profile_version TYPE VARCHAR(64)")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM reasoning_contexts WHERE length(algorithm_profile_version) > 32) THEN "
        "RAISE EXCEPTION 'cannot downgrade while long reasoning profile pins exist'; "
        "END IF; END $$"
    )
    op.execute("ALTER TABLE reasoning_contexts ALTER COLUMN algorithm_profile_version TYPE VARCHAR(32)")
