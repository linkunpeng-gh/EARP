# Data Domain v2.1 — L3 设计文档影响评估

**日期：2026-07-21**
**版本：v1.3（基于 v1.2 评审意见修订）**
**依据：concept-model-v2.1、architecture-v6（v2.1 更新）、knowledge-center-specification、planner-specification、policy-center-specification 的 L2 diff**

---

## 一、v2.1 变更摘要

| 变更 | 位置 | 说明 |
|------|------|------|
| Domain → Business Domain | concept-model §5.7 | 原 Domain 更名为 Business Domain，明确其 Capability 归属边界语义 |
| 新增 Data Domain | concept-model §5.8 | 企业数据与知识的领域归属边界，独立于 Business Domain。N:M 映射关系 |
| 新增知识链 | concept-model 附录 A | 第 5 条概念链：User Request → Data Domain → Knowledge Center → LLM 综合回答 |
| Domain First 扩展 | architecture-v6 §1.2 | A2 原则从单一路由扩展为二维并行：BD → Capability + DD → Knowledge |
| Planner 二维路由 | planner-specification §5 | Phase 3 拆分 3a（BD 路由）+ 3b（DD 路由），路由判别逻辑表 |
| Knowledge Center 域过滤 | knowledge-center-specification | 所有知识实体增加 data_domain 必填字段，检索接口支持域过滤 |
| Policy Center DD 授权 | policy-center-specification §5.1 | 新增 Data Domain 授权维度，独立于 Capability RBAC |

---

## 二、L3 文档清单（11 份）

```
arch/design/
├── server-m0-l3-design-v1.md        # M0 DDL + 脚手架
├── server-m1-l3-design-v1.md        # M1 执行路径
├── server-side-development-plan-v1.md # 服务端开发计划
├── role-based-access-control-v1.md   # RBAC 设计
├── next-phase-plan.md               # 后续计划
├── security-phase2-l3-design-v1.md  # 凭证加密 + 审计
├── security-phase3-l3-design-v1.md  # LLM Guard
├── tech-stack-analysis-v1.md        # 技术选型
├── ADR-007-modular-monolith.md      # 工程形态

arch/L3/
├── runtime-sdk-design-v1.md         # Runtime SDK
└── capability-sdk-design-v1.md      # Capability SDK
```

---

## 三、逐文档影响评估

### 3.1 高影响（需实质性修改）

---

#### 3.1.1 `arch/design/server-m0-l3-design-v1.md`

**影响点：DDL 基线需新增表和列。**

##### (a) 新增表

```sql
-- Data Domain 主表
CREATE TABLE data_domains (
    data_domain_id      VARCHAR(64) PRIMARY KEY,
    tenant_id           VARCHAR(64) NOT NULL,
    name                TEXT NOT NULL,
    description         TEXT,
    data_classification VARCHAR(16) NOT NULL DEFAULT 'internal'
                        CONSTRAINT ck_data_classification CHECK (
                            data_classification IN ('public','internal','confidential','restricted')
                        ),
    owner               TEXT,
    status              VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_data_domains_tenant ON data_domains (tenant_id);

-- Business Domain ↔ Data Domain N:M 映射
CREATE TABLE business_domain_data_domain_map (
    business_domain_id  VARCHAR(64) NOT NULL,
    data_domain_id      VARCHAR(64) NOT NULL REFERENCES data_domains (data_domain_id),
    tenant_id           VARCHAR(64) NOT NULL,
    PRIMARY KEY (business_domain_id, data_domain_id, tenant_id)
);
CREATE INDEX ix_bddm_tenant ON business_domain_data_domain_map (tenant_id);
```

##### (b) 修改列

