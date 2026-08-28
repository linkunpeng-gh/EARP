# Planner Runtime — L3 实现设计

**文档编号：DESIGN-ECMC-PLANNER-RUNTIME-L3**
**版本：v0.1（draft）**
**日期：2026-08-28**

> 上游：`arch/L2/02-reasoning/planner-specification.md`（v1.1，L2 契约）、`arch/design/2026-08-28-planning-blueprint-l3-design.md`（v0.3 基线，Blueprint 元模型）、`arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21，§4.4 Cognitive Service Contract）
> 定位：Planner 如何**解释 Blueprint**、如何**生成 Plan**（Blueprint → Plan 的解释执行层）。
> 技术栈：FastAPI + SQLAlchemy 2 async + PostgreSQL 16，复用现有 planner 模块（`earp_server/planner/`）。

---

# 一、设计原则

```
P1  Blueprint 是输入，Plan 是输出——Planner 不修改 Blueprint（不可变输入）
P2  Blueprint 定义"业务方法"，Plan 定义"执行任务"——解释 = 投影 + 实例化
P3  规划约束（blueprint_constraints）影响规划决策，但不产生新业务逻辑
P4  失败降级：Blueprint 不可用 → 回退直接模型匹配 + 运行时推理
P5  可追溯：Plan 的每个 Task 可回溯到 Blueprint 步骤 → 源模型元素
```

---

# 二、解释执行总览

```
用户意图（NLU）→ Intent 四元组
  → Model Discovery（§4.4.2）：命中 Blueprint
  → Blueprint 加载（只读）
  → Blueprint 解释（本节核心）：Blueprint → Plan 骨架
  → Goal 实例化 + 上下文注入
  → Plan 生成（tasks/deps/constraints）
  → Plan Validation（Runtime 侧，复用 L2 §6.3）
  → Execution（Runtime 执行）
```

**核心问题：Blueprint step（业务方法）如何变成 Plan task（执行任务）？**

---

# 三、Blueprint Step → Plan Task 投影

## 3.1 映射规则（内置五类 step_type）

| Blueprint Step | Plan Task 投影 | 说明 |
|---|---|---|
| `knowledge_query` | 1 个 Causal Reasoning 调用 Task（capability=`ecmc.causal_reasoning` 或内部调用） | 运行时推理，不预编译路径（§3.6） |
| `data_fetch` | 1 个取数 Task（按 source_ref 引用的 data_requirement → connector/capability） | 实例化实例绑定 + 时间窗 |
| `capability_call` | 1 个 Capability Task（capability_requirements 解析） | 按 §4.4.4 链路 |
| `decision_branch` | Plan 分支结构（按源模型 Rule 评估） | 条件分支 → Plan 的 conditional 边 |
| `output` | 输出汇总 Task（组织结果） | 按 output_contract 声明 |

**投影规则：**

```
MUST: 每个 Blueprint step 至少投影为 1 个 Plan task（除决策分支外不合并）
MUST: step 的 source_ref → task 的输入（实例绑定/时间窗来自编译时投影参数）
MUST: step 多引用（blueprint_step_sources）→ task 输入包含全部引用节点
      的观测需求（如综合分析步骤 → 一个 task 汇总多节点数据需求）
SHOULD: 相邻 data_fetch 步骤可合并为并行 Task 组（按 deps 判断无依赖）
```

## 3.2 deps → Plan 边

```
blueprint_step_deps → plan.edges：
  sequential  → depends_on 边（前步 → 后步）
  conditional → 条件边（按源模型 Rule 评估，生成分支 Task 组）
  data_flow   → 数据依赖边（后步 input 引用前步 output_field）
```

```
MUST: deps 投影后 Plan 保持 DAG（Blueprint 已校验无环，投影不得引入环）
MUST: data_flow 的 output_field 缺失 → 规划错误（不静默，P4 原则）
```

## 3.3 规划约束 → Plan 约束

```
blueprint_constraints → plan.execution_constraints：
  priority（safety > cost）     → 任务排序权重（同层并行任务按优先级定序）
  mandatory_capability          → 能力解析强制（缺失 → 规划失败，不降级）
  minimum_evidence              → 输出校验（归因结果证据链 ≥ 下限）
  ordering                      → 显式顺序约束（强制 before/after）
  exclusion                     → 互斥（同 L2 §6.2 conflicts_with）
```

```
MUST: mandatory_capability 缺失时规划失败（明确报错，不静默降级）
MUST: priority 只影响任务排序/调度偏好，不改变任务语义
MUST: minimum_evidence 在 Plan 输出契约中声明（Execution 后校验）
```

---

# 四、Goal 生成与上下文注入

## 4.1 Goal 实例化

```
intent 四元组 + 实例绑定（entity/time_window）→ 实例化 goal_skeleton：
  goal 目标 = 实例化后的业务目标（如"归因：3 号矿产量下降（近 30 天）"）
  goal 约束 = 规划约束（§3.3）
  goal 输出 = output_contract 实例化（输出结构 + 证据要求）
