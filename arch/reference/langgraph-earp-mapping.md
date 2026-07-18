# LangGraph → EARP Runtime 状态管理对照分析

## 目标

将 LangGraph 的状态管理模型映射到 EARP Runtime Spec v1.3，识别可直接复用的设计模式、数据模型和实现参考。

**参考对象**: LangGraph v0.3+ (`langgraph.graph.StateGraph`, `langgraph.checkpoint`)  
**License**: MIT — 可复用概念和模式

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
