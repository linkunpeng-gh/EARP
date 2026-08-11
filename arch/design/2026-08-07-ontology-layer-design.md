# EARP 本体层（Ontology Layer）初始版本设计

- 日期: 2026-08-07
- 状态: draft
- 关联规范: `arch/L1.5/concept-model-v2.1.md`（§5.9 Business Object、§5.8 Data Domain）、`arch/L2/02-reasoning/knowledge-center-specification.md`（第四章 Ontology）、`arch/L2/03-capability/capability-center-specification.md`（Resolution Engine）

## 1. 背景与目标

### 1.1 背景

知识库技术路线已达成共识（见 2026-08-07 讨论记录）：

```
Phase 1   RAG 打底（文档 → 解析 → chunk → embedding → pgvector 混合检索）—— 即插即用
Phase 2   实体积累层（本设计）—— 知识沉淀，借鉴 gBrain 的 self-wiring / Compiled Truth / Enrichment
Phase 3   图谱推理点缀（LightRAG/LazyGraphRAG 类轻量实现 + EARP Ontology 打通）
```

本设计定义 **Phase 2 的本体层初始版本**：TBox（抽象实体类型 + 逻辑关系类型）人工设计，ABox（实例 + 事实）按热度增量填充。

### 1.1.1 战略定位：EARP 与数据中台分工（2026-08-07 决策）

企业已有数据中台产品（数据抽取、治理、API 开放能力）。据此确定分工边界：

| | 数据中台（数据资产） | EARP（知识资产） |
|:---|:---|:---|
| 数据集成/清洗/分层建模 | ✅ 中台承担 | ❌ 不重复建设 |
| 数据治理（MDM/标准/质量/血缘） | ✅ 中台承担 | ❌ 不重复建设 |
| 指标定义与计算 | ✅ 中台承担（口径统一） | ✅ 只定义指标语义（§4.5） |
| 数据服务 API 开放 | ✅ 中台承担 | ✅ 经 Connector 消费 |
| **语义层（本体/词典/术语）** | ❌ 技术元数据为主 | ✅ **EARP 核心能力** |
| **非结构化知识抽取（文档→知识）** | ❌ 不处理 | ✅ **EARP 核心能力** |
| **知识检索/推理（供 Planner/Agent）** | ❌ | ✅ **EARP 核心能力** |

**一句话**：数据中台提供原料（数据/指标/API），EARP 在其上建设企业语义与知识理解。EARP 重点投入知识资产方向：本体层、业务词典、文档知识抽取、知识检索与推理。

### 1.2 目标

1. 定义第一批核心实体类型与业务关系类型，挂到 Data Domain，形成"知识积累"的骨架
2. 让结构化数据（设备台账、供应商表、组织架构）能以零 LLM 成本批量导入实例
3. 让 Planner / Resolution Engine / Chat 能复用同一套实体知识（三通道检索）
4. 与 concept-model 的 Business Object、L2 Ontology 章节对齐，不重新发明

### 1.3 非目标（明确不做）

- ❌ 不引入图数据库（PostgreSQL + 递归 CTE 覆盖 2-3 跳足够）
- ❌ 不做全量文档图谱抽取（成本陷阱，Phase 2c 只做高频核心实体）
- ❌ 不替代 RAG（实体层是 RAG 的增强通道，不是替代品）

## 2. 设计原则

```
P1  TBox 人工设计，ABox 自动填充
    —— 本体层低频变更（月/季度），实例层高频演进（实时）

P2  关系贴近业务动词，不通用化
    —— manufactured_by / maintained_by / responsible_for 优于泛化的 "关联"

P3  实体类型必须挂 Data Domain
    —— 继承 data_classification，权限感知是硬约束

P4  基础设施最小化
    —— PG 表承载 TBox/ABox，无新组件；图数据库留到 Phase 3 评估

P5  先高频核心，后长尾
    —— 实例按热度增量填充，不做一次性全量

P6  本体层变更必须审批，实例层错误可即时修正

P7  Capability ↔ 实体类型显式关联（capability_entity_map）
    —— "哪个能力操作哪类实体"是一等关系，Resolution Engine 语义增强的基础
```

