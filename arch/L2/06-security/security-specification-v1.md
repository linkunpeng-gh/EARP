# Security Specification

## EARP 安全规范

**文档编号：L2-06-SECURITY**
**版本：v1.1**
**定位：L2 — 平台规范。定义 EARP 的安全策略——凭证管理、数据加密、LLM 安全、API 安全。审计基础设施和授权策略由各自的 Governance 规范承载。**
**依赖：L0/design-philosophy.md, L1/architecture-v6.md, L2-01-RUNTIME v1.2, L2-05-POLICY v1.0, L2-05-AUDIT v1.1, L2-05-OBSERVATION v1.0**

---

# 第一章：概述

## 1.1 与 Governance 规范的分工

| 规范 | 负责 | Security Spec 的关系 |
|:-----|:-----|:-------------------|
| **Security Spec**（本文） | 安全**策略**——定义认证、加密、LLM 防护、敏感字段脱敏的具体规则 | — |
| **Policy Center Spec** | 安全**执行**——RBAC 策略评估、Rate Limit 策略执行 | §5 引用：JWT 验证后的 permissions 传递给 Policy Center 做授权评估 |
| **Audit Spec** | 安全**记录**——审计日志格式、不可变存储、哈希链、保留策略 | §6 引用：Security Spec 定义"哪些事件需要审计"，Audit Spec 定义"如何记录" |
| **Observation Spec** | 安全**监控**——Metrics/Trace/告警、日志过滤 | §3.2 引用：敏感字段脱敏规则通过 Observation 的日志过滤执行 |

## 1.2 原则

| 原则 | 含义 |
|:-----|:-----|
| **永不明文存储** | 所有凭证必须加密存储，运行时内存解密 |
| **最小权限** | 每个 Capability/Connector/Plugin 仅获取所需的最小权限 |
| **纵深防御** | 传输层(TLS) + 应用层(JWT) + 数据层(AES) 三层 |
| **LLM 零信任** | LLM 输入/输出默认不可信，需过滤和沙箱 |

---

# 第二章：凭证管理

## 2.1 凭证类型

| 类型 | 用途 | 存储 | 轮换周期 |
|:-----|:-----|:-----|:--------:|
| JWT Token | 用户/应用认证 | 客户端持有 | 短期（1h-24h） |
| API Key | 外部系统连接（Connector） | 加密存储 → earp-sdk-core Config | 手动轮换 |
| OAuth Token | 第三方平台集成 | 加密存储，支持 refresh | 由 provider 决定 |
| mTLS 证书 | 服务间通信 | Kubernetes Secret / Vault | 90 天 |
| 数据库密码 | Connector 连接 | 加密存储，启动时注入 | 90 天 |

> Plugin 使用 Runtime 的统一 JWT 认证，不需要独立的 Plugin API Key。

## 2.2 MUST 约束

```
MUST: 所有凭证必须使用 AES-256-GCM 加密后存储
SHOULD: 凭证不在全局变量中长期持有，使用后让引用离开作用域
        注：Python 字符串不可变，无法安全清除内存。依赖进程级别隔离。
MUST: JWT 使用 RS256 签名（非对称），私钥由 Runtime 持有
MUST: API Key 通过环境变量注入，不得出现在代码或配置文件中
MUST: Connector 的 auth.token 字段在日志中自动脱敏
SHOULD: 支持 Vault 等外部密钥管理服务集成
SHOULD: JWT refresh token 与 access token 分离存储
```

---

# 第三章：数据加密

## 3.1 三层加密

| 层级 | 范围 | 算法 | 密钥管理 |
|:----:|:-----|:-----|:---------|
| **传输层** | 所有 HTTP/gRPC 通信 | TLS 1.3 | Kubernetes cert-manager |
| **应用层** | Session Context、敏感请求参数 | AES-256-GCM | Runtime Key Store |
| **存储层** | 数据库持久化数据 | AES-256 透明加密 | 数据库 TDE |

## 3.2 敏感字段脱敏

