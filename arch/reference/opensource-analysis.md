# EARP 开源软件参考分析

## 目标

识别能加速 EARP 开发的开源项目，明确参考什么、如何参考、参考风险。

---

# 一、总览：8 个开源项目 → 7 个 EARP 组件映射

| 开源项目 | 映射 EARP 组件 | 参考程度 | 核心价值 |
|:---------|:--------------|:--------:|:---------|
| **Dify** | 全栈架构 + Runtime 服务端 | 深度 | 最接近 EARP 的产品形态——同为多租户 AI 平台，架构高度相似 |
| **LangGraph** | Planner + Runtime 状态机 | 深度 | Agent 编排 + Checkpoint——可直接复用其状态管理模型 |
| **Temporal** | Workflow Engine + Self-Healing | 中 | 企业级工作流引擎——补偿、重试、Saga 模式成熟 |
| **n8n** | Workflow DSL 编辑器 | 中 | 可视化工作流编辑器——节点面板 + 连线操作 |
| **vLLM** | LLM 调用层 | 中 | 高吞吐 LLM 推理——原生多租户 + OpenAI 兼容 API |
| **Haystack** | Knowledge Base (RAG) | 浅 | RAG pipeline——Document→Chunk→Embed→Retrieve |
| **Next.js + shadcn/ui** | Console / Portal 前端 | 中 | 前端技术栈选型参考 |
| **OpenTelemetry** | 可观测性 | 浅 | Specification 对齐（Observation Spec 已引用） |

---

# 二、逐项目深度分析

## 2.1 Dify — 全栈参考（最深）

**GitHub**: langgenius/dify  
**License**: Apache 2.0  
**语言**: Python (Flask) + TypeScript (Next.js)

### 参考什么

| EARP 组件 | Dify 对应 | 参考内容 |
|:----------|:----------|:---------|
| Runtime | `core/workflow/` — Workflow App | DAG 执行引擎、节点调度器、变量解析器 |
| Planner | `core/model_runtime/` — LLM 调用抽象 | 统一 LLM 调用接口——Provider → Model → Token/Usage |
| Knowledge Base | `core/rag/` — RAG 引擎 | Document 分段策略、多检索器、重排序 |
| Plugin System | `core/plugin/` — Plugin 框架 | 插件生命周期、Endpoint 注册、沙箱隔离 |
| 多租户 | `api/` — tenant_id 中间件 | 请求级租户注入模式 |
| Conversation | `core/app/` — 对话引擎 | 多轮对话管理、上下文窗口 |

### 如何参考

**直接学习其架构决策，不直接 fork 代码。** 关键收获：

1. **Workflow 节点的 `run` 模式**：Dify 的每个节点类型（LLM/Code/HTTP/Knowledge）实现统一的 `_run()` → `NodeRunResult`。EARP 的 Capability 调用层可采纳同一模式

2. **Plugin 隔离**：Dify 的 Plugin Daemon 使用 subprocess + gRPC——与 EARP 的 SandboxManager 设计完全一致。可参考其错误边界和超时处理

3. **多租户**：Dify 的 `tenant_id` 在 API 层通过 JWT 注入，在 ORM 层通过 `SAASMultiTenantMixin` 自动过滤——与 EARP 的 BaseTenantEntity + RLS 设计一致

### 风险

- Dify License 从 Apache 2.0 变为限制性 License（v0.6+），不可直接 copy 代码
- 架构复杂度高，不适用于 1-2 人团队

---

## 2.2 LangGraph — Planner + Runtime 状态机（最深）

**GitHub**: langchain-ai/langgraph  
**License**: MIT  
**语言**: Python

### 参考什么

| EARP 组件 | LangGraph 对应 | 参考内容 |
|:----------|:--------------|:---------|
| Runtime 状态机 | `StateGraph` + `Checkpoint` | 状态图的定义和执行——节点/边/条件路由 |
| Planner | `create_react_agent` | Agent 多轮推理循环——think → act → observe |
| Closed-loop | `Command` + `interrupt` | Human-in-the-loop + 动态 RePlan |
| 审计/Checkpoint | `MemorySaver` + SQLite/PostgresSaver | Execution 的 Checkpoint 持久化模型 |

### 如何参考

