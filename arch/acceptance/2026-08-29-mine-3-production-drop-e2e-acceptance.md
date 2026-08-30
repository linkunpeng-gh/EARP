# 3 号矿产量下降诊断——端到端案例验收规格

**文档编号：ACCEPT-EARP-MINE3-PRODUCTION-DROP-001**

**版本：v0.3（Fixture Contract Remediation / 待业务确认）**

**日期：2026-08-29**

**状态：验收骨架已评审，Golden Fixture 待冻结，尚未进入执行**

> 架构基线：`arch/design/2026-08-28-planning-blueprint-l3-design.md`（v1.0，Architecture Frozen）、`arch/design/2026-08-28-planner-runtime-l3-design.md`、`arch/design/2026-08-28-causal-reasoning-engine-l3-design.md`、`arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`。
>
> 本文不是新的架构设计。它把冻结契约转化为一个可执行、可判定的真实业务案例。文中标记为 `TBD` 的业务口径、模型结构和阈值必须由 FDE/业务专家确认后，才能成为正式验收基线。
>
> v0.2 Acceptance Patch：① 增加 Golden Model + Algorithm Fixture；② Evaluate 等待全部已规划 Evidence Acquisition Task 进入业务终态；③ 收口 complete/partial/failed 语义；④ 固定 Intent/Goal Resolution 的 LLM 测试边界；⑤ 增加 Causal Blueprint 不预编译动态 Evidence 的负向断言；⑥ 拆分 required/optional Provider 未绑定；⑦ 区分 Audit Replay 与 Executable Replay；⑧ 编译幂等降为 Extended Gate。
>
> v0.3 Fixture Contract Remediation：① Fixture 明确提供兼容现有 Ontology 服务的 data-domain、TBox、relation 与 ABox 前置导入合同；② Evidence Requirement 的实例目标由 Prepare 的结构化 ABox binding 表达式确定，Capability Resolution 仅选 Provider；③ 未构建的算法不再以伪 `implementation_hash` 冒充可执行 artifact；④ `published_fixture` 收口为 hash-locked 测试发布标签，不等同业务/生产发布；⑤ T05 只能校验既有 hash，不能静默重算或替换。

---

# 一、验收目标

使用真实业务问题：

> **“为什么 3 号矿昨天产量下降？”**

验证以下纵向链路能够闭环：

```text
用户请求
  → Intent / Goal Resolution
  → Blueprint Discovery
  → Goal Instantiation
  → knowledge_query Handler
  → Causal Reasoning Prepare
  → Evidence Requirements
  → Capability Resolution / 取证 Tasks
  → EvidenceObservation
  → Causal Reasoning Evaluate
  → Cause Ranking + Evidence Chain
  → Plan / Execution / Reasoning Trace / Final Answer
```

本案例重点回答三个问题：

1. Source Model 能否被确定性编译为不可变 BlueprintVersion。
2. Planner 能否把稳定的方法论转换成本次请求需要的动态取证任务。
3. 最终结论能否完整追溯到 Source Snapshot、Blueprint、Handler、观测与模型元素。

本轮通过只表示：

> **Planning Blueprint 的 Causal Diagnostic Vertical Slice 验收完成。**

不表示复杂 Step DAG、Decision Branch、Scenario Composition、Multi-Blueprint Composition 等 Blueprint Framework 全部能力已经验收。

---

# 二、验收范围

## 2.1 本轮范围（Case A：因果诊断）

本轮必须完成：

- 单一自然语言请求解析为一个 `diagnose` SubGoal。
- Published Causal Model Snapshot → Compiler → Causal BlueprintVersion。
- `knowledge_query` 在 Planning-time 调用 Reasoning Prepare。
- Prepare 动态产生本次诊断的 Evidence Requirements。
- Planner 将 Evidence Requirements 转换为取证 Tasks，并追加一个 Evaluate Task。
- Evaluate 等待所有已规划取证 Task（required + optional）进入业务终态。
- Runtime 通过确定性测试 Provider 产生 EvidenceObservation。
- Evaluate 输出 Cause Ranking、Evidence Chain、完整性状态和 Reasoning Trace。
- Execution Trace 串联 Request、SubGoal、BlueprintVersion、Plan、Task、Prepare 与 Reasoning Trace。

## 2.2 后续范围

### Case B：决策推荐

候选问题：

> “针对产量下降的首要原因，应该采取什么措施？”

