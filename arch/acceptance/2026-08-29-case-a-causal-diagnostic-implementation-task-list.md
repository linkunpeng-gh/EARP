# Case A 因果诊断纵向切片——实施任务清单

**文档编号：TASK-EARP-CAUSAL-DIAG-001**

**版本：v0.1**

**日期：2026-08-29**

**状态：Ready for Execution**

> 目标案例：“为什么 3 号矿昨天产量下降？”
>
> 验收基线：`arch/acceptance/2026-08-29-mine-3-production-drop-e2e-acceptance.md`（v0.2）。
>
> 架构基线：Planning Blueprint L3 v1.0、Planner Runtime L3、Causal Reasoning Engine L3、ECMC 总体设计。
>
> 本清单用于逐个独立会话执行。每个任务只交付一个可验证增量；除非发现核心职责边界冲突，否则不得重新开启宏观架构评审。

---

# 一、执行规则

1. 严格按任务依赖顺序执行；依赖未通过时，不开始后续任务。
2. 每个会话开始时先读取本任务、验收规格、相关实现和仓库协作说明。
3. 每个实现任务必须同时提交自动化测试，不接受“代码先写、测试以后补”。
4. 优先复用现有 Ontology、Capability Registry、Orchestrator、Audit、Checkpoint、RLS 和 Testcontainers 基础设施。
5. 第一阶段使用固定 Fixture、Mock Provider 和 Deterministic LLM Stub，不调用线上 LLM。
6. 不为 Case A 提前实现 Decision Model、Scenario Composition、复杂 DAG Scheduler 或管理后台。
7. 发现冻结文档中的普通实现问题时，记录为 implementation erratum；只有改变核心职责边界时才升级为架构决策。
8. 完成任务后更新本清单状态，并记录主要文件、测试命令和结果。

新会话建议直接使用以下指令：

```text
执行 arch/acceptance/2026-08-29-case-a-causal-diagnostic-implementation-task-list.md
中的 Txx。先核验前置依赖，只完成该任务的目标、内容和验收标准，严格遵守
范围边界。完成后运行相关测试，更新任务状态，并报告文件、测试结果和遗留项。
```

---

# 二、优先级与依赖总览

| 顺序 | ID | 优先级 | 任务 | 依赖 | 对应 Gate | 状态 |
|---:|---|---|---|---|---|---|
| 0 | T00 | P0 | 固化当前架构与验收基线 | 无 | 前置 | Delivered — baseline commit deferred (shared dirty worktree) |
| 1 | T01 | P0 | 冻结业务上下文与因果知识 | T00 | 前置 | Delivered — provisional assumptions; domain confirmation pending |
| 2 | T02 | P0 | 生成机器可读 Golden Fixture | T01 | 前置 | Delivered — provisional fixture package validated |
| 3 | T03 | P0 | 编写 Case A 实施 PRD | T02 | 前置 | Delivered — v1.0 |
| 4 | T04 | P0 | 建立 Case A 数据库 Schema 与 RLS | T03 | G1 | Delivered — migrations 0035–0037 and RLS contract tests |
| 5 | T05 | P0 | 实现 Causal Snapshot 导入、校验与发布 | T04 | G1 | Delivered — fixture-only import; see T05 handoff |
| 6 | T06 | P0 | 实现 StepType Registry 与 Causal Blueprint Compiler | T05 | G1 | Delivered — deterministic Case A compiler and G1 contract tests |
| 7 | T07 | P0 | 实现确定性 Planning Entry | T06 | G2 | Delivered — isolated fixture-backed entry, discovery, and Goal instantiation |
| 8 | T08 | P0 | 实现 Reasoning Prepare 与 ReasoningContext | T07 | G3 | Delivered — provider-free pinned Prepare; see T08 handoff |
| 9 | T09 | P0 | 实现 Capability Resolution 与 PlanFragment 投影 | T08 | G3 | Delivered — fixture-backed binding and DAG-validated fragment |
| 10 | T10 | P0 | 实现 Evidence Acquisition 业务终态语义 | T09 | G3/G4 | Delivered — business terminal vs infrastructure failure contract |
| 11 | T11 | P0 | 实现 sign_propagation_v1 Evaluate | T10 | G4 | Delivered — pinned Evaluate; container-verified in final suite |
| 12 | T12 | P0 | 实现 Trace、幂等与 Audit Replay | T11 | G5 | Delivered — audit-only replay, idempotency and tamper detection |
| 13 | T13 | P0 | 完成 Case A 自动化 E2E 与验收报告 | T12 | G1–G5 | Delivered — 45 Case A checks passed; report dated 2026-08-30 |
| 14 | T14 | P1 | 接入一个真实只读数据 Provider | T13 | Pilot | Not Started |
| 15 | T15 | P2 | 启动 Case B 决策推荐验收设计 | T13 | 后续 | Not Started |

