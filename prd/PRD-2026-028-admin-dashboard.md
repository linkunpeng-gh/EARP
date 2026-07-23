# PRD-2026-028: Web Admin Dashboard

**版本**: v1.7 (页面功能说明)
> **v2.1 备注**：Data Domains 管理页面（§6.6）为 v2.1 新增
**日期**: 2026-07-21
**状态**: Phase 1 — 待人工审核

---

## 一、定位

EARP 目前纯 API，无人能直接使用。Admin Dashboard 提供 Web 管理界面，让平台从"能用"变成"可用"。

**一句话**: 一个单页 Web 应用，用 EARP 自己的 REST API 管理 Sessions、Capabilities、Plans、Audit Logs、LLM Streaming。

---

## 二、技术选型

| 维度 | 决策 | 理由 |
|:---|:---|:---|
| 渲染 | Vue 3 (petite-vue, 6KB CDN) | 零构建工具链，`v-if`/`v-for`/`v-model` 开箱即用 |
| 交互 | 客户端渲染 + REST API 直调 | 无需服务端模板，前后端解耦 |
| 样式 | 自定义 CSS (Linear Dark 设计系统) | 基于 popular-web-designs Linear 模板，暗色主题，Inter 字体，零依赖 |
| 部署 | 同一个 FastAPI app | `app.mount("/admin", StaticFiles(directory="apps/earp-admin", html=True))` |
| 未来升级 | Vite + Vue 3 完整工具链 | 组件语法完全兼容，加 build step 即可 |
| 不选 | React/Svelte | 团队未来方向是 Vue |

**依赖**: `simple.css` (CDN), `petite-vue` (CDN), `vue` (CDN, 仅 dev 模式带 warnings)
**目录结构**:
```
apps/earp-admin/
├── index.html              # Dashboard home
├── css/
│   └── admin.css           # 补充样式
├── js/
│   └── app.js              # Vue app 入口 + 全局状态
└── pages/
    ├── sessions.html
    ├── capabilities.html
    ├── plan.html
    ├── knowledge.html
    ├── conversations.html
    ├── stream.html
    ├── audit.html
    ├── data-domains.html
    └── login.html
```

---

## 三、页面清单

| # | 页面 | 路由 | 数据来源 |
|:--|:---|:---|:---|
| 1 | Dashboard Home | `/admin/` | per-tenant 汇总统计 |
| 2 | Sessions | `/admin/sessions` | `GET /v1/sessions` (列表) + `GET /v1/sessions/{id}` (详情) |
| 3 | Capabilities | `/admin/capabilities` | `GET /capabilities`, `POST /capabilities` |
| 4 | Plan & Invoke | `/admin/plan` | `POST /plan` → `POST /v1/sessions/{id}/invoke` |
| 5 | Knowledge Base | `/admin/knowledge` | `POST /knowledge/documents`, `POST /knowledge/search` |
| 6 | Data Domains | `/admin/data-domains` | `GET /admin/api/data-domains`（新增 admin API） |
| 7 | Conversation | `/admin/conversations` | `POST /conversations`, `POST /conversations/{id}/messages` |
| 8 | Streaming | `/admin/stream` | `POST /stream/invoke` → SSE |
| 9 | Audit Logs | `/admin/audit` | `GET /admin/api/audit-logs?page=&event_type=&tenant_id=` |
| 10 | Langfuse | `/admin/observability` | iframe `{EARP_LANGFUSE_HOST}` (通过环境变量配置，默认 `http://localhost:3000`) |

---

## 四、API 映射

| 页面 | 用到的 API | 新增端点 |
|:---|:---|:---:|
| Dashboard | `SELECT count(*) FROM sessions/executions WHERE tenant_id=?` | 否 |
| Sessions | `GET /v1/sessions` (列表), `GET /v1/sessions/{id}` | **需要新端点** |
| Capabilities | `GET /capabilities`, `POST /capabilities` | 否 |
| Plan & Invoke | `POST /plan`, `POST /v1/sessions/{id}/invoke` | 否 |
| Knowledge Base | `POST /knowledge/documents`, `POST /knowledge/search` | 否 |
| Conversation | `POST /conversations`, `POST /conversations/{id}/messages`, `GET /conversations/{id}/messages` | 否 |
| Streaming | `POST /stream/invoke` | 否 |
| Data Domains | `GET /admin/api/data-domains`（列表）| **需要新端点** |
| Audit | `GET /admin/api/audit-logs?page=&event_type=&tenant_id=` | **需要新端点** |