**直接复用其设计理念**——LangGraph 的状态管理模型是 Python 生态中最成熟的 Agent 编排方案。

关键收获：

1. **StateGraph → EARP Runtime DAG**：LangGraph 的 `add_node → add_edge → add_conditional_edges` 模型可直接对应 EARP 的 Plan DAG 编译。节点类型映射：
   - `langgraph.prebuilt.ToolNode` → EARP Capability 调用节点
   - `langgraph.types.interrupt()` → Workflow `human_approval` 节点

2. **Checkpoint 模型**：LangGraph 的 `CheckpointTuple(config, checkpoint, metadata)` 可直接作为 EARP 的 Execution Checkpoint 数据模型原型

3. **RePlan 模式**：LangGraph 的 `Command(goto=...)` 实现了动态跳转——与 EARP 的 `Failed → Replanning → Planning` 几乎一致

### 风险

- LangGraph 依赖 LangChain 生态，单独提取状态管理核心需裁剪
- 更新频繁（月级），API 可能 breaking

---

## 2.3 Temporal — Workflow Engine（中）

**GitHub**: temporalio/temporal  
**License**: MIT  
**语言**: Go（Server）+ Python/Java/TS（SDK）

### 参考什么

| EARP 组件 | Temporal 对应 | 参考内容 |
|:----------|:-------------|:---------|
| Workflow Engine | Workflow Deterministic Execution | 确定性重放、增量恢复 |
| Self-Healing | Retry Policy + Activity Heartbeat | 指数退避、超时、Fallback |
| Compensation | Saga Pattern | 失败回滚——补偿 Transaction |
| Human-in-Loop | Signal + Query | 外部信号注入工作流 |

### 如何参考

**参考其重试/补偿/Saga 模型**——Temporal 是企业级工作流引擎的黄金标准。

关键收获：

1. **Retry Policy**：`InitialInterval → BackoffCoefficient → MaximumAttempts → MaximumInterval` 可直接作为 EARP 的 `ConnectorRetryConfig` 增强版

2. **补偿模式**：Temporal 的 `Saga.Compensation` 模式——每个 Activity 注册一个 `compensate` 函数。EARP 的 Command 类型 Capability 可采纳此模式

3. **Heartbeat**：长时间运行的 Activity 定时上报进度——可用于 EARP 的 Execution 进度追踪

### 风险

- Temporal Server 是 Go 实现，运维成本高
- 作为基础设施依赖太重，建议只参考模式而非直接依赖

---

## 2.4 n8n — Workflow 可视化编辑器（中）

**GitHub**: n8n-io/n8n  
**License**: Sustainable Use License（限制性）  
**语言**: TypeScript (Vue.js)

### 参考什么

| EARP 组件 | n8n 对应 | 参考内容 |
|:----------|:--------|:---------|
| Workflow 编辑器 | Editor UI + Node Panel | 拖拽节点 → 连线 → 配置面板 |
| Node Registry | `nodes-base/` — 400+ 节点 | 节点注册机制、自定义节点开发流程 |
| DSL Export | `Workflow.export()` | JSON 工作流导出格式 |

### 如何参考

**参考 UI 交互模式**——n8n 的可视化编辑器是生产级开源参考。

关键收获：

1. **节点面板**：左侧节点目录（按类型分组）+ 拖放到画布 → 自动连线
2. **配置面板**：点击节点弹出配置表单（JSON Schema 驱动）→ 实时校验
3. **导出格式**：n8n 的工作流 JSON 格式可作为 EARP Workflow DSL 的参考——但 EARP 已有自己的 DSL（YAML/JSON）

### 风险

- License 不允许商业使用（Sustainable Use License）
- 前端技术栈基于 Vue.js + Express——与 EARP 可能不一致

---

## 2.5 vLLM — LLM 调用层（中）

**GitHub**: vllm-project/vllm  
**License**: Apache 2.0  
**语言**: Python/C++

### 参考什么

| EARP 组件 | vLLM 对应 | 参考内容 |
|:----------|:---------|:---------|
| LLM Invocation | OpenAI-compatible API Server | `/v1/chat/completions` 端点——EARP Connector 的 LLM provider |
| Multi-tenancy | `--enable-prefix-caching` | 多租户 prefix cache 隔离 |
| Token 计量 | `UsageInfo` (prompt_tokens/completion_tokens) | 每租户 Token 用量追踪 |

