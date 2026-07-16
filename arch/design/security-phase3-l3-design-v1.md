# Security Phase 3 — 架构影响分析 + L3 实现设计

## PRD-2026-007 v1.2

| 字段 | 值 |
|------|-----|
| **影响范围** | earp-sdk-core (+1 新模块) |
| **架构决策** | 无 ADR 级别变更 |
| **Breaking Change** | 否 |
| **新增依赖** | 无（纯 stdlib: `re`, `dataclasses`, `typing`） |
| **版本** | v1.0 |
| **日期** | 2026-07-15 |

---

## 1. 影响范围

| 包 | 影响 | 新模块 | 修改 |
|:---|:-----|:-------|:-----|
| `earp-sdk-core` | 新增 | `guard.py` | `__init__.py`（导出 3 符号） |
| 其他 SDK | 无 | — | — |

## 2. L3 接口设计

### 2.1 guard.py — 完整实现

```python
"""LLM security guard — InputGuard + OutputFilter per Security Spec §4."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from earp_sdk_core.audit import AuditEvent, publish_audit_event
from earp_sdk_core.masking import _SENSITIVE_KEYS  # Phase 1 reuse

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

# ── PII patterns (reuse Phase 1) ──

_PII_KEY_PATTERNS = {k: re.compile(rf"\b{k}\b", re.IGNORECASE) for k in _SENSITIVE_KEYS}

# Email/phone standalone patterns for inline text scanning
_PII_RE = re.compile(
    r'([\w.+-]+@[\w-]+\.[\w.-]+)'     # email
    r'|(\+?\d[\d\-()\s]{6,}\d)',       # phone
    re.IGNORECASE,
)


# ── Dangerous code patterns ──

_DANGEROUS_CODE_PATTERNS = [
    (re.compile(r"\bimport\s+os\b"), "python", "import os"),
    (re.compile(r"\bimport\s+subprocess\b"), "python", "import subprocess"),
    (re.compile(r"\beval\s*\("), "python", "eval()"),
    (re.compile(r"\bexec\s*\("), "python", "exec()"),
    (re.compile(r"\bos\.system\s*\("), "python", "os.system()"),
    (re.compile(r"\bsubprocess\.(call|run|Popen)\s*\("), "python", "subprocess.call()"),
    (re.compile(r"\b__import__\s*\("), "python", "__import__()"),
]

# ── Injection patterns (Security Spec §4.2) ──

_INJECTION_PATTERNS = [
    # 指令覆盖
    (re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompt)", re.IGNORECASE),
     "指令覆盖"),
    (re.compile(r"forget\s+(your|all)\s+(training|instructions|rules)", re.IGNORECASE),
     "指令覆盖"),
    # 角色翻转
    (re.compile(r"you\s+are\s+now\s+(DAN|a\s+different\s+AI|an\s+unrestricted\s+AI)", re.IGNORECASE),
     "角色翻转"),
    (re.compile(r"act\s+as\s+(if\s+you\s+were|a)\s+.*?(without|no)\s+(restriction|rule|limit)", re.IGNORECASE),
     "角色翻转"),
    # 分隔符覆盖
    (re.compile(r"---\s*(SYSTEM\s+PROMPT|USER\s+INPUT|---)+\s*---"),
     "分隔符覆盖"),
    # Prompt 窃取
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


# ── InputGuard ──

class InputGuard:
    """Detect prompt injection and sanitize user input."""

    def __init__(self) -> None:
        self._patterns: list[tuple[re.Pattern, str]] = _INJECTION_PATTERNS

    def check(self, text: str) -> GuardResult:
        """Scan text for injection patterns.

        Returns GuardResult(status="blocked", ...) if injection detected,
        or GuardResult(status="ok") if safe.

        Sanitized input (wrapped with --- USER INPUT --- markers)
        is recognized and skipped to avoid false positives.
        """
        if not text or not text.strip():
            return GuardResult(status="ok")

        # Skip sanitized input blocks
        text_to_check = text
        if _SANITIZE_HEADER.strip() in text:
            # Strip sanitize wrappers before checking
            text_to_check = text.replace(_SANITIZE_HEADER, "")
            text_to_check = text_to_check.replace(_SANITIZE_FOOTER, "")
            text_to_check = text_to_check.strip()

        for pattern, category in self._patterns:
            m = pattern.search(text_to_check)
            if m:
                result = GuardResult(
                    status="blocked",
                    reason=f"{category}: {m.group()[:80]}",
                    detail={"pattern": category, "match": m.group()},
                )
                # Audit
                try:
                    publish_audit_event(AuditEvent(
                        source="security", event_type="PROMPT_INJECTION_DETECTED",
                        tenant_id="", user_id="", action="input_guard_check",
                        result="blocked",
                        detail={"pattern": category, "match": m.group()[:200]},
                    ))
                except Exception:
                    pass
                return result

        return GuardResult(status="ok")

    def sanitize(self, user_input: str) -> str:
        """Wrap user input with delimiters to isolate from system prompt."""
        if not user_input:
            return ""
        return f"{_SANITIZE_HEADER}{user_input}{_SANITIZE_FOOTER}"

    def summarize(self, text: str, max_chars: int = 2000) -> str:
        """Truncate external data + annotate source (Phase 3 simplification).

        Phase 4 will upgrade to actual LLM summarization.
        """
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return f"[External source: {len(text)} chars] {text[:max_chars]} (truncated)"


# ── OutputFilter ──

class OutputFilter:
    """Filter LLM output for PII, system prompt leaks, and dangerous code."""

    def __init__(
        self, system_prompt_phrases: list[str] | None = None
    ) -> None:
        self._prompt_phrases = system_prompt_phrases or _DEFAULT_SYSTEM_PROMPT_PHRASES

    def check(self, text: str) -> GuardResult:
        """Filter LLM output.

        Returns:
            blocked  — system prompt leak detected
            filtered — PII or dangerous code found (redactable)
            ok       — output is safe
        """
        if not text:
            return GuardResult(status="ok")

        # 1. System prompt leak (blocked)
        for phrase in self._prompt_phrases:
            if phrase.lower() in text.lower():
                result = GuardResult(
                    status="blocked",
                    reason=f"System prompt leak: '{phrase}'",
                    detail={"leaked_phrase": phrase},
                )
                try:
                    publish_audit_event(AuditEvent(
                        source="security", event_type="SYSTEM_PROMPT_LEAK",
                        tenant_id="", user_id="", action="output_filter_check",
                        result="blocked",
                        detail={"leaked_phrase": phrase},
                    ))
                except Exception:
                    pass
                return result

        # 2. Dangerous code (filtered)
        for pattern, code_type, code_name in _DANGEROUS_CODE_PATTERNS:
            if pattern.search(text):
                result = GuardResult(
                    status="filtered",
                    reason=f"Dangerous code: {code_name}",
                    detail={"code_type": code_type, "pattern": code_name},
                )
                try:
                    publish_audit_event(AuditEvent(
                        source="security", event_type="DANGEROUS_CODE",
                        tenant_id="", user_id="", action="output_filter_check",
                        result="filtered",
                        detail={"code_type": code_type, "pattern": code_name},
                    ))
                except Exception:
                    pass
                return result

        # 3. PII detection (filtered)
        pii_found: list[str] = []
        for m in _PII_RE.finditer(text):
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

        Security Spec §4.3: Command 类型 Capability 的 LLM 生成参数需人工审核。
        """
        return GuardResult(
            status="approval_required",
            reason="Command Capability parameters require human approval per Security Spec §4.3",
        )
```