```sql
-- roles 表增加 Data Domain 授权
ALTER TABLE roles ADD COLUMN data_domain_access JSONB NOT NULL DEFAULT '[]';
-- 结构: [{"data_domain_id": "...", "max_classification": "confidential"}, ...]

-- knowledge_bases 表增加 Data Domain 归属
ALTER TABLE knowledge_bases ADD COLUMN data_domain_id VARCHAR(64) REFERENCES data_domains(data_domain_id);

-- documents 表增加 data_classification 列（文档级分类，细粒度控制）
ALTER TABLE documents ADD COLUMN data_classification VARCHAR(16) DEFAULT 'internal'
    CHECK (data_classification IN ('public','internal','confidential','restricted'));
```

> 如上变更作为新 migration 单独执行，不修改 0001_baseline（保持幂等性）。

##### (c) `data_domain_id` 的存储策略辨析

文档在 `knowledge_bases`、`documents`、`chunks` 三张表上的 `data_domain_id` 列方案需要讨论：

| 方案 | 存储位置 | 检索路径 | 域变更代价 |
|------|---------|---------|-----------|
| **A：归一（推荐）** | 仅在 `knowledge_bases` 存 `data_domain_id` | RAG 检索时 join：chunks → documents → knowledge_bases | 只改 KB 一行 |
| **B：物化** | `knowledge_bases` + `documents` + `chunks` 各存一份 | 零 join：WHERE data_domain_id=? 直接过滤 | 级联更新所有下游行 |

**推荐：Phase 1 走方案 A（归一）。**

理由：
- chunks 万级规模下，多一次 join 性能影响可接受（pgvector 检索本身已是 O(n) 运算）
- 域变更是一致性关键操作——改 KB 一行比级联更新 chunks 安全得多
- 方案 B 的物化收益在 chunk 规模超过 100 万后才有意义，此时再做物化也不迟

Phase 2 后若遇到性能瓶颈，评估在 chunks 上物化 `data_domain_id` 并为 `(kb_id, data_domain_id)` 建复合索引。

> 注意：方案 A 意味着 `documents` 和 `chunks` **不需要**新增 `data_domain_id` 列。

##### (d) 其他修改

| 行号 | 内容 | 修改 |
|:---:|------|------|
| L7 | 依赖声明：concept-model 引用 | "v2.0" → "v2.1" |
| L29-53 | TENANT_TABLES 列表 | 增加 `"data_domains"`, `"business_domain_data_domain_map"` |
| L258 | test_rls 覆盖描述 | 注明需覆盖新增的 2 张表 |

---
#### 3.1.2 `arch/design/role-based-access-control-v1.md`

**影响点：Data Domain 引入了独立于 Capability RBAC 的第二维权控维度。**

##### (a) §1.1 实体关系图

```diff
- 知识检索范围 ← Role.knowledge_scopes (文档标签过滤)
+ 知识检索范围 ← Role.data_domain_access (两级过滤：域ID + 数据分类等级)
+ 说明：Data Domain 授权独立于 Business Domain 的 Capability 权限。
+       知识检索时取 data_domain_access 与知识资产的 data_domain_id + data_classification 的交集。
```

##### (b) §1.2 关键规则

规则 #6 修改：

```diff
- | 6 | **知识检索按角色**。KnowledgeBase 文档标注可访问角色列表，RAG 检索时过滤 |
+ | 6 | **知识检索按角色+数据域**。Knowledge Center 检索时，先按 Role.data_domain_access
+       过滤 Data Domain，再按文档的 accessible_roles 过滤。两级取交集 |
```

##### (c) §3.1 Role 实体

```diff
  MUST: Role 包含以下字段
    - role_id:          string
    - tenant_id:        string
    - name:             string
    - permissions:      list[str]   -- ["alarm:read", "work_order:write"]
    - data_scope:       "self" | "department" | "org" | "all"
    - knowledge_tags:   list[str]   -- 可访问的知识文档标签 (SHOULD)
+   - data_domain_access: list[{data_domain_id, max_classification}]  -- v2.1 新增 (MUST)
+        data_domain_id:  可访问的 Data Domain ID（空列表 = 无知识访问权限）
+        max_classification: 最高可访问的数据分类等级（public < internal < confidential < restricted）
+        通配: data_domain_id="*" 表示全部 Data Domain（管理员角色）
```

