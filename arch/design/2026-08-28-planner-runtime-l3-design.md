# Planner Runtime — L3 实现设计

**文档编号：DESIGN-ECMC-PLANNER-RUNTIME-L3**
**版本：v1.0.1（架构冻结，契约修订）**
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

## 2.1 Goal Resolution / Decomposition（v0.3 新增，v0.4 澄清输入与两阶段）

```
输入（v0.4：支持 Compound Intent，不再限单值四元组）：
  ParsedIntent:
    primary_intent: { entry_point, direction, domain, business_objective }
    objective_candidates[]:  （compound 时，如 diagnose + optimize + recommend）
      { entry_point, direction, domain, business_objective }
输出：1..N SubGoal（每个 SubGoal 独立可规划）

SubGoal 结构：
  sub_goal_id / objective（diagnose|predict|optimize|recommend）
  entry_point / direction / domain（继承或细化自 ParsedIntent）
  origin_clause / confidence（v0.5：来源子句 + 分解置信度）
  priority / dependencies（SubGoal 间顺序或并行）

示例（复杂请求）：
"为什么产量下降？怎么调整？调整后风险？"
  → ParsedIntent.primary = diagnose（产量下降）
  → objective_candidates = [optimize, recommend]
  → SubGoal A：诊断原因（objective=diagnose）
  → SubGoal B：制定优化方案（objective=optimize，依赖 A）
  → SubGoal C：评估风险（objective=recommend，依赖 B）
```

```
MUST: Goal Resolution 在 Blueprint Discovery 之前（先定问题，再找方法）
MUST: 每个 SubGoal 独立 Discovery（不同 SubGoal 可命中不同 Blueprint）
MUST: SubGoal 间依赖关系（顺序/并行）在 Composition 阶段体现
MUST: Compound Intent 的多个 objective 分解为多 SubGoal
      （输入输出一致：不支持"输入单值、输出多值"的矛盾）
SHOULD: 单 objective 简单请求 → 1 个 SubGoal（无额外开销）
```

**Goal Resolution vs Goal Instantiation（v0.4 明确，评审 P1-6）：**

```
Goal Resolution = Request → SubGoals（语义分解："这次到底要解决几个问题"）
                —— §2.1，Blueprint Discovery 之前
Goal Instantiation = SubGoal + Blueprint goal_skeleton + Context
                → Runtime Goal（"把模板套到 3 号矿 + 近 30 天"）
                —— §5.1，Blueprint 命中之后

两者是不同阶段的不同动作，不重复、不混淆
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
| `knowledge_query` | **0..N 取证 Task + 1 Evaluate Task**（v0.6.1 跨文档契约，与 Causal Reasoning L3 v0.3 咬合）：Planner 解释期调用 **Reasoning Prepare**（Planning-time，非执行期）→ 得 Evidence Requirements → Handler 生成 PlanFragment = data_fetch/capability Tasks（按需求）+ 1 个 reasoning_evaluate Task | 运行时推理，不预编译路径（§3.6）；Prepare 在规划期、Evaluate 在执行期 |
| `data_fetch` | **1..N task**（按数据源拆分） | 一个业务步骤可展开多 Task：如"获取设备运行情况" → EAM 故障记录 + IoT 实时状态 + 维修记录（并行） |
| `capability_call` | 1 task（Capability 调用） | 按 §4.4.4 链路 |
| `decision_branch` | **0 task + N conditional edges** | 纯分支结构（按源模型 Rule 评估） |
| `output` | 1 task（输出汇总） | 按 output_contract 声明 |

**投影规则（v0.5 锁定确定性解释）：**

```
MUST: Step → Fragment 由 StepType Handler 主导（确定性解释）——
      投影规则在 Handler 内固定（如 data_fetch: 1 datasource → 1 task；
      N 独立 datasource → N task + parallel edges）
MUST: LLM 只能做参数补全 / 候选建议，不能自由改变投影语义
      （v0.6 收紧：LLM 只能在模型已声明的 Data/Capability Requirement
      候选集合内做匹配与参数补全——如 ECMC 声明"需要设备健康证据，
      允许绑定 EAM/IoT/维修历史"，LLM 可选 EAM+IoT，但不得新增
      未声明的数据需求或外部数据源）
