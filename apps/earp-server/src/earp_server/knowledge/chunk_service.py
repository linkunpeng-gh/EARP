"""Document chunking via langchain-text-splitters + chunk persistence."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def split_text(content: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks using langchain RecursiveCharacterTextSplitter."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\\n\\n", "\\n", ". ", " ", ""],
    )
    return splitter.split_text(content)


async def create_chunks(
    engine: AsyncEngine, tenant_id: str, document_id: str, content: str, content_hash: str,
) -> list[str]:
    """Split document content into chunks and persist. Returns chunk_ids."""
    texts = split_text(content)
    chunk_ids = []
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        for i, chunk_text in enumerate(texts):
            chunk_id = f"chk-{uuid.uuid4().hex[:12]}"
            chunk_hash = hashlib.md5(chunk_text.encode()).hexdigest()
            await conn.execute(
                text(
                    "INSERT INTO chunks (chunk_id, tenant_id, document_id, chunk_index, "
                    "content, content_hash) VALUES (:cid, :tid, :did, :idx, :content, :chash)"
                ),
                {"cid": chunk_id, "tid": tenant_id, "did": document_id, "idx": i,
                 "content": chunk_text, "chash": chunk_hash},
            )
            chunk_ids.append(chunk_id)
        await conn.commit()
    return chunk_ids
