# EARP Enterprise Cognitive Model Center（企业认知模型中心）架构设计

- 日期: 2026-08-28
- 状态: v0.17 — 架构修订：新增 §4.4 ECMC Cognitive Service Contract（认知服务契约：Model Discovery / Reasoning / Capability Dependency / Feedback）（见 §24）
- 定位: L2 前置设计——本文拍板 ECMC 的模块边界、子模块划分与消费方集成契约；正式 L2 规范（enterprise-cognitive-model-center-specification.md）依本文改版清单另行落盘
- 关联规范: `arch/L2/02-reasoning/knowledge-center-specification.md`（v1.2 第四章 Ontology）、`arch/L2/02-reasoning/planner-specification.md`、`arch/L2/02-reasoning/decision-engine-specification.md`（v1.0）、`arch/L2/04-execution/workflow-specification.md`、`arch/L2/04-execution/scheduler-specification.md`、`arch/L2/05-governance/policy-center-specification.md`、`arch/design/2026-08-07-ontology-layer-design.md`
- 术语: ECMC = Enterprise Cognitive Model Center（企业认知模型中心，v0.12 更名，原 BMC = Business Model Center）
  KB = Knowledge Center；FDE = Field Domain Engineer（现场领域工程师）

---

## 1. 背景与建设目标

### 1.1 问题定义

当前主流 Agent 平台解决 Prompt 管理、Workflow 编排、Tool 调用、LLM 调度，但企业核心业务场景（经营分析、生产调度、设备管理）本质依赖专家经验、业务规律、因果关系与决策逻辑——**AI 可以理解语言，但无法天然理解企业运行规律**。

现有 EARP 能力对"企业认知"的覆盖存在缺口：

| 问题 | 现有覆盖 | 缺口 |
|---|---|---|
| 是什么（事实与状态） | KB：RAG / 词典 / ABox 事实（Enterprise Semantic Layer 的 KB 侧） | ✅ 已覆盖 |
| 为什么（因果规律） | ❌ | **本设计核心缺口** |
| 怎么办（决策知识） | Decision Engine 有执行时分支，但规则散落代码/配置，非资产 | **本设计核心缺口** |
| 怎么用（场景组装） | Chat App / Workflow 可组合，但无"专家方法论模板"的知识表达 | 次要缺口 |

### 1.2 建设目标

1. **建立企业业务规律模型**：将专家经验（因果链、决策规则、事件应对）沉淀为可治理、可版本化的模型资产
2. **支撑 Agent 深度业务推理**：使 Planner 从"意图 → 搜数据 → 生成回答"升级为"意图 → 匹配业务模型 → 因果推理 → 数据获取 → 能力调用 → 形成结论"
3. **知识资产沉淀与跨行业复用**：隐性的专家经验转化为租户内知识资产，并支持行业模板包分发

### 1.3 设计由来（本草案 v0.1 → 本稿的关键决策）

本设计源自 ECMC L2 草案 v0.1（2026-08-28 评审），评审中拍板六个结构性决策，详见 §2.4 决策记录。

---

## 2. 模块定位与边界

### 2.1 定位

> **ECMC 是 EARP 的一级知识资产模块，负责将企业业务规律——因果关系、决策逻辑、场景组装方式——结构化为可治理、可版本化的模型资产，供 Planner、Decision Engine、Workflow 编排与 Agent 消费。ECMC 是纯知识层，不执行任何动作。**

一句话分界：

> KB 描述**世界是什么样的**（事实与状态）；ECMC 描述**世界为什么这样运行**（规律与对策）。

### 2.2 边界

**负责：**

- 因果模型：影响关系建模、归因推理知识（FDE 编辑、版本化）
- 决策知识：决策目标、业务约束、决策规则（含事件-任务映射规则）
- 专家业务方案模板（Scenario Template）：业务模型 × Capability 的方法论组装声明（Phase 3+）
- 模型对象生命周期状态机（draft / testing / published / deprecated）
- Enterprise Semantic Layer 因果侧关系类型的登记（共建，非拥有）
- 行业模板包（Industry Pack）的导入/导出契约（Phase 2+ 落地工具）

**不负责：**

- ❌ 执行（Runtime / Orchestrator / Workflow 负责）
- ❌ 规划（Planner 负责，ECMC 是其知识源之一）
- ❌ 执行时分支决策（Decision Engine 负责，ECMC 供其规则）
- ❌ 权限与审批（Policy Center 负责）
- ❌ 审计（Audit Spec 负责）
- ❌ 结构性事实存储（KB 的 ABox 负责）
- ❌ 指标计算（数据中台负责，ECMC/TBox 只定义指标语义——2026-08-07 分工决策）

### 2.3 总体架构位置

```
                        用户
                         │
                   Agent Runtime
                         │
                     Planner ──────────────┐
                         │                 │ 知识注入（模型匹配/规则注入/场景匹配）
 ┌────────────────┬──────┴───────┬─────────┴────────┐
 │  KB（是什么）   │  ECMC（为什么/怎么办/怎么用）      │
 │  RAG / 词典    │  Causal / Decision / Scenario   │
 │  ABox 事实     │        │                        │
 └────────────────┴────────┬───────────────────────┘
             Enterprise Semantic Layer（企业语义层）
             TBox 词汇 · 公共语义基础设施 · KB/ECMC 共建
             （物理在 ontology 域，双方消费、无人拥有）
 ┌──────────────────────────────────────────────────┐
 │  Capability Center / 企业业务系统与数据（ERP/MES/IoT） │
 └──────────────────────────────────────────────────┘
```

### 2.4 决策记录（评审拍板，六个结构性决策）

| # | 决策 | 结论 |
|---|---|---|
| D1 | Ontology 层归属 | **Enterprise Semantic Layer（企业语义层）由 KB/ECMC 共建，双方消费、无人拥有**（v0.11 修正，原“逻辑域归属 ECMC”易误解）：Ontology 不是业务模型，而是企业世界的语言体系（设备/工作面/产线/订单/客户…），同时服务 RAG、数据理解、因果分析、Planner——是 EARP 的公共语义基础设施。代码 `ontology/` 域不迁移（conversation/planner/connector 三处消费方零改动）。语义层内部：结构性关系（ABox 事实用）与因果性关系（ECMC 模型用）分属两个命名空间，同表登记。KB·ABox 管**结构性事实**（世界状态：实例级、时效性、confidence=可信度）；ECMC 管**规律性知识**（世界规律：类型级、可版本化、可回测），两者都是语义层的消费方 |
| D2 | 因果模型建模形态 | **因果图是一等模型对象**，与 ABox 事实图完全分离。节点引用 TBox **实体类型**（类型级，非实例），推理时才绑定具体实例。**推理算法不绑定**（v0.14）：L2 只定义 Causal Reasoning Contract（输入模型+观测+证据 → 输出原因排序+证据链），默认符号传播算法仅作 Phase 1 参考实现，贝叶斯/LLM/时序等算法 L3 选型 |
| D3 | Decision Model 是否独立 | **独立存在，但作为知识资产而非引擎**：ECMC 存决策知识（目标/约束/规则/优化模型绑定），版本化治理；执行归现有 Planner（规划时）+ Decision Engine（执行时），优化模型经 Capability 绑定调用 |
| D4 | Process Model 去留 | **砍独立子模块**：事件-任务映射规则（"给 Workflow 编排提供依据"）并入决策知识；流程执行复用 Workflow + Scheduler，ECMC 不碰执行 |
| D5 | Scenario 定位 | **专家业务方案模板（方法论模板），非运行时对象、非业务应用**（v0.13 措辞细化）：Scenario = 专家对某类问题的**方法论沉淀**（模型绑定 + Capability 集合 + 分析步骤 + 输入输出契约的声明式配置）——如"生产异常分析方法论模板"而非"生产异常分析 Agent"；模板实例化编译为 Workflow / Chat App 由既有执行域运行，**实例化后的 Agent/应用是执行产物，不属于 ECMC**。**Phase 3+ 落地**（纯知识沉淀，价值依赖消费链路，等 Planner 模板匹配能力就绪） |
| D6 | Model Governance | **ECMC 内一等治理子模块，不建平台级独立治理中心**（v0.16 演进）：模型生命周期状态机、问题管理（issue）、修改/版本/发布由 ECMC 的 Model Governance 子模块（§3.4）统一负责；审批/审计/绩效埋点仍复用 Policy Center / Audit Spec / Observation Spec（横切层不重复建设，与 TBox 治理 P6 原则同构） |

### 2.5 通用性原则（跨行业）

产品面向多行业通用落地。**模型结构的 schema 行业无关，行业语义只存在于 TBox 词汇表和模型内容中**：

```
P-G（通用性原则）:
1. CausalModel / DecisionKnowledge / Scenario 的结构不含行业硬编码，
   煤矿只是第一个租户的实例化内容
2. TBox 扩展走既有审批流（实体/关系类型是数据行不是代码），
   禁止任何行业语义硬编码进 ECMC 结构
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

ECMC 下**四个并列二级模块**（三个资产模块 + 一个治理模块），建立在 Enterprise Semantic Layer 之上：

```
Enterprise Semantic Layer（企业语义层 · 公共语义基础设施）
  TBox 词汇（实体类型/关系类型）· KB 与 ECMC 共建 · 双方消费、无人拥有
        ▲            ▲
        │            │
   ┌────┴────┐  ┌────┴──────────────────────────────┐
   │  KB     │  │  ECMC                              │
   │ ABox 事实│  │  ├── Causal Model（因果模型 · "为什么"）
   │ RAG/词典 │  │  ├── Decision Knowledge（决策知识 · "怎么办"）
   └─────────┘  │  ├── Scenario Template（专家方案模板 · "怎么用"，Phase 3+）
               │  └── Model Governance（模型治理 · 问题/修改/版本/发布）
               └──────────────────────────────────────┘

治理说明：Model Governance 为 ECMC 内一等子模块（v0.16）；
审批/审计/绩效埋点复用 Policy Center / Audit Spec / Observation Spec（横切层），
不重复建设
```

### 3.1 CausalModel（因果模型）

#### 3.1.1 对象结构

```
CausalModel
├── model_id / tenant_id / data_domain_id
├── name / description              — "三号矿产量下降归因模型"
├── version                         — 语义化版本（v1.2.0）
├── status                          — draft / testing / published / deprecated
├── dependency_ok                   — 依赖完整标志（published 上的正交布尔，
│                                     详见 §3.4）
├── nodes[]                         — 节点列表
│     ├── node_id
│     ├── entity_type_ref           — 引用 TBox entity_type（object 或 metric kind，
│     │                               类型级而非实例级）
│     ├── entry_point               — 推理入口声明（MUST ≥ 1）
│     │     ├── direction: "up" | "down"   — 观测方向（"下降"/"上升"），
│     │     │                               区分"为什么产量下降"与"为什么产量上升"
│     │     └── description                 — 入口语义描述（供 Planner 匹配）
│     ├── data_requirement          — 数据需求声明（结构见 §3.1.4）
│     ├── observation_window        — object 节点当前观测窗口（必填，
│     │    §3.1.2 口径 1/2/3 的当前窗口；离散状态取窗口首尾状态，
│     │    聚合计数取窗口聚合值）
│     ├── instance_data_binding     — object 节点实例取数输入契约
│     │    （object 节点必填，§3.1.4：instance_source / data_source /
│     │     instance_key_field / instance_observation /
│     │     aggregation_input）
│     ├── aggregation               — object 节点用量声明（§3.1.4）：
│     │    ├── mode: "per_instance" \| "aggregate"（发布时校验，
│     │    │        未声明按 per_instance 补齐入快照）
│     │    └── operator / predicate / weight_ref（mode=aggregate 时）
│     └── capability_bindings[]     — 节点 ↔ Capability 绑定（capability_entity_map 模式）
├── edges[]                         — 有向影响边
│     ├── source_node_id / target_node_id
│     ├── relation_type_ref         — 引用 TBox causal 命名空间关系类型（§3.1.5）
│     ├── effect: "+" | "-"        — 影响符号：源↑导致目标↑为 +，反之 -（MUST）
│     ├── strength                  — 影响强度 0-1（SHOULD）
│     ├── lag                       — 滞后周期（SHOULD，如 "7d"）
│     └── confidence                — 模型作者置信度（≠ ABox fact confidence，语义注明）
├── applicability                   — 适用范围声明（发布时 MUST，见 §3.1.2）
└── owner / created_at / published_at
```

**设计说明（与草案 v0.1 的差异）：**

- 节点**不做 outcome/cause 分型**（多级因果链下分类法失效——中间节点既是果也是因），统一为**业务量**（entity_type 或 metric 引用），用 `entry_point`（含观测方向）标记推理入口
- 草案的"数据节点 / Capability 节点"改为**节点上的声明**（data_requirement、capability_binding），避免图里混入执行语义
- 边的 confidence 语义与 ABox fact 的 confidence 明确区分：前者是"模型作者对影响关系的置信"，后者是"事实的可信度"

#### 3.1.2 契约

**Causal Reasoning Contract（因果推理契约，v0.14 重构：L2 锁契约不锁算法）**

ECMC 不将因果推理算法绑定为唯一实现——企业因果推理未来可能有规则推理、
图搜索、贝叶斯网络、LLM reasoning、时序模型等多种算法。L2 只定义**契约**
（输入/输出/约束），**算法选型归 L3**：

```
输入：
  CausalModel（已发布，实例化后的类型/实例绑定）
  Observation（节点观测：数值序列 / 离散状态 / 聚合值，见 §3.1.4）
  Evidence（外部证据：历史事实、事件记录、回测数据——SHOULD）
