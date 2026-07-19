"""M0 baseline DDL - 8 data domains + checkpoint tables + RLS (PRD-2026-020 AC-03/04).

Sources of truth:
- L3 design: arch/design/server-m0-l3-design-v1.md section 3 (full column definitions)
- RBAC design v1.1 (role_id / data_scope / accessible_roles)
- langgraph-earp-mapping v1.1 section 2.5 (checkpoint 3-table model, EARP-maintained)
- data-architecture v1.0 (indexes / naming)

Dual-role strategy (Gate B P0-2): this migration runs under a BYPASSRLS-capable
role (EARP_MIGRATION_DATABASE_URL); the application connects as `earp_app`
(no BYPASSRLS) so FORCE RLS is effective. The role is created here if absent
(dev/test convenience - production overrides the password out-of-band).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

# Tables carrying tenant_id -> RLS enabled (all except top-level `tenants`).
TENANT_TABLES: tuple[str, ...] = (
    "org_units",
    "users",
    "roles",
    "service_accounts",
    "tenant_account_joins",
    "sessions",
    "executions",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "business_capabilities",
    "capability_calls",
    "connector_bindings",
    "policies",
    "policy_bindings",
    "audit_logs",
    "encrypted_credentials",
    "api_keys",
    "knowledge_bases",
    "documents",
    "chunks",
    "conversations",
    "messages",
    "connector_configs",
)

ALL_TABLES: tuple[str, ...] = ("tenants", *TENANT_TABLES)

_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

-- ============ Workspace domain ============
CREATE TABLE tenants (
    tenant_id   VARCHAR(64) PRIMARY KEY,
    name        TEXT NOT NULL,
    status      VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE org_units (
    org_unit_id VARCHAR(64) PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    parent_id   VARCHAR(64) REFERENCES org_units (org_unit_id),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_org_units_tenant ON org_units (tenant_id);

CREATE TABLE users (
    user_id     VARCHAR(64) PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    name        TEXT NOT NULL,
    email       TEXT,
    status      VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_tenant_email UNIQUE (tenant_id, email)
);

CREATE TABLE roles (
    role_id         VARCHAR(64) PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    name            TEXT NOT NULL,
    permissions     TEXT[] NOT NULL DEFAULT '{}',
    data_scope      VARCHAR(16) NOT NULL DEFAULT 'self'
                    CONSTRAINT ck_roles_data_scope CHECK (data_scope IN ('self','department','org','all')),
    knowledge_tags  TEXT[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_roles_tenant ON roles (tenant_id);

CREATE TABLE api_keys (
    api_key_id   VARCHAR(64) PRIMARY KEY,
    tenant_id    VARCHAR(64) NOT NULL,
    name         TEXT NOT NULL,
    key_hash     TEXT NOT NULL,
    status       VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);
CREATE INDEX ix_api_keys_tenant ON api_keys (tenant_id);

CREATE TABLE service_accounts (
    service_account_id VARCHAR(64) PRIMARY KEY,
    tenant_id          VARCHAR(64) NOT NULL,
    name               TEXT NOT NULL,
    api_key_id         VARCHAR(64) REFERENCES api_keys (api_key_id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_service_accounts_tenant ON service_accounts (tenant_id);

CREATE TABLE tenant_account_joins (
    tenant_id       VARCHAR(64) NOT NULL,
    user_id         VARCHAR(64) NOT NULL,
    role_ids        TEXT[] NOT NULL DEFAULT '{}',
    current_role_id VARCHAR(64),
    PRIMARY KEY (tenant_id, user_id)
);

-- ============ Runtime domain ============
CREATE TABLE sessions (
    session_id  VARCHAR(64) PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    user_id     VARCHAR(64) NOT NULL,
    role_id     VARCHAR(64) NOT NULL,
    status      VARCHAR(16) NOT NULL DEFAULT 'active',
    context     JSONB NOT NULL DEFAULT '{}',
    metadata    JSONB NOT NULL DEFAULT '{}',
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sessions_tenant_session UNIQUE (tenant_id, session_id)
);
CREATE INDEX ix_sessions_tenant_status ON sessions (tenant_id, status);
CREATE INDEX ix_sessions_created_at ON sessions (created_at);

CREATE TABLE executions (
    execution_id VARCHAR(64) PRIMARY KEY,
    tenant_id    VARCHAR(64) NOT NULL,
    session_id   VARCHAR(64) NOT NULL,
    role_id      VARCHAR(64) NOT NULL,
    status       VARCHAR(24) NOT NULL DEFAULT 'pending',
    plan         JSONB,
    result       JSONB,
    error        JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    CONSTRAINT fk_executions_session FOREIGN KEY (tenant_id, session_id)
        REFERENCES sessions (tenant_id, session_id)
);
CREATE INDEX ix_executions_tenant_session ON executions (tenant_id, session_id);
CREATE INDEX ix_executions_tenant_status ON executions (tenant_id, status);

-- ==== Checkpoint tables (LangGraph 3-table model, EARP-maintained; Gate B P0-1) ====
-- parent_checkpoint_id deliberately has NO self-FK (matches LangGraph): checkpoint
-- truncation/archival must stay order-independent (Gate C P1-4 reviewed, deferred by design).
-- Risk (holistic review P1-2): app bug may cause cross-tenant reference; RLS cannot
-- intercept because it filters the querying tenant, not the referenced tenant.
-- Mitigation: EARP owns all checkpoint write paths (not LangGraph library), every
-- insert carries tenant_id context, and SELECT is RLS-guarded. M5 CheckpointStore
-- implementation must audit this path and add app-layer cross-tenant guards.
CREATE TABLE checkpoints (
    thread_id            VARCHAR(64) NOT NULL,
    checkpoint_ns        TEXT NOT NULL DEFAULT '',
    checkpoint_id        VARCHAR(64) NOT NULL,
    tenant_id            VARCHAR(64) NOT NULL,
    parent_checkpoint_id VARCHAR(64),
    type                 TEXT,
    checkpoint           JSONB NOT NULL,
    metadata             JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE INDEX ix_checkpoints_thread ON checkpoints (thread_id);
CREATE INDEX ix_checkpoints_tenant ON checkpoints (tenant_id);

CREATE TABLE checkpoint_blobs (
    thread_id     VARCHAR(64) NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL,
    version       TEXT NOT NULL,
    tenant_id     VARCHAR(64) NOT NULL,
    type          TEXT NOT NULL,
    blob          BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);
CREATE INDEX ix_checkpoint_blobs_thread ON checkpoint_blobs (thread_id);
CREATE INDEX ix_checkpoint_blobs_tenant ON checkpoint_blobs (tenant_id);

CREATE TABLE checkpoint_writes (
    thread_id     VARCHAR(64) NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(64) NOT NULL,
    task_id       VARCHAR(64) NOT NULL,
    idx           INTEGER NOT NULL,
    tenant_id     VARCHAR(64) NOT NULL,
    channel       TEXT NOT NULL,
    type          TEXT,
    blob          BYTEA NOT NULL,
    task_path     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
CREATE INDEX ix_checkpoint_writes_thread ON checkpoint_writes (thread_id);
CREATE INDEX ix_checkpoint_writes_tenant ON checkpoint_writes (tenant_id);

-- ============ Capability domain ============
CREATE TABLE connector_configs (
    connector_id      VARCHAR(64) PRIMARY KEY,
    tenant_id         VARCHAR(64) NOT NULL,
    adapter_type      VARCHAR(32) NOT NULL,
    config_ciphertext BYTEA,
    key_version       VARCHAR(16),
    status            VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_connector_configs_tenant ON connector_configs (connector_id, tenant_id);

CREATE TABLE business_capabilities (
    capability_id          VARCHAR(64) PRIMARY KEY,
    tenant_id              VARCHAR(64) NOT NULL,
    domain                 VARCHAR(64) NOT NULL,
    name                   TEXT NOT NULL,
    type                   VARCHAR(8) NOT NULL
                           CONSTRAINT ck_capability_type CHECK (type IN ('query','command')),
    input_schema           JSONB NOT NULL DEFAULT '{}',
    output_schema          JSONB NOT NULL DEFAULT '{}',
    required_permissions   TEXT[] NOT NULL DEFAULT '{}',
    visible_roles          TEXT[] NOT NULL DEFAULT '{}',
    fallback_capability_id VARCHAR(64) REFERENCES business_capabilities (capability_id),
    embedding              vector(1536),
    version                VARCHAR(16) NOT NULL DEFAULT '1.0.0',
    status                 VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_business_capabilities_domain ON business_capabilities (domain, tenant_id);

CREATE TABLE capability_calls (
    call_id       VARCHAR(64) PRIMARY KEY,
    tenant_id     VARCHAR(64) NOT NULL,
    execution_id  VARCHAR(64) NOT NULL,
    capability_id VARCHAR(64) NOT NULL,
    status        VARCHAR(24) NOT NULL DEFAULT 'pending',
    latency_ms    INTEGER,
    error         JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_capability_calls_tenant_execution ON capability_calls (tenant_id, execution_id);

CREATE TABLE connector_bindings (
    capability_id VARCHAR(64) NOT NULL REFERENCES business_capabilities (capability_id),
    connector_id  VARCHAR(64) NOT NULL REFERENCES connector_configs (connector_id),
    tenant_id     VARCHAR(64) NOT NULL,
    PRIMARY KEY (capability_id, connector_id, tenant_id)
);

-- ============ Governance domain ============
CREATE TABLE policies (
    policy_id   VARCHAR(64) PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    policy_type VARCHAR(24) NOT NULL,
    rules       JSONB NOT NULL DEFAULT '{}',
    status      VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_policies_tenant_type ON policies (tenant_id, policy_type);

CREATE TABLE policy_bindings (
    policy_id   VARCHAR(64) NOT NULL REFERENCES policies (policy_id),
    entity_type VARCHAR(24) NOT NULL,
    entity_id   VARCHAR(64) NOT NULL,
    tenant_id   VARCHAR(64) NOT NULL,
    PRIMARY KEY (policy_id, entity_type, entity_id, tenant_id)
);

CREATE TABLE audit_logs (
    log_id      BIGSERIAL PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    event_type  VARCHAR(48) NOT NULL,
    entity_type VARCHAR(24),
    entity_id   VARCHAR(64),
    user_id     VARCHAR(64),
    detail      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_logs_tenant_event ON audit_logs (tenant_id, event_type, created_at);

-- ============ Security domain ============
CREATE TABLE encrypted_credentials (
    credential_id   VARCHAR(64) PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    credential_type VARCHAR(32) NOT NULL,
    owner_type      VARCHAR(24),
    owner_id        VARCHAR(64),
    ciphertext      BYTEA NOT NULL,
    key_version     VARCHAR(16) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_encrypted_credentials_tenant_type ON encrypted_credentials (tenant_id, credential_type);

-- ============ Knowledge domain ============
CREATE TABLE knowledge_bases (
    kb_id      VARCHAR(64) PRIMARY KEY,
    tenant_id  VARCHAR(64) NOT NULL,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_knowledge_bases_tenant ON knowledge_bases (kb_id, tenant_id);

CREATE TABLE documents (
    doc_id           VARCHAR(64) PRIMARY KEY,
    tenant_id        VARCHAR(64) NOT NULL,
    kb_id            VARCHAR(64) NOT NULL REFERENCES knowledge_bases (kb_id),
    name             TEXT NOT NULL,
    source_type      VARCHAR(24) NOT NULL DEFAULT 'upload',
    accessible_roles TEXT[] NOT NULL DEFAULT '{}',
    status           VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_documents_tenant_kb ON documents (tenant_id, kb_id);

CREATE TABLE chunks (
    chunk_id  VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    doc_id    VARCHAR(64) NOT NULL REFERENCES documents (doc_id),
    kb_id     VARCHAR(64) NOT NULL REFERENCES knowledge_bases (kb_id),
    content   TEXT NOT NULL,
    embedding vector(1536),
    metadata  JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_chunks_kb ON chunks (chunk_id, kb_id);

-- ============ Conversation domain ============
CREATE TABLE conversations (
    conversation_id VARCHAR(64) PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    user_id         VARCHAR(64) NOT NULL REFERENCES users (user_id),
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_conversations_tenant_user ON conversations (tenant_id, user_id, created_at);

CREATE TABLE messages (
    message_id      VARCHAR(64) PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64) NOT NULL REFERENCES conversations (conversation_id),
    seq             INTEGER NOT NULL,
    role            VARCHAR(16) NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_messages_conversation_seq UNIQUE (conversation_id, seq)
);
"""

