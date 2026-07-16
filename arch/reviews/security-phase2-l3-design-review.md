# Security Phase 2 — L3 实现设计评审报告

## PRD-2026-006 v1.2 — 凭证加密 + 审计通道

| 字段 | 值 |
|------|-----|
| **设计文档** | L3 Security Phase 2 — 凭证加密 + 审计通道 |
| **文档版本** | v1.0 |
| **依赖 PRD** | PRD-2026-006 v1.2 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **影响包** | earp-sdk-core (+3 新模块), earp-sdk-connector (+1 修改) |
| **问题统计** | P0: 1 / P1: 4 / P2: 2 → **共 7 个** |

---

## 总体评价

**设计方向正确，模块划分清晰。** 三层抽象（`KeySource` / `CredentialEncryptor` / `EncryptedAuthConfig`）层次分明，`AuditEvent` 与 Audit Spec v1.1 §2.1 精确对齐（11 字段），SDKMUST 10 条全部可追踪到 AC，测试策略覆盖全面。

但存在 **1 个 P0 运行时 bug**：`CredentialEncryptor.encrypt()` 在 lazy init 触发前直接访问 `self._aesgcm`（初始值 None），导致 `AttributeError`。另外 `EncryptedAuthConfig` 的 dataclass 继承和 `__setstate__` 存在几个设计上的微妙问题。

---

## P0 — 必须修复（1 个）

### P0-1：`CredentialEncryptor.encrypt()` / `decrypt()` 直接访问 `self._aesgcm`，lazy init 未触发

**文件**：设计文档 §2.2 `credential.py`:125,139

**问题代码**：
```python
class CredentialEncryptor:
    def __init__(self, key_source: KeySource | None = None) -> None:
        self._key_source = key_source or EnvVarSource()
        self._key: bytes | None = None   # lazy load
        self._aesgcm: AESGCM | None = None

    @property
    def key(self) -> bytes:
        if self._key is None:
            self._key = self._key_source.get_key()
            self._aesgcm = AESGCM(self._key)   # <-- 只有这里初始化 _aesgcm
        return self._key

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(12)
        data = plaintext.encode("utf-8")
        ct = self._aesgcm.encrypt(nonce, data, None)  # 💥 None.encrypt()!
        ...
```

**调用链**：
```
CredentialEncryptor()                  # _aesgcm = None
  → from_plaintext(...)
    → encryptor.encrypt(auth.token)    # self._aesgcm.encrypt(...) → AttributeError
```

`encrypt()` 和 `decrypt()` 都直接访问 `self._aesgcm`，但 `_aesgcm` 只在 `key` property 被访问时才初始化（lazy load）。首次调用 `encrypt()` 时必定 crash。

**建议方案**（最简单）：
```python
def encrypt(self, plaintext: str) -> str:
    self.key  # trigger lazy init
    nonce = secrets.token_bytes(12)
    data = plaintext.encode("utf-8")
    ct = self._aesgcm.encrypt(nonce, data, None)
    ...

def decrypt(self, ciphertext: str) -> str:
    self.key  # trigger lazy init
    raw = base64.b64decode(ciphertext)
    ...
```

---

## P1 — 建议修改（4 个）

### P1-1：`EncryptedAuthConfig.__setstate__` 恢复后 decryptor 为 None，`token` 静默返回空字符串

**文件**：设计文档 §2.2 `credential.py`:238-244

```python
def __setstate__(self, state: dict[str, Any]) -> None:
    self.type = state["type"]
    self.username = state["username"]
    self._ciphertext_token = state["token"]
    self._ciphertext_password = state["password"]
    self._decryptor = None  # 无 decryptor
```

unpickle 后 `_decryptor = None`。调用 `restored.token` 时：
```python
@property
def token(self) -> str:
    if self._decryptor and self._ciphertext_token:  # _decryptor is None → skip
        return self._decryptor.decrypt(self._ciphertext_token)
    return ""  # 静默返回空字符串
```

