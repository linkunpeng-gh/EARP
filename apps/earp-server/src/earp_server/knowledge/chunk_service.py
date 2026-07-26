"""Document chunking — parameterized by process rules (Dify-compatible config)."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# Dify-compatible defaults
DEFAULT_RULES = {
    "pre_processing_rules": [
        {"id": "remove_extra_spaces", "enabled": True},
        {"id": "remove_urls_emails", "enabled": False},
    ],
    "segmentation": {
        "separator": "\\n\\n",
        "max_tokens": 1000,
        "chunk_overlap": 200,
    },
    "parent_mode": "full-doc",
    "subchunk_segmentation": {
        "separator": "\\n",
        "max_tokens": 500,
        "chunk_overlap": 100,
    },
}


def apply_preprocessing(text: str, rules: list[dict]) -> str:
    for rule in rules or []:
        if not rule.get("enabled"):
            continue
        rid = rule["id"]
        if rid == "remove_extra_spaces":
            text = " ".join(text.split())
        elif rid == "remove_urls_emails":
            import re

            text = re.sub(r"https?://\S+|www\.\S+|\S+@\S+\.\S+", "", text)
    return text


def split_text(
    content: str,
    separator: str = "\\n\\n",
    max_tokens: int = 1000,
    chunk_overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks. Uses token-approximated sizing (chars / 4 ≈ tokens)."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    chunk_chars = max_tokens * 4  # ~4 chars per token for CJK
    overlap_chars = chunk_overlap * 4
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_chars,
        chunk_overlap=overlap_chars,
        separators=[separator, "\\n", ". ", " ", ""],
    )
    return splitter.split_text(content)


def build_preview(content: str, rules: dict | None = None) -> list[dict]:
    """Return chunk preview without persisting. Returns [{index, content_preview, char_count}, ...]."""
    rules = rules or DEFAULT_RULES
    seg = rules.get("segmentation", DEFAULT_RULES["segmentation"])
    processed = apply_preprocessing(content, rules.get("pre_processing_rules", []))
    chunks = split_text(processed, seg["separator"], seg["max_tokens"], seg["chunk_overlap"])
    return [{"index": i, "content_preview": c[:120], "char_count": len(c)} for i, c in enumerate(chunks[:10])]


async def create_chunks(
    engine: AsyncEngine,
    tenant_id: str,
    document_id: str,
    content: str,
    rules: dict | None = None,
) -> list[str]:
    """Split document content into chunks and persist. Returns chunk_ids."""
    rules = rules or DEFAULT_RULES
    seg = rules.get("segmentation", DEFAULT_RULES["segmentation"])

    processed = apply_preprocessing(content, rules.get("pre_processing_rules", []))
    texts = split_text(processed, seg["separator"], seg["max_tokens"], seg["chunk_overlap"])

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
                {
                    "cid": chunk_id,
                    "tid": tenant_id,
                    "did": document_id,
                    "idx": i,
                    "content": chunk_text,
                    "chash": chunk_hash,
                },
            )
            chunk_ids.append(chunk_id)
        await conn.commit()
    return chunk_ids