P0 的完成定义：T00–T13 全部通过，Case A 才能标记为 `Causal Diagnostic Vertical Slice — Accepted`。

---

# 三、P0 前置任务

## T00——固化当前架构与验收基线

**优先级：P0**

**依赖：无**

### 目标

把已经完成的 Planning Blueprint v1.0 和 Case A 验收规格 v0.2 固化为清晰、可追溯的开发基线，避免后续会话基于未提交或版本不一致的文件工作。

### 工作内容

- 检查当前工作区所有已修改和未跟踪文件。
- 确认 Planning Blueprint 文档标题、版本和冻结声明为 v1.0。
- 确认 Case A 验收规格为 v0.2，包含本轮评审的 P0/P1 修正。
- 检查相关讨论记录是否应纳入本次基线。
- 更新必要的文档索引或引用，确保路径可发现。
- 创建一个只包含本轮架构冻结和验收规格的清晰提交；不得夹带无关代码变更。

### 交付物

- Planning Blueprint v1.0 基线文件。
- Case A Acceptance v0.2 基线文件。
- 必要的索引/引用更新。
- 一个可定位的基线 commit。

### 验收标准

- `git status` 中不存在属于本轮基线但未纳入提交的文件。
- 基线提交不包含无关功能代码或临时文件。
- 文档内部版本、标题、状态和引用一致。
- `git diff --check` 通过。
- 后续任务可以通过固定 commit 定位全部输入文档。

### 范围边界

- 不修改架构内容。
- 不实现任何 ECMC、Compiler、Planner 或 Reasoning 代码。

---

## T01——冻结业务上下文与因果知识

**优先级：P0**

**依赖：T00**

### 目标

解决验收规格中影响机器判定的业务 TBD，使“3 号矿产量下降”成为定义明确、结果可判断的业务案例。

### 工作内容

- 确认 `mine-3` 的正式实体类型、标识和适用范围。
- 确认“昨天”的时区、生产日和班次口径。
- 确认产量下降的比较基线、阈值、单位和聚合方式。
- 确认 Causal Model 的节点、稳定 node key、边和适用范围。
- 确认每条边的 `effect`、`strength`、`confidence` 和必要解释。
- 确认 direction、unchanged、baseline 等规则和阈值。
- 确认 Evidence Requirement 的逻辑需求、required/optional、粒度、单位和实例绑定。
- 确认 Case A 的 Fail-Closed/Fallback Policy。
- 确认 Algorithm Version/Profile/Params、score contract 和 tie-breaker。
- 确认 Intent/Goal Stub 的 Prompt Version 和 Structured Output Schema Version。
- 确认 Golden Result 的 Top 1 原因和最低 Evidence Chain。
- 将确认结果回写验收规格，关闭相应 TBD。

### 交付物

- 经业务/FDE 确认的案例上下文。
- 经确认的 Causal Model 知识清单。
- 经确认的 Evidence Requirements。
- 更新后的 Acceptance v0.2 TBD 状态表。

### 验收标准

- `TBD-BIZ-*`、`TBD-MODEL-*`、`TBD-ALGO-*`、`TBD-DATA-*`、`TBD-RESULT-*`、`TBD-POLICY-*` 和 `TBD-LLM-*` 均有明确结论或书面延期理由。
- 每个参与排名的节点和边都有稳定 key。
- 每条参与排名的边都有 effect/strength/confidence。
- 每个 Evidence Requirement 明确 required 或 optional。
- 时间窗、基线、阈值和单位无歧义。
- FDE 能依据同一组事实独立说明为什么 Golden Top 1 应成立。

### 范围边界

- 不编写数据库迁移或业务代码。
- 不设计 Decision Model 或 Scenario Model。
- 不把尚未确认的业务假设标记为正式知识。

---

## T02——生成机器可读 Golden Fixture

**优先级：P0**

**依赖：T01**

### 目标

把已确认的业务事实、模型、算法、观测和期望结果转换为可被测试代码直接读取、校验和 hash 的确定性 Fixture。

### 工作内容

