"""Key source abstractions for CredentialEncryptor.

Phase 2:     EnvVarSource (EARP_CREDENTIAL_KEY)
Phase 2.1:   VaultSource, FileSource, ...
"""

from __future__ import annotations

import base64
import binascii
import os
from abc import ABC, abstractmethod

from earp_sdk_core.errors import CredentialKeyError


class KeySource(ABC):
    """Abstract key source. Returns 32-byte AES-256 key."""

    @abstractmethod
    def get_key(self) -> bytes:
        """Return the 32-byte encryption key."""
        ...


class EnvVarSource(KeySource):
    """Read AES-256 key from environment variable (base64 or hex encoded)."""

    def __init__(self, var_name: str = "EARP_CREDENTIAL_KEY") -> None:
        self._var_name = var_name

    def get_key(self) -> bytes:
        raw = os.environ.get(self._var_name)
        if not raw:
            raise CredentialKeyError(
                f"Environment variable {self._var_name} is not set"
            )
        # Try hex first, then base64
        try:
            key = binascii.unhexlify(raw)
        except Exception:
            try:
                import base64 as _b64
                key = _b64.b64decode(raw, validate=True)
            except Exception:
                raise CredentialKeyError(
                    f"{self._var_name} must be base64 or hex encoded"
                )
        if len(key) != 32:
            raise CredentialKeyError(
                f"Key must be 32 bytes, got {len(key)} bytes"
            )
        return key
