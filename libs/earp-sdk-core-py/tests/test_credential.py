"""Tests for CredentialEncryptor + EncryptedAuthConfig — AC-01, AC-02, AC-03."""

import base64
import os
import pickle
import pytest

from cryptography.exceptions import InvalidTag

from earp_sdk_core import (
    AuthConfig,
    CredentialEncryptor,
    CredentialKeyError,
    EncryptedAuthConfig,
    EnvVarSource,
)


# ── Fixtures ──

@pytest.fixture
def key_bytes():
    return os.urandom(32)


@pytest.fixture
def encryptor(key_bytes, monkeypatch):
    monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(key_bytes).decode())
    return CredentialEncryptor()


@pytest.fixture
def plain_auth():
    return AuthConfig(type="bearer", token="sk-test-token-12345", username="svc",
                      password="my-app-password")


# ── CredentialEncryptor ──

class TestCredentialEncryptor:
    """AC-01: encrypt/decrypt roundtrip, nonce uniqueness."""

    def test_encrypt_decrypt_roundtrip(self, encryptor):
        plain = "my-secret-api-key"
        cipher = encryptor.encrypt(plain)
        assert cipher != plain
        assert encryptor.decrypt(cipher) == plain

    def test_non_ascii_plaintext(self, encryptor):
        plain = "密码·token·секрет"
        cipher = encryptor.encrypt(plain)
        assert encryptor.decrypt(cipher) == plain

    def test_empty_string(self, encryptor):
        cipher = encryptor.encrypt("")
        assert encryptor.decrypt(cipher) == ""

    def test_nonce_uniqueness(self, encryptor):
        """Same plaintext encrypted twice produces different ciphertext."""
        plain = "same-token"
        c1 = encryptor.encrypt(plain)
        c2 = encryptor.encrypt(plain)
        assert c1 != c2, "encrypt() must use fresh nonce each time"
        assert encryptor.decrypt(c1) == plain
        assert encryptor.decrypt(c2) == plain

    def test_wrong_key_raises_invalid_tag(self, encryptor, key_bytes, monkeypatch):
        """Decryption with wrong key raises InvalidTag."""
        cipher = encryptor.encrypt("top-secret")
        # Create a second encryptor with a different key
        wrong_key = os.urandom(32)
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(wrong_key).decode())
        wrong_enc = CredentialEncryptor()
        with pytest.raises(InvalidTag):
            wrong_enc.decrypt(cipher)

    def test_corrupted_ciphertext(self, encryptor):
        """Tampered ciphertext raises InvalidTag."""
        cipher = encryptor.encrypt("secret")
        raw = bytearray(base64.b64decode(cipher))
        raw[-1] ^= 0xFF  # flip a bit in the tag
        corrupted = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(InvalidTag):
            encryptor.decrypt(corrupted)

    def test_lazy_init_triggers_on_encrypt(self, key_bytes, monkeypatch):
        """encrypt() triggers lazy key load (P0-1 regression test)."""
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(key_bytes).decode())
        enc = CredentialEncryptor()
        # Never accessed enc.key — directly call encrypt
        cipher = enc.encrypt("test")
        assert enc.decrypt(cipher) == "test"

    def test_lazy_init_triggers_on_decrypt(self, key_bytes, monkeypatch):
        """decrypt() triggers lazy key load."""
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(key_bytes).decode())
        enc = CredentialEncryptor()
        cipher = enc.encrypt("test")  # this triggers init
        enc2 = CredentialEncryptor()
        assert enc2.decrypt(cipher) == "test"  # direct decrypt triggers init

    def test_missing_env_var_raises(self, monkeypatch):
        """CredentialEncryptor raises CredentialKeyError if env var absent."""
        monkeypatch.delenv("EARP_CREDENTIAL_KEY", raising=False)
        enc = CredentialEncryptor()
        with pytest.raises(CredentialKeyError):
            enc.encrypt("test")

    def test_key_source_parameter(self, key_bytes):
        """Explicit KeySource passed to constructor."""
        source = EnvVarSource("CUSTOM_KEY")
        import base64 as _b64
        os.environ["CUSTOM_KEY"] = _b64.b64encode(key_bytes).decode()
        try:
            enc = CredentialEncryptor(key_source=source)
            cipher = enc.encrypt("data")
            assert enc.decrypt(cipher) == "data"
        finally:
            del os.environ["CUSTOM_KEY"]