- 创建 `apps/earp-server/tests/scenarios/mine_3_production_drop/`。
- 创建固定 `scenario.yaml`。
- 创建 `intent_goal_fixture.json`，包含 Prompt/Schema Version 和 fixture hash 所需字段。
- 创建完整的 `causal_model_snapshot.json`。
- 创建 `ontology_fixture.json`，包含 `mine-3` 及 Prepare 实例化所需的最小 ABox 实体/关系。
- 创建 `capability_fixture.json`，包含逻辑 Capability Contract、Mock Provider 和 entity applicability。
- 创建 `algorithm_fixture.json`，包含 Algorithm Version/Profile/Params、实现标识、score contract 和 tie-breaker。
- 创建完整 EvidenceObservation Envelope 的 `evidence_observations.json`。
- 创建 `expected_plan.json`，以稳定 key 描述 acquisition/evaluate/output Task 及依赖，不断言运行时 ID。
- 创建 `expected_reasoning.json`，声明 Top 1、Evidence Chain、complete 状态和必要版本字段。
- 提供一个纯 Fixture 校验测试或脚本，检查必填字段、引用完整性、稳定排序条件和 hash。
- 确保 Fixture 内没有运行时生成 ID；需要动态 ID 的位置使用稳定匹配键或显式占位规则。

### 交付物

```text
apps/earp-server/tests/scenarios/mine_3_production_drop/
├── scenario.yaml
├── intent_goal_fixture.json
├── causal_model_snapshot.json
├── ontology_fixture.json
├── capability_fixture.json
├── algorithm_fixture.json
├── evidence_observations.json
├── expected_plan.json
├── expected_reasoning.json
└── README.md
```

以及 Fixture schema/validation test。

### 验收标准

- Fixture 可由测试代码无网络读取和解析。
- 所有 JSON/YAML 文件通过 schema 校验。
- Snapshot、Algorithm Config、Intent Fixture 和整个案例包都有稳定 hash。
- Ontology Fixture 足以从 `mine-3` 实例化 Case A 所需的目标图。
- Capability Fixture 能把全部 planned requirements 确定性解析到 Mock Provider。
- `expected_reasoning.json` 的 Top 1 能由固定模型、算法和观测唯一决定。
- 所有 planned required + optional Observations 都存在且 `quality.status=valid`。
- 重复运行 Fixture 校验得到相同 hash 和结果。
- 不依赖当前日期、随机数、在线 LLM 或外部数据源。

### 范围边界

- 不实现真实 Compiler 或 Reasoning Engine。
- 可以用独立参考计算验证 Golden Result，但不得把参考脚本当生产算法实现。

---

## T03——编写 Case A 实施 PRD

**优先级：P0**

**依赖：T02**

### 目标

把冻结架构和机器可读 Fixture 转化为一个可编码、可拆分、可测试的实施 PRD，作为 T04–T13 的共同工程合同。

### 工作内容

- 新建 `prd/PRD-2026-032-ecmc-causal-diagnostic-vertical-slice.md`。
- 明确 Case A G1–G5 的功能范围和 Out of Scope。
- 列出新增/修改的模块、迁移、路由、服务、模型和测试文件。
- 明确新模块与现有 domain 的依赖方向及 import-linter 例外。
- 定义最小 API/服务接口，包括 Snapshot import/publish、compile、discovery、prepare、evaluate 和 E2E entry。
- 定义实现期勘误：Compile Record 初始态、Goal Skeleton 同版本校验等。
- 明确 `source_fingerprint` 为 Core 还是 Extended；默认按 Acceptance v0.2 归 Extended。
- 处理 legacy `MAX_PLAN_DEPTH=5`：任务数量不得被误当成 Plan 图深度。
- 明确第一版顺序执行 Evidence Tasks，Evaluate 最后执行；暂不实现通用并行 Scheduler。
- 为 T04–T13 分别给出验收条件和测试映射。

### 交付物

- PRD-2026-032 v1.0。
- 文件/模块影响清单。
- 数据迁移清单。
- AC → Task → Test 映射表。

### 验收标准

- PRD 不再提出新的宏观架构问题。
- 所有 AC 都能映射到 T04–T13 中的某个自动化测试。
- 明确复用 Ontology、Capability Registry、Orchestrator、Audit 和 RLS 的位置。
- 明确不实现 Decision、Scenario、Admin UI、在线 LLM 和复杂 DAG Scheduler。
- Planner legacy 路径与 Blueprint 路径的兼容策略明确。
- PRD 评审后可以直接进入 T04，无未决 P0。

### 范围边界

- 只写实施 PRD，不修改生产代码。
- 不重新改写已冻结的 L3 架构文档。

---

# 四、G1——Knowledge Compilation

## T04——建立 Case A 数据库 Schema 与 RLS

**优先级：P0**

**依赖：T03**