输出：
  Cause Ranking（原因排序：候选原因 + 方向 + 排序 + 置信度）
  Evidence Chain（证据链：从原因到入口的传导路径 + 每步的观测证据与
                  数据来源，保证可解释）
约束：
  MUST: 输出必须可解释——Cause Ranking 的每一项须附 Evidence Chain
  MUST: 可复现——同一输入（模型版本 + 观测 + 证据）同一输出
  MUST: 算法可替换——契约不依赖任何具体算法；算法实现经注册接入，
        允许按模型/场景选择不同算法（Phase 1 默认实现见下）
  MUST: 输入不变性——算法只消费契约输入，不产生副作用、不修改模型
```

**Phase 1 参考实现（默认算法，可替换——以下公式不约束契约，仅约束默认实现）：**

当前默认算法 = 符号传播 + 路径排序（下述公式已经九轮评审打磨，作为
Phase 1 可执行基线；未来引入贝叶斯/LLM 等算法时，满足上述契约即可替换）：
```
MUST: 节点只引用 TBox 已注册的实体类型/metric 类型；未注册先走 TBox 审批
MUST: 发布状态才能被 Planner 检索；draft/testing 对消费方不可见
MUST: 因果边登记为 TBox causal 命名空间关系类型（schema 扩展见 §3.1.5）
MUST: 图为有向无环图（DAG）；编译期做环路检测，含环模型不可发布
      （DAG 约束属模型结构契约，对任何算法成立）
MUST: 边带 effect 符号（+/-）；方向约定：effect 表示源节点取值上升时
      对目标节点的影响方向（+ 同向、- 反向）
      （effect 符号属模型语义契约，任何算法都需消费）

默认实现的原因筛选公式（参考实现，可替换）：
      设推理目标方向 d = entry_point.direction（up=+1 / down=-1），
      路径 p = 原因节点 → … → entry_point 的边序列，
      路径符号积 S(p) = ∏ edges.effect（±1 之积），
      则原因节点对目标的解释方向 d'(p) = d × S(p)：
        - d'(p) = +1：原因节点取值上升可解释目标的 d 方向变化
        - d'(p) = -1：原因节点取值下降才解释目标的 d 方向变化
      全部路径保留进入候选集（反向原因链——如"设备老化↑ →
      健康度↓（effect=-）→ 产量↓"——经公式换算后合法入选），
      候选原因的报告方向按 d'(p) 标注。中间节点不单独输出，
      仅作为传导路径展示
MUST(默认实现): 归因排序分值（Phase 1 默认算法；v0.8 修正 obs_match
      数学/语义）：
      score(path) = |∏ strength| × ∏ confidence × obs_match(path)

      节点 i 的预期方向 e(i) = d × S(从 i 到 entry_point 的子路径符号积)
      ——注意不是整条路径的 d'(p)：以 老化(A)→健康度(B)→产量(C)、
      A→B effect=-、B→C effect=+ 为例，入口 C 下降（d=-1）时：
        原因 A 的 e(A) = d × S(A→C 全路径) = -1 × (-1×+1) = +1
          （老化上升可解释产量下降）
        中间 B 的 e(B) = d × S(B→C 子路径) = -1 × (+1) = -1
          （健康度下降才解释产量下降）
      两者方向相反是正确语义，obs_match 必须用各自的 e(i)，
      不能复用整条路径的 d'(p)

      obs_match(path) 定义（v0.10 显式分派，修正 -1 的几何均值
      实数域无定义问题）：
        若存在任一 m(i) = -1 → obs_match = 0（反向一票否决，
        路径降权垫底）
        否则 → obs_match = (∏ m(i))^(1/n)，n = 路径节点数
        （此时 m(i) ∈ {0.5, 1}，obs_match ∈ [0.5, 1]，实数域恒有定义；
        几何均值消除 0.5^n 长路径衰减）
      节点观测匹配度 m(i)，定义：
        观测方向与 e(i) 一致 → m(i) = +1
        相反                  → m(i) = -1（一票否决）
        无观测数据（取数失败/未声明） → m(i) = 1（中性乘数，
          乘法中 0 会整路径归零，不是中性——见 v0.8 修正）
        观测方向为 unchanged（不变） → m(i) = 0.5（弱支持，
          不解释目标变化但也不反驳）
        观测方向为 unknown（未知）  → m(i) = 1（与无数据同中性，
          不奖不罚）

      效果：
        - 数据全部支持 → obs_match=1 → score = 纯先验分
        - 数据反向（任一 -1） → obs_match=0 → 该路径降权/垫底
        - 无数据/unknown → m(i)=1 → 纯先验排序，不丢候选
        - 不变(unchanged) → 0.5 弱支持，路径长度不再主导（v0.9）
      obs_match 由节点观测值经 §3.1.4 的 instance_data_binding /
      data_requirement 计算（观测方向与 e(i) 比较）；
      节点聚合取其全部入径的最高分路径；同一原因节点正负路径
      并存时，分别列出两条解释并标注"方向冲突待数据裁决"

MUST(默认实现): 观测方向推导口径（P2-3，Phase 1 默认算法，v0.10 补当前窗口）：
      按节点观测类型分三套口径，object 节点统一声明
      observation_window（当前窗口，见 §3.1.4）：
      1. 数值时间序列（metric 节点 / 数值观测）：data_requirement
         observation_window 首尾点比较——首尾差 > 阈值 → up；
         < -阈值 → down；|差| ≤ 阈值 → unchanged；取数失败/无值
         → unknown。阈值在模型发布时声明：必须显式声明绝对阈值
         或相对阈值（相对阈值=窗口均值百分比），默认值仅允许
         正值指标；零均值/负均值指标禁用相对阈值默认值
         （v0.9 修订，故障计数等 0 均值指标用绝对阈值）
      2. 离散状态（per_instance 观测 status 类）：按 observation_window
         首尾状态判定跃迁——非目标态 → 目标态（如 status:
         running → failed）为 up（指向目标状态的跃迁）；目标态 →
         非目标态为 down；首尾同态为 unchanged。目标状态集合在
         发布时声明
      3. 聚合计数/比率（aggregate count/ratio）：observation_window
         聚合值 vs 前一等长基线窗口比较（同口径 1 的阈值规则），
         基线窗口 = aggregation.baseline_window（缺省 = 当前窗口
         前一等长窗口）
      以上口径均保证 Phase 1 可复现；L3 可扩展趋势拟合/显著性
MUST(默认实现): obs_match 语义（P2-5）：几何均值 + 反向一票否决——任一节点
      反向数据足以推翻该路径解释（obs_match=0）；其余情况几何
      均值消除长路径衰减。若需进一步缓解长路径单节点主导，L3
      提供按节点 confidence 加权的变体（obs_match_w = Σ m(i)·conf(i)
      / Σ conf(i)），Phase 1 保持几何均值 + 一票否决
MUST(默认实现): 发布时强制补齐边字段——每条边必须声明 strength 与 confidence
      （默认值：strength=0.5、confidence=0.5，显式声明者优先），
      保证默认排序公式对 published 模型恒有定义
      （strength/confidence 字段本身属模型语义契约，任何算法都需要；
      但“默认补齐值”仅约束默认实现，未来算法可自定义缺失处理）
MUST: 实例化分两类节点：object 节点沿 KB 结构关系（belongs_to /
      located_in 等）展开到具体实体实例；metric 节点无 ABox 实例，
      按 §3.1.4 的 instance_binding 绑定到实体实例 × 时间窗
MUST: 模型可见性 = max(模型所属 Data Domain 的 data_classification,
      全部引用对象（实体类型/metric）的 data_classification)；
      检索/消费按双层权限模型（data_domain_access 角色域 + 行级可见性）执行
MUST: 发布时校验作者对全部引用对象有读取权
SHOULD: strength / lag 在 testing 阶段可由回测数据校准
MUST: applicability 发布时必填（实例集合 / 行业标签），
      Planner 检索依赖该字段过滤
```

**多模型命中同一 entry_point 的消歧（MUST）：** Planner 检索返回多个模型时，按 applicability 匹配度 → 版本新旧排序，取 Top-N 注入；语义上仍冲突时（如两个模型归因方向相反），全部返回并在结果中标注冲突，交由 LLM 分支或用户裁决。

#### 3.1.3 因果推理流程（消费方式）

案例："为什么 3 号矿产量下降？"（流程按 Causal Reasoning Contract 调用，
具体算法由注册的推理实现决定，Phase 1 用默认符号传播算法）：

```
Planner 定位 entry_point 节点（产量下降，direction=down）
  → 匹配已发布 CausalModel
  → 因果模板实例化：object 节点沿 KB ABox 结构关系展开
    （"3 号矿的设备"）；metric 节点按 instance_binding 绑定
    （产量 × 3 号矿 × 近 30 天）
  → 按节点 data_requirement 生成数据获取 Step → 经 capability_binding 绑定 Capability
  → 组装契约输入（CausalModel + Observation + Evidence）
  → 调用因果推理实现（Phase 1 默认：沿因果边反向遍历，按
    筛选公式 d'(p) = d × S(p) 换算解释方向（反向原因链合法入选），
    按 score(path) = |∏ strength| × ∏ confidence × obs_match(path)
    排序——见 §3.1.2 参考实现）
    → 输出契约结果：Cause Ranking（原因排序，候选携带方向与置信度）
      + Evidence Chain（证据链，每步观测证据与数据来源）
```

#### 3.1.4 data_requirement 结构（修订 P1-7）

自由文本声明改为结构化契约，使 Planner 能直接生成可执行 Step：

```
data_requirement
├── source_kind: "connector" | "capability"
├── source_ref              — connector_id 或 capability_id（MUST 已注册且 active）
├── metric_binding          — metric 节点必填
│     ├── metric_ref        — TBox metric 类型
│     ├── instance_binding  — 绑定到哪个实体实例（受限表达式，见下）
│     ├── time_window       — 时间窗（如 P30D）与粒度（如 daily）
│     └── aggregation / unit — 聚合方式（sum/avg/max…）与单位
└── output_mapping          — 输出字段 → 节点取值的映射
                              （Capability 返回 schema 中哪个字段作为节点观测值）