# ── EncryptedAuthConfig ──

class TestEncryptedAuthConfig:
    """AC-02: EncryptedAuthConfig repr, pickle, decrypt, subtype."""

    def test_isinstance_auth_config(self, encryptor, plain_auth):
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        assert isinstance(enc_auth, AuthConfig)

    def test_token_transparent_decrypt(self, encryptor, plain_auth):
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        assert enc_auth.token == "sk-test-token-12345"
        assert enc_auth.password == "my-app-password"

    def test_non_sensitive_fields_preserved(self, encryptor, plain_auth):
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        assert enc_auth.type == "bearer"
        assert enc_auth.username == "svc"

    def test_repr_no_plaintext(self, encryptor, plain_auth):
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        r = repr(enc_auth)
        assert "sk-test-token-12345" not in r
        assert "my-app-password" not in r
        assert "<encrypted>" in r

    def test_str_token_is_ciphertext(self, encryptor, plain_auth):
        """After encryption, _ciphertext_token != plaintext."""
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        # The internal ciphertext field is encrypted, not plaintext
        assert enc_auth._ciphertext_token != ""
        assert "sk-test-token-12345" not in enc_auth._ciphertext_token

    def test_setter_encrypts(self, encryptor, plain_auth):
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        enc_auth.token = "new-token-value"
        assert enc_auth.token == "new-token-value"
        # Ciphertext storage should be updated and not contain plaintext
        assert "new-token-value" not in enc_auth._ciphertext_token

    def test_empty_token_preserved(self, encryptor):
        auth = AuthConfig(type="bearer", token="")
        enc_auth = EncryptedAuthConfig.from_plaintext(auth, encryptor)
        assert enc_auth.token == ""
        assert str(enc_auth.token) == ""

    def test_empty_password_preserved(self, encryptor):
        auth = AuthConfig(type="basic", username="u", password="")
        enc_auth = EncryptedAuthConfig.from_plaintext(auth, encryptor)
        assert enc_auth.password == ""

    def test_pickle_roundtrip(self, encryptor, plain_auth):
        """Pickle excludes decryptor; after rehydrate, token works again."""
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        data = pickle.dumps(enc_auth)
        # Verify pickle binary contains no plaintext
        assert b"sk-test-token-12345" not in data
        assert b"my-app-password" not in data

        restored = pickle.loads(data)
        assert isinstance(restored, EncryptedAuthConfig)
        assert restored.type == "bearer"
        # Without rehydrate, accessing token should raise
        with pytest.raises(CredentialKeyError, match="no decryptor"):
            _ = restored.token

        restored.rehydrate(encryptor)
        assert restored.token == "sk-test-token-12345"
        assert restored.password == "my-app-password"

    def test_rehydrate_after_pickle_with_different_encryptor(self, encryptor, plain_auth, key_bytes, monkeypatch):
        """Rehydrate works with any encryptor that has the same key."""
        enc_auth = EncryptedAuthConfig.from_plaintext(plain_auth, encryptor)
        data = pickle.dumps(enc_auth)
        restored = pickle.loads(data)

        # Create a new encryptor with the same key
        monkeypatch.setenv("EARP_CREDENTIAL_KEY", base64.b64encode(key_bytes).decode())
        enc2 = CredentialEncryptor()
        restored.rehydrate(enc2)
        assert restored.token == "sk-test-token-12345"

    def test_no_decryptor_token_raises(self, encryptor, plain_auth):
        """Direct __init__ without decryptor raises on token access."""
        # This is what __setstate__ produces after unpickling
        enc_auth = EncryptedAuthConfig(
            type="bearer", username="u", token="", password="",
            _ciphertext_token=encryptor.encrypt("some-token"),
            _ciphertext_password=encryptor.encrypt("some-pw"),
            _decryptor=None,
        )
        with pytest.raises(CredentialKeyError, match="no decryptor"):
            _ = enc_auth.token
        with pytest.raises(CredentialKeyError, match="no decryptor"):
            _ = enc_auth.password
