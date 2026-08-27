"""Knowledge admin API service — KB CRUD + document listing + Data Domain aggregates.

Backs admin dashboard pages (PRD-2026-028 §6.5/§6.6): knowledge.html / data-domains.html.
All reads/writes are RLS-scoped via SET LOCAL earp.tenant_id (same pattern as
document_service/chunk_service).
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.knowledge.routing import build_routing_index


async def create_kb(
    engine: AsyncEngine,
    tenant_id: str,
    name: str,
    data_domain_id: str | None = None,
    description: str | None = None,
    retrieval_model: dict | None = None,
    indexing_technique: str = "high_quality",
    metadata_schema: list[dict] | None = None,
    summary_text: str | None = None,
) -> dict:
    """Create a knowledge base with optional retrieval/chunking config.

    retrieval_model (aligned with 0006_add_process_rules retrieval_model JSONB):
      {
        "segmentation": {"separator": "\n\n", "max_tokens": 1000, "chunk_overlap": 200},
        "mode": "vector", "top_k": 5, "score_threshold": 0.0, "model": "bge-m3"
      }
    The segmentation block drives create_chunks(); the rest drives retrieval
    defaults (consumed by the UI / future retrieval endpoints).

    metadata_schema: doc-level metadata field template
      [{"key": "department", "type": "string", "required": false}, ...]
      (enterprise-retrieval design §4.1; validated in schemas/endpoint).
    """
    kb_id = f"kb-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO knowledge_bases "
                "(knowledge_base_id, tenant_id, name, data_domain_id, description, "
                "retrieval_model, indexing_technique, metadata_schema, summary_text) "
                "VALUES (:kid, :tid, :name, :dd, :desc, :rm, :idx, :ms, :st)"
            ),
            {
                "kid": kb_id,
                "tid": tenant_id,
                "name": name,
                "dd": data_domain_id,
                "desc": description,
                "rm": json.dumps(retrieval_model) if retrieval_model else None,
                "idx": indexing_technique,
                "ms": json.dumps(metadata_schema, ensure_ascii=False) if metadata_schema is not None else "[]",
                "st": summary_text,
            },
        )
        await conn.commit()
    # routing index: new KB changes the domain description + needs its own summary
    await build_routing_index(engine, tenant_id, dd_ids=[data_domain_id] if data_domain_id else None, kb_ids=[kb_id])
    return {"knowledge_base_id": kb_id, "name": name, "data_domain_id": data_domain_id}


async def update_kb(
    engine: AsyncEngine,
    tenant_id: str,
    kb_id: str,
    *,
    name: str | None = None,
    data_domain_id: str | None = None,
    description: str | None = None,
    indexing_technique: str | None = None,
    metadata_schema: list[dict] | None = None,
    summary_text: str | None = None,
) -> dict | None:
    """Update KB basic attributes (name / data domain / description / indexing / schema / summary).

    Returns updated row, or None if the KB doesn't exist. Raises ValueError
    when the target data domain doesn't exist (FK integrity). Rebuilds routing
    index for the affected domains (old + new when the KB moves domain).
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        kb_row = await conn.execute(
            text("SELECT knowledge_base_id, data_domain_id FROM knowledge_bases WHERE knowledge_base_id = :kid"),
            {"kid": kb_id},
        )
        kb = kb_row.fetchone()
        if kb is None:
            return None
        old_dd = kb.data_domain_id

        if data_domain_id is not None:
            dd = await conn.execute(
                text("SELECT 1 FROM data_domains WHERE data_domain_id = :dd"),
                {"dd": data_domain_id},
            )
            if dd.fetchone() is None:
                raise ValueError(f"Data domain not found: {data_domain_id}")

        sets: list[str] = []
        params: dict = {"kid": kb_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name
        if data_domain_id is not None:
            sets.append("data_domain_id = :dd")
            params["dd"] = data_domain_id
        if description is not None:
            sets.append("description = :desc")
            params["desc"] = description
        if indexing_technique is not None:
            sets.append("indexing_technique = :idx")
            params["idx"] = indexing_technique
        if metadata_schema is not None:
            sets.append("metadata_schema = :ms")
            params["ms"] = json.dumps(metadata_schema, ensure_ascii=False)
        if summary_text is not None:
            sets.append("summary_text = :st")
            params["st"] = summary_text
        if not sets:
            return {"knowledge_base_id": kb_id}
        await conn.execute(
            text(
                f"UPDATE knowledge_bases SET {', '.join(sets)} "
                f"WHERE knowledge_base_id = :kid RETURNING knowledge_base_id"
            ),
            params,
        )
        await conn.commit()
    # routing index: KB summary changed (name/desc) and/or domain membership changed
    new_dd = data_domain_id if data_domain_id is not None else old_dd
    dd_ids = {d for d in (old_dd, new_dd) if d}
    await build_routing_index(engine, tenant_id, dd_ids=list(dd_ids) or None, kb_ids=[kb_id])
    return await list_kb_detail(engine, tenant_id, kb_id)


async def list_kb_detail(engine: AsyncEngine, tenant_id: str, kb_id: str) -> dict | None:
    """Fetch a single KB row (with counts) — used after updates."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT kb.knowledge_base_id, kb.name, kb.description, kb.data_domain_id, "
                "kb.retrieval_model, kb.indexing_technique, kb.metadata_schema, kb.summary_text, "
                "COUNT(DISTINCT d.document_id) AS doc_count, COUNT(c.chunk_id) AS chunk_count "
                "FROM knowledge_bases kb "
                "LEFT JOIN documents d ON d.knowledge_base_id = kb.knowledge_base_id "
                "LEFT JOIN chunks c ON c.document_id = d.document_id "
                "WHERE kb.knowledge_base_id = :kid "
                "GROUP BY kb.knowledge_base_id"
            ),
            {"kid": kb_id},
        )
        r = rows.fetchone()
        return dict(r._mapping) if r else None


async def update_kb_retrieval(
    engine: AsyncEngine,
    tenant_id: str,
    kb_id: str,
    retrieval_model: dict | None,
    indexing_technique: str | None = None,
) -> dict | None:
    """Update a KB's retrieval/chunking config (retrieval_model JSONB).

    Returns the updated KB row, or None if the KB doesn't exist.
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        sql = (
            "UPDATE knowledge_bases SET retrieval_model = :rm"
            + (", indexing_technique = :idx" if indexing_technique else "")
            + " WHERE knowledge_base_id = :kid RETURNING knowledge_base_id, retrieval_model, indexing_technique"
        )
        result = await conn.execute(
            text(sql),
            {
                "kid": kb_id,
                "rm": json.dumps(retrieval_model) if retrieval_model else None,
                **({"idx": indexing_technique} if indexing_technique else {}),
            },
        )
        await conn.commit()
        r = result.fetchone()
        if r is None:
            return None
        return {
            "knowledge_base_id": r.knowledge_base_id,
            "retrieval_model": r.retrieval_model,
            "indexing_technique": r.indexing_technique,
        }


async def reindex_kb(engine: AsyncEngine, tenant_id: str, kb_id: str) -> dict | None:
    """Re-chunk + re-embed every document of a KB using its saved chunking config.

    Old chunks are removed only AFTER the new chunks are successfully embedded,
    so a mid-flight failure keeps the previous index intact. Returns per-document
    stats, or None if the KB doesn't exist.
    """
    from earp_server.knowledge.chunk_service import create_chunks
    from earp_server.knowledge.embedding_service import embed_chunks

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        kb = await conn.execute(
            text("SELECT retrieval_model FROM knowledge_bases WHERE knowledge_base_id = :kid"),
            {"kid": kb_id},
        )
        kb_row = kb.fetchone()
        if kb_row is None:
            return None
        rm = kb_row.retrieval_model
        docs = await conn.execute(
            text("SELECT document_id, content FROM documents WHERE knowledge_base_id = :kid ORDER BY created_at"),
            {"kid": kb_id},
        )
        doc_rows = [dict(r._mapping) for r in docs.fetchall()]
        old_ids = await conn.execute(
            text(
                "SELECT c.chunk_id FROM chunks c JOIN documents d ON d.document_id = c.document_id "
                "WHERE d.knowledge_base_id = :kid"
            ),
            {"kid": kb_id},
        )
        old_chunk_ids = [r.chunk_id for r in old_ids.fetchall()]

    rules = {"segmentation": rm["segmentation"]} if rm and rm.get("segmentation") else None
    stats: dict = {"kb_id": kb_id, "documents": len(doc_rows), "total_chunks": 0, "per_document": []}

    for doc in doc_rows:
        did = doc["document_id"]
        new_ids = await create_chunks(engine, tenant_id, did, doc["content"], rules=rules)
        try:
            await embed_chunks(engine, tenant_id, new_ids)
        except Exception:
            # roll back this document's new chunks; old index stays untouched
            async with engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
                if new_ids:
                    placeholders = ", ".join(f":cid{i}" for i in range(len(new_ids)))
                    await conn.execute(
                        text(f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})"),
                        {f"cid{i}": cid for i, cid in enumerate(new_ids)},
                    )
                    await conn.commit()
            raise
        stats["total_chunks"] += len(new_ids)
        stats["per_document"].append({"document_id": did, "chunks": len(new_ids)})

    # All new chunks embedded — now safe to drop the old ones
    if old_chunk_ids:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            placeholders = ", ".join(f":cid{i}" for i in range(len(old_chunk_ids)))
            await conn.execute(
                text(f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})"),
                {f"cid{i}": cid for i, cid in enumerate(old_chunk_ids)},
            )
            await conn.commit()
    return stats


