"""评估跑分取消 — eval_runs.status 支持 'cancelled'（FDE 反馈：llm 跑分卡死无法停止）。

背景：跑分是后台任务（asyncio.create_task），llm 模式 111 例 × LLM 升级超时累积
可挂数小时；无 cancel 端点时只能重启进程或改 DB。增加显式取消：
POST /runs/{id}/cancel → status='cancelled'；run_eval_task 每 case 前检查
status != 'running' 提前终止（不覆盖 cancelled）。

Revision ID: 0020_eval_run_cancel
Revises: 0019_eval_sets
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op

revision: str = "0020_eval_run_cancel"
down_revision: str = "0019_eval_sets"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # status CHECK 扩容：running/completed/failed → +cancelled
    op.execute("ALTER TABLE eval_runs DROP CONSTRAINT eval_runs_status_check")
    op.execute(
        "ALTER TABLE eval_runs ADD CONSTRAINT eval_runs_status_check "
        "CHECK (status IN ('running','completed','failed','cancelled'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE eval_runs DROP CONSTRAINT eval_runs_status_check")
    op.execute(
        "ALTER TABLE eval_runs ADD CONSTRAINT eval_runs_status_check "
        "CHECK (status IN ('running','completed','failed'))"
    )
