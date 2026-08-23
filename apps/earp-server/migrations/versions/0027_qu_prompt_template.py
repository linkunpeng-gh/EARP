"""Chatflow QU 升级 prompt 模板 — system_model_settings.qu_prompt_template（租户级可配）。

系统级可配（Part 2，A 方案）：QU 理解层「LLM 升级」的 user prompt 模板，管理员在模型配置中心
系统设置里配置（占位符 {query}/{missing}/{relation_candidates}/{context}）；未配置 → 走内置压缩默认。
列挂在 llm 设置行上（租户级；表无 RLS、写经 admin 门禁）。
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_qu_prompt_template"
down_revision = "0026_flow_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_model_settings",
        sa.Column("qu_prompt_template", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_model_settings", "qu_prompt_template")
