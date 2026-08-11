"""Credential encryption for model_configs.credentials (PRD-2026-031).

AES-256-GCM application-layer encryption. Key from EARP_CREDENTIALS_KEY env
(32 bytes). Dev/test fallback with a hardcoded key + warning (matches the
JWT DEV_SECRET pattern); production MUST set the env var.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_DEV_KEY = "earp-dev-credential-key-0000000000000000"  # dev/test only (hashed to 32 bytes)


def _key() -> bytes:
    raw = os.environ.get("EARP_CREDENTIALS_KEY", "")
    if not raw:
        logger.warning("EARP_CREDENTIALS_KEY not set — using dev key (not for production)")
        raw = _DEV_KEY
    return hashlib.sha256(raw.encode()).digest()  # any length → 32 bytes


def encrypt(plaintext: dict) -> dict:
    """Encrypt a credentials dict → {ciphertext: b64, nonce: b64} wrapper."""
    if not plaintext:
        return {}
    data = __import__("json").dumps(plaintext).encode()
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, data, None)
    return {"ciphertext": base64.b64encode(ct).decode(), "nonce": base64.b64encode(nonce).decode()}


def decrypt(payload: dict) -> dict:
    """Decrypt a {ciphertext, nonce} wrapper → credentials dict. Empty input → {}."""
    if not payload or "ciphertext" not in payload:
        return {}
    try:
        ct = base64.b64decode(payload["ciphertext"])
        nonce = base64.b64decode(payload["nonce"])
        data = AESGCM(_key()).decrypt(nonce, ct, None)
        return __import__("json").loads(data)
    except Exception:
        logger.exception("credential decrypt failed")
        return {}


def masked(payload: dict) -> dict:
    """Public view — never expose credential values, only mask marker."""
    return {"credential_masked": bool(payload)}
