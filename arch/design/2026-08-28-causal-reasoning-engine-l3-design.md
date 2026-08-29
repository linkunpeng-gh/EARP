# Causal Model Storage & Reasoning Engine — L3 实现设计

**文档编号：DESIGN-ECMC-CAUSAL-L3**
**版本：v0.5.1（draft，Framework Freeze Patch）**
**日期：2026-08-28**

> 上游：`arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21，§3.1 CausalModel / §3.1.2 Causal Reasoning Contract + Phase 1 参考实现 / §3.1.4 data_requirement / §4.4.3 Reasoning Contract）、`arch/design/2026-08-07-ontology-layer-design.md`（Enterprise Semantic Layer：TBox/ABox）、`arch/L2/02-reasoning/planner-specification.md`（v1.1）
> 定位：ECMC 的核心技术壁垒——因果模型如何**存储、实例化（Prepare）、推理（Evaluate）**。
> 技术栈：FastAPI + SQLAlchemy 2 async + PostgreSQL 16（存/查/版本/快照），沿用"基础设施最小化"原则（图数据库留待 Phase 3 评估）；推理 = 快照加载内存图 + Python 遍历（非 Recursive CTE 推理）；Phase 1 算法 = 符号传播 + 路径排序（默认实现，可替换）。

---

# 一、设计原则

```
P1  存储与推理分离——模型存储（可版本化/快照）与推理执行（算法可替换）解耦
P2  契约驱动——推理引擎实现 Causal Reasoning Contract（§3.1.2），
     算法可替换（符号传播为 Phase 1 默认，贝叶斯/图搜索/LLM 经注册接入）
P3  存储与图计算分离（v0.2，评审 P1）：PostgreSQL 负责存/查/版本/快照；
     Reasoning Engine 消费统一的 CausalGraphSnapshot（加载内存构建图，
     Python 遍历）——递归 CTE 不作为推理主路径（图计算与算法解耦）
P4  不可变快照（v0.5.1 修正）——生产推理只读 Published Snapshot；
     Model Validation 读 Validation Snapshot；两者都必须是 Immutable
     Snapshot；Reasoning Engine 永不读取可编辑模型表（draft/testing）
P5  可复现——同输入（模型快照 + 观测 + 证据）同输出（reasoning_trace）；
     可复现键含 algorithm id/version + params（v0.2 强化，见 §2.9）
P6  Reasoning Engine 不取数（v0.2，评审 P0-1）——推理拆为
     Prepare（声明证据需求）+ Evaluate（消费观测产出结论）两阶段；
     取数由 Planner data_fetch/capability Tasks 执行（与 Planner
     Runtime v1.0 咬合，见 §三）
P7  模型可表达一般有向图（v0.2，评审 P0-3）——DAG 是算法 Profile
     约束而非存储约束；Phase 1 发布 Profile 仅支持 DAG（见 §4.5）
```

---

# 二、存储模型（PostgreSQL）

## 2.1 表总览（v0.3 更新）

| 表 | 说明 |
|---|---|
| `causal_models` | 逻辑模型（稳定身份） |
| `causal_model_versions` | 模型版本（每个版本一套节点/边/规则/绑定） |
| `causal_nodes` | 节点（元模型① Node，引用 version + node_key） |
| `causal_edges` | 有向影响边（元模型② Relation，edge_key） |
| `causal_rules` | 节点规则（元模型④ Rule，rule_key，1:N per node） |
| `causal_data_bindings` | 逻辑数据需求（元模型⑤ Data Binding，含 requirement_level） |
| `causal_capability_bindings` | 能力需求（元模型⑥ Capability Binding） |
| `causal_model_snapshots` | 版本快照（发布时不可变，推理只读；§2.9） |
| `causal_applicability` | 适用范围（权威表，§2.10） |
| `reasoning_traces` | 推理轨迹（Evidence 归档，元模型③，§2.11） |

## 2.2 版本化 Schema（v0.2 重构，评审 P0-2）

> **关键修正**：`model_id` 不是 PK——Logical Model 与 Model Version 分离：

```
causal_models（逻辑模型，稳定身份）
└── model_id / tenant_id / data_domain_id / name / description
    └── causal_model_versions（版本）
         ├── model_version_id / model_id FK / version / status
         ├── 依赖解析（结构化）/ applicability / owner / 时间戳
         └── 1 版本 → N 不可变快照 → 0..1 published_snapshot_id
             （v0.5.1：版本可有多个 validation 快照，published_snapshot_id
             指向发布快照——不再"每版本一快照"）
```

```
causal_models（逻辑模型）
├── model_id         VARCHAR(64) PK         -- 逻辑身份（production-causal）
├── tenant_id        VARCHAR(64) NOT NULL
├── data_domain_id   VARCHAR(64) NOT NULL
└── name / description TEXT NOT NULL

causal_model_versions（版本）
├── model_version_id VARCHAR(64) PK         -- 版本行身份
├── model_id         VARCHAR(64) NOT NULL FK → causal_models
├── version          VARCHAR(32) NOT NULL   -- 语义化版本（1.0/1.1/2.0）
├── status           VARCHAR(16) NOT NULL CHECK IN ('draft','testing','published','deprecated')
├── dependency_resolution JSONB NOT NULL DEFAULT '{}'  -- 结构化依赖（v0.2，见 2.8）
├── applicability   JSONB                   -- 适用范围投影（v0.2，权威见 2.9）
├── published_snapshot_id VARCHAR(64)       -- v0.5.1 P1：发布快照指针（见 2.10）
├── owner / created_at / updated_at / published_at
└── UNIQUE (model_id, version)

causal_nodes（节点，引用版本）
├── node_row_id      VARCHAR(64) PK         -- 行身份（内部）
├── model_version_id VARCHAR(64) NOT NULL FK
├── node_key         VARCHAR(64) NOT NULL   -- 稳定语义键（equipment_failure）
├── entity_type_ref / entry_point / entry_direction / entry_description
├── aggregation_* / observation_window
└── UNIQUE (model_version_id, node_key)     -- 版本内稳定引用

causal_edges / causal_rules / 绑定表：
├── ..._row_id PK
├── model_version_id FK
├── source_node_key / target_node_key       -- 稳定引用（v0.2）
└── UNIQUE (model_version_id, source_node_key, target_node_key)

跨版本稳定引用（v0.2）：
  Blueprint / Trace 使用 { model_id, version, node_key } 三元组
  ——v1.0 与 v1.1 中同义节点（equipment_failure）键不变，
  行身份（node_row_id）不同；不依赖随机 uuid 丢失语义
```

**为什么（评审 P0-2）**：旧 Schema `model_id PK + version` 只能存一个版本
（主键冲突）；且 nodes/edges 只引用 model_id 无法区分版本。

**复合外键（v0.4 P1，评审）**：node_key 引用必须为真正的 Referential Integrity：

```
FOREIGN KEY (model_version_id, source_node_key)
  REFERENCES causal_nodes(model_version_id, node_key)