使用 Decision Model 消费 Case A 的 Cause Ranking，验证备选方案、约束、规则评估与 Recommendation 输出。本 Case 不阻塞 Case A 验收。

### Case C：业务方法组合

候选问题：

> “分析 3 号矿昨天产量下降的原因，并给出处置建议。”

使用 Scenario Model 组合 Causal Model 与 Decision Model，验证 Compound Intent、多个 SubGoal、多个 BlueprintVersion 和 Plan Composition。本 Case 不阻塞 Case A 验收。

## 2.3 本轮非目标

- UI 展示与交互体验。
- 全量真实 MES/EAM/IoT 集成。
- 性能、容量、压测与高可用。
- Intent semantic index/pgvector 调优。
- Blueprint 缓存策略。
- 自动学习或模型反馈闭环。
- 在线 LLM 的自然语言理解准确率与提示词鲁棒性（另设 Semantic Evaluation）。
- 使用 LLM 自由生成模型关系、业务规则或执行步骤。
- Workflow 的重试、超时、并发和审批编排。

---

# 三、术语与模型范围

本文暂将“业务模型”映射为 ECMC 的 **Scenario Model**。如果项目中的“业务模型”另有正式定义，需在评审本规格时替换此映射（`TBD-BIZ-001`）。

| 模型 | Case A | Case B | Case C | 定位 |
|---|---:|---:|---:|---|
| Causal Model | 必需 | 作为上游结果来源 | 必需 | 解释产量下降的原因网络及证据需求 |
| Decision Model | 不参与 | 必需 | 必需 | 根据原因、约束和目标选择处置方案 |
| Scenario Model（业务模型） | 可选最小版 | 可选 | 必需 | 描述完整业务方法并显式组合多个模型 |

原则：不为了“同时覆盖三种模型”而把三个模型强行塞进 Case A。每个 Case 只引入对其业务目标必要的模型。

---

# 四、固定业务上下文

以下为初始建议值，正式执行前需要确认。

| 字段 | 初始值 | 状态 |
|---|---|---|
| tenant | `tenant-mine-demo` | TBD |
| 用户问题 | 为什么 3 号矿昨天产量下降？ | 固定 |
| request_time | `2026-08-29T09:00:00+08:00` | TBD |
| timezone | `Asia/Shanghai` | TBD |
| entity_id | `mine-3` | TBD：确认是矿山、矿区、采区还是生产单元 |
| entity_type | `mine` | TBD |
| business_objective | `diagnose` | 固定 |
| entry_point | `production_output` | TBD：确认企业语义词汇中的稳定键 |
| direction | `down` | 固定 |
| domain | `production` | TBD |
| time_window | `2026-08-28T00:00:00+08:00` 至 `2026-08-29T00:00:00+08:00` | TBD：应替换为正式生产日/班次口径 |
| reasoning_mode | `explainable` | TBD |
| explain_level | `detailed` | 固定候选 |

## 4.1 “产量下降”的判定口径

当前示例假设：

```text
actual_output < comparison_baseline × (1 - drop_threshold)
```

需要业务确认：

- comparison_baseline 是计划值、前一生产日、近 7 日均值还是同比值。
- drop_threshold 的正式阈值。
- 是否按日、班次、采区或产线统计。
- 计划检修、停产指令等已知事件是否从异常判断中排除。

以上内容属于 Source Model/业务指标定义，不得在 Blueprint 或测试代码中另写一份业务规则。

## 4.2 Intent / Goal Resolution 确定性夹具

第一轮自动化 E2E 保留真实 Intent/Goal Parser 与结构校验逻辑，但所有非确定性的 LLM 调用必须由固定 Fixture/Stub 替代，不调用线上商业模型。

固定 Stub 输出：

```yaml
parsed_intent:
  primary_intent:
    entry_point: production_output
    direction: down
    domain: production
    business_objective: diagnose
  objective_candidates: []
sub_goals:
  - sub_goal_id: sg-diagnose-production-drop
    objective: diagnose
    entry_point: production_output
    direction: down
    domain: production
    origin_clause: 为什么 3 号矿昨天产量下降
    confidence: 1.0
    priority: 1
    dependencies: []
resolved_context:
  entity_id: mine-3
  entity_type: mine
  time_window:
    start: 2026-08-28T00:00:00+08:00
    end: 2026-08-29T00:00:00+08:00
```