async def list_kbs(
    engine: AsyncEngine,
    tenant_id: str,
    data_domain_id: str | None = None,
) -> list[dict]:
    """KB list with aggregated doc/chunk counts and access control for search."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        sql = text(
            "SELECT kb.knowledge_base_id, kb.name, kb.description, kb.data_domain_id, kb.accessible_roles, "
            "kb.retrieval_model, kb.indexing_technique, kb.metadata_schema, kb.summary_text, "
            "COUNT(DISTINCT d.document_id) AS doc_count, COUNT(c.chunk_id) AS chunk_count "
            "FROM knowledge_bases kb "
            "LEFT JOIN documents d ON d.knowledge_base_id = kb.knowledge_base_id "
            "LEFT JOIN chunks c ON c.document_id = d.document_id "
            "WHERE kb.tenant_id = :tid "
            + ("AND kb.data_domain_id = :dd " if data_domain_id else "")
            + "GROUP BY kb.knowledge_base_id ORDER BY kb.name"
        )
        params: dict = {"tid": tenant_id}
        if data_domain_id:
            params["dd"] = data_domain_id
        rows = await conn.execute(sql, params)
        return [dict(r._mapping) for r in rows.fetchall()]


async def delete_kb(engine: AsyncEngine, tenant_id: str, kb_id: str) -> int:
    """Delete a KB and its documents/chunks. Returns deleted KB rows (0 or 1)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        # chunks first (FK), then documents, then KB
        await conn.execute(
            text(
                "DELETE FROM chunks WHERE document_id IN "
                "(SELECT document_id FROM documents WHERE knowledge_base_id = :kid)"
            ),
            {"kid": kb_id},
        )
        await conn.execute(text("DELETE FROM documents WHERE knowledge_base_id = :kid"), {"kid": kb_id})
        result = await conn.execute(text("DELETE FROM knowledge_bases WHERE knowledge_base_id = :kid"), {"kid": kb_id})
        await conn.commit()
        return result.rowcount


