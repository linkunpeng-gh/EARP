# Planner Runtime — L3 实现设计

**文档编号：DESIGN-ECMC-PLANNER-RUNTIME-L3**
**版本：v0.3（draft）**
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

# 二、解释执行总览（v0.3 重构：Goal Decomposition 前置）

> **关键修正（v0.3，评审采纳）**：复杂企业请求不是"1 意图 → 1 Blueprint"。
> 先搞清楚"要解决几个问题"（Goal Decomposition），再给每个 SubGoal 找专家方法。

```
User Request
  ↓
Intent Parsing（四元组解析）
  ↓
Goal Resolution / Decomposition（v0.3 前置，见 §2.1）
  ↓
┌─────────┬─────────┐
↓         ↓         ↓
Goal A   Goal B   Goal C（SubGoal）
↓         ↓         ↓
Knowledge Resolution / Discovery（每个 SubGoal 独立发现）
↓         ↓         ↓
BP-A     BP-B      BP-C（Primary + Supporting）
↓         ↓         ↓
Blueprint Interpretation → Plan Fragment（§三）
└─────────┬─────────┘
          ↓
    Plan Composition（§四，多 Fragment 组装）
          ↓
    Constraint Apply + Capability Resolve
          ↓
    Plan Validation（Runtime 侧，复用 L2 §6.3）
          ↓
    Execution
```

**核心问题（分层回答）**：
```
Goal Resolution —— 要解决几个问题？（多 SubGoal）
Discovery —— 每个问题用哪个专家方法？（Primary + Supporting Blueprint）
Interpretation —— 专家方法如何变成执行任务？（Step → PlanFragment）
Composition —— 多个执行块如何拼成一个 Plan？（Fragment 组装）
```

## 2.1 Goal Resolution / Decomposition（v0.3 新增，评审 P0-1）

```
输入：Intent 四元组（entry_point + direction + domain + business_objective）
输出：1..N SubGoal（每个 SubGoal 独立可规划）

SubGoal 结构：
  sub_goal_id / objective（diagnose|predict|optimize|recommend）
  entry_point / direction / domain（继承或细化自总意图）
  priority / dependencies（SubGoal 间顺序或并行）

示例（复杂请求）：
"为什么产量下降？怎么调整？调整后风险？"
  → SubGoal A：诊断原因（objective=diagnose）
  → SubGoal B：制定优化方案（objective=optimize，依赖 A）
  → SubGoal C：评估风险（objective=recommend，依赖 B）
```

```
MUST: Goal Resolution 在 Blueprint Discovery 之前（先定问题，再找方法）
MUST: 每个 SubGoal 独立 Discovery（不同 SubGoal 可命中不同 Blueprint）
MUST: SubGoal 间依赖关系（顺序/并行）在 Composition 阶段体现
MUST: 多 objective 意图（如 diagnose+optimize）分解为多 SubGoal
SHOULD: 单 objective 简单请求 → 1 个 SubGoal（无额外开销）
```

---

# 三、Blueprint Step → Planning Fragment 投影（v0.2 重构）

> **核心抽象（v0.2，评审采纳）**：Step 与 Task **不绑定基数关系**。
> Interpreter 将 Step 投影为 **Planning Fragment**（Task + Edge + Constraint 的集合）：

```
Blueprint Step
      ↓ Interpretation
Planning Fragment
├── tasks: 0..N       （可 0——纯分支/纯约束步骤）
├── edges: 0..N       （条件边/数据依赖边）
└── constraints: 0..N （规划约束贡献）
```

## 3.1 投影示例（内置五类 step_type）