Fixture 还必须记录 `prompt_version + structured_output_schema_version + fixture_hash`。线上 LLM 的自然语言理解质量另设 Semantic Evaluation，不纳入本轮 G1–G5，以避免模型漂移造成 E2E flaky。

---

# 五、Source Model 前置条件

## 5.1 Causal Model（Case A 必需）

建议初始身份：

```text
model_id: causal-production-drop-mine
version: 1.0.0
status: published
published_snapshot_id: TBD
content_hash: TBD
```

### 5.1.1 候选节点

| node_key | 类型/角色 | 说明 | 确认状态 |
|---|---|---|---|
| `production_output` | effect / entry point | 目标产量 | TBD |
| `equipment_availability` | cause/intermediate | 关键生产设备可用率 | TBD |
| `haulage_cycle_time` | cause/intermediate | 运输循环时间 | TBD |
| `haulage_queue_time` | cause/intermediate | 装卸/运输排队时间 | TBD |
| `ore_quality` | cause/intermediate | 原矿质量或品位 | TBD |
| `effective_production_capacity` | intermediate | 本次时间窗有效产能 | TBD |

### 5.1.2 候选因果关系

以下仅作为建模起点，不构成已确认业务知识：

```text
equipment_availability   → effective_production_capacity → production_output
haulage_cycle_time       → effective_production_capacity → production_output
haulage_queue_time       → effective_production_capacity → production_output
ore_quality              → production_output
```

每条关系必须在正式模型中补充：方向、作用符号、适用范围、规则/阈值、解释文本和稳定 relation key。

### 5.1.3 候选 Evidence Requirements

| requirement_key | node_key | level | 逻辑数据需求 | capability_contract_ref |
|---|---|---|---|---|
| `production_actual_and_baseline` | `production_output` | required | 实际产量与比较基线 | `production_metric_query` |
| `critical_equipment_availability` | `equipment_availability` | required | 关键设备可用率及停机记录 | `equipment_health_query` |
| `haulage_cycle_observation` | `haulage_cycle_time` | required | 运输循环时间 | `haulage_operation_query` |
| `haulage_queue_observation` | `haulage_queue_time` | optional | 装卸点/运输排队时间 | `haulage_operation_query` |
| `ore_quality_observation` | `ore_quality` | optional | 原矿质量/品位 | `quality_metric_query` |

`requirement_level`、时间粒度、聚合方式、单位和实例绑定表达式均为 `TBD`，由 FDE 确认后写入 Causal Model Snapshot。

### 5.1.5 Case A Ontology 与实例绑定合同

Case A Fixture 必须按现有 Ontology 服务支持的顺序提供并导入最小前置条件：

```text
data_domains → TBox entity_types / relation_types → ABox entities / facts
```

`mine`、`haulage_system`、`equipment_group` 及 `has_subsystem`、
`has_equipment_group` 是本 Case 的最小 TBox；Fixture 的指标目录只是推理 Fixture
metadata，当前 Ontology TBox 没有 metric table，T05 不得声称通过既有 TBox/ABox API
导入指标定义。

每个 Evidence Requirement 的 `instance_binding` 使用
`case-a-abox-binding/v1`：`context_entity` 直接绑定请求实体，或从
`context.entity_id` 经指定 outbound relation 解析唯一目标实体（`cardinality=exactly_one`）。
Prepare 负责解析并持久化 target entity；Capability Resolution 只能将逻辑 contract 绑定到
Provider，**不得**推断、补充或替换 target entity。Fixture 的 expected plan 与 Observation
必须回填并校验同一 Prepare 解析结果。

### 5.1.4 Snapshot 完整性

Published Snapshot 必须自包含：

- nodes、edges、rules；
- data requirements；
- logical capability requirements；
- applicability；
- entry point 与 objective support；
- snapshot/content hash。

Prepare 不得回查可编辑的 live model tables。

## 5.2 Decision Model（Case B 前置，本轮不执行）

建议占位身份：

```text
model_id: decision-production-drop-response
version: 0.1.0-draft
status: draft
```

待业务确认内容：

- 输入：Cause Ranking、证据完整度、影响范围和持续时间。
- 候选措施：调整运输调度、安排设备检修、调整生产计划等。
- Hard Constraints：安全、设备操作权限、生产控制审批。
- Soft Constraints：恢复速度、成本、产量影响。
- 决策规则、冲突处理和 recommendation 输出契约。