async def list_documents(engine: AsyncEngine, tenant_id: str, kb_id: str) -> list[dict]:
    """Documents of a KB with char count, recall count, status and process rule."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT d.document_id, d.name, d.title, d.data_classification, d.status, "
                "d.created_at, d.recall_count, length(d.content) AS char_count, "
                "d.process_rule_id, pr.rules::text AS process_rule, d.metadata, "
                "COUNT(c.chunk_id) AS chunk_count "
                "FROM documents d "
                "LEFT JOIN dataset_process_rules pr ON pr.process_rule_id = d.process_rule_id "
                "LEFT JOIN chunks c ON c.document_id = d.document_id "
                "WHERE d.knowledge_base_id = :kid "
                "GROUP BY d.document_id, pr.process_rule_id, pr.rules::text "
                "ORDER BY d.created_at"
            ),
            {"kid": kb_id},
        )
        result = []
        for r in rows.fetchall():
            m = dict(r._mapping)
            if m.get("process_rule") and isinstance(m["process_rule"], str):
                try:
                    m["process_rule"] = json.loads(m["process_rule"])
                except json.JSONDecodeError:
                    pass
            result.append(m)
        return result


async def update_document_status(
    engine: AsyncEngine,
    tenant_id: str,
    document_id: str,
    status: str,
) -> dict | None:
    """Enable/disable a document. Disabled docs are excluded from retrieval."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text("UPDATE documents SET status = :st WHERE document_id = :did RETURNING document_id, status"),
            {"st": status, "did": document_id},
        )
        await conn.commit()
        r = result.fetchone()
        return dict(r._mapping) if r else None


