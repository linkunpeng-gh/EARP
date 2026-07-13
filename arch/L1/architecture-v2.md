# Enterprise AI Runtime Platform（EARP）

## 架构设计 v2.0（优化版）

> 基于 v1.0 架构评审的 Critical & Major 发现进行优化。
> **核心变更**：Runtime 解耦、Kernel 职责收敛、Plan Validation Layer 新增、部署拓扑明确、安全架构补充。

---

# 第一章：设计原则

## 1.1 核心原则

```
┌────────────────────────────────────────────────────────────┐
│ Runtime First   所有应用均调用 Runtime，不允许直连 LLM       │
│ Capability First AI 调用 Business Capability，不直接调 Tool │
│ Domain Driven   围绕企业业务领域设计，而非围绕模型设计        │
│ Event Driven    Runtime 内部事件驱动，模块间解耦             │
│ Adapter Pattern 所有第三方系统经过 Adapter，Runtime 不感知   │
│ Plugin First    所有能力可插件化（SPI 契约定义）             │
│ Stateless Runtime Runtime 无状态，状态外置到 Kernel          │
└────────────────────────────────────────────────────────────┘
```

## 1.2 关键架构决策（ADRs）

### ADR-001：Runtime 无状态化

| 决策 | 值 |
|------|-----|
| 状态位置 | 全部外置到 Kernel + Infrastructure |
| 扩容方式 | Runtime 副本数 ≥ 2，水平扩展 |
| 恢复机制 | 基于 Checkpoint 重建，非任务重调度 |
| 失败模式 | 任何 Runtime 节点宕机，Kernel 重新调度到其他节点 |

### ADR-002：Kernel 下沉

| 决策 | 值 |
|------|-----|
| Context 归属 | Kernel 层持有 KernelContext，Runtime 通过 API 获取，不持有副本 |
| Checkpoint 归属 | Kernel 统一管理 Checkpoint 生命周期 |
| Artifact 归属 | Kernel 统一管理 Artifact 的存储和分发 |
| 实施原则 | Runtime 层不出现与 Kernel 同名的模块 |

### ADR-003：Planner 可靠性保障

| 决策 | 值 |
|------|-----|
| 默认 Planner | Rule-based Planner（Phase 1 默认） |
| LLM Planner | 仅在白名单场景启用，且必须经过 Plan Validation |
| 验证机制 | Plan Validation Layer（执行前）+ Outcome Verification（执行后） |
| 回退策略 | LLM Planner 输出无效时回退到 Rule Planner |

---

# 第二章：总体架构

## 2.1 系统分层