**新增端点**: 3 个 (`GET /v1/sessions` 列表 + `GET /admin/api/data-domains` + `GET /admin/api/audit-logs`)

### 四-B、API 设计约定

**v1 API（通用端点）**:
- `GET /v1/sessions` 是标准 EARP REST API，任何客户端均可使用（非 Dashboard 专用）
- 分页参数：`?page=1&page_size=20`，响应格式：`{"items": [...], "total": N, "page": 1, "page_size": 20}`
- 筛选参数：`?status=active&user_id=u1`
- 认证：JWT Bearer token

**admin API（管理端点）**:
- `/admin/api/*` 是管理后台专用端点，与 v1 API 隔离
- 认证：除 JWT 外，可附加 admin role 检查（`admin` permission required）
- 速率限制：1000 req/min（高于 v1 API 的 100 req/min）
- 未来扩展：用户管理、租户管理、系统配置等管理功能统一放在此前缀下
- `GET /admin/api/audit-logs` 为首个 admin API；`GET /admin/api/data-domains` 为第二个（v2.1 新增）`

---

## 五、页面设计（草图）

### 1. Dashboard Home
```
┌──────────────────────────────────────────┐
│ EARP Admin                     [tenant-demo]│
├──────────┬──────────┬──────────┬──────────┤
│ Sessions │ Executions│  Caps   │  Audit  │
│   12     │   47     │    5    │   89    │
├──────────┴──────────┴──────────┴──────────┤
│ 快捷操作: [New Session] [Plan Intent]      │
└──────────────────────────────────────────┘
```
注意：所有计数均为当前租户 (`tenant-demo`) 作用域。

### 2. Sessions
```
┌──────────────────────────────────────────────────┐
│ Sessions  [Status: ▼all] [User ID: ______] [Search]│
│                                    [Create New]   │
├──────────────────────────────────────────────────┤
│ sess-abc123 | u1 | active  | 2026-07-21 10:00   │
│ sess-def456 | u2 | closed  | 2026-07-20 09:30   │
│                ← 1 2 3 ... 5 →                   │
└──────────────────────────────────────────────────┘
```
分页：每页 20 条。筛选：状态下拉（all/active/closed）+ 用户 ID 搜索框。

### 3. Plan & Invoke
```
┌──────────────────────────────────────────────────┐
│ Intent: [__________________________] [Plan]      │
│ Session: [sess-abc123 ▼]                        │
├──────────────────────────────────────────────────┤
│ ▶ Session Context (collapsed)                    │
├──────────────────────────────────────────────────┤
│ Steps:                                           │
│ 1. cap-demo-echo → {msg: "hello"}               │
│                              [Invoke]           │
├──────────────────────────────────────────────────┤
│ Result: {"echo": {"message": "hello"}}           │
└──────────────────────────────────────────────────┘
```
Session Context 可折叠区域：展开后显示 `GET /v1/sessions/{id}` 返回的 session 状态（status、created_at、metadata），帮助调试时理解当前上下文。

### 4. Streaming
```
┌──────────────────────────────────────────────────┐
│ Prompt: [__________________________] [Stream]    │
│ Session: [auto-create ▼] [Load from list...]     │
├──────────────────────────────────────────────────┤
│ Hello world, this is a streaming                 │
│ response from the LLM...                         │
└──────────────────────────────────────────────────┘
```
支持自动创建临时 Session、手动输入 Session ID、或点击按钮从弹出列表中选取已有 Session。

### 5. Audit Logs
```
┌──────────────────────────────────────────────────┐
│ From: [2026-07-01] To: [2026-07-21]              │
│ Event: [▼all]                    [Search]        │
├──────────────────────────────────────────────────┤
│ 2026-07-21 10:00 | execution.completed           │
│   exec-abc → cap-demo-echo → OK                 │
│                ← 1 2 3 ... 10 →                  │
└──────────────────────────────────────────────────┘
```
分页：每页 50 条，按 `created_at DESC`。筛选：日期范围 + event_type。tenant_id 由 JWT 自动注入，普通管理员不暴露 Tenant 选择器（超级管理员可见）。

---

 

## 六、页面功能说明

---

### 6.1 Dashboard Home (`index.html`)

**用途**: 平台总览——快速了解当前租户的运行状态，提供各模块的快捷入口。

**角色**: 所有登录用户（租户管理员、开发者、运维）。

**场景**: 用户登录后看到的第一个页面。检查 Sessions/Executions 数量是否异常，快速跳转到常用功能。

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| Sessions 计数 | 只读数字 | 当前租户下 active + closed 的 Session 总数。点击跳转 Sessions 页面 |
| Executions 计数 | 只读数字 | 当前租户下的 Execution 总数。点击跳转 Executions 详情（Phase 2） |
| Capabilities 计数 | 只读数字 | 已注册的 Capability 数量。点击跳转 Capabilities 页面 |
| Audit Events 计数 | 只读数字 | 当前租户的审计事件总数。点击跳转 Audit Logs 页面 |
| New Session 按钮 | 快捷操作 | 跳转到 Sessions 页面并触发新建 Session 流程 |
| Plan Intent 按钮 | 主要 CTA | 跳转到 Plan & Invoke 页面——最高频的管理操作 |

**数据来源**: 后端直接 SQL `SELECT count(*) FROM sessions/executions/capabilities/audit_logs WHERE tenant_id=?`。每次页面加载刷新。

---

### 6.2 Sessions (`pages/sessions.html`)

**用途**: 管理 EARP 的执行会话——创建、查看、筛选、关闭 Session。

**角色**: 租户管理员（创建/关闭）、开发者（调试用）、运维（监控 active 会话数）。

**场景**:
- 开发者创建新 Session 准备测试 Plan/Invoke
- 管理员查看当前有多少 active Session，关闭异常 Session
- 运维排查某个 Session 的 Execution 链路

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| Status 下拉 | 筛选器 | 选项: `all` / `active` / `closed`。默认 `all`。筛选后表格仅显示匹配状态的 Session |
| User ID 输入框 | 筛选器 | 文本输入。输入用户 ID（如 `u1`）后点击 Search，表格仅显示该用户的 Session |
| Search 按钮 | 操作 | 应用 Status + User ID 筛选条件，重新加载表格 |
| + New Session 按钮 | 操作 | 调用 `POST /v1/sessions` 创建新 Session。创建成功后自动选中该 Session |
| 表格 | 数据展示 | 列: Session ID / User / Status / Created / View |
| Status 列 | 状态指示 | `● active`（绿色圆点）表示活跃；`closed` 表示已关闭 |
| View 链接 | 操作 | 跳转到 Session 详情页（Phase 2）。当前展示 Session 基本信息 + 关联的 Execution 列表 |
| 分页导航 | 控件 | `← Prev` / `Page N of M` / `Next →`。每页 20 条，`ORDER BY created_at DESC` |

**API**: `GET /v1/sessions?page=1&page_size=20&status=active&user_id=u1`（新增端点）

---

### 6.3 Capabilities (`pages/capabilities.html`)

**用途**: 管理 EARP 的能力注册表——搜索、查看、注册新的 Capability。

**角色**: 平台开发者（注册新 Capability）、租户管理员（查看可用能力）。

**场景**:
- 开发者部署了新的 Connector 后，注册对应的 Capability
- 管理员在 Plan 之前查看当前有哪些可用的 Capability
- 使用语义搜索（pgvector）发现与需求匹配的 Capability

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| Search 输入框 | 筛选器 | 文本输入。支持语义搜索（通过 embedding 匹配），也支持关键字精确匹配 |
| Discover 按钮 | 操作 | 调用 `GET /capabilities?query=` 执行语义/关键字搜索。无 query 时返回所有 Capability |
| + Register Demo 按钮 | 操作 | 调用 `POST /capabilities` 注册一个 demo 能力（`cap-demo-echo`）。生产环境替换为注册表单 |
| 表格 | 数据展示 | 列: ID / Domain / Name / Type / Version |
| Type 列 | 标签 | 显示 Capability 类型: `query`（查询）、`action`（操作）、`llm`（LLM 调用） |

**API**: `GET /capabilities?query=echo&role_id=r1`（已有端点，含 pgvector 语义搜索 + role 过滤）

---

### 6.4 Plan & Invoke (`pages/plan.html`)

**用途**: EARP 核心调试工具——将自然语言意图转化为可执行步骤，并端到端验证执行结果。

**角色**: 平台开发者（调试 Capability 链路）、租户管理员（验证 Plan 结果）。

**场景**:
- 开发者输入意图 "echo hello" → Plan → 查看 LLM 返回的 steps → Invoke 验证
- 调试 multi-step Plan：检查 LLM 是否返回了正确的能力匹配
- 端到端验证：Plan → Invoke → 查看 Result 是否符合预期

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| Intent 输入框 | 必填 | 自然语言意图描述（如 "echo hello"）。传递给 `POST /plan` |
| Plan 按钮 | 主要 CTA | 调用 `POST /plan {intent: "..."}` → LLM 返回 `[{step_id, capability_id, input}]` → 展示在 Steps 表格 |
| Session 下拉 | 选择器 | 选择当前操作的 Session。选项: 已有的 active Session（如 `sess-abc123`）或 `+ New Session`（自动创建） |
| Session Context 面板 | 可折叠 | 展开后显示 `GET /v1/sessions/{id}` 的返回值：status、created_at、metadata。帮助理解当前执行上下文 |
| Steps 表格 | 数据展示 | 列: # / Capability / Input / Invoke 按钮。每行一个步骤 |
| Invoke 按钮 | 操作 | 对当前步骤调用 `POST /v1/sessions/{id}/invoke {capability_call: {...}}`。执行后 Result 区域显示返回的 JSON |
| Result 区域 | 只读 | `<pre><code>` 显示 Invoke 返回的完整 JSON。成功时显示 `result.output`，失败时显示错误信息 |

**API 链路**:
1. `POST /plan {intent: "echo hello"}` → 返回 `[{capability_id: "cap-demo-echo", input: {msg: "hello"}}]`
2. `POST /v1/sessions/{id}/invoke {capability_call: {adapter_type: "demo.echo", input: {msg: "hello"}}}` → 返回 `{result: {echo: {message: "hello"}}}`

---

### 6.5 Knowledge Base (`pages/knowledge.html`)

**用途**: 管理 EARP 的知识库——上传文档、搜索相关内容。文档上传后自动分块（chunking）+ 向量化（embedding），供 LLM Planner 检索。

**角色**: 知识库管理员（上传/维护文档）、平台开发者（测试搜索）。

**场景**:
- 管理员上传产品文档，使 LLM 能基于文档回答问题
- 开发者测试搜索功能：输入查询 → 检查返回的 chunk 是否相关
- 监控文档索引状态：哪些文档已分块/嵌入完成
- 按 Data Domain 过滤知识库和文档，查看 DD → KB → 文档的从属关系；创建/编辑/删除 KB

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| Data Domain 下拉 | 筛选器 | 按 Data Domain 过滤 KB 和文档列表。选项: all / equipment_data / hr_data / corporate_data。切换后两个表同步过滤 |
| Search 输入框 | 筛选器 | 文本输入。调用 `POST /knowledge/search` 执行语义搜索 |
| Search 按钮 | 操作 | 触发搜索，显示匹配的 chunk 列表（含相关度分数） |
| + New KB 按钮 | 操作 | 打开 KB 创建表单。Save 后调用 `POST /knowledge/bases` |
| KB 创建/编辑表单 | 表单 | 行内表单面板。字段: KB name / Description / Data Domain。Edit 模式预填 |
| KB 表格 | 数据展示 | 列: KB ID / Name / Data Domain(标签) / Documents / Chunks / Created / Actions(Edit+Del)。点击 KB 名称可过滤到该 KB 下的文档列表 |
| Edit 按钮(每行) | 操作 | 打开 KB 编辑表单，预填当前值 |
| Del 按钮(每行) | 操作 | 确认对话框后调用 `DELETE /knowledge/bases/{kb_id}` |
| 文档表格 | 数据展示 | 列: Doc ID / Title / Knowledge Base / Data Domain(标签) / Classification(下拉编辑器，可修改) / Chunks / Status |
| Classification 下拉编辑器 | 表单(行内) | 每篇文档的 data_classification 支持行内修改。下拉选项: public / internal / confidential / restricted。修改后立即生效，受 domain 天花板约束（不可高于所属域的分类等级）。降级操作（如 confidential→internal）影响文档可见范围扩大，需确认对话框 |
| Document title 输入框 | 表单 | 文档标题 |
| Content 文本域 | 表单 | 文档正文内容 |
| Upload Data Domain 下拉 | 表单 | 指定上传文档的归属 Data Domain（决定继承哪个域的 data_classification 治理边界）|
| Upload 按钮 | 操作 | 调用 `POST /knowledge/documents` 上传文档。后端自动分块 + 嵌入 → 写入 `documents` + `chunks` 表 |

**API**:
- `POST /knowledge/documents {title: "...", content: "...", data_domain_id: "equipment_data"}` → 返回 `{document_id: "doc-001"}`
- `POST /knowledge/search {query: "...", top_k: 10}` → 返回 `[{chunk_id, content, score, data_domain_id}]`

---
### 6.6 Data Domains (`pages/data-domains.html`) — v2.1 新增

**用途**: 管理 EARP 的数据域——查看所有 Data Domain、钻取域下的 KB 和文档、配置角色访问权限。

**角色**: 平台开发者和知识管理员。

**场景**:
- 知识管理员注册新的 Data Domain（如 "设备数据"）并关联到 Business Domain
- 管理员查看当前有哪些 Data Domain、各域的 KB 数量和文档总量
- 点击展开 DD → KB → 文档的三层钻取，查看每个 DD 下有哪些 KB、每个 KB 下有哪些文档
- 为每个 DD 配置哪些角色可以访问、以及各自的最高数据分类等级

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| 表格 | 数据展示 | 列: (展开箭头) / ID / Name / Classification(标签) / Owner / Mapped BD / KB Count / Doc Count / Role Access(含按钮) / Status |
| 展开箭头 ▶ | 交互 | 点击 DD 行展开其下的 KB 列表（子表格）；点击 KB 行展开其下的文档列表。形成 DD → KB → 文档的三层钻取 |
| Role Access 按钮 | 交互 | 点击展开角色权限配置面板，显示当前有哪些角色可以访问该 DD |
| max_classification 下拉 | 表单 | 每个角色-DD 对可单独设置最高分类等级（public / internal / confidential / restricted）。等级链为包含关系：高等级自动覆盖低等级 |
| Grant Access 下拉+按钮 | 操作 | 选择角色 + 点击 Grant Access → 为该角色授予该 DD 的访问权限（默认 internal）|
| Revoke 按钮 | 操作 | 收回某角色对该 DD 的访问权限。从 `roles.data_domain_access` 中移除对应条目 |
| + New Domain 按钮 | 操作 | 打开创建表单（name, classification, owner, mapped BD）|
| 筛选器 | 下拉 | 按 data_classification 过滤（all / public / internal / confidential / restricted）|

**访问等级定义**:

| 等级 | 含义 | 应用场景示例 |
|:----|:-----|:------------|
| public | 完全公开，不涉及企业机密 | 官网产品手册、已公开发布的白皮书 |
| internal | 企业内部可用，不宜对外公开 | 内部操作规范、部门周报、请假流程（默认等级）|
| confidential | 敏感，仅限于特定岗位 | 安全审计报告、员工绩效、安全隐患列表 |
| restricted | 最高机密，仅限少数人 | 法务合规审查、纪律处分档案、商业秘密图纸 |

等级是包含关系：`restricted` 可看所有等级，`confidential` 可看 public+internal+confidential，以此类推。

### 双层分类模型

Data Domain 和 Document 各有 `data_classification`，但含义不同、层级不同：

```
data_domains.data_classification        ← 域的天花板上限（"这个域最多能装什么等级的文档"）
    ↓ 约束