```


```
instance_binding 受限表达式（L2 契约，语法固定，禁止任意代码）：
  单跳（种子解析）：
    $target_entity                            — 推理目标实体
    $target_entity.<relation>.<dir>           — 沿单一结构关系单跳展开
    $target_entity.<relation>.<dir>.<entity_type>
                                              — 展开后按实体类型过滤
  双跳（链式追加第二个跳段，MUST 显式写全方向与类型）：
    $target_entity.<r1>.<dir1>.<t1>.<r2>.<dir2>.<t2>
    例：$target_entity.located_in.in.equipment.belongs_to.out.production_line
        （矿 → 矿内设备 → 设备所属产线；belongs_to 的 target 为
        production_line/equipment，非 plant——示例与 TBox 事实对齐）
  （说明：默认方向 = 出边 .out；entity_type 过滤的是展开结果中
    非目标一侧的实体类型。例：从"3 号矿"取设备 =
    $target_entity.located_in.in.equipment（矿是 located_in 目标）
    单跳为种子解析；多跳展开一律在模型内显式声明为链式表达式
    （最多 2 跳），禁止依赖引擎"自动继续遍历"——发布校验时
    展开深度超过 2 跳直接拒绝发布（修订 P1-3/P2-5，收敛为
    可实现的静态校验）

    约束：
    MUST: relation 仅允许 TBox structural namespace 中已注册关系
    MUST: 双跳的两个跳段都必须显式声明方向与类型过滤
    MUST: 展开结果按双层权限模型过滤（展开越权实体视为无权限，
          不报错、不返回）

object 节点实例化与聚合契约（修订 P1-1，Phase 1 可执行）：
  结构关系（belongs_to / located_in…）多为 N:1 / N:M，展开结果
  是实例集合。节点必须显式声明用量（node.aggregation），且
  必须有**实例数据输入契约**（object 节点级 instance_data_binding，
  见下）——聚合契约解决输出侧归并，instance_data_binding 解决
  输入侧取数：

  aggregation
  ├── mode: "per_instance" | "aggregate"
  ├── operator  — mode=aggregate 时：count | ratio | max | min | avg
  │               （如"设备故障节点"= 故障设备计数 count；
  │                "设备健康度" = 最差值 min）
  ├── predicate — operator ∈ {count, ratio} 时的实例级谓词
  │               （如 status == 'failed'；阈值判断 metric >= 90——
  │                引用 TBox attribute / metric_ref，非自由文本）
  ├── weight_ref — mode=aggregate 时可选权重来源（实体属性 / metric，
  │               如设备对产出的重要度得分；缺省 = 等权）
  ├── baseline_window — 方向判定的基线窗口（唯一权威字段，
  │               aggregate 模式：当前窗口 vs 前一等长窗口，
  │               见 §3.1.2 口径 3；instance_data_binding 中
  │               不再重复声明，仅引用本字段）
  └── per_instance 模式：每个实例单独成径参与归因，
       各实例路径独立计算 score，输出时按实例展示归因结果；
       回答入口级问题时按 score 上卷（top_k 实例 + 汇总）

  MUST: 每个 object 节点发布时校验 aggregation.mode，未声明则按
        per_instance 补齐并落入版本快照（发布后不可再改）
  MUST: mode=aggregate 时 operator 必填；predicate 在 count/ratio 时必填
  MUST: predicate 只能引用展开实例的 TBox attribute 或 metric_ref
        （禁自由文本条件）
  MUST: weight_ref 存在时须带加权公式（weighted_count / weighted_avg），
        缺省等权；聚合公式如 count(X) = Σ predicate(instance_i)，
        ratio = count / |实例集|
  MUST: per_instance 模式下节点不做集合聚合；入口级归因上卷规则：
        按各实例 score 降序取 top_k（k 由模型声明，缺省 5）输出
        实例级原因 + 汇总统计，避免把不同设备的故障混成一个预测值
  MUST: 聚合不得改变边 effect 语义（聚合值上升/下降的解读与单实例一致）
  SHOULD: mode=aggregate 且展开结果 > 100 实例时，模型作者须显式
    声明聚合策略（operator + predicate + weight_ref）

**instance_data_binding（object 节点输入契约，修订 P1-1）：**
  Planner 展开出实例集合后，取数需要实例级输入契约：

  instance_data_binding
  ├── instance_source        — 实例集（来自 instance_binding 展开结果）
  ├── data_source            — per-instance 取数：
  │     ├── connector_id     — 按实例查询（如设备台账/实时状态 API）
  │     └── capability_id    — 按实例调用（仅 capability_call 源）
  ├── instance_key_field     — 传给数据源的实例标识字段
  │                            （如 entity_id / business_code）
  ├── instance_observation   — 实例观测字段（如 status / health_score）
  ├── observation_window_ref — 当前观测窗口 = 节点 observation_window
  │                            （引用 §3.1.1 节点字段，非独立声明）
  ├── baseline_window_ref    — 基线窗口 = aggregation.baseline_window
  │                            （引用，唯一权威在 aggregation，
  │                            不在本处重复声明——修订 P2-3）
  └── aggregation_input      — 聚合输入（count/ratio 用 predicate
                                判定后的布尔序列；max/min/avg 用观测
                                数值序列）

  MUST: object 节点（无论 mode）发布时必填 instance_data_binding
        ——per_instance 模式按实例取观测值/判断 status/算实例级
        证据，比 aggregate 更需要实例级输入契约；
        mode=aggregate 时再额外要求 aggregation 块（含 predicate）
  MUST: count/ratio 无谓词则编译期错误
  MUST: data_source 与节点 data_requirement 的 source_ref / 能力绑定
        一致（同 §3.1.4 双通道一致性规则）；connector 源禁 capability
  MUST: instance_observation 只能引用 TBox 已注册 attribute 或
        metric_ref

双数据通道优先级与一致性（修订 P2-4，按 source_kind 区分）：
  MUST: 节点同时声明 capability_bindings[] 与 data_requirement 时，
        data_requirement 为主（它携带取数/映射/聚合完整契约），
        capability_bindings 为辅助路由信息
  MUST: source_kind='capability' 时，capability_bindings[] 与
        data_requirement.source_ref 必须一致——二者均非空且指向
        同一 capability_id（列表必须单元素），不一致为编译期错误
  MUST: source_kind='connector' 时，capability_bindings[] 应当为空
        （connector 源无 capability 可比对）；若建模者仍填写
        capability_bindings[]，仅作展示用途并在编译期告警，
        不参与执行路由
```

```
MUST: source_ref 必须指向已注册且 active 的 Connector/Capability
MUST: metric 节点的 data_requirement 必须含 metric_binding
MUST: output_mapping 声明输出字段映射，保证 Planner 生成的 Step 输出
      可直接作为节点观测值参与归因计算
```

#### 3.1.5 TBox causal 命名空间（修订 P1-3）

现状：`relation_types` 表（migration 0008）无 namespace 字段，status 仅
`active/deprecated`；现有 `caused_by` 是 ABox 结构性关系（alarm→equipment）。
若直接新增 `influences/causes`，QU 校验、Ontology 导入、`understanding.py`
动态关系候选会把因果关系当作可落 ABox 事实的类型。

因此 causal 侧登记需 schema 扩展，**在 L3/ECMC 落地前完成**：

```
MUST: relation_types 新增 namespace 列（'structural' | 'causal'，
      默认 'structural'——存量行为不变）
MUST: namespace='causal' 的关系类型仅允许出现在 CausalModel.edges.relation_type_ref，
      ABox facts / QU 关系候选 / 导入映射必须排除 causal namespace
MUST: 现有 caused_by 保持 structural 语义不变（事件归因事实），
      ECMC 因果影响边使用新增 causal 类型（如 influences），不复用 caused_by
MUST: relation_types.status 扩展 draft 态（与 entity_types 对齐，
      支持 Industry Pack 导入 draft——见 §2.5）
SHOULD: capability_entity_map.status 同步扩展 draft 态（Phase 2+ Industry Pack 时）
```

### 3.2 DecisionKnowledge（决策知识）

四类知识对象（DecisionObjective / ConstraintSet / DecisionRule /
EventTaskMapping），统一状态机与治理（均含独立 id/version，§3.4）：

```
DecisionKnowledge
├── DecisionObjective    — 决策目标（提升产量/降低成本）
│     ├── objective_id / version / status
│     ├── metric_ref + 方向 + 阈值
├── ConstraintSet        — 业务约束（安全规则/人员/库存/设备能力）
│     ├── constraint_set_id / version / status
│     └── 约束引用 TBox 类型
├── DecisionRule         — IF-THEN 决策规则
│     ├── rule_id / version / status
│     ├── condition
│     │     ├── source: "metric_ref" | "context" | "capability_call"
│     │     │       （capability_call 仅限 Planner 消费（见下）；
│     │     │          context = 执行上下文已有数据，执行时评估可用）
│     │     └── expression — 条件表达式（引用 metric / entity 属性）
│     ├── action: advice | task_generation | workflow_trigger
│     ├── task_template — action=task_generation 时的任务模板
│     │                   （给 Workflow 编排提供依据）
│     ├── priority        — 冲突裁决优先级（语义对齐 Policy Center：
│     │                     值越低优先级越高，§3.2.1）
│     ├── confidence      — 作者置信度（证据置信度，非执行时决策置信度；
│     │                     execution 消费时忽略——见 §3.2.1）
│     └── scope          — 规则消费域: "planner" | "execution" | "both"
└── EventTaskMapping     — 事件/条件-任务映射（给 Workflow 编排提供依据）
      ├── mapping_id / version / status
      ├── trigger_kind: "event" | "condition"（对齐 Scheduler 两种 Trigger）
      ├── trigger_spec
      │     ├── event: event_type + event_filter
      │     │       （业务事件经 EventBus 事件类型注册表解析——见下）
      │     └── condition: condition_expr + evaluation_frequency
      │             （对齐 Scheduler condition trigger 的评估频率要求；
      │               边沿触发（条件由假变真时触发一次）为默认语义，
      │               电平触发（持续满足重复触发）需显式声明；
      │               condition_expr 禁止 capability_call——见下）
      └── workflow_ref  — 触发的 Workflow 定义（MUST 存在且已发布）
```

**事件类型注册表（修订 P1-5 前置缺口）：** 现有 EventBus 事件类型清单无业务事件（如设备报警）。EventTaskMapping.event 引用的事件类型必须先在**事件类型注册表**（EventBus 规范 v1.2 扩展项）注册——业务事件由 Connector/事件接入层发布，注册表声明事件类型、payload schema、来源。未注册事件类型的 mapping 不可发布。

**condition.source = capability_call 的求值路径（修订 P1-4，评审决策：方案 b）：**

```
capability_call 条件不允许内联在 Decision Engine 执行时分支中
（保持 Rule-based ≤ 100ms 契约不变）。

- scope = planner 的规则: Planner 规划时识别 capability_call 条件，
  将该 Capability 调用生成为 Plan 的前置 Step（走正规 Execution 链路：
  审计/限流/重试由平台保障），执行结果注入分支评估上下文
- scope = execution 的规则: condition.source 仅允许 metric_ref（取数据中台
  实时指标）或 context（执行上下文已有数据）
- MUST: capability_call 源仅允许只读 Capability，可强制校验而非
  依赖建模者自觉：
      a) business_capabilities.type = 'query' 为必要条件（编译期拒绝
         type='command' 的引用）；
      b) 执行 adapter 白名单：capability_call 前置 Step 仅允许
         白名单内 adapter 类型执行（L3 定清单，且 tool.fetch 类
         adapter 默认不允许进 capability_call 白名单——见 P2-3）；
      c) 只读属性由 Orchestrator 从 Capability 注册表推导，不信任
         Step 自带标记——Planner 生成前置 Step 时写入
         capability_id 引用，Orchestrator 查注册表 type=query
         才放行；Connector adapter 执行边界强制校验
         （执行层仅允许白名单 adapter 且校验注册表 type），
         恶意/有误 Planner 标注 read_only=true 亦无法绕过
  MUST（L3）：type=query 仍是注册时声明，不可信任为最终安全边界；
      L3 增加管理端审核的不可变 side_effect 分类（read-only /
      write-only / mixed），capability_call 引用强制要求
      side_effect=read-only，注册后不可变更
  MUST: 声明超时上限与输出字段映射（output_mapping，同 §3.1.4）
MUST: EventTaskMapping.condition.condition_expr 同样禁止 capability_call
      ——表达式仅允许引用 metric_ref / 事件 payload 字段 /
      Connector 提供的实时指标（求值方为 Scheduler，无 Capability
      执行能力）
