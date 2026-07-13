# Capability Center Specification

## EARP 能力中心规范

**文档编号：L2-03-CAPABILITY**
**版本：v1.1**
**定位：L2 — 平台规范。本文定义 Capability Center 的契约，是所有业务能力的注册、发现、解析、治理标准。**
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md**

---

# 第一章：概述

## 1.1 Capability Center 的定位

Capability Center 是 EARP 的**企业能力语义层 + 调度执行中枢**。

它负责：

- 企业能力建模（Capability Definition）
- 能力注册与生命周期管理（Lifecycle）
- 能力语义关联（Graph）
- 能力解析与路由（Resolution）
- 执行契约输出（Execution Contract）

### 明确边界

**Capability Center 不负责：**

- ❌ 执行任务（由 Execution Runtime 负责）
- ❌ 决策是否执行（由 Decision Engine 负责）
- ❌ Prompt / LLM 编排（由 Reasoning 层负责）

## 1.2 范围

本文定义 Capability Center 的规范：

| 模块 | 说明 | 章节 |
|------|------|------|
| Capability 定义 | 业务能力的核心契约 | 第二章 |
| Capability 三层结构 | Definition / Execution Contract / Policy 分层 | 第三章 |
| Capability Lifecycle | 注册 / 版本 / 废弃 / 退役 | 第四章 |
| Capability Registry | 注册与查询规范 | 第五章 |
| Capability Graph | 语义关系网络 + 执行约束 | 第六章 |
| Capability Resolution Engine | 解析、路由、过滤 | 第七章 |
| Capability Invocation | 调用模型与执行路径 | 第八章 |
| Capability Health | 健康与指标 | 第九章 |
| Capability Marketplace | 市场规范（Phase 4） | 第十章 |

本文不涉及：
- Service 如何实现业务逻辑（由 Service Specification 定义）
- Connector 如何对接外部系统（由 Connector Specification 定义）
- Planner 如何选择 Capability（由 Planner Specification 定义）

## 1.3 规范性要求

本文中的"必须（MUST）""应该（SHOULD）""可以（MAY）"按 RFC 2119 解释。

违反 MUST 条款的 Capability 实现属于不合规能力，Runtime 有权拒绝加载或执行。

---

# 第二章：Capability 定义

## 2.1 概念

Capability 是 Runtime 可以完成的一项**业务能力**，是平台最核心的资产。Capability 封装业务语义，隐藏技术实现。调用者不知道底层是 MES、SAP 还是数据库。

```
Capability 不是 Tool：
  Tool 回答 "怎么调"（SQL/HTTP/API）
  Capability 回答 "做什么"（查询库存/创建工单）

Capability 不是 Execution：
  Capability 是 Execution Description（描述如何被执行）
  Capability 不负责执行本身（由 Execution Runtime 负责）
```

## 2.2 核心契约

```
MUST: 每个 Capability 包含以下字段
  - capability_id:     string          — 全局唯一（MUST）
  - name:              string          — 中文名称（MUST）
  - description:       string          — 业务描述（MUST）
  - domain:            string          — 所属业务领域（MUST）
  - version:           string          — 语义版本号（MUST）
  - capability_type:   "query" | "command"（MUST）
  - status:            "draft" | "active" | "deprecated" | "retired"（MUST）

MUST: capability_id 全局唯一，永久不变，下架后不可复用
MUST: 版本号遵循语义化版本（MAJOR.MINOR.PATCH）
  - MAJOR: Schema 不兼容变更
  - MINOR: Schema 向后兼容扩展
  - PATCH: 内部实现变更，对外契约不变
```

## 2.3 命名规范

```
MUST: capability_id 使用 snake_case
  - 正确：query_equipment_alarm、create_work_order

SHOULD: 按 "动词_领域_对象" 命名
  - query_equipment_alarm、create_work_order、approve_purchase_order

SHOULD: name 使用中文业务术语
  - 正确：查询设备报警、创建工单
```

---

# 第三章：Capability 三层结构（核心收敛）

Capability 不是单一结构。它由三层组成，每层职责不同、变更频率不同。

## 3.1 Definition Layer（语义层）

定义 Capability 的业务语义。**几乎不变。**

```
MUST: Definition Layer 包含
  - capability_id:     string    — 唯一标识
  - name:              string    — 中文名称
  - description:       string    — 业务描述
  - domain:            string    — 所属领域
  - tags:              list      — 标签
  - input_schema:      JSONSchema— 输入 Schema
  - output_schema:     JSONSchema— 输出 Schema
  - capability_type:   "query" | "command"
```