## 3. 本体层（TBox）初始版本

### 3.1 实体类型清单（第一批，12 类）

覆盖 EARP 演示/测试核心场景（设备故障处理、产线报警、工单、供应链）：

| entity_type_id | 名称 | 说明 | Data Domain |
|:---|:---|:---|:---|
| `equipment` | 设备 | 生产设备/机床 | equipment_data |
| `component` | 部件 | 设备关键部件（主轴/轴承/电机），一级结构不建层级 | equipment_data |
| `production_line` | 产线 | 生产线 | equipment_data |
| `plant` | 工厂 | 工厂/厂区 | corporate_data |
| `sensor` | 传感器 | 设备监测传感器 | equipment_data |
| `alarm` | 报警 | 设备报警事件 | quality_data |
| `work_order` | 工单 | 维修/生产工单 | production_data |
| `material` | 物料 | 原材料/半成品/成品 | supply_chain_data |
| `product` | 产品 | 产品 | production_data |
| `supplier` | 供应商 | 供应商 | supply_chain_data |
| `customer` | 客户 | 客户 | supply_chain_data |
| `employee` | 员工 | 内部员工 | hr_data |
| `department` | 部门 | 组织部门 | hr_data |

> 说明：
> - 首批类型 = concept-model §5.9 Business Object 清单（设备/工单/订单/库存/物料/报警/产线/人员/客户/部门）的收敛子集，去掉了平台自身对象（Session/Execution/Capability 等——那些不属于业务本体）
> - 每个类型在 `entity_types` 表中可扩展 attributes 定义（JSONB schema），如 `equipment` → `{model, serial_no, install_date, status}`
> - `entity_types` 带 `kind` 字段（object | concept | metric）：首批 13 类均为 `object`（业务实体对象）。`concept`/`metric`（如销售额、良率、OEE）是概念/指标类——不参与 facts 三元组、数据来自结构化数据/Capability 调用、可带时间序列；指标类 Phase 2b 按需注册（§4.5）

### 3.2 关系类型清单（第一批，12 类）

贴近业务动词，标注方向、基数、所属语义：

| relation_type_id | 名称 | 源类型 | 目标类型 | 基数 | 示例 |
|:---|:---|:---|:---|:---|:---|
| `located_in` | 位于 | equipment / sensor / production_line | plant | N:1 | CNC-01 → 华东一厂 |
| `belongs_to` | 属于 | equipment / sensor | production_line | N:1 | CNC-01 → A 产线 |
| `manufactured_by` | 由…制造 | equipment | supplier | N:1 | CNC-01 → 上海某精机 |
| `supplied_by` | 由…供应 | material | supplier | N:1 | 轴承 → 某轴承厂 |
| `maintained_by` | 由…维护 | equipment | employee | N:M | CNC-01 → 张工 |
| `responsible_for` | 负责 | employee / department | production_line / equipment / material | N:M | 张工 → A 产线 |
| `produces` | 生产 | production_line / plant | product | 1:N | A 产线 → 产品 X |
| `consumes` | 消耗 | equipment / production_line | material | N:M | A 产线 → 轴承 |
| `caused_by` | 由…引起 | alarm | equipment / sensor / component | N:1 | 高温报警 → CNC-01 / 高温报警 → 主轴轴承 |
| `monitored_by` | 被…监测 | equipment | sensor | 1:N | CNC-01 → 温度传感器 |
| `relates_to` | 关联 | work_order | equipment / material / product | N:M | 工单 WO-001 → CNC-01 |
| `approved_by` | 由…批准 | work_order | employee | N:1 | WO-001 → 车间主任 |

