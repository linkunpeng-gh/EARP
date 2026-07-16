# PRD-2026-006 v1.1

## Security Phase 2 — 凭证加密存储 + 审计事件通道

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-006 |
| **Feature** | SDK 凭证加密（AES-256-GCM）+ 安全审计事件发布通道 |
| **对齐规范** | Security Spec v1.1 §2.2, §6.2; Audit Spec v1.1 §2.1 |
| **优先级** | **P0** |
| **版本** | v1.2 |
| **日期** | 2026-07-15 |

---

## 1. 背景

Phase 1 完成了脱敏和 header 传递等基础安全增强。Security Spec §2.2 的 `MUST: 所有凭证必须使用 AES-256-GCM 加密后存储` 和 §6.2 的 `MUST: 安全事件写入审计日志` 尚未落地。

当前状态：
- `AuthConfig.token` / `AuthConfig.password` 以明文 `str` 存储在 dataclass 中（已加 `repr=False` 防御）
- AUTH_EXPIRED 审计事件仅通过 `logger.critical` 本地输出，未进入平台审计通道
- 无统一的凭证加密/解密基础设施

## 2. 用户故事

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | `ConnectorConfig` 的 token/password 以 AES-256-GCM 密文存储，运行时按需解密 | 安全 |
| US-02 | `CredentialEncryptor` 提供 `encrypt(plaintext) -> ciphertext` / `decrypt(ciphertext) -> plaintext` 接口，密钥通过 `key_source` 注入（默认环境变量） | 基础设施 |
| US-03 | `EncryptedAuthConfig(AuthConfig)` 子类化 `AuthConfig`，`__repr__`/序列化时只暴露密文，运行时 `token` 属性透明解密 | 安全 |
| US-04 | earp-sdk-core 提供 `publish_audit_event(event: AuditEvent)` 函数，发布符合 Audit Spec v1.1 §2.1 12 字段的标准化审计事件 | 审计 |
| US-05 | `_on_error` 中 AUTH_EXPIRED 等安全事件通过 `publish_audit_event` 发布（保留本地 `logger.critical` 作为 fallback） | 审计 |

## 3. 验收条件

| ID | 描述 | 影响 SDK |
|:--:|:------|:---------|
| AC-01 | `CredentialEncryptor.encrypt("secret")` 返回 base64 密文；两次 `encrypt` 同一明文产生不同密文（nonce 唯一性）；`decrypt(cipher)` 还原原文 | Core |
| AC-02 | `EncryptedAuthConfig` 的 `token`/`password` 在 `__repr__` 中显示为 `"<encrypted>"`，`__getstate__` 返回密文（pickle 安全），属性访问 `.token` 返回明文 | Core |
| AC-03 | `CredentialEncryptor` 密钥通过 `key_source` 参数注入（默认 `EnvVarSource("EARP_CREDENTIAL_KEY")`），base64 解码后为 32 字节；缺失时抛 `CredentialKeyError` | Core |
| AC-04 | `publish_audit_event(event)` 将事件序列化为 JSON，写入 logger `"earp.audit"`（INFO 级别）。包含全部 11 个 Audit Spec §2.1 字段：`log_id`(UUID4 自动), `timestamp`(ISO8601 UTC 自动), `source`, `event_type`, `tenant_id`, `user_id`, `execution_id`, `subject`, `action`, `result`, `detail` | Core |
| AC-05 | AUTH_EXPIRED 发生时，`publish_audit_event` 被调用（同时保留本地 `logger.critical` fallback），event 的 `tenant_id`/`user_id`/`action` 正确传递 | Connector |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| earp-sdk-core (Phase 1 安全增强) | ✅ |
| earp-sdk-connector | ✅ |
| Security Spec v1.1 | ✅ |
| Audit Spec v1.1 | ✅ |

## 5. 不做（Phase 3+ 预留）

- Vault/外部 KMS 集成（Security Spec §2.2 SHOULD，留 Phase 2.1）——通过 `KeySource` 抽象预留扩展点
- EventBus 集成——Phase 2 以 `logger "earp.audit"` JSON 输出，真正的 EventBus 订阅需 Runtime 就绪
- 加密密钥轮换自动化
- Audit Spec 的哈希链/不可变存储（服务端基础设施，非 SDK 职责）

## 6. 接口预览

### 6.1 CredentialEncryptor + 密文格式规范

```python
from earp_sdk_core import CredentialEncryptor

# 默认从环境变量读取密钥
encryptor = CredentialEncryptor()

# Phase 2.1 扩展: key_source 参数（不改变现有调用方）
# encryptor = CredentialEncryptor(key_source=VaultSource("secret/earp/credential-key"))

cipher = encryptor.encrypt("my-api-key")
plain = encryptor.decrypt(cipher)
assert plain == "my-api-key"

# Nonce 唯一性
assert encryptor.encrypt("same") != encryptor.encrypt("same")
```

**密文格式（AES-256-GCM）：**
```
ciphertext = base64(nonce[12 bytes] + encrypted_data[N bytes] + tag[16 bytes])

- nonce: secrets.token_bytes(12)，每次 encrypt() 生成全新随机 nonce
- encrypted_data: AES-256-GCM 加密结果，长度等于明文长度
- tag: GCM 认证标签，16 字节
- 密钥: 32 字节，从 key_source 获取（默认 EARP_CREDENTIAL_KEY 环境变量，base64 或 hex 编码）

解密时从 base64 解码后提取: nonce = raw[:12], tag = raw[-16:], ciphertext = raw[12:-16]
```