##### (d) §3.4 知识库按角色隔离

在当前 `accessible_roles` 方案之前增加 Data Domain 维度。过滤顺序：

```
1. Data Domain 过滤（优先级 1）
   → 检索请求指定 data_domain_ids（Planner 路由结果）
   → 与当前角色 data_domain_access 取交集
   → 仅检索交集内的 Data Domain 中的知识资产

2. 数据分类等级过滤（优先级 2）
   → 知识资产的 data_classification ≤ 角色在该 Data Domain 的 max_classification
   → 比较对象：文档级的 data_classification（DDL 中 documents 表已新增此列）
   → 如：角色对 "hr_data" 的 max_classification="internal"，该域中 "confidential" 文档不可见
   → data_classification 等级链：public(0) < internal(1) < confidential(2) < restricted(3)

3. 文档级过滤（优先级 3，向后兼容）
   → 知识资产的 accessible_roles 包含当前 role_id

过滤链：
  Planner DD 路由结果（候选域列表）
    → ∩ Role.data_domain_access（角色可访问域）
      → ∩ 文档级 data_classification ≤ 角色的 max_classification
        → ∩ Document.accessible_roles（文档级，向后兼容）
          → 最终检索空间
```

> **设计决策**：data_classification 放在 `documents` 表而非 `data_domains` 表，理由有二：
> 1. 同一 Data Domain 内的文档可能有不同的敏感等级（如"设备维护手册"= internal，"设备安全审计报告"= confidential）
> 2. 文档级分类 > 域级分类，更细粒度，对企业合规更友好

##### (e) 新增 §3.5 "Data Domain 授权与 Capability RBAC 的关系"

```
Data Domain 授权 和 Capability RBAC 是两条独立评估路径：

| 维度 | Capability RBAC | Data Domain 授权 |
|------|----------------|-----------------|
| 评估时机 | Capability 调用前（Resolution Engine / PolicyLayer） | Knowledge Center 检索时 |
| 评估对象 | domain:action 权限（如 "alarm:read"） | Data Domain ID + data_classification |
| 失败行为 | 返回 403 / Capability 发现时隐藏 | 检索结果为空（不报错，静默过滤） |
| 管理接口 | Policy Center（permissions 配置） | Role 配置（data_domain_access 字段） |

两条路径互斥——不取交集、不互相阻塞：

- 用户问 "创建工单" → 只走 Capability RBAC（不涉及 Data Domain）
- 用户问 "休假政策" → 只走 Data Domain 授权（不涉及 Capability）
- 用户问 "分析报警趋势并对比安全标准" → 两条路径并行评估，各自独立返回
```

##### (f) §2.2 缺失项

```diff
+ | **Data Domain 授权维度** | Role 只有 knowledge_tags（自由标签），无结构化的数据域+分类等级授权 | Policy Center / Knowledge Center |
```

---
### 3.2 中影响（需补充但非结构级变更）

涉及 5 份文档：server-side-development-plan-v1.md（里程碑描述）、next-phase-plan.md（优先级清单）、capability-sdk-design-v1.md（字段注释）、runtime-sdk-design-v1.md（子客户端）、security-phase2-l3-design-v1.md（审计补充）。

#### 3.2.1 `arch/design/server-side-development-plan-v1.md`

