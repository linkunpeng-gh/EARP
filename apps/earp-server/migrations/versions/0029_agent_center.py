"""应用中心（智能体）：chat_apps 扩展列 + 分类词表/权限矩阵/收藏 三张新表。

设计依据：docs/superpowers/specs/2026-08-24-agent-center-design.md §3。

- chat_apps ALTER：category（业务分类名快照）、tags（自由标签）、created_by（创建人）、
  access_mode（应用权限权威开关 open|restricted，fail-closed 语义，对齐 D2/D3/D4）
- app_categories：租户级预设业务分类词表（category_id 全局唯一，对齐 roles.role_id 模式）
- app_role_access：角色×应用权限矩阵（仅存 restricted 应用的授权行；role FK ON DELETE CASCADE）
- user_app_favorites：我的应用（按 user_id，chat_app_id FK ON DELETE CASCADE 清理收藏）
- 每表 RLS 三件套 + 显式 GRANT earp_app（对齐 0014/0019 先例：升级路径新表必须显式授权）

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rls(table: str, grants: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_setting('earp.tenant_id', true))")
    op.execute(f"GRANT {grants} ON {table} TO earp_app")


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")

    # 1. chat_apps 扩展列
    op.execute(
        "ALTER TABLE chat_apps "
        "ADD COLUMN IF NOT EXISTS category VARCHAR(64) NULL, "
        "ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}', "
        "ADD COLUMN IF NOT EXISTS created_by VARCHAR(64) NULL, "
        "ADD COLUMN IF NOT EXISTS access_mode VARCHAR(16) NOT NULL DEFAULT 'open' "
        "  CHECK (access_mode IN ('open', 'restricted'))"
    )

    # 2. app_categories（租户级预设业务分类词表）
    op.execute(
        "CREATE TABLE IF NOT EXISTS app_categories ("
        "  category_id VARCHAR(64) PRIMARY KEY,"
        "  tenant_id   VARCHAR(64) NOT NULL,"
        "  name        VARCHAR(64) NOT NULL,"
        "  sort_order  INTEGER NOT NULL DEFAULT 0,"
        "  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  CONSTRAINT uq_app_categories_tenant_name UNIQUE (tenant_id, name)"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_app_categories_tenant ON app_categories (tenant_id, sort_order)")

    # 3. app_role_access（角色×应用权限矩阵；仅存 restricted 应用的授权行）
    op.execute(
        "CREATE TABLE IF NOT EXISTS app_role_access ("
        "  chat_app_id VARCHAR(64) NOT NULL REFERENCES chat_apps (chat_app_id) ON DELETE CASCADE,"
        "  role_id     VARCHAR(64) NOT NULL REFERENCES roles (role_id) ON DELETE CASCADE,"
        "  tenant_id   VARCHAR(64) NOT NULL,"
        "  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  PRIMARY KEY (chat_app_id, role_id, tenant_id)"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_app_role_access_role ON app_role_access (role_id, tenant_id)")

    # 4. user_app_favorites（我的应用）
    op.execute(
        "CREATE TABLE IF NOT EXISTS user_app_favorites ("
        "  user_id     VARCHAR(64) NOT NULL,"
        "  chat_app_id VARCHAR(64) NOT NULL REFERENCES chat_apps (chat_app_id) ON DELETE CASCADE,"
        "  tenant_id   VARCHAR(64) NOT NULL,"
        "  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  PRIMARY KEY (user_id, chat_app_id, tenant_id)"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_app_favorites_app ON user_app_favorites (chat_app_id, tenant_id)")

    # 5. RLS 三件套 + GRANT（favorites 无 UPDATE）
    _rls("app_categories", "SELECT, INSERT, UPDATE, DELETE")
    _rls("app_role_access", "SELECT, INSERT, UPDATE, DELETE")
    _rls("user_app_favorites", "SELECT, INSERT, DELETE")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_app_favorites CASCADE")
    op.execute("DROP TABLE IF EXISTS app_role_access CASCADE")
    op.execute("DROP TABLE IF EXISTS app_categories CASCADE")
    op.execute("ALTER TABLE chat_apps DROP COLUMN IF EXISTS access_mode")
    op.execute("ALTER TABLE chat_apps DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE chat_apps DROP COLUMN IF EXISTS tags")
    op.execute("ALTER TABLE chat_apps DROP COLUMN IF EXISTS category")
