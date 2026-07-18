# Multi-Tenant Isolation Specification

## EARP 多租户隔离规范

**文档编号：L2-07-TENANT**  
**版本：v1.2**  
**定位：L2 — 平台规范。定义 EARP 的多租户隔离策略——请求隔离、安全隔离、数据隔离、角色隔离、资源隔离、审计追责。**  
**依赖：L2-01-RUNTIME v1.3, L2-06-SECURITY v1.1, L2-05-POLICY v1.1, L2-05-AUDIT v1.1**

> **v1.2 变更**：新增 §5.4 角色级数据隔离（Session/Execution 增加 role_id + 应用层四层 data_scope 过滤）；Policy Center Spec 依赖更新 v1.0→v1.1

> **v1.1 变更**：调整章节顺序（概述→租户模型→请求隔离→安全隔离→数据隔离→资源隔离→审计）；HKDF 密钥派生补充 `tenant_id=""` 时的 salt 行为；明确系统事件的 SHOULD 适用条件；密文格式增加 version byte 预留。

---

# 第一章：概述

## 1.1 定位

EARP 是 SaaS 多租户平台。每个租户拥有独立的工作空间——数据、凭证、Capability 注册、LLM 配额、审计日志均按租户隔离。

## 1.2 原则

| 原则 | 含义 |
|:-----|:-----|
| **请求必然绑定** | 每个请求必然携带 tenant_id（JWT payload），不可选、不可省 |
| **安全执行隔离** | 凭证密钥按 tenant_id 派生，跨租户密文不可解密 |
| **数据物理隔离** | 同一张表中 `WHERE tenant_id = ?`；不同租户的数据不交叉 |
| **静默过滤** | SDK/ORM 层自动注入 tenant_id，开发者不手写 tenant 过滤条件 |
| **配额独立** | 每个租户有独立的 LLM 调用配额、存储配额、速率限制 |
| **审计追责** | 所有审计事件、Metrics 标签含 tenant_id |

---

# 第二章：租户模型

## 2.1 租户标识

```
MUST: 每个租户具有全局唯一的 tenant_id（UUID 格式）
MUST: tenant_id 在整个请求生命周期中不可变
MUST: JWT payload 中 auth.tenant_id 为请求的权威租户标识
```

## 2.2 租户层级

```
Tenant（租户）── 顶层隔离单位
  └── OrgUnit（组织单元）── 可选，企业内部门隔离
       └── User（用户）── 最终使用者
            └── ServiceAccount（服务账号）── 自动化调用
```

```
SHOULD: 支持 OrgUnit 级别的子隔离（企业多部门场景）
MAY: 支持租户间的 Capability 共享（显式授权，非默认）
```

---

# 第三章：请求隔离

## 3.1 Tenant Context 传播

```
MUST: 每个请求携带 tenant_id（JWT payload 中的 auth.tenant_id）
MUST: Runtime 从 JWT 提取 tenant_id，注入到执行上下文中
MUST: Capability 调用时 Runtime 将 tenant_id 传递给 Capability Context
MUST: Capability 只能访问本租户的数据（Context.tenant_id 决定数据可见性）
```

### 3.1.1 传播链路

```
Client (JWT: {tenant_id: "t1"})
  → Gateway (验证 JWT，提取 tenant_id)
    → Runtime (创建 Session: session.tenant_id = "t1")
      → Planner (Plan 生成：所有操作在 t1 范围内)
        → Capability (Context.tenant_id = "t1")
          → Connector (请求携带 X-EARP-Tenant-Id: t1)
            → External System (API Key per-tenant)
```

## 3.2 SDK 层传播

```
MUST: RuntimeClient 的 Authorization header 携带 JWT（含 tenant_id）
MUST: Connector 的请求中携带 X-EARP-Tenant-Id header（当 connector.tenant_id 非空时）
      系统级 connector（如内部基础设施连接）tenant_id 可为空，不注入此 header
SHOULD: 系统级事件携带 connector.tenant_id——当 connector/plugin 绑定到特定租户时
        事件携带其 tenant_id；全局基础设施事件（如共享 PluginManager 加载）可用 tenant_id=""
```

---

# 第四章：安全隔离

## 4.1 认证与授权

```
MUST: JWT 中的 tenant_id 为请求的权威租户标识，不可绕过
MUST: 用户/ServiceAccount 属于且仅属于一个租户
MUST: 跨租户冒充禁止——JWT tenant_id ≠ target tenant_id 时拒绝
SHOULD: 全局管理员 role 可跨租户只读访问（审计用途）
```

## 4.2 凭证隔离