## 3.2 Execution Contract Layer（执行契约层）

定义 Capability 如何被执行。**按系统对接情况变化。**

```
MUST: Execution Contract Layer 包含
  - protocol:             "http" | "grpc" | "sql" | "mcp" | "sdk"（MUST）
  - timeout:              int       — 超时（毫秒）（MUST）
  - retry_policy:         RetryConfig（MUST）
  - idempotent:           bool      — 是否幂等（MUST）
  - transaction_scope:    "none" | "local" | "distributed" | "saga"（MUST）
  - supports_compensation: bool（Command 类型 MUST）
  - compensating_capability: string | null（supports_compensation=true 时 MUST）
```

## 3.3 Policy Layer（治理层）

定义 Capability 的治理约束。**按企业策略变化。**

```
MUST: Policy Layer 包含
  - auth_required:        bool      — 是否需要认证（MUST）
  - required_permissions: list[str] — 所需权限列表（MUST）
  - approval_required:    bool      — 是否需要审批（MUST）
  - audit_level:          "summary" | "detail"（MUST）
  - constraints:          list[Constraint] — 策略约束（SHOULD）
    - region
    - data_classification
    - rate_limit
```

## 3.4 示例

```json
{
  "definition": {
    "capability_id": "query_equipment_alarm",
    "name": "查询设备报警",
    "domain": "equipment",
    "version": "1.0.0",
    "capability_type": "query",
    "input_schema": { "type": "object", "properties": { "equipment_id": {"type": "string"} } },
    "output_schema": { "type": "object", "properties": { "alarms": {"type": "array"} } }
  },
  "execution_contract": {
    "protocol": "http",
    "timeout": 5000,
    "retry_policy": { "max_attempts": 3, "backoff": "exponential" },
    "idempotent": true,
    "transaction_scope": "none",
    "supports_compensation": false
  },
  "policy": {
    "auth_required": true,
    "required_permissions": ["alarm:read"],
    "approval_required": false,
    "audit_level": "summary",
    "constraints": [{"type": "rate_limit", "value": 100}]
  }
}
```

---

# 第四章：Capability Lifecycle

## 4.1 状态机

```
Draft → Active → Deprecated → Retired
                ← Deprecated（撤回废弃）
```

| 状态 | 含义 | 可调用 | 参与 Graph | 参与 Discovery |
|------|------|--------|-----------|---------------|
| Draft | 开发中，仅开发者可见 | 否 | 否 | 否 |
| Active | 可用 | 是 | 是 | 正常排序 |
| Deprecated | 不推荐但兼容 | 是 | 是（降级排序） | 排末位 |
| Retired | 已退役，不可用 | 否 | 否 | 否 |

## 4.2 关键规则

```
MUST: Active 状态才可进入 Resolution Engine
MUST: Deprecated 至少保留 90 天迁移期
MUST: Deprecated 应继续参与 Graph（提供备用方案），仅在 Discovery 排序时降低优先级
MUST: Retired 的 capability_id 不可复用
MUST: Retired 不参与 Graph
SHOULD: Deprecated 状态需要声明 fallback_capability
```

## 4.3 注册要求

```
MUST: 注册时提供完整的三层结构（所有 MUST 字段）
MUST: 注册时完成 Schema 合法性校验
SHOULD: 注册时完成适配器测试连接
SHOULD: 注册时自动生成语义索引（Embedding 向量）
```

---

# 第五章：Capability Registry

Capability Registry 仅负责三件事：**注册、查询、生命周期管理**。不做执行、不做决策、不做编排。

## 5.1 API

```
POST   /capabilities                  — 注册
PATCH  /capabilities/{id}             — 更新
POST   /capabilities/{id}/deprecate   — 废弃
POST   /capabilities/{id}/retire      — 退役
GET    /capabilities/{id}             — 详情
GET    /capabilities/search?q={query} — 发现
```

## 5.2 Discovery 规范

```
MUST: 支持以下检索模式
  - 语义搜索（Embedding + Vector）
  - 关键词搜索
  - 领域筛选（domain）
  - 类型筛选（type=query|command）
  - 组合检索

SHOULD: 结果排序依据
  - 语义匹配度
  - 历史调用频率
  - 成功率

MUST: 仅在 Active 和 Deprecated 状态的 Capability 中检索
MUST: Active 优先于 Deprecated 排序
```

