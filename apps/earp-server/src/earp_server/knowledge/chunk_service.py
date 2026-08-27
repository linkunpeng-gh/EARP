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
        "separators": ["\n\n", "\n", "。", ";"],
        "separator": "\n\n",  # legacy single separator (kept for compat)
        "max_tokens": 1000,
        "chunk_overlap": 200,
    },
    "parent_mode": "full-doc",
    "subchunk_segmentation": {
        "separator": "\n",
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


def _token_estimate(text: str) -> int:
    """CJK-aware token estimate: 1 CJK char ≈ 1 token, ASCII ≈ 4 chars/token.

    The old chars/4 rule is English-centric and made "1000 tokens" cut 4000-char
    blocks for Chinese docs — a short article stayed a single whole-document chunk.
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_chars = len(text) - cjk
    return cjk + ascii_chars // 4 + 1


# System fallback chain appended after user separators — guarantees the splitter
# can always cut (character-level last resort).
_FALLBACK_SEPARATORS = ("\n", ". ", " ", "")


def suggest_separators(content: str) -> list[str]:
    """Heuristic separator suggestion based on the document's actual structure.

    Inspects the parsed text and returns a priority-ordered list (up to 5) of
    separators that best match how the document is organized:
      - blank-line paragraphs (\n\n) → strongest signal
      - single-line structure (\n)     → next
      - CJK full stop (。) / semicolon (；)
      - ASCII sentence (. ) / semicolon (;)
    System fallback chain is applied by the splitter regardless.
    """
    import re

    if not content or not content.strip():
        return ["\n\n", "\n", "。"]

    suggestions: list[str] = []

    para_count = content.count("\n\n")
    line_count = content.count("\n")
    cjk_stop = content.count("。")
    cjk_semi = content.count("；")
    ascii_stop = len(re.findall(r"\.\s", content))
    ascii_semi = content.count(";")
    md_headers = len(re.findall(r"^#{1,3}\s", content, re.M))

    # 1. paragraph breaks (strongest: blank-line separated sections)
    if para_count >= 2:
        suggestions.append("\n\n")
        # single newlines inside paragraphs are a good fallback when common
        if line_count > para_count * 2:
            suggestions.append("\n")
    elif para_count == 1 or (line_count >= 3 and md_headers == 0):
        suggestions.append("\n")

    # 2. CJK sentence boundaries
    if cjk_stop >= 3:
        suggestions.append("。")
    if cjk_semi >= 3:
        suggestions.append("；")

    # 3. ASCII sentence boundaries
    if ascii_stop >= 3:
        suggestions.append(". ")
    if ascii_semi >= 3:
        suggestions.append(";")

    # 4. markdown-heavy doc → headings are a good structural cue
    if md_headers >= 2:
        suggestions.insert(0, "\n\n")  # ensure paragraph split first

    # dedupe + cap at 5; guarantee at least one entry
    out: list[str] = []
    for s in suggestions:
        if s not in out:
            out.append(s)
    return out[:5] or ["\n\n"]


def resolve_separators(seg: dict) -> list[str]:
    """User separators (priority order) + system fallback chain, deduped.

    Accepts both the new `separators` list and the legacy `separator` string.
    """
    seps: list[str] = []
    if seg.get("separators"):
        seps = [str(s) for s in seg["separators"] if s != ""]
    elif seg.get("separator"):
        seps = [str(seg["separator"])]
    for s in _FALLBACK_SEPARATORS:
        if s not in seps:
            seps.append(s)
    return seps[: 5 + len(_FALLBACK_SEPARATORS)]


def split_text(
    content: str,
    separator: str = "\n\n",
    max_tokens: int = 1000,
    chunk_overlap: int = 200,
    separators: list[str] | None = None,
) -> list[str]:
    """Split text into overlapping chunks sized by CJK-aware token estimate.

    max_tokens / chunk_overlap are REAL token units (via length_function) — a
    "1000" chunk size yields ~1000-CJK-char blocks, not 4000.

    separators: up to 5 user separators in priority order. The splitter tries
    the highest-priority one first; oversized segments recursively fall back to
    the next one (RecursiveCharacterTextSplitter semantics). A system fallback
    chain is appended automatically.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    if separators is None:
        separators = resolve_separators({"separator": separator})
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens,
        chunk_overlap=chunk_overlap,
        length_function=_token_estimate,
        separators=separators,
    )
    return splitter.split_text(content)


def build_preview(content: str, rules: dict | None = None) -> list[dict]:
    """Return chunk preview without persisting. Returns [{index, content, char_count}, ...].

    `content` is the FULL chunk text (not truncated) so users can verify that
    chunk boundaries land sensibly; `content_preview` (first 120 chars) is kept
    for compact list UIs. All chunks are returned (no [:10] cap).
    """
    rules = rules or DEFAULT_RULES
    seg = rules.get("segmentation", DEFAULT_RULES["segmentation"])
    processed = apply_preprocessing(content, rules.get("pre_processing_rules", []))
    chunks = split_text(
        processed,
        seg.get("separator", "\n\n"),
        seg.get("max_tokens", 1000),
        seg.get("chunk_overlap", 200),
        separators=resolve_separators(seg),
    )
    return [{"index": i, "content": c, "content_preview": c[:120], "char_count": len(c)} for i, c in enumerate(chunks)]


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
    texts = split_text(
        processed,
        seg.get("separator", "\n\n"),
        seg.get("max_tokens", 1000),
        seg.get("chunk_overlap", 200),
        separators=resolve_separators(seg),
    )

    # chunks.knowledge_base_id is NOT NULL — resolve from the document row
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT knowledge_base_id FROM documents WHERE document_id = :did"),
            {"did": document_id},
        )
        r = row.fetchone()
        if r is None:
            raise ValueError(f"document not found: {document_id}")
        kb_id = r.knowledge_base_id

    chunk_ids = []
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        for i, chunk_text in enumerate(texts):
            chunk_id = f"chk-{uuid.uuid4().hex[:12]}"
            chunk_hash = hashlib.md5(chunk_text.encode()).hexdigest()
            await conn.execute(
                text(
                    "INSERT INTO chunks (chunk_id, tenant_id, document_id, knowledge_base_id, chunk_index, "
                    "content, content_hash) VALUES (:cid, :tid, :did, :kid, :idx, :content, :chash)"
                ),
                {
                    "cid": chunk_id,
                    "tid": tenant_id,
                    "did": document_id,
                    "kid": kb_id,
                    "idx": i,
                    "content": chunk_text,
                    "chash": chunk_hash,
                },
            )
            chunk_ids.append(chunk_id)
        await conn.commit()
    return chunk_ids