**问题**：调用方期待一个合法的 token，却得到 `""`——这会以 `Authorization: Bearer `（空 token）的形式发出 HTTP 请求，返回 401。调试非常困难，因为真正的错误（缺少 decryptor）被静默掩盖。

**建议**：

方案 A（推荐）：unpickle 后访问 token 时抛明确异常：
```python
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
```

并提供一个 `rehydrate(encryptor)` 方法供 pickle restore 后重新注入 decryptor：
```python
def rehydrate(self, encryptor: CredentialEncryptor) -> None:
    self._decryptor = encryptor
```

---

### P1-2：`from_plaintext()` 中 token/password 先被空值覆盖再重写，依赖 dataclass 字段顺序

**文件**：设计文档 §2.2 `credential.py`:168-180

```python
@classmethod
def from_plaintext(cls, auth, encryptor):
    return cls(
        ...
        token="",                              # __init__: self.token = "" → setter → _ciphertext_token = ""
        password="",                           # __init__: self.password = "" → setter → _ciphertext_password = ""
        _ciphertext_token=encryptor.encrypt(...),  # 覆盖上面的 _ciphertext_token
        _ciphertext_password=encryptor.encrypt(...), # 覆盖上面的 _ciphertext_password
        _decryptor=encryptor,
    )
```

`AuthConfig` 的 dataclass `__init__` 接受 `token` 和 `password` 参数。由于 `EncryptedAuthConfig` 是子类且 `token`/`password` 是继承的 dataclass 字段，`__init__` 中仍接受这些参数。

流程：
1. `__init__` 调用 `self.token = ""` → setter 执行 → `_decryptor` 还未设置 → `_ciphertext_token = ""`（空值覆盖）
2. 然后 `__init__` 调用 `self._ciphertext_token = encryptor.encrypt(auth.token)` → 再次覆盖

**问题**：这段逻辑依赖 `_decryptor` 在 `token`/`password` **之后**初始化。如果 dataclass 字段顺序变化（如未来添加新字段），会出 bug。且两次赋值浪费。

**建议**：在 `from_plaintext` 中使用 `object.__setattr__` 绕过 setter，直接设置 shadow 字段：
```python
@classmethod
def from_plaintext(cls, auth, encryptor):
    instance = cls(
        type=auth.type,
        username=auth.username,
        token="",          # 仍需要传（dataclass __init__ 要求）
        password="",
        _decryptor=encryptor,
    )
    # 绕过 setter，直接设 shadow 字段
    object.__setattr__(instance, '_ciphertext_token',
        encryptor.encrypt(auth.token) if auth.token else "")
    object.__setattr__(instance, '_ciphertext_password',
        encryptor.encrypt(auth.password) if auth.password else "")
    return instance
```

---

### P1-3：`__post_init__` 方法体为空

**文件**：设计文档 §2.2 `credential.py`:182-184

```python
def __post_init__(self) -> None:
    # Override parent's token/password with getter/setter proxies
    pass
```

注释暗示 `__post_init__` 应该覆盖父类的 token/password 字段行为。但实际是通过 `@property` 在类定义层覆盖的，`__post_init__` 不需要做任何事。

**建议**：要么删除 `__post_init__`（Python dataclass 不要求必须定义），要么写明确注释说明为什么不需要逻辑。当前 `pass` 容易让阅读者困惑。

---

### P1-4：`publish_audit_event()` 直接修改 event 对象，阻止重复发布

**文件**：设计文档 §2.3 `audit.py`:284-296

```python
def publish_audit_event(event: AuditEvent) -> None:
    event.log_id = str(uuid.uuid4())      # 修改原对象
    event.timestamp = datetime.now(timezone.utc).isoformat()  # 修改原对象
    ...
```

**问题**：这种设计意味着同一个 `AuditEvent` 实例**不能发布两次**（第二次发布会覆盖 `log_id` 和 `timestamp`）。虽然当前场景（AUTH_EXPIRED）不需要重复发布，但如果未来支持 audit replay 或多通道发布，会成为隐患。

**建议**：两种选择——