```
MUST: Connector 的 API Key / 数据库密码 按租户加密存储
MUST: EncryptedAuthConfig 加密时绑定 tenant_id（密钥派生加入 tenant_id）
SHOULD: 多租户共享 Connector 类型定义，但实例化时绑定独立凭证
```

### 4.2.1 密钥派生

```
AES-256-GCM 密钥 = HKDF-SHA256(
    IKM   = EARP_CREDENTIAL_KEY（环境变量，32 字节 master key）,
    salt  = tenant_id（UTF-8 编码）,
    info  = b"earp-credential-encryption-v1"
)

当 tenant_id 为空字符串 "" 时，salt 为空字节串 b""（Phase 2 向后兼容模式）。
不同 tenant_id 产生独立的派生密钥，跨租户密文不可解密。
```

### 4.2.2 密文格式（预留版本号）

```
Phase 2 当前格式: base64(nonce[12 bytes] + ciphertext[N bytes] + tag[16 bytes])
Phase 3+ 扩展格式: base64(version[1 byte] + nonce[12] + ciphertext[N] + tag[16])
         version = 0x01 → v1 格式（含 tenant 元信息）

Phase 2 密文不含 version byte。Phase 3+ 引入 version byte，与当前格式向后兼容
（密文长度不同，解密时自动识别：37+N bytes = Phase 2, 38+N bytes = Phase 3+）。
```

## 4.3 LLM 隔离

```
MUST: 不同租户的 LLM 调用使用独立的 API Key
MUST: LLM API Key 按租户加密存储
MUST: Prompt/Response 日志按租户隔离
SHOULD: 敏感租户使用私有模型部署（dedicated inference endpoint）
```

---

# 第五章：数据隔离

## 5.1 持久化层

```
MUST: 所有持久化实体包含 tenant_id 字段（BaseTenantEntity）
MUST: 查询时自动注入 WHERE tenant_id = ?（ORM/SDK 层静默过滤）
MUST: 跨租户查询禁止——任何 JOIN/子查询不允许跨 tenant_id
SHOULD: 数据库层面使用 Row-Level Security (RLS) 作为第二道防线
```

### 5.1.1 实体清单

| 实体 | 存储 | tenant_id 来源 |
|:-----|:-----|:--------------|
| Session | Runtime DB | JWT → Context → Session |
| Execution | Runtime DB | 继承 Session.tenant_id |
| Capability 注册 | Capability Registry | 注册时声明，不可变 |
| Connector 配置 | Config Store | 加密存储，per-tenant |
| Audit Log | Audit Store | 事件携带，不可变 |
| Policy 定义 | Policy Store | per-tenant 或 global (tenant_id=NULL) |
| LLM API Key | Vault/Encrypted | per-tenant 加密存储 |

## 5.2 缓存层

```
MUST: 缓存 key 包含 tenant_id 前缀（如 "t:{tenant_id}:session:{session_id}"）
MUST: 缓存驱逐/失效不跨租户
SHOULD: 每个租户有独立的缓存 namespace
```

## 5.3 文件存储

```
MUST: 文件/对象存储路径包含 tenant_id 前缀（如 "s3://earp/{tenant_id}/..."）
MUST: 文件访问 URL 为临时签名 URL，签名中绑定 tenant_id
```

## 5.4 角色级数据隔离（v1.2 新增）

```
MUST: Session、Execution、Checkpoint 创建时写入当前 role_id
MUST: 数据按角色隔离（三层防线）：
  第一层 — Session/Execution 创建时写入 role_id
  第二层 — 应用层按 data_scope 过滤（self/department/org/all）
  第三层 — RLS 仅做 tenant 隔离兜底（WHERE tenant_id = ?）
MUST: 默认封闭 — 无显式授权时角色间数据不可互见
MUST: data_scope 四层由 Policy Center Spec §5.3 定义，应用层 `build_data_filter()` 执行
```

### 5.4.1 影响的数据实体

| 实体 | 新增字段 | 说明 |
|:-----|:---------|:-----|
| Session | `role_id: string` | 创建时的当前角色 |
| Execution | `role_id: string` | 继承 Session 的 role_id |
| Checkpoint | `role_id: string` | 继承 Execution 的 role_id |
| AuditLog | `detail.role_id: string`, `detail.user_roles: list` | 操作时的角色上下文 |

### 5.4.2 示例

```
市场分析员（role=market_analyst, data_scope=department）创建 Session：
  → Session.role_id = "market_analyst"
  → Session.user_id = "u-123"
  → 财务主管（role=finance_manager, data_scope=all）查询时：
     应用层 data_scope="all" → 无 role_id 过滤 → 可看到该 Session
  → 市场分析员（role=market_analyst, data_scope=department）查询时：
     应用层 data_scope="department" → role_id IN ("market_analyst", ...) → 可看到
  → 另一市场分析员（data_scope=self）查询时：
     应用层 data_scope="self" → role_id="market_analyst" AND user_id="u-123" → 不可见
```

