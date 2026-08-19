"""Chatflow F1 — chat_apps.orchestration（auto|flow）+ flow_schema JSONB。

设计稿 §2/§7：chat app 增加编排模式字段（auto = 现状 QU 一键问答；flow = 图驱动），
flow_schema 存声明式 DAG JSON（对齐 Dify/ReactFlow {nodes,edges}，F0 校验复用）。
存量行默认 auto + flow_schema NULL（后端兼容，前端零改动）；列级改动 RLS 策略不动。

Revision ID: 0024_chat_apps_flow
Revises: 0023_eval_sets_governance
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op

revision: str = "0024_chat_apps_flow"
down_revision: str = "0023_eval_sets_governance"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # D1: orchestration 模式（auto|flow）+ flow_schema（flow 模式必填，auto 可 NULL）
    op.execute(
        "ALTER TABLE chat_apps ADD COLUMN IF NOT EXISTS orchestration VARCHAR(16) "
        "NOT NULL DEFAULT 'auto' CHECK (orchestration IN ('auto', 'flow'))"
    )
    op.execute("ALTER TABLE chat_apps ADD COLUMN IF NOT EXISTS flow_schema JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_apps DROP COLUMN IF EXISTS flow_schema")
    op.execute("ALTER TABLE chat_apps DROP COLUMN IF EXISTS orchestration")