documents.data_classification           ← 文档的实际等级（"这篇文档的敏感程度"）
```

关系：`document.data_classification ≤ data_domain.data_classification`——文档等级不能超过所属域的天花板。

| 域 | 域天花板 | 文档示例 | 合规 |
|:---|:--------|:--------|:----:|
| Equipment Data(confidential) | confidential | 维护手册 → internal | ✅ |
| Equipment Data(confidential) | confidential | 安全审计 → confidential | ✅ 等于天花板 |
| Equipment Data(confidential) | confidential | 并购尽调 → restricted | ❌ 被拒绝 |
| HR Policies(confidential) | confidential | 请假流程 → internal | ✅ |
| Corporate Standards(internal) | internal | 公司价值观 → public | ✅ |
| Corporate Standards(internal) | internal | 内部审计报告 → confidential | ❌ 被拒绝 |

### 完整授权过滤链

用户请求一篇文档时，经过三层过滤：

```
1. Data Domain 授权（角色级）
   └── Role.data_domain_access 中是否有该域？无 → 返回空

2. 文档等级 ≤ 角色在该域的最高等级（文档级）
   └── document.data_classification ≤ role.max_classification？否 → 跳过
       等级链：public(0) < internal(1) < confidential(2) < restricted(3)

3. 文档的角色白名单（文档级，向后兼容）
   └── Document.accessible_roles 包含当前 role？无 → 跳过