MUST: scope 组合约束（编译期）：
      - scope='both' + source=capability_call → 编译期错误（禁止）
      - scope='both' + source ∈ {metric_ref, context} → 合法（两域均可消费）
      - scope='planner' 允许 capability_call / metric_ref / context
      - scope='execution' 仅允许 metric_ref / context
      （即 capability_call 只出现在 scope='planner' 的规则中）
```

#### 3.2.1 契约

```
MUST: 规则条件中的指标/实体引用 TBox 类型
MUST: action 为 workflow_trigger / EventTaskMapping.workflow_ref 引用的
      Workflow 必须存在且已发布（发布时校验，被引用 Workflow 下线时
      阻断并通知 owner）
MUST: 与 Policy Center 分工——ECMC 规则是业务性"怎么办"，
      Policy 是治理性"允不允许"，两者叠加生效、互不替代
MUST: 跨 Data Domain 引用时权限取最高 data_classification（同 §3.1.2）
MUST: DecisionKnowledge 四类对象独立标识、独立版本；规则间引用
      （如 DecisionRule 引用 ConstraintSet）必须指向已发布对象
MUST: 同优先级规则冲突时的裁决按 scope 分离：
      - scope = planner（规划时）: 两个 action 并列输出并标注冲突，
        由 Planner/LLM/用户裁决（规划有裁决空间）
      - scope = execution（执行时）: 确定性裁决，不得并列输出——
        依次取 (priority 升序取值 → 更新版本 → 更近发布时间) 选唯一
        生效 action；仍不可分时丢弃两者并走 Decision Engine 默认
        分支（fallback），审计记录冲突详情。
        priority 语义对齐 Policy Center（值越低越高）；
        与 Decision Engine "有且仅有一个 selected_branch" 契约对齐；
        Policy 不裁决业务冲突，仅作治理性否决
MUST: DecisionRule.confidence 语义 = 作者对规则依据的证据置信度，
      不是决策置信度；execution 消费时忽略（Decision Engine Rule-based
      置信度恒为 1.0 契约不变），planner 消费时可用于规则排序参考
MUST: 发布时强制：execution 消费的规则（scope 含 execution）若
      引用 capability_call 则编译期拒绝（见 §3.2 组合约束）

**action × scope 合法组合表（修订 P2-6，v0.6 补 both 列）：**

| action \ scope | planner | execution | both |
|---|---|---|---|
| advice | ✅ 生成建议进规划上下文 | ✅ 选择分支时输出建议 | ✅ 两域均输出建议 |
| task_generation | ✅ 生成任务模板供 Planner 排入 Plan（不立即执行） | ✅ 生成任务 Step | ✅ 两域各按自身语义 |
| workflow_trigger | ❌ 禁止——规划期不触发执行，避免旁路 | ✅ 唯一合法域：触发 Workflow 分支 | ❌ 禁止——workflow_trigger 时 scope 只能是 execution（编译期校验） |

说明：
- scope=planner 的 workflow_trigger 为编译期错误（规划期无执行语义）
- **scope=both 的 action 裁决（修订 P1-2）**：both 域合法条件 =
  action ≠ workflow_trigger；action=workflow_trigger 时编译期
  强制 scope 只能是 execution（both 组合报错）
- 与 EventTaskMapping 职责边界：EventTaskMapping 是事件/条件 →
  Workflow 的**外部触发映射**（Scheduler 消费，见 §3.2.2）；
  DecisionRule.workflow_trigger 是**执行内分支**触发（Decision Engine
  在 Step 分支处触发已发布 Workflow）——两者触发源不同，互不重叠
SHOULD: 规则支持组合（AND / OR / NOT，与 Decision Engine §3.1 一致）
```

#### 3.2.2 消费路径（三条）

| 消费方 | 用法 |
|---|---|
| Planner | DecisionObjective + ConstraintSet 注入规划上下文，用于 Goal 分解与 Plan 生成；scope=planner 规则的 capability_call 条件生成为前置 Step |
| Decision Engine | 执行时分支选择从已发布 DecisionRule（scope 含 execution）读取（规则资产化，替代散落代码/配置）；condition.source 仅 metric_ref / context |
| Scheduler / Workflow | ECMC 将 EventTaskMapping 生命周期发布为事件：`earp.bmc.mapping.published`（创建/更新 trigger）、`earp.bmc.mapping.deprecated`（停用 trigger）、`earp.bmc.mapping.rolled_back`（指向回滚目标版本快照，Scheduler 据此更新 trigger）；事件携带 `mapping_id + mapping_version`；Scheduler 按版本号比较后应用（乱序到达不生效旧版本），并以定时对账任务（对比 ECMC 侧已发布版本 vs Scheduler 侧 trigger 版本）兜底不一致（修订 P1-4 乱序）；ECMC 不主动注册 trigger（修订 P2-13），执行走 Workflow。Scheduler 侧幂等：事件重复消费不重复建 trigger |

### 3.3 ScenarioTemplate（专家业务方案模板，Phase 3+）

> **定位：专家业务方案模板（方法论模板），不是业务应用。**
> 它封装的是"针对某类业务问题，专家如何分析/如何处理"的**方法论**——
> 例如"生产异常分析方法论模板"（不是"生产异常分析 Agent"）；
> 生产异常分析 Agent 是方法论模板实例化后运行的应用形态，
> 属于执行域，不是 ECMC 的资产。

```
ScenarioTemplate（专家业务方案模板）
├── name / description / data_domain_id / version / status
├── problem_type           — 适用问题类型（意图语义描述，供 Planner 匹配）
├── methodology_steps[]    — 方法论步骤骨架（SHOULD）：分析/处理该问题的
│                            步骤顺序与各步骤引用的模型/能力/输出
├── model_bindings[]       — 引用已发布 CausalModel / DecisionKnowledge
├── capability_set[]       — 所需 Capability 清单
├── input_contract         — 触发该模板的意图描述（供 Planner 语义匹配）
├── output_contract        — 输出物契约（原因分析报告/优化建议）
└── compilation_target     — 实例化编译目标（Workflow / Chat App，L3 细化）
```

模板是**专家方法论沉淀**（专家把"分析产量下降要用哪些模型、哪些能力、
按什么步骤、输出什么"固化下来），实例化后编译为 Workflow / Chatflow
由既有执行域运行——**模板是知识资产，实例化后的 Agent/应用是执行产物**，
两者严格区分。Phase 3+ 落地，本次仅定契约骨架。

### 3.4 Model Governance（模型治理子模块，v0.16 重构）

> **定位：ECMC 的一等二级子模块**，负责模型资产的**问题管理、修改、版本、发布**四件事。
> 横切能力（审批流 / 审计 / 绩效埋点）复用 Policy Center / Audit Spec /
> Observation Spec，本模块不重复建设。

```
Model Governance
├── 问题管理（§3.4.1）—— 运行反馈登记为 issue，驱动优化
├── 模型修改（§3.4.2）—— 分支 / 变更原因（change_log）/ diff 对比
├── 版本管理（§3.4.3）—— 语义化版本 / 不可变快照 / 回滚 / 版本对比
└── 发布管理（§3.4.4）—— testing 准入 → Publish Approval → 滚动升级 / 紧急通道
```

#### 3.4.1 问题管理（Issue，v0.16 新增）

**定位**：模型运行中的反馈（不准 / 漂移 / 业务变化）登记为治理问题，
驱动"修改 → 升级"闭环。ECMC 内建轻量 issue 登记（方案 A，不引入外部工单系统）。

```
ModelIssue
├── issue_id / tenant_id / data_domain_id
├── model_ref             — model_id + version（针对哪个模型哪个版本）
├── source_type           — performance_alert | user_feedback |
│                            business_change | dependency_change | manual
├── source_ref            — 触发源引用（绩效告警 ID / 反馈 ID / eval job ID）
├── severity              — low | medium | high | critical
├── description           — 问题描述（含可复现信息）
├── status                — open → triaged → in_progress → fixed →
│                            closed | won't_fix
├── linked_change         — 关联的变更（新版本 / change_log）
├── owner / created_at / resolved_at
└── timeline              — 状态流转记录（Audit 归档）

MUST: issue 与模型版本强关联（model_ref 指向具体版本）
MUST: issue 状态流转全程记录（timeline 走 Audit Spec）
MUST: 修复动作必须产生新版本（change_log 引用 issue_id）
MUST: issue 关闭需有结果记录（fixed 指向修复版本 / won't_fix 附原因）
SHOULD: 同类 issue 聚合（同一模型同一根因多次反馈合并，避免重复工单）
```

#### 3.4.2 模型修改

```
MUST: 新版本从当前 published 版本**分支**（parent_version），
      禁止就地修改 published；分支进入 draft
MUST: 每次修改携带结构化 change_log（change_type / reason /
      trigger_ref / diff_summary / author）；修复 issue 的版本其
      change_log.reason 引用 issue_id（可追溯）
MUST: 版本对比工具展示两版本 diff + 变更原因（评审/审计用）
```

#### 3.4.3 版本管理

```
MUST: 版本语义化（major.minor.patch）；发布产生不可变版本快照
MUST: 消费方引用固定版本号；模型 deprecated 不影响已引用旧版本快照
      在既有 Execution 中的可用性（Plan 执行中不中断）
MUST: 回滚 = 将消费入口指向既有版本快照（发布操作），不删除历史版本
MUST: 回滚同样走 Publish Approval（model_asset 审批）+ Audit diff
      记录 + Scheduler 事件（earp.bmc.mapping.rolled_back）——
      与首次发布同级治理，无绕过路径
MUST: 只有 published 状态的模型对象可被消费方检索
MUST: 变更记录（含版本 diff）走 Audit Spec
```

#### 3.4.4 发布管理

```
状态机: draft → testing → published → deprecated
允许的转换:
  draft → testing      （准入：结构校验通过——DAG 无环、引用完整、
                        output_mapping 齐备；无 testing 需求可直接 draft → published）
  testing → published  （准入：回测报告产出（SHOULD）；依赖完整性校验通过）
  testing → draft      （回测不达标退回）
  published → deprecated（下线）
  deprecated → published（重新启用，仅当依赖仍完整）
禁止: published → draft（不允许就地降级，新修改走新版本）

发布审批（修订 P1-9）：
  现状核对：Policy Center 绑定目标为 Capability/Domain/Role/Tenant，
  approval 是 Execution 等待语义——不支持模型资产内容审批。因此：
  MUST: 发布审批为独立审批流（Publish Approval），Policy Center 新增
        策略目标类型 "model_asset"（改动项见 §5），审批对象 = 版本快照 + diff
  MUST: 审批通过才进入 published；审批记录走 Audit Spec
  SHOULD: 发布者 ≠ 审批者分离（专家编辑 / 管理者审核，与 TBox P6 同构）

滚动升级与旧版本处理：
  MUST: 发布新版本后，旧版本按消费方引用情况处理——有活跃引用的
        旧版本保持 published（不动，消费方自行升级）；无引用可选 deprecated
        （有下线审批）
  MUST: 滚动升级由消费方（Planner）在模型检索时优先新版本
        （applicability 匹配度相同时取最新版本）；消费方可固定版本
  SHOULD: 重大绩效问题可走「紧急修复」通道：reason 必须标注 emergency，
        审批加速但审计不减

依赖完整性校验（发布时 MUST，含引用对象下线的持续保障）：
  MUST: 发布时校验——节点/条件引用的 TBox 类型已 active、
        capability_binding 指向已注册 Capability、
        data_requirement.source_ref 指向 active Connector/Capability、
        workflow_ref 指向已发布 Workflow、事件类型已注册
  MUST: 「依赖失效告警」是 published 状态上的正交布尔标志
        （dependency_ok: true/false），不是独立状态机状态；
        被引用对象下线时标志翻转为 false 并通知 owner
  MUST: dependency_ok=false 的模型：检索仍返回（Planner 需要看到
        归因知识），但模型元数据携带失效依赖清单；依赖节点生成的
        数据 Step 正常执行、失败时按 Execution 既有重试/降级路径
        处理，报告中标注哪些原因链证据缺失——消费方不静默消费
  MUST: 回滚不重复执行发布校验（目标快照在首次发布时已校验）；
        回滚 = 消费入口指向既有版本快照，即便该快照的部分依赖
        已下线（此时依赖失效标志随迁为 false，走上述告警路径）
