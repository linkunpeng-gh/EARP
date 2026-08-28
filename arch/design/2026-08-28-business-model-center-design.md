# EARP Business Model Center（业务模型中心）架构设计

- 日期: 2026-08-28
- 状态: draft（v0.1 草案经架构评审定稿，待团队评审）
- 定位: L2 前置设计——本文拍板 BMC 的模块边界、子模块划分与消费方集成契约；正式 L2 规范（business-model-center-specification.md）依本文改版清单另行落盘
- 关联规范: `arch/L2/02-reasoning/knowledge-center-specification.md`（v1.2 第四章 Ontology）、`arch/L2/02-reasoning/planner-specification.md`、`arch/L2/02-reasoning/decision-engine-specification.md`（v1.0）、`arch/L2/04-execution/workflow-specification.md`、`arch/L2/04-execution/scheduler-specification.md`、`arch/L2/05-governance/policy-center-specification.md`、`arch/design/2026-08-07-ontology-layer-design.md`
- 术语: BMC = Business Model Center；KB = Knowledge Center；FDE = Field Domain Engineer（现场领域工程师）

---

## 1. 背景与建设目标

### 1.1 问题定义

当前主流 Agent 平台解决 Prompt 管理、Workflow 编排、Tool 调用、LLM 调度，但企业核心业务场景（经营分析、生产调度、设备管理）本质依赖专家经验、业务规律、因果关系与决策逻辑——**AI 可以理解语言，但无法天然理解企业运行规律**。

现有 EARP 能力对"企业认知"的覆盖存在缺口：

| 问题 | 现有覆盖 | 缺口 |
|---|---|---|
| 是什么（事实与状态） | KB：RAG / 词典 / Ontology ABox | ✅ 已覆盖 |
| 为什么（因果规律） | ❌ | **本设计核心缺口** |
| 怎么办（决策知识） | Decision Engine 有执行时分支，但规则散落代码/配置，非资产 | **本设计核心缺口** |
| 怎么用（场景组装） | Chat App / Workflow 可组合，但无"专家预组装"的知识表达 | 次要缺口 |

### 1.2 建设目标

1. **建立企业业务规律模型**：将专家经验（因果链、决策规则、事件应对）沉淀为可治理、可版本化的模型资产
2. **支撑 Agent 深度业务推理**：使 Planner 从"意图 → 搜数据 → 生成回答"升级为"意图 → 匹配业务模型 → 因果遍历 → 数据获取 → 能力调用 → 形成结论"
3. **知识资产沉淀与跨行业复用**：隐性的专家经验转化为租户内知识资产，并支持行业模板包分发

### 1.3 设计由来（本草案 v0.1 → 本稿的关键决策）

本设计源自 BMC L2 草案 v0.1（2026-08-28 评审），评审中拍板六个结构性决策，详见 §2.4 决策记录。

---

## 2. 模块定位与边界

### 2.1 定位

> **BMC 是 EARP 的一级知识资产模块，负责将企业业务规律——因果关系、决策逻辑、场景组装方式——结构化为可治理、可版本化的模型资产，供 Planner、Decision Engine、Workflow 编排与 Agent 消费。BMC 是纯知识层，不执行任何动作。**

一句话分界：

> KB 描述**世界是什么样的**（事实与状态）；BMC 描述**世界为什么这样运行**（规律与对策）。

### 2.2 边界

**负责：**

- 因果模型：影响关系建模、归因推理知识（FDE 编辑、版本化）
- 决策知识：决策目标、业务约束、决策规则（含事件-任务映射规则）
- 场景模板：业务模型 × Capability 的组装声明（Phase 3+）
- 模型对象生命周期状态机（draft / testing / published / deprecated）
- 共用 TBox 因果侧关系类型的登记
- 行业模板包（Industry Pack）的导入/导出契约（Phase 2+ 落地工具）

**不负责：**

- ❌ 执行（Runtime / Orchestrator / Workflow 负责）
- ❌ 规划（Planner 负责，BMC 是其知识源之一）
- ❌ 执行时分支决策（Decision Engine 负责，BMC 供其规则）
- ❌ 权限与审批（Policy Center 负责）
- ❌ 审计（Audit Spec 负责）
- ❌ 结构性事实存储（KB 的 ABox 负责）
- ❌ 指标计算（数据中台负责，BMC/TBox 只定义指标语义——2026-08-07 分工决策）

