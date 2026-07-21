# PRD 变更评审报告 — Data Domain 概念引入 (v2.1)

| 评审ID | PRD-DATA-DOMAIN-v2.1-REVIEW |
|:-------|:----------------------------|
| 评审日期 | 2026-07-21 |
| 评审人 | Codex (自动化) |
| 范围 | 7 个已修改 PRD：001, 012, 018, 020, 022, 023, 024 |
| 版本 | v1.0 |

---

## 总览

| 检查项 | 结论 | 严重度 |
|:-------|:-----|:------|
| **#1 概念一致性** | **ISSUE** — data_domain_access JSONB 格式未定义；data_classification 字段语义重叠未区分 | P1 |
| **#2 向后兼容** | **ISSUE** — knowledge_bases.data_domain_id IS NULL 时检索可能被静默排除 | P1 |
| **#3 授权模型** | **ISSUE** — max_classification 未定义来源；双层 classification 交互未说明 | P1 |
| **#4 AC-08 重复** | **ISSUE** — AC-08 的 pytest 描述与 AC-06 完全相同（确认笔误） | P0 |
| **#5 受影响 PRD** | **ISSUE** — 至少 3 个 PRD 需同步更新 | P2 |

---

## 1. 概念一致性 (data_domain_id / data_classification / data_domain_access)

### 1.1 data_domain_id — 一致性 ✅

