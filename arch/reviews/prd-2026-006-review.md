# PRD-2026-006 评审报告

## Security Phase 2 — 凭证加密存储 + 审计事件通道

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-006 |
| **Feature** | SDK 凭证加密（AES-256-GCM）+ 安全审计事件发布通道 |
| **对齐规范** | Security Spec v1.1 §2.2, §6.2; Audit Spec v1.1 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **状态** | ⚠️ 2 个 P0 需修复后再进入 Gate 0 |

---

## 总体评价

**方向正确，5 个 US 精准覆盖 Phase 1 遗留的两个最大缺口（凭证加密 + 审计通道）。** 接口设计清晰——`CredentialEncryptor` / `EncryptedAuthConfig` / `AuditEvent` 三层抽象合理，`publish_audit_event` 保留 `logger.critical` fallback 的降级策略务实。§5 OOS 明确排除了 Vault/KMS、EventBus、密钥轮换等 Phase 3 事项。

但 **2 个 P0 需要修复**：`AuditEvent` 字段与 Audit Spec v1.1 不匹配（缺少 3 个 MUST 字段），AES-256-GCM 的 nonce 管理策略未定义。

---

## P0 — 必须修复（2 个）

### P0-1：US-04 `AuditEvent` 字段与 Audit Spec v1.1 §2.1 不匹配

**涉及段落**：§3 AC-04, §6.3

Audit Spec v1.1 §2.1 定义了 12 个审计日志统一字段，PRD §6.3 的 `AuditEvent` 示例仅覆盖其中 4 个：

| Audit Spec 字段 | 要求 | PRD 示例 | 状态 |
|:----------------|:----:|:---------|:----:|
| `log_id` | MUST | ❌ 缺失 | 缺 |
| `timestamp` | MUST | ❌ 缺失 | 缺 |
| `source` | MUST | ✅ `"security"` | 有 |
| `event_type` | MUST | ✅ `"AUTH_EXPIRED"` | 有 |
| `tenant_id` | MUST | ❌ 缺失 | **缺** |
| `user_id` | MUST | ❌ 缺失 | **缺** |
| `execution_id` | SHOULD | ❌ 缺失 | 缺 |
| `subject` | SHOULD | ❌ 缺失 | 缺 |
| `action` | MUST | ❌ 缺失 | **缺** |
| `result` | MUST | ✅ `"failure"` | 有 |
| `detail` | SHOULD | ✅ | 有 |

**核心问题**：`tenant_id`、`user_id`、`action` 是 Audit Spec 的 MUST 字段，PRD 完全未涉及。AUTH_EXPIRED 场景发生在 connector 连接时——此时可能没有 `user_id`（系统级认证失败），但 `tenant_id` 是必要的（标识哪个租户的 connector 认证失败）。

**建议方案**：

```python
event = AuditEvent(
    source="security",
    event_type="AUTH_EXPIRED",
    tenant_id=connector.tenant_id,      # 新增 MUST
    user_id="",                          # 系统事件可为空字符串
    action="connector_auth",             # 新增 MUST
    result="failure",
    detail={"connector_id": "my-conn", "reason": "token expired"},
)
```

`log_id` 和 `timestamp` 可在 `publish_audit_event()` 内部自动生成（`uuid4()` + `datetime.now(timezone.utc)`），但必须在 AC-04 中明确说明。

---

### P0-2：US-02 `CredentialEncryptor` 未定义 AES-256-GCM 的 nonce/IV 管理

**涉及段落**：§3 AC-01, §6.1

Security Spec §2.2 明确要求 AES-256-**GCM**。GCM 模式的核心安全约束是：**同一密钥下的 12 字节 nonce 绝对不能重复**——否则攻击者可恢复认证密钥 `H = AES_K(0)` 并伪造任意密文。这是 GCM 的已知安全边界，不是理论攻击。

PRD §6.1 只展示了调用接口，但未定义：

1. **Nonce 生成策略**：每次加密用 `secrets.token_bytes(12)`（随机 nonce）还是计数器？随机 nonce 在大量加密时存在碰撞风险（约 2^48 次加密后碰撞概率显著），但在 SDK 场景（凭证数 < 1000）安全。需要明确。
2. **Nonce 存储方式**：nonce 与密文一起存储（prepend to ciphertext）还是分离存储？prepend 是 GCM 的标准做法，推荐。
3. **密文格式**：`base64(nonce[12] + ciphertext + tag[16])` 还是其他编码？

**建议方案**：在 PRD 中明确密文格式规范——

```
密文格式：base64(nonce[12 bytes] + ciphertext[N bytes] + tag[16 bytes])
- nonce: secrets.token_bytes(12)，每次 encrypt() 调用生成全新随机 nonce
- ciphertext: AES-256-GCM 加密结果，长度与明文相同
- tag: GCM 认证标签，16 字节

解密时从 base64 解码后提取前 12 字节作为 nonce，最后 16 字节作为 tag，中间部分为 ciphertext。

密钥: 32 字节，从环境变量 EARP_CREDENTIAL_KEY 的 base64 解码或 hex 解码获得。
```

