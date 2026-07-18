"""LLM security guard — InputGuard + OutputFilter per Security Spec §4.

PII detection covers email and phone (regex-matchable free-text patterns).
Password, token, secret, api_key, id_card, ssn are detected by
mask_sensitive() on structured data; they have no reliable free-text pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Callable, Awaitable

from earp_sdk_core.audit import AuditEvent, publish_audit_event

# ── GuardResult ──

GuardStatus = Literal["ok", "filtered", "blocked", "approval_required"]


@dataclass
class GuardResult:
    status: GuardStatus
    reason: str = ""
    detail: dict = field(default_factory=dict)


# ── sanitize markers ──

_SANITIZE_HEADER = "\n--- USER INPUT ---\n"
_SANITIZE_FOOTER = "\n--- END USER INPUT ---\n"

# ── PII patterns (split to avoid alternation backtracking) ──

_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+', re.IGNORECASE)
_PHONE_RE = re.compile(r'\+?\d[\d\-()\s]{6,}\d')

# ── Dangerous code patterns ──

_DANGEROUS_CODE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bimport\s+os\b"), "python", "import os"),
    (re.compile(r"\bimport\s+subprocess\b"), "python", "import subprocess"),
    (re.compile(r"\beval\s*\("), "python", "eval()"),
    (re.compile(r"\bexec\s*\("), "python", "exec()"),
    (re.compile(r"\bos\.system\s*\("), "python", "os.system()"),
    (re.compile(r"\bsubprocess\.(call|run|Popen)\s*\("), "python", "subprocess.call()"),
    (re.compile(r"\b__import__\s*\("), "python", "__import__()"),
]

# ── Injection patterns (Security Spec §4.2) ──

_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompt)", re.IGNORECASE),
     "指令覆盖"),
    (re.compile(r"forget\s+(your|all)\s+(training|instructions|rules)", re.IGNORECASE),
     "指令覆盖"),
    (re.compile(r"you\s+are\s+now\s+(DAN|a\s+different\s+AI|an\s+unrestricted\s+AI)", re.IGNORECASE),
     "角色翻转"),
    (re.compile(r"act\s+as\s+(if\s+you\s+were|a)\s+.*?(without|no)\s+(restriction|rule|limit)", re.IGNORECASE),
     "角色翻转"),
    (re.compile(r"---\s*(SYSTEM\s+PROMPT|USER\s+INPUT|---)+\s*---"),
     "分隔符覆盖"),
    (re.compile(r"(repeat|tell\s+me|reveal|print|output|show)\s+(your|the)\s+(system\s+prompt|instructions|initial\s+prompt)", re.IGNORECASE),
     "Prompt窃取"),
    (re.compile(r"what\s+are\s+(your|the)\s+(first|initial)\s+(words|instructions)", re.IGNORECASE),
     "Prompt窃取"),
]

# Default system prompt phrases for leak detection
_DEFAULT_SYSTEM_PROMPT_PHRASES = [
    "You are EARP",
    "EARP AI platform",
    "system prompt:",
    "as an AI assistant",
]


# ── Audit helper ──

def _publish_security_audit(
    event_type: str, action: str, result: str, detail: dict
) -> None:
    """Publish a security audit event (non-fatal on failure)."""
    try:
        publish_audit_event(AuditEvent(
            source="security",
            event_type=event_type,
            tenant_id="",
            user_id="",
            action=action,
            result=result,
            detail=detail,
        ))
    except Exception:
        pass


# ── InputGuard ──

class InputGuard:
    """Detect prompt injection and sanitize user input.

    Sanitized input (wrapped with --- USER INPUT --- markers) is recognized
    and the markers are stripped before checking, avoiding false positives
    from the delimiter override detection patterns.
    """

    def check(self, text: str) -> GuardResult:
        """Scan text for injection patterns.

        Returns GuardResult(status="blocked", ...) if injection detected,
        or GuardResult(status="ok") if safe.
        """
        if not text or not text.strip():
            return GuardResult(status="ok")

        # Strip sanitize wrappers before checking to avoid false positives
        text_to_check = text
        header_plain = _SANITIZE_HEADER.strip()
        footer_plain = _SANITIZE_FOOTER.strip()
        if header_plain in text_to_check:
            text_to_check = text_to_check.replace(header_plain, "")
            text_to_check = text_to_check.replace(footer_plain, "")

        for pattern, category in _INJECTION_PATTERNS:
            m = pattern.search(text_to_check)
            if m:
                result = GuardResult(
                    status="blocked",
                    reason=f"{category}: {m.group()[:80]}",
                    detail={"pattern": category, "match": m.group()},
                )
                _publish_security_audit(
                    "PROMPT_INJECTION_DETECTED", "input_guard_check",
                    "blocked", {"pattern": category, "match": m.group()[:200]},
                )
                return result

        return GuardResult(status="ok")

    def sanitize(self, user_input: str) -> str:
        """Wrap user input with delimiters to isolate from system prompt.

        Security Spec §4.2 MUST: 系统 Prompt 与用户输入使用明确分隔符。
        """
        if not user_input:
            return ""
        return f"{_SANITIZE_HEADER}{user_input}{_SANITIZE_FOOTER}"

    def summarize(self, text: str, max_chars: int = 2000) -> str:
        """Truncate external data + annotate source. Phase 3 fallback.

        For LLM-powered summarization, use summarize_with_llm().
        """
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return f"[External source: {len(text)} chars] {text[:max_chars]} (truncated)"

    async def summarize_with_llm(
        self,
        text: str,
        llm_summarize: "Callable[[str], Awaitable[str]]",
        max_chars: int = 2000,
    ) -> str:
        """Summarize external data using LLM. Phase 4 upgrade.

        Args:
            text: The raw external data to summarize.
            llm_summarize: Async callback(truncated_text) → summary string.
            max_chars: Truncate raw text before passing to LLM (cost control).

        Returns:
            LLM-generated summary, or truncated fallback on failure.
        """
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        try:
            truncated = text[:max_chars]
            summary = await llm_summarize(truncated)
            if summary:
                return f"[Summarized from {len(text)} chars] {summary}"
        except Exception:
            pass
        # Fallback to truncation
        return self.summarize(text, max_chars)


# ── OutputFilter ──

class OutputFilter:
    """Filter LLM output for PII, system prompt leaks, and dangerous code.

    PII detection currently covers email and phone (regex-matchable patterns).
    Password, token, secret, api_key, id_card, ssn are detected by
    mask_sensitive() on structured data; they have no reliable free-text pattern.
    """

    def __init__(
        self, system_prompt_phrases: list[str] | None = None
    ) -> None:
        self._prompt_phrases = system_prompt_phrases or _DEFAULT_SYSTEM_PROMPT_PHRASES

    def check(self, text: str) -> GuardResult:
        """Filter LLM output.

        Priority order (first match wins):
          1. System prompt leak → blocked + audit
          2. Dangerous code → filtered + audit
          3. PII → filtered
          4. Safe → ok
        """
        if not text:
            return GuardResult(status="ok")

        # 1. System prompt leak (blocked)
        text_lower = text.lower()
        for phrase in self._prompt_phrases:
            if phrase.lower() in text_lower:
                result = GuardResult(
                    status="blocked",
                    reason=f"System prompt leak: '{phrase}'",
                    detail={"leaked_phrase": phrase},
                )
                _publish_security_audit(
                    "SYSTEM_PROMPT_LEAK", "output_filter_check",
                    "blocked", {"leaked_phrase": phrase},
                )
                return result

        # 2. Dangerous code (filtered)
        for pattern, code_type, code_name in _DANGEROUS_CODE_PATTERNS:
            if pattern.search(text):
                result = GuardResult(
                    status="filtered",
                    reason=f"Dangerous code: {code_name}",
                    detail={"code_type": code_type, "pattern": code_name},
                )
                _publish_security_audit(
                    "DANGEROUS_CODE", "output_filter_check",
                    "filtered", {"code_type": code_type, "pattern": code_name},
                )
                return result

        # 3. PII detection (filtered)
        pii_found: list[str] = []
        for m in _EMAIL_RE.finditer(text):
            if m.group():
                pii_found.append(m.group())
        for m in _PHONE_RE.finditer(text):
            if m.group():
                pii_found.append(m.group())

        if pii_found:
            return GuardResult(
                status="filtered",
                reason=f"PII detected: {len(pii_found)} items",
                detail={"pii_detected": pii_found},
            )

        return GuardResult(status="ok")

    def require_approval(self) -> GuardResult:
        """Mark Command Capability params as requiring human approval.

        Security Spec §4.3 MUST: Command 类型 Capability 的 LLM 生成参数需要人工审核。
        """
        return GuardResult(
            status="approval_required",
            reason="Command Capability parameters require human approval per Security Spec §4.3",
        )
