# Case A 临时 Fixture 假设与业务确认清单

**文档编号：ACCEPT-EARP-MINE3-PRODUCTION-DROP-ASSUMPTIONS-001**  
**版本：v0.2（Fixture Contract Remediation）**
**状态：Implementation Fixture Only / 不代表业务确认**  
**日期：2026-08-29**

## 1. 用途与边界

本文把 Case A 验收规格 v0.2 中尚未确认的业务、模型、算法、数据、策略和 LLM
TBD，收口为可重复运行的临时 Fixture 假设。对应机器文件位于：

`apps/earp-server/tests/scenarios/mine_3_production_drop/`

它们允许 T04–T13 开发与测试使用一致的、可哈希的输入；**不**表示 FDE、领域专家、
数据负责人、算法负责人或 Planner 负责人已确认这些内容。任何真实数据接入、生产启用
或“业务验收通过”结论，均需将以下项目改为书面确认并发布一个新的 Fixture 版本。

## 2. 临时假设

| 原 TBD | 临时 Fixture 假设 | 机器权威位置 | 需要确认者 |
|---|---|---|---|
| TBD-BIZ-001 | 本轮把“业务模型”按 Scenario Model 理解；Case A 不加载 Scenario Model | Case A acceptance §3 | 架构负责人 / FDE |
| TBD-BIZ-002 | `mine-3` 是类型 `mine` 的演示实体，业务码 `MINE-003` | `ontology_fixture.json` | FDE / 本体负责人 |
| TBD-BIZ-003 | “昨天”按 `Asia/Shanghai` 本地自然日，2026-08-28 00:00 至 2026-08-29 00:00 | `scenario.yaml` | 生产业务负责人 |
| TBD-BIZ-004 | 基线为 10,000 t，实际 8,200 t，下降至少 10% 判定为 down；日汇总 | Snapshot rule + observations | 生产业务负责人 |
| TBD-MODEL-001 | 六节点、五边 DAG；运输循环/排队通过有效产能影响产量 | `causal_model_snapshot.json` | FDE / 领域专家 |
| TBD-MODEL-002 | 产量、设备可用率、运输循环为 required；排队和品位为 optional | Snapshot evidence requirements | FDE / 领域专家 |
| TBD-MODEL-003 | 边的 effect/strength/confidence 采用 Fixture 数值（非校准值） | Snapshot edges | FDE / 领域专家 |
| TBD-ALGO-001 | `sign_propagation` `1.0.0-fixture`，最长路径 3，max-path 聚合 | `algorithm_fixture.json` | Reasoning 负责人 |
| TBD-ALGO-002 | 分数为路径每条边 `strength × confidence` 连乘；同分按 score、路径长度、node key 排序 | Algorithm fixture | Reasoning 负责人 / FDE |
| TBD-DATA-001 | 单位使用 `t`、`ratio`、`min`、`grade_index`；固定的日聚合 | Ontology/model/observations fixtures | 数据负责人 |
| TBD-DATA-002 | 8200/10000、0.96/0.95、51/38、17/6、1.15/1.16 是合成 Golden Data | `evidence_observations.json` | 数据负责人 / FDE |
| TBD-ONTOLOGY-001 | `mine`、`haulage_system`、`equipment_group` 与两条关系是 Case A 的最小 TBox；`production_data` 与 `equipment_data` 是其导入前置数据域 | `ontology_fixture.json` import contract | 本体负责人 / FDE |
| TBD-ONTOLOGY-002 | 每条 Evidence Requirement 的 ABox target 按 `case-a-abox-binding/v1` 解析；Capability 只选 Provider，不补 target 语义 | Snapshot binding + ontology expected bindings | 本体负责人 / Planner 负责人 |
| TBD-RESULT-001 | 首因是 `haulage_cycle_time`，第二是 `haulage_queue_time` | `expected_reasoning.json` | 领域专家 |
| TBD-POLICY-001 | required Provider 未绑定：planning fail-closed；required 数据不可用：FAILED/422；optional 数据不可用：PARTIAL | `scenario.yaml` | Policy / 业务负责人 |
| TBD-LLM-001 | Intent/Goal 解析固定为 deterministic stub `case-a-deterministic-stub/v1` 和 output schema v1 | `intent_goal_fixture.json` | Planner 负责人 |

## 3. 已固定的工程语义

以下不是业务知识确认，而是本 Fixture 包的工程合同：

- Fixture package 使用 `fixture_hashes.json` 的 SHA-256 raw-byte 清单；其当前 package
  hash 由校验测试验证。
- Model content、algorithm config 与 intent fixture 分别对规定 payload 做 canonical JSON
  SHA-256；规范见 PRD-2026-032 §6.1。
- `algorithm_id`/`algorithm_version_id`/`algorithm_config_hash` 只标识算法规格与配置；它们
  不等于实现 artifact 的 hash。当前 `implementation_artifact.status=not_built`，T11 前不得
  用配置 hash 冒充实现 hash，也不得由 T05 静默生成或回填。
- `capability_contract_ref` 是逻辑合同，绝不等同于物理 `capability_id`；Fixture 中的
  `mock_*` 仅是 T09 可确定性绑定的测试 Provider。Provider binding 不含 target entity：
  target 由 Prepare 使用 Snapshot 的 ABox binding 表达式解析，Resolver 不得替换它。
- Ontology Fixture 含与既有服务兼容的导入顺序：data domain、TBox entity/relation、再
  ABox entity/fact。指标目录是 Fixture metadata，现有 TBox 没有 metric table，T05 不得
  谎称将其经现有 TBox/ABox API 导入。
- `published_fixture` 仅是 hash-locked 测试 Fixture release，绝不等同真实领域模型发布
  审批或生产状态。`implementation_artifact.status=not_built` 说明算法尚无可执行 artifact；
  T05 必须验证 hash、不得生成或静默重算，T11 才能经显式新 release 写入 artifact hash。

## 4. 后续确认与变更流程

1. 对某项假设完成确认时，记录确认人、日期、依据与实际结论。
2. 若结论改变任何机器 Fixture，更新相关 JSON/YAML、semantic hash、file hash 和
   package hash，并在 PRD/验收规格记录新版本。
3. 改变边、规则、required/optional、算法、输入或预期排序时，旧 Golden Result 不再
   可比较；必须新建或显式升级 Fixture version。
4. 在上述确认前，T13 即使技术测试全部通过，结论也只能是“基于 provisional fixture
   的技术纵向切片通过”，不得表述为业务正确性或生产就绪。
