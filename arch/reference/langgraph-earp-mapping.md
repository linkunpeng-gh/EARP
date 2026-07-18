# LangGraph → EARP Runtime 状态管理对照分析

## 目标

将 LangGraph 的状态管理模型映射到 EARP Runtime Spec v1.3，识别可直接复用的设计模式、数据模型和实现参考。

**参考对象**: LangGraph v0.3+ (`langgraph.graph.StateGraph`, `langgraph.checkpoint`)  
**License**: MIT — 可复用概念和模式

> **v1.1 变更（2026-07-18）**：基于本地源码 `~/code/langchain/langgraph-main/` 实地勘察，将 v1.0 的概念级结论升级为代码级验证：§2.5 修正为 PostgresSaver 真实 3 表 DDL（新增 checkpoint_blobs 分离设计与 task_path 列）；新增 §2.6 Durability 三档模式与 Pregel 引擎模块清单。LangChain 框架本体分析另见 langchain-earp-mapping.md。

---

# 一、概念映射总表

| LangGraph 概念 | EARP 对应 | 映射度 | 关键差异 |
|:--------------|:----------|:-----:|:---------|
| `StateGraph` | Runtime Plan DAG | **90%** | LangGraph 是通用图，EARP 是业务能力编排图 |
| `Node` | Step（capability_call/wait/notify 等） | **85%** | LangGraph 节点是 Python 函数，EARP 节点是 Capability 调用 |
| `Edge` | Plan Edge（source→target+condition） | **95%** | 一致 |
| `ConditionalEdge` | Decision Step（Rule/LLM 决策分支） | **90%** | 一致 |
| `State` (TypedDict) | Execution Context | **80%** | LangGraph 用 TypedDict，EARP 用 dict+JSON Schema |
| `Checkpoint` | Execution Checkpoint | **95%** | **核心可复用点** |
| `CheckpointTuple` | EARP Checkpoint 数据模型 | **90%** | 字段映射见 §2.2 |
| `Command(goto=...)` | RePlan（Failed→Replanning→Planning） | **80%** | EARP 用 Planner.replan() 而非 Command |
| `interrupt()` | Workflow human_approval → paused | **85%** | 一致 |
| `MemorySaver` | EARP Checkpoint Store (PG) | **70%** | LangGraph 提供参考实现 |
| `SqliteSaver/PostgresSaver` | EARP Checkpoint 持久化 | **85%** | 可直接参考表结构 |

---

# 二、核心参考区域

## 2.1 Checkpoint 数据模型（95% 可复用）

LangGraph 的 Checkpoint 模型是当前 Python 生态中最成熟的 Agent 状态快照方案。

### LangGraph 模型

```python
class CheckpointTuple(NamedTuple):
    config: RunnableConfig       # {"configurable": {"thread_id": ..., "checkpoint_ns": ...}}
    checkpoint: Checkpoint        # 核心快照
    metadata: CheckpointMetadata  # {"source": "loop", "step": 3, "writes": {...}}
    parent_config: RunnableConfig | None  # 父 Checkpoint（链式追溯）
    pending_writes: list[PendingWrite]    # 未提交的写入
```

```python
class Checkpoint(TypedDict):
    v: int                        # 版本号
    id: str                       # checkpoint_id（UUID）
    ts: str                       # ISO 8601 timestamp
    channel_values: dict[str, Any]  # 状态快照（key→value）
    channel_versions: dict[str, int]  # 每个 channel 的版本号
    versions_seen: dict[str, dict[str, int]]  # 节点间共享状态的版本追踪
    pending_sends: list[Any]      # 待发送的消息
```

### EARP 映射

```python
# EARP Checkpoint 数据模型（参考 LangGraph）
class EarpCheckpoint:
    checkpoint_id: str            # UUID ← Checkpoint.id
    execution_id: str             # 所属 Execution ← config["thread_id"]
    session_id: str               # 所属 Session
    seq: int                      # 序号 ← metadata["step"]
    timestamp: str                # ISO 8601 ← Checkpoint.ts
    state: dict[str, Any]         # 执行快照 ← Checkpoint.channel_values
    step_states: dict[str, str]   # 每个 Step 的状态 (step_id→status)
    pending_compensations: list[str]  # 待执行的补偿动作
    parent_checkpoint_id: str | None  # 上一个 Checkpoint ← parent_config
```

**关键学习点：**

1. **版本追踪** (`channel_versions`) — LangGraph 为每个 channel 追踪版本号，用于并发冲突检测。EARP 的并行 Step 执行场景（多个 capability_call 同时执行）可采纳此机制

2. **链式追溯** (`parent_config`) — 每个 Checkpoint 指向前一个 Checkpoint，形成可追溯链。EARP 的 RePlan（新 Execution 继承 session_id）可借此关联原始 Execution 和 RePlan Execution

3. **Pending writes** — 在 Checkpoint 点未完成的写操作被保留。EARP 的 `在途并行 Step 保持等待` 行为对应此概念

## 2.2 StateGraph → Plan DAG 编译

### LangGraph 代码示例

