"""运行历史（tech-debt #17 Task 1）— flow_runs.trace 列。

flow_runs（0026）已覆盖执行关联维度（chat_app/conversation/status/attempts），
终态（completed/failed/rejected/timeout）只写 status+finished_at，过程轨迹不落库
（前端即用即弃，刷新即失）。本次加 trace JSONB：终态时写入完整执行轨迹
（node_id/status/branch/input/output/error/error_code/latency_ms），刷新不丢，
管理侧可查历史（对话日志/运行历史，D4/D6）。

存量表仅加列——RLS 三件套（0026 已建）与 GRANT ALL TABLES（表级，覆盖新列）
无需变更；test_migrations.EXPECTED_TABLES（无新表）与 test_rls 矩阵
（flow_runs 已在）不变。

Revision ID: 0034_flow_runs_trace
Revises: 0033_api_keys_chat_app
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op

revision: str = "0034_flow_runs_trace"
down_revision: str = "0033_api_keys_chat_app"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("ALTER TABLE flow_runs ADD COLUMN IF NOT EXISTS trace JSONB NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("ALTER TABLE flow_runs DROP COLUMN IF EXISTS trace")