```
┌──────────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER                                               │
│  Chat │ Workflow Studio │ Agent Studio │ Knowledge Base          │
│  Dashboard │ Playground │ Prompt Center │ SDK │ API Gateway      │
│  ── 不负责执行，所有执行委托给 Runtime ──                         │
├──────────────────────────────────────────────────────────────────┤
│  RUNTIME LAYER (无状态，水平扩展)                                  │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Planner Service │  │ Executor     │  │  Scheduler       │   │
│  │  (独立扩缩容)     │  │ Service      │  │  Service         │   │
│  │                  │  │              │  │                  │   │
│  │  Task Intake     │  │ Capability   │  │ Task Queue       │   │
│  │  Intent Parser   │  │ Executor     │  │ Cron/Event/      │   │
│  │  Capability      │  │ Streamer     │  │ Webhook/MQTT     │   │
│  │  Discovery       │  │ ↓ 流式输出    │  │ Trigger          │   │
│  │  Plan Generator  │  │ Artifact Gen │  │                  │   │
│  └────────┬─────────┘  └──────┬───────┘  └────────┬─────────┘   │
│           │                   │                    │             │
│           └───────────────────┼────────────────────┘             │
│                               │                                  │
│              Plan Validation Layer (验证关卡)                     │
│         Schema校验 │ 权限校验 │ 循环检测 │ 深度限制               │
├──────────────────────────────────────────────────────────────────┤
│  KERNEL LAYER (有状态基础设施)                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────┐  │
│  │ Context  │ │ State    │ │ EventBus │ │ Trace │ Audit      │  │
│  │ Manager  │ │ Machine  │ │          │ │                    │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────┐  │
│  │ Checkpoint│ │ Policy  │ │ Metrics  │ │ Permission         │  │
│  │ Manager  │ │ Engine   │ │          │ │                    │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────────┘  │
│  ┌──────────┐ ┌──────────┐                                      │
│  │ Artifact │ │ Memory   │                                      │
│  │ Manager  │ │ Manager  │                                      │
│  └──────────┘ └──────────┘                                      │
│  ── 不包含业务逻辑，提供通用基础设施 ──                           │
├──────────────────────────────────────────────────────────────────┤
│  CAPABILITY LAYER                                                │
│  Business │ Knowledge │ Analysis │ Communication │ Automation    │
│  ── Runtime 唯一调用对象，不暴露底层实现 ──                      │
├──────────────────────────────────────────────────────────────────┤
│  INTEGRATION LAYER (Adapter 模式)                                │
│  ERP │ MES │ PLM │ CRM │ SCADA │ Database │ REST │ MQTT         │
│  Kafka │ MCP │ Filesystem │ Object Storage │ SOAP               │
│  ── 所有外部系统均经过 Adapter 接入 ──                           │
├──────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE LAYER                                            │
│  PostgreSQL │ Redis │ Object Storage │ Message Queue             │
│  Sandbox │ Docker │ Kubernetes                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 2.2 层间通信契约

| 调用方向 | 通信方式 | 协议/规范 | 同步/异步 |
|----------|---------|----------|----------|
| Application → Runtime | gRPC + REST | Protobuf + OpenAPI | 同步（Chat）/ 异步（Workflow） |
| Runtime → Kernel | gRPC（内部） | Protobuf | 同步 |
| Runtime → Capability | 内部函数调用 | Python Protocol Class | 同步 |
| Capability → Integration | 内部函数调用 | Adapter Interface | 同步 |
| Integration → 外部系统 | REST / gRPC / JDBC / MQTT 等 | 按协议 | 混合 |
| Kernel → EventBus | 内存 + 消息队列 | CloudEvents + Avro | 异步 |

---

# 第三章：Runtime 层（优化）

## 3.1 部署拓扑

```
                  ┌──────────────┐
                  │   Nginx /    │
                  │  API Gateway │
                  └──────┬───────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
   ┌───────────┐  ┌───────────┐  ┌───────────┐
   │  Planner  │  │  Executor │  │ Scheduler │
   │ Service   │  │  Service  │  │ Service   │
   │ (2-10副本) │  │ (5-20副本) │  │ (2-5副本)  │
   └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
         │              │              │
         └──────────────┼──────────────┘
                        │
                        ▼
               ┌────────────────┐
               │ Plan Validation│
               │ Layer          │
               │ (sidecar)      │
               └────────────────┘
                        │
                        ▼
               ┌────────────────┐
               │  Kernel Service│
               │ (3-5副本+主从)  │
               └────────────────┘
```

- **Planner Service**：高延迟（LLM 调用），需要 GPU，独立扩缩容，无状态
- **Executor Service**：短平快执行，CPU 密集，独立扩缩容，无状态
- **Scheduler Service**：长周期任务调度，轻量级，无状态
- **Kernel Service**：有状态（Checkpoint / State Machine / Memory），主从部署

## 3.2 Runtime 模块职责

### 3.2.1 Planner Service

```
输入: Task (用户请求 + Context)
├── Intent Parser      → 理解意图 + 提取参数
├── Capability Discovery → 检索匹配的 Capability
├── Plan Generator     → 生成 Execution Plan（DAG）
└── Plan Output        → 输出 Plan（验证后发给 Executor）

支持的 Planner 类型：
  Rule Planner       [Phase 1 默认] — 基于规则引擎
  LLM Planner        [Phase 2] — 基于 LLM 动态规划
  Hybrid Planner     [Phase 2] — Rule + LLM 混合
  Self-Reflection    [Phase 3] — Plan 执行后自动反思优化
```

### 3.2.2 Executor Service

```
输入: Plan (经过 Plan Validation Layer 校验)
├── Step Runner       → 依次/并行执行 Step
├── Capability Caller → 调用 Capability（经过 Policy Gate）
├── Streamer          → 流式推送结果
├── Artifact Gen      → 产物生成
└── State Reporter    → 报告执行状态到 Kernel