```python
from langgraph.graph import StateGraph, END

class AgentState(TypedDict):
    messages: list
    next_step: str

graph = StateGraph(AgentState)

# 添加节点
graph.add_node("think", think_node)       # LLM 推理
graph.add_node("tool_execute", tool_node)  # 工具调用
graph.add_node("human_approval", human_node)

# 添加边
graph.add_edge("think", "tool_execute")
graph.add_conditional_edges("tool_execute", decide_next, {
    "continue": "think",
    "approve": "human_approval",
    "end": END
})
```

### EARP 编译映射

```yaml
# EARP Workflow DSL → 编译为 Plan DAG
workflow_id: "wf_equipment_fault"
nodes:
  - node_id: "n1"  type: "agent"       # ← LangGraph "think" node
    config: { capability_id: "diagnose_equipment" }
  - node_id: "n2"  type: "business"    # ← LangGraph "tool_execute" node
    config: { capability_id: "query_equipment_status" }
  - node_id: "n3"  type: "decision"    # ← LangGraph conditional_edges
    config: { decision_type: "rule" }
  - node_id: "n4"  type: "human_approval"  # ← LangGraph interrupt() node
    config: { approver_role: "manager" }

edges:
  - { source: "n1", target: "n2" }
  - { source: "n2", target: "n3" }
  - { source: "n3", target: "n4", condition: "selected_branch=='emergency'" }
```

**关键差异：** LangGraph 节点是 Python 函数——在同进程中执行。EARP 的节点是**异步 Capability 调用**——通过 Connector 调用外部系统。这意味着 EARP 的节点间通信必须经过 Runtime 编排层，不能像 LangGraph 一样直接函数调用。

## 2.3 State → Execution Context

LangGraph 的 `State` 是整个图的共享状态，通过 reducer 函数实现增量更新。EARP 的 `Execution Context` 有类似需求但场景不同。

| 维度 | LangGraph | EARP |
|:-----|:---------|:-----|
| 状态定义 | `TypedDict` + reducer | `dict` + JSON Schema |
| 增量更新 | `add_messages` reducer（追加而非替换） | Step 的 input/output 追加到 context |
| 状态隔离 | 每 thread 独立 state | 每 Execution 独立 context + tenant_id 隔离 |
| 状态持久化 | Checkpoint 自动保存 state | Checkpoint 保存 context 快照 |

**可复用模式：** `add_messages` reducer — EARP 的 Execution Context 在多 Step 执行时需要追加每个 Step 的 output 而非覆盖。LangGraph 的 reducer 模式可直接复用。

## 2.4 Human-in-the-Loop → Workflow human_approval

LangGraph 的 `interrupt()` 模型与 EARP Workflow 的暂停/审批机制高度对应。

| LangGraph | EARP Workflow |
|:---------|:--------------|
| `interrupt("需要人工审批")` | `human_approval` 节点 → `paused` 状态 |
| `Command(resume=value)` | 审批通过 → `approved` → 继续执行 |
| 中断时 Save Checkpoint | §7.2 MUST: paused → Checkpoint |
| 中断时在途 Task 保持 | §7.2 MUST: 在途 Task 保持等待 |

**实现参考：** LangGraph 的 `interrupt()` 内部实现：
1. 抛出 `GraphInterrupt` 异常 → 被 Runner 捕获
2. 当前状态写入 Checkpoint
3. 等待外部 `Command(resume=value)` 调用
4. 从 Checkpoint 恢复状态 → 继续执行

EARP 可复用此模式——将 `GraphInterrupt` 替换为 `WorkflowPaused` 事件发布到 EventBus。

## 2.5 Checkpoint 持久化参考

LangGraph 提供了两种 Checkpoint 持久化实现，可直接作为 EARP 的参考。

### SqliteSaver 表结构参考

```sql
-- LangGraph SqliteSaver 核心表
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,         -- 'checkpoint' | 'pending'
    checkpoint BLOB,   -- 序列化的 Checkpoint 对象
    metadata BLOB,     -- 序列化的 CheckpointMetadata
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,         -- 写入类型
    value BLOB,        -- 写入值
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
```

### EARP PostgresSaver 映射

```sql
-- EARP Checkpoint 表（参考 LangGraph 设计）
CREATE TABLE earp_checkpoints (
    checkpoint_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES executions(id),
    session_id UUID NOT NULL,
    tenant_id UUID NOT NULL,           -- Multi-Tenant Spec
    seq INTEGER NOT NULL,              -- 序号（从 1 递增）
    state JSONB NOT NULL,              -- 执行状态快照
    step_states JSONB NOT NULL,        -- 每个 Step 的状态
    pending_writes JSONB,              -- 未提交写入
    parent_checkpoint_id UUID,         -- 链式追溯
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (execution_id, seq)
);

CREATE INDEX idx_checkpoints_execution ON earp_checkpoints(execution_id, seq);
```

**关键参考：** LangGraph 的 `thread_id + checkpoint_ns + checkpoint_id` 复合主键设计解决了多轮对话中的 Checkpoint 命名空间问题——EARP 的 Execution 可能在一次 Session 中多次 RePlan，需要类似的命名空间隔离。

