# PRD-2026-029: User Application Frontend

**版本**: v1.1 (页面功能说明)
**日期**: 2026-07-21
**状态**: Phase 1 — 待人工审核

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
3. 后端: LLM Planner → Domain Routing（二维决策，v2.1 新增 Data Domain 路径）
   ├── Business Domain → Capability 调用（用户请求涉及业务操作时）
   └── Data Domain → Knowledge Center 检索（用户请求涉及企业知识时）
   → LLM 合并结果 → SSE 流式输出到对话区

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

## 六、页面功能说明

---

### 6.1 Chat（`index.html`）— 对话主页

**用途**: 用户与 EARP 交互的唯一入口。用自然语言描述需求，AI 自动规划并执行，结果以对话形式展示。用户不需要理解 Plan、Capability、Session 等平台概念。

**角色**: 所有业务用户（客服代表、数据分析师、知识工作者）。不需要任何技术背景。

**场景**:
- 客服代表输入 "查询所有活跃用户" → AI 返回用户列表
- 数据分析师输入 "生成本周的执行统计报表" → AI 调用 Capability 并返回格式化结果
- 知识工作者输入 "搜索部署文档中关于 pgvector 的内容" → AI 搜索知识库并返回相关段落
- 新用户首次打开 → 看到欢迎消息和 3 个建议问题，点击即可快速体验

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| 欢迎消息区域 | 显示 | 首次打开时（无历史对话）展示。包含标题、一句话说明、3 个建议按钮。开始对话后自动消失 |
| 建议按钮 ×3 | 快捷操作 | 预设的自然语言问题模板，点击后自动填入输入框并提交。示例: "Query all active users" / "Search deployment guide" / "Generate weekly report"。帮助新用户理解平台能力边界 |
| 对话区 | 滚动列表 | 用户消息（右对齐、Indigo 蓝底白字气泡）和 AI 回复（左对齐、白底灰字气泡）交替展示。每条消息显示头像（👤/🤖）和时间戳。自动滚动到最新消息 |
| 输入框 | 文本域 | `textarea` 格式，自适应高度（min 44px, max 120px）。用户输入自然语言需求。按 Enter 提交（Shift+Enter 换行） |
| Send 按钮 | 操作 | 圆形蓝色按钮（↑ 箭头图标）。点击后: `POST /conversations/{id}/messages {role: "user", content: "..."}` → 触发 AI 处理（Planner 根据用户意图自动路由到 Data Domain 知识检索或 Business Domain 能力调用，或两者混合）。AI 回复通过 SSE 流式逐 token 追加到对话区 |
| 📎 附件按钮 | Phase 2 | 上传文件作为对话上下文。后端调用 `POST /knowledge/documents` 先存入知识库，再作为上下文注入 Planner |
| New Chat 按钮 | 操作 | 位于导航栏右侧或对话区顶部。点击后 `POST /conversations {title: "New Chat"}` → 清空对话区 → 重新显示欢迎消息 |
| 顶部导航 | 显示 | 品牌名 "EARP Assistant" + Chat/Search/History 标签 + 用户名。Chat 标签高亮（accent underline） |

**API 链路**:
1. 页面加载 → `POST /conversations {title: "New Chat"}` → 返回 `{conversation_id: "conv-001"}`
2. 用户输入 "查询活跃用户" → `POST /conversations/conv-001/messages {role: "user", content: "查询活跃用户"}` → 后端: Planner → Domain Routing
   ├── Business Domain → Resolution Engine → Capability Invoke（操作路径）
   └── Data Domain → Knowledge Center RAG 检索（知识路径）
   → LLM 合并两条路径结果 → 返回最终回答
3. AI 回复通过 SSE 流式输出 → `data: {"token": "Found", "index": 0}` → `data: {"token": " 5", "index": 1}` → ... → `data: [DONE]`
4. 每个 token 追加到当前 AI 消息气泡中，形成逐字打字效果

**设计要点**: 用户侧不暴露 Plan、Session ID、Capability ID 等概念。对话区只显示自然语言消息和结果。

---

### 6.2 Knowledge Search（`pages/search.html`）

**用途**: 语义搜索知识库中的文档内容。用户在对话中无法完整浏览的文档，可在此页面用关键词搜索并查看完整内容。

**角色**: 知识工作者、分析师。需要查找特定文档内容。

