"""角色域权限 — roles.is_admin（tech-debt #9：Admin 全权限通用机制）。

背景：Admin 全权限原为 seed 特判（建角色时查租户 DD 配全 data_domain_access），
新建 DD 不会自动加入已有角色 → 路由权限失效。通用机制（读侧）：
is_admin 角色跳过 data_domain_access 域过滤（全权限），新建 DD 无需同步任何角色。

Revision ID: 0021_roles_is_admin
Revises: 0020_eval_run_cancel
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op

revision: str = "0021_roles_is_admin"
down_revision: str = "0020_eval_run_cancel"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE roles DROP COLUMN IF EXISTS is_admin")
