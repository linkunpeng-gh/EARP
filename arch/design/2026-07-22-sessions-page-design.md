# Sessions 页面 — 异常监控面板

- 日期: 2026-07-22
- 状态: draft
- 关联 PRD: PRD-2026-028-admin-dashboard v1.7 §6.2

## 1. 背景与目标

Sessions 页面当前是基本 CRUD 列表（筛选+分页），定位为「管理执行会话」。但 Session 的生命周期不应由管理员手动管理——它应该自然结束（成功/失败/超时/权限拒绝）。

**重新定位**：从「管理面板」变为「异常监控面板」——快速发现异常 Session，点击查看 Execution 链路，定位问题根因。

**状态模型变更**：`active`/`closed` → `active`/`completed`/`failed`/`denied`/`expired`

## 2. Session 状态模型

| 状态 | 含义 | 触发条件 |
|---|---|---|
| `active` | 运行中 | 创建后，等待或执行中 |
| `completed` | 正常结束 | 所有步骤 Invoke 成功 |
| `failed` | 执行异常 | Invoke 返回 error、Capability 超时 |
| `denied` | 权限拒绝 | Plan 阶段 Policy Center 评估不通过 |
| `expired` | 超时 | `expires_at` 到达后后台任务自动标记 |

**去掉了 `closed`**：管理员不再手动关闭 Session。

## 3. 页面布局

```
┌─ Sessions ───────────────────────────────────────────────┐
│                                                           │
│  Status: [▼ failed]  User ID: [____]  [Search]           │
│                                                           │
│  ┌─ 异常概览 ──────────────────────────────────────────┐ │
│  │  ❌ 3 failed  ·  🚫 1 denied  ·  ⏰ 2 expired        │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─ Session 列表 ──────────────────────────────────────┐ │
│  │ Session ID      │ User │ Role │ Status │ Created     │ │
│  │ sess-abc123     │ u1   │ r1   │ ❌ failed           │ │
│  │   └─ Plan failed at step 2: timeout after 30s       │ │
│  │ sess-def456     │ u2   │ r1   │ 🚫 denied           │ │
│  │   └─ Role market_analyst lacks permission: finance:* │ │
│  │ sess-ghi789     │ u1   │ r2   │ ✅ completed         │ │
│  │   └─ 3 steps, all successful                        │ │
│  └──────────────────────────────────────────────────────┘ │
│                             ← 1 2 3 ... 5 →               │
└──────────────────────────────────────────────────────────┘
```

**默认筛选**：打开页面默认显示 `failed` + `denied` + `expired`（异常优先），用户可切换查看全部。

**每行展开**：点击 Session 行展开显示失败原因/执行摘要（来自 `executions` 表的 error 字段或 audit_logs）。

## 4. 交互规则

### 4.1 筛选
- Status 下拉：all / active / completed / failed / denied / expired
- 默认选中 failed + denied + expired（多选？还是单选+默认值？选单值：默认 `failed`，用户自行切换）

### 4.2 详情跳转
- 点击 Session 行 → 跳转 Session 详情页（Phase 2）
- 详情页展示：Execution 时间线 + Plan 内容 + Result + Error
- 每个 Execution 可展开查看 Capability Call 细节

### 4.3 自动过期
- 后台任务（procrastinate 调度）定期扫描 `expires_at < NOW() AND status = 'active'`
- 标记为 `expired`
- 频率：每 5 分钟

## 5. 与 Plan & Invoke 页面的关系

| | Sessions 页面 | Plan & Invoke 页面 |
|---|---|---|
| 定位 | 全局监控（异常发现） | 单 Session 调试 |
| 入口 | 导航「运行时」 | 导航「推理」 |
| Session 创建 | 不提供 | 自动创建 |
| 数据视角 | 所有 Session 概述 | 单个 Session 深入 |

## 6. 变更影响

### 数据库
| 变更 | 说明 |
|---|---|
| `sessions.status` | 接受值从 `active/closed` 扩展为 5 种 |
| 后台清理任务 | 新增：扫描 `expires_at` 标记过期 |

### API
| 端点 | 变更 |
|---|---|
| `GET /v1/sessions` | 已存在，筛选参数增加 `failed/denied/expired` |
| `POST /v1/sessions/{id}/close` | **废弃** |
| `GET /v1/sessions/{id}/executions` | **新增**（Phase 2） |

### 前端
| 文件 | 变更 |
|---|---|
| `pages/sessions.html` | 重写：状态模型 + 异常概览 + 展开摘要 |
| `css/admin.css` | 新增状态标签样式 |

## 7. 已知限制

| 限制 | 缓解 |
|---|---|
| 后台过期任务尚未实现 | Phase 1 状态模型先落地，Phase 2 加 procrastinate 任务 |
| Execution 详情页不存在 | Phase 2 `session-detail.html` |
| `expires_at` 当前未自动设置 | Session 创建时默认 `NOW() + 24h` |
