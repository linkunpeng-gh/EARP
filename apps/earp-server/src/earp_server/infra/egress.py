"""Egress 出口管控 — allowed_domains 白名单."""

from __future__ import annotations

ALLOWED_DOMAINS: set[str] = {"localhost", "api.openai.com", "127.0.0.1"}


def is_domain_allowed(url: str) -> bool:
    """Check if a URL's domain is in the allowed list."""
    from urllib.parse import urlparse

    domain = urlparse(url).hostname or ""
    for allowed in ALLOWED_DOMAINS:
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False