### 目标

为 Case A 提供可迁移、可回滚、受租户隔离保护的数据持久化基础，并落实冻结设计中的版本和引用完整性约束。

### 工作内容

- 按 PRD 创建 Case A 所需最小 Causal Model、Snapshot、Algorithm Registry、Blueprint、Compile Record、ReasoningContext 和 ReasoningTrace 表。
- 为全部 tenant-scoped 表增加 `tenant_id`、RLS policy 和必要索引。
- 落实 Logical + Version 模型和不可变 Snapshot 引用。
- 落实 Blueprint 子表统一归属 `blueprint_version_id`。
- 落实 StepDep、StepSource 的复合唯一约束与复合 FK。
- 落实一个 Logical Blueprint 最多一个 `status='compiled'` 的 partial unique index。
- Compile Record 支持 `running → success|failed` 或 PRD 选定的等价状态机。
- ReasoningContext 支持 `prepared → consumed|expired|cancelled`。
- ReasoningTrace 落 Evaluation Input Hash 幂等键。
- 增加升级、降级、RLS、跨版本拒绝和唯一当前版本测试。

### 交付物

- Alembic migration。
- 必要的数据访问模型/Repository 骨架。
- Migration、RLS 和 Referential Integrity 测试。

### 验收标准

- 空库 `alembic upgrade head` 成功。
- `alembic downgrade -1` 后再升级成功。
- App role 无法跨 tenant 读写新增表。
- 数据库拒绝跨版本 StepDep 和 StepSource。
- 数据库拒绝同一 Logical Blueprint 同时存在两个 compiled 版本。
- 编译失败记录可以存在而无需 BlueprintVersion。
- 所有新增约束在 PostgreSQL Testcontainers 中真实验证，不用 SQLite 替代。
- 全量既有 migration/RLS 测试不回归。

### 范围边界

- 只建立 Case A 必需 Schema，不一次启用所有 Phase 2 表。
- 不实现业务服务和 API。

---

## T05——实现 Causal Snapshot 导入、校验与发布

**优先级：P0**

**依赖：T04**

### 目标

把 T02 的 Causal Model Fixture 作为完整、不可变、可发布的 Source Snapshot 装载到 ECMC，并保证生产推理不依赖可编辑 live 表。

### 工作内容

- 创建 `bmc`/`metamodel` 最小模块结构或 PRD 指定的等价模块。
- 实现 Fixture import service。
- 校验 node/edge/rule/requirement/capability binding 引用完整性。
- 校验 Phase 1 Algorithm Profile 要求的 DAG、max depth 和 applicability。
- 生成 canonical content hash。
- 实现 validation run 和 published snapshot pointer。
- 保证 Snapshot 内容行不可修改；重新导入变更内容产生新 Snapshot。
- 提供内部 service API；HTTP 管理 API 只在 PRD 明确要求时实现。

### 交付物

- Causal Snapshot import/validation/publish service。
- Fixture 导入脚本或测试 helper。
- Snapshot 不可变性和发布规则测试。

### 验收标准

- T02 Snapshot 可导入、验证并发布。
- 计算出的 content hash 与 Fixture 期望一致。
- 缺失 node、悬空 edge、悬空 requirement/binding 或不兼容图结构会被拒绝。
- Published pointer 只指向验证通过的不可变 Snapshot。
- 修改已发布 Snapshot 被数据库或服务层拒绝。
- Prepare 所需 nodes/edges/rules/requirements/applicability 全部能从 Snapshot 单独恢复。
- tenant 隔离测试通过。

### 范围边界

- 不做完整模型编辑 UI、审批 UI 或通用模型市场。
- 不实现 Decision/Scenario Model。

---

## T06——实现 StepType Registry 与 Causal Blueprint Compiler

**优先级：P0**

**依赖：T05**

### 目标

将 Published Causal Snapshot 确定性编译为不可变 BlueprintVersion，并完整通过 G1 Knowledge Compilation。

### 工作内容

- 实现/seed `step_types` 与 `step_type_versions` 的 Case A 必需类型。
- 至少提供已版本化的 `knowledge_query` 与 `output` Handler 定义。
- 实现 Compile Record 状态机和错误日志。
- 实现 Causal Compiler：Intent、Goal Skeleton、Source Model pin、Steps、Deps、Sources 和 Cause Ranking Output Contract。
- BlueprintVersion pin Snapshot hash、Compiler Version/Config 和 StepType Handler Version/Hash。
- Compiler Validator 检查 Goal Skeleton 的 Constraint/Output 引用同版本。
- 原子完成旧 compiled → superseded、新版本 → compiled。
- 明确实现或跳过 Extended `source_fingerprint` 幂等；结果写入测试报告。
- 增加负向断言：不得把节点级 Evidence Requirements 编译为 Blueprint capability requirements；只允许显式 model-level hard requirement。

