# EARP AI 配置助手（Copilot）— 任务书

> 创建时间：2026-08-24
> 功能：在管理后台各配置页面提供 AI 辅助，帮助管理员理解参数、诊断配置、建议优化

---

## 一、需求概述

在 EARP 管理后台的配置页面（模型配置、知识库、AI 应用、数据域、角色权限），提供一个 AI 侧边面板，用户可通过自然语言提问，AI 结合当前页面上下文和知识库内容给出指导建议。

### 能力层次

| 层次 | 能力 | 优先级 | 状态 |
|------|------|--------|------|
| L0 | 上下文感知的配置解释 | P0 | ✅ 已完成 |
| L1 | 配置诊断（检查当前配置是否正确） | P0 | ✅ 已完成 |
| L2 | 智能填充建议（ghost text + 接受/拒绝） | P1 | ✅ 已完成 |
| L3 | 一键配置（场景描述 → 完整方案） | P2 | ✅ 已完成 |

---

## 二、任务清单

### Phase 1 — MVP（侧边面板 + 配置解释/诊断）✅ 已完成

#### 后端任务

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 1.1 | 创建 copilot 模块目录和 `__init__.py` | `earp_server/copilot/__init__.py` | ✅ |
| 1.2 | 实现页面 Schema 注册表 (`page_registry.py`) — 5 个配置页面的字段元信息 | `earp_server/copilot/page_registry.py` | ✅ |
| 1.3 | 实现上下文构建器 (`context_builder.py`) — prompt 组装、敏感字段脱敏、意图分流 | `earp_server/copilot/context_builder.py` | ✅ |
| 1.4 | 实现 Copilot 服务 (`service.py`) — SSE 流式生成、KB 检索集成 | `earp_server/copilot/service.py` | ✅ |
| 1.5 | 新增 `POST /copilot/assist` SSE 端点 | `earp_server/main.py` | ✅ |
| 1.6 | 新增 `GET /copilot/pages` 端点（页面列表） | `earp_server/main.py` | ✅ |

#### 前端任务

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 2.1 | 新增 AI 面板 CSS 样式（侧边面板、触发按钮、消息气泡、typing 动画等） | `earp-admin/css/admin.css` | ✅ |
| 2.2 | 实现通用 AI Assist JS 组件 (`copilot.js`) — 面板创建、SSE 流式渲染、快捷提问、Markdown 渲染 | `earp-admin/js/copilot.js` | ✅ |
| 2.3 | 在 `models.html` 集成 AI 面板 + 表单状态采集 | `earp-admin/pages/models.html` | ✅ |
| 2.4 | 在 `knowledge.html` 集成 AI 面板 + 表单状态采集 | `earp-admin/pages/knowledge.html` | ✅ |
| 2.5 | 在 `chat-edit.html` 集成 AI 面板 + 表单状态采集 | `earp-admin/pages/chat-edit.html` | ✅ |
| 2.6 | 在 `data-domains.html` 集成 AI 面板 + 表单状态采集 | `earp-admin/pages/data-domains.html` | ✅ |
| 2.7 | 在 `roles.html` 集成 AI 面板 + 表单状态采集 | `earp-admin/pages/roles.html` | ✅ |

#### 知识库文档

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 3.1 | 编写平台配置指南文档（模型、知识库、AI 应用、数据域、角色权限的参数说明和最佳实践） | `docs/copilot-config-guide.md` | ✅ |

#### 修复记录

| # | 问题 | 修复内容 |
|---|------|----------|
| F1 | 点击 AI 按钮无反应 | `_ensurePanel()` 从 innerHTML 改为逐个 createElement 构建 DOM；添加 null check；添加 `window.EARPCopilot` 全局赋值 |
| F2 | knowledge.html 点击无反应 | 缺少 `copilot.js` 脚本引用；`state.selectedKBData` 不存在，改为从 `state.kbs` 数组查找 |
| F3 | 各页面 `EARPCopilot.init()` 时序问题 | 包裹在 `DOMContentLoaded` 回调中确保 DOM 已就绪 |

