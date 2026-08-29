# Causal Model Storage & Reasoning Engine — L3 实现设计

**文档编号：DESIGN-ECMC-CAUSAL-L3**
**版本：v0.1（draft）**
**日期：2026-08-28**

> 上游：`arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21，§3.1 CausalModel / §3.1.2 Causal Reasoning Contract + Phase 1 参考实现 / §3.1.4 data_requirement / §4.4.3 Reasoning Contract）、`arch/design/2026-08-07-ontology-layer-design.md`（Enterprise Semantic Layer：TBox/ABox）、`arch/L2/02-reasoning/planner-specification.md`（v1.1）
> 定位：ECMC 的核心技术壁垒——因果模型如何**存储、实例化、推理**。
> 技术栈：FastAPI + SQLAlchemy 2 async + PostgreSQL 16（+ 递归 CTE），沿用"基础设施最小化"原则（图数据库留待 Phase 3 评估）；推理引擎 Phase 1 = 符号传播 + 路径排序（默认实现，可替换）。

---

# 一、设计原则

```
P1  存储与推理分离——模型存储（可版本化/快照）与推理执行（算法可替换）解耦
P2  契约驱动——推理引擎实现 Causal Reasoning Contract（§3.1.2），
     算法可替换（符号传播为 Phase 1 默认，贝叶斯/图搜索/LLM 经注册接入）
P3  PG 优先——递归 CTE 覆盖 2-3 跳（先高频场景）；图数据库留待
     多跳/超大规模评估（Phase 3）
P4  不可变快照——推理只读已发布版本快照，不接触 draft/testing
P5  可复现——同输入（模型版本 + 观测 + 证据）同输出（reasoning_trace）
```

---

# 二、存储模型（PostgreSQL）

## 2.1 表总览

| 表 | 说明 |
|---|---|
| `causal_models` | 因果模型主表（版本化资产） |
| `causal_nodes` | 节点（元模型① Node） |
| `causal_edges` | 有向影响边（元模型② Relation） |
| `causal_rules` | 节点规则（元模型④ Rule：predicate/threshold/direction） |
| `causal_data_bindings` | 数据绑定（元模型⑤ Data Binding） |
| `causal_capability_bindings` | 能力绑定（元模型⑥ Capability Binding） |
| `causal_model_snapshots` | 版本快照（发布时不可变拷贝，推理只读它） |
| `causal_applicability` | 适用范围声明 |
| `reasoning_traces` | 推理轨迹（Evidence 归档，元模型③） |

## 2.2 causal_models（主表）

```
model_id            VARCHAR(64) PK
tenant_id           VARCHAR(64) NOT NULL
data_domain_id      VARCHAR(64) NOT NULL
name / description  TEXT NOT NULL
version             VARCHAR(32) NOT NULL          -- 语义化版本
status              VARCHAR(16) NOT NULL CHECK IN ('draft','testing','published','deprecated')
dependency_ok       BOOLEAN NOT NULL DEFAULT true  -- 依赖完整标志（正交布尔）
applicability_json  JSONB NOT NULL                -- 适用范围（实例集合/行业标签）
owner / created_at / updated_at / published_at
UNIQUE (tenant_id, model_id, version)
```

## 2.3 causal_nodes（节点，元模型①）

```
node_id             VARCHAR(64) PK
model_id            VARCHAR(64) NOT NULL FK
node_seq            INT NOT NULL
entity_type_ref     VARCHAR(64) NOT NULL          -- TBox entity_type（object|metric）
entry_point         BOOLEAN NOT NULL DEFAULT false
entry_direction     VARCHAR(8)                    -- entry_point=true 时：up|down
entry_description   TEXT                          -- 入口语义描述（供 Planner 匹配）
aggregation_mode    VARCHAR(16) NOT NULL DEFAULT 'per_instance'
                    CHECK IN ('per_instance','aggregate')