### 2.3 总体架构位置

```
                        用户
                         │
                   Agent Runtime
                         │
                     Planner ──────────────┐
                         │                 │ 知识注入（模型匹配/规则注入/场景匹配）
 ┌────────────────┬──────┴───────┬─────────┴────────┐
 │  KB（是什么）   │  BMC（为什么/怎么办/怎么用）      │
 │  RAG / 词典    │  Causal / Decision / Scenario   │
 │  ABox 事实     │        │                        │
 │   ↕ 共治       │        ↓ 绑定                   │
 │  TBox（词汇 · ontology 域，双方共治）             │
 └────────────────┴────────┬───────────────────────┘
                            │
                     Capability Center
                            │
                企业业务系统与数据（ERP/MES/IoT/数据中台）
```

### 2.4 决策记录（评审拍板，六个结构性决策）

| # | 决策 | 结论 |
|---|---|---|
| D1 | Ontology 层归属 | **逻辑域归属 BMC、物理域不动**：架构上宣布 TBox/ABox 中"实体关系"认知归 BMC 名下；代码 `ontology/` 域不迁移（conversation/planner/connector 三处消费方零改动）。TBox 为 KB 与 BMC **共用语义基础**：结构性关系（ABox 事实用）与因果性关系（BMC 模型用）分属两个命名空间，同表登记。KB·ABox 管**结构性事实**（世界状态：实例级、时效性、confidence=可信度）；BMC 管**规律性知识**（世界规律：类型级、可版本化、可回测） |
| D2 | 因果模型建模形态 | **因果图是一等模型对象**，与 ABox 事实图完全分离。节点引用 TBox **实体类型**（类型级，非实例），推理时才绑定具体实例 |
| D3 | Decision Model 是否独立 | **独立存在，但作为知识资产而非引擎**：BMC 存决策知识（目标/约束/规则/优化模型绑定），版本化治理；执行归现有 Planner（规划时）+ Decision Engine（执行时），优化模型经 Capability 绑定调用 |
| D4 | Process Model 去留 | **砍独立子模块**：事件-任务映射规则（"给 Workflow 编排提供依据"）并入决策知识；流程执行复用 Workflow + Scheduler，BMC 不碰执行 |
| D5 | Scenario 定位 | **知识资产（模板/蓝图），非运行时对象**：场景 = 模型绑定 + Capability 集合 + 输入输出契约的声明式配置；实例化编译为 Workflow / Chat App 由既有执行域运行。**Phase 3+ 落地**（纯知识沉淀，价值依赖消费链路，等 Planner 场景匹配能力就绪） |
| D6 | Model Governance | **不自建治理中心**：模型对象生命周期状态机由 BMC 规范定义；权限/审批复用 Policy Center，变更记录复用 Audit Spec（与 TBox 治理 P6 原则同构） |

### 2.5 通用性原则（跨行业）

产品面向多行业通用落地。**模型结构的 schema 行业无关，行业语义只存在于 TBox 词汇表和模型内容中**：

```
P-G（通用性原则）:
1. CausalModel / DecisionKnowledge / Scenario 的结构不含行业硬编码，
   煤矿只是第一个租户的实例化内容
2. TBox 扩展走既有审批流（实体/关系类型是数据行不是代码），
   禁止任何行业语义硬编码进 BMC 结构
3. 行业落地优先使用 Industry Pack 导入 + 租户内定制，不从零开始
```

**Industry Pack（行业模板包，Phase 2+ 工具化，契约本次定义）：**

```
Industry Pack = 可导出/导入的知识资产集合
├── tbox_subset        — 行业推荐实体类型/关系类型（含 causal 侧）
├── causal_models[]    — 行业通用因果模型
├── decision_rules[]   — 行业通用决策规则/事件映射
└── scenario_templates[]

MUST: 导入到租户时全部落为 draft 状态（不直接发布，租户定制后自行审批发布）
MUST: 导入对象与租户内已有 TBox 类型按 entity_type_id 做冲突检测
SHOULD: 包内对象声明行业标签，与 applicability 字段联动
```

---

## 3. 子模块设计

BMC 四个子模块 + 一份生命周期契约：

