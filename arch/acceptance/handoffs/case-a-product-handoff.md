# Case A 产品与验收交接（T00–T03）

**日期：2026-08-29**  
**交接范围：T00、T01、T02、T03**  
**状态：工程输入已交付；业务确认与基线提交待协调**

## 已完成

- T00：核验当前工作树。Planning Blueprint 是 v1.0 / Architecture Frozen；Case A
  Acceptance 是 v0.3 / 待业务确认。基线前的最近 commit 为 `dbce80e`，但冻结稿和
  验收文件当前仍与其他共享工作区变更混在一起，未创建提交。
- T01：将所有业务、模型、算法、数据、策略和 LLM TBD 收口为明确的**临时 Fixture
  假设**，见
  `arch/acceptance/2026-08-29-case-a-provisional-fixture-assumptions.md`。原验收规格的
  TBD 保持为“待业务确认”，没有被错误关闭。
- T02：创建 `apps/earp-server/tests/scenarios/mine_3_production_drop/`，包含 scenario、
  intent/goal、causal snapshot、ontology、logical capability binding、algorithm、完整
  EvidenceObservation、expected plan/reasoning、README 和 SHA-256 manifest。
- T02：新增纯 Fixture 校验
  `apps/earp-server/tests/test_case_a_fixture_validation.py`；它不访问数据库、网络、Provider、
  Compiler 或 Reasoning service。
- T02 P0 remediation：Fixture 现在提供与现有 Ontology 服务兼容的 import contract：
  data domain → TBox entity/relation type → ABox entity/fact。指标目录明确是 metadata（当前
  TBox 没有 metric table）。Snapshot 用 `case-a-abox-binding/v1` 确定 Prepare target；
  Capability binding 只选 Provider，不能补 target 语义。伪 `implementation_hash` 已改为
  `implementation_artifact.status=not_built`。
- T02 follow-up：增强跨文件校验，固定 Snapshot 的 `case-a-abox-binding/v1` 解析目标与
  Ontology ABox expectation，并断言 Capability fixture 只包含 Provider binding；同时明确
  algorithm identity/config hash 与 executable artifact hash 不可混用。
- T03：创建 `prd/PRD-2026-032-ecmc-causal-diagnostic-vertical-slice.md` v1.0，定义
  T04–T13 的数据、服务、Planner、执行、Trace 和测试合同。

当前 Fixture package hash：

```text
f9c9620f34e90c0119464e43cb1f51b4cb9daf63c26ee77e14040068dda35e66
```

已验证命令：

```bash
cd /Users/linkunpeng/work/EARP/apps/earp-server
.venv/bin/python -m ruff check tests/test_case_a_fixture_validation.py
.venv/bin/python -m pytest tests/test_case_a_fixture_validation.py -q
```

结果：`3 passed`；并已运行 `ruff format`、`ruff check` 与 `git diff --check`。

## 对后续开发的明确输入

### T04 — Schema / RLS

- 以 PRD §5 为准：全部新 tenant 表和 parent-child 引用必须 tenant-scoped；不能以应用层
  tenant filter 替代复合 FK/唯一键。
- 必须含 Compile Record 初始 `running` 或 `pending`、Blueprint current compiled partial
  unique index、跨版本 StepDep/StepSource 复合 FK、RLS 测试。
- Alembic revision 号在执行时从当前 head 分配，避免并行变更冲突。

### T05 — Snapshot / Algorithm / ABox import

- 只消费 Fixture 的 `snapshot`、`algorithm` 和 Ontology import contract；先按 data domain →
  TBox → ABox 顺序装载，验证 canonical/raw-byte hash 后才导入。hash mismatch 必须拒绝，
  **不得**静默重新 hash、替换 hash 或补 algorithm artifact hash。
- `ontology_fixture.json` 已含 mine、运输系统、设备组、关系和五个指标 metadata，足以按
  ABox expression 绑定 Case A；当前 TBox 没有 metric table，T05 不得声称经 TBox/ABox API
  导入指标。
- `published_fixture` 是 hash-locked 测试状态，不能冒充真实领域发布审批，不能映射为持久化
  `published`。`implementation_artifact.status=not_built` 仅允许规格导入/Prepare 规划，
  不允许 executable Evaluate；T11 显式发布新的 artifact-bearing Fixture version。

### T06 — Compiler

- 只生成稳定 `knowledge_query → output` Blueprint；Step source pin Case A snapshot；
  `knowledge_query` pin Handler version/hash。
- 不得将五条动态 Evidence Requirement 或任何 Fixture mock provider 预编译进 Blueprint。
- Validator 必须验证 Goal Skeleton references 属于同一 BlueprintVersion。

### T07–T10 — Planning / Prepare / Capability / Runtime

- Intent 仅使用 `case-a-deterministic-stub/v1` Fixture；线上 LLM 不在本范围。
- `capability_contract_ref` 是逻辑合同，不能直接等同物理 `capability_id`。T08 使用 Snapshot
  的 `case-a-abox-binding/v1` 从 ABox 解析 target entity；T09 只使用
  `capability_fixture.json` 的 deterministic `mock_*` **provider** binding，不能推断、补充
  或替换该 target。
- 本例有 5 acquisition task（3 required、2 optional）、1 Evaluate、1 output；Evaluate
  依赖全部已规划 acquisition。
- 首版顺序执行可以，但依赖图必须保留；业务 DATA_UNAVAILABLE 与基础设施 FAILED 的
  语义必须区分。

### T11–T13 — Evaluate / Trace / E2E

- Fixture Golden result：`haulage_cycle_time` Top 1，`haulage_queue_time` Top 2，结果
  COMPLETE，`complete=true`。
- Hash 规范在 PRD §6.1：semantic JSON hash 与 raw-byte package hash 不可混用；出现
  mismatch 必须失败，不能回读 live model。
- T12 仅承诺 Audit Replay；不要宣称实现了 Phase 2 Executable Replay。

## 临时假设与未决确认

所有列项及确认责任人见 assumptions 文档；主要未决项为：

1. `mine-3` 的企业本体身份、生产日/班次口径和产量基线/异常阈值；
2. 因果图节点、边、强度、置信度、required/optional 和数据质量规则；
3. `sign_propagation` 的 executable artifact hash（T11 release）、分数/覆盖率细节与业务 Top 1；
4. 合成观测值与真实数据可得性；
5. 缺证据 Fail-Closed 策略；
6. Planner intent Stub 的正式 prompt/schema ownership。

在确认前，任何通过结论只能是“基于 provisional fixture 的技术切片通过”，不能称为
业务正确或生产就绪。

## 阻塞与协调请求

- **T00 基线 commit 尚未创建。** 原因是共享工作区含未提交的 Blueprint 修改、验收目录和
  讨论记录；本任务没有安全授权去判断/提交其他 agent 或用户的变更。协调人应在所有本轮
  文档核对完成后，选择性 stage 基线文件并创建干净 commit。
- T04 可立即以本 PRD/Fixture 开始开发；其技术执行不被业务确认阻塞。真实 Provider、
  正式 Golden 排名和业务验收则被上述确认项阻塞。