支持：暂停 / 恢复 / 重试 / 超时熔断
```

### 3.2.3 Scheduler Service

```
输入: 触发事件（Cron / Event / Webhook / MQTT / Condition）
├── Trigger Registry  → 管理所有 Trigger
├── Trigger Evaluator → 评估触发条件
├── Task Enqueuer     → 生成 Task 并入队列
└── Schedule Manager  → Cron 调度管理
```

## 3.3 Runtime 执行流程（带时序）

### 典型流程：用户询问"统计昨天所有产线异常"

```
User                    Planner        Plan Validation    Executor        Kernel
 │                        │                    │              │              │
 │── 查询昨天产线异常 ────→│                    │              │              │
 │                        │                    │              │              │
 │                        ├─ Intent Parser     │              │              │
 │                        │  "产线异常"→意图:   │              │              │
 │                        │  产线异常统计       │              │              │
 │                        │                    │              │              │
 │                        ├─ Capability Disc.  │              │              │
 │                        │  → query_alarms    │              │              │
 │                        │  → query_workorders│              │              │
 │                        │                    │              │              │
 │                        ├─ Plan Generator    │              │              │
 │                        │  生成 Plan (DAG)    │              │              │
 │                        │                    │              │              │
 │                        └── Plan ───────────→│              │              │
 │                                             │              │              │
 │                                             ├─ Schema 校验  │              │
 │                                             ├─ 权限校验      │              │
 │                                             ├─ 循环检测      │              │
 │                                             │              │              │
 │                                             └── OK ────────→│              │
 │                                                             │              │
 │                                                             ├── Step 1 ───→│
 │                                                             │  getContext() │
 │                                                             │←── Context ──│
 │                                                             │              │
 │                                                             ├── Capability │
 │                                                             │ query_alarms │
 │                                                             ├─── Adapter ──│
 │                                                             │ MES Adapter  │
 │                                                             │              │
 │                                                             ├── Step 2 ───→│
 │                                                             │  query_work  │
 │                                                             │  orders      │
 │                                                             │              │
 │                                                             ├── Step 3     │
 │                                                             │  LLM 分析     │
 │                                                             │  (自然语言生成)│
 │                                                             │              │
 │←─────────── 结果流式输出 ←──────────────────────────────────┼── Stream ───│
 │                                                             │              │
 │                                                             └──── Audit ──→│
 │                                                                            │
 │                                                                            │
```

## 3.4 Plan Validation Layer（新增）

这是 Runtime 内部的关键防御关卡，防止 Planner 的错误决策进入执行层。

```
Plan (来自 Planner)
    │
    ▼
