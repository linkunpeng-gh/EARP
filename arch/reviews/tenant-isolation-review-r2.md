# 多租户设计文档二次评审报告

## Multi-Tenant Isolation Spec v1.1 + PRD-2026-009 v1.1

| 字段 | 值 |
|------|-----|
| **Spec 版本** | v1.1 |
| **PRD 版本** | v1.1 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **上一轮** | [tenant-isolation-review.md](../reviews/tenant-isolation-review.md) — 8 个问题（2 P0 / 4 P1 / 2 P2） |
| **本轮** | P0: 0 / P1: 1 / P2: 1 → **共 2 个** |

---

## 总体评价

**上一轮的 8 个问题中 7 个已修复，1 个 P1 仍有微小歧义。** 可以进入 Gate 0。

Tenant Spec v1.1 更新了章节顺序（v1.1 重组的逻辑更流畅：概述→租户模型→请求→安全→数据→资源→审计→SDK），PRD v1.1 的 AC-03/AC-04/AC-05 均已修正。除 1 个 P1 和 1 个 P2 外无其他问题。

---

## 上一轮问题修复确认

### P0-1：HKDF salt 密码学语义 ✅

**Tenant Spec §4.2.1 修复**：
```
AES-256-GCM 密钥 = HKDF-SHA256(
    IKM   = EARP_CREDENTIAL_KEY（环境变量，32 字节 master key）,
    salt  = tenant_id（UTF-8 编码）,
    info  = b"earp-credential-encryption-v1"
)

当 tenant_id 为空字符串 "" 时，salt 为空字节串 b""（Phase 2 向后兼容模式）。
不同 tenant_id 产生独立的派生密钥，跨租户密文不可解密。
```

- ✅ 明确 `HKDF-SHA256` 算法
- ✅ IKM 大小明确 32 字节
- ✅ `info` 使用 `b"..."` 字节串（正确）
- ✅ salt empty case 已定义
- ✅ 跨租户不可解密的属性已声明

---

### P0-2：tenant_id="" 密钥等价性 ✅

**PRD AC-03 修复**：
```
CredentialEncryptor() 无参构造保持向后兼容
(tenant_id="" 时 salt 为空字节串，使用 HKDF(salt=b"") 派生密钥)。
此模式为过渡性——Phase 3 在 TenantContext 就绪后废弃无 tenant_id 的构造。
Phase 2+ 期间所有新增密文应使用 per-tenant encryptor。
```

- ✅ 明确过渡模式
- ✅ 标注 Phase 3 废弃
- ✅ 建议新密文用 per-tenant encryptor

---

### P1-1：X-EARP-Tenant-Id 歧义 ✅

**Tenant Spec §3.2**：
```
MUST: Connector 的请求中携带 X-EARP-Tenant-Id header（当 connector.tenant_id 非空时）
      系统级 connector（如内部基础设施连接）tenant_id 可为空，不注入此 header
```

**PRD AC-04**：
```
系统级 connector（tenant_id=""）不注入此 header
```

两边一致。✅

---

### P1-2：create_session breaking change ✅

**PRD AC-05**：
```
RuntimeClient.create_session() 的 tenant_id 参数默认值改为 Sentinel
(_UNSET = object())，调用时未传入则运行时抛 ValueError("tenant_id is required")。
不 breaking 现有调用方的编译期
```

Sentinel 模式是一个务实的折中——不改变函数签名类型，调用方编译期不受影响，运行时在首次缺失时抛明确的异常。✅

---

### P1-3：系统事件 tenant_id SHOULD ✅

**Tenant Spec §3.2**：
```
SHOULD: 系统级事件携带 connector.tenant_id——当 connector/plugin 绑定到特定租户时
        事件携带其 tenant_id；全局基础设施事件（如共享 PluginManager 加载）可用 tenant_id=""
```

与现有实现对齐（AUTH_EXPIRED 已修复为 `self.tenant_id`，Plugin 和 Guard 审计仍为 `""`）。✅

---

### P1-4：密文格式版本号 ✅

**Tenant Spec §4.2.2**：
```
base64(version[1 byte] + nonce[12 bytes] + ciphertext[N bytes] + tag[16 bytes])

version = 0x01 → 当前格式（v1，不带 tenant 元信息）
Phase 3+ 可定义 0x02 → 含 tenant 元信息的扩展格式
```

⚠️ 见本轮 **P1-1**：Spec 与 PRD 在 v1.1 密文格式新增上有一个微小不一致。

---

### P2-1：章节顺序 ✅

