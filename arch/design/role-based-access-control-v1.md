# EARP 角色级访问控制设计

## 组织内数据与能力按角色隔离

**版本：v1.1**  
**日期：2026-07-17**  
**原则：角色决定一切——数据、能力、知识检索均按角色严格控制。默认封闭：无显式授权即禁止。**

> **v1.1 变更：** P0-1 修复 Capability Spec 版本引用 v1.3→v1.1；P0-2 RLS SQL 对齐 data_scope 四层模型；P1 默认安全姿态改为封闭；P1 accessible_roles 统一为 []=全开放；新增 SET LOCAL 前置说明；表名统一复数

---

# 一、核心模型

## 1.1 实体关系

```
Tenant
  └── User ──(多对多)── Role
       │                    │
       │  当前角色 ─────────┘
       │
       ├── 数据访问范围 ← Role 数据范围 (self/department/org/all)
       ├── 能力调用权限 ← Role.permissions (domain:action)
       └── 知识检索范围 ← Role.knowledge_scopes (文档标签过滤)
```

## 1.2 关键规则

| # | 规则 |
|:-:|:-----|
| 1 | **权限绑定到角色，不绑定到人**。用户通过角色获得权限 |
| 2 | **一人多角色**。用户可拥有多个角色（如同时是"市场分析员"和"报表查看者"） |
| 3 | **操作前选择当前角色**。每次操作在一个确定的角色上下文中执行 |
| 4 | **数据隔离按角色**。应用层按 data_scope 四层过滤（self/department/org/all），RLS 仅做 tenant 隔离兜底 |
| 5 | **能力可见性按角色**。Capability discover 只返回当前角色有权调用的能力 |
| 6 | **知识检索按角色**。KnowledgeBase 文档标注可访问角色列表，RAG 检索时过滤 |
| 7 | **跨角色访问需显式授权**。无通配符——每个能力、每个知识库需逐个绑定到角色 |

---

# 二、当前状态 vs 目标

## 2.1 已有（✅）

| 能力 | 机制 | 位置 |
|:-----|:-----|:-----|
| RBAC — 角色权限 | `domain:action` 格式，`Role.permissions → Capability.required_permissions` | Policy Center §5.1 |
| 租户隔离 | `tenant_id` 全链路 | Multi-Tenant Spec |
| 能力调用拦截 | `PermissionEnforcer` | Plugin SDK |
| 数据所有权 | `BaseTenantEntity` | 数据视图 |
| 审计 | 记录 `user_id` | Audit Spec |

## 2.2 缺失（❌）

| 缺口 | 说明 | 影响范围 |
|:-----|:-----|:---------|
| **数据按角色过滤** | RLS 只过滤 `tenant_id`，不过滤角色。市场角色可查询财务角色的 Session/Execution | Runtime 数据层 |
| **能力按角色可见** | Capability discover API 返回全租户能力，不按角色过滤 | Capability Registry |
| **知识库按角色隔离** | KnowledgeBase/Document 无角色标签。市场角色 RAG 可检索财务文档 | Knowledge Base |
| **当前角色上下文** | 无"当前角色"概念。用户执行操作时不声明以哪个角色执行 | SDK 上下文 |
| **审计缺少角色信息** | AuditEvent 有 `user_id` 无 `role_id`，无法追溯"以什么角色执行" | Audit Spec |

---

# 三、方案设计

## 3.1 角色数据模型增强

### Role 实体

```
MUST: Role 包含以下字段
  - role_id:          string      — 全局唯一
  - tenant_id:        string      — 租户隔离
  - name:             string      — "市场分析员" / "财务主管"
  - permissions:      list[str]   — ["alarm:read", "work_order:write"]
  - data_scope:       "self" | "department" | "org" | "all"  (MUST)
  - knowledge_tags:   list[str]   — 可访问的知识文档标签 (SHOULD)。实际文档级控制见 Knowledge Base Spec §2.2 Document.accessible_roles
```

### User↔Role 关联（已有 tenant_account_joins 可扩展）

```
MUST: tenant_account_joins 增加 role_ids 字段
  - user_id:          string
  - tenant_id:        string
  - role_ids:         list[str]   — 用户拥有的角色列表
  - current_role_id:  string      — 当前活跃角色（运行时切换）
```

## 3.2 数据按角色过滤

### 三层防线（修订 v1.1）