| PRD | 字段名 | 一致性 |
|:----|:-------|:------|
| 018 | `KnowledgeBase.data_domain_id` (nullable) | ✅ |
| 020 | `knowledge_bases.data_domain_id FK REFERENCES data_domains` | ✅ |
| 024 | `WHERE knowledge_bases.data_domain_id IN ?` | ✅ |
| 022 | `请求 data_domain_ids` (US #8，复数) | ✅ — 请求参数为列表，与单列 FK 不矛盾 |

结论：字段命名一致，语义对齐。

### 1.2 data_classification — 语义歧义 ⚠️ P1

该名称在 M0 DDL 表中出现在**两个不同位置**：

| 表 | 字段 | 含义 |
|:---|:-----|:-----|
| `data_domains` | `data_classification VARCHAR(16)` | **域级别**分类等级（public/internal/confidential/restricted） |
| `documents` | `data_classification VARCHAR(16)` | **文档级别**分类等级（v2.1 新增） |

问题：
- PRD-022 US #8 引用的是"文档级 data_classification"，但未说明**域级别 classification**的含义及与文档级的关系。
- PRD-024 引用 `角色 max_classification`，但未说明在 data_domain 含 classification 的情况下，documents.data_classification 是与之平行还是子集。
- **建议**：明确两层 classification 的归属关系 —— 是"文档级继承域级默认值（可覆盖）"还是"独立两层分别约束"？当前所有 PRD 均未说明。

### 1.3 data_domain_access JSONB — 格式未定义 ⚠️ P1

`roles.data_domain_access JSONB` 未在任何可访问的设计文档中定义 schema：

| 引用来源 | 内容 | 定位 |
|:---------|:-----|:----|
| PRD-020 | `roles.data_domain_access JSONB` | 仅声明字段类型 |
| PRD-022 | `Role.data_domain_access ∩ 请求 data_domain_ids` | 语义引用但无结构 |
| PRD-024 | `文档级 data_classification ≤ 角色 max_classification` | 引用 `max_classification`，但该值在 data_domain_access 中如何存放？ |

未定义的问题：
1. `data_domain_access` 是 `["domain_id_1", "domain_id_2"]` 权限列表，还是 `{"domain_id_1": ["public", "internal"], ...}` 精细化分类映射？
2. `max_classification` 从何而来？是 data_domain_access 中的某个字段，还是 data_domains.data_classification 的聚合？
3. 如果 data_domain_access 支持按域精细分配分类权限（如"域 A 可读 confidential"），PRD-022 US #8 描述的 `∩` 交集运算需要扩展说明。

**建议修复**：
- 在 Concept Model v2.1 §5.8 或 Policy Center Spec v1.2 §5.1 中明确定义 JSONB schema。
- 若 Concept Model 文档不存在，至少在本 PRD 变更的任一文档中补充注释或引用 L3 设计的 schema 定义。

---

## 2. 向后兼容 — data_domain_id IS NULL 检索 ⚠️ P1

### 2.1 正面：PRD-018 AC-05 ✅

```
AC-05: KnowledgeBase.data_domain_id 字段存在，可为 None（未分配 DD 的 KB 仍可检索）
```

AC-05 明确要求 NULL 兼容，设计意图正确。

### 2.2 问题：PRD-024 检索 SQL 未兼容 NULL ❌

PRD-024 #4 当前描述：
```
Data Domain 过滤（WHERE knowledge_bases.data_domain_id IN ?）
```

**风险**：SQL 标准中 `NULL NOT IN (?)` 恒为 FALSE，`NULL IN (?)` 恒为 NULL → WHERE 条件排除该行。若查询时传入了 `data_domain_ids` 列表，data_domain_id IS NULL 的 KB 将被静默排除，违反 AC-05 的向后兼容承诺。

**建议两种修复**（任选其一）：

| 方案 | SQL 模式 | 效果 |
|:-----|:---------|:-----|
| A. 仅当显式传入 domain_ids 时过滤 | `IF @domain_ids IS NOT NULL → AND (data_domain_id = ANY(@domain_ids) OR data_domain_id IS NULL)` | 未指定 domain 时不做过滤，保持最大兼容 |
| B. 始终包括无 domain KB | `AND (data_domain_id = ANY(@domain_ids) OR data_domain_id IS NULL)` | 每次检索均包含未分类 KB，推荐于严格权限场景 |

如果采用方案 A（更常见），PRD-024 需要同步说明："未指定 data_domain_ids 时不做 Data Domain 过滤"。

---

## 3. 授权模型 — Role↔Data Domain 粒度评估

### 3.1 设计意图 ✅

```
Role.data_domain_access ∩ 请求 data_domain_ids ∩ 文档级 data_classification
```

三层交集模型在概念上是完整的：
- **角色层**：控制角色能访问的 Data Domain 集合
- **请求层**：本次查询的目标域（由 Planner 或调用方指定）
- **文档层**：文档自身打标的安全等级

### 3.2 遗留问题 ⚠️ P1

| # | 问题 | 影响 |
|:-:|:-----|:-----|
| 1 | `max_classification` 在 PRD-024、PRD-012 中多次引用，但**未定义其来源和计算方式**。是 data_domain_access JSONB 中每个域 entry 的附带字段，还是从 data_domains 表 JOIN 得来的聚合值？ | 实现者无法编码 |
| 2 | 授权模型仅描述了 data_domain_access ∩ data_domain_ids ∩ data_classification 的交集，但**未说明"无 data_domain_access 的角色"（升级前）的行为**。旧角色升级后 data_domain_access 默认是 `[]` 还是 `['*']`（所有域）？ | 迁移兼容性 |
| 3 | M0 DDL 在 `data_domains` 表上定义了 `data_classification`，但 **RBAC 授权路径中未见 data_domains.data_classification 的使用**。该域级分类是否应该参与授权？ | 安全纵深 |

### 3.3 粒度评估

当前模型为**域级别粗粒度 + 文档级别细粒度**的双层授权：
- 域级别：通过 data_domain_access 布尔级授权（可/不可访问某域）
- 文档级别：通过 data_classification 等级过滤

如果未来需要更细粒度的"域 A 只能读 confidential，域 B 可读 internal"，则 data_domain_access 需要扩展为 `dict[domain_id, list[classification]]` 格式。当前 PRD 未做此假设，建议在概念模型文档中明确标注"当前为简单列表模式，可扩展"。

---

## 4. PRD-022 AC-08 与 AC-06 内容重复 ❌ P0

### 4.1 确认问题

**PRD-022 AC-06（原有）**：
```
AC-06: RBAC v1.1 §六 场景可复现（权限拒绝+data_scope 过滤）
```

**PRD-022 AC-08（新增）**：
```
AC-08: 跨 Data Domain 查询→静默跳过无权限的域（不报错，不阻断有权限的域）
```

AC 标题写对了，但 **pytest 描述列完全复制了 AC-06 的内容**：描述的是 R1/R2 Capability 权限拒绝 + data_scope=self 过滤，与 Data Domain 授权无关。

### 4.2 修复方案

AC-08 的 pytest 描述应改为：
```
角色 R1 有 data_domain_access=['dd_hr', 'dd_finance'] → 跨域查询返回 dd_hr + dd_finance 两域结果；
角色 R2 有 data_domain_access=['dd_hr'] → 跨域查询静默跳过 dd_finance 文档，只返回 dd_hr 结果（不报错）
```

**严重度 P0**：该错误将在测试实现时直接导致歧义——测试工程师会误以为要测试 RBAC Capability 场景而非 Data Domain 场景。

---

## 5. 遗漏 PRD 检查

### 5.1 已修改 PRD 内的缺失

#### PRD-2026-024 AC 未同步更新 ⚠️ P2

PRD-024 **范围表 #4** 已更新为包含 Data Domain 过滤 + data_classification 检查：
```
+ Data Domain 过滤（WHERE knowledge_bases.data_domain_id IN ?）
+ 文档级 data_classification ≤ 角色 max_classification
+ accessible_roles 过滤（向后兼容）
```

但 **AC 表格中 AC-03** 仍为旧描述：
```
AC-03: 嵌入检索→top_k chunks 返回, accessible_roles 过滤生效
```

缺少至少 1 个 AC 来覆盖 Data Domain 过滤和 data_classification 检查。建议新增：
- AC-07: Data Domain 过滤 + data_classification 检查 → 仅返回有权限域的文档（pytest）
- AC-08: data_domain_id IS NULL 的 KB 在检索中不被排除（pytest，呼应 PRD-018 AC-05）

### 5.2 未修改的 PRD

| PRD | 需更新原因 | 建议变更 |
|:----|:----------|:--------|
| **PRD-2026-011** (Data Architecture) | M0 基线 DDL 新增了 `data_domains`、`business_domain_data_domain_map` 表，但 data-architecture 文档未提及。PRD-020 已引用 Concept Model v2.1 §5.8 和 Policy Center Spec v1.2 §5.1 作为 Data Domain 的规范来源，这些上游设计文档若不存在则需要补充或由 PRD-011 承载。 | 在 PRD-011 §1.1 或 §2 数据域清单中新增 Data Domain 表格条目。 |
| **PRD-2026-021** (M1 Walking Skeleton) | M1 的 Invoke 链中 Planner 可能会接收含 Data Domain 的 Plan 请求，但 M1 当前仅支持单步 Capability invoke。 | 在 §1 依赖/范围表脚注注明：Data Domain 知识路由属 M3+M4，M1 路径仅限 Capability invoke。 |
| **PRD-2026-013** (Observation/Replay) | PRD-023 US-07 新增纯知识意图跳过 Execution Runtime 的路径，M5 的观测与回放需要确认是否覆盖该路径。 | 在 §2.1 知识查询流程中注明：纯知识查询跳过 Execution，Observation 暂不覆盖。 |
| **PRD-2026-028** (Admin Dashboard) | 已有 Data Domains 管理和 data_classification 筛选，但角色编辑页面（Roles CRUD）是否需同步暴露 data_domain_access 编辑接口？ | 在 §6.9 或角色管理章节补充：角色编辑表单中新增 data_domain_access 多选组件。 |

### 5.3 规范文档（非 PRD）

| 文档 | 引用方 | 当前状态 |
|:-----|:-------|:--------|
| Concept Model v2.1 §5.8 | PRD-020 对齐规范中引用 | 文件不存在，建议创建或在现有架构文档中补充 |
| Policy Center Spec v1.2 §5.1 | PRD-020 对齐规范中引用 | 文件不存在，建议在 RBAC 设计文档中扩展 Data Domain 授权章节 |

---

## 6. 汇总矩阵

| # | 检查项 | 结论 | 严重度 | 关联文件 |
|:-:|:-------|:-----|:------|:--------|
| 1 | data_domain_id 一致性 | ✅ PASS | — | 018, 020, 024 |
| 2 | data_classification 语义歧义（域级 vs 文档级） | ⚠️ **ISSUE** | **P1** | 020, 022, 024 |
| 3 | data_domain_access JSONB 格式未定义 | ⚠️ **ISSUE** | **P1** | 020, 022, 024 |
| 4 | max_classification 来源未定义 | ⚠️ **ISSUE** | **P1** | 024, 012 |
| 5 | data_domain_id IS NULL 兼容性（PRD-024 SQL） | ⚠️ **ISSUE** | **P1** | 024 |
| 6 | 旧角色 data_domain_access 默认值未定义 | ⚠️ **ISSUE** | **P1** | 022 |
| 7 | AC-08 描述与 AC-06 重复（笔误） | ❌ **ISSUE** | **P0** | 022 |
| 8 | PRD-024 AC 表格缺少 Data Domain 过滤 AC | ⚠️ **ISSUE** | **P2** | 024 |
| 9 | PRD-011 未更新 | ⚠️ **ISSUE** | **P2** | 011 |
| 10 | PRD-021 / 013 / 028 注释性缺失 | ⚠️ **ISSUE** | **P2** | 021, 013, 028 |

---

## 7. 高优修复建议

| 优先级 | 修复项 | 建议操作 |
|:------|:-------|:--------|
| **P0** | PRD-022 AC-08 pytest 描述修复 | 将 AC-08 的 pytest 描述替换为 Data Domain 交叉授权场景（见 §4.2 示例） |
| **P1** | data_domain_access JSONB schema 定义 | 在任一上游设计文档（Concept Model 或 Policy Center Spec）中明确 JSONB 格式、max_classification 来源、角色默认值 |
| **P1** | PRD-024 检索兼容性 | 补充 data_domain_id IS NULL 的处理逻辑到 SQL 描述中 |
| **P1** | classification 双层语义说明 | 在 PRD-020 DDL 描述中附加注释说明 documents.data_classification 与 data_domains.data_classification 的关系 |
| **P2** | PRD-024 AC 补缺 | 新增 AC-07、AC-08 覆盖 Data Domain 过滤和 NULL 兼容性 |
| **P2** | PRD-011 同步 | 新增 Data Domain 表到 data-architecture 文档的 domain 清单中 |
