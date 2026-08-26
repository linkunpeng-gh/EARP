"""API 密钥绑定应用列（对外 API 服务 Task 1，tech-debt #18）。

tasks/chat-app-api-access-task-breakdown.md D4：密钥即授权——一把密钥绑一个应用。
api_keys 表（0001 baseline 已建、0 行）缺 chat_app_id 列，本次补列：

- api_keys.chat_app_id VARCHAR(64) NOT NULL → FK chat_apps ON DELETE CASCADE
  （应用删除即吊销其全部密钥；FK 检查受 RLS 约束 → 只能绑同租户应用）
- 索引 ix_api_keys_chat_app (tenant_id, chat_app_id)：按应用列密钥（前端「API 访问」页签）
- 唯一索引 uq_api_keys_tenant_hash (tenant_id, key_hash)：鉴权热路径（tenant+hash 精确命中）
  + 同租户密钥碰撞防护
- SECURITY DEFINER 函数 public.verify_api_key(p_key_hash)：对外 API 鉴权查表。
  RLS 鸡生蛋问题：api_keys FORCE RLS（USING tenant_id = current_setting），而 gateway 中间件
  解析 Bearer app-key 时租户未知（tenant 由密钥行携带）——未设 GUC 时表不可见。
  标准解法：安全定义者函数（owner=postgres BYPASSRLS，函数体绕过 RLS），earp_app 仅获
  EXECUTE（对表零权限，反而收窄攻击面）；SET search_path 防劫持。

存量表仅加列/加索引/加函数——无新表，RLS 三件套（0001 已建）与 GRANT ALL TABLES（表级，覆盖新列）
无需变更；test_migrations.EXPECTED_TABLES（无新表）与 test_rls 矩阵（api_keys 已在）不变。

Revision ID: 0033_api_keys_chat_app
Revises: 0032_conversation_context
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision: str = "0033_api_keys_chat_app"
down_revision: str = "0032_conversation_context"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    # api_keys 为存量表（0 行），NOT NULL 安全；FK 显式命名便于回退。
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS chat_app_id VARCHAR(64) NOT NULL "
        "CONSTRAINT fk_api_keys_chat_app REFERENCES chat_apps (chat_app_id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_chat_app ON api_keys (tenant_id, chat_app_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_tenant_hash ON api_keys (tenant_id, key_hash)"
    )
    # RLS 鸡生蛋：鉴权时租户未知（密钥行携带 tenant_id），app 角色未设 GUC 看不到表。
    # SECURITY DEFINER（owner=postgres BYPASSRLS）函数体绕过 RLS；earp_app 仅 EXECUTE。
    op.execute(
        "CREATE OR REPLACE FUNCTION public.verify_api_key(p_key_hash TEXT) "
        "RETURNS TABLE (api_key_id VARCHAR, tenant_id VARCHAR, chat_app_id VARCHAR, status VARCHAR) "
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$ "
        "BEGIN RETURN QUERY SELECT k.api_key_id, k.tenant_id, k.chat_app_id, k.status "
        "FROM api_keys k WHERE k.key_hash = p_key_hash; END; $$"
    )
    op.execute("GRANT EXECUTE ON FUNCTION public.verify_api_key(TEXT) TO earp_app")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute("DROP INDEX IF EXISTS uq_api_keys_tenant_hash")
    op.execute("DROP INDEX IF EXISTS ix_api_keys_chat_app")
    op.execute("DROP FUNCTION IF EXISTS public.verify_api_key(TEXT)")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS chat_app_id")