aggregation_operator VARCHAR(16)                   -- count|ratio|max|min|avg
aggregation_predicate JSONB                        -- count/ratio 的实例级谓词（引用 TBox attr/metric）
aggregation_weight_ref VARCHAR(64)                 -- 权重来源（缺省等权）
observation_window  JSONB                         -- 当前观测窗口声明
```

## 2.4 causal_edges（有向影响边，元模型②）

```
edge_id             VARCHAR(64) PK
model_id            VARCHAR(64) NOT NULL FK
source_node_id      VARCHAR(64) NOT NULL FK
target_node_id      VARCHAR(64) NOT NULL FK
relation_type_ref   VARCHAR(64) NOT NULL          -- TBox causal namespace 关系类型
effect              VARCHAR(1) NOT NULL CHECK IN ('+','-')
strength            FLOAT NOT NULL DEFAULT 0.5     -- 0-1（发布补齐）
lag                 VARCHAR(16)                    -- 滞后周期（如 '7d'）
confidence          FLOAT NOT NULL DEFAULT 0.5     -- 作者置信度（≠ fact confidence）
UNIQUE (model_id, source_node_id, target_node_id)
```

**约束**：`(source_node_id, target_node_id)` 构成 DAG——编译期/发布时环路检测（递归 CTE 或应用层拓扑排序）。

## 2.5 causal_rules（节点规则，元模型④）

```
rule_id             VARCHAR(64) PK
model_id            VARCHAR(64) NOT NULL FK
node_id             VARCHAR(64) NOT NULL FK
rule_type           VARCHAR(16) NOT NULL CHECK IN ('predicate','threshold','direction_rule')
rule_spec           JSONB NOT NULL                -- 如 {attr:'status', op:'==', value:'failed'}
                                                  --   / {metric:'health', op:'>=', value:90}
                                                  --   / {target_states:['failed'], ...}
```

## 2.6 causal_data_bindings（数据绑定，元模型⑤）

```
binding_id          VARCHAR(64) PK
model_id            VARCHAR(64) NOT NULL FK
node_id             VARCHAR(64) NOT NULL FK
source_kind         VARCHAR(16) NOT NULL CHECK IN ('connector','capability')
source_ref          VARCHAR(64) NOT NULL          -- connector_id / capability_id（active）
metric_binding      JSONB                         -- metric 节点：{metric_ref, instance_binding, time_window, aggregation, unit}
instance_binding_expr JSONB                       -- object 节点：受限表达式（链式 ≤2 跳）
instance_key_field  VARCHAR(64)                   -- 实例标识字段
instance_observation VARCHAR(64)                  -- 实例观测字段
baseline_window_ref VARCHAR(64)                   -- 引用（aggregate 模式，权威在 aggregation）
output_mapping      JSONB                         -- 输出字段 → 节点取值映射
```

## 2.7 causal_capability_bindings（能力绑定，元模型⑥）

```
cap_binding_id      VARCHAR(64) PK
model_id            VARCHAR(64) NOT NULL FK
node_id             VARCHAR(64) NOT NULL FK
capability_id       VARCHAR(64) NOT NULL          -- Capability Center 注册 id
read_only_required  BOOLEAN NOT NULL DEFAULT true -- type=query / side_effect=read-only
```

**一致性**（§3.1.4）：source_kind=capability 时 data_binding.source_ref 与 capability_binding.capability_id 必须一致（同 id）；connector 源禁 capability_binding。

## 2.8 causal_model_snapshots（版本快照，P4）

```
snapshot_id         VARCHAR(64) PK
model_id            VARCHAR(64) NOT NULL
version             VARCHAR(32) NOT NULL
nodes_json          JSONB NOT NULL                -- 发布时不可变拷贝（节点/边/规则/绑定全量）
edges_json          JSONB NOT NULL
rules_json          JSONB NOT NULL
bindings_json       JSONB NOT NULL
content_hash        VARCHAR(64) NOT NULL          -- 内容哈希（防篡改 + 变更检测）
snapshot_time       TIMESTAMPTZ NOT NULL DEFAULT now()
```

**为什么快照**：推理只读快照（不接触可编辑的工作表）；源模型修改 → 新版本 → 新快照；旧快照永不可变（可复现 + 审计）。

## 2.9 reasoning_traces（推理轨迹，Evidence 归档）

```
trace_id            VARCHAR(64) PK
tenant_id           VARCHAR(64) NOT NULL
model_id / version  VARCHAR(64) / VARCHAR(32) NOT NULL
snapshot_id         VARCHAR(64) NOT NULL FK
request_hash        VARCHAR(64) NOT NULL          -- 输入（观测+证据）哈希，同输入同输出校验
algorithm           VARCHAR(32) NOT NULL          -- 实际使用的算法（如 'sign_propagation_v1'）
input_snapshot      JSONB NOT NULL                -- 实例绑定 + 观测 + 证据
result_snapshot     JSONB NOT NULL                -- Cause Ranking + Evidence Chain
status              VARCHAR(16) NOT NULL CHECK IN ('complete','partial','failed')
latency_ms          INT
created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
```

**Evidence（元模型③）**：随 trace 归档，不写入模型对象（§3.1.0 原则）。

---

# 三、实例化（类型级 → 实例级）

## 3.1 object 节点实例化

```
输入：推理目标实体（如 3 号矿）+ 模型快照 + instance_binding 表达式
流程：
  ① 解析 instance_binding（受限表达式，链式 ≤2 跳）：
     $target_entity → 目标实体
     $target_entity.<relation>.<dir>[.<entity_type>] → 展开实例集合
  ② 沿 TBox 结构关系（belongs_to/located_in）展开（从 ontology ABox）
  ③ 双层权限过滤（展开越权实体静默丢弃）
  ④ 聚合（mode=aggregate）或 per_instance 独立成径
  ⑤ 按 instance_data_binding 取观测值（per 实例）
