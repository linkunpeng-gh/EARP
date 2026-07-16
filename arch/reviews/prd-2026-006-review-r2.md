# PRD-2026-006 二次评审报告

## Security Phase 2 — 凭证加密存储 + 审计事件通道（修复验证）

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-006 |
| **版本** | v1.1 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **上一轮** | [prd-2026-006-review.md](../reviews/prd-2026-006-review.md) — 7 个问题（2 P0 / 3 P1 / 2 P2） |
| **本轮** | P0: 0 / P1: 1 / P2: 1 → **共 2 个** |

---

## 总体评价

**上一轮的 7 个问题全部修复。PRD v1.1 质量高，可以进入 Gate 0。**

上一轮的核心缺陷——AuditEvent 字段不匹配 Audit Spec（P0-1）和 GCM nonce 管理未定义（P0-2）——均已精准修复。新增的 §6.1 密文格式规范、§7 用户故事预期行为、§9 评审修复记录三个章节显著提升了 PRD 的完备性。

---

## 上一轮 P0 修复确认（2/2 ✅）

### P0-1：AuditEvent 字段与 Audit Spec v1.1 §2.1 对齐 ✅

**修复内容**：
- AC-04 明确"包含全部 12 个 Audit Spec §2.1 字段"
- §6.3 示例补全 `tenant_id`、`user_id`、`action`、`subject`、`execution_id`
- `log_id` (UUID4) 和 `timestamp` (ISO8601 UTC) 标记为自动生成

**核对 Audit Spec §2.1 字段覆盖**：

| Audit Spec 字段 | v1.0 状态 | v1.1 状态 |
|:----------------|:---------|:---------:|
| log_id | ❌ | ✅ 自动 UUID4 |
| timestamp | ❌ | ✅ 自动 ISO8601 UTC |
| source | ✅ | ✅ |
| event_type | ✅ | ✅ |
| tenant_id | ❌ | ✅ |
| user_id | ❌ | ✅ |
| execution_id | ❌ | ✅ |
| subject | ❌ | ✅ |
| action | ❌ | ✅ |
| result | ✅ | ✅ |
| detail | ✅ | ✅ |

**11/11 字段全覆盖。** ✅

> 注：Audit Spec §2.1 原文列出 11 个字段（非 12——第 12 个字段不存在）。PRD 说"12 个"但实际覆盖了全部 11 个 MUST+SHOULD 字段，不影响正确性。

**⚠️ 小问题**：PRD AC-04 和 §6.3 多处提到"12 个 Audit Spec §2.1 字段"，但 Audit Spec §2.1 实际定义了 **11 个字段**（log_id, timestamp, source, event_type, tenant_id, user_id, execution_id, subject, action, result, detail）。建议改为"11 个"避免与规范不对齐。见本轮 P2-1。

---

### P0-2：AES-256-GCM nonce 管理 ✅

**修复内容**：
- §6.1 新增完整的**密文格式规范**：
  - `base64(nonce[12] + encrypted_data[N] + tag[16])`
  - nonce: `secrets.token_bytes(12)`，每次加密全新随机
  - tag: 16 字节 GCM 认证标签
  - 密钥: 32 字节，默认从 `EARP_CREDENTIAL_KEY` 环境变量 base64/hex 解码
- AC-01 新增 **nonce 唯一性验证**：两次 `encrypt` 同一明文产生不同密文

**安全分析**：随机 nonce（12 bytes = 96 bits）在 GCM 下是标准的随机 nonce 方案（NIST SP 800-38D §8.2.1）。碰撞概率：~2^(-48) 在 2^24 次加密后仍然 < 2^(-32)。SDK 场景（< 1000 次加密）极其安全。正确。✅

---

## 上一轮 P1 修复确认（3/3 ✅）

### P1-1：EncryptedAuthConfig 类型兼容 ✅

**修复内容**：
- §6.2 标题改为"EncryptedAuthConfig（AuthConfig 子类）"
- 示例明确 `isinstance(encrypted_auth, AuthConfig) → True`
- `ConnectorConfig` 的类型注解 `auth: AuthConfig` 接受子类实例，无需修改

**设计合理**：子类化是最干净的方案——继承 `type`/`username`，覆盖 `token`/`password` 的 getter，`RESTConnector._ensure_auth_headers()` 等现有代码零改动。✅

---

### P1-2：publish_audit_event 输出目标 ✅

**修复内容**：
- AC-04 明确：logger `"earp.audit"`，JSON 格式，INFO 级别
- §6.3 展示了完整的 JSON 输出示例
- §7 US-04/05 说明测试验证方式：`caplog("earp.audit")`

**设计合理**：logger 是本地开发的正确选择——`caplog` 可测试、Fluentd 可采集、Phase 3 升级为 EventBus 时只需修改 `publish_audit_event` 内部实现，接口不变。✅

---

### P1-3：密钥源扩展性 ✅

**修复内容**：
- §6.1 新增 `key_source` 参数（默认 `EnvVarSource("EARP_CREDENTIAL_KEY")`）
- 注释展示 Phase 2.1 扩展：`CredentialEncryptor(key_source=VaultSource("secret/..."))`
- Phase 2 不 breaking

**设计合理**：`key_source` 参数预留了抽象点，Phase 2.1 直接加新的 `KeySource` 实现。✅

---

## 上一轮 P2 修复确认（2/2 ✅）

### P2-1：用户故事预期行为 ✅

