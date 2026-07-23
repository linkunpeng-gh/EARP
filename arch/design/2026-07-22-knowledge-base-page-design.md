# Knowledge Base 页面 - 设计方案

- 日期: 2026-07-22
- 状态: draft
- 关联 PRD: PRD-2026-028-admin-dashboard v1.7 §6.5

## 1. 背景与目标

Knowledge Base 是 EARP 知识管理核心页面——创建 KB、上传文档、分段配置、测试召回效果。KB 归属 Data Domain，权限由 Doc 层 + DD 天花板控制。

**当前状态**：452 行内联实现，KB 表 + 文档表上下堆叠。全部 `alert()` 占位，无真实 CRUD。Test Retrieval 嵌入在页面底部。重复 ID、分散的 `<style>` 块。

**目标**：重组为主从布局，工作流清晰——选 KB → 看文档 → 上传/管理 → 跳子页做分段配置和召回测试。

## 2. 方案对比

### 方案 A：主从布局 ✅（选定）
左侧 KB 列表（窄面板） + 右侧选中 KB 的工作区。KB 列表支持 DD 过滤。

### 方案 B：单页流
KB 表在上 + 文档表在下，保持当前风格。

### 召回测试：独立页面 ✅（选定）
从 KB 主页面中移出，作为独立子页。Test Retrieval 功能复杂（查询输入 + 参数展示 + 结果表 + 指标），单独页面空间充裕。

**选择理由**：主从布局与 Plan 页面风格一致；召回测试独立页面便于扩展（Phase 2 加指标图表、对比实验等）。

## 3. 推荐方案详述

### 3.1 页面关系

```
知识 (导航组入口)
  ├─ Knowledge Base  (/admin/knowledge)    ← 主页面：KB 管理 + 文档管理
  ├─ Data Domains    (/admin/data-domains)  ← 独立页面：DD 管理
  ├─ Doc Config      (/admin/doc-config)    ← 子页面：单片文档分段配置 + 预览
  └─ Test Retrieval  (/admin/test-retrieval)← 子页面：召回测试
```

### 3.2 KB 主页面布局

```
┌─ KB 列表 ─┬── 工作区 ─────────────────────────────────────┐
│            │                                                │
│ DD: [all▾]│  📋 Equipment Manuals                          │
│            │  equipment_data · 8 docs · 120 chunks · int    │
│ kb-eq-ma..●│                                                │
│ 8 docs     │  ┌─ 上传文档 ───────────────────────────────┐ │
│ kb-eq-al.. │  │ Title: [__________]  Class: [internal ▾]  │ │
│ 4 docs     │  │ Content: [_____________________________]  │ │
│ kb-hr-po.. │  │ DD: equipment_data         [Upload]       │ │
│ 5 docs     │  └───────────────────────────────────────────┘ │
│            │                                                │
│ + New KB   │  ┌─ 文档列表 ───────────────────────────────┐ │
│            │  │ doc-001 CNC Manual  24 chunks  ⚙️  🔍   │ │
│            │  │ doc-002 Maintenance 15 chunks  ⚙️  🔍   │ │
│            │  └───────────────────────────────────────────┘ │
│            │                                                │
│            │  [Test Retrieval] → 跳转 test-retrieval.html   │
└────────────┴────────────────────────────────────────────────┘
```

### 3.3 KB 列表（左侧）

| 元素 | 说明 |
|---|---|
| DD 过滤下拉 | 按 Data Domain 过滤 KB 列表。选项：all / equipment_data / hr_data / corporate_data |
| KB 列表项 | 每项显示：KB ID（等宽字体）+ 文档数量。选中项高亮（accent 左边框） |
| + New KB 按钮 | 打开 KB 创建模态框 |
| Config 按钮 | 每行铅笔图标，打开 KB 编辑模态框（Chunking + Retrieval 配置） |
| Delete 按钮 | 每行垃圾桶图标，确认后删除 KB |

### 3.4 右侧工作区

**KB 信息栏**（始终可见，选中 KB 后出现）：
- KB 名称 + Data Domain 标签
- 文档数 / Chunks 总数 / 分类天花板
- 不可折叠

**文档上传栏**（选中 KB 后出现）：
- Title 输入框 + Content 文本域
- Data Domain 显示（继承 KB 的 DD，只读）
- Classification 下拉（public/internal/confidential/restricted，受 DD 天花板约束）
- Upload 按钮

**文档列表**：
- 列：Doc ID / Title / Chunks / Status
- 行内操作：⚙️（跳 doc-config 子页，带 `?doc=xxx` 参数）、🔍（查看详情，Phase 2）
- Classification 行内下拉编辑（保留当前功能）