| 位置 | 当前 | 修改 |
|------|------|------|
| §2.1 L38 | `L1.5 concept-model v2.0` | → `v2.1` |
| M0 描述 | DDL 基线（25 表，14 启用） | → DDL 基线（27 表，含 data_domains + bddm 映射表） |
| M2 描述 | PolicyLayer 实现 RBAC/data_scope/rate-limit | → 增加 **Data Domain 授权评估**（独立路径，与 Capability RBAC 并行） |
| M3 描述 | Planner 单域路由 + Capability Discovery | → Planner **二维路由**（Phase 3a BD + Phase 3b DD），纯知识查询可跳过 Execution |
| M4 描述 | Knowledge Base RAG 检索 | → RAG 检索增加 Data Domain 过滤参数，知识资产生命周期增加 DD 管理 |
| §六里程碑↔L2 | 现有 8 行（M1-M7） | → 增加 v2.1 行：Concept Model v2.0→v2.1 / Knowledge Center v1.0→v1.1 / Planner v1.0→v1.1 / Policy v1.1→v1.2 |

---

#### 3.2.2 `arch/design/next-phase-plan.md`

**建议更新。** next-phase-plan.md 是优先级建议文档，不属于设计文档。但当前 plan 中 M0-M7 里程碑没有一条标注 Data Domain 相关内容，不更新则下一个读 plan 的人不知 v2.1 的工作量分配。

| 位置 | 修改 |
|------|------|
| M0 DDL 清单 | 增加 `data_domains` + `business_domain_data_domain_map` 两张表 |
| M2 功能描述 | 增加 "Data Domain 授权评估" 子任务 |
| M3 功能描述 | 增加 "Planner 二维路由（Phase 3b DD 路由）" 子任务 |
| M4 功能描述 | 增加 "RAG Data Domain 过滤 + 资产生命周期 DD 管理" 子任务 |

---

#### 3.2.3 `arch/L3/capability-sdk-design-v1.md`

**影响点：`domain` 字段命名歧义。** v2.1 之后，"Domain" 不再是精确的术语。

| 位置 | 当前 | 修改 |
|------|------|------|
| §2.1 L71 | `domain: str = ""`  # 必填 | `# 必填。Business Domain（v2.1 起与 Data Domain 平行概念，此处指能力归属领域）` |
| §2.4 L190 | `domain="equipment"` | 不变，加注释 `# Business Domain` |
| §7 L457 | `list_by_domain("equipment")` | 不变，加注释 `# 按 Business Domain 浏览` |

> **不改接口签名。** Capability SDK 的 `domain` 始终指 Business Domain，只需文档层面消除歧义。

---

#### 3.2.4 `arch/L3/runtime-sdk-design-v1.md`

**影响点：新增 `session.knowledge` 子客户端。** v2.1 新增了纯知识查询路径（不经 Capability），需要给应用开发者提供一个统一入口。

新增文件：

```
src/earp_sdk_runtime/
├── knowledge/
│   ├── __init__.py
│   └── client.py       # KnowledgeClient（新增，~60 行）
├── session.py           # Session 类增加 @property knowledge
```

核心接口：

```python
class KnowledgeResult:
    """知识检索结果。"""
    content: str           # chunk 内容
    source_doc_id: str     # 来源文档 ID
    source_title: str      # 文档标题（展示用）
    data_domain_id: str    # 所属 Data Domain
    score: float           # 相关度分数（0-1）


class KnowledgeClient:
    async def query(
        self,
        query: str,
        data_domains: list[str] | None = None,
        top_k: int = 10,
    ) -> list[KnowledgeResult]:
        ...

class Session:
    @property
    def knowledge(self) -> KnowledgeClient:
        ...
```

> **架构决策**：两条知识查询路径都是合规的：
> 1. **通过 Runtime SDK**：`session.knowledge.query()` — 统一入口，自动注入 trace/context，推荐
> 2. **直调 Knowledge Center API**：绕过 SDK，适合非交互式集成场景
>
> Runtime SDK 路径将 trace 上下文自动注入，治理更完整。建议 Phase 1 优先实现路径 1。

---

#### 3.2.5 `arch/design/security-phase2-l3-design-v1.md`

**影响点：审计需覆盖 Data Domain 访问路径。**