### 6.2 EncryptedAuthConfig（AuthConfig 子类）

```python
from earp_sdk_core import EncryptedAuthConfig, AuthConfig

# 创建加密版本（子类化 AuthConfig，类型兼容）
encrypted_auth = EncryptedAuthConfig.from_plaintext(
    AuthConfig(type="bearer", token="sk-xxx", password="pw"),
    encryptor,
)

# 存储态：密文
isinstance(encrypted_auth, AuthConfig)  # → True（子类）
repr(encrypted_auth)
# → EncryptedAuthConfig(type='bearer', token='<encrypted>', username='', password='<encrypted>')

str(encrypted_auth.token)    # → base64 密文字符串
encrypted_auth.token          # → "sk-xxx"（透明解密）
encrypted_auth.password       # → "pw"（透明解密）
encrypted_auth.type           # → "bearer"（明文，不加密）

# 序列化安全：pickle 保持密文
import pickle
data = pickle.dumps(encrypted_auth)
restored = pickle.loads(data)
restored.token  # → "sk-xxx"（解密），但 pickle 二进制中包含的是密文

# ConnectorConfig 兼容（类型注解仍为 AuthConfig）
config = ConnectorConfig(base_url="http://api", auth=encrypted_auth)
connector.config = config  # RESTConnector 直接用 config.auth.token
```

### 6.3 AuditEvent + publish_audit_event

```python
from earp_sdk_core import AuditEvent, publish_audit_event

event = AuditEvent(
    source="security",
    event_type="AUTH_EXPIRED",
    tenant_id="tenant-1",           # MUST (Audit Spec §2.1)
    user_id="",                     # MUST，系统事件可为空字符串
    action="connector_auth",        # MUST
    result="failure",
    execution_id=None,              # SHOULD
    subject="connector:my-conn",    # SHOULD
    detail={"connector_id": "my-conn", "reason": "token expired"},
)
publish_audit_event(event)
# → 输出到 logger "earp.audit"（INFO 级别），JSON 格式：
# {
#   "log_id": "uuid4...",
#   "timestamp": "2026-07-15T10:30:00Z",
#   "source": "security",
#   "event_type": "AUTH_EXPIRED",
#   "tenant_id": "tenant-1",
#   "user_id": "",
#   "execution_id": null,
#   "subject": "connector:my-conn",
#   "action": "connector_auth",
#   "result": "failure",
#   "detail": {"connector_id": "my-conn", "reason": "token expired"}
# }
```

## 7. 用户故事预期行为

### US-01/02：凭证加密存储

```
预期行为：
  - AuthConfig 创建后，EncryptedAuthConfig.from_plaintext(auth, encryptor) 得到密文版本
  - 密文 base64 每次加密不同（nonce 唯一性：secrets.token_bytes(12)）
  - encrypt() 和 decrypt() 互为逆操作
  - 错误密钥解密时抛 ValueError（GCM 认证失败）
  - EncryptedAuthConfig 是 AuthConfig 子类，connector.config.auth 类型兼容
```

### US-03：透明解密

```
预期行为：
  - token/password 属性访问返回明文（透明解密）
  - __repr__ 不暴露明文 token/password（显示 "<encrypted>"）
  - pickle.dumps 时 __getstate__ 返回密文，二进制中不含明文
  - type/username 等非敏感字段保持明文，不加密
```

### US-04/05：审计事件通道

```
预期行为：
  - publish_audit_event(event) 自动填充 log_id(UUID4) + timestamp(ISO8601 UTC)
  - 输出到 logger.getLogger("earp.audit").log(INFO, json_str)
  - AUTH_EXPIRED 时同时调用 publish_audit_event + logger.critical（fallback）
  - 测试环境通过 caplog("earp.audit") 验证事件内容
```

## 8. 验收总结表

| # | 检查项 | 状态 |
|:-:|--------|:----:|
| 1 | US 完整 | ✅ 5 个 US |
| 2 | AC 可测试 | ✅ 5 条（含 AC-01 nonce 唯一性、AC-04 12 字段、AC-02 序列化安全） |
| 3 | 依赖完整 | ✅ |
| 4 | P0 合理 | ✅ |

## 9. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | AuditEvent 缺 tenant_id/user_id/action 三个 MUST 字段 | AC-04 明确 11 个 Audit Spec §2.1 字段；§6.3 示例补全；log_id/timestamp 自动生成 |
| P0-2 | AES-256-GCM nonce 管理未定义 | §6.1 补充完整密文格式规范：nonce=token_bytes(12), prepend, tag 16 字节；AC-01 新增 nonce 唯一性验证 |
| P1-1 | EncryptedAuthConfig 与 AuthConfig 类型不兼容 | §6.2 明确子类化 AuthConfig，`isinstance(auth, AuthConfig)` → True |
| P1-2 | publish_audit_event 输出目标未定义 | AC-04 明确 logger "earp.audit" + JSON + INFO 级别 |
| P1-3 | 密钥源缺乏扩展性预留 | §6.1 新增 `key_source` 参数（默认 EnvVarSource("EARP_CREDENTIAL_KEY")），Phase 2.1 不 breaking |
| P2-1 | 缺少预期行为章节 | §7 新增 4 组 US 端到端预期行为 |
| P2-2 | EncryptedAuthConfig 序列化安全 | AC-02 新增 `__getstate__` 返回密文；§7 US-03 明确 pickle 安全性 |
| — | "12 个字段" 计数错误（实际 11 个） | AC-04 和 §6.3 改为 11；§6.3 示例补齐 execution_id/subject |
