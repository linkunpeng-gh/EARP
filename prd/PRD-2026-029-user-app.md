# PRD-2026-029: User Application Frontend

**版本**: v1.0
**日期**: 2026-07-21
**状态**: Phase 0 — 待审核

---

## 一、定位

EARP 目前只有 Admin Dashboard（管理面），缺少终端用户可用的交互界面。User App 是面向**业务用户**的轻量前端——用自然语言与 EARP 交互，获取 AI 驱动的执行结果。

**一句话**: 一个类 ChatGPT 的对话式应用界面，让业务用户输入需求、查看结果，不需要理解 Plan/Capability/Session 等平台概念。

**与 Admin Dashboard 的分工**:

| | Admin Dashboard | User App |
|:---|:---|:---|
| 用户 | 管理员、开发者、运维 | 业务用户（客服、分析师、知识工作者） |
| 页面数 | 9 | 4 |
| 风格 | 管理后台（表格/筛选/统计） | 对话应用（聊天窗口/简洁列表） |
| 核心操作 | Plan→Invoke 调试 | 输入需求 → 看结果 |
| 技术概念 | 暴露 Plan/Session/Capability | 隐藏平台概念，只暴露对话 |
| 类比 | Supabase Dashboard | ChatGPT / Perplexity |

---

## 二、技术选型

与 Admin Dashboard 完全一致，复用同一套技术栈和设计系统：

| 维度 | 决策 | 理由 |
|:---|:---|:---|
| 渲染 | Vue 3 (petite-vue, 6KB CDN) | 零构建工具链 |
| 样式 | 同一套 CSS 变量 (Topnav Light) | Admin + User 风格统一 |
| 部署 | 同一个 FastAPI app | `StaticFiles` 分别 serve |
| 目录 | `apps/earp-user/` | 与 `apps/earp-admin/` 平行 |

**依赖**: 无新增依赖。复用 `Inter` 字体 CDN。

**目录结构**:
```
apps/earp-user/
├── index.html              # 对话主页
├── css/
│   └── app.css             # 用户端样式（可 import admin.css 复用 token）
├── js/
│   └── app.js              # Vue app（共享 EARP.helpers）
└── pages/
    ├── search.html          # 知识库搜索
    ├── history.html         # 历史记录
    └── login.html           # 登录页
```

---

## 三、页面清单

| # | 页面 | 路由 | 数据来源 | 说明 |
|:--|:---|:---|:---|:---|
| 1 | Chat | `/app/` | `POST /conversations` / `POST /conversations/{id}/messages` | 对话式交互主界面 |
| 2 | Search | `/app/search` | `POST /knowledge/search` | 知识库语义搜索 |
| 3 | History | `/app/history` | `GET /conversations?user_id=` | 历史对话列表 |
| 4 | Login | `/app/login` | JWT auth | 登录页（与 admin 共用认证体系） |

**不需要的 Admin 页面**: Sessions、Capabilities、Plan&Invoke、Streaming、Audit、Langfuse。这些概念对终端用户不可见。

---

## 四、页面设计

### 1. Chat（主页）

```
┌─────────────────────────────────────────────┐
│ ⚡ EARP Assistant                    [User]  │ ← 顶部导航
├─────────────────────────────────────────────┤
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ 🤖 Hello! I'm EARP Assistant.      │   │ ← AI 回复
│  │ How can I help you today?          │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ┌──────────────────────────────┐         │
│  │ 👤 Query all active users   │         │ ← 用户消息
│  └──────────────────────────────┘         │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ 🤖 Found 5 active users:           │   │
│  │  • Alice (u1) — online             │   │
│  │  • Bob (u2) — online               │   │
│  │  • ...                             │   │
│  └─────────────────────────────────────┘   │
│                                             │
├─────────────────────────────────────────────┤
│ [___________________________] [Send]  📎    │ ← 输入栏
└─────────────────────────────────────────────┘
```

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| 对话区 | 滚动列表 | 展示用户消息（右对齐、浅蓝背景）和 AI 回复（左对齐、白底）。自动滚动到最新 |
| 输入框 | 文本 | 用户输入自然语言需求。回车或点击 Send 提交 |
| Send 按钮 | 操作 | `POST /conversations/{id}/messages {role: "user", content: "..."}`。触发 AI 回复 |
| 📎 附件按钮 | Phase 2 | 上传文件作为上下文（`POST /knowledge/documents`） |
| 顶部标题 | 显示 | "EARP Assistant" + 当前用户名 |
| New Chat 按钮 | 操作 | 创建新对话，清空当前对话区 |

