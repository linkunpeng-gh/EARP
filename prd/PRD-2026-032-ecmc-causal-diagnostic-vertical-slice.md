# PRD-2026-032：ECMC Case A 因果诊断纵向切片

**状态：v1.0 / Ready for implementation**  
**日期：2026-08-29**  
**范围：Case A（“为什么 3 号矿昨天产量下降？”）的 G1–G5**

## 1. 目的与权威输入

本 PRD 将已冻结的 Planning Blueprint、Planner Runtime 和 Causal Reasoning
Framework 契约落实为一个确定性纵向切片。交付的不是通用智能体平台重写，而是从
Published Causal Snapshot 到可审计 Cause Ranking 的最小真实链路。

实现的机器权威输入是：

`apps/earp-server/tests/scenarios/mine_3_production_drop/`

当前包哈希为
`f9c9620f34e90c0119464e43cb1f51b4cb9daf63c26ee77e14040068dda35e66`。
包内业务事实、术语、阈值、边权、算法实现标识和 Golden Top 1 都是
**provisional fixture assumptions**，仅用于确定性开发与测试；它们不是已由 FDE、
领域专家或数据负责人确认的生产业务知识。生产使用、真实 Provider 接入或正式验收
必须先完成 [Case A provisional assumptions](../arch/acceptance/2026-08-29-case-a-provisional-fixture-assumptions.md)
中的确认项。

架构输入保持不改动：

- `arch/design/2026-08-28-planning-blueprint-l3-design.md` v1.0；
- `arch/design/2026-08-28-planner-runtime-l3-design.md`；
- `arch/design/2026-08-28-causal-reasoning-engine-l3-design.md`；
- `arch/acceptance/2026-08-29-mine-3-production-drop-e2e-acceptance.md` v0.3；
- `arch/acceptance/2026-08-29-case-a-causal-diagnostic-implementation-task-list.md`。

文档和 Fixture 不一致时，以带哈希的 Fixture 为测试执行输入；差异必须回写验收规格
或新建 implementation erratum，不能由实现代码暗中选择另一套事实。

## 2. 目标与非目标

### 2.1 目标

在一个租户内，以固定请求完成如下生产主路径：

```text
published causal snapshot
  → compiler → immutable BlueprintVersion
  → deterministic intent/goal fixture → discovery/instantiation
  → knowledge_query Prepare → logical evidence requirements
  → capability resolution → sequential acquisition tasks
  → EvidenceObservation → Evaluate
  → COMPLETE cause ranking + trace + audit replay
```

必须满足：

- Blueprint、Source Snapshot、StepType Handler、Algorithm 和 Reasoning Context 都有
  可定位版本或 hash；
- Prepare 不查询 Provider readiness，Capability Resolution 不改变逻辑 Evidence
  Requirements；
- 所有已规划的 required 与 optional acquisition task 到达业务终态后才可 Evaluate；
- 固定 Fixture 的首因是 `haulage_cycle_time`，路径为
  `haulage_cycle_time → effective_production_capacity → production_output`；
- 同一 `prepare_id + evaluation_input_hash` 幂等，输入不同则拒绝复用；
- 能从最终结果还原本次输入、模型、计划、观测、算法和结论。

### 2.2 非目标

- Decision Model/Case B、Scenario Model/Case C；
- Admin UI、模型编辑器、线上 LLM 与 semantic evaluation；
- 真实 MES/EAM/IoT 集成（T14 才开始）；
- 通用并行 DAG Scheduler、重试/超时策略重构、跨 Blueprint Composition；
- performance、capacity、HA 或 Phase 2 executable replay artifact repository；
- 以 `source_fingerprint` 去重的编译幂等优化（Extended Gate，可留后续）。

## 3. 固定案例合同

### 3.1 固定输入