| Blueprint Step | Planning Fragment（task 数可变） | 说明 |
|---|---|---|
| `knowledge_query` | 1 task（Causal Reasoning 调用） | 运行时推理，不预编译路径（§3.6） |
| `data_fetch` | **1..N task**（按数据源拆分） | 一个业务步骤可展开多 Task：如"获取设备运行情况" → EAM 故障记录 + IoT 实时状态 + 维修记录（并行） |
| `capability_call` | 1 task（Capability 调用） | 按 §4.4.4 链路 |
| `decision_branch` | **0 task + N conditional edges** | 纯分支结构（按源模型 Rule 评估） |
| `output` | 1 task（输出汇总） | 按 output_contract 声明 |

**投影规则：**

```
MUST: Step → Fragment 的 task 数为 0..N（不锁 1:1；由 Interpreter 按
      业务步骤语义拆分/合并）
MUST: step 的 source_ref → task 的输入（实例绑定/时间窗来自编译时投影参数）
MUST: step 多引用（blueprint_step_sources）→ 展开为多 task 或合并
      单 task（按数据源独立性与并行性决策）
MUST: Fragment 内 tasks 的依赖边同时产出（Fragment 自带子 DAG）
SHOULD: data_fetch 多数据源默认并行（无依赖时）
```

## 3.2 deps → Plan 边

```
blueprint_step_deps → plan.edges：
  sequential  → depends_on 边（前步 → 后步）
  conditional → 条件边（按源模型 Rule 评估，生成分支 Task 组）
  data_flow   → 数据依赖边（后步 input 引用前步 output_field）

condition_eval_phase（v0.3，评审 P1-2）：条件分支由谁判断：
  planning   — Planner 规划时评估（条件基于编译时可用信息/上下文）
  execution  — Decision Engine 执行时评估（条件基于实时状态）
  来源：由源模型 DecisionRule.scope 决定（planner 域 → planning；
        execution 域 → execution），Planner 不得自行决定
```

```
MUST: deps 投影后 Plan 保持 DAG（Blueprint 已校验无环，投影不得引入环）
MUST: data_flow 的 output_field 缺失 → 规划错误（不静默，P4 原则）
MUST: condition_eval_phase=execution 的条件边，Planner 只生成分支结构，
      不预选分支（由 Decision Engine 在 Execution 时选择）
      ——保持 Planning ≠ Runtime Decision 边界（§4.4.5）
```

## 3.3 规划约束 → Plan 约束（v0.2 分层）

**Hard / Soft 分层（v0.2，评审采纳）——约束优先级链：**

```
Policy / Compliance（平台级，不可变）
        ↓
Blueprint Hard Constraint（专家定义，不可被用户削弱）
        ↓
User Constraint（用户只能增加或收紧 Hard，不能削弱）
        ↓
Blueprint Soft Constraint（可被用户调整）
        ↓
Planner Optimization Preference（内部偏好，最低）
```

**约束类型归属：**

```
Hard Constraint（不可削弱）：
  - 安全/合规类 priority（safety > cost）
  - mandatory_capability（缺失 → 规划失败）
  - minimum_evidence（证据下限）
  - 禁止动作（exclusion / compliance 边界）
Soft Constraint（可调整）：
  - 优化偏好（成本优先/速度优先）
  - 解释深度（basic/detailed/audit）
  - 推荐数量 / 排序偏好
```

```
MUST: 用户只能增加或收紧 Hard Constraint，不能削弱（v0.2 关键）
      ——"用户说忽略安全" → 拒绝（明确报错，不静默放行）
MUST: 用户可调整 Soft Constraint（覆盖蓝图默认）
MUST: Policy/Compliance 优先于一切（平台级，Blueprint 也不可越）
MUST: mandatory_capability 缺失时规划失败（明确报错，不静默降级）
MUST: priority 只影响任务排序/调度偏好，不改变任务语义
MUST: minimum_evidence 在 Plan 输出契约中声明（Execution 后校验）
```

# 四、Multi-Blueprint Planning（v0.3 新增，评审 P0-2）

> **定位**：多 Blueprint 不是边缘情况，是企业 Agent 的常态（诊断+优化+风险评估）。
> 一个 Request → 1..N SubGoal → 每个 SubGoal 0..1 Primary + 0..N Supporting。

