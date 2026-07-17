# 多租户设计文档评审报告

## Multi-Tenant Isolation Spec v1.0 + PRD-2026-009 v1.0

| 字段 | 值 |
|------|-----|
| **评审范围** | L2 规范: `multi-tenant-isolation-specification-v1.md` + PRD: `PRD-2026-009-tenant-isolation.md` |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **问题统计** | P0: 2 / P1: 4 / P2: 2 → **共 8 个** |

---

## 总体评价

**规范文档质量高，组织清晰。** 多租户规范的定位（"L2-07-TENANT"）合理——它是 Security Spec 和 Runtime Spec 的交叉规范，专注于多租户这一横切关注点。5 大原则（物理隔离、请求绑定、静默过滤、配额独立、凭证隔离）精准。8 个章节覆盖了租户模型、数据/请求/资源/安全隔离、审计、SDK 集成，与已有 Governance 规范的交叉引用表完整。

PRD 聚焦 Phase 1-2（凭证密钥按 tenant_id 派生 + tenant_id 全链路补齐），范围务实——精准覆盖了 Tenant Spec §6.2 和 §4.2 的当前缺口。

但存在 **2 个 P0**：HKDF salt 参数的安全含义与实现的歧义（规范要求 tenant_id 作为密钥派生输入，但 HKDF 的 salt 参数语义与规范中的"绑定"愿望不匹配），以及 `CredentialEncryptor` 向后兼容模式（`tenant_id=""` 跳过 HKDF）引起的密钥等价性漏洞。

---

## P0 — 必须修复（2 个）

### P0-1：HKDF 的 salt 参数不能实现 "不同租户密文互不可解密" —— spec 正确但实现语义须澄清

**涉及段落**：Tenant Spec §6.2.1, PRD §3 AC-02

**Tenant Spec §6.2.1**:
```
AES-256-GCM 密钥 = HKDF(
    IKM = EARP_CREDENTIAL_KEY (环境变量),
    salt = tenant_id,
    info = "earp-credential-encryption-v1"
)
```

**PRD AC-02**:
```
CredentialEncryptor(tenant_id="t1").decrypt(t2_cipher) 抛 InvalidTag
```

**问题**：HKDF 的 `salt` 是一个抗碰撞参数，不是秘密。salt 值在密码学上是公开的——它包含在密文格式中也无妨。规范用 `salt = tenant_id` 的意图是正确的密钥派生（从单一 master key 派生出 per-tenant 子密钥），但实现上有几个细节需要澄清：

1. **HKDF salt 的角色**：RFC 5869 定义 HKDF 的 salt 参数用于 HMAC 的初始密钥，目的是使相同的 IKM 在不同 salt 下产生不同的输出。`salt=tenant_id` 是正确的——不同 tenant_id 产生不同的派生密钥。

2. **但 HKDF 还有一个 `info` 参数**：规范中 `info = "earp-credential-encryption-v1"` 是正确的——这使得未来版本升级可变更 info 而不影响旧密文。

3. **关键歧义**：HKDF 的 salt 是可选的输入——如果为空，相当于全部零字节。规范说 `tenant_id=""` 时跳过 HKDF（← 这在 PRD AC-03 中定义，不在 Tenant Spec 中），这引入了 **P0-2 的漏洞**。

**结论**：规范本身的 HKDF 设计正确。但需要在 §6.2.1 中补充说明：
```
- salt = tenant_id（UTF-8 编码）。当 tenant_id 为空字符串 "" 时，salt 为空字节串（Phase 2 向后兼容模式）。
- 不同 tenant 的派生密钥互相独立。
```

---

### P0-2：PRD AC-03 向后兼容模式存在密钥等价性漏洞

**涉及段落**：PRD §3 AC-03

```
AC-03: CredentialEncryptor() 无参构造保持向后兼容
       (tenant_id="" 时跳过 HKDF，使用原始密钥)
```

**问题**：AC-03 说 `tenant_id=""` 时**跳过 HKDF**，直接使用原始 `EARP_CREDENTIAL_KEY`。

这意味着：
- `CredentialEncryptor(tenant_id="")` → 使用原始密钥 `K_raw`
- `CredentialEncryptor(tenant_id="t1")` → 使用派生密钥 `HKDF(K_raw, salt="t1")`

**但**，如果任何代码路径中 `tenant_id` 为 `""`（无论是旧代码未传 tenant_id 还是 connector 未设置），它会使用原始密钥——这与 per-tenant 密钥**共存**在同一个系统中。攻击者如果获取了一个 `tenant_id=""` 的密文 + 原始密钥，可以：
1. 解密所有 `tenant_id=""` 的历史密文
2. 不能解密 `tenant_id="t1"` 等 per-tenant 密文（这点安全）
3. **但如果未来有代码在 `tenant_id=""` 的 encryptor 下加密了新数据**，该数据不受 per-tenant 保护

**实际影响**：可控。Phase 2 的向后兼容模式是必要的——已有的 Phase 2 密文都是在 `tenant_id=""` 下加密的，不能要求立刻迁移。但 PRD 需要明确：`tenant_id=""` 是**过渡模式**，Phase 3+ 将废弃。