| 项目 | 固定 Fixture 值 |
|---|---|
| tenant | `tenant-mine-demo` |
| entity | `mine-3` / `mine` |
| request time | `2026-08-29T09:00:00+08:00` |
| production window | `2026-08-28T00:00:00+08:00` 到 `2026-08-29T00:00:00+08:00` |
| intent | `production_output / down / production / diagnose` |
| model | `causal-production-drop-mine` / `1.0.1-fixture` |
| snapshot | `cms-mine-3-production-drop-v1` |
| algorithm | `sign_propagation` / `1.0.1-fixture` |
| policy | required Provider unbound fail-closed；optional 可 partial |

`fixture_hashes.json`、`model_content_hash`、`algorithm_config_hash` 和 Intent Fixture
hash 是代码必须校验的输入，不可在运行期重新生成或替换。

Fixture 的 `published_fixture` 仅表示经过 manifest 固定的**测试输入发布**；它不是领域
模型审批、生产发布状态，也不授权导入服务把任何持久化模型状态改写为 `published`。T05
可在 `testing` 模型版本上登记已校验的 Snapshot pointer，供测试 Compiler 定位；这不改变
生产发布语义。当前
Algorithm Fixture 的 `implementation_artifact.status=not_built` 表示其只能用于规格和
Prepare/规划契约测试，不能作为可执行 Evaluate 或 Executable Replay artifact。

### 3.2 预期运行时结果

Golden path 必须生成 5 个 acquisition task（3 required、2 optional）、1 个 Evaluate
task、1 个 output task。全部 Fixture observation 有效时，结果为：

```json
{
  "status": "COMPLETE",
  "complete": true,
  "top_cause": "haulage_cycle_time",
  "missing_requirements": []
}
```

`haulage_queue_time` 必须以较低分列为第二；设备可用率和矿石品位为
`unchanged`，不能被凭空作为首因。

## 4. 领域边界、目录与依赖

### 4.1 新增模块

新模块遵循已冻结的 `bmc` 前缀，并保持业务逻辑与传输层分离：

```text
src/earp_server/bmc/
├── metamodel/                 # T04–T05：causal source model + immutable snapshots
├── compiler/                  # T04, T06：Blueprint persistence / compiler / validator
└── reasoning/                 # T04, T08, T11–T12：prepare, evaluate, trace, registry
src/earp_server/planner/
├── blueprint_discovery.py     # T07
├── blueprint_entry.py         # T07
├── blueprint_handlers.py      # T08–T09
└── plan_fragment.py           # T09
src/earp_server/capability/
└── resolution.py              # T09：logical contract → physical binding
```

以上文件名是实施期的默认落点；若现有模块已有等价职责，可复用并在实现 PR 说明。
不得把 Causal Model 或 Reasoning Engine 放入 `planner`，也不得把 Capability
Provider readiness 放入 `bmc.reasoning`。

### 4.2 依赖方向与 import-linter

```text
bmc.metamodel ─┐
bmc.compiler  ─┼──→ ontology, infra
bmc.reasoning ─┘
planner ─────────→ bmc.compiler, bmc.reasoning, capability, orchestrator
capability ──────→ infra
orchestrator ────→ runtime/capability execution only
audit ───────────→ immutable event payloads only
```

若 `planner → bmc.compiler` 或 `planner → bmc.reasoning` 触发既有 independence
contract，T06/T08 仅为实际发生的、单向消费 import 增加最小 `ignore_imports` 例外。
不得用双向 import 或 service locator 绕过契约。

### 4.3 复用点

| 已有模块 | Case A 用法 |
|---|---|
| `ontology.abox_service` / TBox | T05 按 Fixture import contract 导入 data domain→TBox→最小 `mine-3` ABox；T08 实例化目标范围 |
| Capability Registry | T09 解析逻辑 contract 到 Fixture mock provider |
| `orchestrator.MultiStepExecutor` | T10 顺序执行 acquisition 后 Evaluate；不改变为通用 DAG scheduler |
| Audit service | T12 写 request/plan/evidence/reasoning trace 关联事件 |
| `infra.db.tenant_session` / Alembic / RLS | T04 所有新租户表和隔离测试 |
| `planner.task_planner.SimpleTaskPlanner` | 保留 legacy 路径；Case A 走新 Blueprint entry，不重写旧路径 |

## 5. 数据与迁移合同（T04）

