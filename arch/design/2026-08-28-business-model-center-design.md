# EARP Business Model Center（业务模型中心）架构设计

- 日期: 2026-08-28
- 状态: v0.4 — 第三轮对抗性评审修订（9 条：P1×5、P2×4，处置记录见 §11）
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

```
MUST: 节点只引用 TBox 已注册的实体类型/metric 类型；未注册先走 TBox 审批
MUST: 发布状态才能被 Planner 检索；draft/testing 对消费方不可见
MUST: 因果边登记为 TBox causal 命名空间关系类型（schema 扩展见 §3.1.5）
MUST: 图为有向无环图（DAG）；编译期做环路检测，含环模型不可发布
MUST: 边带 effect 符号（+/-）；方向约定：effect 表示源节点取值上升时
      对目标节点的影响方向（+ 同向、- 反向）

      原因筛选公式（显式定义）：
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
MUST: 归因排序分值（Phase 1 契约，可评审可替换）：
      score(path) = |∏ strength| × ∏ confidence；节点聚合取其全部
      入径的最高分路径；同一原因节点正负路径并存时，分别列出
      两条解释并标注"方向冲突待数据裁决"，不做静默合并
MUST: 发布时强制补齐边字段——每条边必须声明 strength 与 confidence
      （默认值：strength=0.5、confidence=0.5，显式声明者优先），
      保证排序公式对 published 模型恒有定义
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

案例："为什么 3 号矿产量下降？"

```
Planner 定位 entry_point 节点（产量下降，direction=down）
  → 匹配已发布 CausalModel
  → 沿因果边反向遍历，按筛选公式 d'(p) = d × S(p) 换算每条路径的
    解释方向（反向原因链合法入选，如"设备老化↑ → 健康度↓ → 产量↓"）
  → 因果模板实例化：object 节点沿 KB ABox 结构关系展开
    （"3 号矿的设备"）；metric 节点按 instance_binding 绑定
    （产量 × 3 号矿 × 近 30 天）
  → 按节点 data_requirement 生成数据获取 Step → 经 capability_binding 绑定 Capability
  → 汇总证据，按 score(path) = |∏ strength| × ∏ confidence 排序
    → 输出原因排序报告（候选原因携带 d'(p) 方向标注）
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
instance_binding 受限表达式（L2 契约，语法固定为三段式，禁止任意代码）：
  $target_entity                          — 推理目标实体
  $target_entity.<relation>[.in|.out]     — 沿单一结构关系按方向展开
                                            （一步）：
                                            .in  = 沿入边（target_entity
                                                   是关系目标），
                                            如 $target_entity.belongs_to.in
                                                   → 其父节点
                                            .out = 沿出边（target_entity
                                                   是关系源），
                                            如 $target_entity.belongs_to.out
                                                   → 其子节点
  $target_entity.<relation>.<dir>.<entity_type>
                                          — 展开后按实体类型过滤
  （说明：默认方向 = 出边 .out；entity_type 过滤的是展开结果中
    非目标一侧的实体类型。例：从"3 号矿"取设备 =
    $target_entity.located_in.in.equipment（矿是 located_in 目标）
    约束：
    MUST: relation 仅允许 TBox structural namespace 中已注册关系
    MUST: 展开上限 2 跳（性能与爆炸防护）
    MUST: 展开结果按双层权限模型过滤（展开越权实体视为无权限，
          不报错、不返回）
    SHOULD: 展开结果超过 100 实例时要求模型作者显式声明聚合策略

双数据通道优先级：
  MUST: 节点同时声明 capability_bindings[] 与 data_requirement 时，
        data_requirement 为主（它携带取数/映射/聚合完整契约），
        capability_bindings 为辅助路由信息；两者指向的 Capability
        必须一致，不一致为编译期错误
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

因此 causal 侧登记需 schema 扩展，**在 L3/BMC 落地前完成**：

```
MUST: relation_types 新增 namespace 列（'structural' | 'causal'，
      默认 'structural'——存量行为不变）
MUST: namespace='causal' 的关系类型仅允许出现在 CausalModel.edges.relation_type_ref，
      ABox facts / QU 关系候选 / 导入映射必须排除 causal namespace
MUST: 现有 caused_by 保持 structural 语义不变（事件归因事实），
      BMC 因果影响边使用新增 causal 类型（如 influences），不复用 caused_by
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
         白名单内 adapter 类型执行（L3 定清单）；
      c) 只读属性由 Orchestrator 从 Capability 注册表推导，不信任
         Step 自带标记——Planner 生成前置 Step 时写入
         capability_id 引用，Orchestrator 查注册表 type=query
         才放行；Connector adapter 执行边界强制校验
         （执行层仅允许白名单 adapter 且校验注册表 type），
         恶意/有误 Planner 标注 read_only=true 亦无法绕过
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
MUST: 与 Policy Center 分工——BMC 规则是业务性"怎么办"，
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
SHOULD: 规则支持组合（AND / OR / NOT，与 Decision Engine §3.1 一致）
```