> 说明：
> - **决策（2026-08-07）**：新增 `component` 部件类型（一级结构，不建设备→总成→零件层级），`caused_by` 支持下钻到部件级。部件台账若无现成主数据，Phase 2a 填充率允许偏低，按热度增量补齐。
> - 与 L2 Ontology 章节的 4 种通用关系（has/belongs_to/connects_to/depends_on）兼容：`belongs_to` 直接复用；`located_in`/`maintained_by` 等是 `connects_to` 的业务特化；后续需要时保留 `depends_on` 作为通用兜底
> - 关系可携带执行约束（parallel_allowed / transaction_boundary，与 Capability Graph 同构，Phase 2b 再启用）

### 3.3 BD vs DD 使用边界 + Capability 关联（概念钉死）

**Business Domain（BD）= 业务能力的归属边界（能做什么）；Data Domain（DD）= 知识与数据的归属边界（知道什么）。** 两者平行、N:M 映射，不是包含关系：

| 维度 | BD | DD |
|:---|:---|:---|
| 下辖对象 | Capability | 知识资产：文档 / 词典词条 / 本体实体类型 |
| 约束 | 一个 Capability 只属一个 BD | 每个知识资产必须属一个 DD |
| 治理 | 权限：谁可以调用 | 权限 + data_classification：谁可以查看 |
| 系统形态 | 软概念（business_capabilities.domain 字符串字段） | 硬概念（data_domains 表 + RLS，migration 0005） |
| 为空影响 | 无 Capability 可用 | AI 回答依赖 LLM 自身知识 |

**本设计中实体类型的归属**：实体类型是知识资产 → 挂 **DD**，不直接属于 BD。

**实体类型 ↔ Capability 的显式关联（capability_entity_map）**：

```
Capability（属于 BD）── 操作 ──> 实体类型（属于 DD）
示例：query_equipment_alarm（BD: equipment）── 操作 ──> equipment（DD: equipment_data）
     create_work_order（BD: production）── 操作 ──> work_order（DD: production_data）
     query_supplier_orders（BD: supply_chain）── 操作 ──> supplier（DD: supply_chain_data）
```

**为什么要这张表（三个收益）：**
1. **Resolution Engine 语义增强**：Intent 先做实体识别（"CNC-01 高温报警" → equipment 实例 + alarm 意图）→ 经映射表反查可操作 Capability → 候选集从全库缩小到几类 → 精准路由（替代全库语义匹配硬猜）
2. **能力发现联动**：注册 Capability 时自动推荐可关联实体类型（与 Capability Graph 自动推荐同构）
3. **权限分离校验**：调用权限（BD 维度）与数据查看权限（DD 维度）独立校验——有 `start_equipment` 调用权 ≠ 能看设备手册（confidential）

## 4. 数据层（ABox）结构

### 4.1 实例（entities）

```
entity_id       VARCHAR(64)   — 全局唯一（EARP 生成，防跨系统主键冲突）
entity_type_id  VARCHAR(64)   — 引用 entity_types
name            TEXT          — 显示名（"CNC-01" / "上海某精机"）
business_code   TEXT          — 业务编码属性（设备编码/供应商代码/工单号），可重复（跨类型可同名），建索引支撑业务编码查询
attributes      JSONB         — 类型化属性（model/serial_no/status…）
data_domain_id  VARCHAR(64)   — 引用 data_domains（继承分类等级）
source          VARCHAR(32)   — 来源：manual | import | llm_extract | system
status          VARCHAR(16)   — active | deprecated | merged
```

> **决策（2026-08-07）**：实体 ID 使用 EARP 生成 ID，业务主键（设备编码等）作为 `business_code` 属性保存，避免跨系统主键冲突。

### 4.2 事实（facts，三元组）

```
fact_id           VARCHAR(64)
source_entity_id  VARCHAR(64)  — 主语
relation_type_id  VARCHAR(64)  — 谓词
target_entity_id  VARCHAR(64)  — 宾语
confidence        FLOAT        — 0-1（规则导入=1.0，LLM 抽取<1.0）
source_ref        TEXT         — 证据引用（文档 ID / 导入批次 / capability_call_id）
valid_from        TIMESTAMPTZ
valid_to          TIMESTAMPTZ  — NULL=当前有效（支撑知识时效性）
status            VARCHAR(16)  — active | superseded | revoked
```