v1.1 重组为：概述(§1)→租户模型(§2)→请求隔离(§3)→安全隔离(§4)→数据隔离(§5)→资源隔离(§6)→审计(§7)→SDK(§8)。逻辑链更顺：概念 → 标识传播 → 安全执行 → 数据落地 → 资源约束 → 审计追责。✅

---

### P2-2：BaseConnector.tenant_id 背景说明 ✅

PRD §4 依赖表已标注 `BaseConnector.tenant_id ✅`（实际 Phase 4 #2 修复已就绪）。✅

---

## 本轮发现的新问题（2 个）

### P1-1：Tenant Spec §4.2.2 与 PRD §6.1 在密文格式上不一致

**涉及段落**：

| | 描述 |
|:--|:-----|
| Tenant Spec §4.2.2 | `base64(version[1] + nonce[12] + ciphertext[N] + tag[16])`, version=0x01 |
| PRD §6.1 | `enc_legacy = CredentialEncryptor(); enc_legacy.encrypt("old-data")` — 无 version byte |

**问题**：Spec v1.1 新增了 version byte（0x01），但 PRD v1.1 没有与之对应的 AC 或实现说明。Phase 2 的实现（`credential.py:45`）当前格式是 `base64(nonce[12] + ciphertext + tag[16])` — **没有 version byte**。

这意味着：
- 如果 Spec 要求 version byte，Phase 2 的实现需要修改密文格式（breaking change——所有已加密的密文无法迁移）
- 如果 Phase 2 不加 version byte，Spec 的 4.2.2 应该注明"Phase 3+ 引入"

**建议**：在 Spec §4.2.2 中加注：
```
Phase 2 密文格式为 base64(nonce[12] + ciphertext + tag[16])，不含 version byte。
version byte (0x01) 从 Phase 3+ 引入，与当前格式向后兼容（密文长度不同，解密时自动识别）。
```

或在 PRD §6.1 中补充 AC：`Phase 2 密文格式不变（不含 version byte）`。

---

### P2-1：PRD §6.1 示例代码与 AC-03 不一致

**PRD §6.1 line 83-84**:
```python
# 向后兼容：无 tenant_id 时使用原始密钥
enc_legacy = CredentialEncryptor()  # tenant_id="" → HKDF 跳过
```

**PRD AC-03**:
```
tenant_id="" 时 salt 为空字节串，使用 HKDF(salt=b"") 派生密钥
```

**歧义**：AC-03 说 `HKDF(salt=b"")` 派生密钥，但示例代码注释说 "HKDF 跳过"。哪个是实际行为？

- `HKDF(IKM, salt=b"", info=...)` 会执行一次完整的 HKDF 操作，产生一个确定的派生密钥（与使用不同的 salt 的派生密钥不同）
- "HKDF 跳过" 意味着直接使用 `IKM` 作为密钥

这两种行为都**安全**——关键在于一致。`HKDF(salt=b"")` 更优（因为仍然是派生密钥，不是原始 master key），但需要明确是哪种。

**建议**：统一为 AC-03 的定义（`HKDF(salt=b"")`），修改代码注释：
```python
enc_legacy = CredentialEncryptor()  # tenant_id="" → HKDF(salt=b"")
```

---

## 变更摘要

| 级别 | 上一轮 | 已修复 | 本轮新增 | 未修复 |
|:----:|:------:|:------:|:--------:|:------:|
| P0 | 2 | 2 | 0 | **0** |
| P1 | 4 | 4 | 1 | **1** |
| P2 | 2 | 2 | 1 | **1** |

### v1.1 主要变更

| 变更 | Spec | PRD |
|:-----|:----:|:----:|
| 章节顺序重组 | ✅ | — |
| HKDF 细节补充（算法/SHA256/size/salt） | ✅ | — |
| 密文格式 version byte 预留 | ✅ | ⚠️ 与 Phase 2 实现不一致 (P1-1) |
| 系统事件 SHOULD 条件明确 | ✅ | — |
| tenant_id="" 过渡模式标注 | — | ✅ |
| X-EARP-Tenant-Id 非空条件 | ✅ | ✅ |
| create_session Sentinel 模式 | — | ✅ |

---

## 评审总结

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| P0 | **0** | — |
| P1 | **1** | Spec §4.2.2 新增的 version byte 与 Phase 2 当前实现（无 version byte）不一致 |
| P2 | **1** | PRD §6.1 代码注释说"HKDF 跳过"与 AC-03 `HKDF(salt=b"")` 冲突 |

### 结论

**可以进入 Gate 0。** 2 个新问题均为细节一致性问题，可在 L3 设计或实现阶段修正。