```
BMC（一级模块 · 纯知识资产层，不执行）
├── 共用 TBox（物理留在 ontology 域，双方共治）
├── Causal Model        —— 因果模型对象（"为什么"）
├── Decision Knowledge  —— 目标/约束/规则/事件映射（"怎么办"）
└── Scenario Template   —— 场景模板（"怎么用"，Phase 3+）
治理：生命周期状态机 + 复用 Policy / Audit
```

### 3.1 CausalModel（因果模型）

#### 3.1.1 对象结构

```
CausalModel
├── model_id / tenant_id / data_domain_id
├── name / description              — "三号矿产量下降归因模型"
├── version                         — 语义化版本（v1.2.0）
├── status                          — draft / testing / published / deprecated
├── nodes[]                         — 节点列表
│     ├── node_id
│     ├── entity_type_ref           — 引用 TBox entity_type（object 或 metric kind，
│     │                               类型级而非实例级）
│     ├── entry_point: bool         — 推理入口标记（如"产量下降"），MUST ≥ 1
│     ├── data_requirement          — 数据需求声明（来源 connector / 时间窗）
│     └── capability_bindings[]     — 节点 ↔ Capability 绑定（capability_entity_map 模式）
├── edges[]                         — 有向影响边
│     ├── source_node_id / target_node_id
│     ├── relation_type_ref         — 引用 TBox 因果侧关系类型（influences / causes）
│     ├── strength                  — 影响强度 0-1（SHOULD）
│     ├── lag                       — 滞后周期（SHOULD，如 "7d"）
│     └── confidence                — 模型作者置信度（≠ ABox fact confidence，语义注明）
├── applicability                   — 适用范围声明（SHOULD：实例集合/行业标签）
└── owner / created_at / published_at
```

**设计说明（与草案 v0.1 的差异）：**

- 节点**不做 outcome/cause 分型**（多级因果链下分类法失效——中间节点既是果也是因），统一为**业务量**（entity_type 或 metric 引用），用 `entry_point` 标记推理入口
- 草案的"数据节点 / Capability 节点"改为**节点上的声明**（data_requirement、capability_binding），避免图里混入执行语义
- 边的 confidence 语义与 ABox fact 的 confidence 明确区分：前者是"模型作者对影响关系的置信"，后者是"事实的可信度"

#### 3.1.2 契约

```
MUST: 节点只引用 TBox 已注册的实体类型/metric 类型；未注册先走 TBox 审批
MUST: 发布状态才能被 Planner 检索；draft/testing 对消费方不可见
MUST: 因果边登记为 TBox causal 侧关系类型（与结构性关系命名空间区分）
MUST: 实例化时沿 KB 结构关系（belongs_to / located_in 等）将类型级模型
      展开到具体实体实例
MUST: 模型节点跨 Data Domain 引用时，消费权限取引用对象的
      最高 data_classification（双层权限模型对齐）
SHOULD: strength / lag 在 testing 阶段可由回测数据校准
SHOULD: applicability 声明适用范围（实例集合 / 行业标签）
```

#### 3.1.3 因果推理流程（消费方式）

案例："为什么 3 号矿产量下降？"

```
Planner 定位 entry_point 节点（产量下降）→ 匹配已发布 CausalModel
  → 沿因果边反向遍历，定位候选原因链（设备/地质/调度）
  → 因果模板实例化：类型节点绑定具体实体
    （"3 号矿的设备"——沿 KB ABox 结构关系展开）
  → 按节点 data_requirement 生成数据获取 Step → 经 capability_binding 绑定 Capability
  → 汇总证据，按边 strength 排序 → 输出原因排序报告
```

### 3.2 DecisionKnowledge（决策知识）

三类知识对象，统一状态机与治理：