——同样用于 target_node_key / rule.node_key / binding.node_key
（不只是字符串约定）
```

## 2.3 causal_nodes（节点，元模型①）

```
node_row_id         VARCHAR(64) PK
model_version_id    VARCHAR(64) NOT NULL FK
node_key            VARCHAR(64) NOT NULL        -- 稳定语义键（equipment_failure）
node_seq            INT NOT NULL
entity_type_ref     VARCHAR(64) NOT NULL        -- TBox entity_type（object|metric）
entry_point         BOOLEAN NOT NULL DEFAULT false
entry_direction     VARCHAR(8)                  -- entry_point=true 时：up|down
entry_description   TEXT                        -- 入口语义描述（供 Planner 匹配）
aggregation_mode    VARCHAR(16) NOT NULL DEFAULT 'per_instance'
                    CHECK IN ('per_instance','aggregate')
aggregation_operator VARCHAR(16)                -- count|ratio|max|min|avg
aggregation_predicate JSONB                     -- count/ratio 实例级谓词（引用 TBox attr/metric）
aggregation_weight_ref VARCHAR(64)              -- 权重来源（缺省等权）
observation_window  JSONB                       -- 当前观测窗口声明
UNIQUE (model_version_id, node_key)
```

## 2.4 causal_edges（有向影响边，元模型②，v0.3 增 edge_key）

```
edge_row_id         VARCHAR(64) PK
edge_key            VARCHAR(64) NOT NULL        -- 稳定身份（v0.3 P1）
model_version_id    VARCHAR(64) NOT NULL FK
source_node_key     VARCHAR(64) NOT NULL        -- 稳定引用（v0.2）
target_node_key     VARCHAR(64) NOT NULL
relation_type_ref   VARCHAR(64) NOT NULL        -- TBox causal namespace 关系类型
effect              VARCHAR(1) NOT NULL CHECK IN ('+','-')
strength            FLOAT NOT NULL DEFAULT 0.5  -- 0-1（发布补齐）
lag                 VARCHAR(16)                 -- 滞后周期（如 '7d'）
confidence          FLOAT NOT NULL DEFAULT 0.5  -- 作者置信度（≠ fact confidence）
UNIQUE (model_version_id, edge_key)
```

> **v0.3 P1（评审）**：不强制 source→target 唯一——未来可能有多条
> A→B 边（直接因果 / 介导/滞后机制，不同 lag）。稳定 edge_key 支持
> 1:N 边，语义由 relation_type_ref + lag 区分。

**DAG 约束移至算法 Profile（v0.2，评审 P0-3）**：存储层允许一般有向图
（可含环，企业存在反馈：设备故障→产量↓→赶工→负荷↑→设备故障）。
DAG 校验由推理算法 Profile 声明（sign_propagation_v1 要求 DAG，
调用前做 Algorithm Compatibility Validation，见 §4.5）。

## 2.5 causal_rules（节点规则，元模型④，v0.3 增 rule_key）

```
rule_row_id         VARCHAR(64) PK
rule_key            VARCHAR(64) NOT NULL        -- 稳定身份（v0.3 P1）
model_version_id    VARCHAR(64) NOT NULL FK
node_key            VARCHAR(64) NOT NULL
rule_type           VARCHAR(16) NOT NULL CHECK IN ('predicate','threshold','direction_rule')
rule_spec           JSONB NOT NULL              -- {attr:'status',op:'==',value:'failed'}
                                                -- / {metric:'health',op:'>=',value:90}
UNIQUE (model_version_id, rule_key)
```

> **v0.3 P1（评审）**：一个节点可有多个同类型 Rule
> （health<80 / temperature>90 / vibration>X 都是 threshold）。

## 2.6 causal_data_bindings（逻辑数据需求，元模型⑤）

> **v0.2（评审 P0-1 延伸）**：Data Binding 表达**逻辑需求**（这个节点需要什么
> 数据/证据），不绑定物理 Connector——物理解析在运行时由
> Capability/Connector Resolution 完成（见 §四 Prepare）：

```
binding_row_id      VARCHAR(64) PK
model_version_id    VARCHAR(64) NOT NULL FK
node_key            VARCHAR(64) NOT NULL
requirement_key     VARCHAR(128) NOT NULL       -- 模型级稳定键（equipment_fault_status，v0.4 P1）
requirement_level   VARCHAR(16) NOT NULL DEFAULT 'required'
                    CHECK IN ('required','optional')  -- v0.3 P1：权威来源
metric_binding      JSONB                       -- metric 节点：{metric_ref, instance_binding, time_window, aggregation, unit}
instance_binding_expr JSONB                     -- object 节点：受限表达式（链式 ≤2 跳）
instance_key_field  VARCHAR(64)                 -- 实例标识字段
instance_observation VARCHAR(64)                -- 实例观测字段
output_mapping      JSONB                       -- 输出字段 → 节点取值映射
UNIQUE (model_version_id, node_key, requirement_key)

requirement_key vs requirement_id（v0.4 P1）：
  requirement_key  — 模型级稳定定义（equipment_fault_status，长期不变）
  requirement_id   — 本次 Prepare 的实例（RP001-REQ003，见 §3.1）
  Snapshot 保存 requirement_key；Prepare 输出 requirement_id + requirement_key
```

## 2.7 causal_capability_bindings（能力需求，元模型⑥，v0.5.1 补 contract_ref + FK）

```
cap_binding_row_id  VARCHAR(64) PK
model_version_id    VARCHAR(64) NOT NULL FK
node_key            VARCHAR(64) NOT NULL
requirement_key     VARCHAR(128) NOT NULL       -- 关联 §2.6 的 requirement_key
capability_role     VARCHAR(16) NOT NULL CHECK IN ('primary','supporting')
read_only_required  BOOLEAN NOT NULL DEFAULT true
capability_contract_ref VARCHAR(128) NOT NULL   -- v0.5.1 P1：逻辑 Capability Contract
                                                --  （非当前租户物理 capability instance）

复合外键（v0.5.1 P1，Schema Closure）：
  FOREIGN KEY (model_version_id, node_key, requirement_key)
    REFERENCES causal_data_bindings(model_version_id, node_key, requirement_key)
  ——能力需求必须对应一个真实存在的数据需求（防悬空引用）
```

## 2.8 依赖解析：静态模型依赖 vs 运行绑定就绪（v0.4 拆分，评审 P1）

> **v0.4（评审 P1-2）**：不能把"今天 EAM Connector 是否在线"写进 published
> 模型版本——静态知识不随部署状态变。拆两层：

```
① Model Dependency Resolution（静态，随版本存储）：
  model_version.dependency_resolution（JSONB）：
    { required: { requirement_key_A: 'resolved', capability_contract_B: 'missing' },
      optional: { requirement_key_C: 'unresolved' } }
  检查：TBox 类型存在 / relation 类型合法 / logical requirement 完整 /
       capability contract 合法（不查运行状态）