┌──────────────────────────────────────────┐
│           Plan Validation Layer          │
│                                          │
│  1. Schema Validation                    │
│     └─ 每个 Step 的 input 符合 Schema    │
│                                          │
│  2. Permission Validation                │
│     └─ 当前用户有权限调用这些 Capability  │
│                                          │
│  3. Capability Existence Validation      │
│     └─ 需要调用的 Capability 已注册且可用 │
│                                          │
│  4. Cycle Detection                      │
│     └─ DAG 无环，且嵌套深度 < MaxDepth   │
│                                          │
│  5. Resource Quota Validation            │
│     └─ 不超过租户配额 / 速率限制          │
│                                          │
│  6. LLM Plan Confidence（LLM 模式）       │
│     └─ LLM 的决策置信度是否 > 阈值        │
│                                          │
│  输出: Validated Plan / Rejected + Reason│
└──────────────────────────────────────────┘
```

---

# 第四章：Kernel 层（优化）

## 4.1 模块清单

Kernel 是**有状态基础设施层**，不包含业务逻辑。所有模块呈**下沉部署**，Runtime 不持有同名模块。

| 模块 | 职责 | 数据存储 | 备注 |
|------|------|---------|------|
| Context Manager | 管理请求上下文（Tenant/User/Role/Session） | Redis（快） | 无业务语义 |
| State Machine | 管理执行状态（Created/Running/Paused/Succeeded/Failed） | PostgreSQL | 通用状态机 |
| EventBus | 事件发布/订阅 | Redis Streams / Kafka | CloudEvents 规范 |
| Trace Manager | 分布式链路追踪 | Jaeger + 持久化 | OpenTelemetry 标准 |
| Audit Logger | 审计日志 | PostgreSQL（追加写） | 防篡改 |
| Metrics Collector | 指标收集 | Prometheus | 预定义+自定义 |
| Policy Engine | 策略评估（RBAC / 限流 / 数据范围 / 审批） | PostgreSQL | 可扩展策略 |
| Permission Checker | 权限校验 | Redis（Cache）+ PostgreSQL | RBAC + 行级 |
| Checkpoint Manager | 执行检查点管理（创建/恢复/清理） | Object Storage + PostgreSQL | 用于恢复/重放 |
| Artifact Manager | 产物管理（报告/文件/截图） | Object Storage | 可溯源 |
| Memory Manager | 多层记忆管理 | Redis + PostgreSQL + VectorDB | Phase 1 仅两层 |
| Id Generator | 全局唯一 ID | Snowflake / Redis | 分布式友好 |

## 4.2 Memory 分层（Phase 1 简化版）

```
┌───────────────────────────────────────────────────────┐
│  Memory Manager                                       │
│                                                       │
│  ┌──────────────────────┐  ┌──────────────────────┐  │
│  │  Conversation Memory  │  │   Long Memory        │  │
│  │                      │  │                      │  │
│  │  当前对话历史        │  │  用户长期偏好 / 配置  │  │
│  │  TTL: 会话结束可回收  │  │  跨会话知识积累       │  │
│  │  存储: Redis          │  │  存储: PostgreSQL     │  │
│  │  检索: Key-Value      │  │  检索: Key + Embedding│  │
│  │  一致性: 最终一致性    │  │  一致性: 最终一致性    │  │
│  └──────────────────────┘  └──────────────────────┘  │
│                                                       │
│  Waiting → Phase 2                                    │
│    Working Memory: 当前执行上下文的临时状态            │
│    Semantic Memory: 实体关系 + 知识图谱                │
│    Business Memory: 业务规则 + Capability 调用模式     │
└───────────────────────────────────────────────────────┘
```

---

# 第五章：Capability 层（优化）

## 5.1 Capability 定义

Capability 是 Runtime **唯一调用对象**。

### 接口定义

```python
class CapabilitySchema:
    """Capability 的输入/输出 Schema，使用 JSON Schema 格式"""
    type: str  # "object"
    properties: dict
    required: list[str]

class BusinessCapability:
    """业务能力 — Runtime 唯一调用的对象"""
    
    # 标识
    capability_id: str           # "query_work_order"
    domain: str                  # "manufacturing.production"
    version: str                 # "1.2.0"
    
    # 语义
    name: str                    # "查询工单"
    description: str             # "根据工单号或日期范围查询生产工单"
    
    # Schema
    input_schema: CapabilitySchema
    output_schema: CapabilitySchema
    
    # 权限
    required_permissions: list[str]  # ["work_order:read"]
    data_scope: str                  # "org" | "dept" | "self"
    
    # 策略
    rate_limit: int              # 100/minute
    approval_required: bool      # False
    audit_level: str             # "detail" | "summary" | "none"
    max_execution_time: int      # 30s
    
    # 绑定
    adapter: str                 # "sap_adapter"
    adapter_method: str          # "query_orders"
    
    # 元数据
    tags: list[str]              # ["生产", "工单"]
    source_system: str           # "SAP_S4HANA"
