# Security Phase 2 — L3 实现设计二次评审报告

## PRD-2026-006 v1.2 — 凭证加密 + 审计通道（修复验证）

| 字段 | 值 |
|------|-----|
| **设计文档** | L3 Security Phase 2 — 凭证加密 + 审计通道 |
| **文档版本** | v1.1 |
| **依赖 PRD** | PRD-2026-006 v1.2 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **上一轮** | [security-phase2-l3-design-review.md](../reviews/security-phase2-l3-design-review.md) — 7 个问题（1 P0 / 4 P1 / 2 P2） |
| **本轮** | P0: 0 / P1: 0 / P2: 2 → **共 2 个** |

---

## 总体评价

**上一轮的 7 个问题全部修复。** v1.1 设计质量高，可以进入实现阶段。

本轮新增 2 个 P2 级别的文档优化建议，均不阻塞实现。

---

## 上一轮问题修复确认（7/7 ✅）

### P0-1：`encrypt()`/`decrypt()` lazy init bug ✅

**修复**：`credential.py:132` 和 `credential.py:148` — `self.key` 在方法开头触发 lazy init。

```python
def encrypt(self, plaintext: str) -> str:
    self.key  # trigger lazy init  ← 新增
    nonce = secrets.token_bytes(12)
    ...

def decrypt(self, ciphertext: str) -> str:
    self.key  # trigger lazy init  ← 新增
    ...
```

**验证**：测试策略 §4.1 新增 "lazy init 在 encrypt 中触发（P0-1 回归）" 回归用例。✅

---

### P1-1：unpickle 后静默返回空 token ✅

**修复三件套**：
1. **getter** 中 `_decryptor is None` 时抛 `CredentialKeyError`（`credential.py:212-217`, `233-236`）
2. **`rehydrate(encryptor)`** 方法供 pickle restore 后重新注入 decryptor（`credential.py:251-253`）
3. **SDKMUST-11** 新增覆盖此行为

**设计判断正确**：抛明确的异常比静默返回 `""` 好——调用方不会发出 `Authorization: Bearer `（空 token）的请求。✅

---

### P1-2：`from_plaintext` 字段顺序依赖 ✅

**修复**：`credential.py:198-206` — 使用 `object.__setattr__` 绕过 setter，直接写 shadow 字段。

```python
instance = cls(
    type=auth.type, username=auth.username,
    token="", password="", _decryptor=encryptor,
)
object.__setattr__(instance, "_ciphertext_token",
    encryptor.encrypt(auth.token) if auth.token else "")
object.__setattr__(instance, "_ciphertext_password",
    encryptor.encrypt(auth.password) if auth.password else "")
```

**dataclass init 执行顺序分析**：
1. `token=""` → setter → `_decryptor` 为 None → `_ciphertext_token = ""`
2. `password=""` → setter → `_decryptor` 为 None → `_ciphertext_password = ""`
3. `_ciphertext_token` 字段由 dataclass 以默认值 `""` 覆盖
4. `_ciphertext_password` 字段由 dataclass 以默认值 `""` 覆盖
5. `_decryptor=encryptor` 赋值
6. `object.__setattr__` 覆盖 `_ciphertext_token` 和 `_ciphertext_password` 为密文

最终结果正确。✅

---

### P1-3：空 `__post_init__` ✅

**修复**：`__post_init__` 已移除。token/password 的行为由 `@property` 在类定义层控制，不需要 `__post_init__` 干预。✅

---

### P1-4：`publish_audit_event` 原地修改 ✅

**修复**：`audit.py:333-334` — docstring 明确注明：

```
NOTE: This function modifies 'event' in place (sets log_id + timestamp).
The same event instance should NOT be published more than once.
```

测试策略 §4.2 新增"同一 event 两次 publish → log_id 变化（原地修改特性）"用例，确保行为被测试覆盖。✅

---

### P2-1：函数体内 import ✅

**修复**：`key_source.py:45-47` — `os`, `base64`, `binascii` 移到模块顶部。✅

---

### P2-2：InvalidTag 异常类型未文档化 ✅

**修复**：两处补充：
1. `credential.py:143-147` — `decrypt()` docstring 明确 `cryptography.exceptions.InvalidTag`
2. SDKMUST-02 更新为 `抛 cryptography.exceptions.InvalidTag（ValueError 子类）` ✅

---

## 本轮发现的新问题（2 个 P2）

### P2-1：直接构造 `EncryptedAuthConfig(...)` 时 token/password setter 存储明文

**文件**：设计文档 §2.2 `credential.py:157-180`

`EncryptedAuthConfig` 是公开 dataclass，调用方可能绕过 `from_plaintext` 直接构造：

