"""命令审批流（Task 3）— flow_runs.status 新增 rejected 终态。

命令能力审批驳回（用户下一句明确拒绝）→ flow 终态 rejected（下游命令不执行）。
0026 flow_runs 的 status CHECK 无此值（running | waiting_human | completed | failed |
timeout | cancelled），需扩 CHECK 常量（PG 内联列约束默认名 {table}_{column}_check）。

Revision ID: 0031_flow_runs_rejected
Revises: 0030_copilot_system_settings
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op

revision: str = "0031_flow_runs_rejected"
down_revision: str = "0030_copilot_system_settings"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("ALTER TABLE flow_runs DROP CONSTRAINT flow_runs_status_check")
    op.execute(
        "ALTER TABLE flow_runs ADD CONSTRAINT flow_runs_status_check "
        "CHECK (status IN ('running', 'waiting_human', 'completed', "
        "'failed', 'timeout', 'cancelled', 'rejected'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE flow_runs DROP CONSTRAINT flow_runs_status_check")
    op.execute(
        "ALTER TABLE flow_runs ADD CONSTRAINT flow_runs_status_check "
        "CHECK (status IN ('running', 'waiting_human', 'completed', "
        "'failed', 'timeout', 'cancelled'))"
    )
