"""Schema alignment: knowledge model column names (kb_id→knowledge_base_id etc).

Fixes drift between M0 DDL (kb_id/doc_id) and M4 code (knowledge_base_id /
document_id / title / content / content_hash / chunk_index). M4 ingestion code
was never exercised against the real schema (no integration test covered the
upload path) — this migration + tests/test_knowledge_pipeline.py close that gap.

PostgreSQL automatically propagates column renames to referencing FK
constraints, so renaming parent PKs keeps child FKs consistent.

Revision ID: 0007_schema_alignment
Revises: 0006
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision: str = "0007_schema_alignment"
down_revision: str = "0006"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # knowledge_bases: kb_id → knowledge_base_id; + accessible_roles (search uses kb.accessible_roles)
    op.execute("ALTER TABLE knowledge_bases RENAME COLUMN kb_id TO knowledge_base_id")
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS accessible_roles TEXT[] NOT NULL DEFAULT '{}'")

    # documents: doc_id → document_id, kb_id → knowledge_base_id; + content fields
    op.execute("ALTER TABLE documents RENAME COLUMN doc_id TO document_id")
    op.execute("ALTER TABLE documents RENAME COLUMN kb_id TO knowledge_base_id")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS title TEXT")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content TEXT")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT")

    # chunks: doc_id → document_id, kb_id → knowledge_base_id; + index/hash columns
    op.execute("ALTER TABLE chunks RENAME COLUMN doc_id TO document_id")
    op.execute("ALTER TABLE chunks RENAME COLUMN kb_id TO knowledge_base_id")
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_index INTEGER")
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_hash TEXT")

    # data_domains: Data Domain is tenant-scoped (RLS) — the PK must include
    # tenant_id so different tenants can register the same domain id
    # (e.g. equipment_data) without PK collisions. Order matters: drop dependent
    # FKs before the PK, rebuild PK first then composite FKs.
    op.execute("ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS knowledge_bases_data_domain_id_fkey")
    op.execute("ALTER TABLE business_domain_data_domain_map DROP CONSTRAINT IF EXISTS business_domain_data_domain_map_data_domain_id_fkey")
    op.execute("ALTER TABLE data_domains DROP CONSTRAINT IF EXISTS data_domains_pkey")
    op.execute("ALTER TABLE data_domains ADD PRIMARY KEY (data_domain_id, tenant_id)")
    op.execute(
        "ALTER TABLE knowledge_bases ADD CONSTRAINT knowledge_bases_data_domain_id_fkey "
        "FOREIGN KEY (data_domain_id, tenant_id) "
        "REFERENCES data_domains (data_domain_id, tenant_id)"
    )
    op.execute(
        "ALTER TABLE business_domain_data_domain_map ADD CONSTRAINT business_domain_data_domain_map_data_domain_id_fkey "
        "FOREIGN KEY (data_domain_id, tenant_id) "
        "REFERENCES data_domains (data_domain_id, tenant_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases RENAME COLUMN knowledge_base_id TO kb_id")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS accessible_roles")
    op.execute("ALTER TABLE documents RENAME COLUMN document_id TO doc_id")
    op.execute("ALTER TABLE documents RENAME COLUMN knowledge_base_id TO kb_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS title")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content_hash")
    op.execute("ALTER TABLE chunks RENAME COLUMN document_id TO doc_id")
    op.execute("ALTER TABLE chunks RENAME COLUMN knowledge_base_id TO kb_id")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS chunk_index")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS content_hash")
    # reverse data_domains composite PK: drop composite FKs → drop composite PK
    # → restore single-column PK → restore single-column FKs.
    op.execute("ALTER TABLE business_domain_data_domain_map DROP CONSTRAINT IF EXISTS business_domain_data_domain_map_data_domain_id_fkey")
    op.execute("ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS knowledge_bases_data_domain_id_fkey")
    op.execute("ALTER TABLE data_domains DROP CONSTRAINT IF EXISTS data_domains_pkey")
    op.execute("ALTER TABLE data_domains ADD PRIMARY KEY (data_domain_id)")
    op.execute(
        "ALTER TABLE business_domain_data_domain_map ADD CONSTRAINT business_domain_data_domain_map_data_domain_id_fkey "
        "FOREIGN KEY (data_domain_id) REFERENCES data_domains (data_domain_id)"
    )
    op.execute(
        "ALTER TABLE knowledge_bases ADD CONSTRAINT knowledge_bases_data_domain_id_fkey "
        "FOREIGN KEY (data_domain_id) REFERENCES data_domains (data_domain_id)"
    )
