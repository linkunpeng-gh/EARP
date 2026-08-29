# Planner Runtime — L3 实现设计

**文档编号：DESIGN-ECMC-PLANNER-RUNTIME-L3**
**版本：v0.2（draft）**
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
```

```
MUST: deps 投影后 Plan 保持 DAG（Blueprint 已校验无环，投影不得引入环）
MUST: data_flow 的 output_field 缺失 → 规划错误（不静默，P4 原则）
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
  - 用户显式约束（按 Hard/Soft 规则合并，§3.3）
```

```
MUST: 用户约束按优先级链合并（§3.3）——只能增加/收紧 Hard，
      可调整 Soft；"忽略安全"类削弱请求 → 拒绝并报错
MUST: 注入上下文记入 Plan 元数据（审计/复现）
```

---

# 五、Plan 生成完整流程

```
输入：Blueprint（只读）+ intent + 实例绑定 + 上下文
流程：
  ① 版本冻结（v0.2 拍板，见下）：Planner 创建时确定所用
     blueprint_id/version + source_models 各版本 + compile_id
  ② 解释：step → Planning Fragment（§3.1：0..N task），deps → edges（§3.2）
  ③ 约束注入：Hard/Soft 分层合并（§3.3）
  ④ Goal 实例化 + 上下文注入（§4）
  ⑤ 能力解析：capability_requirements → Capability Center 解析
     （mandatory 缺失 → 规划失败）
  ⑥ 输出契约实例化：output_contract → Plan 输出声明
  ⑦ Plan 组装：plan_id / goal_id / tasks / edges / execution_constraints
  ⑧ Plan Validation（复用 L2 §6.3：schema/权限/无环/资源）
     - 失败 → 按 §5.2 边界修复后重试 → 仍失败按 §6 降级
输出：合规 Plan（携带版本冻结 + 追溯元数据）
```

## 5.1 版本冻结（v0.2 拍板，评审采纳）

```
MUST: Plan 创建时完成版本冻结——确定：
      blueprint: bp-001 v2.3
      source_models: [causal-a v1.7, decision-b v3.1]
      compile_record: compile-8821
      blueprint_snapshot_hash
MUST: 执行期间源模型发布新版本不影响当前 Plan（继续用冻结版本）
MUST: 下一个 Request 才用新版本（冻结在 Plan 级，不跨 Request）
MUST: 审计链完整：Execution → Plan → Blueprint → Compile Record →
      Source Models → 具体模型元素（含 compile_id + compiler_version +
      snapshot_hash，v0.2 增强）
```

## 5.2 Replanning 修复边界（v0.2，评审采纳）

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

# 六、降级路径（P4，v0.2 强化）

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

# 七、Planner 状态机（一次 Request，v0.2 泛化）

> Blueprint 不是必需层——状态机不绑死 Blueprint 路径（降级时无 BLUEPRINT_MATCHED）：

```
IDLE → INTENT_PARSED → KNOWLEDGE_RESOLVED → PLANNING_CONTEXT_READY
  → PLAN_ASSEMBLED → VALIDATED → HANDED_OFF（→ Execution）
  →（失败）REPLANNING（→ 按 §5.2 边界修复 / §6 降级）→ HANDED_OFF / FAILED

KNOWLEDGE_RESOLVED 的 mode（知识来源）：
  blueprint   — 命中并解释 Blueprint（主路径）
  direct_model— 直接模型匹配 + 运行时推理（降级 ①）
  rule        — Rule Planner 兜底（降级 ②）
```

```
MUST: 每个状态转换可观测（trace）
MUST: mode 记入 trace（知识来源可追溯）
MUST: REPLANNING 保留原意图与上下文（不重复 NLU）
MUST: 降级时 KNOWLEDGE_RESOLVED 的 mode 切换为 direct_model/rule，
      但 Hard Constraint 继承不变（§6）
SHOULD: 状态机与现有 Planner 核心循环（L2 §2）兼容（理解→规划→交付→反思）
```

---

# 八、与现有 Planner 模块的对接

```
现有 planner 模块（L2 契约已实现）：
  - intent parsing / goal generation：保留（Blueprint 场景注入 goal_skeleton）
  - domain routing：保留（Blueprint 命中跳过路由，直接匹配）
  - plan generation：新增 Blueprint 解释分支（本节）
  - reflection & replanning：保留（失败 → 按 §5.2 边界修复或 §6 降级）

新增组件（planner 模块内）：
  - blueprint_interpreter.py   # step → Planning Fragment（0..N task）+ edges
  - fragment_assembler.py      # Fragment 组装为 Plan（v0.2）
  - constraint_applier.py      # Hard/Soft 分层合并（v0.2）
  - version_freezer.py         # 版本冻结 + 快照哈希（v0.2）
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

1. **投影粒度实现**：v0.2 已定 Step→Fragment（0..N task）；data_fetch 拆分（多数据源并行）与合并的具体决策规则（数据源独立性判定）待细化
2. **Hard 冲突裁决**：两个 Hard Constraint 冲突（如 safety>cost 与另一合规约束互斥）的裁决机制（v0.2 定分层，具体裁决逻辑待细化）
3. **多 Blueprint 组合**：一个 Request 命中多个 Blueprint（如诊断+优化）时的 Plan 拼接与 Hard Constraint 合并
4. **性能**：Blueprint 解释缓存（相同 blueprint+intent 重复解释 → 缓存 Plan 骨架）
5. **版本冻结粒度**：v0.2 已拍板 Plan 级冻结；跨多个 Plan 的长期任务（长会话）版本续订策略待定
