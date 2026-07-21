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
| 渲染 | 服务端渲染 (Jinja2) | 零前端构建工具链，复用 FastAPI |
| 交互 | htmx (2.0) | 无 JavaScript 框架，属性驱动动态更新 |
| 样式 | 独立 `<style>` 块 + Simple.css | 无 npm/tailwind，10KB 单文件，提供基础表格/表单/按钮样式 |
| 部署 | 同一个 FastAPI app | `Jinja2Templates(directory="templates")` + `StaticFiles(directory="static")` |
| 不选 | React/Vue/Svelte | 单人团队不需要前端工程化 |

**依赖**: `jinja2`, `python-multipart` (表单上传), `htmx` (CDN 单文件), `simple.css` (CDN 单文件)
**目录结构**: `apps/earp-server/templates/` + `apps/earp-server/static/`

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
| 9 | Langfuse | `/admin/observability` | iframe `http://localhost:3000` |

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
┌──────────────────────────────────────────┐
│ Sessions                        [Create] │
├──────────────────────────────────────────┤
│ sess-abc123 | u1 | active | 2026-07-21  │
│ sess-def456 | u2 | closed | 2026-07-20  │
│                ← 1 2 3 ... 5 →           │
└──────────────────────────────────────────┘
```
分页：每页 20 条。

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
┌──────────────────────────────────────────┐
│ Prompt: [________________] [Stream]      │
├──────────────────────────────────────────┤
│ Hello world, this is a streaming         │
│ response from the LLM...                 │
└──────────────────────────────────────────┘
```

### 5. Audit Logs
```
┌──────────────────────────────────────────┐
│ Filter: [event_type] [tenant]  [Search]  │
├──────────────────────────────────────────┤
│ 2026-07-21 10:00 | execution.completed   │
│   exec-abc → cap-demo-echo → OK         │
│ 2026-07-21 09:55 | execution.started     │
│   exec-abc → cap-demo-echo              │
│                ← 1 2 3 ... 10 →          │
└──────────────────────────────────────────┘
```
分页：每页 50 条，按 `created_at DESC`。

---

## 六、安全

| 维度 | 方案 |
|:---|:---|
| 认证 | dev: 跳过 JWT（本地开发）。prod: `/admin/login` 表单页（JWT 签发后存 cookie） |
| 授权 | admin 路由复用 JWT 中间件，无 token 时重定向到 `/admin/login` |
| CSRF | htmx 自动在请求头注入 `X-CSRFToken`（从 cookie 读取），服务端验证 |
| 租户隔离 | Dashboard 统计/Sessions 列表/Audit 查询全部按当前 JWT 的 `tenant_id` 过滤 |
| 速率限制 | admin 路由复用 `TokenBucketRateLimiter`，生产环境提高 admin 阈值 |

---

## 七、风险

| 风险 | 缓解 |
|:---|:---|
| htmx 学习曲线 | 仅用基础属性（hx-get/hx-post/hx-target/hx-swap） |
| Jinja2 模板膨胀 | 页面 ≤ 9 个，模板 ≤ 12 个，复杂度可控 |
| 无前端测试 | Phase 3 人工验收 + curl 脚本覆盖关键路径 |
| Sessions 列表性能 | 分页 20 条/页，`ORDER BY created_at DESC LIMIT 20 OFFSET ?` |
| Audit 日志膨胀 | 分页 50 条/页，按需添加日期范围过滤 |