```

### Capability 粒度规范

| 层级 | 粒度 | 示例 | 复用性 |
|------|------|------|--------|
| 基础 Capability | 原子操作，一个数据源 | `query_work_order`、`get_equipment_status` | 高 |
| 组合 Capability | 2-5 个基础 Capability 组合 | `analyze_production_line_oee` | 中 |
| 业务流程 Capability | 10+ 步的跨系统流程 | `handle_equipment_fault` | 低（按业务场景） |

**原则**：优先设计基础 Capability，组合 Capability 由 Workflow / Agent 编排实现。

## 5.2 Capability Registry

```
┌──────────────────────────────────────────┐
│            Capability Registry            │
│                                          │
│  注册: Post /capabilities {metadata}     │
│  更新: Patch /capabilities/:id           │
│  废弃: Post /capabilities/:id/deprecate  │
│  发现: Get /capabilities/search?q=xxx    │
│          (语义搜索 + 关键词 + 标签筛选)    │
│                                          │
│  存储: PostgreSQL（元数据）               │
│        + Embedding（语义索引）            │
│        + Redis（热点缓存）               │
│                                          │
│  Capability Discovery:                   │
│    Phase 1: Embedding + Vector Search    │
│    Phase 2: + Keyword + Metadata Filter  │
│    Phase 3: + Knowledge Graph 推理       │
└──────────────────────────────────────────┘
```

---

# 第六章：企业集成层（Integration Layer）

## 6.1 Adapter 接口规范

```python
class IntegrationAdapter(ABC):
    """企业集成适配器基类"""
    
    adapter_id: str              # "sap_adapter"
    supported_systems: list[str] # ["SAP_ECC", "SAP_S4HANA"]
    version: str                 # "1.0.0"
    
    @abstractmethod
    def test_connection(self) -> ConnectionResult:
        """测试与外部系统的连接"""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> list[CapabilityDefinition]:
        """返回该适配器提供的能力列表"""
        pass
    
    @abstractmethod
    def execute(self, capability_id: str, params: dict, context: KernelContext) -> AdapterResult:
        """执行业务能力"""
        pass
    
    @abstractmethod
    def health_check(self) -> HealthStatus:
        """健康检查"""
        pass
```

## 6.2 MCP 集成策略

MCP 接入定义为 **Connector 模式**，而非 Tool 模式：

```
MCP Server (SAP)
    │
    ▼
MCP Connector (adapter)
    │
    ├── list_capabilities()   → 注册到 Capability Registry
    ├── execute(cap_id, args) → 调用 MCP Tool
    └── health_check()        → MCP Server 健康状态
            │
            ▼
   Capability Center
   ("query_sap_order")
            │
            ▼
        Runtime
      (不知道 SAP 是谁)
```

MCP Tool 不直接暴露给 AI，而是映射为 Capability 后通过 Runtime 调用。

---

# 第七章：Workflow 与 Agent 安全性

## 7.1 嵌套调用防护

```
┌─────────────────────────────────────────────────┐
│              Loop Detection                      │
│                                                  │
│  Agent A 调用 Workflow B                         │
│  Workflow B 调用 Agent C                         │
│  Agent C 调用 Workflow A  →  ❌ 检测到循环        │
│                                                  │
│  防护机制:                                       │
│  1. Call Stack 追踪                              │
│  2. Max Depth = 10                               │
│  3. 同 Tenant 内 Call ID 唯一                     │
│  4. Circuit Breaker: 连续 N 次失败后熔断          │
└─────────────────────────────────────────────────┘
```

## 7.2 执行模式矩阵

```
                Chat      Workflow     Agent       Scheduled
──────        ──────     ────────     ──────      ──────────
入口            Web        Studio      API         Scheduler
Planner        无         预定义       动态        预定义
执行            直线        DAG        ReAct Loop    DAG
人工介入        无         有(审批节点)  可配置        有
超时            30s        30min       5min        60min
可恢复          否         是(Checkpoint) 否        是
```

---

# 第八章：Enterprise Ontology（演进路径）

```
Phase 1 (简版):
  ┌──────────────────────────┐
  │  业务对象目录 + 关系表    │
  │                          │
  │  对象: 设备 / 工单 / ... │
  │  关系: 设备→产线(N:1)    │
  │  存储: PostgreSQL 关系表  │
  │  用途: Planner Schema 提示 │
  └──────────────────────────┘

Phase 2 (增强):
  ┌──────────────────────────┐
  │  Ontology + 属性扩展     │
  │                          │
  │  对象增加属性定义         │
  │  关系增加 Cardinality    │
  │  存储: PostgreSQL + JSONB│
  │  用途: Planner + 权限继承 │
  └──────────────────────────┘

Phase 3 (正式):
  ┌──────────────────────────┐
  │  知识图谱 + 图推理       │
  │                          │
  │  存储: 图数据库           │
  │  推理: Graph RAG + Rule  │
  │  用途: Planner 自主推理   │
  │        Capability 发现    │
  └──────────────────────────┘