async def save_document_process_rule(
    engine: AsyncEngine,
    tenant_id: str,
    document_id: str,
    rules: dict,
) -> dict | None:
    """Upsert a per-document chunking rule (dataset_process_rules row + FK).

    Returns None if the document doesn't exist. The rule is inherited from the
    KB when missing (handled by the upload/reindex callers).
    """
    import uuid as _uuid

    rule_id = f"rule-{_uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        doc = await conn.execute(
            text("SELECT knowledge_base_id FROM documents WHERE document_id = :did"),
            {"did": document_id},
        )
        d = doc.fetchone()
        if d is None:
            return None
        kb_id = d.knowledge_base_id
        # upsert: reuse existing rule row if the doc already has one
        existing = await conn.execute(
            text("SELECT process_rule_id FROM documents WHERE document_id = :did"),
            {"did": document_id},
        )
        e = existing.fetchone()
        if e and e.process_rule_id:
            await conn.execute(
                text("UPDATE dataset_process_rules SET rules = :rules, mode = 'custom' WHERE process_rule_id = :rid"),
                {"rules": json.dumps(rules), "rid": e.process_rule_id},
            )
            rule_id = e.process_rule_id
        else:
            await conn.execute(
                text(
                    "INSERT INTO dataset_process_rules (process_rule_id, tenant_id, dataset_id, mode, rules) "
                    "VALUES (:rid, :tid, :kid, 'custom', :rules)"
                ),
                {"rid": rule_id, "tid": tenant_id, "kid": kb_id, "rules": json.dumps(rules)},
            )
            await conn.execute(
                text("UPDATE documents SET process_rule_id = :rid WHERE document_id = :did"),
                {"rid": rule_id, "did": document_id},
            )
        await conn.commit()
    return {"document_id": document_id, "process_rule_id": rule_id, "rules": rules}