```

### 3.5 运行绩效观测与优化触发（v0.15 新增，v0.16 定位调整）

**定位**：Model Governance 子模块（§3.4）的**感知前端**——§3.4.1 问题管理负责
issue 登记与流转，本节负责**绩效观测与偏差发现**（把"发现不准"变成可度量的信号）：

**闭环总览（与 §3.4 配合）：**

```
运行消费（Planner/Agent/Decision Engine 使用已发布模型）
  → 绩效观测（Execution 结果 + 用户反馈 + 周期性评估）← §3.5
  → 发现偏差（模型不准/漂移/失效）→ 登记 ModelIssue ← §3.5 → §3.4.1
  → 触发优化（人工 + 系统提示）
  → 修改出新版本（新分支，携带变更原因）← §3.4.2
  → 测试/回测 → 审批 → 重新发布（滚动升级）← §3.4.4
  → 旧版本下线策略决策
```

**① 运行绩效观测（MUST）：**

```
MUST: 模型发布后持续记录运行绩效指标：
      - 调用量 / 成功率 / 平均延迟（Execution 自动埋点）
      - 归因结果被采纳率（用户对 Cause Ranking 的采纳/否决动作）
      - 周期性评估（eval jobs：用保留数据集回测，发现准确率下滑/漂移）
MUST: 绩效数据按 model_id + version 维度存储（可对比版本间表现）
SHOULD: 绩效异常（采纳率骤降 / 评估分数跌破阈值）自动触发
        「建议优化」告警并通知 owner
```

**② 优化触发（MUST，v0.16 对齐 issue 机制）：**

```
触发源（三类），统一登记为 ModelIssue（§3.4.1）：
  1. 运行绩效：采纳率低 / 评估漂移（系统告警 → issue，severity 按漂移幅度）
  2. 用户反馈：专家/员工对归因结果的纠错、补充（显式反馈入口 → issue）
  3. 业务变化：业务规则、数据源、TBox 词汇变化导致模型过时
     （依赖变更检测 → issue）
MUST: 每次触发登记 ModelIssue（source_type + source_ref），
      issue 与模型版本强关联
MUST: 修复动作由 issue 驱动：issue → 新版本（change_log 引用 issue_id）
```

**③ 变更原因管理（归 §3.4.2，本节仅保留引用）：**

```
MUST: 每个版本携带结构化 change_log（change_type / reason /
      trigger_ref / diff_summary / author）——结构定义与不可变
      存储见 §3.4.2/§3.4.3
MUST: 修复 issue 的版本，其 change_log.reason 引用 issue_id（可追溯）
```

**④ 优化升级与旧版本处理（归 §3.4.4，本节仅保留引用）：**

```
MUST: 新版本经 testing → Publish Approval → published（流程、
      滚动升级、旧版本处理、紧急通道均见 §3.4.4）
MUST: 变更原因（change_log.reason / issue 关联）进入审批上下文
      供审批人评估
```

**与 §7 L3 方向的衔接：** 回测机制（L3 #5）是本闭环的评估支撑；
运行绩效观测的 eval jobs 复用 ontology 域已有的 eval 基础设施。

---

## 4. 消费方集成契约

### 4.1 Planner ← ECMC（最重集成点）

```
触发: Goal Generation / Domain Routing 阶段
调用: 模型检索（entry_point 语义匹配 + applicability 过滤 +
      角色可见域过滤；多模型命中按 §3.1.2 消歧）
返回: 已发布 CausalModel 候选集（含节点/边摘要 + 版本号）

后续:
  → 因果归因类意图: 调用 Causal Reasoning Contract（Phase 1 默认：
    沿因果边反向遍历 + 符号积过滤，见 §3.1.2 参考实现）→ 按节点
    data_requirement（§3.1.4）生成数据获取 Step → 经 capability_binding
    绑定 Capability → 纳入 Plan（证据链回填）
  → 决策类意图: 注入 DecisionObjective + ConstraintSet → Goal 分解；
    scope=planner 规则的 capability_call 条件生成前置 Step
  → （Phase 3+）场景类意图: 匹配 ScenarioTemplate → 实例化为 Workflow
```

```
MUST: 只检索 published 状态
MUST: 返回模型版本号（Planner 在 Execution Trace 中记录，保证可复现）
```

### 4.2 Decision Engine ← ECMC

```
触发: 执行时分支 Step
调用: 按 data_domain + entity_type 检索已发布 DecisionRule（scope 含 execution）
行为: Rule → LLM → ML 优先级不变，ECMC 是规则的新来源之一；
      condition.source 仅 metric_ref / context（capability_call 由
      Planner 前置 Step 化，见 §3.2）——Rule-based ≤ 100ms 契约不变
```

### 4.3 与 KB 的双向关系（D1 落地）

```
Enterprise Semantic Layer（共建）: ontology 域物理不动，KB 与 ECMC
  都是消费方（KB 提供 ABox 结构性事实，ECMC 提供因果侧关系类型
  登记）；causal 侧关系类型登记入 TBox 词汇表（namespace 扩展见
  §3.1.5）

KB → ECMC: 实例化时提供实体实例（ABox 沿 belongs_to / located_in 展开）

ECMC → KB（假设性知识闭环，修订 P1-6，评审决策：方案 b；
      v0.3 修正表结构——不复制 facts 三元组）:
  因果推理产生的"假设性断言"（如"3 号矿产量下降疑似因主轴承老化"）
  写入独立候选表 hypothesis_facts。**hypothesis 不是三元组事实**：
  因果结论既不能用 structural 关系表达，又不得使用 causal namespace
  关系类型（§3.1.5 约束其仅限 CausalModel.edges），故采用
  断言式结构，不复用 facts 的 source/relation/target 三列：

  hypothesis_facts
  ├── hypothesis_id
  ├── tenant_id / data_domain_id（可见性同 §3.1.2 双层权限）
  ├── subject: {entity_id?, entity_type_id?, metric_ref?}  — 断言主体
  │       （实体或指标，引用 ABox 实例 / TBox 类型）
  ├── assertion: string          — 断言文本（"疑似主轴承老化"，展示用）
  ├── assertion_schema            — 结构化断言（修订 P2-5，最小骨架，
  │     │                         推理时自动生成，自由文本仅作展示）：
  │     ├── subject               — 断言主体（同 subject）
  │     ├── property / state      — 属性/状态（引用 TBox attribute 或
  │     │                          metric_ref，注册词表内，禁自由文本，
  │     │                          如 bearing_wear 需先注册）
  │     ├── direction             — up / down / unchanged / unknown
  │     ├── time_window           — 断言适用时间窗（如 P30D）
  │     └── confidence_interval   — SHOULD，区间下界（供审核排序）
  ├── normalized_relation?: structural relation_type_id + target_entity_id
  │       （仅当断言可映射为既有结构关系时填写——如"轴承 X 属于 CNC-01"
  │        可映射 belongs_to；映射不了就留空，不强行造关系）
  ├── evidence: JSONB（证据摘要：路径、节点观测值、score）
  ├── provenance: model_id + model_version + reasoning_trace_id
  └── status: candidate → adopted | rejected | withdrawn

  MUST: 假设性结论只入 hypothesis_facts，永不直接写 facts
  MUST: facts/QU/Compiled Truth 检索默认排除 hypothesis_facts
        （显式请求假设查询时单独通道）
  MUST: 审核通过转正：有 normalized_relation 的抄录为 facts 新行
        （source_ref 指向 hypothesis 记录）；无映射的归档为 RAG
        文档型知识条目（归档条目 source_ref=hypothesis_id、携带
        置信度与审核记录，检索结果标注"假设来源"；撤回时联动删除/
        下线归档条目及其 embedding 索引——修订 P1-5），原
        hypothesis 置 adopted
  MUST: 撤回 = hypothesis 置 withdrawn（已转正的走事实正常生命周期；
        已归档的按上一条联动移除），无 orphan 残留
  SHOULD: 同一主体 + 相似断言多次独立推理命中 → 提升审核优先级
        （相似度基于 assertion_schema 字段匹配为主，文本相似度辅助）
```

### 4.4 ECMC Cognitive Service Contract（认知服务契约，v0.17 新增）

> **定位**：Planner（及未来其他消费方）与 ECMC 之间是**认知模型查询与推理服务关系**。
> 本节定义**语义级服务契约**（谁调用谁、为什么、输入输出语义、关键约束），
> 不绑定传输实现（HTTP / gRPC / 内存调用 / Event Bus 由 L3 决定）——
> 避免 L2 被具体协议锁死。

#### 4.4.1 交互定位

Planner 为什么调用 ECMC？因为 ECMC 提供两类认知能力：

```
                ECMC
                 |
     -------------------------
     |                       |
 Model Discovery        Reasoning Service
 （找模型）               （用模型）
```

- **Model Discovery**：给定意图（入口节点 + 业务目标 + 领域 + 方向），返回匹配的已发布模型
- **Reasoning Service**：给定模型版本 + 实例绑定 + 观测数据需求，返回推理结果（Cause Ranking + Evidence Chain）
- 两者均为同步查询语义（无状态）；具体超时/重试策略 L3 定，但**不允许返回假完整结果**（见 4.4.3）

#### 4.4.2 Model Discovery Contract（模型发现契约）

**输入（意图四元组）：**

```
intent:
  entry_point         — 入口节点语义（如"产量下降"）
  direction           — up / down（观测方向，区分"为什么下降"与"为什么上升"）
  domain              — 业务领域（如 production）
  business_objective  — 业务目标（v0.17 新增，同节点不同任务）：
                          diagnose（原因分析）| predict（趋势预测）|
                          optimize（优化建议）| recommend（推荐）
context:
  tenant_id           — 租户
  entity              — 目标实体（{ entity_id, type }，如 3 号矿）
  role_scope          — 角色可见域（双层权限过滤输入）
options:
  top_k               — 候选数
  version_policy      — latest（匹配度→最新）| pinned（固定版本）
```

**输出（模型候选集）：**

```
models: [{
  model_id, version, status: "published",
  entry_points: [{ node_id, direction, description }],
  business_objective_support: [diagnose|predict|optimize|recommend],
  applicability: { entities, industries },
  match_score: 0-1,                    ← 匹配度（Planner 排序用）
  capability_requirements: [...]        ← 见 4.4.4
}]
```

**关键语义：**

```
MUST: business_objective 参与匹配——同一入口节点不同业务目标可能命中不同模型
      （产量下降：原因分析模型 / 趋势预测模型 / 优化建议模型）
MUST: 只返回 published 模型；role_scope 按双层权限过滤
      （模型可见性 + 模型应用范围 + 数据权限，见 Governance）
MUST: version_policy=latest 按 applicability 匹配度 → 最新版本排序；
      pinned 精确匹配版本号
MUST: match_score 语义明确（基于 entry_point 语义 + business_objective +
      applicability 的匹配度；具体算法 L3，契约只定义语义）
```

#### 4.4.3 Reasoning Contract（推理服务契约）

**输入：**

```
instance:
  entity_id / entity_type     — 实例绑定（object 节点展开的锚点）
  scope: time_window          — 观测时间窗（如 P30D）
options:
  reasoning_mode (v0.17，替代 algorithm——不暴露算法实现)：
    default       — 默认（Phase 1 = 符号传播 + 路径排序）
    fast          — 快速（低延迟优先，ECMC 内部选算法）
    explainable   — 可解释优先（完整证据链）
    high_accuracy — 高准确率优先（ECMC 内部选算法，如回测最优）
  explain_level (v0.17 新增)：
    basic     — 简单原因（驾驶舱场景）
    detailed  — 完整证据链（总工场景）
    audit     — 审计级（安全场景，含全部中间步骤）
```

**输出：**

```
cause_ranking: [{
  node_id, direction_explanation,      ← 解释方向
  score, confidence,
  evidence_chain: [{
    step_node_id, relation,
    observation: { direction, value, source },
    data_requirements_met: bool         ← 该步骤数据是否满足
  }]
}]
meta: { model_id, version, reasoning_mode, reasoning_trace_id,
        complete: bool }                ← complete=false 表示部分结果
