# Plan & Invoke 页面 - 设计方案

- 日期: 2026-07-22
- 状态: draft
- 关联 PRD: PRD-2026-028-admin-dashboard v1.7 §6.4

## 1. 背景与目标

Plan & Invoke 是 EARP Admin Dashboard 的核心调试工具——将自然语言意图转化为可执行步骤，端到端验证 LLM Planner 的推理质量和 Capability 执行结果。

**当前状态**：30 行纯静态骨架，零交互。Plan 按钮无 JS，Steps 为单行硬编码，Invoke/Result 未实现。

**目标**：实现完整调试工作流——Intent→Plan→Steps→Invoke→Result，覆盖正常/错误/Loading 全状态，支持历史 Session 查看。

## 2. 方案对比

### 方案 A：单 Result 区（PRD 原方案）
Steps 表 + 底部一个 Result 区，每次 Invoke 覆盖。简单，但无法对比多步结果。

### 方案 B：行内展开 Result ✅（选定）
点击步骤的 Invoke 后，该行下方展开 Result 卡片。可同时查看多步结果，折叠状态默认收起。

### 方案 C：右侧分栏
左 Steps + 右 Result。空间利用率高，但 petite-vue CDN 实现分栏复杂。

**选择理由**：B 实现简单（CSS 展开逻辑），调试时可同时对比多步结果，且不增加页面复杂度。

### 历史记录

| 方案 | 描述 | 
|---|---|
| A：左侧面板 ✅ | 左侧列出最近 Session（ID+意图摘要+step数），点击切换 |
| B：顶部时间线 | Session 下拉扩展为摘要列表，顶部太挤 |

## 3. 推荐方案详述

### 3.1 布局

```
┌─ 历史面板 ─┬── 调试主区 ──────────────────────────────┐
│            │  Session Context (始终可见)               │
│ sess-001   │  ┌──────────────────────────────────────┐ │
│  echo       │  │ sess-abc123 · active · u1 · 07-21   │ │
│  2 steps   │  └──────────────────────────────────────┘ │
│ ────────   │                                          │
│ sess-002   │  Intent: [___________________] [Plan →]  │
│  query      │  Session: [auto-create ▼]               │
│  1 step    │                                          │
│ ────────   │  ⚠ Plan error banner (条件显示)          │
│ + New      │                                          │
│            │  Steps                                    │
│            │  ┌──────────────────────────────────────┐ │
│            │  │ #│Capability      │Input    │        │ │
│            │  │ 1│cap-demo-echo   │{msg:..}│[Invoke]│ │
│            │  │   ├─ 📡 Stream  (展开/折叠)            │ │
│            │  │   │  EARP is the Enterprise AI...     │ │
│            │  │   │  Tokens: 32 · 45 tok/s · 0.7s     │ │
│            │  │   ├─ 📋 Result                          │ │
│            │  │   │  {"echo":{"message":"hello"}}      │ │
│            │  │ 2│cap-llm-analyze│{prompt}│[Invoke]│   │ │
│            │  │   └─ ❌ timeout after 30s              │ │
│            │  └──────────────────────────────────────┘ │
└────────────┴──────────────────────────────────────────┘
```

**左侧面板**（240px 固定宽，可折叠）：
- 标题「History」
- Session 列表项：`session_id` + 最后意图摘要（截断 30 字符） + step 数量
- 当前选中项高亮
- 底部「+ New」创建新 Session
- 数据来源：`GET /v1/sessions?user_id=&status=active&order=created_at_desc&limit=20`

**右侧主区**：
- Session Context（始终可见）
- Intent 输入 + Plan 按钮
- Session 选择器（默认 auto-create）
- Plan 错误 banner（条件显示）
- Steps 表（Plan 成功后才出现）

### 3.2 交互流程

**Stream 页面吸收**：原独立 Streaming 页面（`stream.html`）的功能融入 Plan & Invoke。任意步骤 Invoke 后可查看两

层结果——流式 token 视图 + 结构化 JSON 结果。Stream 页面从导航中移除，「推理」组只剩 Plan & Invoke。

**流程**：

```
1. 页面加载
   → GET /v1/sessions 获取历史列表 → 填充左侧面板
   → 默认选中最近一个 Session，或 auto-create 模式

2. 用户输入 Intent → 点击 Plan
   → 按钮变灰 + spinner + "Planning..."
   → 若未选 Session：POST /v1/sessions → 获得 session_id
   → POST /plan {intent: "...", session_id: "..."}
     ├─ 成功 → 渲染 Steps 表 + 隐藏错误 banner
     └─ 失败 → 显示错误 banner（LLM 超时/非法 JSON/无匹配）

3. 用户点击某步骤的 [Invoke]
   → 按钮变灰 + "Invoking..."
   → POST /v1/sessions/{id}/invoke {capability_call: {...}}
     ├─ 成功 → 该行下方展开 Result 卡片（绿色边框）
     └─ 失败 → 该行下方展开错误卡片（红色边框）

4. 点击左侧某 Session → 加载该 Session 的 Plan 历史
   → GET /v1/sessions/{id} 获取 session 信息
   → 重新渲染 Session Context、Steps（如有历史 Plan 记录）

5. 重复 Plan（改 Intent 再点 Plan）
   → 清空当前 Steps → 重新走流程
```

