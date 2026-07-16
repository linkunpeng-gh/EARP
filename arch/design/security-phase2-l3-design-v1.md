# Security Phase 2 — L3 实现设计文档

## PRD-2026-006 v1.2

| 字段 | 值 |
|------|-----|
| **设计文档** | L3 Security Phase 2 — 凭证加密 + 审计通道 |
| **对齐规范** | Security Spec v1.1 §2.2, §6.2; Audit Spec v1.1 §2.1 |
| **依赖 PRD** | PRD-2026-006 v1.2 |
| **版本** | v1.1 |
| **日期** | 2026-07-15 |
| **影响包** | earp-sdk-core (+3 新模块), earp-sdk-connector (+1 修改) |

> **v1.1 变更**：修复 P0-1 (lazy init bug)、P1-1 (unpickle 静默空 token)、P1-2 (from_plaintext 字段顺序依赖)、P1-3 (空 __post_init__)、P1-4 (publish_audit_event 原地修改)、P2-1 (函数体内 import)、P2-2 (InvalidTag 异常类型)。

---

## 1. 模块结构

```
libs/earp-sdk-core-py/src/earp_sdk_core/
├── credential.py          # 新增: CredentialEncryptor + EncryptedAuthConfig
├── key_source.py          # 新增: KeySource 抽象 + EnvVarSource
├── audit.py               # 新增: AuditEvent + publish_audit_event
├── errors.py              # 修改: 新增 CredentialKeyError
├── __init__.py            # 修改: 导出新符号
├── config.py              # 不变
└── masking.py             # 不变
```

---

## 2. 接口签名

### 2.1 key_source.py — KeySource 抽象

```python
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
        # Try base64 first, then hex
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception:
            try:
                key = binascii.unhexlify(raw)
            except Exception:
                raise CredentialKeyError(
                    f"{self._var_name} must be base64 or hex encoded"
                )
        if len(key) != 32:
            raise CredentialKeyError(
                f"Key must be 32 bytes, got {len(key)} bytes"
            )
        return key
```

### 2.2 credential.py — CredentialEncryptor + EncryptedAuthConfig

```python
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
        bypassing the token/password setters (which would encode
        with _decryptor before it's set).
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
```

### 2.3 audit.py — AuditEvent + publish_audit_event

```python
"""Audit event publishing — Security Spec §6.2, Audit Spec v1.1 §2.1."""

from __future__ import annotations
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class AuditEvent:
    """Audit event aligned with Audit Spec v1.1 §2.1 — 11 fields."""

    source: str                              # MUST  e.g. "security", "runtime"
    event_type: str                          # MUST  e.g. "AUTH_EXPIRED"
    tenant_id: str                           # MUST  tenant scope
    user_id: str                             # MUST  user identity ("" for system events)
    action: str                              # MUST  e.g. "connector_auth"
    result: str                              # MUST  "success" | "failure" | "pending"

    # Auto-generated by publish_audit_event()
    log_id: str = field(default="", init=False)
    timestamp: str = field(default="", init=False)

    # SHOULD fields
    execution_id: str | None = None
    subject: str | None = None
    detail: dict | None = None


_audit_logger = logging.getLogger("earp.audit")


def publish_audit_event(event: AuditEvent) -> None:
    """Publish a standardized audit event.

    Writes JSON-serialized event to logger 'earp.audit' at INFO level.
    Auto-generates log_id (UUID4) and timestamp (ISO 8601 UTC).

    NOTE: This function modifies 'event' in place (sets log_id + timestamp).
    The same event instance should NOT be published more than once.
    """
    event.log_id = str(uuid.uuid4())
    event.timestamp = datetime.now(timezone.utc).isoformat()

    data = asdict(event)
    json_str = json.dumps(data, ensure_ascii=False, default=str)
    _audit_logger.log(logging.INFO, json_str)
```

### 2.4 errors.py — 新增错误码

```python
# 在已有 ConnectorErrorCode / CapabilityErrorCode 之后新增:

class CredentialKeyError(Exception):
    """Raised when credential encryption key is missing, malformed,
    wrong length, or decryptor is not available (after unpickling)."""
    pass
```

---

## 3. SDKMUST 条款