T04 新建一个连续 Alembic revision（编号以当时 head 为准，避免并行任务抢号）。一个
schema migration 可以包含 Case A 必需表，但只建当前纵向切片需要的最小列和索引。

### 5.1 Causal source model 与 Algorithm Registry

至少实现：

- `causal_models`、`causal_model_versions`、`causal_model_snapshots`；
- `causal_nodes`、`causal_edges`、`causal_rules`、`causal_data_bindings`，或等价的
  不可变 snapshot JSON 加可验证 projection；
- `reasoning_algorithms`、`reasoning_algorithm_versions`；
- `reasoning_contexts`、`reasoning_traces`。

Published Snapshot 必须不可变；Prepare 只消费 `snapshot_id + content_hash` 和当时的
ABox instance snapshot，不能回查可编辑模型表。`reasoning_contexts` 必须保存
`prepare_id`、tenant、snapshot/hash、target/time window、instantiated requirements、scope
hash、algorithm version/config/params/hash、状态和过期信息。`reasoning_traces` 保存
evaluation input、ranking、evidence items/provenance、context/algorithm identity。

所有包含 `tenant_id` 的新表必须采用 tenant-scoped identity：引用同租户父对象时以
`(tenant_id, parent_id)` 复合外键保证；业务唯一键、当前版本 partial unique index 与
幂等键均包含 `tenant_id`。不得依赖应用层过滤或全局裸 ID 来阻止跨租户关联。

### 5.2 Blueprint persistence

按 Planning Blueprint L3 v1.0 建立本 Case 所需表：

- `planning_blueprints`、`planning_blueprint_versions`、`blueprint_compile_records`、
  `blueprint_source_models`；
- `blueprint_intents`、`blueprint_goal_skeletons`、`blueprint_steps`、
  `blueprint_step_deps`、`blueprint_step_sources`；
- `step_types`、`step_type_versions`、`blueprint_constraints`、
  `blueprint_output_contracts`。

Case A 只需 `knowledge_query` 与 `output` StepType；不创建 Causal 节点级
`blueprint_capability_requirements`。若表本身按 L3 一并建立，Case A Compiler 必须保证
其为空，除非将来 Source Model 声明 model-level hard requirement。

强制数据库契约：

- 版本子表有 `blueprint_version_id`；
- `(blueprint_version_id, step_id)` 和 `(blueprint_version_id, source_ref_id)` 的复合唯一键
  支撑 StepDep/StepSource 复合外键，拒绝跨版本引用；
- 每 Logical Blueprint 仅一个 `status='compiled'` 的 partial unique index；
- `blueprint_intents` 唯一键包含 direction；
- BlueprintVersion 反向引用 CompileRecord，CompileRecord 初始状态为 `running` 或
  `pending`，成功才写 BlueprintVersion；失败不创建 Version；
- 所有租户表启用 RLS，读写策略采用项目已有 tenant session 变量。

## 6. 服务接口合同

以下为 service 边界，HTTP route 可在相应任务中仅做薄适配层；不得让 route 承担
编译、推理或计划逻辑。

| 服务 | 最小输入 | 最小输出 | 任务 |
|---|---|---|---|
| Snapshot import/publish | tenant、Fixture snapshot、algorithm config、Ontology import contract | immutable snapshot/version IDs 与 hashes；ABox binding-ready fixture scope | T05 |
| Compile | tenant、published snapshot ID、compiler version/config | CompileRecord + current BlueprintVersion | T06 |
| Blueprint planning entry | request/context、deterministic Intent fixture | exactly one instantiated `diagnose` goal + BlueprintVersion | T07 |
| Prepare | Blueprint source reference、goal bindings、scope | persisted `prepare_id` + logical Evidence Requirements + resolved target scope | T08 |
| Capability resolution | Evidence Requirements、Prepare target scope、policy | resolved/unbound provider bindings；不得改写 target | T09 |
| Evaluate | `prepare_id`、EvidenceObservation set | COMPLETE/PARTIAL/FAILED result + ReasoningTrace | T11 |
| Case runner | fixture directory/manifest | deterministic E2E result/report | T13 |