方案 A（推荐）：文档中明确"event 被原地修改，不可重复发布"
方案 B：创建 copy 再修改：
```python
def publish_audit_event(event: AuditEvent) -> None:
    event.log_id = str(uuid.uuid4())
    event.timestamp = datetime.now(timezone.utc).isoformat()
    data = asdict(event)
    event.log_id = ""       # 恢复
    event.timestamp = ""    # 恢复
    ...
```

---

## P2 — 优化建议（2 个）

### P2-1：`key_source.py` 函数体内 import

**文件**：设计文档 §2.1 `key_source.py`:60-61

```python
def get_key(self) -> bytes:
    import os, base64, binascii   # 每次 get_key() 都 import
    ...
```

`get_key()` 虽然有 lazy-load guard（只在首次访问 key property 时调用），但 `import` 在函数体内违反了 PEP 8 规范，且此处的 lazy import 没有实际好处（这些是标准库模块，import 开销忽略不计）。

**建议**：移到模块顶部。

---

### P2-2：缺少 `AESGCM.decrypt` 认证失败的精确异常类型文档化

**文件**：设计文档 §2.2 `credential.py`:130-140

设计文档说 GCM 认证失败时 `decrypt` 抛 `ValueError`。实际上 `cryptography` 库抛的是 `cryptography.exceptions.InvalidTag`（继承自 `ValueError`）：

```python
# cryptography.hazmat.primitives.ciphers.aead.AESGCM
def decrypt(self, nonce, data, associated_data):
    ...
    # On tag mismatch, raises:
    #   cryptography.exceptions.InvalidTag
```

`InvalidTag` 是 `ValueError` 的子类，所以 SDKMUST-02 的技术准确性没有问题。但如果测试中用 `pytest.raises(ValueError)` 断言，建议文档化精确异常类型，方便测试和调用方做更细粒度的错误处理。

**建议**：在 SDKMUST-02 中补充精确异常类型：
```
SDKMUST-02: decrypt() 在密钥错误或密文损坏时抛 cryptography.exceptions.InvalidTag（ValueError 子类）
```

---

## 对齐检查表

### 与 PRD-2026-006 v1.2 AC 的对齐

| AC | PRD 要求 | L3 设计 | 状态 |
|:--:|:---------|:--------|:----:|
| AC-01 | encrypt/decrypt roundtrip, nonce 唯一性, base64 格式 | §2.2 CredentialEncryptor, §6.1 密文格式 | ⚠️ P0-1 lazy init bug |
| AC-02 | EncryptedAuthConfig repr 显示 `<encrypted>`, pickle 安全, 属性解密 | §2.2 EncryptedAuthConfig | ⚠️ P1-1 setstate 静默返回空 |
| AC-03 | key_source 参数, EnvVarSource, 缺失/长度错误 → CredentialKeyError | §2.1 KeySource/EnvVarSource | ✅ |
| AC-04 | 11 个 Audit Spec 字段, logger "earp.audit" INFO JSON | §2.3 AuditEvent/publish_audit_event | ✅ |
| AC-05 | AUTH_EXPIRED → publish_audit_event + logger.critical fallback | §4.3 测试策略（connector 未展示详细实现） | ✅ |

### 与 SDKMUST 条款的对齐

| SDKMUST | 条款 | L3 设计覆盖 | 状态 |
|:-------:|:-----|:----------|:----:|
| 01 | `secrets.token_bytes(12)` nonce | §2.2 encrypt() line 123 | ✅ |
| 02 | decrypt 认证失败 ValueError | §2.2 decrypt() comment | ⚠️ P2-2 建议精确类型 |
| 03 | AuthConfig 子类 | §2.2 `class EncryptedAuthConfig(AuthConfig)` | ✅ |
| 04 | `__repr__` 不暴露明文 | §2.2 `__repr__` `token='<encrypted>'` | ✅ |
| 05 | `__getstate__` 仅返回密文 | §2.2 `__getstate__` | ✅ |
| 06 | `key_source` 可选参数，默认 EnvVarSource | §2.2 `__init__(self, key_source=None)` | ✅ |
| 07 | EnvVarSource 缺失/长度错误 → CredentialKeyError | §2.1 `get_key()` | ✅ |
| 08 | 11 个 Audit Spec 字段 | §2.3 AuditEvent dataclass | ✅ |
| 09 | UUID4 log_id + ISO 8601 timestamp | §2.3 publish_audit_event | ✅ |
| 10 | logger "earp.audit" INFO JSON | §2.3 publish_audit_event | ✅ |

