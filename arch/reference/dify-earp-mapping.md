# Dify → EARP 全栈对照分析

## 目标

对 Dify v1.x 代码库（`/Users/linkunpeng/code/dify-code`）做系统级分析，识别 EARP 可复用的架构模式、模块设计和实现参考。

**License**: Dify v0.6+ 使用限制性 License——不直接 copy 代码。学架构、学模式。

---

# 一、代码库结构

```
dify/
├── api/                          # 后端 (Python Flask + SQLAlchemy)
│   ├── core/                     # 核心引擎
│   │   ├── workflow/            # 工作流引擎 (934 行 node_runtime)
│   │   ├── app/                 # 应用编排 (Agent/Chat/Workflow/Completion)
│   │   ├── model_runtime/       # LLM 调用抽象层
│   │   ├── plugin/              # Plugin 系统 (981 行 plugin_service)
│   │   ├── agent/               # Agent Runner (CoT/FC/Base)
│   │   ├── rag/                 # RAG pipeline
│   │   ├── tools/               # Tool 引擎
│   │   └── memory/              # 对话记忆
│   ├── models/                  # SQLAlchemy 模型 (含 Tenant/Account/TenantAccountJoin)
│   ├── services/                # 业务服务层
│   └── controllers/             # REST 路由 (console/web/service_api/trigger)
├── web/                         # 前端 (Next.js + TypeScript)
└── sdks/                        # 多语言 SDK
```

---

# 二、EARP 组件映射总表

| EARP 组件 | Dify 对应模块 | 映射度 | 可直接参考的内容 |
|:----------|:-------------|:-----:|:-----|
| Runtime | `core/workflow/node_runtime.py` | **80%** | 节点执行引擎——`_run_node()` 模式、错误处理、超时管理 |
| Planner | `core/app/` + `core/agent/` | **70%** | Agent Runner 架构（Base→CoT→FC）、Plan 生成模式 |
| Workflow Engine | `core/workflow/nodes/` | **85%** | 节点类型体系（8 种）+ `node_factory` 注册模式 |
| Capability Registry | `core/tools/` | **75%** | Tool 注册/发现/执行——与 EARP Capability 高度对应 |
| Plugin System | `core/plugin/` | **90%** | **最可复用**——Plugin Daemon + gRPC + 沙箱隔离 |
| 多租户 | `models/account.py` (Tenant/Account) | **85%** | 租户注入模式——`current_tenant_id` + `TenantAccountJoin` |
| LLM 调用层 | `core/model_runtime/` | **70%** | Provider→Model 抽象、Token 用量追踪 |
| Knowledge Base | `core/rag/` | **80%** | RAG pipeline 正交设计 |
| Conversation | `core/memory/` | **60%** | 对话上下文管理 |
| Audit | `core/callback_handler/` | **50%** | 回调处理器（执行事件记录） |
| Console 前端 | `web/` (Next.js) | **60%** | 前端技术栈 + 组件组织 |

---

# 三、逐模块深度分析

## 3.1 Workflow Engine — node_runtime.py (934 行)

**这是 Dify 最核心的执行引擎，也是 EARP Runtime 的最直接参考。**

### Dify 架构

```
node_runtime.py
├── NodeRunResult          # 节点执行结果
├── NodeRuntime            # 节点运行时基类
├── ToolNodeRuntime        # Tool 节点执行 (→ EARP Capability Call)
├── LLMNodeRuntime         # LLM 节点执行 (→ EARP Planner)
├── HumanInputNodeRuntime  # 人工审批节点 (→ EARP human_approval)
├── KnowledgeRetrievalNode # 知识检索节点 (→ EARP Knowledge)
└── CodeNodeRuntime        # 代码节点
```

### EARP 映射

```python
# Dify 节点执行模式 — 可直接参考
class NodeRuntime:
    def _run_node(self, node_data: NodeData) -> NodeRunResult:
        """每个节点类型实现自己的 _run_node"""
        try:
            result = self._do_run(node_data)       # 执行
            self._handle_success(result)             # 成功处理
        except RetriableError:                      # 可重试
            self._handle_retry()
        except FatalError:                          # 不可恢复
            self._handle_failure()

# → EARP Step 执行模式
class CapabilityStep:
    """参考 Dify ToolNodeRuntime 的 try/retry/failure 分支"""
    def execute(self, cap_call: CapabilityCall) -> StepResult:
        ...
```

**关键学习点：**

1. **统一的 `NodeRunResult` 类型** — 所有节点返回同一种结果类型。EARP 的 Step 层应统一 `StepResult(status, output, error, usage)`

2. **错误分类** — `RetriableError` vs `FatalError`。EARP 的 `ConnectorRetryConfig` 已区分 retryable/non-retryable 错误，但缺少明确的错误类型体系