### 4.3 事实档案（Compiled Truth，gBrain 借鉴）

对高频实体（设备/供应商/客户）预合成"事实档案"——检索时直接命中档案，替代多次图遍历：

```
entity_profile_id  VARCHAR(64)
entity_id          VARCHAR(64)
profile            JSONB        — 合成事实摘要 {summary, key_facts[], related_entities[], stats{}}
compiled_at        TIMESTAMPTZ
profile_version    INT          — 新证据到达时增量重写（version+1）
```

触发时机：实体相关 facts 变更（新增/失效）时异步重编译；夜间 enrichment 全量巡检。

### 4.4 实体时间线（Timeline / Enrichment 素材）

```
entity_timeline_id  VARCHAR(64)
entity_id           VARCHAR(64)
event_type          VARCHAR(32)  — created | maintained | failed | alarm | order | status_change…
payload             JSONB
occurred_at         TIMESTAMPTZ
source_ref          TEXT         — 来源（audit_logs / executions / 人工录入）
```

回填来源（Enrichment 的天然素材）：
- `audit_logs`：Capability 调用记录 → 实体行为时间线
- `executions`：工单创建/审批/完成 → work_order 时间线
- `capability_calls`：查询热点 → 实体热度排序（指导增量填充优先级）

### 4.5 指标/概念实体（metric / concept，Phase 2b 扩展）

部分业务知识是**指标/概念**而非实体对象，如：销售额、良率、OEE、交货准时率。

| 维度 | 对象实体（object） | 指标/概念（metric / concept） |
|:---|:---|:---|
| 数据来源 | 导入 / 抽取 / 回填，可进 facts 三元组 | 主要来自结构化数据 / Capability 调用 |
| facts 参与 | 是 | 否（数值随时间变化，不存三元组） |
| 查询方式 | 实体检索 + 图谱遍历 | 指标定义（TBox）+ 取数（Capability） |
| 示例 | CNC-01（设备实例） | 上月销售额（月度快照） |

落地：`entity_types.kind` = object | concept | metric；注册 metric 类型时声明取数 Capability（经 capability_entity_map 关联）。

> 注意：指标类问题（如"分析销售额下降原因"）走的是**业务链**——DD 路由 → 指标定义 → Capability 取数，不经过 ABox 三元组。与本文 §7 的纯知识检索链路不同，两者通过 §7.1 第 3 层汇合。

### 4.6 ABox 数据源模式与数据中台对接

**ABox 是统一访问层，不统一存储位置。** 三种来源模式：

| 模式 | 场景 | EARP 是否存数据 | 实现机制 |
|:---|:---|:---|:---|
| **直连（virtual）** | 已有系统/指标 API（情况①） | 不存，只存元数据（实体 ID/类型/访问配置） | 查询时经 Connector 实时取数（Compiled Truth 缓存高频实体） |
| **同步（synced）** | 数据散落多系统（情况②） | 同步主数据/关键事实副本 | 定时导入 / CDC / 联邦查询 |
| **抽取（extracted）** | 报表/文件类知识（情况③） | 物理存储（LLM 抽取 + 人工审核） | Phase 2b 抽取管线 |

**对接数据中台（2026-08-07 决策）**：

```
数据中台（外部）                         EARP（知识层）
┌─────────────────────┐              ┌──────────────────────────┐
│ 指标平台（指标 API）  ──Connector(REST)─▶ metric 类型（§4.5 取数）    │
│ 数仓结果表（DM 层）   ──Connector(DB)───▶ ABox synced 实体（同步副本）│
│ 主数据（MDM）        ──Connector(REST/DB)─▶ ABox virtual/synced 实体 │
│ 数据服务 API         ──Connector(REST)──▶ ABox virtual 实体（实时）  │
└─────────────────────┘              └──────────────────────────┘
      ▲ 数据整理（ETL/建模/指标计算）         ▲ 语义 + 知识 + 检索
      ▲ 全部由中台承担，EARP 不重复            ▲ 中台给原料，EARP 加工成知识
```

