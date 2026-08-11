# Knowledge Center Specification

## EARP 知识中心规范

**文档编号：L2-02-KNOWLEDGE**  
**版本：v1.2**  
**定位：L2 — 平台规范。本文定义 Knowledge Center 的契约，负责企业知识的建模、存储、检索与注入。**  
**依赖：L0/design-philosophy.md, L1/architecture-v5.md, L1.5/concept-model-v1.3.md, L2-01-runtime/runtime-specification.md, L2-11 knowledge-base-specification v1.1（双层访问模型）**

> **v1.2 变更（2026-08-07）**：第四章 Ontology 重构为 TBox/ABox 双层（实体类型 kind、三种数据源模式、Compiled Truth/Timeline/Enrichment、capability_entity_map）；新增 §4.6 数据中台对接（EARP 聚焦知识资产）；§3.4 检索权限对齐双层模型。实现细节见 arch/design/2026-08-07-ontology-layer-design.md。

> **v1.1 变更（2026-07-18）**：§3.3 "MUST: 异步处理（Celery 任务）" 改为 "MUST: 异步处理（任务队列）"——队列实现选型属 L3 实现细节，不入规范层（tech-stack-analysis-v1 评审 P0-1 修复；当前选型见 arch/design/tech-stack-analysis-v1.md D6）。

---

# 第一章：概述

## 1.1 定位

Knowledge Center 是 EARP 的**知识基础设施层**。它不等于 RAG——RAG 只是 Knowledge Center 的一种能力。

知识服务于四个消费者：

| 消费者 | 知识用途 |
|--------|---------|
| Intent Planner | Business Dictionary 术语映射 |
| Task Planner | Ontology 关系推理 |
| Agent / Chat | RAG 文档检索 |
| Resolution Engine | Capability Metadata 语义索引 |

### 明确边界

**负责：**
- 企业术语统一映射
- 文档知识检索（RAG）
- 对象关系模型（Ontology）
- 语义索引
- Prompt 模板管理

**不负责：**
- ❌ 执行推理（Planner 负责）
- ❌ 保存运行时状态（Memory 负责）
- ❌ 保存执行产物（Artifact Center 负责）

## 1.2 范围

| 模块 | 说明 | 章节 |
|------|------|------|
| Business Dictionary | 企业术语统一映射 | 第二章 |
| RAG | 文档知识库 | 第三章 |
| Ontology | 企业对象关系模型 | 第四章 |
| Semantic Index | 语义索引层 | 第五章 |
| Capability Metadata | 能力搜索索引 | 第六章 |
| Prompt Library | Prompt 模板管理 | 第七章 |
| 知识生命周期 | 流入/流出/闭环 | 第八章 |

---

# 第二章：Business Dictionary

## 2.1 定位

Intent Planner 最核心的依赖。解决"用户说的和系统理解的不一致"。

## 2.2 词条结构

```
MUST: 每个词条包含
  - term:              string    — 原始术语
  - language:          string    — 语言（如 "zh-CN"）
  - mapped_entity:     string    — 映射的标准实体
  - mapped_domain:     string    — 映射的业务领域
  - data_domain:       string    — 所属 Data Domain（v2.1 新增，MUST）
  - synonyms:          list[str] — 同义词（SHOULD）
  - context_rules:     list[ContextRule] — 上下文消歧规则（SHOULD）

MUST: ContextRule 包含 context_key、context_value、mapped_entity
```

示例：

```yaml
- term: "异常"
  language: "zh-CN"
  mapped_entity: "Alarm"
  mapped_domain: "equipment"
  synonyms: ["报警", "告警", "故障"]
  context_rules:
    - context_key: "domain"
      context_value: "quality"
      mapped_entity: "Defect"
    - context_key: "domain"
      context_value: "equipment"
      mapped_entity: "EquipmentAlarm"

- term: "工单"
  language: "zh-CN"
  mapped_entity: "WorkOrder"
  mapped_domain: "production"
  synonyms: ["维修单", "任务单"]
```

## 2.3 契约

```
MUST: Intent Planner 使用 Business Dictionary 进行术语映射
SHOULD: 至少覆盖 100+ 企业术语（Phase 1）
SHOULD: 未匹配术语记录到 Unknown Term 日志
SHOULD: 支持批量导入（CSV/JSON）
MUST: 同义词搜索支持模糊匹配
```

---

# 第三章：RAG

## 3.1 定位

基于企业文档的知识检索，适用于 Chat/Agent 的知识问答。

## 3.2 数据源

