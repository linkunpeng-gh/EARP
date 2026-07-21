# PRD-2026-028: Web Admin Dashboard

**版本**: v1.1 (codex r1 修复)
**日期**: 2026-07-21
**状态**: Phase 0 — 待人工审核

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
| 样式 | Simple.css (10KB CDN) | 无 npm，提供基础表格/表单/按钮样式 |
| 部署 | 同一个 FastAPI app | `StaticFiles(directory="static")` serve HTML/JS/CSS |
| 未来升级 | Vite + Vue 3 完整工具链 | 组件语法完全兼容，加 build step 即可 |
| 不选 | React/Svelte | 团队未来方向是 Vue |

**依赖**: `simple.css` (CDN), `petite-vue` (CDN), `vue` (CDN, 仅 dev 模式带 warnings)
**目录结构**:
```
apps/earp-server/static/admin/
├── index.html              # Dashboard home
├── css/
│   └── admin.css           # 补充样式（覆盖 simple.css 默认值）
├── js/
│   └── app.js              # Vue app 入口 + 全局状态（token/tenant）
└── pages/
    ├── sessions.html       # Sessions 列表+详情
    ├── capabilities.html   # Capability 注册+发现
    ├── plan.html           # Plan & Invoke
    ├── knowledge.html      # Knowledge Base
    ├── conversations.html  # Conversation 管理
    ├── stream.html         # Streaming 测试
    ├── audit.html          # Audit Logs
    └── login.html          # 登录页 (prod)
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
| 6 | Conversation | `/admin/conversations` | `POST /conversations`, `POST /conversations/{id}/messages` |
| 7 | Streaming | `/admin/stream` | `POST /stream/invoke` → SSE |
| 8 | Audit Logs | `/admin/audit` | `GET /admin/api/audit-logs?page=&event_type=&tenant_id=` |
| 8 | Langfuse | `/admin/observability` | iframe `{EARP_LANGFUSE_HOST}` (通过环境变量配置，默认 `http://localhost:3000`) |

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
| Audit | `GET /admin/api/audit-logs?page=&event_type=&tenant_id=` | **需要新端点** |

**新增端点**: 2 个 (`GET /v1/sessions` 列表 + `GET /admin/api/audit-logs`)

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
┌──────────────────────────────────────────┐
│ Intent: [________________] [Plan]        │
├──────────────────────────────────────────┤
│ Steps:                                   │
│ 1. cap-demo-echo → {msg: "hello"}        │
│                              [Invoke]    │
├──────────────────────────────────────────┤
│ Result: {"echo": {"message": "hello"}}   │
└──────────────────────────────────────────┘
```

### 4. Streaming
```
┌──────────────────────────────────────────────────┐
│ Prompt: [__________________________] [Stream]    │
│ Session ID: [auto-create ▼] [sess-abc123]        │
├──────────────────────────────────────────────────┤
│ Hello world, this is a streaming                 │
│ response from the LLM...                         │
└──────────────────────────────────────────────────┘
```
支持自动创建临时 Session 或选择已有 Session。

### 5. Audit Logs
```
┌──────────────────────────────────────────────────┐
│ From: [2026-07-01] To: [2026-07-21]              │
│ Event: [▼all] Tenant: [______] [Search]          │
├──────────────────────────────────────────────────┤
│ 2026-07-21 10:00 | execution.completed           │
│   exec-abc → cap-demo-echo → OK                 │
│                ← 1 2 3 ... 10 →                  │
└──────────────────────────────────────────────────┘
```
分页：每页 50 条，按 `created_at DESC`。日期范围 + event_type + tenant_id 筛选。

---

## 六、安全

| 维度 | 方案 |
|:---|:---|
| 认证 | 通过环境变量 `EARP_AUTH_STRATEGY=dev-skip` 跳过 JWT（仅本地开发，默认关闭）。生产环境 `/admin/login` → JWT 签发后存 localStorage，所有 API 请求带 `Authorization: Bearer <token>` |
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
