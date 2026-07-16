"""Sensitive data masking utility — Security Spec §3.2.

Built-in sensitive field list with field-specific masking strategies.
Callers do NOT need to specify fields; all masking happens automatically.

Fields and their strategies:
    password, token, secret, api_key, id_card, ssn → "***"
    email → u***@example.com  (retains first char + domain)
    phone → 138****5678       (retains first 3 + last 4 digits)
    authorization, auth       → "***"
"""

from __future__ import annotations

import re
from typing import Any, Callable


def _full_mask(value: str) -> str:
    """Replace entire value with '***'."""
    return "***"


def _mask_email(value: str) -> str:
    """Retain first char of local part + domain: u***@example.com."""
    if not value:
        return "***"
    if "@" in value:
        local, domain = value.split("@", 1)
        return (local[0] + "***@" + domain) if local else "***@" + domain
    return value[0] + "***"


def _mask_phone(value: str) -> str:
    """Retain first 3 + last 4 digits: 138****5678."""
    if not value:
        return "***"
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 7:
        return digits[:3] + "****" + digits[-4:]
    return "***"


# Field → mask function dispatch (Security Spec §3.2)
_MASK_DISPATCH: dict[str, Callable[[str], str]] = {
    "password": _full_mask,
    "token": _full_mask,
    "secret": _full_mask,
    "api_key": _full_mask,
    "id_card": _full_mask,
    "ssn": _full_mask,
    "email": _mask_email,
    "phone": _mask_phone,
    "authorization": _full_mask,
    "auth": _full_mask,
}

_SENSITIVE_KEYS = frozenset(_MASK_DISPATCH)


def mask_sensitive(data: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    """Recursively mask sensitive fields in a dictionary.

    Mutates the input dict in place AND returns it.
    Sensitive values are replaced per Security Spec §3.2 rules.

    Args:
        data: The dictionary to mask (modified in place).
        depth: Internal recursion guard (max 10).

    Returns:
        The same dict with sensitive values replaced.
    """
    if depth > 10:
        return data

    for key, value in data.items():
        key_lower = key.lower()

        if key_lower in _SENSITIVE_KEYS and isinstance(value, str):
            data[key] = _MASK_DISPATCH[key_lower](value)
        elif isinstance(value, dict):
            data[key] = mask_sensitive(value, depth=depth + 1)
        elif isinstance(value, list):
            data[key] = [
                mask_sensitive(item, depth=depth + 1) if isinstance(item, dict) else item
                for item in value
            ]

    return data