## 5.3 Domain 绑定

```
MUST: 每个 Capability 绑定到一个 Domain
MUST: 一个 Domain 包含 N 个 Capability
```

---

# 第六章：Capability Graph（语义关系 + 执行约束）

Capability Graph 是 Capability 之间的语义关系网络，同时携带执行约束。Planner 的智能度不取决于 LLM 本身，而取决于 Capability Graph 的丰富度。

Graph = 语义关系 + 执行约束，而不仅是知识关系。

## 6.1 关系类型

| 关系 | 方向 | 说明 | 示例 |
|------|------|------|------|
| depends_on | 有向 | A 的执行依赖 B | `query_alarm_analysis` → `query_equipment_alarm` |
| composes | 有向 | A 由 B 和 C 组成 | `handle_fault` → `[query_alarm, create_task]` |
| substitutes | 双向 | A 可替代 B | `query_oee_by_mes` ↔ `query_oee_by_manual` |
| conflicts_with | 双向 | A 和 B 互斥 | `start_equipment` ↔ `stop_equipment` |
| related_to | 双向 | 同域不同侧面 | `query_inventory` ↔ `query_order` |
| followed_by | 有向 | A 完成后通常执行 B | `create_work_order` → `notify_team` |

## 6.2 执行约束（新增重点）

Graph 不仅表达语义关系，还表达**执行约束**：

```
MUST: 每条关系可携带执行约束
  - parallel_allowed:     bool  — A 和 B 是否可并行执行（MUST）
  - sequence_required:    bool  — A 和 B 是否必须串行执行（MUST）
  - transaction_boundary: bool  — A 和 B 是否在同一事务边界内（MUST）
```

示例：

```yaml
depends_on:
  target: query_equipment_alarm
  parallel_allowed: false      # 必须先查状态才能分析
  sequence_required: true
  transaction_boundary: false

conflicts_with:
  target: stop_equipment
  parallel_allowed: false
  sequence_required: true      # 不能同时启动和停止
  transaction_boundary: false

followed_by:
  target: notify_team
  parallel_allowed: true       # 可以一边完成一边通知
  sequence_required: false
  transaction_boundary: true   # 与创建工单在同一事务
```

## 6.3 契约

```
MUST: 关系声明包含 source、target、relation_type、weight(0-1)、执行约束
SHOULD: 支持自动推理（传递关系/对称关系/互补关系）
SHOULD: 新 Capability 注册时自动推荐关系
SHOULD: 调用模式自动补充 followed_by 关系
SHOULD: Active version 才参与 Graph
MUST: Retired 状态不参与 Graph
```

## 6.4 Planner 使用场景

```
Planner 利用 Graph 进行：
  - 能力发现：通过关系链发现候选 Capability
  - 路径规划：通过 depends_on 链 + 执行约束生成执行路径
  - 故障替代：通过 substitutes 找到备用 Capability
  - 并行优化：通过 parallel_allowed 决定 Step 调度策略
```

---

# 第七章：Capability Resolution Engine（新增核心）

Resolution Engine 是 Planner 调用 Capability 时的**唯一入口**。

## 7.1 Resolution 定义

```
Capability Resolution =
  semantic match（语义匹配）
+ graph traversal（图遍历：关系链 + 执行约束）
+ policy filtering（策略过滤：权限/合规/审批）
+ runtime availability check（运行时可用性：健康/速率）
```

## 7.2 决策原则

优先级从高到低：

1. **Policy 合规** — 用户有权限、不违反约束
2. **可执行性** — Capability 状态为 Active、健康度正常
3. **语义匹配度** — 输入意图与 Capability 描述的匹配程度
4. **成本最低** — 多个候选时选择成本最优

## 7.3 输出结构

```yaml
selected_capabilities:    # 最终选择的能力列表
  - capability_id: string
    confidence: float
    execution_contract: {...}

fallback_capabilities:    # 备用方案（当 selected 不可用时）
  - capability_id: string
    relation: "substitutes" | "similar_to"
    degrade_level: "full" | "partial"

composition_plan:         # 组合方案
  - steps: [...]
    execution_constraints: {...}

constraints:              # 约束条件
  - timeout: int
  - parallel_allowed: bool
  - transaction_boundary: bool
```

## 7.4 Resolution 统一入口