```
MUST: 支持 PDF / Word / Excel / Markdown / CSV / 纯文本
SHOULD: 支持数据库表 / API 返回 / 网页抓取（Phase 2+）
```

## 3.3 索引流程

```
文档上传 → 提取 → 清洗 → 分割 → Embedding → 存入向量数据库
```

```
MUST: 异步处理（任务队列）
MUST: 按文档类型选择提取器
SHOULD: 分割策略可配置（chunk_size / overlap）
MUST: 使用统一的 Embedding Provider
MUST: 文档索引时标注所属 Data Domain（v2.1 新增）
```

## 3.4 检索

```
MUST: 支持向量检索 / 关键词检索 / 混合检索
SHOULD: 检索结果按相关性排序，支持 Top-K
SHOULD: 结果附带来源引用
MUST: 检索接口支持 data_domain 参数，按域过滤检索空间（v2.1 新增）
SHOULD: 支持多 Data Domain 并行检索（跨域查询）
```

> **v1.2**：检索权限为双层模型——data_domain 过滤 + data_classification 天花板 + 行级角色，见 L2-11 knowledge-base-specification v1.1 §2.1.1。

---

# 第四章：Ontology（v1.2 重构为 TBox / ABox 双层）

## 4.1 TBox — 本体层（抽象实体类型 + 关系类型）

```
MUST: 实体类型（entity_type）包含
  - entity_type_id:  string       — 全局唯一
  - name:            string       — 中文名称
  - kind:            "object" | "concept" | "metric"（v1.2 新增）
  - description:     string       — 业务描述
  - data_domain_id:  string       — 所属 Data Domain（MUST，实体类型是知识资产）
  - attributes:      JSONSchema   — 属性定义（SHOULD）
  - status:          "draft" | "active" | "deprecated"

MUST: 关系类型（relation_type）包含
  - relation_type_id: string       — 全局唯一
  - name:             string       — 业务动词（manufactured_by / maintained_by…）
  - source_type:      string       — 源实体类型
  - target_type:      string       — 目标实体类型
  - cardinality:      "1:1" | "1:N" | "N:M"
  - status:           "active" | "deprecated"

MUST: 实体类型归属 Data Domain，不直接归属 Business Domain
  （BD 通过 Capability 关联：Capability 属 BD，经 capability_entity_map 操作实体类型）
SHOULD: 关系类型贴近业务动词，而非泛化的 "关联"
MAY: 关系可携带执行约束（parallel_allowed / transaction_boundary，与 L2-03 Capability Graph 同构）
```

## 4.2 ABox — 数据层（实例 + 事实，三种来源模式）

```
MUST: 实体实例（entity）包含
  - entity_id:        string    — EARP 生成，全局唯一
  - entity_type_id:   string    — 引用 TBox 类型
  - name:             string    — 显示名
  - business_code:    string    — 业务编码属性（设备编码/供应商代码），可重复
  - attributes:       JSONB     — 实例属性
  - source_mode:      "virtual" | "synced" | "extracted"（v1.2 新增）
  - source_ref:       string    — 来源引用（connector 配置 / 导入批次 / 文档 ID）
  - data_domain_id:   string    — 继承分类等级
  - status:           "active" | "deprecated" | "merged"

MUST: 事实（fact，三元组）包含
  - fact_id / source_entity_id / relation_type_id / target_entity_id
  - confidence:       FLOAT     — 规则导入=1.0，LLM 抽取<1.0
  - source_ref:       string    — 证据引用（文档/导入批次/capability_call_id）
  - valid_from / valid_to       — valid_to=NULL=当前有效
  - status:           "active" | "superseded" | "revoked"

ABox 三种来源模式（v1.2 新增）：
  virtual   — 不存数据，经 Connector 实时取数（已有系统/指标 API）
  synced    — 同步外部数据副本（主数据，定时/CDC）
  extracted — EARP 物理存储（文档 LLM 抽取 + 人工审核）

MUST: 查询按 source_mode 分派（extracted/synced 读表，virtual 经 Connector 实时取数）
MUST: 实例/事实权限 = DD classification 天花板 + 行级角色（同 L2-11 双层模型）
```

## 4.3 知识积累机制（v1.2 新增）

```
MUST: 实体事实档案（Compiled Truth）
  - 高频实体预合成事实档案（entity_id / profile JSONB / compiled_at / profile_version）
  - 检索直接命中档案，替代多次图遍历
  - 触发：事实变更时增量重编译 + 定时巡检
SHOULD: 实体时间线（Timeline）
  - audit_logs / executions / capability_calls 回填实体行为历史（event_type / payload / occurred_at）
SHOULD: Enrichment 定时任务
  - 热度统计 → 指导增量填充优先级；失效事实清理；档案重编译
```