async def get_document_detail(engine: AsyncEngine, tenant_id: str, document_id: str) -> dict | None:
    """Single document detail incl. its saved process rule and KB context."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text(
                "SELECT d.document_id, d.knowledge_base_id, d.name, d.title, d.status, "
                "d.data_classification, d.created_at, d.recall_count, "
                "length(d.content) AS char_count, d.process_rule_id, pr.rules::text AS process_rule, "
                "kb.name AS kb_name, kb.retrieval_model::text AS kb_retrieval_model "
                "FROM documents d "
                "JOIN knowledge_bases kb ON kb.knowledge_base_id = d.knowledge_base_id "
                "LEFT JOIN dataset_process_rules pr ON pr.process_rule_id = d.process_rule_id "
                "WHERE d.document_id = :did"
            ),
            {"did": document_id},
        )
        r = row.fetchone()
        if r is None:
            return None
        m = dict(r._mapping)
        for key in ("process_rule", "kb_retrieval_model"):
            v = m.get(key)
            if v and isinstance(v, str):
                try:
                    m[key] = json.loads(v)
                except json.JSONDecodeError:
                    pass
        return m


async def reindex_document(engine: AsyncEngine, tenant_id: str, document_id: str) -> dict | None:
    """Re-chunk + re-embed ONE document using its own rule (fallback: KB config).

    Returns stats or None if the document doesn't exist.
    """
    from earp_server.knowledge.chunk_service import create_chunks
    from earp_server.knowledge.embedding_service import embed_chunks

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        doc = await conn.execute(
            text(
                "SELECT d.document_id, d.content, d.process_rule_id, pr.rules, "
                "kb.retrieval_model FROM documents d "
                "JOIN knowledge_bases kb ON kb.knowledge_base_id = d.knowledge_base_id "
                "LEFT JOIN dataset_process_rules pr ON pr.process_rule_id = d.process_rule_id "
                "WHERE d.document_id = :did"
            ),
            {"did": document_id},
        )
        r = doc.fetchone()
        if r is None:
            return None
        content = r.content
        # doc rule > KB rule > global default
        rules = None
        if r.rules and r.rules.get("segmentation"):
            rules = {"segmentation": r.rules["segmentation"]}
        elif r.retrieval_model and r.retrieval_model.get("segmentation"):
            rules = {"segmentation": r.retrieval_model["segmentation"]}
        # old chunk ids
        old = await conn.execute(text("SELECT chunk_id FROM chunks WHERE document_id = :did"), {"did": document_id})
        old_ids = [x.chunk_id for x in old.fetchall()]

    new_ids = await create_chunks(engine, tenant_id, document_id, content, rules=rules)
    try:
        await embed_chunks(engine, tenant_id, new_ids)
    except Exception:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            if new_ids:
                ph = ", ".join(f":c{i}" for i in range(len(new_ids)))
                await conn.execute(
                    text(f"DELETE FROM chunks WHERE chunk_id IN ({ph})"),
                    {f"c{i}": cid for i, cid in enumerate(new_ids)},
                )
                await conn.commit()
        raise
    if old_ids:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            ph = ", ".join(f":c{i}" for i in range(len(old_ids)))
            await conn.execute(
                text(f"DELETE FROM chunks WHERE chunk_id IN ({ph})"),
                {f"c{i}": cid for i, cid in enumerate(old_ids)},
            )
            await conn.commit()
    return {"document_id": document_id, "chunks": len(new_ids)}


async def update_document_classification(
    engine: AsyncEngine,
    tenant_id: str,
    document_id: str,
    data_classification: str,
) -> dict | None:
    """Update a document's classification (must respect DD ceiling — validated by caller via check).

    Also strips any stale data_classification snapshot from documents.metadata
    (the value is a mutable business attribute, not an auto field — 2026-08-09).
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE documents SET data_classification = :cls, "
                "metadata = metadata - 'data_classification' "
                "WHERE document_id = :did RETURNING document_id, data_classification"
            ),
            {"cls": data_classification, "did": document_id},
        )
        await conn.commit()
        r = result.fetchone()
        return dict(r._mapping) if r else None


async def delete_document(engine: AsyncEngine, tenant_id: str, document_id: str) -> int:
    """Delete a document (+ chunks). Rebuilds the owning KB summary embedding
    (doc titles are part of the summary text) — routing write-time cascade.
    """
    kb_id: str | None = None
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT knowledge_base_id FROM documents WHERE document_id = :did"), {"did": document_id}
        )
        r = row.fetchone()
        if r is not None:
            kb_id = r.knowledge_base_id
        await conn.execute(text("DELETE FROM chunks WHERE document_id = :did"), {"did": document_id})
        result = await conn.execute(text("DELETE FROM documents WHERE document_id = :did"), {"did": document_id})
        await conn.commit()
    if kb_id is not None:
        await build_routing_index(engine, tenant_id, kb_ids=[kb_id])
    return result.rowcount