```

```
MUST: 展开沿 Enterprise Semantic Layer 的 ABox（ontology 域）
MUST: 展开结果权限过滤（越权静默，不报错）
MUST: 实例化结果记入 trace（input_snapshot，可复现）
SHOULD: 展开 > 100 实例且 mode=aggregate → 按聚合策略（operator+predicate+weight）
```

## 3.2 metric 节点实例化

```
metric 节点无 ABox 实例（§3.1.4）：
  绑定 = 目标实体 × 时间窗：
    metric_ref（TBox metric 类型）
    instance_binding（绑定到目标实体或其展开子集）
    time_window + 粒度 + 聚合 + 单位
  数据源：data_requirement.source_ref（Connector/指标 API/数据中台）
```

```
MUST: metric 观测按声明的时间窗/粒度/聚合取数
MUST: 取数失败 → unknown（obs_match 中性，见推理引擎 §4.4）
```

---

# 四、Reasoning Engine（Phase 1 默认实现）

## 4.1 架构

```
Reasoning Engine（实现 Causal Reasoning Contract §3.1.2）
  ├── sign_propagation/     # Phase 1 默认算法（本设计）
  ├── registry/             # 算法注册表（未来：bayesian/graph_search/llm/...）
  ├── observability/        # 观测方向推导（三口径）
  └── aggregator/           # 归因排序聚合
```

**算法注册机制（P2）：**

```
reasoning_algorithms 表：
  algo_id         VARCHAR(32) PK        -- 'sign_propagation_v1' | 'bayesian_v1' | ...
  contract_version VARCHAR(16) NOT NULL -- 实现的契约版本
  status          VARCHAR(16) CHECK IN ('active','beta','deprecated')
  params_schema   JSONB                 -- 算法参数声明
  handler         VARCHAR(128)          -- 实现入口

MUST: 算法实现 Causal Reasoning Contract（输入/输出/约束，§3.1.2）
MUST: 新算法经注册 + 测试接入；Planner 只感知 reasoning_mode
      （default/fast/explainable/high_accuracy），不感知算法本身（§4.4.3）
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

## 4.3 契约输出