本模型不得在 Case A 验收前被虚构为 Published Model。

## 5.3 Scenario Model / 业务模型（Case C 前置，本轮可选）

建议占位身份：

```text
model_id: scenario-production-drop-diagnosis-and-response
version: 0.1.0-draft
status: draft
```

最小职责：

- 声明业务入口、目标和适用范围。
- 显式引用 Causal Model 与 Decision Model。
- 描述“先诊断、后决策、再输出”的业务方法依赖。
- 不描述重试、超时、并发、endpoint 或审批执行流程。

---

# 六、Golden Reasoning Fixture（确定性推理夹具）

Golden Result 不能只由业务直觉决定。正式启用 Top 1 断言前，必须同时冻结：

```text
Immutable Model Snapshot
  + Algorithm Version / Profile / Params
  + Edge Strength / Confidence
  + Rule / Observation Thresholds
  + Fixed EvidenceObservation
  = Machine-decidable Golden Result
```

如果本章任一必填项仍为 `TBD`，Case A 只能执行链路联调，不能判定 G4 的原因排序是否通过。

## 6.1 Model Snapshot Fixture

```yaml
model_id: causal-production-drop-mine
model_version: 1.0.0
model_snapshot_id: TBD-MODEL-SNAPSHOT
model_content_hash: TBD-MODEL-HASH
graph_type: dag
entry_point: production_output
direction: down
```

Snapshot 中所有参与候选原因路径的边必须冻结 `effect`、`strength` 和 `confidence`。初始候选如下，数值仅用于形成可讨论的 fixture，并非已确认业务知识：

| edge_key | source → target | effect | strength | confidence | 状态 |
|---|---|---:|---:|---:|---|
| `edge-equipment-capacity` | `equipment_availability → effective_production_capacity` | `+` | 0.85 | 0.95 | TBD |
| `edge-cycle-capacity` | `haulage_cycle_time → effective_production_capacity` | `-` | 0.90 | 0.95 | TBD |
| `edge-queue-capacity` | `haulage_queue_time → effective_production_capacity` | `-` | 0.80 | 0.95 | TBD |
| `edge-capacity-output` | `effective_production_capacity → production_output` | `+` | 0.95 | 0.98 | TBD |
| `edge-quality-output` | `ore_quality → production_output` | `+` | 0.55 | 0.90 | TBD |

## 6.2 Algorithm Fixture

```yaml
algorithm_id: sign_propagation
algorithm_version_id: TBD-ALGORITHM-VERSION-ID
algorithm_version: 1.0
implementation_artifact:
  status: not_built
  sha256: null
  required_before_executable_evaluate: true
algorithm_profile_version: TBD-PROFILE-VERSION
profile:
  graph_type: dag
  max_depth: 3
algorithm_params: {}
algorithm_config_hash: TBD-ALGORITHM-CONFIG-HASH
score_contract:
  path_score: abs(product(edge.strength)) * product(edge.confidence) * obs_match(path)
  node_aggregation: max_path_score
  tie_breaker: TBD
```

`not_built` 表示该 Fixture 目前是算法**规格**，不是可执行 artifact。T05 只能验证
`algorithm_config_hash` 和 `not_built` 状态，既不能生成 placeholder hash，也不能因为导入
而重新 hash。T11 实现可执行算法时，必须显式发布新的 executable Fixture version，记录
可重复计算的 artifact hash/scope，并原子更新语义 hash、file hash 与 package hash。

以下规则也必须进入 Snapshot 或不可变 Algorithm Config，不能只写在验收代码中：

| rule_key | 初始候选规则 | 状态 |
|---|---|---|
| `rule-output-down` | 产量相对基线下降 ≥ 10% 判定为 `down` | TBD |
| `rule-equipment-unchanged` | 可用率 ≥ 95% 判定为 `unchanged/normal` | TBD |
| `rule-cycle-up` | 循环时间相对基线上升 ≥ 20% 判定为 `up` | TBD |
| `rule-queue-up` | 排队时间相对基线上升 ≥ 50% 判定为 `up` | TBD |
| `rule-quality-unchanged` | 品位相对基线变化绝对值 < 5% 判定为 `unchanged` | TBD |

## 6.3 Evidence Observation Fixture

下表用于形成第一版 Golden Case，所有数值、单位、时间窗和质量状态均需确认并转成完整 EvidenceObservation Envelope。