**决策指南（synced vs virtual）**：主数据同步（synced），状态/指标数据直连（virtual）；源系统无稳定 API 时用同步。

**必须保留的边界**：
- 情况③（文档知识抽取）永远在 EARP——中台不处理非结构化语义
- 无中台场景兜底——三种模式全部支持，CSV/文件导入（§6）作为兜底路径

## 5. 存储设计（PostgreSQL 表草案）

新增 7 张表（全部 tenant-scoped + RLS，与 0001_baseline 模式一致）：

| 表 | 类型 | 说明 |
|:---|:---|:---|
| `entity_types` | TBox | 实体类型定义（含 kind: object/concept/metric、attributes JSONB schema、owner、status） |
| `relation_types` | TBox | 关系类型定义（source/target 类型、基数、status） |
| `capability_entity_map` | TBox | Capability ↔ 实体类型关联（§3.3） |
| `entities` | ABox | 实例 |
| `facts` | ABox | 事实三元组 |
| `entity_profiles` | ABox 派生 | Compiled Truth 档案 |
| `entity_timeline` | ABox 派生 | 时间线事件 |

capability_entity_map 结构：

```
capability_id     VARCHAR(64)  — 引用 business_capabilities
entity_type_id    VARCHAR(64)  — 引用 entity_types
operation         VARCHAR(16)  — read | write | both（该能力对实体的操作性质）
status            VARCHAR(16)  — active | deprecated
```

索引：`(capability_id)`、`(entity_type_id)`——两向查询（能力→类型 / 类型→能力）。

索引要点：
- `facts`：`(source_entity_id, relation_type_id)`、`(target_entity_id)`、`(relation_type_id, target_entity_id)`——递归 CTE 多跳遍历的支撑
- `entities`：`(entity_type_id, data_domain_id)`、`name` 前缀匹配索引
- `facts.valid_to` 参与 WHERE 过滤（只查当前有效事实）
- 全部表 `ENABLE ROW LEVEL SECURITY` + tenant_isolation policy（复用 0001 的既有模式）

> 递归 CTE 多跳示例（"A 产线使用的轴承由哪些供应商供应"）：
> ```sql
> WITH RECURSIVE hops AS (
>   SELECT e.entity_id, r.relation_type_id, t.entity_id AS hop
>   FROM entities e
>   JOIN facts f ON f.source_entity_id = e.entity_id AND f.valid_to IS NULL
>   JOIN relation_types r ON r.relation_type_id = f.relation_type_id
>   JOIN entities t ON t.entity_id = f.target_entity_id
>   WHERE e.name = 'A产线' AND r.relation_type_id = 'consumes'
>   UNION ALL
>   SELECT h.hop, f.relation_type_id, f.target_entity_id
>   FROM hops h JOIN facts f ON f.source_entity_id = h.hop AND f.valid_to IS NULL
>   WHERE depth < 3
> )
> -- 终止条件：relation_type_id = 'supplied_by' 时收集 target 为 supplier
> ```
> 2-3 跳以内用 CTE 足够；深度遍历需求出现后再评估图数据库。

## 6. 数据填充策略（按热度增量）

### Phase 2a — 对接数据中台 + 结构化导入（零 LLM，零幻觉）

**优先路径（有数据中台）**：中台数据源注册为 ABox 实体——主数据走 synced 同步，指标/数据服务走 virtual 直连（§4.6），无需 EARP 建表更新。

**兜底路径（无中台/无法对接）**：

| 数据源 | 目标实体类型 | 导入方式 |
|:---|:---|:---|
| 设备台账（CSV/Excel/API） | equipment / sensor / production_line / plant | 批量导入 + 规则生成 located_in/belongs_to/manufactured_by |
| 供应商/客户表 | supplier / customer | 批量导入 + supplied_by |
| 组织架构 | department / employee | 批量导入 + belongs_to / responsible_for |
| 物料/产品主数据 | material / product | 批量导入 + produces / consumes（人工勾选映射） |

