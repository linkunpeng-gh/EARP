# Workflow Specification

## EARP 工作流规范

**文档编号：L2-04-WORKFLOW**
**版本：v1.0**
**定位：L2 — 平台规范。本文定义 Workflow 的契约。Workflow 是 Runtime 的一种 Execution Pattern（预定义 DAG 执行模式），不是 Runtime 本身。**
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md, L2-03-capability/capability-center-specification.md**

---

# 第一章：概述

## 1.1 定位

Workflow 是 Runtime 的**一种执行模式**，不是 Runtime 本身。Workflow 定义"流程描述规范"，执行统一交给 Runtime。

```
错误的认知：Runtime = Workflow 引擎 → Agent/Chat/Scheduled 变成二等公民
正确的认知：Runtime = 统一执行平台，Workflow = 一种执行模式
```

### 明确边界

**Workflow 负责：**
- 流程描述 DSL 定义
- 节点类型注册与配置
- 可视化编辑器的输出规范
- 编译为 Runtime Plan

**Workflow 不负责：**
- ❌ 执行（Execution Runtime 负责）
- ❌ 动态规划（Planner 负责）
- ❌ 决策（Decision Engine 负责）
- ❌ 审批（Policy Engine 负责）

---

# 第二章：Workflow DSL

## 2.1 DSL 结构

```
MUST: Workflow DSL 包含
  - workflow_id:     string    — 全局唯一
  - name:            string    — 名称
  - version:         string    — 版本号
  - nodes:           list[Node]— 节点列表
  - edges:           list[Edge]— 边列表
  - variables:       list      — 变量定义（SHOULD）

MUST: Node 包含
  - node_id:         string    — 唯一标识
  - type:            string    — 节点类型
  - label:           string    — 显示名称（SHOULD）
  - config:          dict      — 节点配置

MUST: Edge 包含
  - edge_id:         string    — 唯一标识
  - source:          string    — 源节点 ID
  - target:          string    — 目标节点 ID
  - condition:       string    — 条件表达式（SHOULD）
```

## 2.2 示例

```yaml
workflow_id: "wf_equipment_fault_handling"
name: "设备故障处理"
version: "1.0.0"
nodes:
  - node_id: "n1"
    type: "trigger"
    config: { trigger_type: "event", event_filter: "alarm_level == 'critical'" }
  - node_id: "n2"
    type: "business"
    config: { capability_id: "query_equipment_status" }
  - node_id: "n3"
    type: "decision"
    config:
      decision_type: "rule"
      rules: ["IF alarm_level='critical' AND status='running' THEN emergency_stop"]
  - node_id: "n4"
    type: "human_approval"
    config: { approver_role: "maintenance_manager", timeout_hours: 4 }
  - node_id: "n5"
    type: "business"
    config: { capability_id: "create_work_order" }
  - node_id: "n6"
    type: "notification"
    config: { channel: "enterprise_wechat", template: "设备 {id} 故障，已创建工单 {order_id}" }

edges:
  - edge_id: "e1"  source: "n1"  target: "n2"
  - edge_id: "e2"  source: "n2"  target: "n3"
  - edge_id: "e3"  source: "n3"  target: "n4"  condition: "selected_branch == 'emergency_stop'"
  - edge_id: "e4"  source: "n3"  target: "n5"  condition: "selected_branch == 'normal'"
  - edge_id: "e5"  source: "n4"  target: "n5"  condition: "approved"
  - edge_id: "e6"  source: "n5"  target: "n6"
```

## 2.3 DSL 格式

```
MUST: 支持 JSON 和 YAML 两种序列化格式
SHOULD: 可视化编辑器导出为 JSON 格式
```

---

# 第三章：节点类型

## 3.1 内建节点

| 类型 | 说明 | 执行方 |
|------|------|--------|
| trigger | 触发节点（流程起点） | Trigger Service |
| business | 调用业务 Capability | Execution Runtime |
| agent | 调用 AI Agent | Execution Runtime |
| decision | 决策节点（Rule/LLM） | Decision Engine |
| human_approval | 人工审批 | Runtime 编排层 |
| llm | LLM 调用 | Execution Runtime |
| code | 自定义脚本 | Execution Runtime |
| notification | 通知发送 | Execution Runtime |
| condition | 条件路由 | Runtime 编排层 |
| loop | 循环节点 | Runtime 编排层 |
| sub_workflow | 子工作流 | Runtime 编排层 |

## 3.2 节点契约

```
MUST: 每个 type 有唯一标识
SHOULD: 节点注册时声明 config 的 JSON Schema
SHOULD: 节点可以声明依赖的 Capability
SHOULD: 节点类型支持插件化注册（SPI）
```

---

# 第四章：编译为 Runtime Plan

## 4.1 编译过程

```
Workflow DSL → Compiler → Runtime Plan（由 Execution Runtime 执行）
```

```
DSL → Plan 映射：
  trigger          → 不编译为 Task（Trigger Service 管理）
  business         → Task(capability_call)
  agent            → Task(capability_call: agent_run)
  decision         → Task(decision)
  human_approval   → Task(wait, type=approval)
  llm              → Task(capability_call: llm_invoke)
  code             → Task(capability_call: code_execute)
  notification     → Task(capability_call: send_notification)
  condition        → 编译为边条件（Edge.condition）
  loop             → 编译为 Task 组 + 循环控制
  sub_workflow     → Task(sub_execution)
```

## 4.2 编译规则

```
MUST: 编译器将 DSL 转化为 Runtime Plan（DAG）
MUST: trigger 不编译为 Task，由 Trigger Service 管理
MUST: 保持 DSL 中的依赖关系（Plan.edges）
SHOULD: 编译器进行 Cycle Detection
SHOULD: 编译时校验引用的 Capability 是否存在
SHOULD: 校验 Node.input 是否符合 Capability Schema
```

---

# 第五章：执行模式

## 5.1 同步

调用者等待完成。适用于短流程、实时交互。

## 5.2 异步

调用者立即获得 execution_id。适用于长流程、审批流程。
执行状态通过 Event 推送。

## 5.3 长流程（Process Instance）

跨小时/天/周。编译为 Process Instance，支持暂停/恢复/超时升级/Checkpoint。

---

# 第六章：闭环机制

Workflow 执行完成后触发 Runtime 的统一反馈闭环。

```
Workflow 完成 → Execution 完成 → Feedback → Evaluation
    │
    ├── Evaluation → Workflow 模板优化建议（SHOULD）
    │   ├── 节点参数调整：可自动优化（如 timeout、retry_policy）
    │   └── 节点增删：需人工确认（涉及流程结构变更）
    │
    ├── Evaluation → Capability Graph 更新（SHOULD）
    │   └── followed_by 关系权重自动调整
    │
    └── Evaluation → Knowledge Center（SHOULD）
        └── 执行模式记录，用于 Planner 参考
```

```
MUST: Workflow 每次执行完成后触发 Runtime 的 Feedback 收集（见 Runtime Spec 第十二章）
SHOULD: Workflow 模板的节点参数优化可自动执行
SHOULD: Workflow 模板的节点增删优化需要人工确认
MUST: 流程治理的完整规则由 Policy Center Specification 定义（参见 P5 Governance）
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Execution | 编译为 Runtime Plan |
| Runtime Spec — Lifecycle | 同步/异步/长流程 |
| Runtime Spec — Checkpoint | 长流程 Checkpoint 恢复 |
| Capability Center Spec | business 节点引用 Capability |
| Decision Engine Spec | decision 节点调用 |
