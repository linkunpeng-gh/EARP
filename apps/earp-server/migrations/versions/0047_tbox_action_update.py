"""Widen tbox_changes.action CHECK — add 'update' for data-domain change requests.

设计：arch/design/2026-09-04-entity-type-data-domain-change-design.md §4.3。
无新表新列：payload JSONB 已承载新数据域；仅放宽动作枚举。
"""

from __future__ import annotations

from alembic import op

revision: str = "0047_tbox_action_update"
down_revision: str = "0046_file_datasets"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("SET statement_timeout = '120s'")
    # 0018 内联 CHECK 自动命名 tbox_changes_action_check；显式 drop+add 幂等
    op.execute("ALTER TABLE tbox_changes DROP CONSTRAINT IF EXISTS tbox_changes_action_check")
    op.execute(
        "ALTER TABLE tbox_changes ADD CONSTRAINT tbox_changes_action_check "
        "CHECK (action IN ('create','deprecate','reactivate','update'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tbox_changes DROP CONSTRAINT IF EXISTS tbox_changes_action_check")
    op.execute(
        "ALTER TABLE tbox_changes ADD CONSTRAINT tbox_changes_action_check "
        "CHECK (action IN ('create','deprecate','reactivate'))"
    )