```diff
# Data Domain 授权变更的审计要求（v2.1 新增）

MUST: 以下 Data Domain 相关操作产生审计事件：
  - data_domain_access 配置变更（谁授予了哪个角色对哪个 DD 的访问权）
  - Knowledge Center 检索时的 Data Domain 过滤（辅助排查"为什么看不到某篇文档"）

SHOULD: audit_logs.detail 中增加 data_domain_id 字段（跨域查询时记录为数组）
SHOULD: data_classification 越级访问尝试记录为审计事件（日志不报错，仅记录）
```

---

### 3.3 低影响

#### 3.3.1 `arch/design/server-m1-l3-design-v1.md`

**无需修改。** M1 覆盖纯执行路径（invoke → StepRunner → Connector → Checkpoint → EventBus）。Data Domain 路由发生在 Planner（M3）和 Knowledge Center（M4）层，运行时执行不感知 Data Domain。

#### 3.3.2 无影响文档（3 份）

| 文档 | 原因 |
|------|------|
| `security-phase3-l3-design-v1.md` | LLM Guard/输入过滤，与域模型无关 |
| `tech-stack-analysis-v1.md` | 技术选型参考，不涉及领域模型 |
| `ADR-007-modular-monolith.md` | 工程形态决策 |


---

## 四、建议修改顺序

按上游依赖关系排列：

```
role-based-access-control-v1.md（DD 授权模型必须先定稿）
    → server-m0-l3-design-v1.md（DDL 是其他所有里程碑的基础）
        → server-side-development-plan-v1.md（里程碑分配反映 v2.1 工作量）
            → next-phase-plan.md（标注 Data Domain 在各里程碑的子任务）
                → capability-sdk-design-v1.md（顺手修注释）
                → runtime-sdk-design-v1.md（session.knowledge 子客户端）
                → security-phase2-l3-design-v1.md（审计补充）

> 注：三个 SDK/审计文档之间无先后依赖，可并行执行。缩进仅表示它们依赖于上游 DDL/Plan 的完成顺序。
```

顺序映射到已有里程碑：

| 顺序 | 文档 | 对应里程碑 | 增量估算 |
|:----:|------|:----------:|:-------:|
| 1 | RBAC 设计 | M2 前置 | 1h |
| 2 | M0 DDL | M0 | 0.5h |
| 3 | 开发计划 | — | 0.5h |
| 4 | next-phase-plan | — | 0.5h |
| 5 | Capability SDK | — | <0.5h |
| 6 | Runtime SDK（升入中影响） | — | 1h |
| 7 | 安全审计 | M2 审计 | 0.5h |

> "—" 表示该文档工作**不占用里程碑时间**，属于独立的前置/配套文档更新，可在对应里程碑空闲时穿插完成。

---

## 五、里程碑工作量明细

### M0（DDL）

| 子任务 | 估时 |
|--------|:---:|
| data_domains 表 DDL | 10min |
| business_domain_data_domain_map 表 DDL | 5min |
| knowledge_bases.data_domain_id 列 | 5min |
| documents.data_classification 列 | 5min |
| roles.data_domain_access 列 | 5min |
| RLS 策略 + TENANT_TABLES 更新 | 5min |
| 测试覆盖（2 张新表 + RLS 验证） | 5min |
| **小计** | **0.5h** |

---

### M2（Policy Layer）

| 子任务 | 估时 |
|--------|:---:|
| Role 实体扩展：data_domain_access 读写 | 15min |
| DD 授权评估器：data_domain_access ∩ 请求域列表 ∩ classification | 25min |
| 审计事件：data_domain_access 变更 + DD 越级尝试 | 15min |
| RBAC 文档更新（§3.1/3.4/3.5） | 5min |
| **小计** | **1h** |

---

### M3（Planner）