MUST: step 的 source_ref → task 的输入（实例绑定/时间窗来自编译时投影参数）
MUST: step 多引用（blueprint_step_sources）→ 展开为多 task 或合并
      单 task（按 Handler 定义的数据源独立性规则）
MUST: Fragment 内 tasks 的依赖边同时产出（Fragment 自带子 DAG）
SHOULD: data_fetch 多数据源默认并行（无依赖时，并行边不物理合并）
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
Hard Constraint（不可削弱，v0.4 类型化）：
  - mandatory_check（必须执行的检查，如安全风险检查）
  - prohibition（禁止动作）
  - mandatory_capability（缺失 → 规划失败）
  - minimum_evidence（证据下限）
  - compliance_rule（合规/政策边界）
  - priority 语义澄清（v0.4，评审 P1-1）："安全优先"如果只是排序偏好
    归 Soft；安全真的不可违反，必须表达为 mandatory_check /
    prohibition / compliance_rule（Hard）
Soft Constraint（可调整）：
  - priority / scheduling_weight（任务排序权重）
  - cost_vs_speed（成本/速度偏好）
  - 解释深度（basic/detailed/audit）
  - 推荐数量 / 排序偏好
```

```
MUST: 用户只能增加或收紧 Hard Constraint，不能削弱（v0.2 关键）
      ——"用户说忽略安全" → 拒绝（明确报错，不静默放行）
MUST: 用户可调整 Soft Constraint（覆盖蓝图默认）
MUST: Policy/Compliance 优先于一切（平台级，Blueprint 也不可越）
MUST: mandatory_capability 缺失时规划失败（明确报错，不静默降级）
MUST: priority/scheduling_weight 只影响任务排序/调度偏好，不改变任务语义
      （安全约束必须走 mandatory/prohibition，不能仅靠排序表达）
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
MUST: Supporting Blueprint 由 Planner 动态发现（v0.4 修正：Phase 1
      禁止 Blueprint 静态引用另一个 Blueprint）——Planner 判断是否需要
      补充分析（交叉验证/深度下钻）后再 Discovery
MUST: Blueprint → Source Cognitive Models（source_models：causal/decision/
      scenario）与 Primary → Supporting Blueprint 是两种不同关系，
      禁止混用 source_models.supporting 表达 Supporting Blueprint
      （v0.4 P0：见 §4.5 关系澄清）
MUST: Supporting 的引入不得改变 Primary 的 Goal 语义（只增强证据）
MUST: Supporting 数量/深度/终止规则（v0.5，评审 P1-3）：
      - 每 SubGoal 最多 max_supporting_per_subgoal（默认 2）
      - Supporting 不触发递归 Supporting Discovery（结构只允许
        Primary → Supporting A/B 一层，禁止 Primary → Supporting A
        → Supporting B 的链）
      - 每次添加记录 support_reason：cross_validation（交叉验证）/
        evidence_gap（证据缺口）/ specialist_analysis（专项分析）
MUST: 超过上限或需要递归 → 规划失败或显式提示（不静默膨胀）
SHOULD: Supporting Blueprint 的输出并入 Primary 的 Evidence Chain
        （多源证据合并，输出契约合并）
```

## 4.3 多 Blueprint 的约束合并（Hard 取并集 + Merge Operator）

```
MUST: 多 Blueprint 的 Hard Constraint 取并集（任一蓝图的 Hard 都生效）
MUST: 冲突的 Hard（两个 Hard 互斥）→ 规划失败 + 明确冲突报告
      （不静默取舍）
MUST: Hard 冲突的处理路径（v0.5，评审 P1-4）：
      - 更换兼容 Blueprint / 修改规划输入 / 发起认知模型治理变更
        （专家改蓝图，走 ECMC Governance §3.4）
      - 禁止 Runtime 内直接豁免 Hard Constraint（不弹"是否强制继续"）
      - Policy/Compliance 永不可人工临时覆盖
