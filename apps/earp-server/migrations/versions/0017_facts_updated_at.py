"""Facts add updated_at — profile freshness 第三时间源（tech-debt #11，D4 方案 A）。

facts 表原无 updated_at：revoke 是 status 软删（created_at 不变），entity_timeline
只覆盖钩子写入后的变更——存量已 revoke 且 profile 后编译的场景漏检。加
updated_at + add_fact/revoke_fact 写时更新，作为 freshness 时间源之一
（timeline / facts.updated_at / entities.updated_at 三源取最大）。

Revision ID: 0017_facts_updated_at
Revises: 0016_tbox_component_relations
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op

revision: str = "0017_facts_updated_at"
down_revision: str = "0016_tbox_component_relations"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("ALTER TABLE facts ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute(
        "CREATE INDEX ix_facts_entity_updated ON facts (source_entity_id, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_facts_entity_updated")
    op.execute("ALTER TABLE facts DROP COLUMN IF EXISTS updated_at")