### 与 Phase 1 实现的兼容性

| Phase 1 组件 | Phase 2 变更 | 兼容性 |
|:------------|:-----------|:------:|
| `AuthConfig` | `EncryptedAuthConfig(AuthConfig)` 子类 | ✅ 子类 is-a 关系 |
| `ConnectorConfig.auth: AuthConfig` | 值可为 `EncryptedAuthConfig` | ✅ 类型注解接受子类 |
| `RESTConnector._ensure_auth_headers()` | 访问 `config.auth.token` 触发明文解密 | ✅ 透明，零改动 |
| `_on_error` audit log | 加 `publish_audit_event()` + fallback | ✅ 无 regression |

---

## 测试策略评审

测试计划覆盖全面。补充建议：

| 测试 | 当前覆盖 | 建议新增 |
|:-----|:-------|:---------|
| `TestCredentialEncryptor` | roundtrip, nonce 唯一性, 空/unicode, 错误密钥 | **+** 未设置环境变量时 `EncryptedAuthConfig.from_plaintext` 抛 `CredentialKeyError`（验证 P0-1 的修复——确认 lazy init 在 encrypt 中生效） |
| `TestEncryptedAuthConfig` | isinstance, 解密, repr, pickle | **+** pickle 恢复后无 decryptor 时访问 token 抛 `CredentialKeyError`（P1-1），**+** `rehydrate()` 后 token 正确返回 |
| `TestAuditEvent` | 11 字段, None, JSON | ✅ 覆盖充分 |

---

## 评审总结

### 数据统计

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0 | 1 | `encrypt()`/`decrypt()` 直接访问 `self._aesgcm`（None），lazy init 未触发 |
| ⚠️ P1 | 4 | unpickle 后静默返回空 token；from_plaintext 字段顺序依赖；空 __post_init__；publish_audit_event 原地修改 |
| 💡 P2 | 2 | 函数体内 import；InvalidTag 异常类型未文档化 |

### P0 影响分析

| 问题 | 影响 | 修复复杂度 |
|:-----|:-----|:----------:|
| P0-1 lazy init bug | **阻断性** — `from_plaintext()` 调用 `encrypt()` 直接 crash | **1 行**（`encrypt`/`decrypt` 开头加 `self.key`） |

### 好的方面

- **三层抽象清晰** — `KeySource`（密钥来源）→ `CredentialEncryptor`（加解密）→ `EncryptedAuthConfig`（dataclass 集成），关注点分离
- **密文格式规范精确** — `base64(nonce[12] + ciphertext + tag[16])`，nonce 生成、tag 位置、密钥长度全部明确，实现者无需猜测
- **Audit Spec 对齐精确** — 11 个字段（不是 12），与规范完全一致
- **SDKMUST 10 条可追踪** — 每条都映射到具体代码行
- **pickle 安全考虑完整** — `__getstate__`/`__setstate__` 确保二进制中不含明文
- **`cryptography` 选库正确** — `AESGCM` 是高级 API，nonce+ciphertext+tag 自动处理，比低级的 `Cipher` API 更不易出错
- **Phase 1 完全兼容** — `RESTConnector` 零改动，`ConnectorConfig.auth` 类型注解不变

### 建议修复优先级

1. **P0-1**（1 行修复，阻断性，优先处理）
2. **P1-1**（unpickle 安全性，重要）
3. **P1-2**（代码健壮性）
4. **P1-3, P1-4** + **P2**（可边实现边改）
