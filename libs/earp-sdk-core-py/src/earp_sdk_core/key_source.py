"""Key source abstractions for CredentialEncryptor.

Phase 2:     EnvVarSource (EARP_CREDENTIAL_KEY)
Phase 2.1:   VaultSource (HashiCorp Vault KV v2), FileSource
"""

from __future__ import annotations

import base64
import binascii
import os
from abc import ABC, abstractmethod
from pathlib import Path

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
        return self._decode(raw)

    @staticmethod
    def _decode(raw: str) -> bytes:
        # Try hex first, then base64
        try:
            key = binascii.unhexlify(raw)
        except Exception:
            try:
                import base64 as _b64
                key = _b64.b64decode(raw, validate=True)
            except Exception:
                raise CredentialKeyError("Key must be base64 or hex encoded")
        if len(key) != 32:
            raise CredentialKeyError(f"Key must be 32 bytes, got {len(key)} bytes")
        return key


class VaultSource(KeySource):
    """Read AES-256 key from HashiCorp Vault KV v2 secrets engine.

    Requires: pip install hvac

    Environment variables:
        VAULT_ADDR  — Vault server URL (default: http://localhost:8200)
        VAULT_TOKEN — Vault authentication token
    """

    def __init__(
        self,
        path: str = "secret/earp/credential-key",
        key: str = "key",
        mount_point: str = "secret",
    ) -> None:
        self._path = path
        self._key = key
        self._mount_point = mount_point

    def get_key(self) -> bytes:
        try:
            import hvac
        except ImportError:
            raise CredentialKeyError(
                "VaultSource requires hvac. Install: pip install hvac"
            )

        addr = os.environ.get("VAULT_ADDR", "http://localhost:8200")
        token = os.environ.get("VAULT_TOKEN", "")
        if not token:
            raise CredentialKeyError("VAULT_TOKEN environment variable is not set")

        client = hvac.Client(url=addr, token=token)
        if not client.is_authenticated():
            raise CredentialKeyError(f"Vault authentication failed at {addr}")

        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=self._path, mount_point=self._mount_point
            )
        except Exception as e:
            raise CredentialKeyError(f"Vault read failed: {e}") from e

        data = response.get("data", {}).get("data", {})
        raw = data.get(self._key)
        if not raw:
            raise CredentialKeyError(
                f"Key '{self._key}' not found in Vault path '{self._path}'"
            )

        return EnvVarSource._decode(str(raw))


class FileSource(KeySource):
    """Read AES-256 key from a file (base64 or hex encoded).

    Useful for K8s secrets mounted as files.
    """

    def __init__(self, path: str = "/etc/earp/credential-key") -> None:
        self._path = Path(path)

    def get_key(self) -> bytes:
        if not self._path.exists():
            raise CredentialKeyError(f"Key file not found: {self._path}")
        raw = self._path.read_text().strip()
        if not raw:
            raise CredentialKeyError(f"Key file is empty: {self._path}")
        return EnvVarSource._decode(raw)