```
MUST: 以下字段在日志/审计/API 响应中自动脱敏：
  - password, token, secret, api_key（全部替换为 "***"）
  - email（保留 @ 前首字母，替换其余为 ***）
  - phone（保留前 3 后 4 位，中间替换为 ****）
  - id_card / ssn（替换全部为 ***）

执行层：脱敏规则在响应序列化层和日志中间件中执行（详见 Observation Spec 日志过滤能力）。
SDK 侧：Connector SDK 的 RESTConnector._ensure_auth_headers() 已实现 token 不在日志中出现。
SHOULD: Capability 的输出包含敏感字段时，Capability 开发者应声明 output_masking
```

## 3.3 加密存储

```
MUST: 持久化存储的所有用户数据必须加密存储（AES-256 或数据库 TDE）
MUST: Session Context 中的用户身份信息在落盘时加密
SHOULD: 加密密钥与数据分库存储
```

---

# 第四章：LLM 安全

## 4.1 关键实体定义

- **InputGuard**：Gateway 层的请求过滤器，在用户输入进入 Runtime 前执行注入检测和输入净化。实现为中间件，在 HTTP 请求路由到 Planner 之前执行。
- **OutputFilter**：LLM 响应过滤器，在 LLM 输出进入 Capability 执行前执行 PII 检测、有害内容过滤。实现为 Capability 调用链中的拦截器。

## 4.2 Prompt 注入防御

| 攻击向量 | 防御措施 |
|:---------|:---------|
| 直接注入 | 用户输入与系统 Prompt 通过分隔符隔离；用户输入经过 InputGuard 净化 |
| 间接注入 | 外部数据源在注入 Prompt 前通过 LLM 二次摘要 |
| 越狱 | Multi-turn 对话中检测 prompt 模式变化 |
| 泄露系统 Prompt | OutputFilter 检测到 system prompt 片段时阻断 |

```
MUST: 所有用户输入必须通过 InputGuard 处理
MUST: 系统 Prompt 与用户输入使用明确分隔符（如 "--- USER INPUT ---"）
MUST: 外部数据源在进入 Prompt 前必须经过摘要/过滤
SHOULD: 检测到疑似注入攻击时，生成 Security Alert 事件（由 Audit Spec 定义的审计通道记录）
```

## 4.3 输出安全

```
MUST: LLM 输出在进入 Capability 执行前必须经过 OutputFilter
MUST: Command 类型 Capability 的 LLM 生成参数需要人工审核（Approval 流程，见 Policy Spec）
SHOULD: 输出包含可执行代码时，自动路由到沙箱环境
```

## 4.4 模型访问控制

```
MUST: 不同租户的 LLM 调用通过独立的 API Key 隔离
MUST: 限制 LLM 调用频率（per-tenant rate limit，详见 Policy Spec rate_limit 策略）
SHOULD: 敏感 Capability 使用私有模型部署
```

---

# 第五章：API 安全

## 5.1 认证——由 Security Spec 定义

Security Spec 负责**认证**（"你是谁"）——Policy Center Spec 负责**授权**（"你能做什么"，见 L2-05-POLICY §2.2 RBAC 策略）。

```
MUST: 所有 API 端点需要认证（除 /health）
MUST: JWT 验证在每个请求上执行，不做 session 缓存
MUST: JWT payload 包含 user_id、tenant_id、permissions
      验证后，permissions 字段传递给 Policy Center 做 RBAC 评估（见 L2-05-POLICY §2.2）
SHOULD: 支持 mTLS 服务间认证
```

## 5.2 速率限制——策略由 Policy Spec 执行

```
MUST: 所有 API 端点实施速率限制
MUST: 限流策略由 Policy Center Spec 的 rate_limit 策略类型执行（见 L2-05-POLICY §2.2）
MUST: 限流基于 user_id 或 token（非 IP）
SHOULD: 返回 HTTP 429 时包含 Retry-After header
```

## 5.3 输入校验

```
MUST: 所有 API 输入必须在请求入口层校验 JSON Schema
MUST: 请求体大小限制（默认 1MB）
MUST: URL/Query 参数长度限制
SHOULD: 拒绝包含 script 标签的输入
```

---

# 第六章：审计安全

## 6.1 与 Audit Spec 的分工

```
Security Spec（本文）：定义需要审计的**安全事件类型**
Audit Spec v1.1（L2-05-AUDIT）：定义审计日志的**记录格式、不可变存储、哈希链、保留策略**
```

## 6.2 安全事件类型