```

三层都通过 = 返回文档给用户。任何一层失败 = 静默过滤（不报错，不影响其他层的结果）。
- `GET /admin/api/data-domains`（列表，含 KB 和文档的聚合计数）
- `POST /admin/api/data-domains`（创建新域）
- `GET /admin/api/roles/{role_id}/data-domain-access`（查询角色 DD 权限）
- `PUT /admin/api/roles/{role_id}/data-domain-access`（更新角色 DD 权限）

---



### 6.7 Conversations (`pages/conversations.html`)

**用途**: 管理多轮对话——创建对话、查看消息历史。Conversation 是管理前端（如聊天 UI、客服系统）与 EARP 交互的容器。

**角色**: 应用开发者（调试对话流程）、客服管理员（查看对话记录）。

**场景**:
- 开发者创建新 Conversation → 添加消息 → 查看 LLM 的回复链路
- 管理员查看某个 Conversation 的消息历史，排查用户反馈
- 追踪 Conversation 的 message 数量，监控 API 使用量

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| + New Conversation 按钮 | 操作 | 调用 `POST /conversations {title: "..."}` 创建新对话 |
| 表格 | 数据展示 | 列: ID / Title / Messages / Created。Messages 为该对话的消息总数 |
| 表格行点击 | 交互 | 点击某行展开消息列表，显示逐条 message 的 role/content |

**API**:
- `POST /conversations {title: "Support Chat"}` → 返回 `{conversation_id: "conv-001"}`
- `POST /conversations/{id}/messages {role: "user", content: "..."}` → LLM 回复
- `GET /conversations/{id}/messages` → 返回消息列表

---

### 6.8 Streaming (`pages/stream.html`)

**用途**: 实时测试 LLM 流式输出——输入 prompt，逐 token 查看 LLM 生成过程。是调试 LLM 行为和验证流式管道的核心工具。

**角色**: 平台开发者（调试流式管道）、LLM 工程师（评估 LLM 输出质量）。

**场景**:
- 开发者测试 `/stream/invoke` SSE 端点是否正常工作
- 评估不同 prompt 下 LLM 的 token 生成速度
- 验证 Ollama 流式 API 的稳定性

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| Prompt 输入框 | 必填 | 发送给 LLM 的 prompt 文本 |
| Stream 按钮 | 操作 | 调用 `POST /stream/invoke` → SSE 连接 → 实时显示每个 token |
| Session 下拉 | 选择器 | 选项: `auto-create`（自动创建临时 Session）、已有 Session ID |
| Load from list 按钮 | 操作 | 打开弹出模态框，从 Session 列表中选取一个已有 Session |
| 输出区域 | 只读 | 黑色背景（`#191a1b`），等宽字体。token 逐字追加显示。收到 `[DONE]` 时追加换行标记 |