② Runtime Binding Readiness（动态，不写模型，Evaluate/Planner 时查）：
  ——当前租户是否有 Provider / Connector 是否 active /
    Credential 是否有效 / Capability 是否可执行
  属 Planner / Capability Resolution 职责（v0.2 已定：物理解析在运行时）

MUST: 运行状态变化不得修改 published 模型版本（依赖解析只含静态检查）
MUST: binding readiness 由 Planner/Capability Resolver 判断（v0.5 P1）——
      Prepare 只声明"需要什么"（requirement_key），不查 Connector/credential/
      provider（ECMC 不判断运行就绪）；ResolvedEvidenceRequirement 带
      binding_status（resolved|unavailable）属 Planner 层
```

## 2.9 适用范围（单一事实源）

```
causal_applicability（结构化，权威）：
  app_id / model_version_id FK
  scope_type  — entity_instances | industries | tenant_scope
  scope_value JSONB

causal_model_versions.applicability = projection/cache（v0.2，评审 P1）
  ——仅作查询加速，非第二事实源；变更以 causal_applicability 为准
```

## 2.10 causal_model_snapshots（绝对不可变内容快照，v0.5 重构）

> **v0.5（评审 P0-2）**：快照**永远不可修改**（含 type 字段）。
> validation/published 是**治理事实**（usage/pointer），不是快照自身状态——
> 不通过修改 snapshot 行表达。

```
causal_model_snapshots（内容快照，无生命周期身份）：
  snapshot_id         VARCHAR(64) PK
  model_version_id    VARCHAR(64) NOT NULL FK
  content_hash        VARCHAR(64) NOT NULL   -- 全量内容哈希（防篡改）
  nodes_json / edges_json / rules_json      -- 元模型①②④
  requirements_json   JSONB NOT NULL        -- 完整需求包（v0.5 P0-3，见下）
  applicability_snapshot JSONB NOT NULL DEFAULT '{}'
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (model_version_id, content_hash)   -- 内容寻址（同内容同快照）

用法（v0.5 P0-2，分离治理事实）：
  causal_model_versions.published_snapshot_id
    = snapshot-ABC      -- 发布指针（不复制、不修改快照）
  validation_runs 记录某次验证用了哪个 snapshot：
    validation_run { run_id, snapshot_id, result, created_at }

  ——"测试使用的内容 = 发布使用的内容"（published_snapshot_id 指向
  验证过的 snapshot）仍成立，但 snapshot 本身从未被修改
  ——同一快照可同时拥有 validated + published 两个治理事实

P4 修正（v0.5 P0-2，原则同步）：
  生产推理只读 Published Snapshot；Model Validation 读 Validation
  Snapshot；两者都必须是 Immutable Snapshot；
  Reasoning Engine 不直接读取可编辑模型表
```

## 2.10.1 Snapshot = 完整可运行认知包（v0.5 P0-3）

> **原则**：Snapshot + ABox Instance Snapshot = Prepare 所需的全部认知输入。
> Prepare 不得回查 live 表（causal_nodes/edges/rules/data_bindings/
> capability_bindings）——否则 Snapshot 只是半个。

```
requirements_json（完整需求包，含能力需求）：
  [{
    requirement_key, node_key, requirement_level,
    data_requirement: { metric_binding / instance_binding_expr /
      instance_key_field / instance_observation / output_mapping },
    capability_requirement: { capability_role / read_only_required /
      capability_contract_ref }
  }]

MUST: Prepare 只消费 Snapshot（+ ABox 实例化）——包含节点/边/规则/
      数据需求/能力需求全部静态信息
MUST: 生产推理绝不查 live 模型表（draft/testing 编辑态）
```

## 2.11 reasoning_contexts（推理上下文，v0.4 新增 P0-1）

> **P0-1（评审）**：prepare_id 必须可持久化（Planner 生成 Plan 后可能
> 几分钟才执行 / 排队 / 审批 / 重试 / 服务重启 / 异步执行）。
> ReasoningContext 是两阶段间**运行态桥梁**，与 ReasoningTrace（Evaluate 后
> 的审计记录）**分离**——trace 不兼任 Prepare 状态。

```
reasoning_contexts（上下文，Prepare 产出；自身即完整可重放的 Prepare Snapshot）
├── prepare_id        VARCHAR(64) PK
├── tenant_id         VARCHAR(64) NOT NULL
├── model_version_id  VARCHAR(64) NOT NULL FK
├── snapshot_id       VARCHAR(64) NOT NULL FK
├── snapshot_hash     VARCHAR(64) NOT NULL
├── target_json       JSONB NOT NULL         -- v0.5 P1：目标实体/绑定
├── time_window_json  JSONB NOT NULL         -- v0.5 P1：时间窗
├── instance_snapshot JSONB NOT NULL         -- 实例化图（冻结）
├── evidence_requirements JSONB NOT NULL     -- requirements[]（requirement_id + key）
├── scope_meta        JSONB NOT NULL         -- scope_complete/restricted/accessible_count
├── authz_scope_hash  VARCHAR(64)            -- v0.5 P1：权限范围哈希
├── algorithm_version_id VARCHAR(64) NOT NULL FK  -- v0.5 P0-1：可定位版本
├── algorithm_profile_version VARCHAR(32) NOT NULL
├── algorithm_params_json JSONB NOT NULL     -- v0.5 P1：不可变 params（非只存 hash）
├── algorithm_config_hash VARCHAR(64) NOT NULL
├── context_hash      VARCHAR(64) NOT NULL   -- 可复现键（见下）
├── prepared_at       TIMESTAMPTZ NOT NULL DEFAULT now()
├── expires_at        TIMESTAMPTZ NOT NULL  -- 生命周期（如 P1D）
└── status            VARCHAR(16) NOT NULL CHECK IN ('prepared','consumed','expired','cancelled')

生命周期：
  prepared → consumed（Evaluate 消费后）
          → expired（超时未消费，回收）
          → cancelled（Plan 取消）
MUST: 持久化存储（非内存 cache）；过期回收任务
MUST: 过期/取消后 Evaluate 拒绝（prepare_id 无效）
MUST: context 自包含（target/window/params/profile 全落库，
      不只存 hash——历史可重放可恢复真实参数）
```

## 2.12 reasoning_traces（推理轨迹，Evaluate 后审计记录，v0.5.1 补 evidence_items）

```
trace_id            VARCHAR(64) PK
prepare_id          VARCHAR(64) NOT NULL FK → reasoning_contexts
evaluation_input_hash VARCHAR(64) NOT NULL   -- v0.5.1：幂等键（覆盖观测+证据）
model_version_id    VARCHAR(64) NOT NULL FK
snapshot_id         VARCHAR(64) NOT NULL FK
observations_json   JSONB NOT NULL           -- EvidenceObservation[]（P0-4）
evidence_items_json JSONB NOT NULL DEFAULT '[]'  -- v0.5.1 P0/P1：非结构化证据
                                                --  （专家记录/文档/维修说明）必须保存原文
                                                --  （不只存 hash——历史重放可见原始证据）
