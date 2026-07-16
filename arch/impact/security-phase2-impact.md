# Security Phase 2 — 架构影响分析

## PRD-2026-006 v1.2

| 字段 | 值 |
|------|-----|
| **影响范围** | earp-sdk-core (+3 新模块), earp-sdk-connector (+1 文件修改) |
| **架构决策** | 无 ADR 级别变更 |
| **Breaking Change** | 否——所有变更向后兼容 |
| **新增依赖** | `cryptography` (AES-256-GCM) |
| **分析人** | Arch Agent |
| **日期** | 2026-07-15 |

---

## 1. 影响范围

### 1.1 包级影响

| 包 | 影响类型 | 新模块 | 修改文件 |
|:---|:--------|:-------|:---------|
| `earp-sdk-core` | **新增功能** | `credential.py` (CredentialEncryptor + KeySource + EncryptedAuthConfig) | `__init__.py` (导出) |
| | | `audit.py` (AuditEvent + publish_audit_event) | |
| | | `key_source.py` (EnvVarSource + KeySource 抽象) | |
| `earp-sdk-connector` | **修改** | — | `base.py` (_on_error → publish_audit_event) |
| `earp-sdk-runtime` | 无影响 | — | — |
| `earp-sdk-capability` | 无影响 | — | — |
| `earp-sdk-plugin` | 无影响 | — | — |

### 1.2 PRD AC → 包映射

| AC | 核心接口 | 所在包 |
|:--:|:---------|:------:|
| AC-01 | encrypt/decrypt + nonce 唯一性 | core: `credential.py` |
| AC-02 | EncryptedAuthConfig(AuthConfig) + pickle 安全 | core: `credential.py` |
| AC-03 | EARP_CREDENTIAL_KEY → KeySource | core: `credential.py` + `key_source.py` |
| AC-04 | AuditEvent + publish_audit_event → logger | core: `audit.py` |
| AC-05 | _on_error → publish_audit_event | connector: `base.py` |

---

## 2. 架构层影响

### 2.1 L2 规范对齐

| 规范 | 条款 | 实现模块 |
|:-----|:-----|:---------|
| Security Spec §2.2 | MUST: AES-256-GCM 加密存储 | `credential.py` → CredentialEncryptor |
| Security Spec §2.2 | SHOULD: Vault 等外部 KMS | `key_source.py` → KeySource 抽象（Phase 2.1 实现） |
| Security Spec §6.2 | MUST: 安全事件写入审计日志 | `audit.py` → publish_audit_event |
| Audit Spec §2.1 | MUST: 11 个统一字段 | `audit.py` → AuditEvent dataclass |

### 2.2 新增依赖

```
earp-sdk-core
  └── cryptography>=41.0  (新增，AES-256-GCM)
```

`cryptography` 是 Python 安全生态的标准库，广泛使用于 Django、FastAPI、SQLAlchemy。选择理由：
- `cryptography.hazmat.primitives.ciphers.aead.AESGCM` 提供正确的 AES-GCM 实现（自动管理 tag、内置 nonce 检查）
- 替代 `pycryptodome`（GCM 需要手动拼接 tag）和 stdlib `hashlib`（无加密原语）

### 2.3 向后兼容性

```
Phase 1 代码                            Phase 2 代码
────────────────────────────────────    ────────────────────────────────────
AuthConfig(token="sk-xxx")              EncryptedAuthConfig.from_plaintext(
                                          AuthConfig(token="sk-xxx"), enc)
                                        → isinstance(auth, AuthConfig) == True ✅

config.auth: AuthConfig                 config.auth: EncryptedAuthConfig ✅
config.auth.token  # → "sk-xxx"        config.auth.token  # → "sk-xxx" ✅

RESTConnector._ensure_auth_headers()    RESTConnector._ensure_auth_headers()
  config.auth.token → Bearer header       config.auth.token → Bearer header ✅
  (透明解密，无需修改调用方)
```

---

## 3. 测试影响

### 3.1 新增测试文件

| 文件 | 测试内容 | AC 覆盖 |
|:-----|:---------|:-------:|
| `core-py/tests/test_credential.py` | CredentialEncryptor encrypt/decrypt, nonce 唯一性, 错误密钥, 空明文 | AC-01, AC-03 |
| | EncryptedAuthConfig from_plaintext, repr, pickle, init, 类型兼容 | AC-02 |
| `core-py/tests/test_audit.py` | AuditEvent 构造, 11 字段完整性, publish 写入 logger, JSON 格式 | AC-04 |
| `connector-py/tests/test_connector.py` | AUTH_EXPIRED → publish_audit_event 调用 + logger fallback | AC-05 |

### 3.2 现有测试影响

无回归风险——所有新增是纯增量。

---

## 4. 风险与未知项

| # | 风险 | 缓解措施 |
|:-:|:-----|:---------|
| 1 | `cryptography` 在某些 CI 环境需编译（需要 `rust` toolchain ≥1.65） | 使用 PyPI wheel 预编译版本（macOS/Linux/Windows 均已提供） |
| 2 | `EncryptedAuthConfig.__getattr__` 代理可能与 dataclass `__init__` 交互异常 | PRD 已指定子类化 `AuthConfig`（非 `__getattr__` 代理），规避此问题 |
| 3 | 审计 logger `"earp.audit"` 在生产环境需配置 handler | Phase 2 只负责输出到 logger，handler 配置留运维层 |
| 4 | 环境变量 `EARP_CREDENTIAL_KEY` 长度需验证 | AC-03 要求 32 字节（base64 解码后），不足时抛明确错误 |
| 5 | pickle 序列化 EncryptedAuthConfig 时 `__getstate__` 需排除 `_decryptor` 引用 | `__getstate__` 返回 `{fields, _ciphertexts}`，`_decryptor` 不序列化 |

---

## 5. 总结

**影响范围小，无架构变更，全部向后兼容。** 新增 3 个 core 模块（credential.py / audit.py / key_source.py）和 1 处 connector 修改，新增 1 个 pip 依赖（cryptography）。不涉及 L1 架构变动，不需要 ADR。
