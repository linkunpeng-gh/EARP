"""Ontology layer — TBox/ABox tables + RLS (PRD-2026-030 M1).

7 new tenant-scoped tables:
  TBox:  entity_types, relation_types, capability_entity_map
  ABox:  entities, facts, entity_profiles, entity_timeline

Seeds (13 entity types + 12 relation types) are injected per-tenant by
ontology/tbox_service.init_tenant_tbox (ON CONFLICT DO NOTHING) — migrations
cannot seed tenant data (tenant_id is not known at migrate time).

Revision ID: 0008_ontology
Revises: 0007
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision: str = "0008_ontology"
down_revision: str = "0007_schema_alignment"
branch_labels: None = None
depends_on: None = None

_TABLES: tuple[str, ...] = (
    "entity_types",
    "relation_types",
    "capability_entity_map",
    "entities",
    "facts",
    "entity_profiles",
    "entity_timeline",
)


def _enable_rls() -> None:
    for tbl in _TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tbl} "
            f"USING (tenant_id = current_setting('earp.tenant_id', true))"
        )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_types (
            entity_type_id  VARCHAR(64) NOT NULL,
            tenant_id       VARCHAR(64) NOT NULL,
            name            TEXT NOT NULL,
            kind            VARCHAR(16) NOT NULL DEFAULT 'object'
                            CHECK (kind IN ('object','concept','metric')),
            description     TEXT,
            data_domain_id  VARCHAR(64),
            attributes      JSONB NOT NULL DEFAULT '{}',
            owner           TEXT,
            version         VARCHAR(16) NOT NULL DEFAULT '1.0.0',
            status          VARCHAR(16) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('draft','active','deprecated')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (entity_type_id, tenant_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE relation_types (
            relation_type_id VARCHAR(64) NOT NULL,
            tenant_id        VARCHAR(64) NOT NULL,
            name             TEXT NOT NULL,
            source_type      VARCHAR(128) NOT NULL,   -- comma-separated entity type ids
            target_type      VARCHAR(128) NOT NULL,   -- comma-separated entity type ids
            cardinality      VARCHAR(8) NOT NULL CHECK (cardinality IN ('1:1','1:N','N:1','N:M')),
            status           VARCHAR(16) NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active','deprecated')),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (relation_type_id, tenant_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE capability_entity_map (
            capability_id   VARCHAR(64) NOT NULL,
            entity_type_id  VARCHAR(64) NOT NULL,
            tenant_id       VARCHAR(64) NOT NULL,
            operation       VARCHAR(8) NOT NULL DEFAULT 'read'
                            CHECK (operation IN ('read','write','both')),
            status          VARCHAR(16) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','deprecated')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (capability_id, entity_type_id, tenant_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE entities (
            entity_id       VARCHAR(64) PRIMARY KEY,
            tenant_id       VARCHAR(64) NOT NULL,
            entity_type_id  VARCHAR(64) NOT NULL,
            name            TEXT NOT NULL,
            business_code   TEXT,
            attributes      JSONB NOT NULL DEFAULT '{}',
            source_mode     VARCHAR(16) NOT NULL DEFAULT 'extracted'
                            CHECK (source_mode IN ('virtual','synced','extracted')),
            source_ref      TEXT,
            data_domain_id  VARCHAR(64),
            status          VARCHAR(16) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','deprecated','merged')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE facts (
            fact_id          VARCHAR(64) PRIMARY KEY,
            tenant_id        VARCHAR(64) NOT NULL,
            source_entity_id VARCHAR(64) NOT NULL,
            relation_type_id VARCHAR(64) NOT NULL,
            target_entity_id VARCHAR(64) NOT NULL,
            confidence       FLOAT NOT NULL DEFAULT 1.0,
            source_ref       TEXT,
            valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
            valid_to         TIMESTAMPTZ,
            status           VARCHAR(16) NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active','superseded','revoked')),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE entity_profiles (
            entity_profile_id VARCHAR(64) PRIMARY KEY,
            tenant_id         VARCHAR(64) NOT NULL,
            entity_id         VARCHAR(64) NOT NULL UNIQUE,
            profile           JSONB NOT NULL,
            profile_version   INT NOT NULL DEFAULT 1,
            compiled_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE entity_timeline (
            entity_timeline_id VARCHAR(64) PRIMARY KEY,
            tenant_id          VARCHAR(64) NOT NULL,
            entity_id          VARCHAR(64) NOT NULL,
            event_type         VARCHAR(32) NOT NULL,
            payload            JSONB NOT NULL DEFAULT '{}',
            occurred_at        TIMESTAMPTZ NOT NULL,
            source_ref         TEXT
        );
        """
    )

    # Indexes
    op.execute("CREATE INDEX ix_facts_source_rel ON facts (source_entity_id, relation_type_id)")
    op.execute("CREATE INDEX ix_facts_target ON facts (target_entity_id)")
    op.execute("CREATE INDEX ix_facts_rel_target ON facts (relation_type_id, target_entity_id)")
    op.execute("CREATE INDEX ix_facts_valid_to ON facts (valid_to)")
    op.execute("CREATE INDEX ix_entities_type_dd ON entities (entity_type_id, data_domain_id)")
    op.execute("CREATE INDEX ix_entities_name ON entities (name)")
    op.execute("CREATE INDEX ix_entities_bizcode ON entities (business_code)")
    op.execute("CREATE INDEX ix_timeline_entity_ts ON entity_timeline (entity_id, occurred_at DESC)")

    _enable_rls()


def downgrade() -> None:
    for tbl in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
