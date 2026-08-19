"""评估集治理 — eval_sets.seed_version + eval_cases.source（T3 D4-1/D4-4）。

背景：内置模板升级后老租户不更新（无版本概念）；同步只覆盖 builtin 用例、
custom 保留——eval_cases 无来源列无法区分。
加列 + 存量回填（按所属集合 source 回填：builtin 集合 → builtin，custom → custom）。
风险注明（任务书风险 2）：存量「builtin 集合里手工加的用例」会被回填成
builtin、同步时被覆盖——同步前前端有确认提示。

Revision ID: 0023_eval_sets_governance
Revises: 0022_eval_runs_heartbeat
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op

revision: str = "0023_eval_sets_governance"
down_revision: str = "0022_eval_runs_heartbeat"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # D4-1: 内置模板版本（custom 集合 NULL）
    op.execute("ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS seed_version INT")
    # D4-4: 用例来源（builtin/custom，同步只覆盖 builtin）
    op.execute("ALTER TABLE eval_cases ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'builtin'")
    # 存量回填：按所属集合 source 回填（builtin 集合 → builtin，custom → custom）
    op.execute(
        "UPDATE eval_cases SET source = s.source "
        "FROM eval_sets s WHERE s.eval_set_id = eval_cases.eval_set_id"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE eval_cases DROP COLUMN IF EXISTS source")
    op.execute("ALTER TABLE eval_sets DROP COLUMN IF EXISTS seed_version")
