"""评估集管理 — eval_sets/eval_cases/eval_runs/eval_run_cases 四表（B6，D1）。

三套评估（routing/understanding/planning）从 markdown fixture 落库 + 跑分记录，
评估从「脚本验证」变「平台能力」。种子按租户惰性初始化（ensure_eval_sets，
tbox 先例），本 migration 只建表 + RLS。

Revision ID: 0019_eval_sets
Revises: 0018_tbox_changes
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op

revision: str = "0019_eval_sets"
down_revision: str = "0018_tbox_changes"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE eval_sets (
            eval_set_id  VARCHAR(64) PRIMARY KEY,
            tenant_id    VARCHAR(64) NOT NULL,
            kind         VARCHAR(16) NOT NULL
                         CHECK (kind IN ('routing','understanding','planning')),
            name         VARCHAR(128) NOT NULL,
            description  TEXT,
            source       VARCHAR(16) NOT NULL DEFAULT 'builtin'
                         CHECK (source IN ('builtin','custom')),
            thresholds   JSONB NOT NULL DEFAULT '{}',
            enabled      BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE eval_cases (
            case_id     VARCHAR(64) PRIMARY KEY,
            tenant_id   VARCHAR(64) NOT NULL,
            eval_set_id VARCHAR(64) NOT NULL,
            sort_order  INT NOT NULL DEFAULT 0,
            query       TEXT NOT NULL,
            expected    JSONB NOT NULL,
            note        TEXT,
            enabled     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_eval_cases_set ON eval_cases (tenant_id, eval_set_id, sort_order)")
    op.execute(
        """
        CREATE TABLE eval_runs (
            run_id       VARCHAR(64) PRIMARY KEY,
            tenant_id    VARCHAR(64) NOT NULL,
            eval_set_id  VARCHAR(64) NOT NULL,
            mode         VARCHAR(16) NOT NULL
                         CHECK (mode IN ('rules','llm')),
            status       VARCHAR(16) NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running','completed','failed')),
            summary      JSONB NOT NULL DEFAULT '{}',
            gates        JSONB NOT NULL DEFAULT '{}',
            triggered_by VARCHAR(64),
            started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at  TIMESTAMPTZ
        );
        """
    )
    op.execute("CREATE INDEX ix_eval_runs_set ON eval_runs (tenant_id, eval_set_id, started_at DESC)")
    op.execute(
        """
        CREATE TABLE eval_run_cases (
            result_id  VARCHAR(64) PRIMARY KEY,
            tenant_id  VARCHAR(64) NOT NULL,
            run_id     VARCHAR(64) NOT NULL,
            case_id    VARCHAR(64) NOT NULL,
            passed     BOOLEAN NOT NULL,
            actual     JSONB NOT NULL DEFAULT '{}',
            detail     JSONB NOT NULL DEFAULT '{}',
            latency_ms INT
        );
        """
    )
    op.execute("CREATE INDEX ix_eval_run_cases_run ON eval_run_cases (run_id)")
    # RLS 三件套（同 0018）——app 角色 earp_app 无 BYPASSRLS，FORCE 生效
    for table in ("eval_sets", "eval_cases", "eval_runs", "eval_run_cases"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('earp.tenant_id', true))"
        )
        # 显式 GRANT earp_app（queue_schema 的 GRANT ALL TABLES 不覆盖升级路径新表，对齐 0014 先例）
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO earp_app")


def downgrade() -> None:
    for table in ("eval_run_cases", "eval_runs", "eval_cases", "eval_sets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
