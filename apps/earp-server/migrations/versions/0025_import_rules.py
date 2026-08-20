"""M3 中台 importer — import_rules 数据源注册表 + connector_configs.config_payload。

import_rules（M3 D2/G5）：数据源注册（connector + entity_type + field_mapping 落库），
定时同步的规则持久化载体——MappingRule 从「每次导入传参」升级为「注册后复用」，
B3 同步任务按 (connector, entity_type, source_mode) 读取规则执行。

connector_configs.config_payload JSONB：REST/DB 连接配置加密落库（复用
credential_crypto AES-256-GCM {ciphertext,nonce} JSON 格式）——0001 的
config_ciphertext BYTEA 从未写入（零代码引用，全 NULL），保留不动，
代码侧改用新列（避免不可逆的 BYTEA→JSONB 类型转换）。

Revision ID: 0025_import_rules
Revises: 0024_chat_apps_flow
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op

revision: str = "0025_import_rules"
down_revision: str = "0024_chat_apps_flow"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE import_rules (
            data_source_id  VARCHAR(64) PRIMARY KEY,
            tenant_id       VARCHAR(64) NOT NULL,
            connector_id    VARCHAR(64) NOT NULL REFERENCES connector_configs (connector_id),
            entity_type_id  VARCHAR(64) NOT NULL,
            source_mode     VARCHAR(16) NOT NULL
                            CHECK (source_mode IN ('virtual','synced')),
            field_mapping   JSONB NOT NULL DEFAULT '{}',
            incremental     JSONB NOT NULL DEFAULT '{}',
            status          VARCHAR(16) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','deprecated')),
            last_synced_at  TIMESTAMPTZ,
            last_sync_status VARCHAR(16)
                            CHECK (last_sync_status IN ('running','completed','failed','interrupted')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (entity_type_id, tenant_id)
                REFERENCES entity_types (entity_type_id, tenant_id)
        );
        """
    )
    op.execute("CREATE INDEX ix_import_rules_connector ON import_rules (tenant_id, connector_id)")
    op.execute("CREATE INDEX ix_import_rules_entity_type ON import_rules (tenant_id, entity_type_id)")
    # RLS 三件套（同 0019 模式）——app 角色 earp_app 无 BYPASSRLS，FORCE 生效
    for table in ("import_rules",):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('earp.tenant_id', true))"
        )
        # 显式 GRANT earp_app（queue_schema 的 GRANT ALL TABLES 不覆盖升级路径新表，对齐 0014 先例）
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO earp_app")
    # connector_configs 配置加密落库列（credential_crypto JSON 格式；旧 BYTEA 列保留不动）
    op.execute(
        "ALTER TABLE connector_configs ADD COLUMN IF NOT EXISTS "
        "config_payload JSONB NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE connector_configs DROP COLUMN IF EXISTS config_payload")
    op.execute("DROP TABLE IF EXISTS import_rules")