## 4.1 组合关系（Primary + Supporting）

```
1 Request
  ↓
1..N SubGoal（§2.1）
  ↓
每个 SubGoal：
  0..1 Primary Blueprint   — 主方法论（该问题的核心方法）
  0..N Supporting Blueprint — 补充（深度下钻/交叉验证）
  ↓
每个 Blueprint → Plan Fragment
  ↓
Composition → 1 Plan
```

**为什么不"1 Goal → N Blueprint 无限拼"**：
- 失控风险（组合爆炸 / 约束冲突 / 输出重复）
- Primary 定义主方法，Supporting 只做补充——组合关系清晰可治理

## 4.2 发现与绑定

```
MUST: 每个 SubGoal 独立 Discovery（§4.4.2），命中 Primary Blueprint
MUST: Supporting Blueprint 由 Primary 声明（编译时 source_models 中的
      supporting role）或 Planner 按需发现（交叉验证场景）
MUST: Supporting 的引入不得改变 Primary 的 Goal 语义（只增强证据）
SHOULD: Supporting Blueprint 的输出并入 Primary 的 Evidence Chain
        （多源证据合并，输出契约合并）
```

## 4.3 多 Blueprint 的约束合并（Hard 取并集）

```
MUST: 多 Blueprint 的 Hard Constraint 取并集（任一蓝图的 Hard 都生效）
MUST: 冲突的 Hard（两个 Hard 互斥）→ 规划失败 + 明确冲突报告
      （不静默取舍——由专家改蓝图或人工裁决）
SHOULD: Soft Constraint 按 Primary 优先、Supporting 补充合并
```

## 4.4 版本一致性

```
MUST: 多 Blueprint 各版本在 Composition 时同时冻结（§6 版本冻结）
MUST: 跨 Blueprint 引用同一源模型时，用同一版本（防版本分裂）
```

---

# 五、Goal 实例化与上下文注入

## 4.1 Goal 实例化

```
intent 四元组 + 实例绑定（entity/time_window）→ 实例化 goal_skeleton：
  goal 目标 = 实例化后的业务目标（如"归因：3 号矿产量下降（近 30 天）"）
  goal 约束 = 规划约束（§3.3，Hard/Soft 合并）
  goal 输出 = output_contract 实例化（输出结构 + 证据要求）
```

## 4.2 上下文注入

```
注入推理上下文（供运行时/决策分支使用）：
  - 实例绑定（entity_id / entity_type / time_window）
  - 角色 scope（双层权限，见 ECMC §4.4）
  - 用户显式约束（按 Hard/Soft 规则合并，§3.3）
```

```
MUST: 用户约束按优先级链合并（§3.3）——只能增加/收紧 Hard，
      可调整 Soft；"忽略安全"类削弱请求 → 拒绝并报错
MUST: 注入上下文记入 Plan 元数据（审计/复现）
```

---

# 六、Plan Composition 与生成流程（v0.3 重构）

```
输入：SubGoals + 各 SubGoal 的 Blueprint（只读）+ 实例绑定 + 上下文
流程（v0.3：多 SubGoal 并行解释，最终 Composition）：
  ① Goal Resolution（§2.1）：1 Request → 1..N SubGoal
  ② 每个 SubGoal：
     a. 版本冻结（§6.1）：确定 blueprint/version + source_models + compile_id
     b. 解释：step → Planning Fragment（§3：0..N task），deps → edges（§3.2）
     c. 约束注入：Hard/Soft 分层合并（§3.3）
     d. Goal 实例化 + 上下文注入（§5）
     e. 能力解析：capability_requirements → Capability Center
        （mandatory 缺失 → 该 SubGoal 规划失败）
     → 产出 SubGoal 的 Plan Fragment
  ③ Composition（§4.3/4.4）：多 Fragment 组装为 1 Plan
     - SubGoal 间依赖边（顺序/并行）
     - Hard Constraint 并集（冲突 → 失败 + 冲突报告）
     - 跨 Blueprint 版本一致性（同一源模型同版本）
  ④ 输出契约实例化：output_contract → Plan 输出声明（合并）
  ⑤ Plan Validation（复用 L2 §6.3：schema/权限/无环/资源）
     - 失败 → 按 §6.2 边界修复后重试 → 仍失败按 §7 降级
输出：合规 Plan（携带版本冻结 + 追溯元数据）
```