验收：核心实体类型实例覆盖 ≥ 70%（按主数据行数），facts 全部 confidence=1.0。

### Phase 2b — 经验文档 LLM 抽取（受控）

```
文档 → LLM 抽取候选实体/事实（confidence < 1.0）→ 人工审核队列（status=pending）
     → 审核通过 → facts 落库（status=active）
     → 审核驳回 → 丢弃（记入抽取质量日志，反哺 Prompt）
```

约束：只处理高频核心实体类型（首批 12 类），不扩展新类型（新类型走 TBox 审批流程）。

### Phase 2c — Enrichment 定时任务

```
夜间任务（复用 scheduler/任务队列）：
  1. audit_logs / executions → entity_timeline 回填
  2. 热度统计 → 未覆盖的高频实体标记，进入 Phase 2b 候选
  3. 失效事实清理（valid_to 过期）
  4. entity_profiles 增量重编译
```

## 7. 检索集成（三层流水线 + 三通道）

### 7.1 完整检索流水线

**DD 路由（空间裁剪）在前，Ontology 导航 + 文档检索并行，结构化数据（Capability）作为第三通道。DD 与 Ontology 是正交维度，必须同时使用——DD 决定"去哪找"，Ontology 决定"按什么线索找"。**

```
用户问题
  │
  ├─ 第 1 层 — DD 路由（空间裁剪）
  │    实体/意图识别 → Business Dictionary 消歧 → 命中一个或多个 Data Domain
  │    → 检索空间从全库缩小到域内（跨域查询按 v2.1 支持）
  │
  ├─ 第 2 层 — 知识检索（域内并行）
  │    ├─ 通道 A: Ontology 导航 —— TBox 找关系链 → ABox 取事实（递归 CTE 多跳）
  │    ├─ 通道 B: vector 检索 —— 文档 chunks（RAG 现有）
  │    └─ 通道 C: keyword —— BM25/tsvector（现有）
  │
  ├─ 第 3 层 — 结构化数据（业务链，可选）
  │    需要数字/明细时 → capability_entity_map 反查 Capability → 调用取数
  │
  ↓
三通道结果 → RRF 融合 → 图谱多跳扩展 → 合成回答（带引用）
```

### 7.2 完整示例：设备故障分析

> 用户问："华东一厂的 CNC 设备主轴轴承为什么最近故障率高？"

```
第 1 层 — DD 路由
  "CNC / 主轴轴承" → 实体识别 → equipment_data 域
  "故障 / 报警" → quality_data 域
  → 跨域检索：equipment_data + quality_data

第 2 层 — Ontology 导航 + 文档检索（并行）
  TBox 导航链：
    Alarm(报警) —caused_by→ Component(主轴轴承) —belongs_to→ Equipment(CNC-01)
    Equipment —located_in→ Plant(华东一厂)
    Equipment —supplied_by→ Supplier(轴承供应商)     ← 关键线索：供应商
  ABox 取证：
    高温报警 ×12（本月）→ CNC-01 → 主轴轴承           ← timeline 佐证"最近"
    主轴轴承 —manufactured_by→ 新供应商（上月初变更）  ← 图谱发现关联变化
  RAG 文档：设备维护手册、近期维修记录 chunks

第 3 层 — 结构化数据（可选增强）
  需要精确数字 → query_alarm_history（BD: equipment）→ 报警时间线统计

合成：图谱给因果链（供应商变更 → 轴承质量 → 报警上升），
      文档给背景，Capability 给数字 → 带证据的分析回答
```

**为什么选这个例子**：
- 纯知识检索问题（答案在企业知识里，Capability 只是可选增强）——聚焦 DD 路由 + Ontology 导航的组合
- 实体是业务实体对象（非指标概念），ABox 直接取证
- 展示图谱独特价值：多跳导航 + 发现"供应商变更"这类关联变化
- 展示 DD 跨域路由（equipment_data + quality_data）
- 指标类问题（如"销售额下降原因"）见 §4.5——走业务链取数，与本链路不同，在 §7.1 第 3 层汇合