```
Cause Ranking（§4.4.3）：node_id / direction_explanation / score /
  confidence / evidence_chain[每步: step_node_id, relation,
  observation{direction,value,source}, data_requirements_met]
meta：model_id / version / algorithm / reasoning_trace_id / complete
```

```
MUST: 输出必须可解释（每项带 evidence_chain）
MUST: 数据不足 → complete=false + missing_requirements（422 语义，非 404）
MUST: 超时 → complete=false 部分结果（不假完整，P4）
```

---

# 五、与既有模块对接

| 既有模块 | 对接点 |
|---|---|
| Enterprise Semantic Layer（ontology） | TBox 词汇引用（entity_type/relation_type）；ABox 实例展开（object 节点）；causal namespace 排除 QU/ABox |
| data_requirement（§3.1.4） | data_bindings 表落地；instance_binding 受限表达式解析 |
| Causal Reasoning Contract（§3.1.2） | 推理引擎实现契约；算法注册机制 |
| Reasoning Contract（§4.4.3） | 输入（模型+观测+证据）/输出（Cause Ranking+Evidence Chain） |
| Model Governance（§3.4） | 发布时建快照；变更 → 新版本新快照；推理只读快照 |
| Model Validation（§3.7 Step 5） | 历史案例回放 → 命中率评估（复用推理引擎 + trace） |
| Planner（L3） | knowledge_query step → 调本引擎（§4.4.3 reasoning_mode） |

---

# 六、目录结构（新增 reasoning_engine 模块）

```
apps/earp-server/src/earp_server/
├── bmc/
│   ├── metamodel/            # 模型 CRUD + 快照（causal_models/nodes/edges/...）
│   ├── reasoning_engine/     # 本设计（推理引擎）
│   │   ├── __init__.py
│   │   ├── models.py         # reasoning_traces / reasoning_algorithms 表
│   │   ├── instantiate.py    # 实例化（object/metric 展开）
│   │   ├── observe.py        # 观测方向推导（三口径）
│   │   ├── sign_propagation.py  # Phase 1 默认算法
│   │   ├── registry.py       # 算法注册表
│   │   ├── aggregator.py     # 归因排序聚合
│   │   ├── explain.py        # explain_level 输出
│   │   └── routes.py         # /v1/ecmc/reasoning/...
│   └── governance/           # 模型治理（issue/审批/change_log）
├── ontology/                 # 现有（Enterprise Semantic Layer）
└── planner/                  # 现有（消费推理结果）
```

---

# 七、API 草案

```
POST /v1/ecmc/reasoning/invoke   — 输入 {model_id, version, instance, reasoning_mode, explain_level}
                                   → Cause Ranking + Evidence Chain（§4.4.3）
GET  /v1/ecmc/reasoning/traces/{trace_id}  — 推理轨迹（可复现/审计）
POST /v1/ecmc/reasoning/validate  — Model Validation 回放（历史案例 → 命中率）
GET  /v1/ecmc/reasoning/algorithms — 算法注册列表
```

（传输层 HTTP 为参考，gRPC/内存/EventBus 由 Runtime 集成层决定。）

---

# 八、开放问题（下一轮评审）

1. **路径枚举复杂度**：DAG 反向枚举在最坏情况（稠密图）指数爆炸——需限制（如最大路径长度/节点数上限、剪枝策略），Phase 1 先限制深度 ≤ 3 跳 + 每节点最多 N 条路径
2. **快照 vs 实时表**：推理全量走快照（JSONB 拷贝）还是实时表 + 版本过滤？（快照安全但可能大；实时表省空间但需防修改）——当前选快照（安全优先），性能实测后定
3. **strength/confidence 校准**：Model Validation 回测如何回写校准值（仅 testing 阶段可校准，published 不可变——校准只影响新版本）
4. **观测并发取数**：多节点观测取数的并行策略与超时聚合（避免整体超时）
5. **图数据库评估时机**：Phase 3 多跳/超大规模评估的量化门槛（节点数/跳数/延迟）