3. **Human Input 暂停机制** — `HumanInputNodeRuntime` 在需要审批时返回 `PAUSED` 状态，由 RunLoop 检查并挂起。EARP 的 Workflow human_approval 节点可直接复用此模式

## 3.2 Plugin System — plugin_service.py (981 行)

**Dify 的 Plugin 系统是 EARP 的第 4 个安全 Phase（沙箱）的最直接参考——两者都使用 subprocess + gRPC 隔离。**

### Dify 架构

```
core/plugin/
├── plugin_service.py          # 插件生命周期管理 (install/uninstall/upgrade/list)
├── impl/
│   ├── plugin.py              # PluginInstaller (subprocess + gRPC 调用)
│   ├── endpoint.py            # PluginEndpointClient (HTTP endpoint)
│   ├── model.py               # PluginModelClient (LLM model provider)
│   ├── tool.py                # PluginToolClient (Tool execution)
│   ├── agent.py               # PluginAgentClient
│   ├── exc.py                 # PluginDaemonClientSideError
│   └── debugging.py           # PluginDebuggingClient
├── entities/
│   ├── plugin.py              # PluginDeclaration, PluginEntity
│   └── plugin_daemon.py       # PluginInstallTask, PluginVerification
└── utils/
```

### EARP 映射

| Dify | EARP 对应 | 映射度 |
|:-----|:----------|:-----:|
| `PluginInstaller` (subprocess + gRPC) | `SandboxManager` (subprocess + JSON) | **85%** |
| `PluginEntity` (id/version/category/permissions) | `Plugin` 基类 (name/version/permissions) | **90%** |
| `PluginDeclaration` (manifest) | `Plugin` dataclass | **80%** |
| `PluginDaemonClientSideError` | `SandboxExecutionError` | **90%** |
| gRPC 通信协议 | EARP 当前用 JSON (stdin/stdout)，Phase 2 可选 gRPC | **60%** |
| Plugin marketplace (远程下载) | EARP 无此需求（企业内部插件） | **0%** |

**关键学习点：**

1. **Plugin 安装流程** — Dify 的 install 流程：`download → verify → unpack → register → health_check`。EARP 的 PluginManager 目前只有 `load/unload`，缺少 verify 和 health_check 阶段

2. **租户范围的 plugin 缓存** — `plugin_service.py` 的 docstring 明确："cache mutations for plugin-owned provider metadata stay **tenant-scoped**"。EARP 的 PluginManager 应同样支持 tenant_id 隔离

3. **Plugin 声明 vs 安装** — `PluginDeclaration`（元数据）和 `PluginInstallation`（安装状态）分离。EARP 的 Plugin 基类目前混合了两者

## 3.3 多租户模型 — models/account.py

### Dify 架构

```python
class Account(db.Model):
    """用户账号 — 通过 TenantAccountJoin 关联多个租户"""
    _current_tenant: Tenant | None  # 会话级租户上下文

    @property
    def current_tenant_id(self) -> str | None:
        return self._current_tenant.id if self._current_tenant else None

class Tenant(db.Model):
    """租户 — 独立工作空间"""
    id: str    # UUID
    name: str
    plan: str  # 订阅计划

class TenantAccountJoin(db.Model):
    """用户-租户关联表"""
    tenant_id: str
    account_id: str
    role: TenantAccountRole  # owner/admin/editor/dataset_operator
```

### EARP 映射

| Dify | EARP | 差异 |
|:-----|:-----|:-----|
| `Account._current_tenant` | `RuntimeContext.tenant_id` | EARP 从 JWT 注入，Dify 从 DB Session 注入 |
| `TenantAccountJoin` | `TenantAccountJoin` (数据视图已定义) | 一致 |
| `TenantAccountRole` | `Role` (数据视图已定义) | EARP 有更细粒度的 RBAC |
| `Tenant.plan` (订阅) | 未定义 | EARP 缺少资源配额模型 |

**关键学习点：**

1. **租户上下文的 session 级注入** — Dify 在用户登录后通过 `Account._current_tenant` setter 加载租户，后续所有 DB 查询通过 `current_tenant_id` 过滤。EARP 的 RuntimeContext 已有类似机制（从 JWT → Session → Execution 链）

2. **TenantAccountJoin 表** — 多对多关系通过独立的 Join 表管理。EARP 数据视图已定义此表，但 SDK 层未实现

3. **租户切换** — Dify 支持用户在多租户间切换（`set_tenant_id()`）。EARP 的 Phase 2+ 需要此能力

## 3.4 Agent Runner — core/agent/

### Dify 架构

```
core/agent/
├── base_agent_runner.py          # 抽象基类
├── cot_agent_runner.py           # Chain-of-Thought Agent
├── cot_chat_agent_runner.py      # Chat 场景 CoT
├── fc_agent_runner.py            # Function Calling Agent
├── plugin_entities.py            # Plugin Agent 实体
├── entities.py                   # AgentEntity, AgentToolEntity
└── output_parser/                # LLM 输出解析器
```