`Evaluate` 不接收 `reasoning_mode`、model version 或 live target 作为替换冻结 Context 的
入口。调用方若想改变算法、模型或实例化结果，必须重新 Prepare。

### 6.1 Fixture hash canonicalization

实现和测试使用两种明确、不可混用的 SHA-256 口径：

- 语义对象 hash：对 JSON 对象以 UTF-8、`ensure_ascii=false`、key 排序、紧凑分隔符
  (`separators=(',', ':')`) 序列化后计算。Intent hash 排除自身 `fixture_hash` 字段；
  Model/Algorithm hash 分别覆盖其 `snapshot`/`algorithm` payload。
- Fixture package hash：`fixture_hashes.json` 中列出的每个文件以原始 UTF-8 bytes 计算
  file hash；按文件名排序，将 `filename:hex_hash\n` 串联后再计算 package hash。Manifest
  与 README 被明确排除，避免 self-reference。

服务端未来生成的 Snapshot、Algorithm Config、ReasoningContext 和 evaluation input hash
必须使用同一 canonical JSON 规范，并把 schema/version 与 hash 一并持久化。任何 hash
mismatch 都是验证失败，不能静默重新 hash 或回退到 live model。

T05 是 fixture **消费者**：它必须验证 manifest 和 semantic hash 后再导入，绝不能生成、
替换或静默重新 hash。算法 artifact hash 不是可由 T05 推导的 config hash；T11 只有在实现
artifact 后，才能经显式的新 Fixture release 写入可重复计算的 artifact hash/scope。

## 7. 实施增量、验收与测试映射

| 任务 | 实现交付 | 关键自动化测试 / AC |
|---|---|---|
| T04 | Schema、RLS、复合 FK、current compiled index、CompileRecord 初始态 | migration up/down；RLS；跨版本 StepDep/StepSource 拒绝；唯一 current compiled |
| T05 | Fixture Snapshot/Algorithm/ABox 导入、hash/release 校验 | import contract 按 domain→TBox→ABox 执行；hash mismatch 拒绝且不重算；`published_fixture` 仅测试边界；ABox 满足全部 Prepare binding |
| T06 | StepType Registry、Causal Compiler、validator | 生成 `knowledge_query → output`；pin snapshot/handler；Goal Skeleton 同版本 refs；不预编译动态 evidence |
| T07 | Deterministic LLM fixture adapter、Discovery、Goal Instantiation | 仅一个 SubGoal；唯一当前 Blueprint 命中；正确绑定 entity/time；legacy planner 回归 |
| T08 | Prepare、ReasoningContext 持久化、logical requirements | `prepare_id`、requirements IDs、snapshot/algorithm/scope pin；按 ABox binding 解析目标；无 Provider readiness 调用 |
| T09 | Capability resolution、PlanFragment projection | 5 acquisition + 1 Evaluate + output；只选择 Provider、不得改写 Prepare target；Evaluate 依赖全部 planned acquisition；required Provider unbound fail closed |
| T10 | Fixture mock providers、Observation envelope、业务终态 | valid、DATA_UNAVAILABLE、stale/suspicious 为业务终态；infra error FAILED/BLOCKED；Evaluate 不早启 |
| T11 | `sign_propagation_v1`、状态归类、ranking | 固定数据 Top1 cycle、Top2 queue；required missing 422；optional missing PARTIAL；tie-breaker |
| T12 | Trace、idempotency、Audit Replay | same input returns existing; different input rejected; audit payload 可还原版本/观测/链路 |
| T13 | Fixture 驱动 E2E、异常路径、machine/human report | G1–G5 core one command；N-01..N-11；报告明确 Extended/Phase 2 未运行 |

实现测试必须分层：T04–T12 各自拥有快速单元/服务测试；T13 才使用完整迁移与 E2E
fixture。不得用 T13 一条黑盒测试替代前序任务的契约测试。

## 8. Planner 与执行语义

### 8.1 Legacy compatibility