### Phase 2 实现记录

#### 后端改动

| 文件 | 改动 |
|------|------|
| `context_builder.py` | 新增 `_SYSTEM_AUTOFILL` 提示词，指导 LLM 输出 JSON 数组格式的字段建议 |
| `service.py` | 新增 `_parse_autofill_response()` 解析 LLM JSON 响应；`copilot_assist()` 检测 autofill intent 时收集完整响应并 yield `suggestions` 事件 |
| `main.py` | `CopilotAssistRequest.intent` 枚举添加 `autofill` |

#### 前端改动

| 文件 | 改动 |
|------|------|
| `copilot.js` | 新增 `_suggestions`、`_ghostElements` 状态；新增 `_renderGhostText()`、`acceptSuggestion()`、`rejectSuggestion()`、`acceptAllSuggestions()`、`rejectAllSuggestions()` 函数；`_ensurePanel()` 添加建议操作栏；`send()` 添加 autofill intent 检测和 suggestions 事件处理 |
| `admin.css` | 新增 `.ai-ghost-text`、`.ai-ghost-*`、`.ai-suggestions-bar`、`.ai-suggestions-*` 样式 |

#### SSE 事件格式（autofill）

```
data: {"type": "sources", "items": [...]}
data: {"type": "suggestions", "items": [
  {"field": "temperature", "value": 0.3, "confidence": 0.9, "reason": "配置任务推荐低温度"},
  {"field": "top_p", "value": 0.9, "confidence": 0.85, "reason": "标准采样参数"}
]}
data: {"type": "done", "conversation_id": "..."}
```

### Phase 3 实现记录

#### 后端改动

| 文件 | 改动 |
|------|------|
| `context_builder.py` | 新增 `_SYSTEM_APPLY` 提示词，指导 LLM 输出 JSON 对象格式的完整配置方案；`build_copilot_context()` 新增 `apply` intent 分支 |
| `service.py` | 新增 `_parse_apply_response()` 解析 LLM JSON 响应；`copilot_assist()` 新增 `apply` intent 分支，yield `apply_plan` 事件 |
| `main.py` | `CopilotAssistRequest.intent` 枚举注释添加 `apply` |

#### 前端改动

| 文件 | 改动 |
|------|------|
| `copilot.js` | 新增 `_applyPlan` 状态；新增 `_renderApplyPlan()` 渲染 diff 预览；新增 `applyPlan()` 批量填充表单；新增 `cancelPlan()` 取消；`send()` 新增 `apply_plan` 事件处理；intent 检测新增 `apply` 关键词；快捷提问新增「一键配置完整方案」 |
| `admin.css` | 新增 `.ai-apply-plan`、`.ai-apply-row`、`.ai-apply-old`、`.ai-apply-new`、`.ai-apply-actions`、`.ai-apply-btn` 等 diff 预览样式 |

#### SSE 事件格式（apply）

```
data: {"type": "sources", "items": [...]}
data: {"type": "apply_plan", "fields": {
  "temperature": 0.3,
  "top_p": 0.9,
  "system_prompt": "你是客服助手...",
  "api_key": "__PLACEHOLDER__"
}, "explanation": "根据客服场景，推荐低温度高确定性配置..."}
data: {"type": "done", "conversation_id": "..."}
```

---

## 三、技术架构

### 请求流程

```
前端页面 → onclick="EARPCopilot.toggle()"
         → 侧边面板 → 用户输入问题
         → POST /copilot/assist (SSE)
         → 后端: Context Builder 组装 prompt
              → KB 检索 (pgvector)
              → LLM 流式生成 (Ollama/OpenAI)
         → SSE 事件流 → 前端逐 token 渲染
```

### 文件结构