```
MUST: 以下安全事件必须写入审计日志（由 Audit Spec 定义的审计通道记录）：
  - 认证失败（401）
  - 权限拒绝（403）
  - Prompt 注入检测
  - 凭证轮换
  - 异常访问模式（短时间内大量失败）
  - Plugin 加载/卸载
  - 管理员操作
```

---

# 第七章：Plugin 沙箱

## 7.1 权限模型

| 权限 | 说明 | 默认 |
|:-----|:-----|:----:|
| `network` | 允许 Plugin 发起网络请求 | 禁止 |
| `filesystem` | 允许 Plugin 读写本地文件 | 禁止 |
| `llm_call` | 允许 Plugin 调用 LLM | 禁止 |

```
MUST: 所有 Plugin 必须声明所需权限
MUST: Plugin 未声明的权限操作自动拒绝
SHOULD: Plugin Manager 在 Plugin 加载时初始化沙箱约束
```

## 7.2 隔离级别

```
Phase 1: None（信任内部 Plugin）
Phase 2: Process（子进程隔离，通过 gRPC 通信）
Phase 3: Sandbox（WASM 或 RestrictedPython）
```

---

# 第八章：与 SDK 的映射

| SDK | 安全关注点 | 对应章节 |
|:----|:----------|:---------|
| earp-sdk-core | ConnectorConfig 凭证加密存储 | 第二章 |
| earp-sdk-capability | InputGuard/OutputFilter 集成点 | 第四章 |
| earp-sdk-runtime | JWT 验证、permissions 传递 → Policy Center | 第五章 |
| earp-sdk-connector | API Key 注入、TLS、token 不在日志中 | 第二章 |
| earp-sdk-plugin | permissions 声明、沙箱约束 | 第七章 |

---

# 优先级路线图

| 规范 Phase | SDK Phase | 内容 | 影响 SDK |
|:---------:|:--------:|:-----|:---------|
| **P1** | **P1** | JWT 认证 + API 速率限制 | Runtime SDK |
| **P1** | **P2** | 凭证加密存储（AES-256） | Connector SDK |
| **P2** | **P2** | 敏感字段脱敏 | 全部 SDK（日志层） |
| **P2** | **P3** | InputGuard + OutputFilter | Capability SDK |
| **P3** | **P4** | Plugin 沙箱（Process 隔离） | Plugin SDK |

---

# 第九章：与其他规范的交叉引用

| 规范 | 引用场景 |
|:-----|:---------|
| L2-05-POLICY | §5.1 JWT → RBAC 授权评估、§5.2 rate_limit 策略、§4.3 人工审核流程 |
| L2-05-AUDIT | §6 安全事件的审计通道、不可变存储格式 |
| L2-05-OBSERVATION | §3.2 脱敏规则的日志过滤执行层 |
| L2-01-RUNTIME | Session Context 加密、JWT 验证流程 |
| L2-03-CAPABILITY | ConnectorConfig 凭证注入 |

---

# 评审修复记录

| 编号 | 问题 | 修复 |
|:----:|:-----|:-----|
| P0-1 | RBAC/Rate Limit 与 Policy Spec 双边定义 | §5 明确分工：Security=认证，Policy=授权。新增交叉引用 |
| P0-2 | "内存归零"在 Python 不可实现 | MUST 降级为 SHOULD，标注 Python 限制 |
| P0-3 | 审计日志与 Audit Spec 重叠 | §6 删除存储/哈希链内容，改为引用 Audit Spec。只保留安全事件列表 |
| P1-1 | 缺 Governance 引用 | §1.1 新增 Policy/Audit/Observation 分工表 + §9 交叉引用表 |
| P1-2 | 脱敏无实现层 | §3.2 明确执行层在响应序列化 + 日志中间件 + Connector SDK |
| P1-3 | InputGuard 未定义 | §4.1 新增实体定义（Gateway 中间件） |
| P1-4 | OutputFilter 未定义 | §4.1 新增实体定义（Capability 链拦截器） |
| P2-1 | 路线图缺规范 Phase | §8 新增"规范 Phase"列 |
| P2-2 | 凭证表缺 Plugin API Key | §2.1 明确 Plugin 使用 Runtime JWT，不需独立 Key |
