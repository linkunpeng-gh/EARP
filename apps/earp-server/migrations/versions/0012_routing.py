"""enterprise retrieval Phase 1 — soft routing + metadata filtering columns.

Design: arch/design/2026-08-09-enterprise-retrieval-design.md (2026-08-09 会话定稿).
Adds:
  - data_domains.routing_description / routing_embedding / routing_hash
    (DD-level retrieval description + embedding; NULL embedding = keyword-lane only)
  - knowledge_bases.summary_embedding / summary_hash / metadata_schema
    (KB summary embedding for Level 2; metadata_schema = doc metadata field template)
  - documents.metadata (authoritative doc-level metadata; chunks.metadata stays
    unused by design — doc metadata is the single source of truth)
  - GIN (jsonb_path_ops) on documents.metadata for containment filters (@>)

Embedding dim 1024 aligned with 0004 (bge-m3); NULL allowed = graceful degrade
(keyword lane still matches, vector lane skips).

Revision ID: 0012_routing
Revises: 0011_kb_description
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision: str = "0012_routing"
down_revision: str = "0011_kb_description"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s';")

    # DD routing layer
    op.execute("ALTER TABLE data_domains ADD COLUMN IF NOT EXISTS routing_description TEXT")
    op.execute("ALTER TABLE data_domains ADD COLUMN IF NOT EXISTS routing_embedding vector(1024)")
    op.execute("ALTER TABLE data_domains ADD COLUMN IF NOT EXISTS routing_hash TEXT")

    # KB summary + metadata schema template
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS summary_embedding vector(1024)")
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS summary_hash TEXT")
    op.execute(
        "ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS metadata_schema JSONB NOT NULL DEFAULT '[]'::jsonb"
    )

    # authoritative doc-level metadata + GIN for containment filters
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_metadata_gin ON documents USING GIN (metadata jsonb_path_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_metadata_gin")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS metadata")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS metadata_schema")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS summary_hash")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS summary_embedding")
    op.execute("ALTER TABLE data_domains DROP COLUMN IF EXISTS routing_hash")
    op.execute("ALTER TABLE data_domains DROP COLUMN IF EXISTS routing_embedding")
    op.execute("ALTER TABLE data_domains DROP COLUMN IF EXISTS routing_description")