result_snapshot     JSONB NOT NULL           -- Cause Ranking + Evidence Chain
status              VARCHAR(16) NOT NULL CHECK IN ('complete','partial','failed')
latency_ms          INT
created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE (prepare_id, evaluation_input_hash)  -- v0.5.1：幂等键覆盖 observations + evidence_items

幂等/重试语义（v0.5 P1）：
  同 prepare_id + 同 Evaluation Input Hash → 直接返回已有结果
    （网络超时后 Runtime 重试不导致 Plan 失败）
  同 prepare_id + 不同 Evaluation Input Hash → 拒绝（须显式新建
    Evaluation Attempt 或重新 Prepare）

可复现键（v0.4/v0.5.1）：
  = ReasoningContext Hash + Evaluation Input Hash
  ReasoningContext Hash = Model Snapshot Hash + Instance Snapshot Hash
    + Algorithm ID/Version + Algorithm Params Hash + Target/Time Window + Scope
  Evaluation Input Hash = Observations + Evidence Items（含原文归档）
  ——Evaluate 不重新实例化、不换算法（全部冻结于 context），
  可复现自然成立
```

**Evidence（元模型③）**：随 trace 归档，不写入模型对象（§3.1.0 原则）。

---

# 三、Reasoning Prepare（声明证据需求，v0.2 重构）

> **P0-1 核心（评审采纳）**：Reasoning Engine **不取数**。
> 拆为两阶段——Prepare（引擎声明需要什么证据）+ Evaluate（Planner 取证后引擎推理）。
> 与 Planner Runtime v1.0 咬合：knowledge_query step 进入推理，
> data_fetch/capability Tasks 由 Planner 生成、Runtime 执行取数。

```
Planner
  ↓ knowledge_query（Reasoning Prepare 调用）
Reasoning Prepare
  ↓ 产出 Evidence Requirements（声明：需要哪些证据，怎么取）
Planner
  ↓ 生成 data_fetch / capability Tasks（按 Evidence Requirements）
Runtime
  ↓ MES / EAM / 指标 / Capability（真实取数）
Observations / Evidence
  ↓
Reasoning Evaluate（§四）
  ↓ Cause Ranking + Evidence Chain
```

## 3.1 ReasoningPrepare 接口（v0.4：产出持久化 ReasoningContext + 冻结算法）

```
输入：
  model_version（快照）+ target（entity）+ time_window
  + reasoning_mode（v0.4 P0-3：只在 Prepare 消费，Evaluate 不再接受）
输出（ReasoningContext，持久化，不取数）：
  ReasoningPrepareResult:
    prepare_id            -- 稳定推理上下文 ID（RP-001）
    model_snapshot_id / model_snapshot_hash
    target
    instance_snapshot: { nodes: [...], edges: [...] }   -- 实例化图（冻结）
    evidence_requirements: [{
      requirement_id,        -- 本次推理实例 ID（RP001-REQ003）
      requirement_key,       -- 模型级稳定键（equipment_fault_status，v0.4 P1）
      node_key,
      logical_requirement,   -- 需要什么数据（§2.6 逻辑需求）
      instance_scope,        -- 实例范围（instance_binding 展开结果）
      time_window / granularity / aggregation / unit,
      capability_role,       -- primary/supporting（§2.7）
      requirement_level       -- required | optional
    }]
    algorithm: {             -- v0.4 P0-3：算法在 Prepare 冻结
      algorithm_id / version / profile_version / params / config_hash
    }
    scope_meta:            -- 权限范围（v0.3 P1，见 §3.2）
      { scope_complete, scope_restricted, accessible_count }
    prepared_at / expires_at / status
    context_hash

requirement_level 权威来源（v0.3 P1）：
  由 logical_requirement 声明（§2.6 data_bindings 的 requirement_level），
  非 capability_role 推导（primary ≠ required）

算法冻结（v0.4 P0-3，关键）：
  reasoning_mode → Prepare 时经 Algorithm Registry 选择并冻结
    algorithm_id/version/profile/params 进 ReasoningContext
  MUST: Evaluate 不接受 reasoning_mode（不得换算法）——
    如果调用方想 fast → high_accuracy，必须重新 Prepare
  MUST: Evidence Requirements 与冻结算法一致（Prepare 按所选算法的
    max_depth 等 Profile 生成需求；Evaluate 用同一算法，假设一致）

Evaluate 必须消费同一个 prepare_id（v0.3 P0）：
  Evaluate 输入 = prepare_id + observations（EvidenceObservation[]）
  ——不得仅凭 model_version + target 重新实例化，不得换算法
  （ABox 在取证期间可能变化；重实例化/换算法破坏一致性与可复现）
```

## 3.1.1 EvidenceObservation Envelope（v0.4 P0-4，核心接口契约）

> **定义 Planner/Runtime → Reasoning Engine 的观测数据契约**——
> 区分结构化观测（observation）与非结构化证据（evidence_items）：

```
EvidenceObservation（结构化观测，Evaluate 主输入）
├── requirement_id      -- 对应 Prepare 的 requirement_id（可追溯）
├── requirement_key     -- 模型级键（v0.4 P1）
├── instance_ref        -- 实例（device-23；node_key 的类型实例）
├── node_key
├── value / value_type / unit
├── observed_at / time_window
├── source: { source_type: capability|connector|metric, source_ref }
├── quality: { status: valid|stale|suspicious, confidence }
├── provenance: { execution_id, task_id }
└── error: { code, message }      -- 取数失败时

evidence_items[]（非结构化证据，可选）：
  { type: expert_note|document|maintenance_record, content, ref }

示例：
  { requirement_id: 'req-001', node_key: 'equipment_health',
    instance_ref: 'device-23', value: 63, unit: '%',
    source: { source_type: 'capability', source_ref: 'equipment_health_query' },
    quality: { status: 'valid', confidence: 0.95 } }

MUST: Evaluate 输入 = prepare_id + observations[]（EvidenceObservation）
      + evidence_items[]（可选）
MUST: observation 按 requirement_id 关联（Requirement↔Observation↔
      Evidence Chain 完整可追溯）