| 观测 | 固定值 | 固定基线 | quality | 预期方向解释 |
|---|---:|---:|---|---|
| 实际产量 | 8,200 t | 10,000 t | valid | `down`，下降 18% |
| 关键设备可用率 | 96% | 95% | valid | `unchanged/normal`，不应成为首因 |
| 运输循环时间 | 51 min | 38 min | valid | `up`，显著异常 |
| 平均排队时间 | 17 min | 6 min | valid | `up`，显著异常 |
| 原矿品位 | 1.15（单位 TBD） | 1.16 | valid | `unchanged/normal`，不应成为首因 |

Golden Case 的所有 planned required 和 optional Evidence Acquisition Tasks 都必须返回 `valid` Observation；因此正常结果必须满足：

```text
status: COMPLETE
complete: true
missing_requirements: []
Top 1 Cause: 运输能力/运输拥堵相关原因（正式 node_key TBD）
Evidence Chain 至少包含：
  haulage_cycle_time 或 haulage_queue_time
    → effective_production_capacity
    → production_output
```

## 6.4 Golden Result 激活条件

Top 1 机器断言只有在以下条件全部满足后才能进入 CI：

- `model_snapshot_id + content_hash` 已冻结；
- Algorithm Version、Profile、Params、Config Hash 与可重复定位的 Implementation Artifact Hash 已冻结；
- 所有候选路径的 edge effect/strength/confidence 已冻结；
- direction/unchanged/baseline rules 已冻结；
- 所有 required + optional Observations 均固定且为 valid；
- FDE 用相同 fixture 独立确认 Top 1 与 Evidence Chain；
- 排名相同时的 tie-breaker 已定义。

第一阶段可暂不对 score/confidence 的绝对值做断言，但必须断言 Top 1、Evidence Chain、`complete=true` 和全部版本/hash 字段。算法契约稳定后再增加分数容差。

---

# 七、预期 Blueprint 编译产物

## 7.1 Logical Blueprint 与 Version

建议稳定身份：

```text
blueprint_id: bp-production-drop-diagnosis
blueprint_version_id: 运行时生成
version: 与 Source Snapshot/Compiler 输入对应的不可变版本
status: compiled
compile_record_id: 必填
source_fingerprint: Phase 1 Extended（建议）
```

若实现 `source_fingerprint`，至少覆盖 Source Snapshot hashes、Compiler version 和 Compiler config hash；它用于编译幂等优化，不作为 Case A Core Gate 的必要条件。

## 7.2 预期 Intent

```yaml
entry_point: production_output
direction: down
domain: production
business_objective: diagnose
```

## 7.3 预期 Goal Skeleton

```text
objective: diagnose
goal_template: 分析 {entity} 在 {time_window} 的产量下降原因
required_bindings: [entity, time_window]
output_contract_ref: cause-ranking-output
```

Validator 必须确认 `constraint_refs` 与 `output_contract_ref` 都属于同一 BlueprintVersion。

## 7.4 预期 Steps

Case A 的最小产物建议包含：

```text
knowledge_query
  → output
```

- `knowledge_query` 引用 Causal Source Model Snapshot 中的稳定 entry point/模型元素。
- Step 必须 pin `step_type_version_id`、handler version 和 handler hash。
- `output` 使用 `cause_ranking` Output Contract。
- Blueprint 不预编译节点级 Evidence Capability；具体 Evidence Requirements 由 Prepare 动态产生。

---

# 八、G1–G5 验收门槛

## G1：Knowledge Compilation（模型发布与 Blueprint 编译）

执行：

1. 发布确认后的 Causal Model Snapshot。
2. 创建 Compile Record，状态从 `running`（或最终实现采用的等价初始态）进入 `success`。
3. 创建 Logical Blueprint（首次）与不可变 BlueprintVersion。
4. 写入 Intent、Goal Skeleton、Steps、Deps、Sources、Constraints 和 Output Contract。

通过条件：

- Compile Record 保留输入快照、Compiler 配置与校验结果。
- BlueprintVersion pin `source_snapshot_id + source_content_hash`。
- 所有子对象归属同一 BlueprintVersion。
- Steps pin StepType Handler Version。
- 同一 Logical Blueprint 最多一个 `compiled` 版本。
- 编译失败不创建 BlueprintVersion。
- Causal Blueprint 只编译稳定的 `knowledge_query` 方法，不得把节点级 Evidence Requirements 静态展开为 `blueprint_capability_requirements`。
- `equipment_health_query`、`haulage_operation_query`、`quality_metric_query` 等本次动态取证需求不得在 Prepare 之前出现在 Blueprint；唯一例外是 Source Model 明确声明的 model-level hard requirement。