#### 3.2.2 消费路径（三条）

| 消费方 | 用法 |
|---|---|
| Planner | DecisionObjective + ConstraintSet 注入规划上下文，用于 Goal 分解与 Plan 生成；scope=planner 规则的 capability_call 条件生成为前置 Step |
| Decision Engine | 执行时分支选择从已发布 DecisionRule（scope 含 execution）读取（规则资产化，替代散落代码/配置）；condition.source 仅 metric_ref / context |
| Scheduler / Workflow | BMC 将 EventTaskMapping 生命周期发布为事件：`earp.bmc.mapping.published`（创建/更新 trigger）、`earp.bmc.mapping.deprecated`（停用 trigger）、`earp.bmc.mapping.rolled_back`（指向回滚目标版本快照，Scheduler 据此更新 trigger）；事件携带 `mapping_id + mapping_version`；Scheduler 按版本号比较后应用（乱序到达不生效旧版本），并以定时对账任务（对比 BMC 侧已发布版本 vs Scheduler 侧 trigger 版本）兜底不一致（修订 P1-4 乱序）；BMC 不主动注册 trigger（修订 P2-13），执行走 Workflow。Scheduler 侧幂等：事件重复消费不重复建 trigger |

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

**状态机与转换（修订 P1-8）：**

```
状态: draft → testing → published → deprecated

允许的转换:
  draft → testing      （准入：结构校验通过——DAG 无环、引用完整、
                        output_mapping 齐备；无 testing 需求可直接 draft → published）
  testing → published  （准入：回测报告产出（SHOULD）；依赖完整性校验通过）
  testing → draft      （回测不达标退回）
  published → deprecated（下线）
  deprecated → published（重新启用，仅当依赖仍完整）

禁止: published → draft（不允许就地降级，新修改走新版本）
```

**依赖完整性校验（发布时 MUST，含引用对象下线的持续保障）：**

```
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

**版本与回滚（修订 P1-8）：**

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

**发布审批（修订 P1-9）：**

现状核对：Policy Center 绑定目标为 Capability/Domain/Role/Tenant，
approval 是 Execution 等待语义——**不支持模型资产内容审批**。因此：

```
MUST: BMC 发布审批为独立审批流（Publish Approval），
      Policy Center 需新增策略目标类型 "model_asset"（改动项见 §5），
      审批对象 = 模型资产版本快照 + 变更 diff
MUST: 审批通过才进入 published；审批记录走 Audit Spec
SHOULD: 支持「发布者 ≠ 审批者」分离（专家编辑 / 管理者审核，与 TBox P6 同构）
```

---

## 4. 消费方集成契约

### 4.1 Planner ← BMC（最重集成点）

```
触发: Goal Generation / Domain Routing 阶段
调用: 模型检索（entry_point 语义匹配 + applicability 过滤 +
      角色可见域过滤；多模型命中按 §3.1.2 消歧）
返回: 已发布 CausalModel 候选集（含节点/边摘要 + 版本号）

后续:
  → 因果归因类意图: 沿因果边反向遍历（符号积过滤）→ 按节点
    data_requirement（§3.1.4）生成数据获取 Step → 经 capability_binding
    绑定 Capability → 纳入 Plan
  → 决策类意图: 注入 DecisionObjective + ConstraintSet → Goal 分解；
    scope=planner 规则的 capability_call 条件生成前置 Step
  → （Phase 3+）场景类意图: 匹配 ScenarioTemplate → 实例化为 Workflow
```

```
MUST: 只检索 published 状态
MUST: 返回模型版本号（Planner 在 Execution Trace 中记录，保证可复现）
```

### 4.2 Decision Engine ← BMC

```
触发: 执行时分支 Step
调用: 按 data_domain + entity_type 检索已发布 DecisionRule（scope 含 execution）
行为: Rule → LLM → ML 优先级不变，BMC 是规则的新来源之一；
      condition.source 仅 metric_ref / context（capability_call 由
      Planner 前置 Step 化，见 §3.2）——Rule-based ≤ 100ms 契约不变
```

### 4.3 与 KB 的双向关系（D1 落地）

```
共治 TBox: ontology 域物理不动，KB 与 BMC 都是消费方；
          causal 侧关系类型登记入 TBox 词汇表（namespace 扩展见 §3.1.5）

