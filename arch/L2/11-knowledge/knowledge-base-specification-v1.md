# Knowledge Base Specification v1.1

## EARP 知识库规范

**文档编号：L2-11-KNOWLEDGE**  
**版本：v1.1**  
**定位：L2 — 平台规范。定义 EARP 的知识库管理——Document/Chunk 结构、RAG 检索、双层访问控制（data_classification 天花板 + 角色级行权限）。**  
**依赖：L1/data-architecture-v1.md (Knowledge 域), L2-07-TENANT v1.2, L2-05-POLICY v1.1**

> **v1.1 变更（2026-08-07）**：新增 §2.1.1 双层访问模型——data_classification（Data Domain 天花板）与 accessible_roles（文档级角色）两层叠加；与本体层设计（arch/design/2026-08-07-ontology-layer-design.md §8）对齐。

> **v1.0 新建**：KnowledgeBase/Document/Chunk 数据模型；RAG 检索流程；角色级文档访问控制（默认封闭原则）。

---

# 第一章：数据模型

## 1.1 核心实体（对齐数据视图 Knowledge 域）

```
KnowledgeBase → Document → Chunk (1:N:N)

MUST: KnowledgeBase 包含以下字段
  - kb_id:          string    — 全局唯一
  - tenant_id:      string    — 租户隔离
  - name:           string
  - description:    string

MUST: Document 包含以下字段
  - doc_id:            string    — 全局唯一
  - kb_id:             string    — 所属知识库
  - tenant_id:         string    — 租户隔离
  - title:             string
  - format:            string    — txt/pdf/md/html
  - status:            "processing" | "ready" | "error"
  - accessible_roles:  list[str] — 可访问角色列表（v1.0 新增，默认封闭原则）
  - chunk_count:       int
  - created_at:        string    — ISO 8601

MUST: Chunk 包含以下字段
  - chunk_id:       string        — 全局唯一
  - doc_id:         string        — 所属 Document
  - tenant_id:      string        — 租户隔离（冗余，避免 RAG 检索时 JOIN Document）
  - content:        string        — 文本内容
  - embedding:      list[float]   — 向量（pgvector）
  - metadata:       dict          — 分块元信息
```

---

# 第二章：角色级文档访问控制（核心）

## 2.1 原则

```
MUST: 默认封闭 — Document 创建时 accessible_roles 默认为 [创建者当前角色]
MUST: 空数组 [] = 管理员显式确认"对所有角色开放"
MUST: 检索时按当前角色过滤 — 市场角色不可检索财务文档
```

### 2.1.1 双层访问模型（v1.1 新增）

知识访问控制为**两层叠加（取交集）**：

```
第一层 — data_classification 天花板（Data Domain 级，全局约束）
  Document 归属的 DD 有 data_classification（public/internal/confidential/restricted）
  → 用户角色须通过 Policy Center 分类授权，分类不够则后续层再开放也看不到

第二层 — accessible_roles 行级（Document 级，精确粒度）
  Document.accessible_roles 精确到文档
  → 默认封闭：创建者角色

过滤规则（两层叠加）：
  WHERE tenant_id = ?
    AND role 可访问该文档所属 Data Domain（classification 天花板）
    AND (accessible_roles @> ARRAY[current_role] OR accessible_roles = '{}')
```

> 本体层（实体/事实/档案）沿用同一模型：实体继承 DD 的 data_classification（天花板）+ 行级角色控制，见 arch/design/2026-08-07-ontology-layer-design.md §8。

## 2.2 访问控制规则

```
MUST: Document 创建时自动设置 accessible_roles = [创建者当前角色]
MUST: 管理员可修改 accessible_roles（增删角色、设为 [] 全开放）
MUST: RAG 检索 SQL 过滤：
  WHERE tenant_id = ? 
    AND (accessible_roles @> ARRAY[current_role] OR accessible_roles = '{}')
  
  语义：
    - accessible_roles = ['market_analyst'] → market_analyst 可见，finance_manager 不可见
    - accessible_roles = [] → 管理员已确认全开放，所有角色可见
    - 默认封闭：新 Document 不设标签时仅创建者角色可见

SHOULD: 生产环境建议 accessible_roles 为 MUST 字段，防止遗漏导致泄漏
```

## 2.3 示例

```
市场分析员（current_role=market_analyst）上传文档：
  → Doc.accessible_roles = ["market_analyst"]（自动）

财务主管（current_role=finance_manager）检索 "库存报表"：
  → RAG SQL：accessible_roles @> ARRAY['finance_manager']
  → market_analyst 的文档不匹配 → 不出现在结果中
```

---

# 第三章：RAG 检索流程

```
User query → embed → pgvector search
  → WHERE tenant_id = ? AND (accessible_roles @> ARRAY[current_role] OR accessible_roles = '{}')
  → 返回过滤后的 Chunk 列表 → 构建 LLM Prompt
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Multi-Tenant Spec v1.2 | tenant_id + role_id 隔离 |
| Policy Center Spec v1.1 | Role.permissions 定义 |
| Capability Center Spec v1.4 | 语义搜索共享 pgvector 索引 |