Extended Gate（不单独决定 Case A Core Pass/Fail）：

- 若 Phase 1 实现 `source_fingerprint`，相同 Source Snapshot、Compiler 与配置再次编译，应返回已有版本或等价幂等结果，不创建内容相同的新 BlueprintVersion。

## G2：Planning Entry（Goal Resolution 与 Blueprint Discovery）

输入固定用户问题与上下文；Intent/Goal Parser 使用 §4.2 的确定性 LLM Stub 输出。

通过条件：

- 产生且只产生一个 SubGoal。
- `objective=diagnose`、`direction=down`、`domain=production`。
- Discovery 只返回可见且适用的唯一当前 compiled BlueprintVersion。
- Goal Instantiation 正确绑定 `mine-3` 与固定 time window。
- 未提前产生取证 Task。
- 测试报告记录 `prompt_version + structured_output_schema_version + fixture_hash`，不记录或依赖在线 LLM 的临时响应。

## G3：Dynamic Planning（Reasoning Prepare 与 PlanFragment）

执行 `knowledge_query` Handler，在 Planner 解释期调用 Prepare。

通过条件：

- 生成持久化 `prepare_id`。
- ReasoningContext pin model version、snapshot/hash、实例图、算法版本/参数和权限范围。
- Evidence Requirements 包含唯一的 `requirement_id` 与稳定的 `requirement_key`。
- Prepare 只声明逻辑需求，不检查 Provider、Connector 或 Credential 是否在线。
- Capability Resolver 在 Planner 层完成物理绑定。
- PlanFragment 为 `0..N` 个取证 Task + `1` 个 Evaluate Task。
- Evaluate Task 依赖本次**所有已规划 Evidence Acquisition Tasks**进入业务终态，包括 required 和 optional。
- 取证业务终态至少包括：`success + value`、`success + DATA_UNAVAILABLE`、`success + stale/suspicious`。
- required/optional 决定 Evaluate 的 COMPLETE/PARTIAL/FAILED 结果语义，不决定是否等待该已规划 Task。
- Runtime/Executor 等基础设施故障不属于取证业务终态；该 Task 应为 FAILED，并使 Evaluate BLOCKED。

## G4：Reasoning Execution（Runtime 取证与 Reasoning Evaluate）

第一轮使用确定性测试 Provider 返回第六章的观测数据。

通过条件：

- 每条 EvidenceObservation 按 `requirement_id` 关联 Prepare 需求。
- Observation 包含 unit、time window、source、quality 和 provenance。
- Evaluate 启动前，所有已规划 Evidence Acquisition Tasks 都已进入业务终态。
- Evaluate 消费同一个 `prepare_id`，不得重新实例化或切换算法。
- Evaluate 使用 §6 冻结的 Algorithm Version/Profile/Params 与 Model Snapshot，不得使用当前默认版本替代。
- Cause Ranking 的 Top 1 与确认后的 Golden Result 一致。
- Evidence Chain 能解释从异常运输指标到产量下降的路径。
- Golden Case 中全部 required + optional Observation 均有效，因此返回 `status=COMPLETE`、`complete=true`、空 missing requirements 和 `reasoning_trace_id`。
- required missing → FAILED/422；optional missing → PARTIAL/`complete=false`，不得以 required 全部有效推导 `complete=true`。

## G5：Auditability（Trace、审计复现与版本隔离）

通过条件：

- 可从最终响应追溯到 Request、SubGoal、BlueprintVersion、Compile Record、Source Snapshot、StepType Handler、Plan、Task、EvidenceObservation 和 Reasoning Trace。
- 相同 `prepare_id + evaluation_input_hash` 重试返回已有结果。
- 不同输入不得复用已消费的 `prepare_id`。
- 数据库拒绝跨 BlueprintVersion 的 StepDep 与 StepSource。

Phase 1 MUST——Audit Replay：

- 使用归档 Source Snapshot、BlueprintVersion、ReasoningContext、EvidenceObservation、Reasoning Trace 与版本/hash 元数据，完整还原“当时使用了什么输入、实现和规则，以及为什么得到该结果”。
- Audit Replay 是审计复现，不要求重新执行已经下线的旧代码。