| # | 条款 | 对应 AC |
|:-:|:-----|:------:|
| SDKMUST-01 | `CredentialEncryptor.encrypt()` 使用 `secrets.token_bytes(12)` 生成 nonce，每次加密产生不同密文 | AC-01 |
| SDKMUST-02 | `CredentialEncryptor.decrypt()` 在密钥错误或密文损坏时抛 `cryptography.exceptions.InvalidTag`（`ValueError` 子类） | AC-01 |
| SDKMUST-03 | `EncryptedAuthConfig` 是 `AuthConfig` 的子类，保持 `isinstance` 和类型注解兼容 | AC-02 |
| SDKMUST-04 | `EncryptedAuthConfig.__repr__()` 不暴露明文 token/password | AC-02 |
| SDKMUST-05 | `EncryptedAuthConfig.__getstate__()` 仅返回密文，`_decryptor` 不序列化 | AC-02 |
| SDKMUST-06 | `CredentialEncryptor.__init__()` 接受可选 `key_source: KeySource` 参数，默认 `EnvVarSource("EARP_CREDENTIAL_KEY")` | AC-03 |
| SDKMUST-07 | `EnvVarSource.get_key()` 在环境变量缺失或 key 长度 != 32 时抛 `CredentialKeyError` | AC-03 |
| SDKMUST-08 | `AuditEvent` 包含全部 11 个 Audit Spec §2.1 字段 | AC-04 |
| SDKMUST-09 | `publish_audit_event()` 自动生成 UUID4 `log_id` 和 ISO 8601 UTC `timestamp` | AC-04 |
| SDKMUST-10 | `publish_audit_event()` 将事件 JSON 序列化写入 logger `"earp.audit"` (INFO) | AC-04 |
| SDKMUST-11 | `EncryptedAuthConfig.token`/`password` 在 `_decryptor is None` 时抛 `CredentialKeyError`，调用方需 `rehydrate()` | AC-02 |

---

## 4. 测试策略

### 4.1 test_credential.py

| 测试类 | 覆盖 |
|:--------|:-----|
| `TestCredentialEncryptor` | encrypt→decrypt roundtrip, 同一明文两次 encrypt 不同, 空字符串, unicode, 错误密钥抛 InvalidTag, lazy init 在 encrypt 中触发（P0-1 回归）, 未设环境变量时 from_plaintext 抛 CredentialKeyError（验证 lazy init 生效） |
| `TestEncryptedAuthConfig` | from_plaintext 创建, isinstance(AuthConfig), token/password 透明解密, __repr__ 不泄露, __repr__ 显示 `<encrypted>`, pickle roundtrip（密文在二进制中）, pickle 恢复后无 decryptor → token 访问抛 CredentialKeyError, rehydrate() 后 token 正确返回, setter 加密, 空 token/password 边界 |
| `TestKeySource` | EnvVarSource base64 key, hex key, missing var, wrong length, invalid encoding |

### 4.2 test_audit.py

| 测试类 | 覆盖 |
|:--------|:-----|
| `TestAuditEvent` | 构造 11 字段, 默认值, None 字段 |
| `TestPublishAuditEvent` | publish 后 caplog 验证: log_id UUID4, timestamp ISO8601, 全部 11 字段, JSON 可解析, 两次 publish 不同 log_id, 同一 event 两次 publish → log_id 变化（原地修改特性） |

### 4.3 test_connector.py（追加）

| 测试 | 覆盖 |
|:-----|:-----|
| AUTH_EXPIRED → publish_audit_event 调用 | 验证 audit logger 收到 11 字段 JSON 事件 |
| logger.critical fallback 保留 | 同时存在本地 CRITICAL 日志 |

---

## 5. 包依赖更新

```toml
# earp-sdk-core-py/pyproject.toml
[project]
dependencies = ["cryptography>=41.0"]
```

其他 SDK 无需更新——它们通过 `earp-sdk-core` 间接获取新功能。

---

## 6. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | `encrypt()`/`decrypt()` 直接访问 `self._aesgcm`（None） | 在 `encrypt()`/`decrypt()` 开头加 `self.key` 触发 lazy init |
| P1-1 | unpickle 后 `_decryptor=None`，token 静默返回 `""` | token/password getter 中 `_decryptor is None` 时抛 `CredentialKeyError`；新增 `rehydrate(encryptor)` 方法 |
| P1-2 | `from_plaintext` 字段顺序依赖 | 使用 `object.__setattr__` 绕过 setter，直接写 `_ciphertext_*` |
| P1-3 | `__post_init__` 为空 | 移除 `__post_init__`（无必要） |
| P1-4 | `publish_audit_event` 原地修改 event | 文档明确 "NOT be published more than once" |
| P2-1 | `key_source.py` 函数体内 import | `os`, `base64`, `binascii` 移到模块顶部 |
| P2-2 | `InvalidTag` 异常类型未文档化 | SDKMUST-02 改为明确 `cryptography.exceptions.InvalidTag` + decrypt docstring |