取证失败任务语义（v0.5.1 P1，跨模块契约）：
  业务数据缺失（DATA_UNAVAILABLE）→ 取证 Task 正常完成，产出
    EvidenceObservation 带 error: { code: DATA_UNAVAILABLE }——
    不是 Task FAILED（防止 Runtime DAG 上游失败 → Evaluate BLOCKED，
    导致 optional missing → PARTIAL 永远到不了）
  Evaluate：required missing → FAILED+422；optional missing → PARTIAL
    （正常业务结果）
  执行基础设施故障（Runtime crash / Capability executor crash /
    认证系统故障）→ 才是 Task FAILED → Evaluate BLOCKED（Runtime Failure）
  ——业务数据缺失由 Reasoning 解释；基础设施故障由 Runtime 失败
```

## 3.2 实例化（Prepare 内完成，不取数）

```
object 节点实例化：
  ① 解析 instance_binding（受限表达式，链式 ≤2 跳）
  ② 沿 TBox 结构关系（belongs_to/located_in）从 ontology ABox 展开
  ③ 双层权限过滤（越权静默丢弃）
  ④ 聚合声明（mode=aggregate）或 per_instance 独立成径
  → 产出实例范围（不取观测值）

metric 节点实例化：
  绑定 = 目标实体 × 时间窗（metric_ref + instance_binding + 时间窗/粒度/聚合/单位）
  → 产出取数需求（不取数）
```

```
MUST: Prepare 只产出 Evidence Requirements + 实例化图，不调用
      Connector/Capability（P0-1）
MUST: 展开沿 Enterprise Semantic Layer 的 ABox（ontology 域）
MUST: 展开结果权限过滤（越权静默，不报错）
MUST: 权限范围记入 scope_meta（v0.3 P1）：
      scope_complete / scope_restricted / accessible_count
      ——不泄露被过滤实体身份（不输出 filtered_ids）
MUST: scope_restricted=true 时，Evaluate 输出的 Cause Ranking
      标注 complete=false + reason=scope_restricted
      （企业审计：不装作"分析了全部设备"）
MUST: 逻辑需求 → 物理数据源的解析由 Planner 在取证阶段完成
      （Capability/Connector Resolution，模型与部署环境解耦）
MUST: Prepare 结果持久化到 reasoning_contexts（v0.5 P2 修正：
      Prepare → reasoning_contexts；Evaluate → reasoning_traces 经
      prepare_id 引用——不再写 trace.input_snapshot）
SHOULD: 展开 > 100 实例且 mode=aggregate → 按聚合策略（operator+predicate+weight）
```

---

# 四、Reasoning Evaluate（消费观测，产出结论）

> **v0.2（P0-1）**：Evaluate 只消费 Planner 取证后的 Observations/Evidence，
> 不取数、不调用外部系统。与 §三 Prepare 组成两阶段。

## 4.1 架构

```
Reasoning Engine（实现 Causal Reasoning Contract §3.1.2）
  ├── prepare/              # Prepare 阶段（§三：声明证据需求）
  ├── evaluate/             # Evaluate 阶段（本设计：消费观测推理）
  │     ├── sign_propagation/  # Phase 1 默认算法
  │     ├── observability/     # 观测方向推导（三口径）
  │     └── aggregator/        # 归因排序聚合
  ├── registry/             # 算法注册表（含 Algorithm Profile）
  └── explain/              # explain_level 输出
```

**算法注册机制（P2）：**

```
reasoning_algorithms（逻辑算法）表：
  algorithm_id     VARCHAR(32) PK        -- 'sign_propagation'
  name             VARCHAR(64) NOT NULL

reasoning_algorithm_versions（版本，v0.5 P0-1 新增）：
  algorithm_version_id VARCHAR(64) PK    -- 可定位的不可变版本
  algorithm_id      VARCHAR(32) NOT NULL FK
  version           VARCHAR(32) NOT NULL -- '1.0' / '1.2'
  contract_version  VARCHAR(16) NOT NULL -- 实现的契约版本
  profile_version   VARCHAR(32) NOT NULL
  profile_json      JSONB NOT NULL       -- Algorithm Profile（graph_type/max_depth）
  params_schema     JSONB NOT NULL       -- 参数声明
  handler           VARCHAR(128) NOT NULL
  implementation_hash VARCHAR(64) NOT NULL -- 实现哈希（可定位/审计）
  status            VARCHAR(16) CHECK IN ('active','beta','deprecated')
  UNIQUE (algorithm_id, version)

ReasoningContext 冻结（v0.5 P0-1，闭环）：
  algorithm_version_id + algorithm_config（immutable params）+
    algorithm_config_hash
  MUST: config_hash → 不可变 config 有可查询映射（历史重放可恢复真实参数，
    不能只存 hash）
  MUST: Context 可定位到具体 algorithm_version_id（Registry 中存在）

MUST: 算法实现 Causal Reasoning Contract（输入/输出/约束，§3.1.2）
MUST: 新算法经注册 + 测试接入；Planner 只感知 reasoning_mode
      （default/fast/explainable/high_accuracy），不感知算法本身（§4.4.3）
MUST: Evaluate 只消费输入观测/证据，不产生外部副作用（P6）
```

## 4.5 Algorithm Profile（v0.2，评审 P0-3）

> **DAG 不是存储约束，是算法 Profile 约束**——模型可表达一般有向图；
> 算法声明自己能处理的图类型，调用前做兼容性校验。

```
Algorithm Profile 字段：
  graph_type: 'dag' | 'general_directed' | 'temporal'   -- 算法能处理的图
  max_depth: int                                        -- 路径/推理深度上限
  features: ['feedback_handling', 'finite_unrolling', ...]

sign_propagation_v1.profile：
  graph_type: 'dag'       -- 要求无环
  max_depth: 3

调用流程：
  Model → Algorithm Compatibility Validation
    → 模型有环 且 算法 profile.graph_type=dag
    → 拒绝使用 sign_propagation_v1
    → 选择其它算法 / finite_unrolling / 或 Phase 1 发布 Profile 拒绝

Phase 1 发布 Profile：
  MUST: Phase 1 仅支持 DAG 模型发布（sign_propagation_v1 适用）
  MUST: 有环模型可存储（存储层允许），但 Phase 1 不可发布（
        发布校验按 Phase 1 Profile；未来贝叶斯/时序算法接入后可发布）
```

## 4.2 默认算法：符号传播 + 路径排序（sign_propagation_v1）

### 4.2.1 路径枚举

```
输入：entry_point 节点 + 快照边图
流程：
  ① 从 entry_point 沿反向边（target → source）做 DAG 遍历
  ② 枚举到叶子原因节点的所有路径 p（原因 → … → entry_point）
  ③ 每条路径计算：
     S(p) = ∏ edges.effect（±1 之积）
     d'(p) = d × S(p)（原因节点对目标的解释方向）
     节点 i 的预期方向 e(i) = d × S(i→entry_point 子路径符号积)
```

### 4.2.2 观测匹配（obs_match）

```
按节点观测类型（§3.1.2 三口径）推导观测方向：
  ① 数值序列：observation_window 首尾差 vs 阈值 → up/down/unchanged/unknown
     （绝对/相对阈值，零均值禁相对默认）
  ② 离散状态：窗口首尾状态跃迁（目标态集合声明）
  ③ 聚合计数：当前窗口 vs 基线窗口