```

---

# 第九章：安全架构（新增）

## 9.1 安全域

```
┌─────────────────────────────────────────────────┐
│                  Security Architecture          │
│                                                  │
│  Authentication                                   │
│  ├── SSO / OAuth2 / OIDC / LDAP                  │
│  ├── API Key (Service Account)                   │
│  └── JWT 内部服务间认证                          │
│                                                  │
│  Authorization (通过 Kernel Policy Engine)        │
│  ├── RBAC (Role → Permission → Resource)        │
│  ├── 行级数据权限 (只看本部门)                    │
│  └── Capability 级别权限                         │
│                                                  │
│  LLM 安全                                         │
│  ├── Prompt Injection 检测（规则 + LLM as Judge） │
│  ├── 输出过滤（敏感信息 / 代码 / PII）            │
│  └── LLM 调用审计（完整 Prompt + Response 记录）  │
│                                                  │
│  数据安全                                         │
│  ├── 字段级脱敏（返回前根据角色过滤）              │
│  ├── 数据传输加密（TLS 1.3）                      │
│  └── 密钥管理（Vault / KMS，不落盘明文）          │
│                                                  │
│  审计安全                                         │
│  ├── Audit Log 追加写，不可篡改                   │
│  ├── 审计日志加密存储                             │
│  └── 审计数据独立存储，与应用数据隔离              │
│                                                  │
│  沙箱安全                                         │
│  ├── Code Node 执行隔离（Docker / WASM）          │
│  ├── 网络策略（仅允许出站白名单）                  │
│  ├── 资源限制（CPU / Memory / Timeout）           │
│  └── 文件系统隔离                                 │
└─────────────────────────────────────────────────┘
```

---

# 第十章：错误处理与恢复策略（新增）

## 10.1 错误分类

```
┌─────────────────────────────────────────────────────────┐
│                  Error Classification                    │
│                                                         │
│  可重试 (Retryable):                                    │
│  ├── 网络超时 / 连接重置 → 自动重试 (Retry 3次, Backoff)│
│  ├── 数据库死锁 / 冲突  → 自动重试                     │
│  ├── Rate Limit 被限流  → 等待后重试                   │
│  └── LLM 临时错误        → 自动重试                    │
│                                                         │
│  不可重试 (Non-Retryable):                              │
│  ├── 鉴权失败 → 拒绝执行，记录审计                     │
│  ├── Schema 校验失败 → 拒绝执行，返回错误               │
│  ├── Capability 不存在 → 拒绝执行                       │
│  └── 数据一致性问题 (如库存不足) → 返回业务错误          │
│                                                         │
│  需人工介入 (Human Required):                           │
│  ├── 审批流程被拒绝 → 记录 + 通知                       │
│  ├── 业务规则冲突 → 挂起任务，等待人工裁决               │
│  ├── Checkpoint 恢复失败 → 降级到 New Execution         │
│  └── 连续失败超过阈值 → 熔断，告警                      │
└─────────────────────────────────────────────────────────┘
```

## 10.2 恢复策略

| 场景 | 策略 |
|------|------|
| Executor 宕机 | Kernel 检测心跳超时，将未完成的 Plan 重新调度到其他 Executor（从最新 Checkpoint 恢复） |
| Planner 宕机 | 任务回到队列，被其他 Planner 实例消费 |
| Kernel 主节点切换 | Readiness Probe 检测 + 主从切换，从 PostgreSQL WAL 恢复 State Machine |
| Capability 执行超时 | Executor 发送 Kill Signal，标记 Step 为 Failed，走重试策略 |
| Workflow 部分失败 | 支持 Saga 模式或事务补偿（根据节点类型） |
| 数据库不可用 | 降级到 Redis Cache 只读模式，写操作排队 |

---

# 第十一章：非功能性需求（新增）

## 11.1 SLA 目标

| 场景 | P99 延迟 | 吞吐量 | 可用性 |
|------|---------|--------|-------|
| Chat 对话 | < 3s | 1000 RPM | 99.9% |
| Workflow 执行 | < 30s | 100 RPM | 99.9% |
| Agent 任务 | < 60s | 50 RPM | 99.9% |
| 数据分析查询 | < 10s | 200 RPM | 99.9% |
| 知识库检索 | < 2s | 500 RPM | 99.9% |
| 调度触发 | < 5s | 1000 TPM | 99.99% |

**全平台可用性**：99.95%（每月停机 ≤ 22 分钟）

## 11.2 伸缩策略

| Service | 扩容依据 | 垂直扩展 | 水平扩展 |
|---------|---------|---------|---------|
| Planner | LLM 调用队列深度 ≥ 100 | CPU 升配 | 增加副本 |
| Executor | 执行队列深度 ≥ 200 | CPU + 内存升配 | 增加副本 |
| Scheduler | 触发器数量 ≥ 10,000 | 内存升配 | 增加副本 |
| Kernel | 状态数量 ≥ 100,000 | 内存升配 | 主从 + 读写分离 |
| EventBus | 分区 100MB/s | - | 增加分区 |

---

# 第十二章：错误码体系

## 12.1 全局错误码结构

```
EARP-{Layer}-{Module}-{NNNN}

