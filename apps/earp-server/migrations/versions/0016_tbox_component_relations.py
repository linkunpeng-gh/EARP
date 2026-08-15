"""TBox component supply/belong relations — belongs_to/supplied_by 源集合扩 component.

2026-08-15 决策（方案 A，TBox 部件级关系缺口闭合）：
- belongs_to 源扩 component（component→equipment：部件属于设备；同时保留
  equipment/sensor→production_line）
- supplied_by 源扩 component（component→supplier：部件由供应商供应）

注意：init_tenant_tbox 是 ON CONFLICT DO NOTHING——存量租户不会自动更新，
migration（superuser, BYPASSRLS）全量同步所有租户的 relation_types。

Revision ID: 0016_tbox_component_relations
Revises: 0015_chat_generation
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op

revision: str = "0016_tbox_component_relations"
down_revision: str = "0015_chat_generation"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        "UPDATE relation_types SET source_type = 'equipment,sensor,component', "
        "target_type = 'production_line,equipment' WHERE relation_type_id = 'belongs_to'"
    )
    op.execute(
        "UPDATE relation_types SET source_type = 'material,component' "
        "WHERE relation_type_id = 'supplied_by'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE relation_types SET source_type = 'equipment,sensor', "
        "target_type = 'production_line' WHERE relation_type_id = 'belongs_to'"
    )
    op.execute(
        "UPDATE relation_types SET source_type = 'material' WHERE relation_type_id = 'supplied_by'"
    )
