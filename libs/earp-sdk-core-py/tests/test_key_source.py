"""Tests for KeySource abstractions — Security Spec §2.2."""

import base64
import os
import pytest

from earp_sdk_core import CredentialKeyError, EnvVarSource


class TestEnvVarSource:
    """AC-03: Key via EARP_CREDENTIAL_KEY environment variable."""

    def test_base64_key(self, monkeypatch):
        """base64-encoded 32-byte key."""
        key_bytes = b"a" * 32
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(key_bytes).decode())
        source = EnvVarSource()
        assert source.get_key() == key_bytes

    def test_hex_key(self, monkeypatch):
        """hex-encoded 32-byte key (distinctive non-base64-looking string)."""
        key_bytes = bytes.fromhex("a1b2c3d4e5f60718293a4b5c6d7e8f90"  # 16
                                    "00112233445566778899aabbccddeeff")  # 32 total
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", key_bytes.hex())
        source = EnvVarSource()
        assert source.get_key() == key_bytes

    def test_custom_var_name(self, monkeypatch):
        """Custom environment variable name."""
        key_bytes = b"x" * 32
        monkeypatch.setenv("MY_KEY", base64.b64encode(key_bytes).decode())
        source = EnvVarSource("MY_KEY")
        assert source.get_key() == key_bytes

    def test_missing_var_raises(self, monkeypatch):
        """Missing environment variable raises CredentialKeyError."""
        monkeypatch.delenv("EARP_CREDENTIAL_KEY", raising=False)
        source = EnvVarSource()
        with pytest.raises(CredentialKeyError, match="not set"):
            source.get_key()

    def test_invalid_encoding_raises(self, monkeypatch):
        """Invalid encoding raises CredentialKeyError."""
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", "!!! not valid !!!")
        source = EnvVarSource()
        with pytest.raises(CredentialKeyError, match="base64 or hex"):
            source.get_key()

    def test_wrong_length_raises(self, monkeypatch):
        """Key length != 32 raises CredentialKeyError."""
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(b"short").decode())
        source = EnvVarSource()
        with pytest.raises(CredentialKeyError, match="32 bytes"):
            source.get_key()

    def test_too_long_raises(self, monkeypatch):
        """Key length > 32 raises CredentialKeyError."""
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(b"x" * 64).decode())
        source = EnvVarSource()
        with pytest.raises(CredentialKeyError, match="32 bytes"):
            source.get_key()