```

**关键语义：**

```
MUST: 结论可解释——Cause Ranking 每项必须带 Evidence Chain；
      explain_level 决定证据链粒度（audit 含全部中间步骤与数据来源）
MUST: 可复现——响应携带 reasoning_trace_id + version，Planner 记入
      Execution Trace
MUST: 不允许假完整——超时/数据不足时返回 complete=false 的部分结果
      + 缺失清单，绝不静默补齐
MUST: 输入不足（模型需要 30 天数据但只有 3 天）→ 判定为
      "不可处理"（L3 映射 422 语义）：返回 missing_requirements
      清单（缺哪些观测/数据），不是"找不到模型"
MUST: reasoning_mode 是 ECMC 内部算法选择的意图声明；
      Planner 不感知、不依赖具体算法（贝叶斯/图搜索/LLM 均为
      ECMC 内部实现，L3 选型）
```

#### 4.4.4 Capability Dependency Contract（能力依赖契约）

**定位**：ECMC 不执行。它告诉 Planner——为了完成这个业务推理，需要什么能力：

```
capability_requirements: [{
  capability_id,                        ← Capability Center 注册的 id
  purpose,                              ← 为什么需要（对应模型节点/步骤）
  required: true | false,               ← 必需 vs 可降级
  input_schema,                         ← 需要的输入（实体/时间窗/字段）
  output_usage                          ← 输出如何被使用（节点观测值）
}]
```

```
MUST: capability_requirements 是模型运行所必需（区别于"建议"）；
      Planner 据此向 Capability Center 解析并纳入 Plan
MUST: required=false 的能力缺失时可降级（推理结果标注降级）
MUST: ECMC 不直接调用 Capability——调用由 Planner 编排（保持
      纯知识层定位，见 §2.2 不负责清单）
```

链路：`Planner → ECMC（能力需求）→ Capability Center（解析）→ Plan 生成`

#### 4.4.5 Feedback Contract（运行反馈契约，v0.17 新增）

**定位**：为模型演进闭环（§3.5）准备的反馈通道——消费方（Agent/用户）
对推理结果的采纳/否决/纠错回传给 ECMC：

```
feedback:
  reasoning_trace_id      — 关联哪次推理
  model_id / version      — 关联哪个模型版本
  action: accept | reject | correct
  correct_payload?        — action=correct 时的新事实/纠错内容
  source: user | system   — 来源
```

```
MUST: 反馈按 reasoning_trace_id + model_id + version 归档（绩效统计基础）
MUST: 采纳/否决率是 §3.5 ① 运行绩效观测的核心指标
MUST: correct 反馈触发 ModelIssue 登记（source_type=user_feedback，
      见 §3.4.1）——驱动模型优化闭环
```

**交互总链路（闭环）：**

```
User → Agent Runtime → Planner → ECMC（Discovery → Reasoning →
Capability Requirements）→ Capability Center → Enterprise Systems
→ Observation Feedback（§4.4.5）→ ECMC Model Improvement（§3.5）
```

---

## 5. L2 规范改版清单

| # | 文档 | 改动 | 优先级 |
|---|---|---|---|
| 1 | 新建 `arch/L2/02-reasoning/enterprise-cognitive-model-center-specification.md` | ECMC 主规范（本文设计的契约化落盘；核心章节：元模型统一视图 / 认知服务契约 / FDE 建模工作流 / 治理闭环） | P0 |
| 2 | `knowledge-center-specification.md` v1.2 → v1.3 | 第四章 Ontology 标注"Enterprise Semantic Layer（企业语义层），KB/ECMC 共建"；ABox 增补 hypothesis_facts 候选表契约（ECMC 假设回写通道，方案 b） | P0 |
| 3 | `planner-specification.md` | 新增"ECMC 知识源"章节：模型检索、因果遍历、决策知识注入、capability_call 前置 Step 化 | P0 |
| 4 | `decision-engine-specification.md` v1.0 → v1.1 | §3.1 增补"ECMC DecisionRule 为规则来源之一（scope=execution）"；条件源约束（metric_ref/context） | P1 |
| 5 | `concept-model-v2.x` | 新增 CausalModel / DecisionKnowledge / ScenarioTemplate 概念对象 | P1 |
| 6 | `scheduler-specification.md` | 新增"订阅 earp.bmc.mapping.published 创建/更新 trigger"说明；EventTaskMapping 触发语义（边沿/电平、评估频率）对齐 | P1 |
| 7 | `workflow-specification.md` | task_template / ScenarioTemplate 实例化的编排依据说明 | P2 |
| 8 | `eventbus-specification.md` v1.1 → v1.2 | 新增业务事件类型注册表；`earp.bmc.mapping.published / deprecated / rolled_back` 事件类型 | P1 |
| 9 | `policy-center-specification.md` | 新增策略目标类型 model_asset（ECMC 发布审批） | P1 |
| 10 | migration（代码侧，L3 前瞻） | relation_types 加 namespace 列 + status 扩展 draft；hypothesis_facts 表；既有 QU 校验/导入/understanding 排除 causal namespace | P0 |
| 11 | `observation-specification.md`（可观测性） | 新增模型运行绩效观测：调用量/成功率/延迟/采纳率埋点（§3.5 ①） | P1 |
| 12 | `audit-specification.md` | 模型变更日志（change_log：reason/trigger_ref/diff）归档要求对齐（§3.4.2） | P2 |

代码侧（L3 前瞻，不入本文）：新增 `earp_server/bmc/` 域；import-linter 新增契约；`ontology/` 域不迁移。

---

## 6. 实施路线建议

```
Phase 1  CausalModel + 决策知识核心（DecisionRule / EventTaskMapping）
         + 生命周期状态机（含 Publish Approval）+ Planner 因果归因链路
         + 前置基础设施（relation_types namespace 扩展、事件类型注册表、
           model_asset 策略目标）——最小闭环："为什么产量下降"端到端跑通
Phase 2  DecisionObjective / ConstraintSet 注入 Planner；
         ECMC → KB hypothesis_facts 回写闭环；Industry Pack 工具化；
         运行反馈闭环起步（绩效埋点 + change_log 变更原因管理）
Phase 3  ScenarioTemplate + Planner 场景匹配 + 实例化编译；
         运行绩效评估自动化（采纳率监控 + 漂移检测 + 建议优化告警）
