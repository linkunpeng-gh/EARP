"""N01A fix: widen idempotency operation (long node/requirement keys overflow).

The N01A operation strings are built from dynamic keys, e.g.
  causal-evidence.put:{version_id}:{node_key}:{requirement_key}
  causal-node.put:{version_id}:{node_key}
with node_key up to VARCHAR(64).  VARCHAR(96) overflows for long business keys
(e.g. entry node key `production_output` + generated requirement key), which
surfaces as a 500 StringDataRightTruncation on evidence/node writes.
"""
from __future__ import annotations

from alembic import op

revision: str = "0041_widen_idempotency_operation"
down_revision: str = "0040_n01_causal_model_management"


def upgrade() -> None:
    op.execute("ALTER TABLE idempotency_records ALTER COLUMN operation TYPE VARCHAR(255)")


def downgrade() -> None:
    op.execute("ALTER TABLE idempotency_records ALTER COLUMN operation TYPE VARCHAR(96)")
