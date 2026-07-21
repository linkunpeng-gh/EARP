"""JSON-ish stdlib logging with credential masking (M15 enhancement).

M0: basic JSON log format (no structlog dependency).
M15: CredentialMaskingFilter — masks Bearer tokens, passwords, API keys in logs.
"""

from __future__ import annotations

import logging
import re

from earp_server.config import Settings

_FORMAT = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'


def init_app(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level.upper(), format=_FORMAT)


# ── Credential Masking Filter (M15) ──

_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer ***"),
    (r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?\s*)Bearer\s+[A-Za-z0-9\-._~+/]+=*", r"\1Bearer ***"),
    (r'(?i)"password"\s*:\s*"[^"]*"', '"password": "***"'),
    (r'(?i)"token"\s*:\s*"[^"]*"', '"token": "***"'),
    (r'(?i)"(api_key|secret|apikey)"\s*:\s*"[^"]*"', r'"\1": "***"'),
]


class CredentialMaskingFilter(logging.Filter):
    """Logging filter that masks sensitive credential values in log output."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern, replacement in _SENSITIVE_PATTERNS:
            msg = re.sub(pattern, replacement, msg)
        record.msg = msg
        record.args = ()
        return True


def install() -> None:
    """Install credential masking filter on root + earp_server loggers."""
    f = CredentialMaskingFilter()
    logging.getLogger().addFilter(f)
    logging.getLogger("earp_server").addFilter(f)