```

## 4.2 上下文注入

```
注入推理上下文（供运行时/决策分支使用）：
  - 实例绑定（entity_id / entity_type / time_window）
  - 角色 scope（双层权限，见 ECMC §4.4）
  - 用户显式约束（覆盖/叠加规划约束）
```

```
MUST: 用户显式约束优先于蓝图默认约束（同类型时用户覆盖）
MUST: 注入上下文记入 Plan 元数据（审计/复现）
```

---

# 五、Plan 生成完整流程

```
输入：Blueprint（只读）+ intent + 实例绑定 + 上下文
流程：
  ① 解释：step → task 投影（§3.1），deps → edges（§3.2）
  ② 约束注入：constraints → plan 约束（§3.3）
  ③ Goal 实例化 + 上下文注入（§4）
  ④ 能力解析：capability_requirements → Capability Center 解析
     （mandatory 缺失 → 规划失败）
  ⑤ 输出契约实例化：output_contract → Plan 输出声明
  ⑥ Plan 组装：plan_id / goal_id / tasks / edges / execution_constraints
  ⑦ Plan Validation（复用 L2 §6.3：schema/权限/无环/资源）
     - 失败 → 调整后重试（≤3 次）→ 仍失败降级（P4）
输出：合规 Plan（携带 blueprint 追溯元数据）
```

**追溯元数据（P5）：**

```
plan.meta:
  blueprint_id / blueprint_version
  source_models: [{ model_id, version }]
  task_trace: { task_id → step_id → source_ref_path }
```

---

# 六、降级路径（P4）

```
触发：Blueprint 编译失败 / withdrawn / 版本不可用 / 解释失败
降级链：
  ① 直接模型匹配 + 运行时推理（ECMC §4.4：Discovery → Reasoning）
     ——功能可用，规划效率降级（无预编译步骤骨架）
  ② 更严重 → Rule Planner 兜底（L2 §8：规则模式）
行为：
  MUST: 降级不静默——响应标注 degraded + 原因
  MUST: 降级后仍满足最小功能（推理可运行，无步骤优化）
```

---

# 七、Planner 状态机（一次 Request）

```
IDLE → INTENT_PARSED → BLUEPRINT_MATCHED → EXPLAINED → PLAN_ASSEMBLED
  → VALIDATED → HANDED_OFF（→ Execution）
  →（失败）REPLANNING（→ 重新解释/降级）→ HANDED_OFF / FAILED
```

```
MUST: 每个状态转换可观测（trace）
MUST: REPLANNING 保留原意图与上下文（不重复 NLU）
SHOULD: 状态机与现有 Planner 核心循环（L2 §2）兼容（理解→规划→交付→反思）
```

---

# 八、与现有 Planner 模块的对接

```
现有 planner 模块（L2 契约已实现）：
  - intent parsing / goal generation：保留（Blueprint 场景注入 goal_skeleton）
  - domain routing：保留（Blueprint 命中跳过路由，直接匹配）
  - plan generation：新增 Blueprint 解释分支（本节）
  - reflection & replanning：保留（失败 → 重新解释或降级）

新增组件（planner 模块内）：
  - blueprint_interpreter.py   # step → task 投影 + deps → edges
  - constraint_applier.py      # constraints → plan 约束
  - goal_instantiator.py       # goal_skeleton 实例化 + 上下文注入
  - blueprint_trace.py         # task_trace 追溯元数据
```

---

# 九、API 草案（L3 接口）

```
POST /v1/planner/plan-from-blueprint    — 输入 intent + blueprint_id + 实例绑定，输出 Plan
GET  /v1/planner/plans/{plan_id}/trace  — Plan 追溯（task → step → source）
POST /v1/planner/replan                 — 失败重规划（保留意图上下文）
```

（传输层 HTTP 为参考，gRPC/内存/EventBus 由 Runtime 集成层决定。）

---

# 十、开放问题（下一轮评审）

1. **投影粒度**：一个 Blueprint step 是否总是 1 个 Plan task？还是可展开为多 task（如 data_fetch 拆分为多数据源并行）？——当前 SHOULD 合并相邻取数，反向拆分待定
2. **约束冲突**：用户显式约束与蓝图约束、多个 constraint 之间冲突的裁决（priority 冲突）
3. **Blueprint 版本切换**：执行中源模型更新 → 当前 Plan 用旧 Blueprint 快照（不中断），下一个 Request 用新版本——需明确快照边界
4. **多 Blueprint 组合**：一个 Request 命中多个 Blueprint（如诊断+优化）时的 Plan 拼接
5. **性能**：Blueprint 解释缓存（相同 blueprint+intent 重复解释 → 缓存 Plan 骨架）