Phase 2 SHOULD——Executable Replay：

- 旧 Algorithm 与 StepType Handler artifact 仍然可定位、可加载、可运行。
- 使用同一 Snapshot、Context、Evidence、Algorithm/Handler 版本和参数重新执行，得到契约等价结果。
- 仅保存 implementation/handler hash 而没有可运行 artifact，不得宣称支持 Executable Replay。

---

# 九、异常路径验收

| 编号 | 场景 | 预期结果 |
|---|---|---|
| N-01 | required evidence 数据不可用 | 取证 Task 正常完成并产生带 `DATA_UNAVAILABLE` 的 Observation；Evaluate 返回 FAILED/422 与 missing requirements |
| N-02 | optional evidence 数据不可用 | 该 Task 以 `success + DATA_UNAVAILABLE` 进入业务终态；Evaluate 等待它后返回 PARTIAL/`complete=false`，不得伪造完整结果 |
| N-03A | required requirement 的 Provider 未绑定 | 本 Case 的 Fail-Closed Policy Fixture 下产生 planning failure，不生成可执行 Plan；若未来验证其他 fallback，必须另建明确预期的子用例，不得把 required 当 optional |
| N-03B | optional requirement 的 Provider 未绑定 | 仍允许构造 Plan；为该需求形成 unavailable/missing optional 的业务结果；Evaluate 等待取证阶段终结后返回 PARTIAL/`complete=false` |
| N-04 | Runtime/Executor 基础设施故障 | Task FAILED，Evaluate BLOCKED；不得伪装成业务数据缺失 |
| N-05 | `prepare_id` 过期或取消 | Evaluate 拒绝消费 |
| N-06 | 同一 `prepare_id` 使用不同 Evaluation Input | 拒绝并要求新 Attempt/重新 Prepare |
| N-07 | Policy 禁止降级 | Fail Closed，不走 direct model reasoning |
| N-08（Extended） | 编译相同 source fingerprint | 若 Phase 1 实现编译幂等，则返回已有版本或等价幂等结果，不新增重复 BlueprintVersion；未实现不影响 Core Gate |
| N-09 | 发布新 BlueprintVersion | 同一事务内旧版本 `compiled → superseded`、新版本 → `compiled` |
| N-10 | 写入跨版本 StepDep/StepSource | 数据库复合 FK 拒绝 |
| N-11 | Goal Skeleton 引用其他版本的 Constraint/Output | Compiler Validator 拒绝 |

---

# 十、验收执行策略

## 10.1 第一轮：确定性纵向切片

使用：

- 固定 `published_fixture` Source Snapshot（仅 hash-locked 测试输入，不是领域或生产发布）；
- 固定 Golden Algorithm Version/Profile/Params 与 Reasoning Fixture；
- 确定性 Compiler；
- 真实 Intent/Goal Parser 逻辑 + Deterministic LLM Fixture/Stub；
- Mock Capability Resolver；
- Mock 生产、设备、运输、质量 Provider；
- 真实 Planner 组合逻辑；
- 真实 Reasoning Prepare/Evaluate；
- 真实数据库约束和 Trace。

第一轮只验证职责、数据契约、版本隔离、结果解释与追溯，不验证外部系统可用性。

第一轮组件边界必须保持：

```text
假的企业外部环境与非确定性 LLM 响应
+
真的 Compiler / Planner / Prepare / Evaluate / DB Constraints / Trace
```

不得用 Mock Reasoning Result 绕过 Prepare/Evaluate，也不得用 Mock Plan 直接跳到 Runtime。

## 10.2 第二轮：替换一个真实 Provider

G1–G5 全部通过后，只选择一个数据源替换 Mock，建议优先接入生产指标或运输指标。其余 Provider 继续使用固定夹具，以便隔离集成问题。

## 10.3 第三轮：扩展 Case B / Case C

按顺序进行：

```text
Case A 因果诊断通过
  → Case B 决策推荐
  → Case C Scenario 多模型组合
```

每新增一个 Case，均使用独立 Golden Dataset 和验收报告，不修改 Case A 的已冻结事实。

---

# 十一、交付物与完成定义

执行阶段应将本文中的内嵌示例物化为机器可读夹具，建议目录：