### 3.3 状态设计

| 状态 | Plan 按钮 | Steps 区域 | Result 区域 |
|---|---|---|---|
| 初始（无 Plan） | 可点击 | 空（提示文字 "Enter intent and click Plan"） | 无 |
| Planning... | 灰+spinner+"Planning..." | 保留上次结果或空 | — |
| Plan 成功 | 恢复可点击 | 填充 Steps 表 | — |
| Plan 失败 | 恢复可点击 | 错误 banner | — |
| Invoking... | — | 该行按钮灰+"Invoking..." | 占位（上次结果保留或空） |
| Invoke 成功 | — | 按钮恢复 | 绿色卡片展开 |
| Invoke 失败 | — | 按钮恢复 | 红色卡片展开 |

### 3.4 Session Context

```
┌─ Session ──────────────────────────────────────────────┐
│ sess-abc123 · active · u1 · r1 · created 2026-07-21    │
│ Last Plan: 2026-07-22 15:30 (3 steps)                   │
└────────────────────────────────────────────────────────┘
```

信息行：
- Session ID + 状态标签
- User ID + Role ID
- 创建时间
- 最后一次 Plan 的时间 + step 数（有 Plan 记录时显示）

数据来源：首次渲染用 `GET /v1/sessions/{id}`，Plan 成功后更新 last_plan 时间。

### 3.5 历史面板

数据来源：`GET /v1/sessions?user_id=&status=active&order=created_at_desc&limit=20`

每项显示：
- Session ID（如 `sess-abc123`）
- 意图摘要（最后 Plan 的 intent 前 30 字符，如 "echo hello"）
- Step 数量（该 Session 最近一次 Plan 的 step 数）
- 创建时间（相对时间："2h ago"）

无历史时：空面板 + 「No sessions yet. Create one with Plan.」

### 3.6 API 链路

```
页面加载:
  GET /v1/sessions?user_id=&status=active&order=created_at_desc&limit=20
    → [{session_id, status, user_id, created_at, last_plan_intent, last_plan_steps}]

Plan:
  POST /v1/sessions  (若 auto-create)
    → {session_id: "sess-xyz"}
  POST /plan {intent: "...", session_id: "sess-xyz"}
    → [{step_id: 1, capability_id: "cap-demo-echo", input: {msg: "hello"}}]
    → 或错误: {error: "No matching capability", detail: "..."}

Invoke:
  POST /v1/sessions/{id}/invoke {capability_call: {adapter_type: "...", input: {...}}}
    → {result: {echo: {message: "hello"}}}
    → 或错误: {error: "timeout", detail: "..."}

Session 详情（左侧点击时）:
  GET /v1/sessions/{id}
    → {session_id, status, user_id, role_id, created_at, plan_history: [...]}
```

**新增 API 需求**：
- `GET /v1/sessions` 需新增 `last_plan_intent` 和 `last_plan_steps` 字段（或通过关联查询）
- `GET /v1/sessions/{id}` 需返回 `plan_history` 数组

若后端不支持 `last_plan_intent`，前端可用 `plan_history[-1].intent` 替代（需后端返回 plan_history）。

## 4. 影响分析

### 受影响文件

| 文件 | 变更 |
|---|---|
| `apps/earp-admin/pages/plan.html` | 重写：新布局 + 完整 JS |
| `apps/earp-admin/css/admin.css` | 新增 `.history-panel`、`.step-result`、`.error-banner` 等 |
| `apps/earp-admin/js/app.js` | 可能需要 `EARP.fetchJSON` / `EARP.streamSSE`（已有） |

### 可能需要新增的后端能力

| 端点 | 变更 |
|---|---|
| `GET /v1/sessions` | 新增 `last_plan_*` 字段 |
| `GET /v1/sessions/{id}` | 新增 `plan_history` |
| `POST /plan` | 已存在，确认返回格式 |

## 5. 已知限制与风险

| 限制/风险 | 缓解 |
|---|---|
| `GET /v1/sessions` 可能不返回 `last_plan_*` | Phase 1 用 session_id + created_at 即可，摘要先留空 |
| 左侧面板在小屏幕上占空间 | 默认显示，`@media (max-width: 768px)` 折叠为汉堡菜单 |
| Plan 历史存储在后端的方案未定 | 优先用 session metadata 存储最近一次 Plan 的 intent/step_count |
| 大量 Session 导致左侧列表过长 | 限制 20 条 + 虚拟滚动（Phase 2） |
| 无 Plan 记录的旧 Session 在列表中无摘要 | 显示 "No plan yet" |

## 6. 下一步

- [ ] 用户评审本设计文档
- [ ] 确认后端 `GET /v1/sessions` 是否需要新增字段
- [ ] 批准后 → `plan` skill 输出实施任务