---

# 第六章：资源隔离

## 6.1 LLM 配额

```
MUST: 每个租户有独立的 LLM 调用配额（token 数/时间窗口）
MUST: LLM API Key 按租户隔离存储（见 §4.3）
MUST: 配额耗尽时返回 429 RateLimited，不影响其他租户
SHOULD: 租户可配置自己的 LLM provider（不同租户可用不同的模型供应商）
```

## 6.2 速率限制

```
MUST: Rate Limit 按 tenant_id + capability_id 统计（对齐 Policy Spec）
MUST: 一个租户触发限流不影响其他租户的可用性
SHOULD: 默认 per-tenant rate limit 在全局配置中可覆盖
```

## 6.3 存储配额

```
MUST: 每租户 Session/Execution 存储有上限
MUST: 审计日志保留周期 per-tenant 可配置
SHOULD: 租户达到存储上限时阻止新 Session 创建（非静默丢弃）
```

---

# 第七章：审计与可观测性

## 7.1 审计范围

```
MUST: 所有审计事件包含 tenant_id（对齐 Audit Spec §2.1）
MUST: 审计日志查询默认按 tenant_id 过滤
SHOULD: 租户管理员只能查看本租户的审计日志
```

## 7.2 监控指标

```
MUST: 所有 Metrics 标签包含 tenant_id（对齐 Observation Spec）
MUST: 跨租户聚合查询仅在全局管理视角允许
SHOULD: 每个租户的 Dashboard 仅展示本租户数据
```

---

# 第八章：SDK 集成

## 8.1 SDK → 规范映射

| SDK | 多租户关注点 | 对应章节 |
|:----|:----------|:---------|
| earp-sdk-core | 凭证加密密钥按 tenant_id 派生（HKDF） | §4.2 |
| earp-sdk-runtime | Session/Execution 自动携带 tenant_id | §3.2 |
| earp-sdk-connector | X-EARP-Tenant-Id header，凭证 per-tenant | §3.2, §4.2 |
| earp-sdk-capability | Context.tenant_id 数据过滤 | §3.1.1 |
| earp-sdk-plugin | Plugin 权限 per-tenant，沙箱隔离 | — |

## 8.2 实现优先级

| Phase | 内容 | 影响 SDK | 复杂度 |
|:-----:|:-----|:---------|:------:|
| **Phase 1** | tenant_id 全链路传播（JWT → Session → Capability → Connector） | Runtime + Connector | 低（已有） |
| **Phase 2** | 凭证密钥按 tenant_id 派生（HKDF） + X-EARP-Tenant-Id header | Core + Connector | 低 |
| **Phase 3** | LLM API Key per-tenant 存储 | Capability + Security | 中 |
| **Phase 4** | 资源配额执行（LLM token/存储/速率） | Policy + Runtime | 高 |
| **Phase 5** | 缓存/文件路径 tenant_id 前缀，系统事件 tenant_id 统一补齐 | 基础设施 | 中 |

---

# 第九章：与其他规范的交叉引用

| 规范 | 引用场景 |
|:-----|:---------|
| L2-01-RUNTIME | Session/Execution/Context 的 tenant_id 字段（§6.3） |
| L2-06-SECURITY | JWT payload 含 tenant_id（§5.1）；LLM per-tenant API Key（§4.4） |
| L2-05-POLICY | Rate Limit per tenant+capability_id（§2.2） |
| L2-05-AUDIT | 审计事件 tenant_id 为 MUST 字段（§2.1） |
| L2-05-OBSERVATION | Metrics 标签含 tenant_id |
| L1/enterprise-architecture | BaseTenantEntity, workspace domain model |

---

# 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | HKDF salt 参数的密码学语义需澄清 | §4.2.1 补充：tenant_id="" 时 salt 为空字节串；明确不同 tenant 密钥独立 |
| P0-2 | tenant_id="" 向后兼容密钥等价性风险 | PRD AC-03 补充过渡说明（待 PRD 修复） |
| P1-1 | X-EARP-Tenant-Id 非空条件与 MUST 的歧义 | §3.2 补充：系统级 connector 可为空，业务级必须设置 |
| P1-3 | 系统事件 SHOULD 与实现不一致 | §3.2 SHOULD 改为"绑定到租户时携带 tenant_id，全局事件可为空" |
| P1-4 | 密文格式未预留版本号 | §4.2.2 新增 version byte 定义（0x01=当前格式） |
| P2-1 | 章节顺序可优化 | 重组为：概述→租户模型→请求隔离→安全隔离→数据隔离→资源隔离→审计→SDK |