```python
# 错误用法：直接构造
ec = EncryptedAuthConfig(
    type="bearer",
    token="my-token",   # 走 setter → _decryptor is None → _ciphertext_token = "my-token"（明文！）
    username="",
    password="",
    _decryptor=encryptor,  # 初始化在后，setter 时 _decryptor 还是 None
)
```

此时 `_ciphertext_token` 中存储的是明文 `"my-token"`，而不是密文。后续调用 `ec.token` 会走 `_decryptor.decrypt("my-token")` → GCM 认证失败 → `InvalidTag`。

**影响**：低。正确的使用方式是通过 `from_plaintext` 类方法创建。且 dataclass 参数的顺序（`_decryptor` 在最后）使得即使调用方意识到问题也无法通过调整参数顺序解决——这是 dataclass 继承的固有行为。

**建议**：在 `EncryptedAuthConfig` 的 docstring 中加一句话：

```
Note: Always use EncryptedAuthConfig.from_plaintext() to create instances.
Direct construction via __init__ is NOT supported — it will store
token/password as plaintext in shadow fields.
```

---

### P2-2：`publish_audit_event` 依赖 docstring 约束而非代码级防护

**文件**：设计文档 §2.3 `audit.py:327-341`

重复发布的防护完全依赖 docstring 中的 "The same event instance should NOT be published more than once"，没有代码级别的 guard。

**影响**：极低。Phase 2 的使用场景（AUTH_EXPIRED 时发布一次）不会触发这个问题。

**建议**：如果未来需要防护，可加一个轻量 guard：

```python
def publish_audit_event(event: AuditEvent) -> None:
    if event.log_id:  # 已经发布过
        raise ValueError("AuditEvent has already been published")
    ...
```

当前保持现状即可。

---

## 变更摘要

### 修复统计

| 级别 | 上一轮 | 已修复 | 本次新增 | 未修复 |
|:----:|:------:|:------:|:--------:|:------:|
| P0 | 1 | 1 | 0 | **0** |
| P1 | 4 | 4 | 0 | **0** |
| P2 | 2 | 2 | 2 | **2** |

### v1.1 新增内容

| 新增项 | 说明 |
|:------|:-----|
| `self.key` lazy init trigger | 在 `encrypt()`/`decrypt()` 开头触发 AESGCM 初始化 |
| `CredentialKeyError` in getters | `_decryptor is None` → 抛异常（非静默） |
| `rehydrate(encryptor)` | pickle restore 后重新注入 decryptor |
| `object.__setattr__` | 绕过 setter 直接写 shadow 字段 |
| `InvalidTag` 文档化 | docstring + SDKMUST-02 |
| SDKMUST-11 | 新增：unpickle 后访问 token/password 的行为 |
| §6 评审修复记录 | 完整追踪 7 个修复项 |

---

## SDKMUST 对齐终审

| # | 条款 | 状态 |
|:-:|:-----|:----:|
| 01 | `secrets.token_bytes(12)` nonce，每次加密不同密文 | ✅ |
| 02 | `decrypt()` 密钥/密文错误 → `InvalidTag` | ✅ |
| 03 | `EncryptedAuthConfig` 是 `AuthConfig` 子类 | ✅ |
| 04 | `__repr__` 显示 `<encrypted>` | ✅ |
| 05 | `__getstate__` 仅返回密文 | ✅ |
| 06 | `key_source` 可选，默认 `EnvVarSource` | ✅ |
| 07 | `EnvVarSource.get_key()` 缺失/错误长度 → `CredentialKeyError` | ✅ |
| 08 | `AuditEvent` 11 个 Audit Spec 字段 | ✅ |
| 09 | UUID4 `log_id` + ISO 8601 `timestamp` | ✅ |
| 10 | logger `"earp.audit"` INFO JSON | ✅ |
| 11 | `_decryptor is None` → `CredentialKeyError` + `rehydrate()` | ✅ |

---

## 评审总结

### 数据统计

| 类别 | 上一轮 | 已修复 | 本次新增 | 未修复 |
|:----|:------:|:------:|:--------:|:------:|
| P0 | 1 | 1 | 0 | **0** |
| P1 | 4 | 4 | 0 | **0** |
| P2 | 2 | 2 | 2 | **2** |

### 结论

**v1.1 设计质量高，可以进入实现阶段。** 代码接口签名、SDKMUST 条款、测试策略均已完备。2 个新增 P2 为文档优化建议，不阻塞实现。

**v1.1 亮点**：
- lazy init bug 修复精准（`self.key` 一行代码）
- unpickle 安全设计完善（抛异常 + `rehydrate` + SDKMUST-11）
- `from_plaintext` 用 `object.__setattr__` 绕过 setter，消除了字段顺序依赖
- `InvalidTag` 异常类型文档化到 docstring 和 SDKMUST-02
- SDKMUST 11 条全部可追踪到具体代码行和测试用例