现有 `SimpleTaskPlanner` 和其调用者继续服务既有路径。Case A 新增显式 Blueprint
planning entry；只有匹配 Fixture/Blueprint 的 `diagnose` goal 才进入该路径。不得把
所有 intent 都切换到 Blueprint，也不得删除 legacy tests。

`planner.validation.MAX_PLAN_DEPTH=5` 当前把 step 数量当图深度，不能用于 Case A 的
七个 Task。T09 必须将其改为基于依赖图的最长路径，或为 PlanFragment 建立独立验证器；
保留 `MAX_PLAN_DEPTH` 作为真正的 graph-depth 防护。不能仅把常量调大来掩盖语义错误。

### 8.2 Sequential Phase 1 execution

Phase 1 允许按固定顺序运行 acquisition tasks，全部到达业务终态后运行 Evaluate，最后
运行 output。Task 的依赖图仍必须正确表达“Evaluate 等待全部 acquisition”，以免未来
换并行 executor 时丢失语义。不要在本 PRD 范围内实现并行调度、重试策略、超时聚合或
工作流审批。

### 8.3 Evidence terminal states

| 情形 | Acquisition Task | Evaluate |
|---|---|---|
| valid value | success + valid Observation | 正常消费 |
| `DATA_UNAVAILABLE` | success + business Observation | required → FAILED/422；optional → PARTIAL |
| stale/suspicious | success + quality-bearing Observation | 按冻结算法/质量规则消费 |
| connector/auth/crash | FAILED | BLOCKED，不伪装为业务缺数 |

required/optional 只决定 Evaluate 的业务结果，不能让 optional task 被提前跳过；所有已经
规划的 acquisition 都是 Evaluate 的依赖。

## 9. Trace 与重放合同

T12 的 Phase 1 Audit Replay 必须能够从持久化对象或审计事件定位：

```text
request → subgoal → BlueprintVersion → CompileRecord → SourceSnapshot
        → pinned StepType Handler → Plan/Tasks → Prepare/Context
        → EvidenceObservations → Algorithm config → ReasoningTrace → response
```

Audit Replay 还原“当时为什么得到该结果”，不重新执行历史 Python artifact。若只有 hash
而无法加载历史 handler/algorithm，不得宣称完成 Phase 2 Executable Replay。

## 10. 实施期勘误与决策

这些是冻结架构已经允许、为实现而必须明确的收口，并非重新开启架构设计：

1. Compile Record 需要 `running`/`pending` 初始态；仅 `success`/`failed` 不足以表示
   build job 生命周期。
2. `source_fingerprint` 是本 Phase 的 Extended Gate：Schema 可预留，T06 不以其作为
   Core Pass 条件。
3. Compiler Validator 必须检验 Goal Skeleton 的 `constraint_refs` 与
   `output_contract_ref` 只指向同一 BlueprintVersion 的对象。
4. Causal Blueprint 只编译稳定方法；Evidence Requirements 是 Prepare 的动态输出，
   不是 Blueprint 的静态 provider/capability 展开。
5. Fixture 的 `published_fixture` 仅是 hash-locked 测试治理状态，绝不等同真实领域模型发布审批，T05 不得将它映射或升级为持久化 `published` 状态。
6. `implementation_artifact.status=not_built` 不是 artifact hash 的替代值；T11 前禁止宣称支持 executable Evaluate 或 Executable Replay，也禁止 T05 静默补 hash。
7. `0038_algorithm_fixture_contract` 允许未构建 fixture 的 artifact hash 为空，单独保存
   algorithm configuration hash/JSON，并将 profile version 扩展到 64 字符；config hash
   绝不作为 artifact hash，Registry 仍不授予 tenant app 写权限。

## 11. 开发完成定义

T13 完成后，在 `apps/earp-server` 内的一条受控测试命令应可：加载并校验 Fixture、
导入 Snapshot、编译 Blueprint、计划、取证、Evaluate、验证 trace/异常路径，并输出
机器可读和人工可读报告。

通过结论只能写为：

> Planning Blueprint Causal Diagnostic Vertical Slice — Accepted

它不表示 Blueprint Framework、Decision、Scenario、真实 Provider 或 Executable Replay
已被验收。