## 6.1 版本冻结（v0.2 拍板，v0.3 扩展多 Blueprint）

```
MUST: Plan 创建时完成版本冻结（v0.3 多 Blueprint：每个 Blueprint 独立冻结）——确定：
      blueprints: [bp-001 v2.3 (primary), bp-002 v1.1 (supporting)]
      source_models: [causal-a v1.7, decision-b v3.1]
      compile_records: [compile-8821, compile-8830]
      blueprint_snapshot_hashes
MUST: 跨 Blueprint 引用同一源模型 → 用同一版本（防版本分裂，§4.4）
MUST: 执行期间源模型发布新版本不影响当前 Plan（继续用冻结版本）
MUST: 下一个 Request 才用新版本（冻结在 Plan 级，不跨 Request）
MUST: 审计链完整：Execution → Plan → Blueprint → Compile Record →
      Source Models → 具体模型元素（含 compile_id + compiler_version +
      snapshot_hash，v0.2 增强）
```

## 6.2 Replanning 修复边界（v0.2，评审采纳）

```
允许修改（Repair Allowed）：
  - Task 拆分/合并
  - Capability 重新解析（换等价能力）
  - 并行度调整
  - Soft Constraint 排序
  - 资源选择（超时/优先级）
禁止修改（Repair Forbidden）：
  - Goal 语义
  - source_ref（指向源模型元素的引用）
  - 源模型 Rule（决策分支逻辑）
  - Hard Constraint（mandatory_capability / minimum_evidence / 禁止动作）
  - 业务输出契约

MUST: 修复不得改变 Blueprint 语义（只允许执行层调整）
MUST: 违反 Forbidden 的"修复" → 拒绝 + 记录（防 Planner 绕过硬约束
      变回自由 Agent）
SHOULD: 重试次数配置化（默认 ≤3，非架构常量）
```

**追溯元数据（P5）：**

```
plan.meta:
  blueprint_id / blueprint_version
  source_models: [{ model_id, version }]
  compile_id / compiler_version / blueprint_snapshot_hash  （v0.2 增强）
  task_trace: { task_id → step_id → source_ref_path }
```

---

# 七、降级路径（P4，v0.2 强化）

```
触发：Blueprint 编译失败 / withdrawn / 版本不可用 / 解释失败
降级链：
  ① 直接模型匹配 + 运行时推理（ECMC §4.4：Discovery → Reasoning）
     ——功能可用，规划效率降级（无预编译步骤骨架）
  ② 更严重 → Rule Planner 兜底（L2 §8：规则模式）

关键约束（v0.2，评审采纳）：
MUST: Fallback 只能降低规划质量，不能降低业务约束等级——
      必须继承：Hard Constraints / Policy / Permission /
      mandatory capability / minimum evidence / output contract
MUST: 降级不静默——响应标注 degraded + 原因 + 继承的约束清单
MUST: Fallback 也满足不了 Hard Constraint → FAILED（不再继续降级）
```

---

# 八、Planner 状态机（一次 Request，v0.3 泛化）

> Blueprint 不是必需层——状态机覆盖多 Goal / 多 Blueprint / 降级路径：

