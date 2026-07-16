"""AES-256-GCM credential encryption — Security Spec §2.2."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from earp_sdk_core.config import AuthConfig
from earp_sdk_core.errors import CredentialKeyError
from earp_sdk_core.key_source import EnvVarSource, KeySource


class CredentialEncryptor:
    """Encrypt/decrypt with AES-256-GCM.

    Ciphertext format:
        base64(nonce[12] || ciphertext[N] || tag[16])

    The key is loaded lazily from key_source on first encrypt()/decrypt() call.
    """

    def __init__(self, key_source: KeySource | None = None) -> None:
        self._key_source = key_source or EnvVarSource()
        self._key: bytes | None = None
        self._aesgcm: AESGCM | None = None

    @property
    def key(self) -> bytes:
        if self._key is None:
            self._key = self._key_source.get_key()
            self._aesgcm = AESGCM(self._key)
        return self._key

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext → base64 ciphertext."""
        self.key  # trigger lazy init
        nonce = secrets.token_bytes(12)
        data = plaintext.encode("utf-8")
        ct = self._aesgcm.encrypt(nonce, data, None)
        # ct includes the 16-byte tag appended automatically by AESGCM
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

    # Ciphertext storage shadow fields
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

    # ── token ──

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

    # ── password ──

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

    # ── rehydration ──

    def rehydrate(self, encryptor: CredentialEncryptor) -> None:
        """Re-inject decryptor after unpickling or deserialization."""
        self._decryptor = encryptor

    # ── repr ──

    def __repr__(self) -> str:
        return (
            f"EncryptedAuthConfig("
            f"type={self.type!r}, "
            f"token='<encrypted>', "
            f"username={self.username!r}, "
            f"password='<encrypted>')"
        )

    # ── pickle safety ──

    def __getstate__(self) -> dict[str, Any]:
        """Pickle: return ciphertext only, exclude decryptor."""
        return {
            "type": self.type,
            "username": self.username,
            "token": self._ciphertext_token,
            "password": self._ciphertext_password,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Unpickle: restore ciphertext, decryptor is None.

        Accessing token/password after unpickling raises CredentialKeyError.
        Caller must call rehydrate(encryptor) to enable decryption.
        """
        self.type = state["type"]
        self.username = state["username"]
        self._ciphertext_token = state["token"]
        self._ciphertext_password = state["password"]
        self._decryptor = None