### 7.3 集成点

- **Resolution Engine**：经 capability_entity_map 反查——Intent 实体识别后（"CNC-01 高温报警" → equipment + alarm）→ 反查可操作实体类型的 Capability → 缩小候选集后语义匹配（§3.3）
- **Planner**：Intent 解析阶段先做实体识别（"CNC-01 的高温报警" → 实体 + 意图），利用 Business Dictionary + 实体索引
- **Chat/Agent**：三层流水线（§7.1）RAG 检索
- **Conversation**：实体作为会话上下文持久化（Session Context 中带 entity_refs）

## 8. 治理机制

| 治理项 | 规则 |
|:---|:---|
| TBox 变更（新增实体类型/关系类型） | 必须审批（owner 团队 + 管理员），变更记录进 audit_logs |
| TBox 版本 | entity_types/relation_types 带 version + status（draft/active/deprecated） |
| 实例纠错 | 实例/facts 支持 superseded/revoked，修正留痕 |
| 权限 | 实体/事实继承 data_domain 的 data_classification；RLS 按 tenant 隔离；查询时按用户角色过滤可访问 Data Domain |
| 数据质量 | 事实 confidence < 1.0 需人工审核；抽取质量指标回传 Evaluation Center |

## 9. 演进路线与验收标准

```
Phase 2a（结构化导入）   → 验收：实体查询准确率、零 LLM 成本建图
Phase 2b（LLM 抽取）     → 验收：审核通过率、抽取精度（实体/关系）
Phase 2c（Enrichment）   → 验收：时间线覆盖、档案新鲜度
Phase 3（图谱推理）      → 仅对多跳/关联问题启用（LightRAG/LazyGraphRAG 评估）
```

**先行验收指标（Phase 2a 完成时）：**
1. 核心实体类型实例覆盖 ≥ 70%
2. 三通道检索对"实体类问题"的 P@5 高于纯 vector 基线（目标 +10 分以上）
3. 事实档案（Compiled Truth）命中即可回答的问题占比（无需 LLM 合成）

## 10. 影响分析

| 项 | 变更 |
|:---|:---|
| 数据库 | 新增 migration 0007：7 张表 + RLS policy + 索引 |
| 规范 | knowledge-center-spec Ontology 章节需细化（实体/事实表结构、capability_entity_map、Compiled Truth、Timeline） |
| Knowledge Center | 新增 Ontology Service（TBox/ABox CRUD + 检索 + 档案编译） |
| Knowledge 页面 | Data Domains 页面可扩展实体类型管理入口（Phase 2b） |
| Capability Center | Capability 注册/编辑时关联实体类型（capability_entity_map 维护） |
| Business Dictionary | 词条 mapped_entity 与 entity_type_id 打通（术语 → 类型 → 实例） |
| 不影响 | RAG 现有链路、Runtime 状态机 |

## 11. 开放问题

1. ~~实体 ID 规范~~ ✅ **已决策（2026-08-07）**：EARP 生成 ID，业务主键作为 `business_code` 属性（见 §4.1）
2. ~~是否需要 component~~ ✅ **已决策（2026-08-07）**：新增 `component` 一级部件类型（不建层级），`caused_by` 支持设备/传感器/部件级（§3.1、§3.2）
3. ~~档案重编译时机~~ ✅ **已决策（2026-08-07）**：定时批量（夜间）+ 高频实体变更即时重编（§4.3）
4. RRF 三通道权重：实体通道命中是否加权——**留待 Phase 2a POC 小实验确定**（§7）
5. ~~Capability ↔ 实体类型关联是否建~~ ✅ **已决策（2026-08-07）**：建 `capability_entity_map` 关联表（§3.3、§5）
6. ~~DD 路由与 Ontology 导航如何组合~~ ✅ **已决策（2026-08-07）**：同时使用，三层流水线——DD 空间裁剪 →（Ontology 导航 + RAG 检索）→ Capability 结构化数据（§7）