AC-01 应补充验证 nonce 唯一性：
```
AC-01: encrypt("s1") 和 encrypt("s1") 两次调用产生不同密文（nonce 不同）
```

---

## P1 — 建议修改（3 个）

### P1-1：`EncryptedAuthConfig` 与 `ConnectorConfig.auth: AuthConfig` 类型不兼容

**涉及段落**：§6.2

当前 Phase 1 代码中 `ConnectorConfig.auth` 的类型注解是 `AuthConfig`：

```python
@dataclass
class ConnectorConfig:
    auth: AuthConfig = field(default_factory=AuthConfig)
```

PRD §6.2 将 `EncryptedAuthConfig` 赋给 `config.auth`：

```python
connector.config.auth = EncryptedAuthConfig.from_plaintext(AuthConfig(...), encryptor)
```

这会导致类型不匹配。`RESTConnector._ensure_auth_headers()` 等代码访问 `config.auth.token`、`config.auth.type`、`config.auth.username`、`config.auth.password`——`EncryptedAuthConfig` 需要透明代理所有四个字段的读写。

**建议方案**：

- **方案 A（推荐）**：`EncryptedAuthConfig(AuthConfig)` 子类化——继承 `type`、`username` 等字段，仅覆盖 `token`/`password` 的存储和访问行为。调用方无需修改。
- **方案 B**：组合模式——`EncryptedAuthConfig` 通过 `__getattr__` 代理到内部 `AuthConfig`。

在 PRD 中明确选用哪种方案。

---

### P1-2：`publish_audit_event()` 输出目标未定义

**涉及段落**：§3 AC-04

AC-04 说"产生标准化事件"，但未说明发布到**哪里**。Phase 1 的 `logger.critical` fallback 写本地日志，Phase 2 的审计事件应该有一个明确的输出目标，否则：
- 实现时目标不明确，可能简单 print 了事
- AC 验证无法判断"产生"是否成功

PRD §5 OOS 说"真正的 EventBus 订阅需 Runtime 就绪"——这是合理的分期。但 Phase 2 仍需定义一个明确的本地输出目标。

**建议方案**：

明确 Phase 2 使用结构化 JSON 输出到独立 audit logger：

```python
audit_logger = logging.getLogger("earp.audit")
# publish_audit_event 将事件序列化为 JSON，调用 audit_logger.log(CRITICAL, json_str)
```

这样做的好处：
- 本地开发可直接通过 `caplog` 验证
- 生产环境被 Fluentd/Logstash 直接消费
- 后续升级为 EventBus 发布时接口不变（`publish_audit_event` 内部切换实现）

在 AC-04 中补充：
```
AC-04: publish_audit_event(event) 产生 JSON 格式事件，写入 logger "earp.audit"（CRITICAL 级别）。
       包含：log_id(UUID4), timestamp(ISO8601 UTC), source, event_type, tenant_id, user_id, action, result, detail
```

---

### P1-3：`CredentialEncryptor` 密钥源缺乏扩展性预留

**涉及段落**：§5, §6.1

Security Spec §2.2 SHOULD 支持 Vault 等外部 KMS。PRD §5 明确"Vault 留 Phase 2.1"——分期合理。但当前设计 `CredentialEncryptor()` 无参数直接读 `EARP_CREDENTIAL_KEY`，后续扩展为多密钥源时接口需要变更，导致 Phase 2.1 成为 breaking change。

**建议方案**：

当前接口可以保留，但在 PRD 中加一句扩展性说明：

```python
# Phase 2: 仅环境变量
encryptor = CredentialEncryptor()  # → EARP_CREDENTIAL_KEY

# Phase 2.1 扩展（不改变现有调用方）:
encryptor = CredentialEncryptor(key_source=EnvVarSource("EARP_CREDENTIAL_KEY"))
encryptor = CredentialEncryptor(key_source=VaultSource("secret/earp/credential-key"))
```

实现时在 `CredentialEncryptor.__init__` 中预留 `key_source` 参数（默认值 `None` 走环境变量），避免后续 breaking change。

---

## P2 — 优化建议（2 个）

### P2-1：缺少用户故事预期行为详细章节

**涉及段落**：§6

PRD-2026-005 v1.1 §6 有详细的"用户故事预期行为"——每个 US 对应一段代码风格的端到端行为描述，方便开发者和 reviewer 理解。PRD-2026-006 的 §6 只有接口预览（API 签名），缺少这种端到端的行为描述。

**建议**：补充类似 Phase 1 PRD 的 §6 格式：

```
### US-01：凭证加密存储

预期行为：
  - AuthConfig 创建后，调用 EncryptedAuthConfig.from_plaintext() 得到密文版本
  - 密文 base64 每次加密不同（nonce 唯一性）
  - __repr__ 不暴露明文 token/password
  - 属性访问 .token / .password 透明解密，返回明文

### US-02：CredentialEncryptor
  ...
```