```
Planner → Resolution Engine → Registry(查询)
                             → Graph(遍历)
                             → Policy(过滤)
                             → Runtime(可用性确认)
                             → 输出 ResolutionResult
```

---

# 第八章：Capability Invocation

## 8.1 调用模式

```
Query Capability  → Read-only execution（只读，无副作用）
Command Capability → State-changing execution（写操作，有副作用）
```

## 8.2 Invocation Flow

```
Resolution（解析/路由/过滤）
    ↓
Policy Check（权限/速率/合规）
    ↓
Dispatch（调度到 Service/Connector）
    ↓
Result（返回结果 + 审计）
```

Execution Contract 是 Capability 声明时自带的静态信息，无需运行时构建。

## 8.3 完整执行路径

```
Query:
  Resolution → Policy Check(只读) → Dispatch → Service → Connector → Result → Audit(摘要)

Command:
  Resolution → Policy Check(读写) → Approval Check
    → Approved → Transaction → Dispatch → Service → Connector → Result
    → Rejected → Cancelled
    → Audit(详细) → Completed / Compensated
```

## 8.4 错误码

| 错误码 | 说明 | 可重试 |
|--------|------|--------|
| CAPABILITY_NOT_FOUND | Capability 不存在 | 否 |
| SCHEMA_VALIDATION_FAILED | Schema 校验失败 | 否 |
| PERMISSION_DENIED | 无权限 | 否 |
| RATE_LIMIT_EXCEEDED | 超出限流 | 是 |
| CONNECTOR_ERROR | 适配器连接失败 | 是 |
| BUSINESS_ERROR | 业务逻辑错误 | 否 |
| TIMEOUT | 执行超时 | 是 |
| SYSTEM_ERROR | 系统内部错误 | 是 |

---

# 第九章：Capability Health

```
MUST: 持续追踪以下指标
  - call_count / success_count / failure_count
  - avg_duration_ms / p99_duration_ms
  - error_distribution（按错误码）

MUST: 定期执行健康检查（每分钟）
  - 状态：healthy | degraded | unreachable

SHOULD: 成功率影响 Discovery 排序
SHOULD: 成功率低于 90% → 告警
SHOULD: degraded 状态的 Capability 在 Resolution 中降低优先级
MUST: unreachable 状态的 Capability 不出现在 Resolution 结果中
```

---

# 第十章：Capability Marketplace（Phase 4）

```
MUST: Marketplace Capability 遵循完全相同的规范（三层结构、Graph、Resolution）
MUST: 通过沙箱隔离执行
MUST: 增加字段：publisher_id、pricing_model、rating
SHOULD: 有独立的安全审计流程
```

---

# 附录 A：Capability vs Runtime vs Planner vs Decision（最关键收敛点）

| 模块 | 一句话职责 | 解释 |
|------|-----------|------|
| **Capability Center** | "有哪些能力" | 能力建模、注册、Graph、Resolution |
| **Planner** | "怎么组合能力" | 利用 Graph 和 Resolution 生成执行 Plan |
| **Decision Engine** | "是否执行" | 判断当前条件下是否应该执行 |
| **Execution Runtime** | "执行能力" | 按 Contract 可靠执行 Capability |

**四个职责互不重叠，一个改动的变更不影响另外三个。**

---

# 附录 B：核心设计原则（L2 冻结级）

---

## Principle 1：Capability is Semantic Unit

Capability 不是 API，不是 Tool，不是 Endpoint。Capability 是**业务语义单元**。

---

## Principle 2：Capability is Not Execution

Capability **描述**如何被执行（Execution Contract），但**不负责**执行本身（Execution Runtime 负责）。

---

## Principle 3：Graph is Executable-Aware

Graph 不仅表达语义关系（depends_on / substitutes / composes），还表达**执行约束**（parallel_allowed / sequence_required / transaction_boundary）。

---

## Principle 4：Resolution is Single Entry Point

所有 Capability 调用必须经过 Resolution Engine。Registry 只存查，不参与 Planner 决策路径。

---

## Principle 5：Policy is First-Class

所有 Capability 必须受 Policy 控制。无 Policy 的能力不可执行。

---

# 附录 C：Connector 规范

Connector 是企业系统集成适配器，负责将 Capability 的执行请求转发到外部系统。

## C.1 定义

