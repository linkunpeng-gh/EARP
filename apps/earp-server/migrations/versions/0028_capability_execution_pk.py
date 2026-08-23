"""business_capabilities: 复合主键 (capability_id, tenant_id) + execution 声明列。

tech-debt #7：单行 capability_id 主键跨租户冲突——改为复合主键，跨租户同名能力各自隔离。
同步引用 business_capabilities(capability_id) 的 FK（fallback 自引用 / capability_calls /
connector_bindings）改为引用复合主键；tbox capability_entity_map 仅存 capability_id、无 FK、无需改动。
同时新增 execution JSONB（能力中心任务书 D1 / 通用执行器任务书 D1：声明「这个能力怎么执行」）。

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027_qu_prompt_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")

    # 1. 先拆所有引用 business_capabilities(capability_id) 的 FK（含自引用），再动 PK
    op.execute(
        "ALTER TABLE business_capabilities "
        "DROP CONSTRAINT IF EXISTS business_capabilities_fallback_capability_id_fkey;"
    )
    op.execute(
        "ALTER TABLE capability_calls "
        "DROP CONSTRAINT IF EXISTS capability_calls_capability_id_fkey;"
    )
    op.execute(
        "ALTER TABLE connector_bindings "
        "DROP CONSTRAINT IF EXISTS connector_bindings_capability_id_fkey;"
    )

    # 2. 单行 PK -> 复合 PK（存量 capability_id 全局唯一，加 tenant_id 不会冲突）
    op.execute("ALTER TABLE business_capabilities DROP CONSTRAINT IF EXISTS business_capabilities_pkey;")
    op.execute("ALTER TABLE business_capabilities ADD PRIMARY KEY (capability_id, tenant_id);")

    # 3. execution 声明列（默认空对象，能力中心存声明、通用执行器消费）
    op.execute(
        "ALTER TABLE business_capabilities "
        "ADD COLUMN IF NOT EXISTS execution JSONB NOT NULL DEFAULT '{}'::jsonb;"
    )

    # 4. FK 改引用复合主键（fallback 自引用用本行 tenant_id 作为复合键第二部分）
    op.execute(
        "ALTER TABLE business_capabilities "
        "ADD CONSTRAINT business_capabilities_fallback_capability_id_fkey "
        "FOREIGN KEY (fallback_capability_id, tenant_id) "
        "REFERENCES business_capabilities (capability_id, tenant_id);"
    )
    op.execute(
        "ALTER TABLE capability_calls "
        "ADD CONSTRAINT capability_calls_capability_id_fkey "
        "FOREIGN KEY (capability_id, tenant_id) "
        "REFERENCES business_capabilities (capability_id, tenant_id);"
    )
    op.execute(
        "ALTER TABLE connector_bindings "
        "ADD CONSTRAINT connector_bindings_capability_id_fkey "
        "FOREIGN KEY (capability_id, tenant_id) "
        "REFERENCES business_capabilities (capability_id, tenant_id);"
    )


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")

    # 1. 拆复合 FK
    op.execute(
        "ALTER TABLE business_capabilities "
        "DROP CONSTRAINT IF EXISTS business_capabilities_fallback_capability_id_fkey;"
    )
    op.execute(
        "ALTER TABLE capability_calls "
        "DROP CONSTRAINT IF EXISTS capability_calls_capability_id_fkey;"
    )
    op.execute(
        "ALTER TABLE connector_bindings "
        "DROP CONSTRAINT IF EXISTS connector_bindings_capability_id_fkey;"
    )

    # 2. 拆 execution 列 + 复合 PK，恢复单行 PK
    op.execute("ALTER TABLE business_capabilities DROP COLUMN IF EXISTS execution;")
    op.execute("ALTER TABLE business_capabilities DROP CONSTRAINT IF EXISTS business_capabilities_pkey;")
    op.execute("ALTER TABLE business_capabilities ADD PRIMARY KEY (capability_id);")

    # 3. 恢复单行 FK 引用
    op.execute(
        "ALTER TABLE business_capabilities "
        "ADD CONSTRAINT business_capabilities_fallback_capability_id_fkey "
        "FOREIGN KEY (fallback_capability_id) REFERENCES business_capabilities (capability_id);"
    )
    op.execute(
        "ALTER TABLE capability_calls "
        "ADD CONSTRAINT capability_calls_capability_id_fkey "
        "FOREIGN KEY (capability_id) REFERENCES business_capabilities (capability_id);"
    )
    op.execute(
        "ALTER TABLE connector_bindings "
        "ADD CONSTRAINT connector_bindings_capability_id_fkey "
        "FOREIGN KEY (capability_id) REFERENCES business_capabilities (capability_id);"
    )