**修复内容**：§7 新增 4 组 US 端到端预期行为——凭证加密存储（US-01/02）、透明解密（US-03）、审计事件通道（US-04/05）。格式与 PRD-2026-005 §6 对齐。

---

### P2-2：EncryptedAuthConfig 序列化安全 ✅

**修复内容**：
- AC-02 新增 `__getstate__` 返回密文（pickle 安全）
- §7 US-03 明确 pickle 二进制中不含明文

---

## 本轮发现的新问题（2 个）

### P1-1：AC-04/§6.3 声称"12 个字段"，Audit Spec 实际定义 11 个字段

**涉及段落**：§3 AC-04, §6.3 注释

**Audit Spec §2.1 原文定义了 11 个字段**：

```
log_id, timestamp, source, event_type, tenant_id, user_id,
execution_id, subject, action, result, detail
```

PRD AC-04 和 §6.3 说"12 个"是计数错误。实际覆盖率 11/11（100%），不影响完整性——但数字不一致可能导致后续 review 混淆。

**建议**：将"12 个"改为"全部 11 个 Audit Spec §2.1 字段"。

---

### P2-1：§6.3 AuditEvent 缺少 `execution_id` 和 `subject` 的参数展示

**涉及段落**：§6.3 代码示例

PRD 的 AuditEvent 构造示例未展示 `execution_id` 和 `subject` 参数，虽然它们在 JSON 输出中正确显示为 `null`（SHOULD 字段）。调用方可能不知道这两个参数的存在。

**当前示例**：
```python
event = AuditEvent(
    source="security",
    event_type="AUTH_EXPIRED",
    tenant_id="tenant-1",
    user_id="",
    action="connector_auth",
    result="failure",
    detail={...},
)
```

**建议**：在示例中展示可选参数：
```python
event = AuditEvent(
    ...,
    execution_id=None,   # SHOULD，有 execution 上下文时填充
    subject=None,        # SHOULD，操作对象
)
```

这不影响 AC 验证，纯属文档完整性问题。

---

## 变更摘要

### 修复统计

| 级别 | 上一轮 | 已修复 | 剩余 | 本轮新增 | 当前未修复 |
|:----:|:------:|:------:|:----:|:--------:|:----------:|
| P0 | 2 | 2 | 0 | 0 | **0** |
| P1 | 3 | 3 | 0 | 1 | **1** |
| P2 | 2 | 2 | 0 | 1 | **1** |

---

## 对齐检查表（v1.1 最终状态）

### 与 Security Spec v1.1

| 要求 | 覆盖 | 状态 |
|:-----|:---:|:----:|
| §2.2 MUST: AES-256-GCM 加密 | US-01, US-02, AC-01, §6.1 密文格式 | ✅ |
| §2.2 SHOULD: Vault 集成 | §5 OOS + key_source 扩展点 | ✅ |
| §2.2 MUST: API Key 环境变量注入 | AC-03 EnvVarSource("EARP_CREDENTIAL_KEY") | ✅ |
| §6.2 MUST: 认证失败写入审计 | US-04, US-05, AC-04, AC-05 | ✅ |

### 与 Audit Spec v1.1 §2.1

| 字段 | 覆盖 | 状态 |
|:-----|:---:|:----:|
| log_id (MUST) | AC-04 UUID4 自动生成 | ✅ |
| timestamp (MUST) | AC-04 ISO8601 UTC 自动生成 | ✅ |
| source (MUST) | §6.3 source="security" | ✅ |
| event_type (MUST) | §6.3 event_type="AUTH_EXPIRED" | ✅ |
| tenant_id (MUST) | §6.3 tenant_id="tenant-1" | ✅ |
| user_id (MUST) | §6.3 user_id=""（系统事件） | ✅ |
| execution_id (SHOULD) | §6.3 JSON null | ✅ |
| subject (SHOULD) | §6.3 JSON null | ✅ |
| action (MUST) | §6.3 action="connector_auth" | ✅ |
| result (MUST) | §6.3 result="failure" | ✅ |
| detail (SHOULD) | §6.3 detail={...} | ✅ |

---

## 评审总结

### 数据统计

| 类别 | 上一轮 | 已修复 | 本轮新增 | 当前未修复 |
|:----|:------:|:------:|:--------:|:----------:|
| P0 | 2 | 2 | 0 | **0** |
| P1 | 3 | 3 | 1 | **1** |
| P2 | 2 | 2 | 1 | **1** |

### 新增的 v1.1 亮点

- **§6.1 密文格式规范** — 精确定义了 nonce 长度、生成策略、tag 长度、base64 编码，可指导实现
- **§7 用户故事预期行为** — 4 组 US 端到端行为描述，格式对齐 Phase 1 PRD
- **§9 评审修复记录** — 完整追踪 7 个修复项
- **AC-01 nonce 唯一性** — 可测试的安全约束（两次 encrypt 同一明文→不同密文）
- **AC-02 序列化安全** — `__getstate__` 返回密文，pickle 安全

### 结论

**PRD v1.1 质量高，可以进入 Gate 0。** 2 个新问题（P1-1 字段计数、P2-1 缺少可选参数展示）均为低优先级文档问题，不阻塞实现。

**修复建议**（可选，不阻塞 Gate 0）：
1. 将"12 个字段"改为"11 个字段"
2. §6.3 示例中显式展示 `execution_id=None, subject=None` 参数