```
earp-server/src/earp_server/copilot/
├── __init__.py          # 模块入口
├── page_registry.py     # 页面 Schema 注册（7 个页面的字段元信息）
├── context_builder.py   # 上下文构建（prompt 组装、敏感字段脱敏）
└── service.py           # SSE 流式服务（KB 检索 → LLM 生成 → 对话持久化 → 审计日志）

earp-admin/
├── js/copilot.js        # 通用 AI 面板组件
├── css/admin.css        # AI 面板样式（新增部分）
└── pages/
    ├── models.html      # ✅ 已集成
    ├── knowledge.html   # ✅ 已集成
    ├── chat-edit.html   # ✅ 已集成
    ├── chatflow-edit.html # ✅ 已集成
    ├── data-domains.html # ✅ 已集成
    ├── doc-seg.html     # ✅ 已集成
    └── roles.html       # ✅ 已集成

docs/
└── copilot-config-guide.md  # 平台配置指南知识库文档
```

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/copilot/assist` | AI 配置助手（SSE 流式响应） |
| `GET` | `/copilot/pages` | 返回已注册的页面列表 |

#### `/copilot/assist` 请求体

```json
{
  "page_id": "models",
  "intent": "explain",
  "query": "温度参数是什么意思？",
  "form_state": { "default_llm": "xxx", "temperature": 0.7 },
  "conversation_id": null
}
```

#### SSE 响应事件

```
data: {"type": "sources", "items": [{"title": "...", "knowledge_base_name": "..."}]}
data: {"type": "token", "content": "温度"}
data: {"type": "token", "content": "参数"}
data: {"type": "done", "conversation_id": "..."}
```

---

## 四、后续迭代计划

### Phase 2 — P1：表单内联建议 ✅ 已完成

| # | 任务 | 说明 | 状态 |
|---|------|------|------|
| 4.1 | 后端支持 `autofill` intent | 返回逐字段建议（field → value → confidence → reason） | ✅ |
| 4.2 | 前端 ghost text 渲染 | 在表单字段下方显示建议值，用户可 Tab 接受或继续输入覆盖 | ✅ |
| 4.3 | 接受/拒绝交互 | 单字段接受、全部接受、全部清除 | ✅ |

### Phase 3 — P2：一键配置 ✅ 已完成

| # | 任务 | 说明 | 状态 |
|---|------|------|------|
| 5.1 | 后端支持 `apply` intent | 根据场景描述生成完整配置方案 | ✅ |
| 5.2 | 配置 diff 预览 | 展示 AI 建议的变更与当前值的对比 | ✅ |
| 5.3 | 确认应用 | 用户确认后批量更新表单字段 | ✅ |

### 其他优化

| # | 任务 | 说明 | 状态 |
|---|------|------|------|
| 6.1 | 知识库文档扩充 | 将 `docs/copilot-config-guide.md` 上传到 EARP 知识库，供 RAG 检索 | ✅ 已完成 |
| 6.2 | 多轮对话持久化 | 复用现有 conversation 模块，保存 copilot 对话历史 | ✅ 已完成 |
| 6.3 | 审计日志 | 记录 AI 交互到 audit_logs | ✅ 已完成 |
| 6.4 | 快捷 Prompt 自定义 | 从 page_registry 的 `common_questions` 字段动态渲染 | ✅ 已完成 |
| 6.5 | 更多页面集成 | chatflow-edit、doc-seg 等页面 | ✅ 已完成 |

### 维护任务

| # | 任务 | 说明 | 优先级 |
|---|------|------|--------|
| 7.1 | page_registry 字段同步 | 页面新增/修改字段时，同步更新 `copilot/page_registry.py` 中的字段描述 | 高 |
| 7.2 | copilot-config-guide.md 更新 | 平台功能变更时，更新知识库文档内容 | 中 |

> **重要**：`page_registry.py` 是 AI 助手理解页面参数的主要来源。如果页面字段发生变化但未同步更新，AI 助手将无法正确解释新字段。