```
DecisionKnowledge
├── DecisionObjective    — 决策目标（提升产量/降低成本）
│     ├── metric_ref + 方向 + 阈值
├── ConstraintSet        — 业务约束（安全规则/人员/库存/设备能力）
│     └── 约束引用 TBox 类型
├── DecisionRule         — IF-THEN 决策规则
│     ├── condition
│     │     ├── source: metric_ref | capability_call
│     │     │       （capability_call：条件数据来自 Capability 调用结果，
│     │     │          含输出字段映射——如"设备健康评分"来自设备诊断能力）
│     │     └── expression — 条件表达式（引用 metric / entity 属性）
│     ├── action: advice | task_generation | workflow_trigger
│     ├── task_template — action=task_generation 时的任务模板
│     │                   （给 Workflow 编排提供依据）
│     ├── priority / confidence
│     └── conflict_resolution — SHOULD，同优先级冲突时叠加 Policy 裁决
└── EventTaskMapping     — 事件/条件-任务映射（给 Workflow 编排提供依据）
      ├── trigger_kind: "event" | "condition"（对齐 Scheduler 两种 Trigger）
      ├── event_type / condition_expr
      │     （event_type 引用 EventBus 事件类型，如 earp.alarm.critical；
      │       condition_expr 如"库存 < 安全库存"——条件持续满足触发）
      └── workflow_ref  — 触发的 Workflow 定义
```

#### 3.2.1 契约

```
MUST: 规则条件中的指标/实体引用 TBox 类型
MUST: action 为 workflow_trigger 时校验 Workflow 存在且已发布
MUST: 与 Policy Center 分工——BMC 规则是业务性"怎么办"，
      Policy 是治理性"允不允许"，两者叠加生效、互不替代
MUST: 跨 Data Domain 引用时权限取最高 data_classification
SHOULD: 规则支持组合（AND / OR / NOT，与 Decision Engine §3.1 一致）
```

#### 3.2.2 消费路径（三条）

| 消费方 | 用法 |
|---|---|
| Planner | DecisionObjective + ConstraintSet 注入规划上下文，用于 Goal 分解与 Plan 生成 |
| Decision Engine | 执行时分支选择从已发布 DecisionRule 读取（规则资产化，替代散落代码/配置）；condition.source = capability_call 时先执行该 Capability 再评估 |
| Scheduler / Workflow | EventTaskMapping 发布后注册为 event / condition trigger，执行走 Workflow |

### 3.3 ScenarioTemplate（场景模板，Phase 3+）

```
ScenarioTemplate
├── name / description / data_domain_id / version / status
├── model_bindings[]       — 引用已发布 CausalModel / DecisionKnowledge
├── capability_set[]       — 所需 Capability 清单
├── input_contract         — 触发该场景的意图描述（供 Planner 语义匹配）
├── output_contract        — 输出物契约（原因分析报告/优化建议）
└── compilation_target     — Workflow 或 Chat App（实例化编译目标，L3 细化）
```

场景是**预组装的知识包**（专家把"分析产量下降需要哪些模型、哪些能力、输出什么"沉淀下来），实例化走既有 Workflow / Chatflow 编译执行。Phase 3+ 落地，本次仅定契约骨架。

### 3.4 生命周期契约（治理复用，D6）

```
状态机: draft → testing → published → deprecated
        （testing：回测/试运行；published：对消费方可见）

MUST: 只有 published 状态的模型对象可被消费方检索
MUST: 发布走 Policy Center 审批流
MUST: 变更记录（含版本 diff）走 Audit Spec
MUST: 版本语义化（major.minor.patch），消费方引用需携带版本
```

---

## 4. 消费方集成契约

### 4.1 Planner ← BMC（最重集成点）

```
触发: Goal Generation / Domain Routing 阶段
调用: 模型检索（entry_point 语义匹配 + applicability 过滤）
返回: 已发布 CausalModel 候选集（含节点/边摘要 + 版本号）

后续:
  → 因果归因类意图: 沿因果边反向遍历 → 按节点 data_requirement
    生成数据获取 Step → 经 capability_binding 绑定 Capability → 纳入 Plan
  → 决策类意图: 注入 DecisionObjective + ConstraintSet → Goal 分解
  → （Phase 3+）场景类意图: 匹配 ScenarioTemplate → 实例化为 Workflow
```

```
MUST: 只检索 published 状态
MUST: 返回模型版本号（Planner 在 Execution Trace 中记录，保证可复现）
```

### 4.2 Decision Engine ← BMC

```
触发: 执行时分支 Step
调用: 按 data_domain + entity_type 检索已发布 DecisionRule
行为: Rule → LLM → ML 优先级不变，BMC 是规则的新来源之一；
      condition.source = capability_call 时先执行 Capability 再评估
```

### 4.3 与 KB 的双向关系（D1 落地）

