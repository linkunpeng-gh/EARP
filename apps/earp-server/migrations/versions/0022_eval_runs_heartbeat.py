"""评估跑分心跳 — eval_runs.heartbeat_at（T1 D2：stale 判定不用 started_at 一刀切）。

背景：llm 跑分 111 例 × 30s 超时 ≈ 55min，TTL=1h 用 started_at 会误杀
还在跑的合法任务。改为 job 内每 case 更新 heartbeat_at；worker 启动扫描
running AND heartbeat_at < now()-TTL → failed（interrupted）。
start_run 插入时 DEFAULT now()（心跳新鲜起点 = 创建时刻）。

Revision ID: 0022_eval_runs_heartbeat
Revises: 0021_roles_is_admin
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op

revision: str = "0022_eval_runs_heartbeat"
down_revision: str = "0021_roles_is_admin"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # NOT NULL + DEFAULT now()：存量行也取创建时刻（不区分新旧）
    op.execute("ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    # stale 扫描索引（status + heartbeat 组合，worker 启动全租户扫描用）
    op.execute("CREATE INDEX IF NOT EXISTS ix_eval_runs_stale ON eval_runs (status, heartbeat_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_eval_runs_stale")
    op.execute("ALTER TABLE eval_runs DROP COLUMN IF EXISTS heartbeat_at")