```

排序依据：因果归因是 ECMC 净增值最高、可独立验证的链路，先跑通；决策知识先落规则与事件映射（对 Workflow 编排的依据价值立即兑现）；场景模板价值依赖消费链路，最后落地。

---

## 7. 后续 L3 设计方向

1. **模型元数据物理模型**：ECMC 各对象的表结构（PG 承载，沿用"基础设施最小化"原则，图数据库留待多跳推理需要时评估）
2. **因果图引擎**：图存储（递归 CTE vs 图数据库）、图查询、实例化展开规则
3. **因果推理算法选型（v0.14 新增，L2 契约已预留）**：Phase 1 默认 = 符号传播 + 路径排序（§3.1.2 参考实现）；L3 评估并可选引入：规则推理、图搜索、贝叶斯网络、LLM reasoning、时序模型——候选算法必须满足 Causal Reasoning Contract（可解释：输出带 Evidence Chain；可复现；可替换；无副作用）
4. **Planner 集成实现**：entry_point 语义匹配（复用 Semantic Index）、模型选择、因果遍历 → Plan 生成的映射
5. **FDE 建模工具**：拖拽编辑器、节点配置、发布流程（对接 Policy 审批）
6. **回测机制**：testing 阶段的 strength/lag 校准、DecisionRule 回测、testing 准入/退出标准的量化定义
7. **Industry Pack 格式**：导出/导入 schema、冲突检测算法、ID 映射与重复导入幂等性、发布时 dependency 完整性校验同 §3.4
8. **多跳因果聚合细化**（默认实现的增强）：重叠路径去重、路径冲突的数据裁决、强度衰减函数
9. **Publish Approval 审批流实现**：审批对象（版本快照 + diff）、审批人路由（owner 角色）、与 Policy Center model_asset 目标类型的对接

---

## 8. 场景验证记录（设计修订依据）

设计过程中以四个差异化场景代入验证，发现并修复六个缺口：

| 场景 | 发现的缺口 | 修订 |
|---|---|---|
| A 煤矿产量下降归因 | 节点 outcome/cause 分型在多级链失效；类型模型绑实例缺跨层级规则；缺适用范围声明 | 节点统一为业务量 + entry_point 标记；MUST 沿 KB 结构关系实例化展开；增加 applicability |
| B 预测性检修 | 条件数据源可能是 Capability 输出而非预计算指标；规则冲突消解未定义 | condition.source 支持 capability_call；增加 conflict_resolution |
| C 供应链缺料预警 | 条件持续满足触发（非事件触发）漏建模 | EventTaskMapping 增加 trigger_kind: event \| condition |
| D 跨域经营分析 | 模型跨 Data Domain 引用指标时权限未定义 | 模型可见性 = max(模型所属域分类, 引用对象分类) + 双层权限 + 发布时作者读取权校验（v0.2 强化） |

---

## 9. 对抗性评审处置记录（v0.1 → v0.2）

| # | 评审意见 | 处置 |
|---|---|---|
| P0-1 | 跨域权限防不住模型本体泄漏 | §3.1.2：可见性 = max(模型所属域分类, 全部引用对象分类)，纳入双层权限模型；发布时校验作者对全部引用对象读取权 |
| P0-2 | 无方向语义（up/down、边符号）、无 DAG/聚合定义 | §3.1.1/§3.1.2：entry_point.direction、边 effect 符号、DAG 编译期校验、路径符号积过滤与聚合、多模型命中消歧 |
| P1-3 | causal 命名空间与 relation_types 现状冲突（无 namespace 列；caused_by 已是结构关系） | §3.1.5：schema 扩展（namespace 列、status 加 draft）、ABox/QU/导入排除 causal namespace、不复用 caused_by；§5 改版清单新增 migration 项 |
| P1-4 | capability_call 冲突 Rule ≤100ms | §3.2：**方案 b**（评审拍板）——capability_call 仅限 Planner 消费，生成为 Plan 前置 Step；execution 规则仅 metric_ref/context；只读 + 超时 + output_mapping 约束 |
| P1-5 | EventTaskMapping 缺评估频率/边沿电平/生命周期；业务事件不在事件类型清单 | §3.2：evaluation_frequency、边沿默认/电平显式、workflow_ref 发布校验 + 下线阻断；新增事件类型注册表（EventBus v1.2 扩展，改版清单 #8） |
| P1-6 | 假设回写污染 ABox（facts 无候选态） | §4.3：**方案 b**（评审拍板）——独立 hypothesis_facts 表（provenance/审核状态/撤回），ABox 检索零污染 |
| P1-7 | data_requirement 自由文本无法生成 Step；metric 节点无 ABox 实例 | §3.1.4：结构化契约（source_ref/metric_binding/时间窗/聚合/单位/output_mapping）；实例化区分 object 节点（结构关系展开）与 metric 节点（instance_binding 绑定） |
| P1-8 | 生命周期缺转换规则/回滚/依赖校验/固定版本可用性 | §3.4：完整状态转换表、testing 准入/退回、发布快照不可变、deprecated 不中断既有 Execution、回滚 = 指向既有快照、依赖完整性校验 + 失效告警态 |
| P1-9 | Policy Center 无内容审批，不能直接复用 | §3.4：独立 Publish Approval + Policy Center 新增 model_asset 目标类型（改版清单 #9） |
| P1-10 | Industry Pack draft 与 status 约束冲突（精确化：entity_types 已有 draft，冲突仅 relation_types/capability_entity_map）；ID 映射/幂等未定义 | §3.1.5：relation_types.status 扩展 draft（capability_entity_map Phase 2+）；§7 L3 方向补 ID 映射与重复导入幂等性 |
| P2-11 | applicability SHOULD 但过滤依赖它；多模型命中无消歧 | §3.1.2：发布时必填；消歧策略（applicability 匹配度 → 版本排序 → 冲突标注交消费方裁决） |
| P2-12 | DecisionKnowledge 身份/版本未定义；conflict_resolution 空洞 | §3.2.1：四类对象独立标识/版本、规则间引用须指向已发布对象；冲突 = 并列输出标注，Policy 仅治理性否决 |
| P2-13 | "BMC 不执行"与"注册 trigger"所有权冲突 | §3.2.2：改为 Scheduler 订阅 `earp.bmc.mapping.published` 事件创建/更新 trigger，BMC 不主动注册 |

---

## 10. 第二轮对抗性评审处置记录（v0.2 → v0.3）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | 符号积按字面实现会丢掉反向原因链 | §3.1.2：显式公式 d'(p) = d × S(p)（候选方向 = 目标方向 × 路径符号积），全部路径保留、按 d' 标注方向；中间节点仅作传导路径；归因排序 score = |∏ strength| × ∏ confidence，正负路径并存时并列标注待数据裁决 |
| P1-2 | hypothesis_facts 复制 facts 三列与 causal namespace 约束矛盾 | §4.3：改为断言式结构（subject + assertion + evidence + provenance），normalized_relation 仅在可映射既有结构关系时填写；不可映射的转正后归档为 RAG 文档型知识 |
| P1-3 | 并列输出与 Decision Engine 单分支契约冲突 | §3.2.1：按 scope 分离——planner 并列输出交裁决；execution 确定性裁决链（priority → 版本 → 发布时间 → fallback 默认分支），审计记录冲突详情 |
| P1-4 | mapping 只有 published 事件，无下线/回滚；condition_expr 未禁 capability_call | §3.2.2：新增 `earp.bmc.mapping.deprecated` / `earp.bmc.mapping.rolled_back` 事件，Scheduler 幂等消费；§3.2 契约明禁 condition_expr 使用 capability_call |
| P1-5 | "只读 Capability"无强制元数据 | §3.2：三重强制——type='query' 编译期必要条件、执行 adapter 白名单（L3 定清单）、Planner 前置 Step 注入 read_only 门禁由 Orchestrator 校验 |
| P1-6 | 告警态不在状态机内且"仍可消费"矛盾；回滚被发布校验堵死 | §3.4：dependency_ok 明确为 published 上的正交布尔标志；失效模型返回时携带失效清单、数据 Step 失败走既有重试/降级、报告标注证据缺失；回滚不重复执行发布校验（快照首次发布已校验），依赖失效标志随迁 |
| P2-7 | Phase 1 闭环依赖未定义的聚合算法 | §3.1.2：Phase 1 给出可评审基础契约（score 公式 + 节点取最高分入径 + 冲突并列标注）；去重/衰减留 L3 |
| P2-8 | instance_binding 无语法/权限/性能约束；双数据通道无优先级 | §3.1.4：三段式受限表达式（2 跳上限、仅 structural 关系、展开越权静默过滤、100 实例需显式聚合）；data_requirement 为主、capability_bindings 为辅助路由、不一致为编译期错误 |
| P2-9 | "三类对象"与四类不一致；Objective/ConstraintSet 缺 id/version | §3.2：更正为四类；全部补 id/version/status 字段 |

---

## 11. 第三轮对抗性评审处置记录（v0.3 → v0.4）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | scope='both' + capability_call 组合未定义 | §3.2：编译期组合约束表——both+capability_call 为编译期错误；capability_call 仅出现在 scope='planner' |
| P1-2 | read_only=true 不是安全边界 | §3.2：只读属性由 Orchestrator 从 Capability 注册表推导（Planner 只写 capability_id 引用），Connector adapter 执行边界强制校验注册表 type；恶意标注无法绕过 |
| P1-3 | Scheduler 事件只解决幂等不解决乱序 | §3.2.2：事件携带 mapping_id + mapping_version，Scheduler 按版本比较应用；定时对账任务兜底 |
| P1-4 | instance_binding 未定义遍历方向 | §3.1.4：三段式语法加显式方向段 .in/.out（默认 .out），entity_type 过滤非目标侧实体类型；示例修正（$target_entity.located_in.in.equipment） |
| P1-5 | hypothesis 归档 RAG 后脱离生命周期管控 | §4.3：归档条目 source_ref=hypothesis_id、带置信度与审核记录、检索标注"假设来源"；撤回联动删除/下线条目与 embedding 索引 |
| P2-6 | DecisionRule.confidence 与 Decision Engine 恒 1.0 契约冲突 | §3.2.1：语义定义为作者证据置信度；execution 忽略，planner 排序参考 |
| P2-7 | 排序公式依赖可选字段 | §3.1.2：发布时强制补齐（默认 strength=0.5 / confidence=0.5，显式优先），公式恒有定义 |
| P2-8 | priority 语义与 Policy Center 冲突 | §3.1.1/§3.2.1：对齐 Policy Center"值越低越高"，execution 裁决链改为 priority 升序取值 |
| P2-9 | 回滚绕过审批/审计 | §3.4：回滚同样走 Publish Approval + Audit diff + Scheduler 事件，无绕过路径 |

---

## 12. 第四轮对抗性评审处置记录（v0.4 → v0.5）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | object 节点展开后观测/聚合语义未定义（逐实例 vs 聚合、权重、2-99 实例无契约） | §3.1.4：新增 aggregation 契约——节点显式声明 mode（per_instance / aggregate 缺省 per_instance）、operator（count/ratio/max/min/avg）、weight_ref（缺省等权）；per_instance 每实例独立成径归因、不混聚；聚合不改边 effect 语义 |
| P1-2 | instance_binding 声明 2 跳但语法只支持单跳 | §3.1.4：补链式双跳语法（两个跳段均须显式方向+类型）；单跳 = 种子解析，深度 > 2 跳由 Planner 实例化时沿结构关系继续遍历——语法与契约对齐，不再自相矛盾 |
| P2-3 | 只读建立在 type=query 注册声明之上，不可信 | §3.2：标注 L3 必做——管理端审核的不可变 side_effect 分类，capability_call 要求 side_effect=read-only；tool.fetch 类 adapter 默认不进白名单 |
| P2-4 | 双数据通道一致性规则对 connector 源不成立（无 capability 可比对、列表 vs 单引用歧义） | §3.1.4：按 source_kind 区分——capability 源要求列表单元素且与 source_ref 同一 id；connector 源 capability_bindings 应为空（填写则告警、不参与路由） |
| P2-5 | hypothesis 断言自由文本，无法结构化审核 | §4.3：新增 assertion_schema（subject/property-state/direction/time_window/confidence_interval），相似命中以 schema 字段匹配为主；自由文本仅展示 |
| P2-6 | action × scope 矩阵未定义，workflow_trigger 与 EventTaskMapping 职责重叠 | §3.2.1：新增合法组合表——advice/task_generation 两域合法，workflow_trigger 仅 execution（planner 域编译期错误）；职责边界：EventTaskMapping=外部触发映射（Scheduler），DecisionRule.workflow_trigger=执行内分支触发（Decision Engine） |


---

## 13. 第五轮对抗性评审处置记录（v0.5 → v0.6）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | object 节点缺取数输入契约（聚合只解决输出侧）；count/ratio 缺实例级谓词 | §3.1.4：新增 instance_data_binding（instance_source/data_source/instance_key_field/instance_observation/aggregation_input）；object 节点 mode=aggregate 必须声明；count/ratio 谓词引用 TBox attribute/metric_ref，禁自由文本 |
| P1-2 | action×scope 表缺 both 列，workflow_trigger×both 无裁决 | §3.2.1：补 both 列——advice/task_generation 合法、workflow_trigger 编译期强制 scope=execution（both 组合报错） |
| P1-3 | 双跳示例与 TBox 事实冲突（belongs_to target 非 plant）；"Planner 继续遍历"未收敛 | §3.1.4：示例修正为 production_line（对齐 TBox）；多跳一律模型内显式链式声明（≤2 跳），禁止依赖引擎自由展开，未声明深巷编译期报错 |
| P2-4 | 聚合算子语义不完整（count/ratio 无谓词、weight_ref 无公式、per_instance 无上卷规则） | §3.1.4：补 predicate、加权公式（weighted_count/weighted_avg）、聚合公式显式化、per_instance 上卷规则（按 score 降序 top_k，k 缺省 5） |
| P2-5 | data_requirement 代码块重复 | §3.1.4：删除重复块，保留单份 |
| P2-6 | assertion_schema.property/state 自由字符串 | §4.3：约束为引用 TBox attribute/metric_ref 注册词表，禁自由文本 |


---

## 14. 第六轮对抗性评审处置记录（v0.6 → v0.7）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | instance_data_binding 只对 aggregate 强制，per_instance（缺省模式）反而可不带，Planner 无法生成实例级取数 Step | §3.1.4：改为**所有 object 节点发布时必填** instance_data_binding；per_instance 按实例取观测/判断 status/算实例级证据；aggregate 再额外要求 aggregation 块 |
| P1-2 | 排序公式不含观测证据，归因排序本质是作者先验排序 | §3.1.2：score = |∏strength| × ∏confidence × obs_match(path)；obs_match = ∏节点观测匹配度（一致 +1 / 反向 -1 / 无数据 0 中性），反向数据降权垫底、无数据保留纯先验不丢候选；obs_match 由 instance_data_binding/data_requirement 观测值计算 |
| P2-3 | "MUST 声明 aggregation.mode（缺省 per_instance）"自相矛盾 | §3.1.4：改为发布时校验，未声明按 per_instance 补齐并落入版本快照（发布后不可改） |
| P2-4 | instance_data_binding 未进 §3.1.1 节点结构 | §3.1.1：节点结构补 instance_data_binding 字段（object 节点必填，含五字段说明） |
| P2-5 | ">2 跳隐藏依赖编译期报错"不可实现（编译器不知道未声明的依赖） | §3.1.4：改为发布校验时展开深度超过 2 跳直接拒绝发布（静态可校验），删除不可实现的"隐藏依赖报错"表述 |


---

## 15. 第七轮对抗性评审处置记录（v0.7 → v0.8）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | "无数据=0"在乘法里不是中性（整路径归零），与"保留纯先验"矛盾 | §3.1.2：无数据/unknown 因子改为 1（真正中性）；新增 unchanged=0.5 弱支持；乘法中 0 语义明确修正 |
| P1-2 | obs_match 中间节点复用整条路径 d'(p)，方向会算反 | §3.1.2：定义节点预期方向 e(i) = d × S(i→entry_point 子路径符号积)；用老化→健康度→产量示例证明 e(A)=+1、e(B)=-1 的正确语义 |
| P2-3 | 观测方向缺从原始数据推导的契约，无法复现 | §3.1.2：Phase 1 用首尾点比较（>阈值=up / <-阈值=down / 差≤阈值=unchanged / 无值=unknown）；阈值发布时声明，缺省时间窗均值 5%；L3 可扩展趋势拟合/显著性 |
| P2-4 | unchanged/unknown 未归入 obs_match | §3.1.2：unchanged→0.5 弱支持、unknown→1 中性 |
| P2-5 | 每节点等权连乘，单节点主导长路径 | §3.1.2：声明反向一票否决为有意设计；L3 提供按 confidence 加权变体 obs_match_w = Σ m(i)·conf(i)/Σconf(i)，Phase 1 保持连乘 |


---

## 16. 第八轮对抗性评审处置记录（v0.8 → v0.9）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | 观测方向推导只覆盖数值时间序列，离散状态/计数场景无口径 | §3.1.2：三套口径——①数值序列首尾比较（显式绝对/相对阈值，零/负均值禁用相对默认）；②离散状态按状态跃迁判定（目标状态集发布时声明）；③聚合计数/比率用当前窗口 vs 前一等长窗口（aggregation/instance_data_binding 增加 baseline_window 字段） |
| P2-2 | 默认阈值"时间窗均值 5%"对零均值/负均值/离散值失效 | §3.1.2：发布时强制声明绝对阈值或相对阈值；相对阈值默认仅允许正值指标 |
| P2-3 | unchanged=0.5 连乘让长路径不成比例衰减（0.5^n） | §3.1.2：obs_match 改为节点匹配度几何均值 (∏m)^(1/n)——路径长度不变性，同时保留反向一票否决（任一 -1 → obs_match=0） |


---

## 17. 第九轮对抗性评审处置记录（v0.9 → v0.10）

| # | 评审意见 | 处置 |
|---|---|---|
| P1-1 | 几何均值公式未实现"任一 -1 → obs_match=0"（(-1)^(1/偶数) 实数域无定义 → NaN；偶数个 -1 → +1 矛盾） | §3.1.2：显式分派——存在任一 m(i)=-1 → obs_match=0；否则几何均值 (∏m)^(1/n)（此时 m∈{0.5,1}，结果∈[0.5,1] 实数域恒有定义） |
| P1-2 | 离散状态/聚合计数的"当前窗口"未定义（只定义了基线窗口） | §3.1.1/§3.1.4：object 节点统一新增 observation_window（当前窗口）；口径 2 离散状态按窗口首尾状态判定跃迁；口径 3 聚合计数按窗口聚合值对比基线 |
| P2-3 | baseline_window 在 aggregation 与 instance_data_binding 各出现一次，无一致性规则 | §3.1.4：aggregation.baseline_window 为唯一权威；instance_data_binding 改为 baseline_window_ref 引用，不重复声明 |
| P2-4 | v0.9 改几何均值后仍写"连乘不等权"，表述不一致 | §3.1.2：统一为"几何均值 + 反向一票否决"；L3 加权变体 obs_match_w 保留 |


---

## 18. 架构修订：Ontology 归属更名（v0.10 → v0.11）

**背景**：原 D1 决策"Ontology 逻辑归属 BMC"名称易误解——Ontology 本质不是业务模型，而是企业世界的语言体系（设备/工作面/产线/订单/客户…），同时服务 RAG、数据理解、因果分析、Planner，是 EARP 的公共语义基础设施。

**决策**：

```
原： BMC
      |
      Ontology（BMC 拥有）

