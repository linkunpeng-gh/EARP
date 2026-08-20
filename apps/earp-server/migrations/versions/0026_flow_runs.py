"""Chatflow F4 — flow_runs 执行状态持久化（挂起/恢复/超时 的载体）。

F4 核心前置：flow 从「同步跑完即弃」升级为「可挂起/恢复」——human_approval 节点
执行到挂起点时，pool 序列化落 flow_runs（status=waiting_human + pending_node_id），
用户下一轮消息恢复继续执行。超时扫描（scheduler + 惰性检查）终态化。

列设计（任务书 D1）：
- status CHECK: running | waiting_human | completed | failed | timeout | cancelled（cancelled 一期不产出，预留）
- pending_node_id: 当前等待的 human_approval 节点 id（挂起时非空）
- node_state JSONB: pool 序列化（node_id → StepResult 的 output/status/error）
- flow_input JSONB: 图输入快照（{{query}} 模板替换数据源，恢复时原样重放）
- attempts: 恢复次数（每次恢复 +1）

RLS 三件套 + earp_app 显式 GRANT（对齐 0014 chat_apps 先例）。

Revision ID: 0026_flow_runs
Revises: 0025_import_rules
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op

revision: str = "0026_flow_runs"
down_revision: str = "0025_import_rules"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE flow_runs (
            execution_id    VARCHAR(64) PRIMARY KEY,
            tenant_id       VARCHAR(64) NOT NULL,
            chat_app_id     VARCHAR(64) NOT NULL REFERENCES chat_apps(chat_app_id),
            conversation_id VARCHAR(64) NOT NULL,
            status          VARCHAR(16) NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'waiting_human', 'completed',
                                              'failed', 'timeout', 'cancelled')),
            pending_node_id VARCHAR(64),
            node_state      JSONB NOT NULL DEFAULT '{}',
            flow_input      JSONB NOT NULL DEFAULT '{}',
            attempts        INTEGER NOT NULL DEFAULT 1,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at     TIMESTAMPTZ
        );
        """
    )
    op.execute("CREATE INDEX ix_flow_runs_conv ON flow_runs (tenant_id, conversation_id, status)")

    # RLS 三件套（对齐 0014 chat_apps）
    op.execute("ALTER TABLE flow_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE flow_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON flow_runs "
        "USING (tenant_id = current_setting('earp.tenant_id', true))"
    )
    # earp_app 授权：queue_schema.apply() 的 GRANT ALL TABLES 仅在启动时覆盖当时存在的表
    # —— 新表必须在此显式授权，否则 dev 升级路径（无 queue_schema）会 permission denied
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON flow_runs TO earp_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flow_runs CASCADE")
