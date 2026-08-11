"""Chat agent generation params — temperature / top_p / max_tokens.

P1 问答链路一期补充（2026-08-11 会话决策）：编排页新增「生成参数」区，
应用级 LLM 推理参数（Dify 模型参数面板对齐）。chat_stream 不再写死
temperature=0.7。

Revision ID: 0015_chat_generation
Revises: 0014_chat_apps
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0015_chat_generation"
down_revision: str = "0014_chat_apps"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat_apps ADD COLUMN generation JSONB NOT NULL "
        "DEFAULT '{\"temperature\": 0.7, \"top_p\": 0.9, \"max_tokens\": 1024}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chat_apps DROP COLUMN IF EXISTS generation")