### 交付物

- StepType Registry/seed。
- Causal Blueprint Compiler 和 Validator。
- Compile service/API（按 PRD）。
- G1 自动化测试。

### 验收标准

- T02 Snapshot 能编译出最小 `knowledge_query → output` BlueprintVersion。
- Blueprint 的 Intent、Goal Skeleton、Output Contract 与 Fixture 一致。
- Source Snapshot、Compiler 和 Handler 全部被 pin。
- 所有 Blueprint 子对象属于同一 BlueprintVersion。
- Blueprint 中不存在 `equipment_health_query`、`haulage_operation_query`、`quality_metric_query` 等节点级动态能力展开。
- validation 失败时 Compile Record 为 failed 且不创建 BlueprintVersion。
- 新版本切换保持唯一 compiled 版本。
- G1 Core Gate 全部通过。

### 范围边界

- 只支持 Causal Model → Causal Blueprint。
- 不实现通用多模型组合、Decision/Scenario Compiler。

---

# 五、G2——Planning Entry

## T07——实现确定性 Planning Entry

**优先级：P0**

**依赖：T06**

### 目标

让固定自然语言请求经过确定性 Intent/Goal 入口，唯一发现正确的 BlueprintVersion，并实例化运行时 Goal。

### 工作内容

- 保留现有 `SimpleTaskPlanner` legacy 路径。
- 新增 Blueprint Planning 路径和明确的选择/路由条件。
- 实现或补齐 ParsedIntent、SubGoal 和 Runtime Goal 类型。
- 第一轮使用 T02 `intent_goal_fixture.json` 作为 LLM Stub 输出。
- 保留真实 Parser、结构校验、上下文绑定和错误处理逻辑。
- 实现 Blueprint Discovery：Intent、objective、domain、direction、applicability、tenant/role scope。
- 只加载唯一当前 compiled BlueprintVersion。
- 实现 Goal Instantiation：绑定 `mine-3` 与固定 time window。
- 记录 Prompt Version、Structured Output Schema Version 和 Fixture Hash。

### 交付物

- Goal Resolution/Discovery/Instantiation 服务。
- Deterministic LLM Stub adapter。
- Blueprint Planner 入口。
- G2 自动化测试。

### 验收标准

- 固定请求产生且只产生一个 diagnose SubGoal。
- Intent 字段与 Fixture 完全一致。
- 唯一命中 Case A 当前 compiled BlueprintVersion。
- Runtime Goal 正确绑定 entity 和 time window。
- Discovery 不返回 superseded/withdrawn、越租户或越权限版本。
- 此阶段不产生 Evidence Task。
- 测试无网络、无在线 LLM、可重复运行。
- 现有 `/plan` legacy 测试不回归。

### 范围边界

- 不测试线上 LLM 的自然语言理解准确率。
- 不实现 Compound Intent 或多 SubGoal Composition。

---

# 六、G3——Dynamic Planning

## T08——实现 Reasoning Prepare 与 ReasoningContext

**优先级：P0**

**依赖：T07**

### 目标

让 `knowledge_query` Handler 在 Planning-time 调用 Prepare，根据本次 entity/time window 动态生成 Evidence Requirements，并持久化可恢复的 ReasoningContext。

### 工作内容

- 创建 Reasoning Algorithm Registry/Version 的最小服务和 Fixture seed。
- 实现 `reasoning_mode → algorithm_version` 的确定性选择。
- 验证 Snapshot 与 Algorithm Profile 兼容性。
- 从 Published Snapshot 和 Ontology ABox 实例化目标图。
- 动态生成 requirement_id，并保留稳定 requirement_key。
- 冻结 Snapshot、target、time window、instance graph、requirements、algorithm profile/params 和权限范围。
- 计算 context hash，持久化 ReasoningContext。
- 实现 prepared/expired/cancelled 生命周期基础行为。
- Prepare 不访问 Provider、Connector、Credential 或当前运行就绪状态。

### 交付物

- Algorithm Registry seed/service。
- Reasoning Prepare service/API。
- ReasoningContext repository。
- G3 Prepare 测试。

### 验收标准