**Test Retrieval 跳转按钮**：
- 点击跳转 `test-retrieval.html?kb=xxx`，限定在当前选中 KB 范围内
- 若未选 KB 但有 DD 过滤，跳转 `test-retrieval.html?dd=xxx`

### 3.5 KB 创建/编辑模态框

**创建 KB 字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| Name | 文本 | KB 名称（必填） |
| Description | 文本 | 可选描述 |
| Data Domain | 下拉 | 归属 DD（必填） |
| Chunk Size | 选择 | 500/1000/1500/2000（默认 1000） |
| Overlap | 选择 | 100/200/300（默认 200） |
| Separators | 文本 | 分段分隔符（默认 `\n\n,\n,., ,`） |
| Embedding Model | 选择 | bge-m3 / text-embedding-3-small |
| Retrieval Mode | 选择 | vector / hybrid |
| Top-K | 选择 | 3/5/10/20（默认 5） |
| Score Threshold | 数字 | 0.0-1.0（默认 0.0） |
| Index | 选择 | high_quality / economy |

**编辑 KB**：打开同模态框，预填当前值。字段全可修改。

**删除 KB**：确认对话框 → 删除 KB 及其所有文档。不可逆。

### 3.6 Test Retrieval 页面（独立子页）

```
┌─ Test Retrieval ─────────────────────────────────────────┐
│                                                           │
│  Scope: [KB: Equipment Manuals ▾] 或 [DD: equipment_data] │
│                                                           │
│  Query: [___________________________] [Search]            │
│                                                           │
│  Settings: Mode: vector · Top-K: 5 · Threshold: 0.0      │
│                                                           │
│  ┌─ Results ────────────────────────────────────────────┐ │
│  │ # │ Chunk ID │ Content                     │ Score   │ │
│  │ 1 │ chk-001  │ CNC machines require...     │ 0.92    │ │
│  │ 2 │ chk-003  │ Temperature sensors...      │ 0.87    │ │
│  │ 3 │ chk-007  │ All safety inspections...   │ 0.81    │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  召回指标: Recall@5: 0.73 · MRR: 0.85                     │
└───────────────────────────────────────────────────────────┘
```

**参数/元素**：

| 元素 | 说明 |
|---|---|
| Scope 选择器 | 限定召回范围。来源页面携带参数自动预选（`?kb=xxx` 或 `?dd=xxx`）。手动可切换 |
| Query 输入 | 搜索查询文本 |
| Search 按钮 | 调用 `POST /knowledge/search {query, scope, top_k}` |
| Settings 行 | 显示当前检索参数（来自 KB 配置或手动覆盖） |
| 结果表 | 列: # / Chunk ID / Content（前 150 字符）/ Score |
| 召回指标 | Phase 2：Recall@K / MRR |

---

### 3.7 与 Data Domains 页面的关系

- DD 页面管理 DD 的创建/角色权限/天花板，不涉及 KB/Doc 层级操作
- KB 页面创建 KB 时选择已存在的 DD（DD 下拉从 `GET /admin/api/data-domains` 获取）
- 两个页面通过导航「知识」组关联，不通过 URL 参数

---

## 4. 影响分析

### 受影响文件

| 文件 | 变更 |
|---|---|
| `apps/earp-admin/pages/knowledge.html` | 重写：主从布局 + 完整 CRUD JS |
| `apps/earp-admin/pages/test-retrieval.html` | 新建：独立召回测试页面 |
| `apps/earp-admin/css/admin.css` | 新增 `.kb-layout`、`.kb-list`、`.kb-workspace` 等 |

### doc-config.html

- 保持不变：通过 `?doc=xxx` 参数接收文档 ID
- breadcrumb 返回 Knowledge Base 页面

## 5. 已知限制与风险

| 限制/风险 | 缓解 |
|---|---|
| KB 删除不可逆 | 确认对话框用红色警告文案 |
| 大量文档时文档列表性能 | Phase 1 限制一页 20 条 |
| Test Retrieval 指标（Recall/MRR）需后端支持 | Phase 1 仅展示原始结果，Phase 2 加指标 |
| 重复 ID 问题（当前 `kb-chunk-size` 出现两次） | 重写时统一 ID 命名 |

## 6. 下一步

- [ ] 用户评审本设计文档
- [ ] 确认 Test Retrieval 页面是否需要独立的召回指标 API
- [ ] 批准后 → `plan` skill 输出实施任务