async def list_data_domains(engine: AsyncEngine, tenant_id: str) -> list[dict]:
    """Data Domains with aggregated KB/doc counts (admin dashboard §6.6)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT dd.data_domain_id, dd.name, dd.description, dd.data_classification, dd.owner, dd.status, "
                "dd.routing_description, "
                "COUNT(DISTINCT kb.knowledge_base_id) AS kb_count, COUNT(d.document_id) AS doc_count "
                "FROM data_domains dd "
                "LEFT JOIN knowledge_bases kb ON kb.data_domain_id = dd.data_domain_id "
                "LEFT JOIN documents d ON d.knowledge_base_id = kb.knowledge_base_id "
                "WHERE dd.tenant_id = :tid GROUP BY dd.data_domain_id, dd.name, dd.description, "
                "dd.data_classification, dd.owner, dd.status, dd.routing_description ORDER BY dd.name"
            ),
            {"tid": tenant_id},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def create_data_domain(
    engine: AsyncEngine,
    tenant_id: str,
    data_domain_id: str,
    name: str,
    data_classification: str = "internal",
    description: str | None = None,
    owner: str | None = None,
) -> dict:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO data_domains "
                "(data_domain_id, tenant_id, name, description, data_classification, owner, status) "
                "VALUES (:dd, :tid, :name, :desc, :cls, :owner, 'active') "
                "ON CONFLICT (data_domain_id, tenant_id) DO UPDATE SET name = EXCLUDED.name"
            ),
            {
                "dd": data_domain_id,
                "tid": tenant_id,
                "name": name,
                "desc": description,
                "cls": data_classification,
                "owner": owner,
            },
        )
        await conn.commit()
    await build_routing_index(engine, tenant_id, dd_ids=[data_domain_id])
    return {"data_domain_id": data_domain_id, "name": name, "data_classification": data_classification}


class DataDomainInUseError(Exception):
    """Raised when deleting a data domain that still has knowledge bases attached."""


async def update_data_domain(
    engine: AsyncEngine,
    tenant_id: str,
    data_domain_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    data_classification: str | None = None,
    owner: str | None = None,
    routing_description: str | None = None,
) -> dict | None:
    """Update a data domain's basic attributes. Returns updated row or None.

    routing_description: retrieval-specific description (empty/NULL = auto
    aggregate from DD + KB names; non-empty = manual override). Changing it
    triggers a routing embedding rebuild.
    """
    sets: list[str] = []
    params: dict = {"dd": data_domain_id, "tid": tenant_id}
    if name is not None:
        sets.append("name = :name")
        params["name"] = name
    if description is not None:
        sets.append("description = :desc")
        params["desc"] = description
    if data_classification is not None:
        sets.append("data_classification = :cls")
        params["cls"] = data_classification
    if owner is not None:
        sets.append("owner = :owner")
        params["owner"] = owner
    if routing_description is not None:
        sets.append("routing_description = :rdesc")
        params["rdesc"] = routing_description
    if not sets:
        return {"data_domain_id": data_domain_id}
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                f"UPDATE data_domains SET {', '.join(sets)} "
                "WHERE data_domain_id = :dd AND tenant_id = :tid "
                "RETURNING data_domain_id, name, description, data_classification, owner, status"
            ),
            params,
        )
        await conn.commit()
        r = result.fetchone()
        if r is None:
            return None
    await build_routing_index(engine, tenant_id, dd_ids=[data_domain_id])
    return dict(r._mapping)


async def delete_data_domain(engine: AsyncEngine, tenant_id: str, data_domain_id: str) -> dict:
    """Delete an empty data domain (RLS-scoped).

    Refuses (DataDomainInUseError) when knowledge bases reference the domain —
    the caller surfaces a 409. The domain-map rows are cleaned up in the same
    transaction; standard seeded domains are deletable too (re-seeded on next
    startup by seed_demo_tenant via ON CONFLICT DO NOTHING).
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        # existence + in-use check
        dd = await conn.execute(
            text("SELECT data_domain_id FROM data_domains WHERE data_domain_id = :dd"),
            {"dd": data_domain_id},
        )
        if dd.fetchone() is None:
            return {"data_domain_id": data_domain_id, "deleted": False, "reason": "not_found"}
        kb = await conn.execute(
            text("SELECT 1 FROM knowledge_bases WHERE data_domain_id = :dd LIMIT 1"),
            {"dd": data_domain_id},
        )
        if kb.fetchone() is not None:
            raise DataDomainInUseError(f"Data domain '{data_domain_id}' has knowledge bases — delete them first")
        # remove map rows + the domain itself in one transaction
        await conn.execute(
            text("DELETE FROM business_domain_data_domain_map WHERE data_domain_id = :dd"),
            {"dd": data_domain_id},
        )
        await conn.execute(
            text("DELETE FROM data_domains WHERE data_domain_id = :dd"),
            {"dd": data_domain_id},
        )
        await conn.commit()
    return {"data_domain_id": data_domain_id, "deleted": True}