```text
tests/scenarios/mine_3_production_drop/
├── scenario.yaml
├── intent_goal_fixture.json
├── causal_model_snapshot.json
├── algorithm_fixture.json
├── evidence_observations.json
├── expected_reasoning.json
└── acceptance_report.json
```

文档与夹具存在差异时，以已评审且带 hash 的机器可读 fixture 为执行权威，并回写本文的对应标识；不得让两套 Golden Facts 独立演进。

## 11.1 本规格评审完成条件

- 所有 `TBD` 有 owner 和处理结论。
- FDE 确认节点、关系、edge strength/confidence、规则、Evidence Requirements 和 Golden Result。
- Algorithm 负责人冻结 Algorithm Version/Profile/Params、score contract 和 tie-breaker；进入 T11 executable Evaluate 前再冻结可重复定位的 Implementation Artifact Hash。
- 数据负责人确认指标口径、单位、时间窗和可取得性。
- Planner 负责人确认 Intent/Goal LLM Fixture、Prompt/Schema Version 和 fixture hash。
- Compiler、Planner、Reasoning、Runtime 负责人确认边界与验收断言可实现。
- 明确 Case A 不依赖 Decision/Scenario Model 完成。

## 11.2 Case A 执行完成条件

一条自动化命令能够：

1. 装载或定位 Published Causal Snapshot；
2. 编译并加载 BlueprintVersion；
3. 提交固定请求；
4. 产生取证 Plan；
5. 注入固定 EvidenceObservation；
6. 输出符合 Golden Result 的 Cause Ranking；
7. 校验完整 Trace、Audit Replay 与异常路径；
8. 生成机器可读和人工可读验收报告。

只有 G1–G5 Core Gate 全部通过，Case A 才可标记为：

> **Planning Blueprint Causal Diagnostic Vertical Slice — Accepted**

不得将结果表述为“Planning Blueprint Framework 全部能力验收完成”。Extended Compiler Idempotency 和 Phase 2 Executable Replay 分别单独记录，不阻塞 Core 结论。

---

# 十二、待业务确认清单

| ID | 待确认项 | 建议责任人 | 结论 |
|---|---|---|---|
| TBD-BIZ-001 | “业务模型”是否等同 ECMC Scenario Model | 架构负责人/FDE | 待确认 |
| TBD-BIZ-002 | `mine-3` 的正式实体类型和企业语义标识 | FDE/本体负责人 | 待确认 |
| TBD-BIZ-003 | “昨天”的生产日、班次和时区口径 | 生产业务负责人 | 待确认 |
| TBD-BIZ-004 | 产量下降的基线与阈值 | 生产业务负责人 | 待确认 |
| TBD-MODEL-001 | Causal nodes、relations、rules 的正式定义 | FDE/领域专家 | 待确认 |
| TBD-MODEL-002 | Evidence requirement required/optional 分类 | FDE/领域专家 | 待确认 |
| TBD-MODEL-003 | Golden Snapshot 中 edge effect/strength/confidence | FDE/领域专家 | 待确认 |
| TBD-ALGO-001 | Algorithm Version/Profile/Params/Implementation Hash | Reasoning 负责人 | 待确认 |
| TBD-ALGO-002 | score contract、阈值与 tie-breaker | Reasoning 负责人/FDE | 待确认 |
| TBD-DATA-001 | 指标单位、粒度、聚合和数据质量规则 | 数据负责人 | 待确认 |
| TBD-DATA-002 | Golden Dataset 的数值与数据来源 | 数据负责人/FDE | 待确认 |
| TBD-RESULT-001 | 首因与 Evidence Chain 的业务正确性 | 领域专家 | 待确认 |
| TBD-POLICY-001 | 缺证据时的 fallback/Fail Closed 策略 | Policy/业务负责人 | 待确认 |
| TBD-LLM-001 | Intent/Goal Stub、Prompt/Schema Version 与 fixture hash | Planner 负责人 | 待确认 |

---

# 十三、验收结果记录（执行时填写）

| Gate | 结果 | 证据链接/产物 | 缺陷编号 |
|---|---|---|---|
| G1 Knowledge Compilation | Not Run | — | — |
| G2 Planning Entry | Not Run | — | — |
| G3 Dynamic Planning | Not Run | — | — |
| G4 Reasoning Execution | Not Run | — | — |
| G5 Auditability | Not Run | — | — |
| Extended Compiler Idempotency | Not Run | — | — |
| Phase 2 Executable Replay | Not Run | — | — |

**最终结论：Not Run**