Layer:
  APP  → Application Layer
  RT   → Runtime Layer
  KRL  → Kernel Layer
  CAP  → Capability Layer
  INT  → Integration Layer

Module:
  PLN  → Planner
  EXE  → Executor
  SCH  → Scheduler
  PVL  → Plan Validation
  CTX  → Context Manager
  STM  → State Machine
  PLY  → Policy Engine
  AUD  → Audit
  CHK  → Checkpoint
  ART  → Artifact
  MEM  → Memory
  CAP  → Capability Registry
  ADR  → Adapter
  MSG  → Message Bus
  SAN  → Sandbox
```

### 错误码示例

| 错误码 | 含义 | HTTP 状态码 | 严重度 | 处理方式 |
|--------|------|-----------|--------|---------|
| `EARP-RT-PLN-0001` | Planner 生成的 Plan 为空 | 500 | Critical | 重试 Planner |
| `EARP-RT-PLN-0002` | Capability Discovery 未找到匹配 | 404 | Warning | 回退到 Rule Planner |
| `EARP-RT-PVL-0001` | Capability 权限校验失败 | 403 | Error | 拒绝执行 |
| `EARP-RT-PVL-0002` | Plan 超出最大深度限制 | 400 | Error | 拒绝执行 |
| `EARP-RT-PVL-0003` | Plan 包含循环调用 | 400 | Critical | 拒绝执行并记录审计 |
| `EARP-RT-EXE-0001` | Capability 执行超时 | 504 | Error | 重试 (Retryable) |
| `EARP-RT-EXE-0002` | Capability 调用被熔断 | 503 | Critical | 暂停 + 告警 |
| `EARP-RT-EXE-0003` | 下游系统返回不可重试错误 | 422 | Error | 记录 + 通知 |
| `EARP-KRL-STM-0001` | 状态机转换非法 (Running→Created) | 500 | Critical | 审计 + 人工介入 |
| `EARP-KRL-CHK-0001` | Checkpoint 恢复失败 | 500 | Warning | 降级为 New Execution |
| `EARP-CAP-ADR-0001` | 适配器连接失败 | 502 | Error | 自动重试 |
| `EARP-CAP-ADR-0002` | 适配器返回数据格式错误 | 500 | Error | 记录 + 告警 |
| `EARP-INT-ADR-0001` | 外部系统认证凭据过期 | 401 | Warning | 通知管理员更新凭证 |
| `EARP-INT-ADR-0002` | MQTT 连接断开 | 503 | Warning | 自动重连 |
| `EARP-INT-SAN-0001` | Sandbox 执行内存超限 | 400 | Critical | 终止 + 审计 |

---

# 第十三章：部署架构

```
                         ┌────────────┐
                         │  Nginx     │
                         │  API GW    │
                         └─────┬──────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
   ┌────────────┐      ┌────────────┐      ┌────────────┐
   │  Planner   │      │  Executor  │      │ Scheduler  │
   │  Svc       │      │  Svc       │      │  Svc       │
   │  (2-10)    │      │  (5-20)    │      │  (2-5)     │
   │  w/ GPU    │      │  CPU only  │      │  CPU only  │
   └──────┬─────┘      └──────┬──────┘      └──────┬──────┘
          │                   │                    │
          └───────────────────┼────────────────────┘
                              │
                              ▼
                     ┌────────────────┐
                     │  Kernel        │
                     │  (3-5 主从)    │
                     └────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
   ┌────────────┐     ┌────────────┐     ┌────────────┐
   │ PostgreSQL │     │   Redis    │     │  Kafka     │
   │ 主从+只读   │     │  哨兵+Cluster│   │  多分区    │
   └────────────┘     └────────────┘     └────────────┘
          │
          ▼
   ┌────────────┐
   │ MinIO/S3  │
   │ Object    │
   │ Storage   │
   └────────────┘