## 4.4 Capability 关联（v1.2 新增）

```
MUST: capability_entity_map — Capability ↔ 实体类型显式关联
  - capability_id / entity_type_id / operation（read|write|both）/ status
MUST: Resolution Engine 可用该映射反查收窄候选集（Planner spec §5.1.5）
MUST: 调用权限（BD 维度）与数据查看权限（DD 维度）独立校验
```

## 4.5 演进

```
Phase 1: 对象目录 + 关系表（PostgreSQL）              ← 已完成（v1.1 及之前）
Phase 2: TBox/ABox 双层 + 三种来源模式 + 知识积累机制   ← 本设计（2026-08-07）
Phase 3: 图推理（图数据库 + Graph RAG，仅多跳场景）
```

## 4.6 数据中台对接（v1.2 新增）

```
战略定位：EARP 与数据中台分工——
  数据中台：数据抽取 / 清洗 / 建模 / 治理 / 指标计算 / API 开放（数据资产）
  EARP：    语义层 / 非结构化知识抽取 / 知识检索推理（知识资产）

对接方式（ABox 数据源）：
  指标平台 API → metric 类型（virtual，经 Connector）
  数仓结果表   → synced 实体（同步副本）
  主数据 MDM   → virtual / synced 实体
  数据服务 API → virtual 实体（实时）

MUST: EARP 不重复建设数据整理（ETL / 数仓 / 指标计算归数据中台）
MUST: 无中台场景兜底——CSV / 文件导入（extracted / synced）仍支持
```

---

# 第五章：Semantic Index

统一的语义索引层，为 Capability Discovery 提供 Embedding 支持。

```
SHOULD: 为 Capability / Business Dictionary / Ontology 建立 Embedding
MUST: 使用统一的 Embedding Provider
SHOULD: 数据更新时自动重建
```

---

# 第六章：Capability Metadata

Capability 注册时的副产品，为 Resolution Engine 提供搜索索引。

写入：Capability Center 注册时自动写入
读取：Resolution Engine 检索

---

# 第七章：Prompt Library

## 7.1 模板结构

```
SHOULD: 每个模板包含
  - prompt_id:     string    — 标识
  - template:      string    — Prompt（含变量占位符）
  - variables:     list[str] — 变量列表
  - version:       string    — 版本号
```

## 7.2 契约

```
SHOULD: 支持版本管理和 A/B 测试
```

---

# 第八章：知识生命周期

## 8.1 知识流入流出与闭环

```
流入：
  Business Dictionary: 手动录入 + 批量导入 + 未匹配术语自动记录
  RAG:                 用户上传 → 自动索引
  Ontology:            手动维护（Phase 1）/ 自动抽取（Phase 3+）
  Prompt Library:      手动管理

流出：
  Business Dictionary → Intent Planner
  RAG → Chat / Agent
  Ontology → Planner
  Semantic Index → Capability Discovery
  Prompt Library → LLM 调用

闭环（Evaluation 回写）：
  Evaluation → Business Dictionary（新增术语）
            → RAG（优化权重）
            → Semantic Index（更新 Embedding）
            → Prompt Library（优化模板）
```

## 8.2 Data Domain 生命周期管理（v2.1 新增）

```
Data Domain 的创建与维护：

创建：
  MUST: Data Domain 在首次注册同类知识资产时自动创建
  SHOULD: 支持手动创建（批量注册前预定义）
  SHOULD: 创建时声明 data_classification（public / internal / confidential / restricted）

变更：
  MUST: Data Domain 与 Business Domain 的映射关系支持动态调整
  SHOULD: 知识资产在不同 Data Domain 之间迁移时保留审计记录

废弃：
  MUST: Data Domain 废弃时，下属知识资产需先迁移或标记为 orphan
  MUST: 废弃的 Data Domain 不可用于路由（路由时跳过）

治理：
  SHOULD: 每个 Data Domain 有明确的 owner 团队
  SHOULD: data_classification 变更需审批（结合 Policy Center）
  MAY: 支持 Data Domain 层级（子域继承父域的数据分类等级）
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Planner Spec — Intent Parsing | Business Dictionary |
| Capability Center Spec — Discovery | Capability Metadata + Semantic Index |
| Runtime Spec — Feedback & Learning | 闭环回写 |