```
MUST: Connector 包含
  - connector_id:    string    — 全局唯一
  - name:            string    — 名称
  - protocol:        string    — 协议类型（http/grpc/jdbc/mqtt/opcua/rfc/odata/mcp）
  - version:         string    — 版本号
  - status:          "active" | "inactive" | "error"
```

## C.2 基类契约

```
MUST: 所有 Connector 实现以下方法

test_connection() -> { status, latency_ms, error }
  测试外部系统连接

execute(operation, params) -> { status, data, error }
  执行业务操作

get_capabilities() -> list[CapabilityDefinition]
  返回可提供的 Capability（用于自动注册）

health_check() -> "healthy" | "degraded" | "unreachable"
  健康检查，频率每分钟
```

## C.3 生命周期

```
Registered → Connected → Active → Disconnected
    ↓                   ↓
Connection Failed    Error → Reconnecting → Connected
                      ↓
                 RetryLimit → Removed
```

```
MUST: test_connection 成功后进入 Connected
MUST: 连接失败自动重连（最多 3 次，指数退避）
SHOULD: 重连策略可配置
```

## C.4 内建类型

| Connector | 协议 | Phase |
|-----------|------|-------|
| REST | HTTP | Phase 1 |
| Database | JDBC/SQL | Phase 1 |
| MQTT | MQTT | Phase 2 |
| OPC-UA | OPC-UA | Phase 2 |
| SAP | RFC/OData | Phase 2 |
| MCP | MCP | Phase 2 |
| SOAP | SOAP/XML | Phase 2 |
| IM | HTTP | Phase 2 |

## C.5 MCP Connector

```
MCP Connector 职责：
  1. 连接 MCP Server（MCP 协议）
  2. list_tools → 映射为 Capability（注册到 Capability Center）
  3. call_tool → 执行

Tool → Capability 映射规则：
  Tool name → capability_id
  Tool description → Capability description
  Tool inputSchema → Capability input_schema

MUST: MCP 凭证由 Connector 配置管理，不在 Tool 参数中透传
SHOULD: MCP Tool 映射的 Capability 自动标记 source_system = "mcp"
```

## C.6 错误码

| 错误码 | 可重试 |
|--------|:------:|
| CONNECTION_FAILED | 是 |
| TIMEOUT | 是 |
| RATE_LIMITED | 是（等待后重试） |
| AUTH_EXPIRED | 否 |
| INVALID_RESPONSE | 否 |
| SYSTEM_ERROR | 是 |

```
MUST: 所有 Connector 使用统一错误码
SHOULD: 可重试错误自动重试（最多 3 次，指数退避）
MUST: 不可重试错误记录审计日志并通知管理员
```

---

# 附录 D：v1.0 → v1.1 变更记录

| 变更 | 类型 | 说明 | 章节 |
|------|------|------|------|
| Capability 三层结构 | 重构 | Definition / Execution Contract / Policy 独立分层 | 第三章 |
| 明确边界 | 新增 | 在第一章声明 Capability Center 不做什么 | 1.1 |
| Graph 增加执行约束 | 重构 | parallel_allowed / sequence_required / transaction_boundary | 第六章 |
| Resolution Engine | 🔴 新增 | 统一 Planner 调用 Capability 的入口 | 第七章 |
| Invocation Flow | 重构 | 简化为 Resolution → Policy Check → Dispatch → Result | 第八章 |
| Lifecycle | 优化 | Removed → Retired；补充 Deprecated Graph 规则 | 第四章 |
| 边界收敛表 | 新增 | Capability vs Planner vs Decision vs Runtime 职责对照 | 附录 A |
| 设计原则 | 新增 | 5 条 L2 冻结级原则 | 附录 B |

---

# 附录 D：与 Concept Model 的对应关系

| Concept Model v1.3 | 本规范章节 |
|-------------------|-----------|
| Capability | 第二章、第三章 |
| Query / Command | 3.1 |
| Domain | 5.3 |
| Policy | 3.3 Policy Layer |
| Service | 引用 Service Specification |
| Connector | 引用 Connector Specification |

---

# 附录 E：与 Runtime Spec 的对应关系

| Runtime Specification v1.2 | 本规范章节 |
|---------------------------|-----------|
| Execution（第九章） | 第八章 — 调用契约与错误码 |
| Plan Validation（第二章） | 8.3 — 执行路径 |
| Business Transaction（第十章） | 8.3 — Command 的事务执行 |
| Compensation（9.6） | 3.2 — 补偿声明 |
