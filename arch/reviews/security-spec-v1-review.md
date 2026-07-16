# Security Specification v1 — 评审报告

## 文档位置：arch/L2/06-security/security-specification-v1.md

| 字段 | 值 |
|------|-----|
| **文档** | Security Specification v1（L2） |
| **评审人** | Review Agent |
| **日期** | 2026-07-14 |
| **状态** | ✅ 全部 P0/P1/P2 已修复（v1.0 → v1.1） |

> **2026-07-14 更新**：PM Agent 已按本评审报告逐条修复。核心变更：明确与 Policy/Audit/Observation 的分工、InputGuard/OutputFilter 实体定义、内存清零 MUST→SHOULD。详见 §9。

---

## 总体评价

**首次阅读感受很好——组织清晰，覆盖面广，与四个 SDK 有明确的映射关系。** 7 个章节覆盖了凭证管理、数据加密、LLM 安全、API 安全、审计安全、Plugin 沙箱，范围完整。MUST 条款数量适中（30+ 条），与 SDK 的映射表（§8）实用。

共发现 **3 个 P0（必须修复）、4 个 P1（建议修改）、2 个 P2（建议性优化）**。

---

## P0 — 必须修复

### P0-1：与 Policy Spec 存在职责重叠——RBAC 和 Rate Limit 双边定义

**涉及段落：** §5.1（第 159-168 行）、§5.2（第 171-178 行）

Security Spec §5 定义了 API 认证授权和速率限制，但 Policy Center Spec（L2-05-POLICY §2.2）同样定义了 `rbac` 和 `rate_limit` 两种策略类型。

| 领域 | Security Spec | Policy Center Spec |
|:-----|:-------------|:------------------|
| RBAC | §5.1: JWT payload 含 permissions | §2.2: rbac 策略类型，Plan Validation 时评估 |
| Rate Limit | §5.2: 基于 user_id 限流 | §2.2: rate_limit 策略类型 |

两边都在定义同样的概念但没有互相引用——Security Spec 说"JWT → permissions"，Policy Spec 说"rbac policy → 评估"，但缺少中间的连接：**Policy 怎样使用 JWT 中的 permissions 做 rbac 决策？**

**建议方案：**

在 Security Spec §5 中明确引用 Policy Center Spec，说明分工：
- Security Spec 定义**认证**（JWT 验证、API Key 注入）——"你是谁"
- Policy Center Spec 定义**授权**（RBAC 策略评估）——"你能做什么"

跨文档引用示例：
```
MUST: JWT 验证后，permissions 字段传递给 Policy Center 做 RBAC 评估（见 L2-05-POLICY §2.2）
```

---

### P0-2：§2.2 MUST 要求"内存中的凭证必须在使用后立即归零"——Python 不可实现

**涉及段落：** §2.2（第 61 行）

```
MUST: 内存中的凭证必须在使用后立即归零
```

这是 C/Rust 级别的安全要求——Python 中字符串是不可变的（immutable），`token = ""` 只是重新绑定，原来的字符串对象可能仍在内存中直到 GC 回收。且 Python 的 GC 不保证覆盖内存。

**这个 MUST 在 Python 实现的四个 SDK 中是不现实的。** 要么降级为 SHOULD（说明 Python 的限制），要么改为更实际的要求（如"凭证仅在需要时读取，不在全局变量中长期持有"）。

**建议方案：**

```
SHOULD: 内存中的凭证不在全局变量中持有，使用后让引用离开作用域
说明：Python 字符串不可变，无法安全清零。依赖进程级别隔离。
```

---

### P0-3：§6 审计安全与 Audit Spec (L2-05-AUDIT v1.1) 存在内容重叠

**涉及段落：** §6（第 191-213 行）

Security Spec §6 定义了"审计日志不可变性"和"安全事件"，但 Audit Specification v1.1（L2-05-AUDIT）同样定义了审计日志格式、哈希链、存储保留。

Security Spec 应该**引用** Audit Spec 而不是重新定义审计基础设施。重叠的具体内容：

| Security Spec §6 | Audit Spec v1.1 | 问题 |
|:----------------|:----------------|:-----|
| 哈希链保证完整性（MUST） | 第二章同样定义 | 完全重叠 |
| append-only 存储（MUST） | 第三章存储与保留策略 | 完全重叠 |
| 安全事件列表（MUST） | 由 EventBus 事件类型定义 | Audit v1.1 已移除硬编码事件列表 |

**建议方案：**

Security Spec §6 只保留"哪些安全事件需要审计"（事件触发条件），删除"审计日志如何存储/防篡改"（引用 Audit Spec）。

---

## P1 — 建议修改

### P1-1：缺少与 Governance 层已有规范的交叉引用

**涉及段落：** 全文

Security Spec 是新规范（v1.0），但它不是凭空出现——Governance 层已有 4 份规范：
- Policy Center Spec（RBAC、Rate Limit）
- Audit Spec v1.1（审计日志）
- Observation Spec（Metrics/Trace）

Security Spec 目前只引用了 Runtime Spec（依赖行），没有引用这三份。P0-3 覆盖了 Audit；Policy Center 的 RBAC 重叠（P0-1）也应通过引用解决。

**建议：** 在 §1.1 依赖中增加 Policy Spec 和 Audit Spec。

---

### P1-2：§3.2 脱敏规则使用精确样式但未定义实现接口

**涉及段落：** §3.2（第 96-100 行）

```
MUST: 以下字段在日志/审计/API 响应中自动脱敏：
  - email（保留 @ 前首字母，替换其余为 ***）
  - phone（保留前 3 后 4 位，中间替换为 ****）
```