**建议**：在 PRD 中增加过渡说明：
```
AC-03 补充: tenant_id="" 的向后兼容模式是过渡性的。
Phase 3 在 TenantContext 就绪后，废弃无 tenant_id 的构造。
Phase 2+ 期间，所有新增密文应使用 per-tenant encryptor。
```

---

## P1 — 建议修改（3 个）

### P1-1：PRD AC-04 `X-EARP-Tenant-Id` header 命名与 Security Spec 不一致

**涉及段落**：PRD §3 AC-04

```
AC-04: RESTConnector._ensure_auth_headers() 当 connector.tenant_id 非空时
       注入 X-EARP-Tenant-Id: {tenant_id}
```

**问题**：Security Spec §5.1 定义 JWT payload 中有 `tenant_id` 字段。多租户 Spec §4.2 要求 `Connector 的请求中携带 X-EARP-Tenant-Id header`。命名一致没问题。

但当前 `RESTConnector` 中已有 `connector.tenant_id`（从 BaseConnector 继承）。Phase 4 代码评审（#2 修复）后，`connector.tenant_id` 默认 `""`。`_ensure_auth_headers()` 检查 `if self.config and self.config.auth.token` 决定是否注入 auth header。tenant header 的注入条件是什么——`if connector.tenant_id`（非空）？这和 Tenant Spec 第四章 "MUST" 有微妙的差异——Tenant Spec 要求所有 Connector 请求携带 `X-EARP-Tenant-Id`，但 AC-04 只在 connector.tenant_id 非空时注入。

这意味着：如果 connector.tenant_id 为 `""`（默认值），请求不带 `tenant_id` header，外部系统无法做租户级别的认证/限流。

**建议**：在 Tenant Spec 或 PRD 中明确非空条件：
```
如果 connector.tenant_id 为空（系统级 connector，如
内部基础设施连接），可以不注入 X-EARP-Tenant-Id。
业务级 connector 必须设置 tenant_id。
```

---

### P1-2：PRD AC-05 `RuntimeClient.create_session()` 参数变更可能 breaking

**涉及段落**：PRD §3 AC-05, §6.3

```
AC-05: RuntimeClient.create_session() 的 tenant_id 参数默认值从 ""
       改为无默认值（MUST 显式传入）
```

**当前 `client.py`** 签名：
```python
async def create_session(
    self, *, user_id: str, tenant_id: str = "", ttl_seconds: int = 3600, ...
) -> Session:
```

**改为无默认值**意味着所有 `create_session()` 调用方都需要显式传 `tenant_id`——包括测试、Phase 1 的 `test_security.py`、demo 代码等。

**建议**：如果这是一个 breaking change，需要在 PRD §1 背景中标注影响范围，并在 §6.3 中给出迁移示例。或者更温和的做法——保留默认值但改为 `Sentinel` 模式：
```python
_UNSET = object()

async def create_session(self, *, user_id: str, tenant_id: str | object = _UNSET, ...):
    if tenant_id is _UNSET:
        raise ValueError("tenant_id is required (Multi-Tenant Spec §4.2 MUST)")
```

这个方案在运行时抛错（而非编译期），但不会立即 breaking 所有现有调用——会在第一次调用时发现缺失。

---

### P1-3：Tenant Spec §4.2 "系统级事件的 tenant_id SHOULD" 与现有实现冲突

**涉及段落**：Tenant Spec §4.2

```
SHOULD: 系统级事件（如 AUTH_EXPIRED、Plugin load）携带 connector.tenant_id
```

**问题**：当前 Phase 2-4 实现中，审计事件的 `tenant_id` 全部硬编码 `""`。回顾:
- `base.py:92` — `tenant_id=self.tenant_id`（Phase 4 修复 #2 后）
- `manager.py:20` — `tenant_id=""`（PluginManager 审计）
- `guard.py:88` — `tenant_id=""`（InputGuard/OutputFilter 审计）

AUTH_EXPIRED 已修复为 `self.tenant_id`（✅ 对齐）。但 Plugin 加载和 LLM 安全审计事件仍为 `""`（❌ 不对齐）。

**建议**：在 Tenant Spec 中明确 "系统级事件的 tenant_id SHOULD" 的适用条件：
```
SHOULD: 当 connector/plugin 绑定到特定租户时，事件携带其 tenant_id。
全局基础设施事件（如共享 PluginManager 的加载）可以 tenant_id=""。
```

或在 Phase 5 统一补齐。

---

### P1-4：Tenant Spec §6.2.1 密钥派生方案未考虑加密密文格式升级

**涉及段落**：Tenant Spec §6.2.1

当前密文格式（Phase 2 L3 设计）：
```
base64(nonce[12] + ciphertext[N] + tag[16])
```

如果未来要支持 `tenant_id` 编码到密文中（使得密文可以自描述其所属租户，方便审计和迁移），当前的格式没有预留元数据空间。