- Case A `knowledge_query` 生成持久化 prepare_id。
- Requirements 与 T02 Fixture 的 requirement_key、required/optional、实例范围和时间窗一致。
- 每个 requirement_id 在本次 Context 内唯一。
- Context 包含完整可恢复字段，不只保存 hash。
- Prepare 期间没有调用 Capability Provider 或 Connector。
- Snapshot/算法不兼容、目标实体不存在或权限范围无效时明确失败。
- 服务重建后仍能读取同一 ReasoningContext。

### 范围边界

- Prepare 不取业务数据。
- 不在 Runtime 执行阶段动态增加 Task。

---

## T09——实现 Capability Resolution 与 PlanFragment 投影

**优先级：P0**

**依赖：T08**

### 目标

把 Prepare 产生的逻辑 Evidence Requirements 解析为当前租户的物理取证 Tasks，并生成 Evaluate 在后的可执行 PlanFragment。

### 工作内容

- 实现 `knowledge_query` StepType Handler 的 PlanFragment 投影。
- 复用 Capability Registry，根据 capability contract 和 entity applicability 解析 Mock Provider。
- 为每个已规划 Evidence Requirement 创建 acquisition Task。
- 创建且只创建一个 reasoning_evaluate Task，并携带 prepare_id。
- 所有 acquisition Tasks 排在 Evaluate 之前；第一版允许顺序执行。
- required/optional 只影响结果语义，不影响已规划 Task 是否需要进入业务终态。
- 处理 Provider unavailable 的 required/optional 分支。
- 修正 legacy `MAX_PLAN_DEPTH=5`：不得用总 Task 数量代替依赖图深度；保持合理的循环/深度保护。
- 保证 legacy SimpleTaskPlanner 和既有 Orchestrator 接口兼容。

### 交付物

- knowledge_query Handler。
- Capability Resolution adapter/service。
- PlanFragment/Plan 映射。
- Planner validation 修订。
- G3 PlanFragment 测试。

### 验收标准

- Case A 产生 N 个 acquisition Tasks + 1 个 Evaluate Task；如 Output Handler 产生 Task，其顺序在 Evaluate 之后。
- 每个 Task 可追溯到 requirement_id、requirement_key 和 Blueprint Step。
- Evaluate 不会在任一已规划 optional acquisition Task 之前执行。
- required Provider unavailable 在 Fail-Closed Fixture 下导致 planning failure。
- optional Provider unavailable 仍能形成可结束为 missing optional 的 Plan。
- Case A 不因 Task 总数超过 5 被 legacy 校验错误拒绝。
- 现有 Planner、Workflow 和 Orchestrator 测试不回归。

### 范围边界

- 不实现通用并行 Scheduler。
- 不实现跨 Blueprint Plan Composition。

---

## T10——实现 Evidence Acquisition 业务终态语义

**优先级：P0**

**依赖：T09**

### 目标

确保所有已规划取证任务都能以明确的业务结果结束，并严格区分“业务数据不可用”和“执行基础设施故障”。

### 工作内容

- 创建 Mock 生产、设备、运输和质量 Provider。
- 将 Provider 正常数据映射为完整 EvidenceObservation Envelope。
- 将业务无数据映射为 `success + DATA_UNAVAILABLE` Observation。
- 将 stale/suspicious 数据映射为成功业务终态并保留 quality 信息。
- Runtime/Connector crash、认证失败等映射为 Task FAILED。
- 保证 Evaluate 等待所有已规划 acquisition Tasks 进入业务终态。
- 基础设施 FAILED 时 Evaluate BLOCKED。
- required/optional 缺失信息完整传递给 Evaluate，不在 Runtime 偷做推理判断。
- 保留 execution_id/task_id/source_ref 等 provenance。

### 交付物

- Mock Evidence Providers。
- EvidenceObservation mapper。
- Acquisition Task terminal-state handling。
- N-01、N-02、N-03A、N-03B、N-04 测试。

### 验收标准

- Golden Case 全部 acquisition Tasks 产生 valid Observation。
- optional DATA_UNAVAILABLE 不会让 Task FAILED，也不会提前跳过 Evaluate。
- required DATA_UNAVAILABLE 能到达 Evaluate，由 Reasoning 返回 FAILED/422。
- Runtime/Executor 故障导致 Evaluate BLOCKED。
- 每条 Observation 都包含 requirement、实例、单位、时间、source、quality 和 provenance。
- Evaluate 启动时间晚于所有 acquisition 业务终态。

### 范围边界

- 不接真实 MES/EAM/IoT。
- 不实现 Retry/Timeout 的新策略，只使用现有 Runtime 能力。

---

# 七、G4——Reasoning Execution

## T11——实现 sign_propagation_v1 Evaluate

**优先级：P0**