### 2.2 __init__.py 更新

```python
from earp_sdk_core.guard import InputGuard, OutputFilter, GuardResult, GuardStatus
```

## 3. SDKMUST 条款

| # | 条款 | AC |
|:-:|:-----|:--:|
| SDKMUST-01 | `InputGuard.check()` 扫描 4 类注入模式，命中返回 `blocked` + audit | AC-01, AC-07 |
| SDKMUST-02 | `InputGuard.sanitize()` 用 `--- USER INPUT ---` 包裹输入 | AC-02 |
| SDKMUST-03 | `sanitize` 后的输入被 `check()` 识别并跳过注入检测 | — (P2-1 修复) |
| SDKMUST-04 | `OutputFilter.check()` 检测 system prompt 短语 → `blocked` + audit | AC-04, AC-09 |
| SDKMUST-05 | `OutputFilter.check()` 检测危险代码 → `filtered` + audit | AC-05, AC-10 |
| SDKMUST-06 | `OutputFilter.check()` 检测 PII → `filtered` | AC-03 |
| SDKMUST-07 | `OutputFilter.require_approval()` → `approval_required` | AC-06 |
| SDKMUST-08 | `InputGuard.summarize()` 截断 + 来源标注 | AC-08 |
| SDKMUST-09 | `GuardResult` 使用 `Literal["ok","filtered","blocked","approval_required"]` | 全 AC |

## 4. 测试策略

### test_guard.py

| 测试类 | 覆盖 |
|:--------|:-----|
| `TestGuardResult` | 构造 ok/filtered/blocked/approval_required, detail dict, 默认值 |
| `TestInputGuardCheck` | 指令覆盖/角色翻转/分隔符覆盖/Prompt窃取→blocked; 安全文本→ok; 空输入→ok; sanitize 后输入→ok（P2-1验证） |
| `TestInputGuardSanitize` | 普通输入包裹分隔符, 空输入, unicode 输入, sanitize+check 组合 |
| `TestInputGuardSummarize` | 短文本通过, 长文本截断+标注, 空文本, max_chars 边界 |
| `TestOutputFilterCheck` | PII(email/phone)→filtered; system prompt→blocked; 危险代码→filtered; 安全输出→ok |
| `TestOutputFilterRequireApproval` | 返回 approval_required + reason |
| `TestAuditIntegration` | InputGuard blocked → audit event; OutputFilter blocked → SYSPROMPTLEAK; OutputFilter filtered → DANGEROUS_CODE |

## 5. 复用说明

| Phase | 组件 | 使用方式 |
|:-----:|:-----|:---------|
| Phase 1 | `masking._SENSITIVE_KEYS` | OutputFilter PII 检测：导入 `_SENSITIVE_KEYS` 构建 `_PII_KEY_PATTERNS` |
| Phase 2 | `publish_audit_event` / `AuditEvent` | InputGuard/OutputFilter 检测到威胁时发布审计事件 |