改： Enterprise Semantic Layer（企业语义层）
      |
      ----------------
      |              |
     KB             BMC
```
- Ontology/TBox 更名定位为 **Enterprise Semantic Layer（企业语义层）**：EARP 的公共语义基础设施
- 由 **KB/BMC 共建**：KB 提供 ABox 结构性事实，BMC 提供因果侧关系类型登记
- **双方消费、无人拥有**：BMC 使用它，不拥有它
- 物理实现不变：`ontology/` 域不迁移，conversation/planner/connector 消费方零改动

**影响范围**：
- §2.2 负责清单、§2.3 架构图、§3 模块树、§4.3 集成、§5 改版清单已同步
- 文档内术语统一为 Enterprise Semantic Layer；"共治 TBox / 双方共治 / 逻辑域归属 BMC"表述已清除


---

## 19. 架构修订：模块更名（v0.11 → v0.12）

**背景**："Business Model Center（业务模型中心）"名称易误解——"Business Model" 容易被理解为业务流程模型 / 业务对象模型，而本模块实际承载的是**业务认知**（企业运行规律：因果、决策、场景）。

**决策**：

```
原： Business Model Center（BMC · 业务模型中心）
改： Enterprise Cognitive Model Center（ECMC · 企业认知模型中心）
```

- 与 Enterprise Semantic Layer（企业语义层）成对：**语义层 = 企业语言体系（是什么的词汇）**，**认知层 = 企业运行规律（为什么/怎么办/怎么用）**
- 模块内容不变：Causal Model / Decision Knowledge / Scenario Template / 生命周期治理

**影响范围**：
- 文档正文（§1-§8）全部更名：BMC → ECMC
- §5 改版清单：主规范文件名改为 `enterprise-cognitive-model-center-specification.md`
- 历史评审记录（§9-§17）与 §18 保留 BMC 原名（追溯性，当时评审用名）

**保留不变的契约（API 稳定性）**：
- `earp.bmc.mapping.published / deprecated / rolled_back` 事件类型名**不随模块更名改变**——Scheduler 已按此订阅，事件命名是稳定平台契约；若未来确需改名，走 EventBus 事件类型注册表的版本化流程，禁止直接改名破坏订阅


---

## 20. 架构修订：Scenario 定位细化（v0.12 → v0.13）

**背景**：Scenario 易被理解为"业务应用"（如"生产异常分析 Agent"），但 ECMC 是纯知识资产层——Scenario 的实际定位是**专家业务方案模板（方法论模板）**。

**决策**：

```
不是： 业务应用 —— 生产异常分析 Agent
而是： 专家业务方案模板 —— 生产异常分析方法论模板
```

- Scenario 封装的是**方法论**：针对某类业务问题，专家如何分析/如何处理的步骤、模型、能力、输出物
- **模板是知识资产，实例化后的 Agent/应用是执行产物**——后者属于执行域，不属于 ECMC
- 与 D5 一致并强化：非运行时对象、非业务应用，纯方法论沉淀

**影响范围**：
- §3.3 重命名定位为"专家业务方案模板"，结构图新增 problem_type / methodology_steps[]（方法论步骤骨架）
- D5 决策记录措辞细化（"生产异常分析方法论模板"而非"生产异常分析 Agent"）
- §2.2 负责清单、§1.1 表格措辞同步


---

## 21. 架构修订：Causal Reasoning Contract（v0.13 → v0.14）

**背景**：前九轮评审将因果归因公式打磨到"可评审、可实现"（score = strength × confidence × obs_match、符号传播、DAG、路径排序）。但 L2 不应将算法锁死——企业因果推理未来可能有规则推理、图搜索、贝叶斯网络、LLM reasoning、时序模型等多种算法。

**决策**：L2 定义 **Causal Reasoning Contract**，不定义 Causal Reasoning Algorithm：

```
L2 契约（算法无关）：
  输入：CausalModel（已发布、已实例化）+ Observation（节点观测）+ Evidence（外部证据）
  输出：Cause Ranking（原因排序）+ Evidence Chain（证据链）
  约束：可解释（输出带证据链）、可复现（同输入同输出）、
        可替换（算法经注册接入、可按模型/场景选择）、无副作用

Phase 1 参考实现（默认算法，可替换）：
  符号传播 + 路径排序（score = |∏strength| × ∏confidence × obs_match、
  d'(p)/e(i) 符号积、观测三口径）——九轮评审打磨的公式保留为默认基线，
  但明确标注不约束契约
```

**关键区分**：
- **模型语义契约**（任何算法都需要）：DAG 无环、effect 符号、strength/confidence 字段、实例化规则、可见性——这些仍是 MUST
- **算法实现**（可替换）：原因筛选公式、排序分值、obs_match、观测方向推导——降级为 MUST(默认实现)
- **输出契约**：Cause Ranking + Evidence Chain 成为一等输出，替代原来的"排序报告"表述

**影响范围**：
- §3.1.2 重构为契约层 + 参考实现层；§3.1.3 流程改为契约调用
- D2 决策记录补充"推理算法不绑定"
- §7 L3 方向新增"因果推理算法选型"（规则/图搜索/贝叶斯/LLM/时序），候选算法须满足契约


---

## 22. 架构修订：运行反馈与模型优化闭环（v0.14 → v0.15）

**背景**：§3.4 生命周期契约覆盖"发布后的管理"（版本/审批/回滚），但缺少**运行优化闭环**：实际使用中发现模型不准 → 优化 → 修改 → 升级 → 重新发布，以及"为什么修改"的变更原因管理。

**新增 §3.5 运行反馈与模型优化闭环**：

```
运行消费 → 绩效观测（Execution 埋点 + 用户反馈 + 周期评估）
  → 发现偏差（采纳率骤降 / 评估漂移 / 业务变化导致过时）
  → 触发优化（系统告警 + 人工，记录触发原因）
  → 分支出新版本（携带结构化 change_log：change_type / reason /
    trigger_ref / diff_summary）
  → testing → Publish Approval → 重新发布（变更原因进审批上下文）
  → 旧版本按引用情况处理（有引用保持 published / 无引用可下线）
```

**关键契约**：
- 运行绩效观测：调用量/成功率/采纳率 + 周期评估，按 model_id+version 维度存储
- 三类触发源：运行绩效告警 / 用户反馈 / 业务变化（依赖变更检测）
- **change_log（变更原因管理）**：每版本结构化记录为什么改（performance_drop / user_feedback / business_change / dependency_change / bugfix），随版本快照不可变归档
- 新版本从 published 分支（parent_version），禁止就地改 published
- 滚动升级：消费方检索优先新版本；消费方可固定版本；紧急修复通道（reason=emergency，审批加速审计不减）

**影响范围**：§5 清单新增 #11（observation-spec 绩效埋点）、#12（audit-spec change_log 归档）；§6 路线 Phase 2/3 加入反馈闭环起步与自动化评估。


---

## 23. 架构修订：四个并列二级模块 + Model Governance 子模块（v0.15 → v0.16）

**背景**：① Causal Model / Decision Knowledge / Scenario Template 应为并列二级模块（此前模块树层级不齐）；② 模型治理（问题管理/修改/版本/发布）需要统一归属——用户确认：ECMC 内建治理子模块 + 轻量问题登记（方案 A），不建平台级独立治理中心、不引入外部工单系统。

**决策**：

```
ECMC（一级模块）
├── Causal Model        —— 因果模型（"为什么"）
├── Decision Knowledge  —— 决策知识（"怎么办"）
├── Scenario Template   —— 专家方案模板（"怎么用"，Phase 3+）
└── Model Governance    —— 模型治理（一等子模块）
      ├── 问题管理（§3.4.1）：ModelIssue 登记与流转，驱动优化闭环
      ├── 模型修改（§3.4.2）：分支 / change_log / diff 对比
      ├── 版本管理（§3.4.3）：语义化版本 / 不可变快照 / 回滚
      └── 发布管理（§3.4.4）：testing 准入 / Publish Approval / 滚动升级
```

**关键点**：
- 三个资产模块并列（同层），治理模块作为第四个并列二级模块
- **ModelIssue（问题管理）**：issue_id / model_ref（模型+版本）/ source_type（绩效告警/用户反馈/业务变化/依赖变化/人工）/ severity / status（open→triaged→in_progress→fixed→closed|won't_fix）/ linked_change / timeline；issue 与版本强关联，修复必须产生新版本，change_log 引用 issue_id
- §3.5 定位调整为"绩效观测与优化触发"（治理子模块的感知前端），原 §3.5 中的修改/版本/发布/升级内容归入 §3.4 子节（避免重复）
- D6 决策记录演进：从"不自建治理中心"→"ECMC 内一等治理子模块，横切层仍复用"


---

## 24. 架构修订：ECMC Cognitive Service Contract（v0.16 → v0.17）

**背景**：ECMC 需要从"能力定义"进入"运行时可调用的企业认知服务"。新增 Planner 交互协议章节，评审确认方向后做六项调整，落为 §4.4。

**六项调整（评审采纳）：**

| 调整 | 内容 |
|---|---|
| 协议 → 服务契约 | 定义语义级契约（谁调用谁/为什么/输入输出语义/约束），不绑定 HTTP/gRPC/内存/Event Bus——传输实现 L3 定，避免 L2 被协议锁死 |
| business_objective | 意图四元组增加业务目标（diagnose/predict/optimize/recommend）——同节点不同任务命中不同模型，提升匹配准确度 |
| capability_hint → capability_requirements | 明确 ECMC/Capability 边界：能力需求是模型运行**必需**（含 required 标志），ECMC 不调用，Planner 编排 |
| explain_level | basic（驾驶舱）/ detailed（完整证据链）/ audit（审计级）——满足企业分级解释需求 |
| algorithm → reasoning_mode | L2 不暴露算法：default/fast/explainable/high_accuracy 为意图声明，ECMC 内部选算法（贝叶斯/图搜索/LLM 均内部实现） |
| 增加 422 语义 | 模型存在但输入不足（需 30 天数据只有 3 天）→ "不可处理" + missing_requirements 清单，非"找不到模型" |

**§4.4 结构**：4.4.1 交互定位（Model Discovery + Reasoning Service 两类认知能力）/ 4.4.2 Model Discovery Contract / 4.4.3 Reasoning Contract / 4.4.4 Capability Dependency Contract / 4.4.5 Feedback Contract（为 §3.5 模型演进闭环预留反馈通道）

**闭环链路**：User → Agent Runtime → Planner → ECMC（Discovery → Reasoning → Capability Requirements）→ Capability Center → Enterprise Systems → Observation Feedback → ECMC Model Improvement