KB → BMC: 实例化时提供实体实例（ABox 沿 belongs_to / located_in 展开）

BMC → KB（假设性知识闭环，修订 P1-6，评审决策：方案 b；
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
  ├── assertion: string          — 断言文本（"疑似主轴承老化"）
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
```

---

## 5. L2 规范改版清单

| # | 文档 | 改动 | 优先级 |
|---|---|---|---|
| 1 | 新建 `arch/L2/02-reasoning/business-model-center-specification.md` | BMC 主规范（本文设计的契约化落盘） | P0 |
| 2 | `knowledge-center-specification.md` v1.2 → v1.3 | 第四章 Ontology 标注"TBox 与 BMC 共治"；ABox 增补 hypothesis_facts 候选表契约（BMC 假设回写通道，方案 b） | P0 |
| 3 | `planner-specification.md` | 新增"BMC 知识源"章节：模型检索、因果遍历、决策知识注入、capability_call 前置 Step 化 | P0 |
| 4 | `decision-engine-specification.md` v1.0 → v1.1 | §3.1 增补"BMC DecisionRule 为规则来源之一（scope=execution）"；条件源约束（metric_ref/context） | P1 |
| 5 | `concept-model-v2.x` | 新增 CausalModel / DecisionKnowledge / ScenarioTemplate 概念对象 | P1 |
| 6 | `scheduler-specification.md` | 新增"订阅 earp.bmc.mapping.published 创建/更新 trigger"说明；EventTaskMapping 触发语义（边沿/电平、评估频率）对齐 | P1 |
| 7 | `workflow-specification.md` | task_template / ScenarioTemplate 实例化的编排依据说明 | P2 |
| 8 | `eventbus-specification.md` v1.1 → v1.2 | 新增业务事件类型注册表；`earp.bmc.mapping.published / deprecated / rolled_back` 事件类型 | P1 |
| 9 | `policy-center-specification.md` | 新增策略目标类型 model_asset（BMC 发布审批） | P1 |
| 10 | migration（代码侧，L3 前瞻） | relation_types 加 namespace 列 + status 扩展 draft；hypothesis_facts 表；既有 QU 校验/导入/understanding 排除 causal namespace | P0 |

代码侧（L3 前瞻，不入本文）：新增 `earp_server/bmc/` 域；import-linter 新增契约；`ontology/` 域不迁移。

---

## 6. 实施路线建议

```
Phase 1  CausalModel + 决策知识核心（DecisionRule / EventTaskMapping）
         + 生命周期状态机（含 Publish Approval）+ Planner 因果归因链路
         + 前置基础设施（relation_types namespace 扩展、事件类型注册表、
           model_asset 策略目标）——最小闭环："为什么产量下降"端到端跑通
Phase 2  DecisionObjective / ConstraintSet 注入 Planner；
         BMC → KB hypothesis_facts 回写闭环；Industry Pack 工具化
Phase 3  ScenarioTemplate + Planner 场景匹配 + 实例化编译
```

排序依据：因果归因是 BMC 净增值最高、可独立验证的链路，先跑通；决策知识先落规则与事件映射（对 Workflow 编排的依据价值立即兑现）；场景模板价值依赖消费链路，最后落地。

---

## 7. 后续 L3 设计方向

1. **模型元数据物理模型**：BMC 各对象的表结构（PG 承载，沿用"基础设施最小化"原则，图数据库留待多跳推理需要时评估）
2. **因果图引擎**：图存储（递归 CTE vs 图数据库）、图查询、因果遍历算法、实例化展开规则
3. **Planner 集成实现**：entry_point 语义匹配（复用 Semantic Index）、模型选择、因果遍历 → Plan 生成的映射
4. **FDE 建模工具**：拖拽编辑器、节点配置、发布流程（对接 Policy 审批）
5. **回测机制**：testing 阶段的 strength/lag 校准、DecisionRule 回测、testing 准入/退出标准的量化定义
6. **Industry Pack 格式**：导出/导入 schema、冲突检测算法、ID 映射与重复导入幂等性、发布时 dependency 完整性校验同 §3.4
7. **多跳因果聚合算法**：Phase 1 已定义基础契约（score = |∏ strength| × ∏ confidence，§3.1.2）；L3 细化重叠路径去重、路径冲突的数据裁决、强度衰减函数
8. **Publish Approval 审批流实现**：审批对象（版本快照 + diff）、审批人路由（owner 角色）、与 Policy Center model_asset 目标类型的对接

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
