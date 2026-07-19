"""InputGuard: block injection patterns in request bodies."""

from __future__ import annotations

import re

# Regex patterns matching common SQL injection / command injection attempts.
_BLOCKLIST = (
    re.compile(r"\bUNION\s+SELECT\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\b1\s*=\s*1\b"),
    re.compile(r"\bxp_cmdshell\b", re.IGNORECASE),
    re.compile(r"\b(ALTER|TRUNCATE)\s+(TABLE|DATABASE)\b", re.IGNORECASE),
    re.compile(r"<script\b", re.IGNORECASE),
)


def sanitize_body(body: dict | None) -> dict | None:
    """Return None if any value triggers a blocklisted pattern. Lightweight, fixed-alphabet defence."""
    if body is None:
        return None
    serialised = str(body)
    for pattern in _BLOCKLIST:
        if pattern.search(serialised):
            return None
    return body