MUST: 约束合并用类型化 Merge Operator（v0.4，评审 P1-3）：
      minimum → max()          （minimum_evidence ≥2 与 ≥3 → ≥3）
      maximum → min()          （timeout ≤10m 与 ≤5m → ≤5m）
      set_required → union     （mandatory_capability 并集）
      allowed_set → intersection
      prohibited → union
      priority → Primary 优先 / policy 裁决
SHOULD: Soft Constraint 按 Primary 优先、Supporting 补充合并（同型算子）
```

## 4.4 版本兼容校验（v0.4 修正，评审 P0-2）

> **关键原则**：Composition 不得修改已冻结 Blueprint 的源模型版本（Blueprint 不可变）。
> 跨 Blueprint 引用同一 Source Model 时做**兼容校验**，不做强制统一。

```
场景：
  BP-A v2 编译时引用 Causal Model v1.7
  BP-B v3 编译时引用 Causal Model v1.8
  → Planner 同时命中 BP-A + BP-B

MUST: 不修改任何 Blueprint 的冻结版本（v1.7 就是 v1.7，不可换 v1.8）
MUST: 检查 Blueprint 组合的版本兼容性：
      - 引用同一 Source Model 的多个 Blueprint，若版本相同 → 兼容
      - 版本不同 → Version Compatibility Conflict
MUST: Phase 1 兼容策略 = strict_exact_version（v0.5，评审 P2-1）：
      只有完全相同版本才兼容（v1.7 ≠ v1.7.1）；Phase 2 可演进为
      semantic_version / declared_compatible_range / schema_compatibility
处理（按序）：
      ① 优先找兼容版本的 Blueprint（同源模型同版本的替代）
      ② 找不到 → 要求重新编译 / 换 Blueprint
      ③ 仍无法兼容 → Composition Failed（明确报错）
```

## 4.5 关系澄清（v0.4，评审 P0-1）

```
两种关系必须分开：

Blueprint → Source Cognitive Models（编译时引用）：
  blueprint_source_models（model_type: causal/decision/scenario，
  model_role: primary_model/supporting_model）——"这个 Blueprint
  用了哪些 ECMC 模型"（v0.6 命名：role → model_role，避免与
  Blueprint 组合的 role 混淆）

Primary Blueprint → Supporting Blueprint（规划时组合）：
  blueprint_role: primary/supporting（v0.6 命名区分）
  Phase 1 不静态建模——由 Planner 动态发现（§4.2）
  未来如需静态关系，单独定义 BlueprintRelation（
  primary_blueprint_id / supporting_blueprint_id / relation_type /
  purpose），不复用 source_models
```

---

# 五、Goal 实例化与上下文注入

## 5.1 Goal 实例化

```
SubGoal + Blueprint goal_skeleton + 实例绑定（entity/time_window）→ Runtime Goal：
  goal 目标 = 实例化后的业务目标（如"归因：3 号矿产量下降（近 30 天）"）
  goal 约束 = 规划约束（§3.3，Hard/Soft 合并）
  goal 输出 = output_contract 实例化（输出结构 + 证据要求）
  goal 来源 = SubGoal.origin_clause（v1.0 统一命名：追溯用户哪句话）
```

**SubGoal 结构补充（v0.5，评审 P1-2）：**

```
SubGoal:
  sub_goal_id / objective / entry_point / direction / domain
  origin_clause   — 来源子句（用户原话片段，如"怎么调整？"）
  confidence      — 分解置信度（LLM 辅助拆分时标注，低置信 → 人工确认）
  dependencies    — 顺序/并行依赖

LLM 边界（v0.5 明确）：
  MUST: LLM 可以识别/拆分/归类用户**表达出来的**目标
  MUST: LLM 不可以凭空新增用户未提出的业务目标
        （如用户只问"为什么下降" → 只有 diagnose，不自动加 optimize/
        execute-maintenance，除非 Blueprint/Policy 明确要求后续阶段）
  MUST: 每个 SubGoal 保留 origin_clause（可追溯"这个 Goal 从哪句话来"）
  SHOULD: 低置信分解 → 人工确认（不静默）