m(i)（节点匹配度）：
  观测方向与 e(i) 一致 → +1
  相反                 → -1（一票否决）
  无数据/unknown       → 1（中性）
  unchanged           → 0.5（弱支持）

obs_match(path)：
  存在任一 m(i) = -1 → obs_match = 0（反向一票否决）
  否则 → obs_match = (∏ m(i))^(1/n)（几何均值，m∈{0.5,1}，实数域恒有定义）
```

### 4.2.3 归因排序

```
score(path) = |∏ strength| × ∏ confidence × obs_match(path)
节点聚合 = 取该节点全部入径的最高分路径
输出 Cause Ranking：候选原因按 score 降序
  携带：d'(p) 方向标注 / evidence_chain / confidence
同一原因节点正负路径并存 → 分别列出，标注"方向冲突待数据裁决"
```

### 4.2.4 explain_level 实现

```
basic     → 只输出 top 原因 + 一句话解释
detailed  → 完整 evidence_chain（每步观测 + 数据来源）
audit     → 全部中间步骤 + 数据来源 + 阈值/规则明细（安全场景）
```

## 4.3 契约输出（v0.4 统一 node_key + instance_ref）

```
Cause Ranking（§4.4.3）：
  node_key / instance_ref（v0.4 P1：区分类型节点与实例节点——
    同一 node_key 可对应多实例：equipment_failure / device-23）
  direction_explanation / score / confidence
  evidence_chain[每步: step_node_key, relation, observation{...},
    data_requirements_met]
meta：model_id / version / algorithm / prepare_id / trace_id / complete
```

```
MUST: 输出必须可解释（每项带 evidence_chain）
MUST: Required evidence missing → FAILED + 422 +
      missing_required_requirements（v0.5 P1）
MUST: Optional evidence missing → PARTIAL + 正常业务结果（非 422）+
      complete=false + missing_optional_requirements
      （防止 Runtime 把非 2xx 一律判为 Task Failure）
MUST: 超时 → complete=false 部分结果（不假完整，P4）
MUST: scope_restricted → complete=false + reason=scope_restricted（§3.2）
```

---

# 五、与既有模块对接（v0.2 更新）

| 既有模块 | 对接点 |
|---|---|
| Enterprise Semantic Layer（ontology） | TBox 词汇引用（entity_type/relation_type）；ABox 实例展开（object 节点，Prepare 阶段）；causal namespace 排除 QU/ABox |
| data_requirement（§3.1.4） | data_bindings 表落地（逻辑需求）；instance_binding 受限表达式解析 |
| Causal Reasoning Contract（§3.1.2） | 推理引擎实现契约；算法注册机制 |
| Reasoning Contract（§4.4.3） | 输入（模型+观测+证据）/输出（Cause Ranking+Evidence Chain） |
| Model Governance（§3.4） | 发布时建快照；变更 → 新版本新快照；推理只读快照 |
| Model Validation（§3.7 Step 5） | 历史案例回放 → 命中率评估（复用推理引擎 + trace） |
| **Planner（L3 v1.0，v0.2/v0.3 关键）** | knowledge_query → **Planning-time Prepare**（v0.3 P0：Prepare 在 Planner 解释期调用，非执行期）→ 生成 Evidence Requirements → knowledge_query Handler 产出 PlanFragment = **0..N 取证 Task + 1 Evaluate Task**（v0.3 P0 跨文档契约：Planner v1.0 的 knowledge_query "1 Task" 映射微调为 Fragment 多 Task，见 Planner 文档同步）→ Runtime 取数 → Evaluate（消费 prepare_id）——**引擎不取数、不在运行时动态加 Task** |

---

# 六、目录结构（新增 reasoning_engine 模块，v0.2 两阶段）

```
apps/earp-server/src/earp_server/
├── bmc/
│   ├── metamodel/            # 模型 CRUD + 版本 + 快照（Logical Model + Model Version）
│   ├── reasoning_engine/     # 本设计（推理引擎）
│   │   ├── __init__.py
│   │   ├── models.py         # reasoning_traces / reasoning_algorithms 表
│   │   ├── prepare.py        # Prepare：实例化 + Evidence Requirements（v0.2）
│   │   ├── evaluate/         # Evaluate：消费观测推理（v0.2）
│   │   │   ├── observe.py        # 观测方向推导（三口径）
│   │   │   ├── sign_propagation.py # Phase 1 默认算法
│   │   │   └── aggregator.py     # 归因排序聚合
│   │   ├── registry.py       # 算法注册表（含 Algorithm Profile）
│   │   ├── graph_loader.py   # 快照 → CausalGraphSnapshot（内存图，v0.2 P3）
│   │   ├── explain.py        # explain_level 输出
│   │   └── routes.py         # /v1/ecmc/reasoning/...
│   └── governance/           # 模型治理（issue/审批/change_log）
├── ontology/                 # 现有（Enterprise Semantic Layer）
└── planner/                  # 现有（消费推理结果，取证由 Planner 编排）
```

---

# 七、API 草案（v0.3 两阶段接口 + invoke 定位修正）

```
POST /v1/ecmc/reasoning/prepare
    — 输入（v0.5.1 明确快照选择路径）：
      Production：{ model_id, version, target, time_window, reasoning_mode }
        → 服务经 version → published_snapshot_id → Snapshot（生产不可
          任意指定 validation snapshot）
      Model Validation：{ snapshot_id, target, ... }
        → 显式指定 validation snapshot（经 /validate 路径执行）
    → ReasoningContext（prepare_id + Evidence Requirements + 实例化图，不取数）
POST /v1/ecmc/reasoning/evaluate
    — 输入 {prepare_id, observations: EvidenceObservation[], evidence_items?, explain_level}
    → Cause Ranking + Evidence Chain（消费同一 prepare_id + 冻结算法，
      不接受 reasoning_mode——换算法须重新 Prepare）
POST /v1/ecmc/reasoning/invoke
    — 测试/回放接口（v0.3 P0 降级，非生产主路径）：
      仅允许两种用法：
      a) 调用方直接提供 observations/evidence（服务内部 prepare →
         validate supplied evidence → evaluate，不调用 Planner）
      b) Model Validation / 单元测试 / 历史案例回放
      禁止：内部调用 Planner/Runtime 取数（避免
      Planner→ECMC→Planner→Runtime 循环，破坏边界）
GET  /v1/ecmc/reasoning/traces/{trace_id}  — 推理轨迹（可复现/审计）
POST /v1/ecmc/reasoning/validate  — Model Validation 回放（历史案例 → 命中率）
GET  /v1/ecmc/reasoning/algorithms — 算法注册列表（含 Profile）