```

---

# 第十四章：Phase 1 可落地的实施路径

## 14.1 Phase 1 范围（1-3 个月）

```
可交付物：
  ┌── 基础运行时
  │   ├── Runtime 骨架（Planner Service + Executor Service 单体）
  │   ├── Kernel Service（Context / State Machine / EventBus 基础版）
  │   ├── Plan Validation Layer（Schema + 权限校验）
  │   └── 无状态部署（2 副本，状态外置）
  │
  ├── 业务能力中心
  │   ├── Capability Registry（CRUD + Embedding 检索）
  │   ├── 3-5 个基础 Capability（查询数据库 / REST 调用）
  │   └── 数据库 Adapter（PostgreSQL / MySQL）
  │
  ├── 多租户
  │   ├── Tenant / Org / User / Role
  │   ├── RBAC 基础权限
  │   └── 行级数据隔离
  │
  ├── Workflow
  │   ├── 可视化 Workflow Studio
  │   ├── 节点类型（Business / HumanApproval / Decision / Notification）
  │   ├── Workflow 服务（创建/更新/运行）
  │   └── 暂停/恢复（审批节点）
  │
  └── 企业知识库
      ├── 多源知识（文档 + 数据库 + API）
      ├── 检索（向量 + 关键词 + 混合）
      └── Indexing Pipeline
```

## 14.2 Phase 1 不做的事项

| 模块 | 原因 |
|------|------|
| LLM Planner | Phase 1 仅用 Rule Planner |
| Multi-Agent Runtime | Phase 3 范围 |
| Ontology 知识图谱 | Phase 3 范围 |
| Semantic Memory | Phase 2 范围 |
| 全量 Adapter 生态 | Phase 2 范围 |
| 事件驱动 Agent | Phase 3 范围 |

## 14.3 Phase 技术栈选型

| 层级 | 选型 |
|------|------|
| 后端框架 | Python FastAPI（API Server）+ Celery（任务） |
| ORM | SQLAlchemy 2.0 + Alembic |
| 数据库 | PostgreSQL |
| 缓存 | Redis |
| 消息队列 | Redis Streams（Phase 1）→ 可迁移 Kafka（Phase 2） |
| 向量数据库 | pgvector（PostgreSQL 插件） |
| 对象存储 | MinIO |
| 沙箱 | Docker SDK（Python 代码执行） |
| LLM SDK | LangChain / LiteLLM（统一 LLM 调用） |
| 可观测 | OpenTelemetry + Prometheus + Grafana |

---

# 附录 A：v1.0 → v2.0 变更记录

| 章节 | 变更类型 | 变更说明 |
|------|---------|---------|
| 1.2 | 新增 | 关键架构决策（ADR-001 ~ ADR-003） |
| 2.1 | 重构 | 六层架构图增加 Runtime 内部三 Service 拆分 + Plan Validation Layer |
| 2.2 | 新增 | 层间通信契约表 |
| 3.1 | 新增 | 部署拓扑图 + 各 Service 扩缩容策略 |
| 3.2 | 重构 | Planner / Executor / Scheduler 明确拆分描述 |
| 3.3 | 新增 | 典型 Task 时序图 |
| 3.4 | 新增 | Plan Validation Layer 详细设计 |
| 4.0 | 重构 | Kernel 模块收敛，消除与 Runtime 重叠 |
| 4.2 | 重构 | Memory 五层简化为两层（Phase 1） |
| 5.0 | 重构 | Capability 增加接口定义、粒度规范、Registry 设计 |
| 6.0 | 新增 | Adapter 接口规范 + MCP 集成策略 |
| 7.0 | 新增 | Workflow/Agent 嵌套防护 + 执行模式矩阵 |
| 8.0 | 重构 | Ontology 给出三阶段演进路径 |
| 9.0 | 新增 | 安全架构专章 |
| 10.0 | 新增 | 错误处理与恢复策略 |
| 11.0 | 新增 | 非功能性需求 SLA |
| 12.0 | 新增 | 错误码体系 |
| 13.0 | 新增 | 部署架构图 |
| 14.0 | 重构 | Phase 1 可落地实施路径 + 技术栈选型 |