**场景**: 客服代表查询用户信息、分析师让 EARP 生成报表、知识工作者搜索文档。

**API 链路**:
1. 页面加载 → `POST /conversations {title: "New Chat"}` → 获取 `conversation_id`
2. 用户输入 → `POST /conversations/{id}/messages {role:"user", content:"..."}`
3. 后端: LLM Planner → Capability 调用 → 返回结果 → SSE 流式输出到对话区

**流式输出**: 与 Admin Streaming 页面相同技术（SSE `text/event-stream`），但 UI 是逐 token 追加到最新 AI 消息气泡中。

---

### 2. Knowledge Search

```
┌─────────────────────────────────────────────┐
│ ⚡ EARP               Chat  Search  History  │
├─────────────────────────────────────────────┤
│ [Search documents...              ] [Search] │
├─────────────────────────────────────────────┤
│                                             │
│  📄 Getting Started (doc-001)              │
│  EARP is an enterprise AI runtime...       │
│  Relevance: 92%                            │
│                                             │
│  📄 API Reference (doc-002)               │
│  The EARP API provides REST endpoints...   │
│  Relevance: 87%                            │
│                                             │
│  📄 Deployment Guide (doc-003)             │
│  Deploy EARP using Docker Compose...       │
│  Relevance: 73%                            │
│                                             │
└─────────────────────────────────────────────┘
```

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| 搜索框 | 文本 | 输入查询关键词 |
| Search 按钮 | 操作 | `POST /knowledge/search {query, top_k: 10}` |
| 搜索结果 | 列表 | 每项显示: 文档名、内容摘要（前 150 字符）、相关度分数（百分比） |
| 结果点击 | 交互 | 展开完整 chunk 内容 |

---

### 3. History

```
┌─────────────────────────────────────────────┐
│ ⚡ EARP               Chat  Search  History  │
├─────────────────────────────────────────────┤
│                                             │
│  💬 Support Chat         23 msg  2h ago    │
│  💬 Bug Report            5 msg  yesterday  │
│  💬 Data Analysis        12 msg  3 days ago │
│                                             │
└─────────────────────────────────────────────┘
```

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| 对话列表 | 列表 | 每项显示: 标题、消息数、最后活跃时间。点击进入该对话 |
| 搜索/筛选 | Phase 2 | 按标题或日期范围筛选 |

---

## 五、安全

与 Admin Dashboard 一致，复用 JWT 认证。User App 不需要 admin role。

| 维度 | 方案 |
|:---|:---|
| 认证 | `EARP_AUTH_STRATEGY=dev-skip`（本地）/ JWT Bearer（生产） |
| 授权 | Conversation 自动绑定 `tenant_id` + `user_id`。用户只能看自己的对话 |
| 租户隔离 | 所有查询自动注入 `tenant_id` |
| 速率限制 | 用户端 100 req/min（低于 admin 的 1000） |

---

## 六、风险

| 风险 | 缓解 |
|:---|:---|
| 用户不理解"对话即操作"模式 | 首次使用时展示引导消息（"Try asking: Query all users"） |
| LLM 响应质量不可控 | 后端已有 Planner + Capability 校验链，无效 capability_id 会被丢弃 |
| 流式输出 UI 抖动 | 固定气泡容器高度 + `overflow-anchor: auto` |