**API**: `POST /stream/invoke {prompt: "...", system: "", session_id: ""}` → SSE `text/event-stream` → `data: {"token": "...", "index": N}` → `data: [DONE]`

---

### 6.9 Audit Logs (`pages/audit.html`)

**用途**: 查看平台审计日志——追踪所有执行事件、排查问题、满足合规要求。所有 EARP 操作（Session 创建→Plan→Invoke→完成）均产生审计事件。

**角色**: 安全管理员（合规审计）、租户管理员（排查问题）、超级管理员（跨租户查询）。

**场景**:
- 安全审计：查看过去 7 天的所有 execution 事件
- 问题排查：某次 Invoke 失败后，按 event_type 筛选 `execution.failed` 事件
- 合规检查：导出指定日期范围内的审计日志

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| From 日期 | 筛选器 | 起始日期（默认 7 天前）。`date` 类型输入框 |
| To 日期 | 筛选器 | 结束日期（默认今天） |
| Event 下拉 | 筛选器 | 选项: `all` / `session.created` / `execution.started` / `execution.completed` / `execution.failed` |
| Search 按钮 | 操作 | 应用所有筛选条件，重新加载日志列表 |
| 日志列表 | 数据展示 | 每条日志一行。格式: `时间 | event_type | 详情`。等宽字体，按 `created_at DESC` 排序 |
| 分页导航 | 控件 | `← Prev` / `Page N of M` / `Next →`。每页 50 条 |
| Tenant 选择器 | 筛选器 | **仅超级管理员可见**。普通管理员的 tenant_id 从 JWT 自动注入，不暴露此控件 |