**建议**：可以忽略——Phase 2 的密文格式不必立即包含 tenant_id。但当 HKDF 派生引入后，建议增加密文版本号：
```
base64(version[1 byte] + nonce[12] + ciphertext[N] + tag[16])
version = 1  →  当前格式
version = 2  →  将来格式（含 tenant 元信息）
```

标记为 P1 供 Phase 3 设计参考。

---

## P2 — 优化建议（2 个）

### P2-1：Tenant Spec 章节顺序稍显跳跃

**涉及段落**：Tenant Spec 全篇

当前顺序：概述 → 租户模型 → 数据隔离 → 请求隔离 → 资源隔离 → 安全隔离 → 审计 → SDK 集成。

建议调整：
1. 概述 (§1)
2. 租户模型 (§2) — 概念定义
3. 请求隔离 (§4) — 这是所有其他隔离的**前提**（tenant_id 从哪来）
4. 安全隔离 (§6) — 凭证、认证
5. 数据隔离 (§3) — 持久化、缓存、文件
6. 资源隔离 (§5) — LLM 配额、速率、存储
7. 审计 (§7)
8. SDK 集成 (§8)

逻辑链更顺：概念 → 标识传播 → 安全执行 → 数据落地 → 资源约束 → 审计追责。

标记为 P2——当前顺序也可接受。

---

### P2-2：PRD 缺少与 Phase 4 `BaseConnector.tenant_id` 修复的关系说明

**涉及段落**：PRD §4 依赖表

PRD §4 依赖表标注了"BaseConnector.tenant_id ✅"，但这是 Phase 4 代码评审 #2 修复的结果。如果 PRD 在修复前编写，缺少此上下文。**当前已修复，无实际影响**。

---

## 对齐检查表

### Tenant Spec §6.2 vs 已有 CredentialEncryptor

| Tenant Spec 要求 | 当前实现 | 状态 |
|:-----------------|:---------|:----:|
| §6.2 MUST: API Key per-tenant 加密存储 | `CredentialEncryptor` 统一密钥 | ⚠️ Phase 2+ 引入 HKDF |
| §6.2 MUST: 绑定 tenant_id（HKDF 派生） | 未实现 | PRD US-01/02 覆盖 |
| §6.2 SHOULD: 共享类型定义，实例绑定独立凭证 | 未实现 | Phase 3 |

### Tenant Spec §4.2 vs 已有 connector

| Tenant Spec 要求 | 当前实现 | 状态 |
|:-----------------|:---------|:----:|
| §4.2 MUST: Authorization header 携带 JWT（含 tenant_id） | ✅ RuntimeClient | ✅ 已有 |
| §4.2 MUST: Connector 请求携带 X-EARP-Tenant-Id | ❌ 未实现 | PRD AC-04 覆盖 |
| §4.2 SHOULD: 系统事件携带 connector.tenant_id | AUTH_EXPIRED ✅ / 其他 ⚠️ | 部分完成 |

### 与 Security Spec 的交叉引用

| Security Spec 要求 | Tenant Spec 引用 | 一致性 |
|:-------------------|:----------------|:------:|
| §2.2 MUST: AES-256-GCM 加密 | §6.2.1 HKDF 密钥派生 | ✅ 一致 |
| §5.1 MUST: JWT payload 含 tenant_id | §4.1.1 传播链路 | ✅ 一致 |
| §4.4 MUST: LLM per-tenant API Key | §6.3 LLM 隔离 | ✅ 一致 |

---

## 评审总结

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0 | 2 | HKDF salt 参数的密码学语义需在 Spec 中澄清；`tenant_id=""` 向后兼容模式存在密钥等价性风险 |
| ⚠️ P1 | 4 | X-EARP-Tenant-Id 非空条件与 Spec MUST 有歧义；create_session breaking change 影响未评估；系统事件 tenant_id SHOULD 与实现不一致；密文格式未预留版本号 |
| 💡 P2 | 2 | 章节顺序可优化；缺少 BaseConnector.tenant_id 的背景说明 |

### 结论

**规范 §6.2.1 的 HKDF 设计正确，PRD 的 HKDF 语义需要对齐规范。** 两个 P0 修复量较小（均不涉及架构变更）——分别是密码学实现细节的文本澄清和过渡策略说明。

### 好的方面

- **5 大原则精准** — 物理隔离、请求绑定、静默过滤、配额独立、凭证隔离抓住了多租户的核心
- **§4.1.1 传播链路完整** — Client → Gateway → Runtime → Planner → Capability → Connector → External System，7 跳端到端
- **§9 交叉引用表实用** — 与 Runtime/Security/Policy/Audit/Observation + Enterprise Architecture 全部引用，无遗漏
- **§8.2 实现优先级务实** — Phase 1-2 已有基础（tenant_id 已存在于所有关键实体），Phase 3-5 为增量
- **PRD 聚焦精准** — 5 个 US 覆盖了 Phase 1-2 的两个缺口（凭证密钥派生 + tenant_id header 补齐）
- **向后兼容考虑** — AC-03 保留无参构造，Phase 2 存量密文无需立即迁移
