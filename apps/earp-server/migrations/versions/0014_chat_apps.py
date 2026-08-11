"""Chat agent (chat_apps) + conversation citations + conversation chat_app_id.

P1 问答链路一期 — arch/design/2026-08-11-chat-agent-design.md §4.1:
  - chat_apps: 工作台 chat 智能体（配置 + 状态 draft|published，RLS 三件套对齐 0009）
  - messages.citations JSONB: 引用溯源（对话日志/应用形态共用）
  - conversations.chat_app_id (FK → chat_apps ON DELETE SET NULL): 会话归属（CP1/N1）

Revision ID: 0014_chat_apps
Revises: 0013_kb_summary_text
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_chat_apps"
down_revision: str = "0013_kb_summary_text"
branch_labels: None = None
depends_on: None = None

_DEFAULT_PROMPT = (
    "你是企业知识库智能助手。请基于提供的资料准确回答用户问题；"
    "资料不足时明确说明，不要编造。回答用中文，简洁清晰。"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chat_apps (
            chat_app_id     VARCHAR(64) PRIMARY KEY,
            tenant_id       VARCHAR(64) NOT NULL,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            system_prompt   TEXT NOT NULL DEFAULT :default_prompt,
            kb_scope        JSONB NOT NULL DEFAULT '[]',
            retrieval       JSONB NOT NULL
                            DEFAULT '{"mode": "hybrid", "top_k": 5, "threshold": 0.0}',
            model_config_id VARCHAR(64) NULL REFERENCES model_configs(config_id),
            context_turns   INTEGER NOT NULL DEFAULT 6,
            status          VARCHAR(16) NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'published')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """.replace(":default_prompt", "'" + _DEFAULT_PROMPT + "'")
    )
    op.execute("CREATE INDEX ix_chat_apps_tenant ON chat_apps (tenant_id, created_at)")

    op.execute("ALTER TABLE messages ADD COLUMN citations JSONB")
    op.execute(
        "ALTER TABLE conversations ADD COLUMN chat_app_id VARCHAR(64) "
        "REFERENCES chat_apps(chat_app_id) ON DELETE SET NULL"
    )

    # RLS 三件套（对齐 0009_model_config）
    op.execute("ALTER TABLE chat_apps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_apps FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON chat_apps "
        "USING (tenant_id = current_setting('earp.tenant_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_apps CASCADE")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS chat_app_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS citations")