**场景**:
- 用户在对话中得到了相关文档的引用，点击 "查看详情" 跳转到此页面
- 用户想确认知识库中是否有某篇文档（如 "部署指南"），输入关键词搜索
- 用户浏览搜索结果，点击某条展开完整 chunk 内容

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| 搜索框 | 文本输入 | 输入查询关键词（如 "deployment"）。`input` 元素，支持回车触发搜索 |
| Search 按钮 | 操作 | 主要 CTA（蓝色按钮）。调用 `POST /knowledge/search {query: "...", top_k: 10}` → 返回匹配的 chunk 列表 |
| 搜索结果卡片 | 列表 | 每张卡片显示: 📄 文档标题（粗体） + 内容摘要（前 150 字符，灰字） + 相关度分数 + 文档 ID + 总 chunk 数。按相关度降序排列 |
| 相关度分数 | 显示 | 百分比（如 "92%"），来自 pgvector `<=>` 余弦距离的映射值。帮助用户判断结果可信度 |
| 结果卡片点击 | 交互 | 点击卡片 → 展开完整 chunk 内容（callout 样式）。再次点击收起 |
| 空结果状态 | 显示 | 当搜索无匹配时，显示 "未找到相关文档。尝试其他关键词。" 提示 |

**API**: `POST /knowledge/search {query: "deployment", top_k: 10}` → `[{chunk_id, document_id, document_title, content, score}]`

---

### 6.3 History（`pages/history.html`）

**用途**: 查看用户的所有历史对话。用户可以回到之前的对话继续交互，或查看过去的执行结果。

**角色**: 所有用户。需要回顾之前的对话内容。

**场景**:
- 用户昨天让 EARP 生成了报表，今天想查看结果 → 点击历史中的对话进入
- 用户有多个对话线程（客服、数据分析、故障排查），按需切换
- 用户清理不再需要的历史对话（Phase 2）

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| 对话列表 | 可点击卡片 | 每项显示: 💬 图标 + 对话标题（粗体） + 最后活跃时间（灰字，如 "2 hours ago"） + 消息数量（右侧灰字）。点击任意一项 → 跳转到 Chat 页面并加载该对话 |
| 页面标题 | 显示 | "History — Your recent conversations" |
| 搜索/筛选 | Phase 2 | 按标题关键词或日期范围筛选。placeholder 输入框 |

**API**: `GET /conversations?user_id=u1` → `[{conversation_id, title, message_count, last_active_at}]`（需新增查询参数支持）

**设计要点**: 列表卡片点击后跳转到 Chat 页面并携带 `?conversation_id=conv-001` 参数，Chat 页面加载对应对话的消息历史。

---

### 6.4 Login（`pages/login.html`）

**用途**: 用户登录页。与 Admin Dashboard 共用同一套 JWT 认证体系，但 User App 的用户通常没有 admin role。

**角色**: 所有用户。首次访问时未认证 → 重定向到此页面。

**场景**:
- 用户首次打开 User App → 跳转到登录页
- Token 过期后 → 重新登录
- 本地开发 → `EARP_AUTH_STRATEGY=dev-skip` 跳过登录，直接进入 Chat

**参数/元素**:

| 元素 | 类型 | 说明 |
|:---|:---|:---|
| Tenant ID | 文本输入 | 预填 `tenant-demo`。用户所属的租户标识 |
| User ID | 文本输入 | 预填 `u1`。用户唯一标识 |
| Password | 密码输入 | 用户密码（`type="password"`）。生产环境通过 JWT 签发验证 |
| Sign in 按钮 | 操作 | 主要 CTA（蓝色全宽按钮）。提交表单 → 调用 JWT 签发 API → 成功后将 token 存入 localStorage → 跳转 Chat 页面 |
| dev mode 提示 | 显示 | 底部灰色小字: "dev: EARP_AUTH_STRATEGY=dev-skip"。提醒开发者当前认证模式 |
| 错误提示 | Phase 2 | 登录失败时在表单顶部显示红色错误消息（如 "Invalid credentials"） |

**API**: 生产环境需新增 `POST /auth/login {tenant_id, user_id, password}` → `{token: "eyJ...", user_id, tenant_id}`。dev 模式跳过此步骤。

---

## 七、安全

与 Admin Dashboard 一致，复用 JWT 认证。User App 不需要 admin role。

| 维度 | 方案 |
|:---|:---|
| 认证 | `EARP_AUTH_STRATEGY=dev-skip`（本地）/ JWT Bearer（生产） |
| 授权 | Conversation 自动绑定 `tenant_id` + `user_id`。用户只能看自己的对话 |
| 租户隔离 | 所有查询自动注入 `tenant_id` |
| 速率限制 | 用户端 100 req/min（低于 admin 的 1000） |

---

## 八、风险

| 风险 | 缓解 |
|:---|:---|
| 用户不理解"对话即操作"模式 | 首次使用时展示引导消息（"Try asking: Query all users"） |
| LLM 响应质量不可控 | 后端已有 Planner + Capability 校验链，无效 capability_id 会被丢弃 |
| 流式输出 UI 抖动 | 固定气泡容器高度 + `overflow-anchor: auto` |