```
共治 TBox: ontology 域物理不动，KB 与 BMC 都是消费方；
          causal 侧关系类型登记入 TBox 词汇表（命名空间区分）

KB → BMC: 实例化时提供实体实例（ABox 沿 belongs_to / located_in 展开）

BMC → KB: 因果推理产生的"假设性事实"（如"疑似轴承老化"）
          SHOULD 回写为低 confidence（< 1.0）候选事实，
          经人工审核后转正——BMC 反哺 KB 的知识闭环
```

---

## 5. L2 规范改版清单

| # | 文档 | 改动 | 优先级 |
|---|---|---|---|
| 1 | 新建 `arch/L2/02-reasoning/business-model-center-specification.md` | BMC 主规范（本文设计的契约化落盘） | P0 |
| 2 | `knowledge-center-specification.md` v1.2 → v1.3 | 第四章 Ontology 标注"TBox 与 BMC 共治"；ABox 增补"BMC 假设性事实回写通道" | P0 |
| 3 | `planner-specification.md` | 新增"BMC 知识源"章节：模型检索、因果遍历、决策知识注入 | P0 |
| 4 | `decision-engine-specification.md` v1.0 → v1.1 | §3.1 增补"BMC DecisionRule 为规则来源之一"；capability_call 条件源 | P1 |
| 5 | `concept-model-v2.x` | 新增 CausalModel / DecisionKnowledge / ScenarioTemplate 概念对象 | P1 |
| 6 | `scheduler-specification.md` | EventTaskMapping 的 trigger_kind 对齐说明 | P2 |
| 7 | `workflow-specification.md` | task_template / ScenarioTemplate 实例化的编排依据说明 | P2 |

代码侧（L3 前瞻，不入本文）：新增 `earp_server/bmc/` 域；import-linter 新增契约；`ontology/` 域不迁移。

---

## 6. 实施路线建议

```
Phase 1  CausalModel + 决策知识核心（DecisionRule / EventTaskMapping）
         + 生命周期状态机 + Planner 因果归因链路（最小闭环：
         "为什么产量下降"端到端跑通）
Phase 2  DecisionObjective / ConstraintSet 注入 Planner；
         BMC → KB 假设性事实回写闭环；Industry Pack 工具化
Phase 3  ScenarioTemplate + Planner 场景匹配 + 实例化编译
```

排序依据：因果归因是 BMC 净增值最高、可独立验证的链路，先跑通；决策知识先落规则与事件映射（对 Workflow 编排的依据价值立即兑现）；场景模板价值依赖消费链路，最后落地。

---

## 7. 后续 L3 设计方向

1. **模型元数据物理模型**：BMC 各对象的表结构（PG 承载，沿用"基础设施最小化"原则，图数据库留待多跳推理需要时评估）
2. **因果图引擎**：图存储（递归 CTE vs 图数据库）、图查询、因果遍历算法、实例化展开规则
3. **Planner 集成实现**：entry_point 语义匹配（复用 Semantic Index）、模型选择、因果遍历 → Plan 生成的映射
4. **FDE 建模工具**：拖拽编辑器、节点配置、发布流程（对接 Policy 审批）
5. **回测机制**：testing 阶段的 strength/lag 校准、DecisionRule 回测
6. **Industry Pack 格式**：导出/导入 schema、冲突检测算法

---

## 8. 场景验证记录（设计修订依据）

设计过程中以四个差异化场景代入验证，发现并修复六个缺口：

| 场景 | 发现的缺口 | 修订 |
|---|---|---|
| A 煤矿产量下降归因 | 节点 outcome/cause 分型在多级链失效；类型模型绑实例缺跨层级规则；缺适用范围声明 | 节点统一为业务量 + entry_point 标记；MUST 沿 KB 结构关系实例化展开；增加 applicability |
| B 预测性检修 | 条件数据源可能是 Capability 输出而非预计算指标；规则冲突消解未定义 | condition.source 支持 capability_call；增加 conflict_resolution |
| C 供应链缺料预警 | 条件持续满足触发（非事件触发）漏建模 | EventTaskMapping 增加 trigger_kind: event \| condition |
| D 跨域经营分析 | 模型跨 Data Domain 引用指标时权限未定义 | MUST 消费权限取引用对象最高 data_classification |