```
IDLE → INTENT_PARSED → GOALS_RESOLVED → KNOWLEDGE_RESOLVED
  → PLAN_FRAGMENTS_BUILT → PLAN_ASSEMBLED → VALIDATED → HANDED_OFF
  →（失败）REPLANNING（→ 按 §6.2 边界修复 / §7 降级）→ HANDED_OFF / FAILED

GOALS_RESOLVED：1..N SubGoal 已分解（§2.1）
KNOWLEDGE_RESOLVED.mode（每个 SubGoal 的知识来源）：
  blueprint   — 命中并解释 Blueprint（主路径）
  direct_model— 直接模型匹配 + 运行时推理（降级 ①）
  rule        — Rule Planner 兜底（降级 ②）
  mixed       — 多 SubGoal 混合模式（部分 blueprint / 部分降级）
PLAN_FRAGMENTS_BUILT：各 SubGoal 的 Plan Fragment 已产出
PLAN_ASSEMBLED：Composition 完成（多 Fragment → 1 Plan，§6）
```

```
MUST: 每个状态转换可观测（trace）
MUST: mode 记入 trace（每个 SubGoal 的知识来源可追溯）
MUST: REPLANNING 保留原意图与上下文（不重复 NLU）
MUST: 降级时 KNOWLEDGE_RESOLVED 的 mode 切换为 direct_model/rule，
      但 Hard Constraint 继承不变（§7）
SHOULD: 状态机与现有 Planner 核心循环（L2 §2）兼容（理解→规划→交付→反思）
```

---

# 九、与现有 Planner 模块的对接

```
现有 planner 模块（L2 契约已实现）：
  - intent parsing / goal generation：保留（Blueprint 场景注入 goal_skeleton）
  - domain routing：保留（Blueprint 命中跳过路由，直接匹配）
  - plan generation：新增 Blueprint 解释分支（本节）
  - reflection & replanning：保留（失败 → 按 §6.2 边界修复或 §7 降级）

新增组件（planner 模块内）：
  - blueprint_interpreter.py   # step → Planning Fragment（0..N task）+ edges
  - fragment_assembler.py      # Fragment 组装为 Plan（v0.2）
  - constraint_applier.py      # Hard/Soft 分层合并（v0.2）
  - version_freezer.py         # 版本冻结 + 快照哈希（v0.2）
  - goal_instantiator.py       # goal_skeleton 实例化 + 上下文注入
  - blueprint_trace.py         # task_trace 追溯元数据
```

---

# 十、API 草案（L3 接口）

```
POST /v1/planner/plan-from-blueprint    — 输入 intent + blueprint_id + 实例绑定，输出 Plan
GET  /v1/planner/plans/{plan_id}/trace  — Plan 追溯（task → step → source）
POST /v1/planner/replan                 — 失败重规划（保留意图上下文）
```

（传输层 HTTP 为参考，gRPC/内存/EventBus 由 Runtime 集成层决定。）

---

# 十一、开放问题（下一轮评审）

1. **投影粒度实现**：v0.2 已定 Step→Fragment（0..N task）；data_fetch 拆分（多数据源并行）与并行调度（保留独立 Task + 并行边，不物理合并）的具体规则（数据源独立性判定）待细化
2. **Hard 冲突裁决实现**：v0.3 已定"冲突 → 规划失败 + 冲突报告"；冲突报告的表述与人工裁决流程待细化
3. **Goal Resolution 启发式**：v0.3 已前置 Goal Decomposition；多 objective 意图的拆分启发式（何时拆/拆几个）与 LLM 辅助拆分的边界待细化
4. **性能**：Blueprint 解释缓存（相同 blueprint+intent 重复解释 → 缓存 Plan 骨架）
5. **版本冻结粒度**：v0.3 已拍板 Plan 级冻结（多 Blueprint 独立冻结）；跨多个 Plan 的长期任务（长会话）版本续订策略待定
6. **SubGoal 依赖编排**：SubGoal 间依赖（如诊断→优化→风险评估）在 Composition 后的执行语义（是否整 Plan 一个 Execution 还是分段）待细化