**安全**: 普通用户只能查看本租户日志（tenant_id 从 JWT 提取）。超级管理员（`role: admin`，`data_scope: all`）可切换租户查看。

**API**: `GET /admin/api/audit-logs?page=1&page_size=50&event_type=execution.failed&from=2026-07-01&to=2026-07-21` → `{items: [...], total: 89, page: 1, page_size: 50}`（新增端点，admin permission required）

---

### 6.10 Langfuse (`pages/observability.html` — Phase 2)

**用途**: 内嵌 Langfuse 可观测性面板——查看 LLM 调用的 trace、token 用量、延迟分布、错误率。

**角色**: LLM 工程师（模型评估）、平台运维（成本监控）。

**场景**:
- 查看本周的 LLM token 消耗总量
- 分析某次 Plan 调用的完整 trace（prompt→LLM→output→validation）
- 监控 embedding 调用的延迟和错误率

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| iframe | 内嵌 | `<iframe src="{EARP_LANGFUSE_HOST}">`。通过环境变量 `EARP_LANGFUSE_HOST` 配置，默认 `http://localhost:3000` |

**配置**: 不需要代码修改。生产环境设置 `EARP_LANGFUSE_HOST=https://langfuse.example.com`。

---

## 七、安全

| 维度 | 方案 |
|:---|:---|
| 认证 | 生产环境：JWT Bearer token 鉴权（`EARP_AUTH_STRATEGY=jwt` 或未设置，默认要求认证）。本地开发：显式设置 `EARP_AUTH_STRATEGY=dev-skip` 跳过 JWT，应用启动时若检测到 `dev-skip` 且 `EARP_APP_ENV` 非 dev/test 则拒绝启动。 |
| 授权 | 所有 API 请求在 `Authorization: Bearer <token>` header 携带 JWT |
| CSRF | 不适用 — SPA 纯 Bearer token 鉴权，无 cookie 会话 |
| 租户隔离 | Dashboard 统计/Sessions 列表/Audit 查询全部按当前 JWT 的 `tenant_id` 过滤 |
| 速率限制 | admin 端点 1000 req/min，普通 API 100 req/min（生产环境初始值，上线后根据监控调整） |

---

## 七、风险

| 风险 | 缓解 |
|:---|:---|
| petite-vue 学习曲线 | 仅用基础语法（v-if/v-for/v-model/@click），与完整 Vue 3 语法兼容 |
| 无前端测试 | Phase 3 人工验收 + curl 脚本覆盖关键路径 |
| Sessions 列表性能 | 分页 20 条/页，`ORDER BY created_at DESC LIMIT 20 OFFSET ?` |
| Audit 日志膨胀 | 分页 50 条/页，按需添加日期范围过滤 |
| 无服务端模板 | API 直调无 CSRF 风险（JWT Bearer token 在 header），不暴露 cookie |