生产主路径（唯一）：
  Planner → Prepare（Planning-time）→ Plan（取证 Tasks + Evaluate Task）
  → Runtime 取证 → Evaluate（prepare_id）
```

（传输层 HTTP 为参考，gRPC/内存/EventBus 由 Runtime 集成层决定。）

---

# 八、开放问题（v0.3 更新；已拍板项移除）

1. **路径枚举复杂度**：DAG 反向枚举最坏情况指数爆炸——限制深度 ≤ 3 跳 + 每节点最多 N 条路径（Algorithm Profile max_depth）
2. **strength/confidence 校准**：Model Validation 回测如何回写校准值（仅 testing 阶段可校准，published 不可变——校准只影响新版本）
3. **图数据库评估时机**：Phase 3 多跳/超大规模评估的量化门槛（节点数/跳数/延迟）
4. **取证编排细化**（v0.2 新）：Planner 侧 data_fetch/capability Tasks 的并行与超时聚合（避免整体超时）——属 Planner Runtime 实现迭代
5. **模型与部署解耦验证**（v0.2 新）：逻辑需求 → 物理数据源解析（Capability/Connector Resolution）在跨租户/行业复用时的验证

**已拍板（v0.2）**：
- 推理统一走快照（CausalGraphSnapshot 加载内存 + Python 遍历，非 Recursive CTE 推理）——P3
- 取数移出引擎（Prepare/Evaluate 两阶段）——P0-1
- DAG 是算法 Profile 约束非存储约束；Phase 1 发布 Profile 仅支持 DAG——P0-3

---

# 九、v0.2 评审处置记录（v0.1 → v0.2）

---

# 十、v0.3 评审处置记录（v0.2 → v0.3）

| 级别 | 评审意见 | 处置 |
|---|---|---|
| P0-1 | Prepare/Evaluate 间缺稳定推理上下文（Evaluate 可能重新实例化，ABox 变化破坏一致性） | §3.1：新增 ReasoningPrepareResult（prepare_id + instance_snapshot + content_hash）；Evaluate 必须消费同一 prepare_id，不得凭 model_version+target 重新实例化 |
| P0-2 | knowledge_query=1 Task 与两阶段推理冲突（跨文档） | §五 + Planner v1.0.1：Prepare = Planning-time；knowledge_query Handler 产出 0..N 取证 Task + 1 Evaluate Task（Step→Fragment 多 Task，Planner 架构不动） |
| P0-3 | /invoke 内部调用 Planner/Runtime 取数破坏边界 | §七：/invoke 降级为测试/回放接口（调用方提供 evidence 或仅 Model Validation/单测）；生产主路径 = Planner→Prepare→Plan→Runtime 取证→Evaluate |
| P1-1 | Evidence Requirement 缺稳定 ID | §3.1：evidence_requirements 增加 requirement_id（req-001），Runtime 回传 Observation 带 requirement_id（Requirement↔Observation↔Evidence Chain 可追溯） |
| P1-2 | required 权威来源不清 | §2.6：data_bindings 增加 requirement_level（required/optional 声明）；不通过 capability_role 推导（primary≠required） |
| P1-3 | 权限过滤完全静默 | §3.2：scope_meta（scope_complete/scope_restricted/accessible_count，不泄露实体身份）；scope_restricted → Cause Ranking 标注 complete=false + reason=scope_restricted |
| P1-4 | 快照缺 Schema | §2.10：补全 causal_model_snapshots（snapshot_id/model_version_id 1:1/content_hash/nodes/edges/rules/requirements/applicability）；published 版本恰好一个不可变快照 |
| P1-5 | Edge 唯一键太严格 | §2.4：edge_key 稳定身份（1:N 边，语义由 relation_type_ref+lag 区分），不强制 source→target 唯一 |
| P1-6 | Rule 唯一键太严格 | §2.5：rule_key 稳定身份；节点可 1:N 同类型 Rule（health<80/temp>90/vibration>X） |

**留待 Reasoning Algorithm v1 专门评审**：unknown=1（无数据=完全支持）、evidence_coverage、epistemic_status、反向一票否决置信阈值、structural×observation×coverage×epistemic 组合。

| 级别 | 评审意见 | 处置 |
|---|---|---|
| P0-1 | Reasoning Engine 不得自己取数（与 Planner v1.0 冲突） | §三/§四重构：Prepare（声明 Evidence Requirements，不取数）→ Planner 取证（data_fetch/capability Tasks）→ Evaluate（消费观测推理）；引擎纯知识层，取数编排归 Planner |
| P0-2 | model_id PK + version 只能存一个版本（Schema 错误） | §2.2：Logical Model（causal_models）+ Model Version（causal_model_versions）分离；nodes/edges/rules 引用 model_version_id + 稳定 node_key；跨版本引用 {model_id, version, node_key} 三元组 |
| P0-3 | DAG 不应固化为存储约束 | §4.5：Algorithm Profile（graph_type/max_depth）声明算法能力；调用前兼容性校验；存储层允许一般有向图；Phase 1 发布 Profile 仅 DAG |
| P1 | 递归 CTE vs JSON Snapshot 混用 | P3 修正：PostgreSQL 存/查/版本/快照；graph_loader 加载 CausalGraphSnapshot 内存图 + Python 遍历（图计算与算法解耦） |
| P1 | unknown=1 让无证据路径得高分 | **留待 Reasoning Algorithm v1 专门评审**（evidence_coverage 拆方向匹配与证据覆盖率） |
| P1 | Edge 缺 epistemic_status | **留待 Algorithm v1 评审**（expert_hypothesis/empirical_association/validated_causal/deterministic） |
| P1 | dependency_ok 太粗 | §2.8：结构化 dependency_resolution（required/optional 逐项 resolved/missing）；dependency_ok 仅 denormalized summary |
| P1 | 逻辑 Data Requirement 与物理 Binding 分离 | §2.6/§2.7：logical_requirement（equipment_fault_status）不绑物理 connector；运行时由 Capability/Connector Resolution 解析（跨租户/行业复用） |
| P1 | applicability 双数据源 | §2.9：causal_applicability 结构化表为权威；版本表 applicability 仅 projection/cache |
| P1 | Trace 可复现缺 algorithm 版本 | §2.10：可复现键 = 模型快照哈希 + Algorithm ID/Version + Params Hash + 观测快照 + 证据快照 |
| P2 | 一票否决需置信阈值 | **留待 Algorithm v1 评审**（contradiction confidence >= threshold 才 veto，低置信转 penalty） |

---

# 十一、v0.4 评审处置记录（v0.3 → v0.4，Framework 收口）

| 级别 | 评审意见 | 处置 |
|---|---|---|
| P0-1 | prepare_id 存在哪？生命周期？服务重启后能否 Evaluate？trace 兼任 Prepare 状态矛盾 | §2.11/§2.12：新增持久化 reasoning_contexts（prepare_id/snapshot/instance/requirements/scope/algorithm 冻结/context_hash/expires_at/status: prepared→consumed/expired/cancelled）；trace 与 context 分离（trace 只记 Evaluate 后审计） |
| P0-2 | testing 需 Model Validation 但 testing 无 snapshot（矛盾） | §2.10：snapshot_type = validation \| published；model_version → N validation 快照 → 1 published（可 pin validation 快照，不复制）；"测试的模型 = 发布的模型" |
| P0-3 | Algorithm 需 Prepare 冻结，Evaluate 不得换算法 | §3.1：reasoning_mode 仅 Prepare 消费 → 冻结 algorithm_id/version/profile/params 进 context；Evaluate 不接受 reasoning_mode（换算法须重新 Prepare） |
| P0-4 | observations/evidence 无数据契约 | §3.1.1：EvidenceObservation Envelope（requirement_id/instance_ref/node_key/value/unit/source/quality/provenance/error）+ evidence_items（非结构化，可选）；按 requirement_id 关联可追溯 |
| P1-1 | 模型级 requirement_key 与运行时 requirement_id 混用 | §2.6/§3.1：requirement_key（模型稳定键，snapshot 保存）vs requirement_id（本次 Prepare 实例，RP001-REQ003） |
| P1-2 | dependency_resolution 混入部署状态 | §2.8：拆 Model Dependency Resolution（静态：TBox/capability contract 合法）vs Runtime Binding Readiness（动态：Provider/Connector/credential，属 Planner/Capability Resolution，不进模型） |
| P1-3 | node_key 引用无真正 FK | §2.2：复合外键（model_version_id, node_key）REFERENCES causal_nodes——用于 edge/rule/binding 全部引用 |
| P1-4 | 输出 node_id 命名漂移 | §4.3：Cause Ranking 输出统一 node_key + instance_ref（类型节点 vs 实例节点区分） |

**Framework 冻结标准**（评审）：Storage + Prepare/Evaluate Framework 完成后冻结；
下一轮单独 Reasoning Algorithm v1（structural × observation × coverage × epistemic 组合、unknown=1、epistemic_status、veto 阈值）。

---

# 十二、v0.5 评审处置记录（v0.4 → v0.5，Framework Closure）

| 级别 | 评审意见 | 处置 |
|---|---|---|
| P0-1 | Algorithm 版本冻结在数据模型上未闭环（Context 说冻结 1.2 但 Registry 无可定位版本） | §4.1：reasoning_algorithms（逻辑）+ reasoning_algorithm_versions（版本：version/profile_version/profile_json/params_schema/handler/implementation_hash）；Context 冻结 algorithm_version_id + 不可变 config（config_hash→config 可查询映射，历史重放可恢复真实参数） |
| P0-2 | Snapshot 不可变与 validation 升级 published 矛盾（修改 type 破坏 immutable） | §2.10：Snapshot 无生命周期身份（绝对不可变）；validation/published 分离为治理事实——published_snapshot_id 指针 + validation_run 记录；同一快照可同时拥有两个治理事实；P4 原则修正（生产读 Published、验证读 Validation、均不可变） |
| P0-3 | Snapshot 缺 Prepare 所需全部信息（capability_role 要回查 live 表） | §2.10.1：requirements_json = 完整需求包（data_requirement + capability_requirement{role/read_only/contract_ref}）；原则：Snapshot + ABox 实例快照 = Prepare 全部认知输入，不查 live 表 |
| P1-1 | ReasoningContext 缺 target/time_window/params/profile/authz scope | §2.11：补 target_json/time_window_json/authz_scope_hash/algorithm_params_json（不可变 params 落库，不只存 hash）——context 自包含可重放 |
| P1-2 | Prepare 判断 Runtime Binding Readiness 职责冲突 | §2.8/§3.1：readiness 完全留给 Planner/Capability Resolver（ResolvedEvidenceRequirement.binding_status）；ECMC 不查 Connector/credential/provider |
| P1-3 | Evaluate 需幂等/重试语义 | §2.12：UNIQUE(prepare_id, observation_hash)——同 hash 重试返回已有结果；异 hash 拒绝（须新 Attempt/重新 Prepare） |
| P1-4 | required/optional 失败语义统一 | §4.3：Required missing → FAILED + 422 + missing_required_requirements；Optional missing → PARTIAL + 正常业务结果（非 422）+ missing_optional_requirements（防 Runtime 非 2xx 一律判失败） |
| P2 | 残留描述清理 | §2.7 logical_requirement→requirement_key；§3.2 Prepare 写 trace → 改 reasoning_contexts；旧 UNIQUE 描述清除 |

**Framework 冻结标准达成**：Storage + Prepare/Evaluate Framework 收口。
下一轮：Causal Reasoning Algorithm v1（structural × observation × coverage × epistemic、unknown=1、epistemic_status、veto 阈值）。

---

# 十三、v0.5.1 评审处置记录（v0.5 → v0.5.1，Framework Freeze Patch）

| 级别 | 评审意见 | 处置 |
|---|---|---|
| P0/P1 | Trace 未存 evidence_items（只存 hash，历史重放找不到原始证据） | §2.12：reasoning_traces 增加 evidence_items_json（原文归档）；observation_hash → evaluation_input_hash（幂等键覆盖 observations + evidence_items） |
| P1 | Prepare 加载哪个 Snapshot 有歧义（Production vs Validation） | §七 API：Production 只传 model_id+version → 经 published_snapshot_id → Snapshot（生产不可指定 validation）；Model Validation 显式传 snapshot_id（经 /validate）；causal_model_versions 补 published_snapshot_id 字段 |
| P1 | capability_contract_ref 来源未闭环 | §2.7：补 capability_contract_ref（逻辑 Capability Contract，非物理实例）+ 复合 FK（model_version_id, node_key, requirement_key）→ causal_data_bindings（防悬空引用） |
| P1 | 取证失败 Task FAILED 会让 optional missing → Evaluate BLOCKED（PARTIAL 永远到不了） | §3.1.1：业务数据缺失（DATA_UNAVAILABLE）→ 取证 Task 正常完成 + Observation 带 error envelope（非 Task FAILED）；仅基础设施故障（crash/认证）→ Task FAILED → BLOCKED——业务缺失由 Reasoning 解释、基础设施故障由 Runtime 失败 |

**残留清理**：P4 原则修正（生产读 Published / 验证读 Validation / 永不读编辑表）；版本模型描述（1 版本 → N 快照 → 0..1 published_snapshot_id）；旧 UNIQUE 描述清除。

**冻结声明**：Causal Model Storage + Prepare/Evaluate Framework 达到 v1.0 baseline 标准——模型存/版本化/快照/实例化/证据需求/取证/证据回传/算法冻结/Prepare-Evaluate 衔接/审计/重试/复现全部闭环。不再扩架构。