```
第一层：Session/Execution 创建时写入 role_id
第二层：应用层数据权限（ORM 注入 WHERE 条件）— 按 data_scope 四层过滤
第三层：数据库 RLS 策略 — 仅做 tenant 隔离（兜底防线）
```

**设计决策：** 应用层负责 data_scope 过滤，数据库 RLS 仅做 tenant 隔离。理由：
- RLS 内无法高效读取 Role 表做四层判断（需要 JOIN + CASE WHEN）
- 应用层已有 User 对象和 Role 信息，过滤开销低
- RLS 作为最后一道防线：即使应用层被绕过，数据仍不会跨租户泄漏

### RLS 策略（PostgreSQL）— 仅 tenant 隔离

```sql
-- 由 Runtime SDK 在每次数据库连接建立时注入
-- SET LOCAL earp.user_id = 'u-123';
-- SET LOCAL earp.tenant_id = 't-456';

CREATE POLICY tenant_isolation ON sessions
  FOR SELECT USING (tenant_id = current_setting('earp.tenant_id', true));
```

### 应用层数据过滤 — 按 data_scope 四层

```python
# ORM 层：根据当前角色的 data_scope 构建 WHERE 条件
def build_data_filter(role: Role, user_id: str, user_roles: list[str]) -> dict:
    if role.data_scope == "self":
        return {"role_id": role.role_id, "user_id": user_id}
    elif role.data_scope == "department":
        # 同部门：role_id 在 user_roles 中
        return {"role_id": ("IN", user_roles)}
    elif role.data_scope == "org":
        return {}  # 同一租户内所有 role 的数据
    elif role.data_scope == "all":
        return {}  # 管理员：全租户无限制
    return {"role_id": role.role_id}  # 默认 self
```

## 3.3 能力按角色可见

### Capability discover API 增强

```
当前：GET /capabilities/search?q={query} → 返回全租户 Capability
增强后：
  GET /capabilities/search?q={query}&role_id={current_role}
  → 仅返回 current_role 有权调用的 Capability
  → 过滤条件：capability.required_permissions ⊆ role.permissions
```

### Capability Registry 变更

| 变更 | 说明 |
|:-----|:-----|
| `BusinessCapability` 增加 `visible_roles` | 显式声明哪些角色可见（可选，默认所有） |
| discover() 增加 `role_id` 参数 | 按角色过滤返回结果 |
| 检索索引不包含不可见 Capability | pgvector 搜索时过滤 |

## 3.4 知识库按角色隔离

### KnowledgeBase/Document 增加角色标签

```
MUST: Document 创建时 accessible_roles 默认为 [创建者当前角色]，而非空数组
      空数组 [] = 管理员显式确认"对所有角色开放"（默认封闭原则）
MUST: Document 增加 accessible_roles: list[str]
  - [] = 管理员已确认全开放（需显式操作）
  - ["market_analyst", "reporter"] = 仅指定角色可访问
  - 缺少标签时 → 仅创建者角色可见

SHOULD: 生产环境建议 accessible_roles 为 MUST 字段，
        防止遗漏标签导致跨角色泄漏
```

### RAG 检索时角色过滤

```
检索流程：
  User query → embed → pgvector search
    → WHERE tenant_id = ? AND (accessible_roles @> ARRAY[current_role] OR accessible_roles = '{}')
    → 默认封闭：新 Document 的 accessible_roles = [创建者角色]，不可见其他角色
    → 空数组 [] = 管理员显式全开放（@> 不匹配空数组，需 OR 兜底）
    → 返回过滤后的 Chunk 列表
```

## 3.5 SDK 侧：当前角色上下文

### CapabilityContext 增强

```python
@dataclass
class CapabilityContext:
    session_id: str
    request_id: str
    user_id: str | None
    tenant_id: str | None
    role_id: str | None          # 新增：当前角色 ← Policy Center 权限评估入口
    user_roles: list[str]        # 新增：用户拥有的所有角色 ← 数据过滤入口
```

### RuntimeClient 增强

```python
# create_session 时指定当前角色
session = await client.create_session(
    user_id="u1",
    tenant_id="t1",
    role_id="market_analyst"     # 新增：当前操作角色
)
```

### 角色切换

```python
client.set_tenant_id("t1")
client.switch_role("finance_manager")  # 新增
# 后续 create_session 默认使用新角色
```

## 3.6 审计增强