### EARP 映射

| Dify Agent | EARP Planner | 关系 |
|:-----------|:------------|:-----|
| `base_agent_runner.run()` | `Planner.plan(intent)` | 同为"输入意图 → 输出执行方案" |
| `cot_agent_runner` (step-by-step) | RePlan 模式 (Failed→Replanning→Planning) | CoT 是单 Agent 内闭环，RePlan 是跨 Execution 闭环 |
| `fc_agent_runner` (function calling) | Capability 调用（CapabilityCall） | FC 的 tool_call → EARP 的 capability_call |
| `agent_tool_entities` | Capability Registry 中的 Capability 定义 | 对应 |

**关键学习点：**

1. **Agent 回调链** — Dify 的 `base_agent_runner` 使用 callback handler 模式记录每次 tool_call 的输入/输出。EARP 的 Audit 通道应采纳此模式——在 Capability 调用前后自动触发审计事件

2. **Agent Strategy 模式** — CoT/FC 是两种不同的 Plan 生成策略。EARP 的 Planner 当前未区分策略，扩展性预留

## 3.5 RAG Pipeline — core/rag/

### Dify 架构

```
core/rag/
├── datasource/           # 数据源 (Notion/Web/File)
├── extractor/            # 文本提取
├── cleaner/              # 清洗
├── splitter/             # 分块策略
├── embedding/            # 向量化
├── index_processor/      # 索引管理
├── docstore/             # 文档存储
├── retriever/            # 多检索器 (vector/keyword/hybrid)
├── data_post_processor/  # 检索后处理 (rerank)
└── models/               # Document/Chunk 数据模型
```

### EARP 映射

| Dify RAG | EARP Knowledge Base | 映射度 |
|:---------|:-------------------|:-----:|
| `models/dataset.py` Document/Segment | 数据视图 KnowledgeBase→Document→Chunk | **90%** |
| Pipeline 正交设计 | EARP Knowledge Spec (未写) | **85%** |
| 多检索器 (vector/keyword/hybrid) | EARP 当前只有 pgvector | **50%** |

**关键学习点：**

1. **Document→Chunk 模型** — Dify 的 `Document.segments[*]` 对应 EARP 数据视图的 `Document→Chunk` 1:N 关系。可直接参考字段定义

2. **Retriever 抽象** — Dify 支持 vector/keyword/hybrid 三种检索器。EARP Knowledge Spec 应预留此扩展点

---

# 四、EARP 不可复用的 Dify 设计

| Dify 特性 | 不可复用原因 | EARP 替代方案 |
|:----------|:------------|:------------|
| Flask + SQLAlchemy | EARP 未选择后端框架 | EARP SDK 是 Python 库，不绑定 web 框架 |
| `db.session` 全局变量 | 与 EARP 的 multi-package SDK 冲突 | EARP 通过 `RuntimeClient` 统一入口 |
| GraphQL API (console) | EARP 使用 gRPC 内部通信 | 已在部署视图中定义 |
| `extensions/` 模块（Flask 扩展） | 框架绑定 | EARP 用独立 Python 包 |
| 内置 LLM Provider (30+) | EARP 通过 Connector 对接外部 LLM | 更灵活的 connector 模式 |
| 复杂前端 (Next.js 14) | EARP 前端未开始 | 参考组件布局，不直接复用 |

---

# 五、Dify License 注意事项

Dify v0.6+ 使用 **Dify Open Source License**（基于 Apache 2.0 增加限制条款）：
- ✅ 学习架构、参考设计模式 — 合法
- ✅ 参考 API 接口定义 — 合法
- ❌ 直接 copy 代码片段 — 违反 License
- ❌ Fork Dify 作为 EARP 子模块 — 违反 License

**实践原则：** 在 EARP 代码中写注释标明参考来源（如 `# Inspired by Dify core/workflow/node_runtime.py`），但代码实现由 EARP 团队独立完成。

---

# 六、实施建议

| 阶段 | 内容 | 节省时间 | 参考模块 |
|:----:|:-----|:------:|:---------|
| **1** | Capability SDK — 统一 `CapabilityResult` 类型 (参考 NodeRunResult) | 3 天 | `core/workflow/node_runtime.py` |
| **2** | Plugin Manager — 完善 install/verify/health_check 流程 | 1 周 | `core/plugin/plugin_service.py` |
| **3** | Tenant 上下文注入 — SDK 侧 `set_tenant_id()` 支持 | 3 天 | `models/account.py` (Account._current_tenant) |
| **4** | Knowledge Base 数据模型 — 参考 Document/Chunk 字段 | 3 天 | `core/rag/models/` |
| **5** | Agent 回调链 — Capability 调用前后自动审计 | 2 天 | `core/agent/base_agent_runner.py` |
