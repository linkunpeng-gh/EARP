# Workflows 管理页面 - 设计方案

- 日期: 2026-07-22
- 状态: draft
- 关联规范: `arch/L2/04-execution/workflow-specification.md` v1.1

## 1. 背景与目标

工作流是 EARP 四大能力类型之一。当前缺少工作流管理页面，无法创建/编辑/发布/下线工作流。Capabilities 页面虽可注册工作流能力，但工作流本身没有管理入口。

**目标**：提供工作流列表管理页面——创建、编辑、发布、下线、查看运行状态、跳转可视化编辑器。

## 2. 导航位置

```
能力 (Capability)
  ├─ Capabilities    /admin/capabilities
  └─ Workflows       /admin/workflows     ← 本页面
```

## 3. 页面布局

```
┌─ Workflows ───────────────────────────────────────────────┐
│                                                            │
│  Status: [all ▾]  Domain: [all ▾]  [Search...]  [+ New]  │
│                                                            │
│  ┌─ 状态概览 ───────────────────────────────────────────┐ │
│  │  📝 3 draft  ·  ✅ 5 published  ·  🔄 1 running      │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌─ 工作流列表 ─────────────────────────────────────────┐ │
│  │ ID │ Name │ Version │ Domain │ Status │ Last Edit │    │ │
│  │ wf-01│设备故障│ 1.0.0 │ equip  │ ✅ pub  │ 2h ago   │ ✏️ │ │
│  │ wf-02│请假审批│ 0.1.0 │ hr     │ 📝 draft│ 1d ago   │ ✏️ │ │
│  │ wf-03│报表生成│ 2.0.0 │ corp   │ 🔄 run  │ 5m ago   │ ✏️ │ │
│  └────────────────────────────────────────────────────────┘ │
│                              ← 1 2 3 ... 5 →               │
└──────────────────────────────────────────────────────────┘
```

## 4. 交互规则

### 4.1 创建
- + New → 创建新工作流（填 name + domain + version 初始 0.1.0）→ 状态 draft
- 可选：「从模板创建」下拉

### 4.2 编辑
- ✏️ 图标点击 → 跳转工作流编辑器（Phase 1 跳 `workflow-editor.html` 表单编辑，Phase 2 跳 Vue Flow 画布编辑器）

### 4.3 发布
- draft 状态的行显示「Publish」按钮
- 发布后状态变为 `published`，版本号不变
- 已发布的工作流可被 Capabilities 页面发现和注册

### 4.4 下线
- published 状态的行显示「Unpublish」按钮
- 下线后回到 `draft` 状态
- 若已被注册为 Capability，提示「该工作流已注册为能力 xxx，下线后将失效」

### 4.5 删除
- 🗑 删除按钮（仅 draft 状态的可以删）
- published 的先下线再删

## 5. 工作流状态

| 状态 | 含义 | 允许操作 |
|---|---|---|
| `draft` | 编辑中 | 编辑 / 发布 / 删除 |
| `published` | 已发布 | 编辑 / 下线 / 复制 |
| `running` | 有活跃执行中 | 查看运行详情 |

## 6. 与 Capabilities 的关系

```
Workflows 页面                          Capabilities 页面
─────────────────                      ──────────────────
创建 wf-001 → 编辑 → 发布 →            注册 Capability（type=workflow）
                                       → 引用 wf-001 + 暴露参数 + 权限配置
```

工作流的生命周期管理在 Workflows 页面，注册为能力在 Capabilities 页面。两个页面独立但关联。

## 7. 影响分析

| 文件 | 变更 |
|---|---|
| `apps/earp-admin/pages/workflows.html` | 新建 |
| `apps/earp-admin/css/admin.css` | 状态标签复用（draft/published/running） |
| 导航所有页面 | 「能力」组增加 Workflows 链接 |

## 8. 已知限制

| 限制 | 缓解 |
|---|---|
| Phase 1 无画布编辑器 | 编辑跳转表单编辑页（workflow-editor.html）或 JSON 编辑 |
| 无运行时引擎 | running 状态暂用模拟数据 |
| 工作流模板 | Phase 2 |