---

### P2-2：`EncryptedAuthConfig` 序列化安全未覆盖

**涉及段落**：§6.2

如果 `ConnectorConfig` 被 `pickle` 或 `json.dumps`（例如用于缓存、调试或跨进程传递），`EncryptedAuthConfig` 的属性访问可能触发解密，导致明文泄露到序列化输出。

**建议**：在 AC-02 中增加一条：

```
AC-02 补充: pickle.dumps(config.auth) 时 token/password 字段保持密文
```

或明确 `__getstate__` / `__reduce__` 行为——序列化时跳过 `token`/`password` 的 getter，直接返回密文。

---

## 对齐检查表

### 与 Security Spec v1.1 的对齐

| Security Spec 要求 | PRD 对应 | 状态 |
|:-------------------|:---------|:----:|
| §2.2 MUST: AES-256-GCM 加密存储 | US-01, US-02, AC-01 | ⚠️ P0-2 nonce 未定义 |
| §2.2 SHOULD: Vault 集成 | §5 OOS → Phase 2.1 | ✅ 合理延期 |
| §2.2 MUST: API Key 通过环境变量注入 | AC-03 `EARP_CREDENTIAL_KEY` | ✅ |
| §2.2 MUST: token 在日志中脱敏 | Phase 1 已实现 | ✅ （不涉及） |
| §6.2 MUST: 认证失败写入审计 | US-04, US-05, AC-04, AC-05 | ⚠️ P0-1 字段不匹配 |

### 与 Audit Spec v1.1 的对齐

| Audit Spec 要求 | PRD 对应 | 状态 |
|:----------------|:---------|:----:|
| §2.1 MUST: 12 个统一字段 | AC-04 定义 5 个字段 | ❌ P0-1 缺 3 个 MUST |
| §2.1 log_id 全局唯一 | 未定义 | ⚠️ 应在 AC-04 中说明自动生成 |
| §2.1 tenant_id (MUST) | 缺失 | ❌ |
| §2.1 user_id (MUST) | 缺失 | ❌ |
| §2.1 action (MUST) | 缺失 | ❌ |

### 与 Phase 1 实现的衔接

| Phase 1 实现 | Phase 2 变更 | 兼容性 |
|:------------|:-----------|:------:|
| `AuthConfig` 明文 dataclass | `EncryptedAuthConfig` 包装 | ⚠️ P1-1 类型兼容 |
| `_on_error` 中 `makeRecord` + `logger.handle` | 加 `publish_audit_event` + 保留 fallback | ✅ AC-05 |
| `mask_sensitive` | 不变 | ✅ |
| `ConnectorConfig.auth: AuthConfig` | 值改为 `EncryptedAuthConfig` | ⚠️ P1-1 |

---

## 评审总结

### 数据统计

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0（必须修复） | 2 | AuditEvent 缺 tenant_id/user_id/action；GCM nonce 管理未定义 |
| ⚠️ P1（建议修改） | 3 | EncryptedAuthConfig 类型兼容；publish 目标未定义；密钥源扩展性 |
| 💡 P2（优化建议） | 2 | 缺预期行为章节；序列化安全 |

### P0 影响分析

| # | 问题 | 影响 | 修复复杂度 |
|:-:|:-----|:-----|:----------:|
| P0-1 | AuditEvent 字段不匹配 Audit Spec | 审计日志不符合平台规范，后续接入审计系统需**重新设计数据结构** | 低（补 3 个字段 + AC 说明） |
| P0-2 | GCM nonce 未定义 | 实现者可能用固定 IV 或错误方案，导致**加密可被破解** | 低（PRD 中补充格式规范即可） |

### 好的方面

- **US 范围精准** — 5 个 US 精准覆盖 Phase 1 的两个最大遗留缺口（凭证加密 + 审计通道），没有贪多
- **§5 OOS 明确** — Vault/KMS、EventBus、密钥轮换合理延期到 Phase 3+
- **§6 接口预览实用** — `CredentialEncryptor`、`EncryptedAuthConfig`、`AuditEvent` 三层抽象清晰
- **降级策略务实** — `publish_audit_event` 保留 `logger.critical` fallback，不因审计通道故障丢失事件
- **AC 可测试** — 5 条 AC 均可在单元测试中验证，不依赖外部服务
- **依赖完整** — 对齐 Security Spec v1.1 + Audit Spec v1.1

### 修复优先级建议

1. **P0-1** + **P0-2** 先修——都是 PRD 层面的补充，不涉及架构变更，预计 30 分钟完成
2. **P1-1** 在实现前澄清——影响 `EncryptedAuthConfig` 的类设计
3. **P1-2** 在 AC-04 中补充输出目标
4. **P2** 可在实现过程中逐步完善