**依赖：T10**

### 目标

使用冻结的 Snapshot、Algorithm Fixture 和 EvidenceObservation 执行确定性因果推理，得到机器可判定的 Cause Ranking 与 Evidence Chain。

### 工作内容

- 实现 Algorithm Registry 定位与 implementation hash 校验。
- 实现 DAG 反向路径枚举和 max_depth 限制。
- 实现 direction 推导、obs_match、一票否决、unchanged 弱支持。
- 实现冻结契约中的 path score 和 node aggregation。
- 实现确定性 tie-breaker。
- Evaluate 只消费 prepare_id 对应的冻结 Context 和传入 Evidence。
- 不允许 Evaluate 切换算法、重新实例化或读取 live model tables。
- 实现 COMPLETE、PARTIAL、FAILED/422 语义。
- 输出 Cause Ranking、Evidence Chain、missing requirements、complete 和版本元数据。

### 交付物

- `sign_propagation_v1` 实现。
- Evaluate service/API。
- Golden Result、缺证据、方向冲突和幂等输入准备测试。

### 验收标准

- T02 Golden Fixture 的 Top 1、Evidence Chain 和 complete 状态全部匹配。
- 相同冻结输入重复计算结果稳定。
- 全部 required + optional valid → COMPLETE/`complete=true`。
- required missing → FAILED/422 + missing requirements。
- optional missing → PARTIAL/`complete=false`。
- 过期/取消/已被不同输入消费的 prepare_id 被拒绝。
- 输出携带 Snapshot、Algorithm Version/Profile/Params 和 context hash。

### 范围边界

- 只实现 `sign_propagation_v1`。
- 不实现贝叶斯、时序、含环或 LLM 推理算法。

---

# 八、G5——Auditability

## T12——实现 Trace、幂等与 Audit Replay

**优先级：P0**

**依赖：T11**

### 目标

建立从用户请求到最终原因排序的完整追溯链，并提供 Phase 1 Audit Replay，而不虚假承诺旧代码可重新执行。

### 工作内容

- 持久化 ReasoningTrace，包括 observations、evidence items、result、版本/hash 和 evaluation_input_hash。
- 串联 Request、SubGoal、BlueprintVersion、Compile Record、Source Snapshot、StepType Handler、Plan、Tasks、ReasoningContext 和 ReasoningTrace。
- 实现 `prepare_id + evaluation_input_hash` 幂等。
- 同一 prepare_id 相同输入返回已有结果。
- 同一 prepare_id 不同输入拒绝并要求新 Attempt/Prepare。
- 实现 Audit Replay 查询/服务，能够还原当时输入、规则、实现标识和推理理由。
- 明确 Audit Replay 不调用已删除的旧 Handler/Algorithm artifact。
- Executable Replay 保留接口/文档占位，但不纳入 Core Gate。

### 交付物

- ReasoningTrace repository/service。
- Trace lineage 查询或测试 helper。
- Audit Replay 输出结构。
- G5、N-05、N-06 测试。

### 验收标准

- 从最终响应能定位全部 G5 规定对象和版本/hash。
- 相同输入重试不创建重复 ReasoningTrace。
- 不同输入不能污染已消费 Context。
- Audit Replay 在不访问外部系统、不重新运行算法的情况下还原完整决策依据。
- Trace 包含归档 EvidenceObservation，而不是只保存 hash。
- 不把只有 hash 的历史记录标记为 Executable Replay capable。

### 范围边界

- 不建设历史 Algorithm/Handler artifact 仓库。
- 不实现 Phase 2 Executable Replay。

---

# 九、Case A 总验收

## T13——完成 Case A 自动化 E2E 与验收报告

**优先级：P0**

**依赖：T12**

### 目标

通过一条自动化命令真实运行 G1–G5，证明 EARP 核心因果诊断纵向切片可运行、可判定、可追溯。

### 工作内容

- 新建独立于 legacy echo E2E 的 Case A E2E 测试。
- 使用 Testcontainers PostgreSQL、真实迁移和真实 RLS。
- 装载 T02 Fixtures。
- 执行 Snapshot publish → compile → request → discovery → prepare → plan → acquisition → evaluate → trace。
- 覆盖 Golden Path 与 Acceptance v0.2 N-01 至 N-11；N-08 按 Extended 结果单列。
- 验证 Blueprint 不预编译动态 Evidence。
- 验证 optional Task 终态等待语义。
- 生成 `acceptance_report.json` 和简明人工报告。
- 增加 Makefile 目标，例如 `make e2e-causal-diagnostic`。
- 确保 legacy `make e2e` 和全量测试继续通过。

