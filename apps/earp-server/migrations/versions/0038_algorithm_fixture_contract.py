"""Allow a hash-verified, non-executable algorithm fixture to be registered honestly.

T04 made ``implementation_hash`` mandatory.  Case A's frozen fixture deliberately
declares that no executable implementation artifact exists yet, so coercing the
configuration hash into that column would break the fixture contract.  This
implementation erratum keeps the two identities distinct: an unbuilt version has
a NULL artifact hash, while its canonical configuration hash and payload remain
auditable.  T11 is responsible for publishing an artifact-bearing version.

Revision ID: 0038_algorithm_fixture_contract
Revises: 0037_reasoning_runtime_schema
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

revision: str = "0038_algorithm_fixture_contract"
down_revision: str = "0037_reasoning_runtime_schema"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute("ALTER TABLE reasoning_algorithm_versions ALTER COLUMN implementation_hash DROP NOT NULL")
    op.execute("ALTER TABLE reasoning_algorithm_versions ALTER COLUMN profile_version TYPE VARCHAR(64)")
    op.execute("ALTER TABLE reasoning_algorithm_versions ADD COLUMN algorithm_config_hash VARCHAR(64)")
    op.execute(
        "ALTER TABLE reasoning_algorithm_versions ADD COLUMN algorithm_config_json JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    op.execute("ALTER TABLE reasoning_algorithm_versions DROP COLUMN IF EXISTS algorithm_config_json")
    op.execute("ALTER TABLE reasoning_algorithm_versions DROP COLUMN IF EXISTS algorithm_config_hash")
    # Existing rows without an artifact hash cannot truthfully be represented by
    # the pre-0038 schema; migration rollback must stop rather than invent one.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM reasoning_algorithm_versions WHERE implementation_hash IS NULL) THEN "
        "RAISE EXCEPTION 'cannot downgrade while unbuilt algorithm fixtures exist'; "
        "END IF; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM reasoning_algorithm_versions WHERE length(profile_version) > 32) THEN "
        "RAISE EXCEPTION 'cannot downgrade while long algorithm profile versions exist'; "
        "END IF; END $$"
    )
    op.execute("ALTER TABLE reasoning_algorithm_versions ALTER COLUMN profile_version TYPE VARCHAR(32)")
    op.execute("ALTER TABLE reasoning_algorithm_versions ALTER COLUMN implementation_hash SET NOT NULL")