### v1.1 实码勘察修正：PostgresSaver 真实 DDL 是 3 表而非 2 表

源码 `libs/checkpoint-postgres/langgraph/checkpoint/postgres/base.py` MIGRATIONS 实测：

```sql
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,           -- 快照主体（小字段）
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE TABLE checkpoint_blobs (          -- ⭐ v1.0 分析遗漏的表
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,                          -- 大值（channel_values）按版本单独存储
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);
CREATE TABLE checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',  -- 后补迁移：子图/嵌套任务路径
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
-- 三表均有 thread_id 单列索引（CREATE INDEX CONCURRENTLY）
```

**对 EARP DDL 的修正结论：**
1. **大小值分离**——checkpoint 行只存小快照（JSONB），大的 channel 值（LLM 上下文、中间产物）拆到 blobs 表按 `(channel, version)` 存，同版本值不随每个 checkpoint 重复落盘。EARP 的 earp_checkpoints 表设计（本文 §2.5 EARP 版）应同样把 `state` 拆为"小快照 JSONB + 大值 BYTEA/S3 引用"，否则多步 Execution 的 checkpoint 会线性放大存储。
2. **task_path 列**——嵌套子图执行的任务寻址（对应 EARP 嵌套 Workflow / 子 Execution 场景），M5 前在 checkpoint_writes 等价表预留。
3. **迁移即代码**——MIGRATIONS 是带版本号的 SQL 列表 + checkpoint_migrations 版本表，与 EARP 的 Alembic 策略一致，无需变更。

## 2.6 Durability 三档与 Pregel 引擎（v1.1 新增）

源码 `langgraph/types.py`: `Durability = Literal["sync", "async", "exit"]`：

| 档位 | 语义 | EARP 对应场景 |
|:-----|:-----|:--------------|
| sync | 每步先落 checkpoint 再继续（最强，最慢） | Command 类 Capability / Saga 步骤（一致性优先） |
| async | 执行下一步的同时异步落盘（默认） | Query 为主的常规 Execution |
| exit | 仅在图退出/中断时落盘（最快） | 短平快的纯 Query 会话 |

**结论**：EARP Runtime Spec 的 Checkpoint 创建点（Step 完成/Waiting/Paused）可增加 per-execution 的持久化档位参数（默认 async），Command 步骤强制 sync——把"一致性 vs 吞吐"的取舍显式化。建议 M5 L3 设计采纳。

执行引擎实体为 Pregel 模块（`langgraph/pregel/`）：`_loop`（BSP 主循环）/ `_algo`（plan-execute-update 三阶段）/ `_runner`/`_executor`（任务执行）/ `_retry`（步级重试）/ `_checkpoint`（落盘）/ `protocol.py`。印证 EARP Orchestrator 的"计划→执行→更新状态→落 checkpoint"循环骨架；步级重试内建于引擎层而非节点层，与 M5 Retry/Timeout Manager 的位置一致。

---

# 三、不可复用的部分

| LangGraph 特性 | 不可复用原因 | EARP 替代方案 |
|:--------------|:------------|:------------|
| 节点作为 Python 函数 | EARP 节点是异步 Capability 调用 | 通过 Runtime → Capability → Connector 异步链 |
| `RunnableConfig` 全局配置 | 与 EARP 的 multi-tenant Auth 冲突 | EARP 使用 RuntimeContext（tenant_id + user_id + session_id） |
| `MemorySaver` 纯内存 | 不适用于企业级持久化 | EARP Checkpoint Store 基于 PostgreSQL |
| LangChain 生态依赖 | 避免 vendor lock-in | EARP 独立实现 Checkpoint 协议 |
| `StreamMode` 流式输出 | EARP 的流式输出通过 WebSocket Gateway | 不需要适配 LangGraph 的 streaming API |

---

# 四、实施建议

## 4.1 Phase 1：Checkpoint 协议（1 周）

**优先级最高** — 直接复用 LangGraph 的 Checkpoint 数据模型。

1. 定义 `EarpCheckpoint` 类（参考 §2.1 映射）
2. 实现 PostgresSaver（参考 §2.5 表结构）
3. 集成到 Runtime Spec 的 Checkpoint 创建点（Step 完成/Waiting/Paused）

**为什么 P0：** Checkpoint 是 RePlan、Human-in-Loop、Self-Healing 的基础设施——所有闭环能力都依赖它。

## 4.2 Phase 2：reducer 模式（3 天）

复用 LangGraph 的 `add_messages` reducer 思路——实现 Execution Context 的增量更新机制。

## 4.3 Phase 3：interrupt 模式（3 天）

复用 LangGraph 的 `interrupt()` 内部实现——将 Workflow 的暂停/恢复标准化为异常驱动的 Checkpoint + Resume 流程。

## 4.4 Phase 4：正式迁移到 LangGraph（可选）

如果未来 Runtime 服务端的核心编排逻辑变得足够复杂（3+ 嵌套 Workflow、10+ 并行 Step），可以考虑直接用 LangGraph 作为 Runtime 的状态引擎——但这引入 LangChain 生态依赖，需要独立评估。