```

## 5.2 上下文注入

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

# 六、Plan Composition 与生成流程（v0.3 重构，v0.6 补跨 SubGoal 数据链）

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
  ③ Composition（§4.3/4.4/4.5）：多 Fragment 组装为 1 Plan
     - SubGoal 间依赖边（顺序/并行，§6.3 Cross-SubGoal Data Binding）
     - Hard Constraint 并集 + Merge Operator（§4.3）
     - 版本兼容校验（§4.4：不修改冻结版本，不兼容 → 换蓝图/重新编译/失败）
  ④ 输出契约实例化：output_contract → Multi-SubGoal Output（§6.4）
  ⑤ Plan Validation（复用 L2 §6.3：schema/权限/无环/资源）
     - 失败 → 按 §6.2 边界修复后重试 → 仍失败按 §7 降级
输出：合规 Plan（携带版本冻结 + 追溯元数据 + 跨 SubGoal 数据绑定）
```

## 6.1 版本冻结（v0.2 拍板，v0.3 扩展多 Blueprint）

```
MUST: Plan 创建时完成版本冻结（v0.3 多 Blueprint：每个 Blueprint 独立冻结）——确定：
      blueprints: [bp-001 v2.3 (primary), bp-002 v1.1 (supporting)]
      source_models: [causal-a v1.7, decision-b v3.1]
      compile_records: [compile-8821, compile-8830]
      blueprint_snapshot_hashes
MUST: 跨 Blueprint 引用同一源模型 → 版本兼容校验（§4.4：同版本兼容，
      异版本 → Version Compatibility Conflict，不强行统一）
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

**追溯元数据（P5，v0.4 升级为 Multi-Blueprint 结构）：**

```
plan.meta:
  blueprints: [                       （v0.4：复数，多 Blueprint）
    {
      blueprint_id, version, blueprint_role（primary|supporting，v0.6）,
      sub_goal_id,                    ← 关联哪个 SubGoal
      compile_id, compiler_version, snapshot_hash
    }
  ]
  source_models: [{ model_type, model_id, version }]
  task_trace: {                       （v0.4：task → 1..N 来源）
    task_id → [{
      sub_goal_id, blueprint_id, step_id, source_ref_path
    }]
  }
```

---

## 6.3 Cross-SubGoal Data Binding（v0.6 新增，评审 P0）

> **缺口**：此前 SubGoal 间只有 depends_on（控制依赖），缺"B 怎么拿到 A 的结果"。
> 诊断结果 → 优化方案 → 风险评估，需要 output → input 映射。

```
SubGoalBinding
├── from_sub_goal_id
├── from_output          — 来源输出字段（如 diagnose 的 cause_ranking）
├── to_sub_goal_id
├── to_input             — 目标输入字段（如 optimize 的 root_causes）
└── required             — true=必传（缺失 → 规划失败）；false=可选

控制依赖 vs 数据依赖（v0.6 区分）：
  control_dependency — B 必须等 A 完成（depends_on，已有）
  data_dependency    — B 需要 A 的某个输出作为输入（SubGoalBinding，新增）
  MUST: data_dependency 隐含 control_dependency（传数据必须先完成）

示例：
  A: diagnose → output: cause_ranking
    ↓ binding: { from_output: cause_ranking, to_input: root_causes }
  B: optimize → output: recommended_plan
    ↓ binding: { from_output: recommended_plan, to_input: plan_assumptions }
  C: risk → output: risk_list
```

```
MUST: SubGoal 间数据传递必须显式声明 SubGoalBinding（不隐式全局共享）
MUST: to_input 字段必须存在于目标 SubGoal 的 Blueprint 输入契约；
      from_output 字段必须存在于来源 SubGoal 的输出契约
      ——由 Plan Composition / Plan Validation 阶段校验
      （v1.0：Composition-time Validation，非 Compiler 编译期——
      SubGoal/Binding 是 Planner Runtime 组合出来的，ECMC Compiler
      不知道 SubGoal 结构）
MUST: from_output schema 与 to_input schema 基础兼容校验
      （v1.0：类型匹配如 array<Cause> → array<RootCause> 需兼容；
      不兼容 → Plan Validation Failed；Phase 1 不允许 LLM 随意
      转换数据结构，future 可加 registered_transform）