### 交付物

- `test_causal_diagnostic_e2e.py` 或 PRD 指定的等价测试。
- 一键执行目标。
- 机器可读验收报告。
- 人工验收摘要。

### 验收标准

- 单条命令在干净数据库上可重复通过。
- 测试不访问互联网、在线 LLM 或真实企业系统。
- G1–G5 Core Gate 全部为 PASS。
- Golden Top 1、Evidence Chain、COMPLETE 状态与 Fixture 一致。
- 全部异常路径结果与 Acceptance v0.2 一致。
- Trace lineage 完整，Audit Replay 可用。
- 全量既有测试、lint、type check 和 import-linter 不回归。
- 最终报告只声明：`Planning Blueprint Causal Diagnostic Vertical Slice — Accepted`。

### 范围边界

- 不宣称 Planning Blueprint Framework 全部能力完成。
- 不接真实 Provider，不测试性能和 UI。

---

# 十、P1 真实集成

## T14——接入一个真实只读数据 Provider

**优先级：P1**

**依赖：T13**

### 目标

在不破坏确定性 Golden Case 的前提下，用一个真实只读数据源验证 Capability Contract、Connector、数据质量和 EvidenceObservation 映射。

### 工作内容

- 在生产指标或运输指标中选择一个最稳定、最容易获取的数据源。
- 实现对应 Capability Provider/Connector binding。
- 明确认证、超时、数据权限、时间窗、单位和聚合。
- 将真实响应映射为既有 EvidenceObservation Contract。
- 其余 Provider 继续使用 Mock，以隔离集成风险。
- 建立独立 Pilot Test，不替换 CI Golden Fixture。
- 记录数据偏差、质量问题和 Contract 改进建议。

### 交付物

- 一个真实只读 Provider。
- Connector/Capability binding 配置。
- Pilot 集成测试和报告。

### 验收标准

- Provider 只读且经过 tenant/role scope 检查。
- 能按 Case A entity/time window 返回结构化 Observation 或明确 DATA_UNAVAILABLE。
- 单位、时间窗、quality 和 provenance 完整。
- Provider 不可用不会破坏 CI Golden Case。
- Pilot 结果能够进入既有 Plan/Evaluate/Trace 链，无专用旁路。
- 不在 Provider 内复制因果规则或推理逻辑。

### 范围边界

- 一次只接一个真实 Provider。
- 不同时接入全部 MES/EAM/IoT 系统。

---

# 十一、P2 后续案例

## T15——启动 Case B 决策推荐验收设计

**优先级：P2**

**依赖：T13**

### 目标

在 Case A 已证明“会分析”之后，定义“针对首要原因应该怎么办”的独立 Decision Model 验收案例。

### 工作内容

- 明确 Case B 用户问题、输入和边界。
- 定义 Decision Model 的 alternatives、rules、hard/soft constraints 和 output contract。
- 定义如何消费 Case A Cause Ranking，而不把 Case A 与 Case B 强耦合为一次测试。
- 设计 Decision Blueprint、decision_evaluate Handler 和 Recommendation Golden Fixture。
- 定义新的 Gate/异常路径和 Trace 要求。
- 只形成 Acceptance Draft，不直接实现 Case B。

### 交付物

- Case B Decision Recommendation Acceptance v0.1。
- Decision Model TBD 清单。
- 与 Case A 的输入输出契约说明。

### 验收标准

- Case B 可以单独运行，输入可使用固定 Cause Ranking Fixture。
- Decision Model 业务规则不写入 Blueprint 或测试代码形成第二事实源。
- Hard/Soft Constraints 和 Policy 边界明确。
- 不要求 Scenario Model 才能完成 Case B。
- 文档明确 Case C 多模型组合仍为后续工作。

### 范围边界

- 不编写 Decision Model 生产代码。
- 不启动 Case C Scenario Composition 实现。

---

# 十二、总体完成标准

P0 阶段完成时必须同时满足：

```text
T00–T13 全部完成
  + G1–G5 Core Gate 全部通过
  + Acceptance Report 结论准确
  + Legacy 路径无回归
  = Case A Causal Diagnostic Vertical Slice Accepted
```

P0 完成不代表：

- Planning Blueprint Framework 全部能力完成；
- Decision/Scenario Model 已实现；
- 复杂 DAG/并行 Scheduler 已实现；
- 线上 LLM 语义质量已验收；
- 全量企业数据源已经接入；
- Executable Replay 已实现。

这些能力必须由后续独立任务和案例验收，不得借 Case A 的通过结论提前宣称完成。