| 子任务 | 估时 |
|--------|:---:|
| 路由判别器实现（Rule-based 关键词分类：判断纯知识/纯操作/混合） | 30min |
| Data Domain 查找服务接入（根据 Goal 中提取的 domain 线索查映射表） | 20min |
| Knowledge Center 调用渠道（纯知识查询路径，绕过 Execution Runtime） | 30min |
| 双路结果合并逻辑（LLM 综合 BD+DD 结果） | 20min |
| 降级/回退逻辑（DD 路由失败不阻塞 BD，两者均失败回退 LLM 自身知识） | 20min |
| **小计** | **2h** |

---

### M4（Knowledge Center）

| 子任务 | 估时 |
|--------|:---:|
| RAG 检索接口增加 data_domain 参数（pgvector 前级过滤） | 20min |
| Business Dictionary 查询支持 data_domain 过滤 | 15min |
| Ontology 查询支持 data_domain 过滤 | 10min |
| Data Domain CRUD service（新增 data_domains_service.py） | 25min |
| 资产生命周期：DD 创建/变更/废弃流程 | 10min |
| 测试覆盖（DD 过滤 + 跨域查询） | 15min |
| **小计** | **1.5h** |

---

### 总工作量

| 板块 | 单独估时 | 备注 |
|:----:|:-------:|------|
| **里程碑内** | | |
| M0（DDL） | 0.5h | 纯 DDL，与其他模块无依赖冲突 |
| M2（Policy Layer） | 1h | 独立于现有 RBAC 逻辑，不修改原有权限评估 |
| M3（Planner） | 2h | 最大的块；路由判别器是核心新逻辑 |
| M4（Knowledge Center） | 1.5h | Data Domain 过滤是 RAG 检索的新维度 |
| **配套文档更新** | | 不占用里程碑时间，可并行穿插 |
| SDK 清理 | 1h | 包括 Runtime SDK 子客户端 + Capability SDK 注释 |
| 审计补充 | 0.5h | 独立于安全功能逻辑 |
| **合计** | **~6.5h** | |

> **L2 版本引用扫描**：以下 L3 文档的头部依赖声明需要核实是否升级版本号：
> - `capability-sdk-design-v1.md`（依赖: L2-03-CAPABILITY v1.1 → 实际只改了注释，API 签名不变，版本可不升）
> - `runtime-sdk-design-v1.md`（依赖: L2-01-RUNTIME v1.2 → Runtime 规范未变，版本不升）
> - `server-m0-l3-design-v1.md`（依赖: concept-model → 已标注从 v2.0 → v2.1，见 §3.1.1(d)）
>
> 结论：仅 M0 L3 文档需要更新依赖版本号，其余 L3 文档引用的 L2 规范在 v2.1 中未发生实质变更，无需更新。

> 注：v1.1 原估算 5h，v1.2 扩展到 6.5h，主要增量来自：（1）Runtime SDK 的 `session.knowledge` 子客户端（1h），（2）审计事件补充（0.5h）。这两个在 v1.1 中被归类为"低/无影响"。

---

## 附录 A：关键设计决策清单

| # | 决策 | 选择 | 理由 |
|:-:|------|------|------|
| D1 | `data_domain_id` 存储策略 | 归一：仅在 knowledge_bases | 避免级联更新风险，万级规模下 join 性能可接受 |
| D2 | `data_classification` 归属 | 文档级（documents 表） | 同一域内不同文档可有不同敏感等级，粒度更细 |
| D3 | 过滤链层级 | DD → 文档级 classification → accessible_roles | 由粗到细逐层收敛，上层过滤后下层自然通过 |
| D4 | Knowledge query 入口 | Runtime SDK（session.knowledge.query()） | 统一入口，自动注入 trace/context |
| D5 | BD vs DD 授权关系 | 独立评估，不取交集 | 两条路径互斥，互不阻塞 |
| D6 | data_domain_access 类型 | JSONB（如 [{"id":"equipment","max":"confidential"}]） | 灵活支持多域 + 每域独立分类等级 |