MUST: 校验分两个时间阶段（v1.0，评审）:
      - Planning-time：绑定契约不成立（字段不存在/类型不兼容）
        → PLAN_INVALID（规划/校验失败）
      - Execution-time：required 来源输出缺失（上游执行失败）
        → 下游 BLOCKED + 失败传播（Execution failure propagation，
        Plan 结果 = FAILED / PARTIAL_FAILED 依 Plan Policy）
MUST: 所有 SubGoalBinding 转换为依赖边后参与最终 Plan DAG 校验
      （v1.0：Final DAG = Fragment 内部边 + SubGoal 控制依赖 +
      跨 SubGoal 数据依赖 + 条件边；Composition 后整体无环，
      防 A→B→C→A 跨 Fragment 环）
SHOULD: required=false 绑定缺失 → 下游降级（标注缺输入）
```

## 6.4 Multi-SubGoal Output Contract（v0.6，评审 P1）

> **不简单 merge 成一个大 JSON**——保留每个 SubGoal 的结构化输出，
> 再由最终 Output Task 做综合表达：

```
Plan Output
├── subgoals:
│     diagnose:  { cause_ranking, evidence_chain }   ← 保留结构化
│     optimize:  { recommendation, expected_benefit }
│     risk:      { risk_list, risk_level }
├── cross_goal_bindings: [ ... ]                     ← 传递链（可追溯）
└── final_response: { ... }                          ← 综合表达（Output Task 生成）
```

```
MUST: 每个 SubGoal 的输出保留独立结构化结果（好追溯/测试/复用）
MUST: final_response 由最终 Output Task 综合生成（引用各 SubGoal 输出，
      不复制业务逻辑）
MUST: 字段冲突（两个 SubGoal 同名字段不同义）→ 命名空间隔离（按 sub_goal_id）
      ，不静默覆盖
```

# 七、降级路径（P4，v0.2 强化）

```
触发：Blueprint 编译失败 / withdrawn / 版本不可用 / 解释失败
降级链：
  ① 直接模型匹配 + 运行时推理（ECMC §4.4：Discovery → Reasoning）
     ——功能可用，规划效率降级（无预编译步骤骨架）
  ② 更严重 → Rule Planner 兜底（L2 §8：规则模式）

关键约束（v0.2，v0.6 按场景澄清 Fallback 约束来源）：
MUST: Fallback 只能降低规划质量，不能降低业务约束等级
MUST: FallbackConstraintSet（v0.6 明确，按场景取）：
      场景 A（Blueprint 已选中但解释失败）：
        = Policy/Compliance + User Hard + 该 Blueprint 的 Hard Constraints
      场景 B（未命中 Blueprint，直接模型/规则）：
        = Policy/Compliance + User Hard + 已解析知识资产的 Hard Constraints
        （不存在"继承未选中的 Blueprint 约束"——实现勿误读）
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

新增组件（planner 模块内，v0.5 补全）：
  - goal_resolver.py         # Goal Resolution：Request → SubGoals（v0.5 新增，
  -                        #   对应 GOALS_RESOLVED 状态；含 LLM 边界约束）
  - knowledge_resolver.py    # Discovery：SubGoal → Primary/Supporting Blueprint
  -                          #   （v0.5 新增，对应 KNOWLEDGE_RESOLVED；含 Supporting
  -                          #    数量/深度/终止规则）
  - blueprint_interpreter.py # step → Planning Fragment（0..N task）+ edges
  -                          #   （Handler 确定性解释，v0.5 锁定）
  - fragment_assembler.py    # Fragment 组装为 Plan（v0.2）
  - constraint_applier.py    # Hard/Soft 分层合并 + Merge Operator（v0.2/v0.4）
  - version_freezer.py       # 版本冻结 + 快照哈希（v0.2）
  - goal_instantiator.py     # goal_skeleton 实例化 + 上下文注入（§5）
  - blueprint_trace.py       # task_trace 追溯元数据（Multi-Blueprint，v0.4）
```

---

# 十、API 草案（L3 接口，v0.4 主入口升级）

```
POST /v1/planner/plans                — 主入口（v0.4）：
      输入 { request/intent, context, entity, constraints }
      → Goal Resolution → Discovery → Multi-Blueprint → Composition → Plan
