"""Allow copilot as system_model_settings.setting_type.

Copilot 配置助手模型（AI 助手专用）此前无法保存：system_model_settings.setting_type 的
DB CHECK 约束（0009）仅允许 llm/embedding/rerank，前端提交 copilot 会触发约束违反导致
保存失败。本轮将 copilot 纳入允许范围（model_configs.model_type 仍保持三类，copilot
选择的是 llm 类型配置的 config_id）。
"""

from alembic import op

revision = "0030_copilot_system_settings"
down_revision = "0029"
branch_labels = None
depends_on = None

CONSTRAINT = "system_model_settings_setting_type_check"


def upgrade() -> None:
    op.execute(f"ALTER TABLE system_model_settings DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE system_model_settings ADD CONSTRAINT {CONSTRAINT} "
        f"CHECK (setting_type IN ('llm','embedding','rerank','copilot'))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE system_model_settings DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE system_model_settings ADD CONSTRAINT {CONSTRAINT} "
        f"CHECK (setting_type IN ('llm','embedding','rerank'))"
    )
