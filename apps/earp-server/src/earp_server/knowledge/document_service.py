"""Document ingestion — create document row, trigger chunk pipeline."""

from __future__ import annotations

import datetime
import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# auto-injected doc metadata keys — system facts, never manually overridable
# (2026-08-09 enterprise-retrieval design §4.1; store stable ids, not names).
# Extended 2026-08-09: common defaults (original_file_name / uploaded_at /
# updated_at / source) requested by product — all derived at upload time.
# data_classification is deliberately NOT here: it is a mutable business value
# (admin-editable column), a metadata snapshot would go stale (2026-08-09).
AUTO_METADATA_KEYS = frozenset(
    {
        "source_kb",
        "data_domain",
        "original_file_name",
        "uploaded_at",
        "updated_at",
        "source",
    }
)


def normalize_metadata(metadata: dict | None, schema: list[dict]) -> dict:
    """Validate + type-normalize manual metadata against the KB's metadata_schema.

    Strong validation (C-9 decision): unknown keys rejected, types coerced per
    schema ({"year": "2024"} → 2024 for type number). Values are stored as real
    JSON types so containment filters (@>) match exactly.
    """
    if not metadata:
        return {}
    schema_map = {f.get("key"): f for f in schema if f.get("key")}
    result: dict = {}
    for key, value in metadata.items():
        field = schema_map.get(key)
        if field is None:
            raise ValueError(f"元数据字段 '{key}' 不在 KB 的 metadata_schema 中")
        ftype = field.get("type", "string")
        if ftype == "number":
            try:
                if isinstance(value, bool):
                    raise ValueError
                if isinstance(value, (int, float)):
                    result[key] = (
                        int(value) if isinstance(value, float) and value.is_integer() else value
                    )
                else:
                    s = str(value).strip()
                    result[key] = int(s) if s.isdigit() else float(s)
            except (TypeError, ValueError):
                raise ValueError(f"元数据字段 '{key}' 期望 number，收到 '{value}'") from None
        elif ftype == "boolean":
            if isinstance(value, bool):
                result[key] = value
            elif isinstance(value, str) and value.lower() in ("true", "false"):
                result[key] = value.lower() == "true"
            else:
                raise ValueError(f"元数据字段 '{key}' 期望 boolean，收到 '{value}'")
        else:  # string
            result[key] = value if isinstance(value, str) else str(value)
    return result


async def _kb_context(engine: AsyncEngine, tenant_id: str, knowledge_base_id: str) -> dict:
    """Fetch KB data_domain_id + metadata_schema (for doc metadata injection)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text(
                "SELECT data_domain_id, metadata_schema FROM knowledge_bases "
                "WHERE knowledge_base_id = :kid"
            ),
            {"kid": knowledge_base_id},
        )
        r = row.fetchone()
        if r is None:
            raise ValueError(f"knowledge base not found: {knowledge_base_id}")
        return {"data_domain_id": r.data_domain_id, "metadata_schema": r.metadata_schema or []}


async def create_document(
    engine: AsyncEngine,
    tenant_id: str,
    knowledge_base_id: str,
    content: str,
    title: str = "",
    data_classification: str = "internal",
    metadata: dict | None = None,
) -> dict:
    """Create a document row. documents.metadata is authoritative (B-5 decision):

      auto fields (stable ids, not overridable): source_kb / data_domain /
        data_classification — injected from the owning KB + upload context.
      manual fields: validated + type-normalized against KB metadata_schema.
    """
    document_id = f"doc-{uuid.uuid4().hex[:12]}"
    content_hash = hashlib.md5(content.encode()).hexdigest()
    ctx = await _kb_context(engine, tenant_id, knowledge_base_id)

    manual = normalize_metadata(metadata, ctx["metadata_schema"])
    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    doc_metadata = {
        "source_kb": knowledge_base_id,
        "data_domain": ctx["data_domain_id"],
        # common defaults (product request 2026-08-09): file-upload provenance
        "original_file_name": title or "",
        "uploaded_at": now_iso,
        "updated_at": now_iso,
        "source": "upload",
    }
    doc_metadata.update(manual)

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO documents "
                "(document_id, tenant_id, knowledge_base_id, name, title, content, content_hash, "
                "data_classification, metadata) "
                "VALUES (:did, :tid, :kid, :name, :title, :content, :chash, :dclass, :md)"
            ),
            {
                "did": document_id,
                "tid": tenant_id,
                "kid": knowledge_base_id,
                "name": title or "untitled",
                "title": title,
                "content": content,
                "chash": content_hash,
                "dclass": data_classification,
                "md": __import__("json").dumps(doc_metadata, ensure_ascii=False),
            },
        )
        await conn.commit()
    return {"document_id": document_id, "content_hash": content_hash}


async def update_document_metadata(
    engine: AsyncEngine,
    tenant_id: str,
    document_id: str,
    metadata: dict,
) -> dict | None:
    """Edit a document's manual metadata (merged, schema-validated).

    Auto fields (source_kb/data_domain/data_classification) are rejected —
    system facts must not be overridden (A-2 decision); they change only via
    their source (KB move / classification update / re-upload).
    """
    import json

    bad = AUTO_METADATA_KEYS & set(metadata)
    if bad:
        raise ValueError(f"自动字段不可手工覆盖: {sorted(bad)}")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text(
                "SELECT d.metadata, kb.metadata_schema FROM documents d "
                "JOIN knowledge_bases kb ON d.knowledge_base_id = kb.knowledge_base_id "
                "WHERE d.document_id = :did"
            ),
            {"did": document_id},
        )
        r = row.fetchone()
        if r is None:
            return None
        current = dict(r._mapping.get("metadata") or {})
        manual = normalize_metadata(metadata, r._mapping.get("metadata_schema") or [])
        current.update(manual)
        # system refresh: updated_at follows metadata edits (auto key — the
        # server writes it, clients can never pass it)
        current["updated_at"] = datetime.datetime.now(datetime.UTC).isoformat()
        await conn.execute(
            text("UPDATE documents SET metadata = :md WHERE document_id = :did"),
            {"md": json.dumps(current, ensure_ascii=False), "did": document_id},
        )
        await conn.commit()
        return current


async def get_document(engine: AsyncEngine, document_id: str, tenant_id: str) -> dict | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT document_id, title, content, content_hash FROM documents WHERE document_id = :did"),
            {"did": document_id},
        )
        r = row.fetchone()
        return dict(r._mapping) if r else None


async def find_duplicate(
    engine: AsyncEngine,
    tenant_id: str,
    knowledge_base_id: str,
    content_hash: str,
) -> str | None:
    """RecordManager dedup: return existing document_id with same hash in the KB."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT document_id FROM documents WHERE knowledge_base_id = :kid AND content_hash = :chash LIMIT 1"),
            {"kid": knowledge_base_id, "chash": content_hash},
        )
        r = row.fetchone()
        return r.document_id if r else None