GET  /v1/planner/plans/{plan_id}       — Plan 查询（含 meta/task_trace）
GET  /v1/planner/plans/{plan_id}/trace — Plan 追溯（task → subgoal → blueprint → step → source）
POST /v1/planner/replan                — 失败重规划（保留意图上下文）

内部/调试接口（非主入口）：
POST /v1/planner/plan-from-blueprint   — 强制指定 Blueprint（调试/内部编排）
```

（传输层 HTTP 为参考，gRPC/内存/EventBus 由 Runtime 集成层决定。）

---

# 十一、Implementation Follow-ups / Phase 2（v1.0 降级：不再阻塞 L3）

以下均为实现迭代 / Phase 2 优化项，不阻塞 L3 冻结：
1. **投影粒度实现**：data_fetch 拆分与并行调度的具体规则（数据源独立性判定）——实现期细化
2. **Hard 冲突裁决实现**：v0.4 已定"冲突 → 规划失败 + 冲突报告" + Merge Operator；冲突报告的表述与人工裁决流程待细化
3. **Goal Resolution 启发式**：v0.4 已支持 Compound Intent（objective_candidates）；拆分启发式（何时拆/拆几个）与 LLM 辅助拆分的边界待细化
4. **Supporting Blueprint 发现启发式**：v0.4 已定"Planner 动态发现、Phase 1 禁止静态引用"；何时需要 Supporting（交叉验证/深度下钻）的判定规则待细化
5. **性能**：Blueprint 解释缓存（相同 blueprint+intent 重复解释 → 缓存 Plan 骨架）
6. **版本冻结粒度**：v0.3 已拍板 Plan 级冻结（多 Blueprint 独立冻结）；跨多个 Plan 的长期任务（长会话）版本续订策略待定
7. **SubGoal 依赖编排（v0.5 给出 Phase 1 默认答案）**：默认 1 Request → 1 Plan → 1 Execution
   ——SubGoal 只是 Plan 内部逻辑分组（顺序/并行边）；仅当出现人工审批 /
   超长任务 / 跨时间等待 / 外部事件触发时才切分为多个 Execution
8. **Merge Operator 覆盖**：v0.4 已定义基础算子（min→max/max→min/union/intersection）；更多约束类型（如时序、嵌套）的算子待细化
9. **SubGoal 执行编排细化**：v0.5 已定 Phase 1 默认"1 Plan = 1 Execution"；切分 Execution 的触发条件量化（何时算超长/跨时间等待）待细化
10. **Cross-SubGoal Data Binding 类型**：v0.6 已定义 SubGoalBinding（output→input 映射）；更多传递类型（流式/部分结果/事件触发传递）待 Phase 2 细化


---

# 十二、v1.0 冻结记录（v0.6 → v1.0）

**评审结论**：Planner Runtime 架构设计完成，`Request → SubGoal → Blueprint → Fragment → Plan → Execution` 链路闭环。不建议再增加架构概念；后续为实现迭代（数据源拆分规则、Goal 启发式、Supporting 触发、缓存等，见 §十一）。

**v1.0 冻结前四项契约修正（评审采纳）：**
1. SubGoalBinding 字段校验 = **Composition/Planning-time**（SubGoal/Binding 由 Planner 组合，ECMC Compiler 不知其结构）
2. 区分 **Planning-time binding invalid（PLAN_INVALID）** vs **Execution-time upstream failure → downstream BLOCKED + 失败传播**
3. 跨 SubGoal 数据依赖纳入**最终 Plan DAG 校验**（Final DAG = Fragment 内部边 + 控制依赖 + 数据依赖 + 条件边，整体无环）
4. from_output → to_input **Schema 兼容校验**（Phase 1 不做 LLM 随意转换；future 可加 registered_transform）

**文档修正**：6.x 重排（6.1 版本冻结 / 6.2 Replanning / 6.3 数据绑定 / 6.4 输出契约）；origin 统一为 origin_clause；§十一 降级为 Implementation Follow-ups / Phase 2。