脱敏规则的精确样式定义了，但没说**在哪里实现、怎么实现**。§3.2 说"在 Gateway 层统一执行"，但 EARP 的 Gateway 是 SDK 还是服务端组件？这个术语在 L1 架构中没有对应。

**建议：** 定义脱敏的执行层（响应拦截器？日志中间件？），或引用 Observation Spec 的日志过滤能力。

---

### P1-3：§4.1 Prompt 注入防御的 "InputGuard" 实体未定义

**涉及段落：** §4.1（第 128 行）

```
MUST: 所有用户输入必须通过 InputGuard 处理
```

`InputGuard` 是什么？是一个 Python 类？是一个服务？是一个 Gateway 中间件？规范中首次出现但没有定义这个实体的职责、位置、接口。

**建议：** 用一段话定义 InputGuard 的职责和集成位置（如"InputGuard 是 Gateway 层的请求过滤器，在请求进入 Runtime 前执行"）。

---

### P1-4：§4.2 输出过滤的 "OutputFilter" 同样未定义

**涉及段落：** §4.2（第 144 行）

```
MUST: LLM 输出在进入 Capability 执行前必须经过 OutputFilter
```

同上，未定义 OutputFilter。

---

## P2 — 建议性优化

### P2-1：优先级路线图中缺少 Security Spec 自身的 Phase

§8 优先级路线图只列出了 4 个 Phase 按 SDK 划分。但规范层面的安全措施（如凭证加密、脱敏）的 Phase 划分与 SDK 的实现 Phase 可能不同。

**建议：** 增加一列"规范 Phase" vs "SDK 实现 Phase"，澄清规范定义与实现的时间关系。

---

### P2-2：§2.1 凭证类型表缺少 Plugin API Key

| 类型 | 用途 |
|:-----|:-----|
| ... | ... |
| Plugin API Key | 缺失 |

当前列出了 JWT、API Key、OAuth、mTLS、数据库密码 5 种，但 §7 的 Plugin 权限模型（`network`/`filesystem`/`llm_call`）可能需要 Plugin 自身的 API Key 来做沙箱访问控制。如果不需要，也应声明 Plugin 使用 Runtime 的统一认证。

---

## 对齐检查表

### 与其他 L2 规范的关系

| 规范 | 关系 | 状态 |
|:----|:-----|:----:|
| L2-01-RUNTIME v1.2 | ✅ 已引用 | Session/Context/JWT 认证 |
| L2-05-POLICY v1.0 | ⚠️ P0-1 | RBAC/Rate Limit 重叠未引用 |
| L2-05-AUDIT v1.1 | ⚠️ P0-3 | 审计日志内容重叠未引用 |
| L2-05-OBSERVATION | ⚠️ P1-2 | 脱敏可能与 Observation 日志过滤重叠 |

### 与 SDK 的映射（§8）

| SDK | 映射 | 状态 |
|:----|:-----|:----:|
| earp-sdk-core | ConnectorConfig 凭证存储 | ✅ 合理 |
| earp-sdk-capability | LLM 输入过滤 | ⚠️ InputGuard 未定义 |
| earp-sdk-runtime | JWT + rate limit | ✅ 合理 |
| earp-sdk-connector | API Key + TLS | ✅ 合理 |
| earp-sdk-plugin | permissions + sandbox | ✅ 合理 |

### MUST 条款统计

| 章节 | MUST | SHOULD | 总计 |
|:----|:----:|:------:|:----:|
| 凭证管理 | 5 | 2 | 7 |
| 数据加密 | 4 | 3 | 7 |
| LLM 安全 | 5 | 3 | 8 |
| API 安全 | 6 | 4 | 10 |
| 审计安全 | 4 | 1 | 5 |
| Plugin 沙箱 | 2 | 1 | 3 |
| **总计** | **26** | **14** | **40** |

MUST 密度适中，分布均匀。

---

## 评审总结

### 数据统计

| 类别 | 数量 |
|:----|:----:|
| ✅ 通过的检查项 | 10+ |
| ❌ P0（必须修复） | 3 |
| ⚠️ P1（建议修改） | 4 |
| 💡 P2（建议性优化） | 2 |

### 三个 P0 拦路石

1. **P0-1** — RBAC 和 Rate Limit 与 Policy Center Spec 双边定义，缺少引用关系
2. **P0-2** — "内存中凭证使用后立即归零"在 Python 中不现实
3. **P0-3** — 审计日志防篡改/哈希链与 Audit Spec v1.1 内容重叠

### 好的方面

- **覆盖面好** — 7 个章节从凭证加密到 LLM Prompt 注入，范围完整
- **MUST 条款粒度适中** — 40 条，分布均匀，大多可测试
- **§8 SDK 映射表** — 实用，直接将安全要求连接到四个 SDK
- **Plugin 沙箱（§7）** — 设计了权限声明模型，与 Plugin SDK 的 Permission 枚举完全对应
- **三层加密模型（§3.1）** — 传输层(TLS) + 应用层(AES) + 存储层(DB TDE)，分层清晰

### 总体建议

Security Spec 作为 L2 的后加入规范，内容本身质量高，但与前三个 Governance 规范（Policy/Audit/Observation）存在边界模糊——这是 P0-1 和 P0-3 的根源。建议：

1. 明确 Security Spec 的定位是"安全策略定义者"，不是"安全基础设施实现者"——后者由 Policy/Audit/Observation 规范承载
2. 删掉与 Audit Spec 重叠的审计存储/哈希链内容，改为引用
3. 将 P0-2 的内存清零要求降级为 Python 可实现的实际要求
