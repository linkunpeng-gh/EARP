"""TBox 审批流 — tbox_changes 变更请求表（tech-debt #12，D1）。

所有 TBox 变更（实体/关系类型新增、停用、恢复）先提交变更请求（pending），
审批通过后 apply 真实生效（applied），拒绝保留原因（rejected）。

Revision ID: 0018_tbox_changes
Revises: 0017_facts_updated_at
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op

revision: str = "0018_tbox_changes"
down_revision: str = "0017_facts_updated_at"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tbox_changes (
            change_id      VARCHAR(64) PRIMARY KEY,
            tenant_id      VARCHAR(64) NOT NULL,
            change_type    VARCHAR(16) NOT NULL
                           CHECK (change_type IN ('entity_type','relation_type')),
            action         VARCHAR(16) NOT NULL
                           CHECK (action IN ('create','deprecate','reactivate')),
            target_id      VARCHAR(64) NOT NULL,
            payload        JSONB NOT NULL DEFAULT '{}',
            status         VARCHAR(16) NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending','approved','applied','rejected')),
            requested_by   VARCHAR(64) NOT NULL,
            reviewed_by    VARCHAR(64),
            review_reason  TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_at    TIMESTAMPTZ
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_tbox_changes_status ON tbox_changes (tenant_id, status)"
    )
    # RLS 三件套（同 0008）——app 角色 earp_app 无 BYPASSRLS，FORCE 生效
    op.execute("ALTER TABLE tbox_changes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tbox_changes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tbox_changes "
        "USING (tenant_id = current_setting('earp.tenant_id', true))"
    )
    # 显式 GRANT earp_app（queue_schema 的 GRANT ALL TABLES 不覆盖升级路径新表，对齐 0014 先例）
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tbox_changes TO earp_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tbox_changes")