_ROLE_AND_GRANTS = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'earp_app') THEN
        -- Dev/test default; production rotates the password out-of-band.
        CREATE ROLE earp_app LOGIN PASSWORD 'earp_app';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO earp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO earp_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO earp_app;
"""


def upgrade() -> None:
    # Timeout guardrails (squawk require-timeout-settings; data-arch section 6.3 discipline):
    # baseline runs on an empty DB, but the preamble sets the pattern for every future migration.
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    op.execute(_DDL)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = current_setting('earp.tenant_id', true));"
        )
    op.execute(_ROLE_AND_GRANTS)


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s';")
    op.execute("SET statement_timeout = '120s';")
    # Reverse dependency order (FK targets last). Policies drop with tables.
    for table in (
        "messages",
        "conversations",
        "chunks",
        "documents",
        "knowledge_bases",
        "encrypted_credentials",
        "audit_logs",
        "policy_bindings",
        "policies",
        "connector_bindings",
        "capability_calls",
        "business_capabilities",
        "connector_configs",
        "checkpoint_writes",
        "checkpoint_blobs",
        "checkpoints",
        "executions",
        "sessions",
        "tenant_account_joins",
        "service_accounts",
        "api_keys",
        "roles",
        "users",
        "org_units",
        "tenants",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
    # extension `vector` and role `earp_app` are intentionally kept (shared, idempotent).