### 如何参考

**作为 LLM 推理后端**——vLLM 提供 OpenAI 兼容的 HTTP API，可直接用 EARP 的 REST Connector 对接。

关键收获：

1. **部署模型**：vLLM 作为独立服务（K8s Deployment），EARP 通过 Connector → gRPC/HTTP 调用。已在部署视图中预留

2. **多租户隔离**：vLLM 的 `--enable-prefix-caching` + per-tenant API key → 映射到 EARP 的 LLM API Key per-tenant 需求

3. **Token 计量**：vLLM 返回的 `usage` 对象可直接写入 EARP 的 AuditLog.detail（LLM Prompt+Response 30 天保留）

### 风险

- vLLM 需要 GPU（本地部署时），增加部署复杂度
- 作为外部依赖，服务可用性影响 Planner

---

## 2.6 Haystack — Knowledge Base RAG（浅）

**GitHub**: deepset-ai/haystack  
**License**: Apache 2.0  
**语言**: Python

### 参考什么

- `Document` / `Chunk` 数据模型（与 EARP 数据视图中的 Knowledge 域完全一致）
- `DocumentStore` + `Retriever` 的抽象层
- RAG pipeline 的正交设计：`Document → Splitter → Embedder → Store → Retriever`

### 风险

- Haystack 本身较重，建议只参考其数据模型和 pipeline 设计——不引入为依赖

---

## 2.7 前端技术栈 — Next.js + shadcn/ui（中）

**对齐**: Dify 前端技术栈

| 组件 | Dify 选型 | EARP 建议选型 | 理由 |
|:-----|:---------|:-------------|:-----|
| 框架 | Next.js 14 (App Router) | Next.js 14+ | React 生态最成熟的 SSR 框架 |
| UI 组件 | 自研 | **shadcn/ui** | 可定制、源码级复制、Radix 无样式组件 |
| 状态管理 | Zustand | Zustand | 轻量、TypeScript 友好 |
| 数据查询 | SWR | TanStack Query | 缓存策略更强 |
| 图表 | ECharts | ECharts / Recharts | 管理控制台看板需要 |

**参考参考**：Dify 的 `web/` 目录结构——pages layout、组件复用模式、API 调用封装。

---

## 2.8 OpenTelemetry — 可观测性对齐（浅）

EARP 的 Observation Spec 已引用 OTel。非开源参考——而是规范对齐。

---

# 三、收益排序

| 优先级 | 项目 | EARP 组件 | 节省时间估计 | 参考方式 |
|:------:|:-----|:----------|:----------:|:---------|
| **1** | LangGraph | Planner + Runtime 状态机 | 2-3 周 | 复用状态管理模型 + Checkpoint 协议 |
| **2** | Dify | Runtime 服务端全栈 | 3-4 周 | 学习架构决策 + 复用模式 |
| **3** | Temporal | Workflow 重试/补偿 | 1 周 | 参考 Retry Policy + Saga 模式 |
| **4** | vLLM | LLM 调用层 | 0（接入） | 直接作为推理后端对接 |
| **5** | n8n | Workflow 编辑器 | 2 周 | 参考 UI 交互模式 |
| **6** | Haystack | Knowledge Base 模型 | 3 天 | 参考数据模型 |
| **7** | Next.js + shadcn/ui | 前端 | 1 周 | 技术栈决策参考 |

**总计估算节省：约 8-10 周开发时间。**

---

# 四、参考原则

| 原则 | 说明 |
|:-----|:-----|
| **学架构、不抄代码** | 参考开源项目的设计思路和接口定义——而非 copy-paste |
| **优选 MIT/Apache 2.0 License** | Dify v0.6+ 和 n8n 的 License 有商业限制——不可直接采纳代码 |
| **保持 EARP 架构独立性** | L0-L3 四层治理 + 六边形架构是 EARP 的核心护城河——开源参考不能违背 |
| **对接而非法 fork** | vLLM 作为独立服务对接，LangGraph 概念复用而非依赖 |
| **SDK 先行、服务端后行** | 当前阶段优先完善 SDK 和规范，服务端实现阶段再引入参考 |
