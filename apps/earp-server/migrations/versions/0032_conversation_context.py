"""会话上下文列（C 系列 Task 1）— conversations.context + 会话元数据列。

Chatflow C 系列（会话上下文）— arch/design/2026-08-18-chat-session-context-design.md §2.2/§3.1：
  - conversations.context JSONB: 每轮结构化理解结果（last_entities/last_intent/last_relations + updated_at），
    只存上一轮（last-*），不存全量历史（QU §5.2 语义）
  - conversations.last_active_at TIMESTAMPTZ: 最后活跃时间（会话元数据，chat 二期前置）
  - conversations.message_count INT: 消息计数（冗余列，add_message 维护，避免 count 查询）
  - conversations.status VARCHAR: active/archived（一期加列不强制归档流程）

conversations 为存量表（0001 baseline 已建 + RLS 三件套 + GRANT ALL TABLES 全覆盖），
本次仅加列——无需新表 RLS/GRANT；test_migrations.EXPECTED_TABLES / test_rls 表数不变。

Revision ID: 0032_conversation_context
Revises: 0031_flow_runs_rejected
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision: str = "0032_conversation_context"
down_revision: str = "0031_flow_runs_rejected"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN context JSONB NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE conversations ADD COLUMN last_active_at TIMESTAMPTZ")
    op.execute("ALTER TABLE conversations ADD COLUMN message_count INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE conversations ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active' "
        "CHECK (status IN ('active', 'archived'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS message_count")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS last_active_at")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS context")
