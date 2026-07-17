"""AES-256-GCM credential encryption — Security Spec §2.2, Multi-Tenant Spec §4.2.

Per-tenant key derivation via HKDF-SHA256 when tenant_id is provided.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from earp_sdk_core.config import AuthConfig
from earp_sdk_core.errors import CredentialKeyError
from earp_sdk_core.key_source import EnvVarSource, KeySource

_INFO = b"earp-credential-encryption-v1"


def _derive_key(master_key: bytes, tenant_id: str) -> bytes:
    """Derive per-tenant encryption key via HKDF-SHA256.

    HKDF(IKM=master_key, salt=tenant_id_utf8, info=b"earp-credential-encryption-v1")
    When tenant_id is empty string, salt is b"" (backward compatible transition mode).
    """
    salt = tenant_id.encode("utf-8") if tenant_id else b""
    # HKDF-Extract: PRK = HMAC-SHA256(salt, IKM)
    prk = hmac.new(salt, master_key, hashlib.sha256).digest()
    # HKDF-Expand: OKM = HMAC-SHA256(PRK, info || 0x01)
    okm = hmac.new(prk, _INFO + b"\x01", hashlib.sha256).digest()
    return okm


class CredentialEncryptor:
    """Encrypt/decrypt with AES-256-GCM.

    Ciphertext format (Phase 2):
        base64(nonce[12] || ciphertext[N] || tag[16])

    When tenant_id is provided, the encryption key is derived from the master
    key via HKDF-SHA256. Different tenant_ids produce independent keys.
    Cross-tenant decryption raises InvalidTag.

    Backward compatibility: tenant_id="" uses HKDF(salt=b"") which is
    deterministic but NOT the raw master key. This is a transition mode;
    Phase 3+ will require per-tenant encryptors.
    """

    def __init__(
        self,
        key_source: KeySource | None = None,
        tenant_id: str = "",
    ) -> None:
        self._key_source = key_source or EnvVarSource()
        self._tenant_id = tenant_id
        self._key: bytes | None = None
        self._aesgcm: AESGCM | None = None

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def key(self) -> bytes:
        if self._key is None:
            master = self._key_source.get_key()
            self._key = _derive_key(master, self._tenant_id)
            self._aesgcm = AESGCM(self._key)
        return self._key

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext → base64 ciphertext."""
        self.key  # trigger lazy init
        nonce = secrets.token_bytes(12)
        data = plaintext.encode("utf-8")
        ct = self._aesgcm.encrypt(nonce, data, None)
        raw = nonce + ct
        return base64.b64encode(raw).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt base64 ciphertext → plaintext.

        Raises:
            cryptography.exceptions.InvalidTag: if ciphertext is invalid
                or key is wrong (GCM auth failure). InvalidTag is a
                subclass of ValueError.
        """
        self.key  # trigger lazy init
        raw = base64.b64decode(ciphertext)
        nonce = raw[:12]
        ct = raw[12:]
        data = self._aesgcm.decrypt(nonce, ct, None)
        return data.decode("utf-8")


@dataclass
class EncryptedAuthConfig(AuthConfig):
    """AuthConfig subclass with encrypted token/password at rest.

    Inheritance from AuthConfig preserves compatibility with
    ConnectorConfig.auth: AuthConfig type annotation.

    Storage state:
        token → ciphertext base64 string (stored)
        password → ciphertext base64 string (stored)

    Runtime state:
        token → plaintext (transparent decrypt on access)
        password → plaintext (transparent decrypt on access)

    Pickle safety:
        __getstate__ returns ciphertext only (no decryptor).
        After unpickling, accessing token/password raises CredentialKeyError.
        Call rehydrate(encryptor) to re-inject the decryptor.
    """

    _ciphertext_token: str = field(default="", repr=False)
    _ciphertext_password: str = field(default="", repr=False)
    _decryptor: CredentialEncryptor | None = field(default=None, repr=False)

    @classmethod
    def from_plaintext(
        cls, auth: AuthConfig, encryptor: CredentialEncryptor
    ) -> "EncryptedAuthConfig":
        """Create encrypted version from a plaintext AuthConfig.

        Uses object.__setattr__ to directly set shadow fields,
        bypassing the token/password setters.
        """
        instance = cls(
            type=auth.type,
            username=auth.username,
            token="",
            password="",
            _decryptor=encryptor,
        )
        object.__setattr__(
            instance, "_ciphertext_token",
            encryptor.encrypt(auth.token) if auth.token else "",
        )
        object.__setattr__(
            instance, "_ciphertext_password",
            encryptor.encrypt(auth.password) if auth.password else "",
        )
        return instance

    @property
    def token(self) -> str:
        if self._decryptor is None:
            raise CredentialKeyError(
                "EncryptedAuthConfig has no decryptor. "
                "Call rehydrate(encryptor) after unpickling."
            )
        if self._ciphertext_token:
            return self._decryptor.decrypt(self._ciphertext_token)
        return ""

    @token.setter
    def token(self, value: str) -> None:
        if self._decryptor and value:
            self._ciphertext_token = self._decryptor.encrypt(value)
        else:
            self._ciphertext_token = value

    @property
    def password(self) -> str:
        if self._decryptor is None:
            raise CredentialKeyError(
                "EncryptedAuthConfig has no decryptor. "
                "Call rehydrate(encryptor) after unpickling."
            )
        if self._ciphertext_password:
            return self._decryptor.decrypt(self._ciphertext_password)
        return ""

    @password.setter
    def password(self, value: str) -> None:
        if self._decryptor and value:
            self._ciphertext_password = self._decryptor.encrypt(value)
        else:
            self._ciphertext_password = value

    def rehydrate(self, encryptor: CredentialEncryptor) -> None:
        """Re-inject decryptor after unpickling or deserialization."""
        self._decryptor = encryptor

    def __repr__(self) -> str:
        return (
            f"EncryptedAuthConfig("
            f"type={self.type!r}, "
            f"token='<encrypted>', "
            f"username={self.username!r}, "
            f"password='<encrypted>')"
        )

    def __getstate__(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "username": self.username,
            "token": self._ciphertext_token,
            "password": self._ciphertext_password,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.type = state["type"]
        self.username = state["username"]
        self._ciphertext_token = state["token"]
        self._ciphertext_password = state["password"]
        self._decryptor = None