```
MUST: AuditEvent.detail 增加以下字段（符合 Audit Spec v1.1 JSONB 存储格式）
  - role_id:          string      — 操作时的当前角色
  - user_roles:       list[str]   — 用户拥有的所有角色（用于追溯）

MUST: 以下事件记录 role_id
  - SESSION_CREATED
  - EXECUTION_STARTED / COMPLETED / FAILED
  - CAPABILITY_CALL
  - PERMISSION_DENIED（记录"以什么角色被拒绝"）
  - KNOWLEDGE_RETRIEVAL
```

---

# 四、变更清单

## 4.1 规范层（3 份更新 + 1 份新建）

| # | 规范 | 版本 | 变更 |
|:-:|:-----|:----:|:-----|
| 1 | Policy Center Spec | v1.0→v1.1 | §5.1 RBAC 增加角色切换规则；§5.3 Data Scope 细化 four-level 语义 |
| 2 | Multi-Tenant Spec | v1.1→v1.2 | 新增 §5.4 角色级数据隔离（RLS + role_id 链路） |
| 3 | Capability Spec | v1.1→v1.4 | discover() 增加 role_id 过滤；BusinessCapability 增加 visible_roles（注：v1.1→v1.3 已有变更为三层结构+fallback_capability_id，不在此列出） |
| 4 | Audit Spec | v1.1→v1.2 | AuditEvent.detail 增加 role_id + user_roles |
| 5 | Knowledge Base Spec | v1.0（新建） | 已有 L2-09-Conversation，需要新建 L2-11-KNOWLEDGE |

## 4.2 SDK 层（3 个包）

| 包 | 文件 | 变更 |
|:----|:-----|:-----|
| core-py | — | — |
| capability-py | `context.py` | CapabilityContext 增加 role_id + user_roles + switch_role() |
| runtime-py | `client.py` | create_session 增加 role_id 参数；switch_role() |
| plugin-py | — | — |
## 4.3 数据层（DDL）

| 表 | 变更 |
|:-----|:-----|
| sessions | ADD role_id VARCHAR |
| executions | ADD role_id VARCHAR |
| audit_logs | 在 detail JSONB 字段中增加 role_id + user_roles（与 Audit Spec v1.2 对齐） |
| documents（knowledge base） | ADD accessible_roles TEXT[] |
| tenant_account_joins | ADD role_ids TEXT[], current_role_id VARCHAR |

---

# 五、实施顺序

| 顺序 | 任务 | 依赖 |
|:----:|:-----|:-----|
| 1 | 写方案设计文档（本文档） | — |
| 2 | Policy Center Spec v1.1（角色切换规则） | 1 |
| 3 | Multi-Tenant Spec v1.2（角色数据隔离） | 1 |
| 4 | SDK CapabilityContext + role_id | 3 |
| 5 | Capability discover + role 过滤 | 4 |
| 6 | Knowledge Base 角色标签 + RAG 过滤 | 4 |
| 7 | Audit 增强 | 4 |

---

# 六、示例场景

## 市场分析员查询 RAG

```
1. User (roles: [market_analyst, reporter]) 登录，选择当前角色 market_analyst
2. 输入查询 "上季度库存报表"
3. RAG 检索：
   → embed(query) → pgvector search
   → WHERE tenant_id = 't1' AND accessible_roles @> ARRAY['market_analyst']
   → 返回 3 个市场文档（不包含财务部的库存报表，财务文档 accessible_roles=['finance_manager']）
4. LLM 基于 3 个市场文档生成回答
```

## 市场分析员尝试调用财务能力

```
1. Role market_analyst: permissions = ["marketing:read", "report:read"]
2. Capability "query_finance_ledger": required_permissions = ["finance:read"]
3. Policy Center 评估：market_analyst 不满足 finance:read → 403 + PERMISSION_DENIED 审计
4. Capability discover("库存") 时，query_finance_ledger 因权限不足被过滤，不出现在结果中
```

## 财务主管查看所有部门的执行记录

```
1. Role finance_manager: data_scope = "all", permissions = ["finance:*", "report:read"]
2. 查询 Execution 列表：应用层 data_scope="all" → 无 role_id 过滤 → 返回全部角色执行记录
3. 对比：Role market_analyst: data_scope = "department" → 只能看到自己拥有角色的执行记录（market_analyst + reporter，即 role_id IN (user_roles)）
```
