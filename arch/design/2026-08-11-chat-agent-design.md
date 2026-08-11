# Chat 智能体（工作台 · chat）设计

- 日期: 2026-08-11
- 状态: 定稿（待实施，P1 问答链路一期）
- 关联: `arch/session-record.md` P1（A1 问答链路 + P7 引用溯源并入）；`arch/design/2026-08-11-admin-navigation-redesign.md`（决策 #4 chat 概念、§5 应用发布流程）；`arch/design/2026-08-09-enterprise-retrieval-design.md`（软路由/元数据过滤/评估集）
- 参考: Dify 应用编排模式（智能体列表 → 编排页：左配置/右调试预览）

## 1. 背景与目标

后台导航改版后，工作台 → chat 为「规划中」。P1 问答链路落地 chat：基于知识中心内容的问答（query → 检索 → LLM 生成回答 → 带引用溯源）。

**职责澄清**（对齐导航改版 §5 应用发布流程）：

| 位置 | 形态 | 一期 |
|---|---|---|
| 工作台 · chat | **编排 + 测试工作台**：创建 chat 智能体、配置（提示词/KB/模型/检索参数）、调试对话、发布 | ✅ 本次实现 |
| 应用中心 | 展示已发布智能体（只读；最终使用界面二期） | ✅ 基础列表 |
| earp-user | 应用商店 / 我的应用 / 最终对话界面 | 后续 |
| 发布评审 | 审批人查看智能体开放的数据与能力 → 设置可见范围 | 二期 |

## 2. 决策记录（8 项）

| # | 议题 | 决策 |
|---|---|---|
| 1 | 检索范围 | **C 混合**：默认全租户软路由（复用 `/knowledge/search` 无 scope 语义）；chat 应用可绑定 KB 列表限定范围（空 = 全租户自动路由） |
| 2 | 回答方式 | **SSE 流式**：逐 token 渲染，末尾 `done` 事件携带引用；复用 `app.js streamSSE` 与 `LLMConnector.stream` 基建 |
| 3 | 多轮上下文 | **最近 N 轮进 LLM（默认 6，可配）**，检索 embedding 始终只用当前问题原文（追问指代靠 LLM 上下文消解，检索不污染） |
| 4 | 引用溯源 | **行内角标 `[1]` + 底部依据卡**：LLM 按编号上下文生成标注；citations JSONB 落库（对话日志二期共用） |
| 5 | 工作台形态 | **智能体卡片列表 + 编排页左右分栏**（无左侧列表栏）：列表页「新建」模态（命名+描述）→ 生成 chat 智能体 → 编排页 |
| 6 | 提示词 | **chat 应用级可编辑**（Dify 一致）：`chat_apps.system_prompt`，创建时预填默认模板；**结构尾巴代码内置不可改**（引用标注规则/内容边界/历史格式），引用机制不坏 |
| 7 | 发布语义 | 一期 **直接发布**（draft→published，审计）；**编辑已发布 → 回 draft 需重新发布** |
| 8 | 验收 | **机制层 pytest + 效果层 QA 评估集**（真模型，人工抽检要点与引用命中） |

## 3. 概念模型

```
chat 智能体（chat_apps）= 工作台配置单元
  ├─ 配置：名称/描述/系统提示词/KB 绑定/检索参数/大模型选择/多轮轮数
  ├─ 调试：测试对话（流式 + 引用卡）
  └─ 发布：draft → published → 应用中心可见（二期：pending_review + 可见范围）
应用（应用中心）= published 的 chat 智能体的对外形态（二期最终使用界面）
测试对话 = conversations/messages 复用（落库，审计可查，一期不提供列表 UI）
```

## 4. 后端设计

### 4.1 数据模型（migration **0014**，0013 已被 kb_summary_text 占用）

```sql
chat_apps (
    chat_app_id     VARCHAR(64) PRIMARY KEY,      -- app-xxx
    tenant_id       VARCHAR(64) NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    system_prompt   TEXT NOT NULL DEFAULT '<默认模板>',  -- 人设部分；结构尾巴代码内置

-- 默认提示词模板（创建时预填，可编辑；结构尾巴代码内置不可改）：
--   「你是企业知识库智能助手。请基于提供的资料准确回答用户问题；
--     资料不足时明确说明，不要编造。回答用中文，简洁清晰。」
    kb_scope        JSONB NOT NULL DEFAULT '[]',  -- [] = 全租户软路由；否则限定 KB 列表
    retrieval       JSONB NOT NULL DEFAULT '{"mode": "hybrid", "top_k": 5, "threshold": 0.0}',  -- CP5：定默认值
    model_config_id VARCHAR(64) NULL REFERENCES model_configs (config_id),  -- NULL = 系统默认
    context_turns   INTEGER NOT NULL DEFAULT 6,
    status          VARCHAR(16) NOT NULL DEFAULT 'draft',   -- draft | published（二期 + pending_review）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_chat_apps_tenant ON chat_apps (tenant_id, created_at);

ALTER TABLE messages ADD COLUMN citations JSONB;   -- 引用数组：见 4.3
ALTER TABLE conversations ADD COLUMN chat_app_id VARCHAR(64) NULL
    REFERENCES chat_apps (chat_app_id);              -- CP1：会话归属（二期应用形态/会话隔离直接可用）
```

### 4.2 端点

```
GET    /chat_apps                        # 列表（RLS 租户隔离）
POST   /chat_apps                        # 创建（draft）
PATCH  /chat_apps/{id}                   # 更新（published → 自动回 draft）
DELETE /chat_apps/{id}                   # 删除（硬删 + 审计）
POST   /chat_apps/{id}/publish           # draft → published（审计）
POST   /chat_apps/{id}/chat              # SSE 流式对话（见 4.3）
GET    /conversations                    # 新增端点（Q1）：会话列表（id/标题/chat_app_id/message_count/最后消息时间）
GET    /conversations/{id}/messages      # 已存在；响应补 citations 字段
# Q2 承接：GET /conversations 是运行监控「对话日志」（现静态页 conversations.html）
# 的第一个真实数据源；一期仅建端点供 chat 链路/二期应用形态使用，对话日志 UI 升级留二期（P7）
```

### 4.3 chat 链路（chat_service.py，单编排：无独立外部 API 调用，非 DB 长事务）

```
POST /chat_apps/{app_id}/chat  { query, conversation_id? }  → SSE
  ① 校验 app 存在且属于当前租户
  ② 会话：conversation_id 空 → 新建（标题 = 首问截断 30 字，chat_app_id 归属写入）；否则续接
  ③ 落库用户消息（seq++，先 commit —— CP4：逐步提交，SSE 开始前用户消息已可见）
  ④ 取最近 context_turns 轮历史：按 (user, assistant) 配对取最近 N 对（S1：孤立 user 消息跳过，
     避免连续两条 user 破坏 role 交替）；只进 LLM 上下文
  ⑤ 检索：kb_scope 空 → route_query 软路由；否则限定 KB（角色无权限 KB 静默过滤，不硬拒绝）
  ⑥ 拼提示词 = app.system_prompt + 结构尾巴
  ⑦ LLMConnector.chat_stream 流式生成（DB 模型配置驱动，见 4.4）
  ⑧ done 后落库助手消息 + citations JSONB（commit）
```

**citations 结构**（search_chunks 结果增强后携带）：
```json
[{ "chunk_id": "...", "document_id": "...", "title": "费用报销流程手册",
   "kb_id": "kb-1", "kb_name": "财务制度库", "metadata": {"version": "v3", "year": 2024},
   "similarity": 0.83 }]
```

**引用编号规则（CP3，写死在结构尾巴）**：检索结果按 `[1]..[N]` 编号（与返回顺序一致）；LLM 引用用对应编号；`citations` 数组顺序 = 编号顺序（citations[0] ↔ [1]）。

**SSE 事件**：
```
data: {"type":"token","content":"…"}
data: {"type":"done","message_id":"msg-xxx","citations":[...]}
data: {"type":"error","message":"…"}     # LLM/embedding 不可用等
```

### 4.4 LLM 补强

- `LLMConnector.chat_stream(system, history, query)`：新增方法，payload 为完整 messages 列表（system + 历史 + 当前问题）
- **修复 `stream()` 忽略 model_override 的 base_url 问题**（当前直接用 settings.ollama_base_url）；chat_stream 支持 DB model_configs 驱动（provider/model_name/base_url/api_key）
- **模型三级解析链（CP2）**：`chat_apps.model_config_id → system_model_settings(llm)（PRD-031 Layer 3）→ env`；无配置时回落系统默认，消除「系统默认」歧义

### 4.5 检索结果增强（search_service.py）

`_SELECT_COLS` 增量补 `kb.knowledge_base_id AS kb_id, kb.name AS kb_name, d.metadata`——纯增量，现有调用方不受影响。

### 4.6 权限 / 审计 / 架构合规

- chat_apps 走 RLS 租户隔离；检索链路沿用现有 role 过滤
- 审计事件：chat_app 创建 / 修改 / 删除 / 发布 → 类型 **`earp.chat_app.created / updated / deleted / published`**（F2）；main.py 增加 `earp.chat_app.*` 订阅（audit handler 通用，写 audit_logs）
- 测试对话落库 conversations/messages（对话日志与审计可追溯），不单独发审计事件
- import-linter：conversation → `knowledge.embedding_service` / `knowledge.search_service` / `knowledge.routing` / `connector` 加 ignore_imports 条目（注明原因：chat 为 RAG 编排层）
- OpenAPI 基线同步（仓库惯例）

## 5. 前端设计

### 5.1 `pages/chat.html` — 智能体列表

- 卡片网格：已创建 chat 智能体（名称 / 描述 / 状态徽标 draft|已发布）
- 「+ 新建」功能按钮 → 模态框（**命名 + 描述**）→ 确定 → 创建（draft）→ 自动进入编排页
- 空态：引导新建

### 5.2 `pages/chat-edit.html?app=app-xxx` — 编排页（左右分栏）

```
┌─ 顶部: 智能体名 · 状态徽标 ─────────────── [保存] [发布] ─┐
│ 左栏（配置）                │ 右栏（调试预览）             │
│ 大模型选择（下拉，空=默认）  │ ┌──────────────────────┐    │
│ 系统提示词 textarea（+重置）│ │ 对话显示窗口           │    │
│ KB 绑定（多选 + 全租户开关）│ │ 流式回答 + 引用卡       │    │
│ 检索参数 mode/top_k/thr    │ └──────────────────────┘    │
│ 多轮轮数 context_turns     │ [输入问题框] [发送]           │
└────────────────────────────┴───────────────────────────┘
```

- **保存**（PATCH）：已发布应用保存 → 自动回 draft 并提示「已修改，需重新发布」
- **发布**（POST publish）：draft → published，成功提示「已发布，可在应用中心查看」
- 调试预览：Enter 发送；流式渲染（token 事件）；done 后渲染引用卡（标题/KB/元数据徽标，点击跳 `knowledge.html?kb=xxx`）；error 红条提示

### 5.3 `pages/apps.html` — 应用中心（**新建页**，F1：当前不存在，nav.js 现指向 planned.html?section=apps）

- 展示 `status=published` 的 chat 智能体卡片（只读；点击提示「使用界面二期开放」）
- 「我的应用」仍规划中（earp-user 侧）

### 5.4 导航联动（nav.js / index.html）

- 工作台 drawer：chat 项 → `chat.html`（去「规划中」标签）；PLANNED 删除 `workspace/chat`
- 应用中心 drawer：概览 → `apps.html`（真实页）；「我的应用」保留规划中
- index.html 快捷卡「chat 问答」→ `chat.html`，去「规划中 →」文案

## 6. 发布与评审（一期 vs 二期）

**一期**：直接发布（draft → published）+ 审计；应用中心可见（读 chat_apps status=published）。
**二期（本期不做，设计预留）**：

```
发布 → 提交评审（pending_review）
  → 审批人查看智能体开放的 KB 范围 / 数据分类 / 检索能力
  → 设置可见范围（visible_scope：角色/用户组授权，如财务智能体仅限财务部）
  → 通过（published + 可见范围生效）/ 驳回（rejected）
```

- chat_apps 二期加：`visible_scope JSONB`、状态机扩展（pending_review/rejected）
- 关联：治理中心 Roles 权限管理（tech-debt #9 / P8）；与角色域权限联动
- conversations.chat_app_id 一期已就位（CP1），二期会话隔离/按应用列表直接可用
- 一期**不预加字段、不做审批 UI**（避免过度设计）

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| LLM 不可用 / embedding 失败 | SSE `error` 事件 → 前端红条「回答生成失败，请稍后重试」；用户消息已落库，可重新提问 |
| 流中断（无 done） | 前端提示「回答中断」 |
| 会话/应用不存在或跨租户 | 404（RLS 兜底） |
| 发布前未测试 | 不强制（提示性引导，不阻塞） |
| 停止按钮 / 重试按钮 | 一期不做（YAGNI） |

## 8. 测试与评估

### 8.1 机制层（pytest：`tests/test_chat_apps.py` + `tests/test_chat.py`）

| 用例 | 验证点 |
|---|---|
| chat_apps CRUD | 创建（draft）/列表（RLS）/更新/删除 |
| 发布状态机 | draft→published；编辑已发布→回 draft；发布写审计 |
| 链路闭环 | 会话创建→用户消息落库→检索→流式→助手消息+citations 落库 |
| 检索范围 | kb_scope=[] 软路由；限定 KB 生效；无权限 KB 静默过滤 |
| 多轮上下文 | 第 2 问 prompt 含最近 N 轮；检索只用当前问题 |
| 引用对齐 | mock 检索 2 chunk → citations 完整字段 |
| SSE 格式 | token/done/error 事件正确 |
| chat_stream | model_override 驱动；无配置回落 env |
| 审计 | 创建/修改/删除/发布事件 |

### 8.2 效果层（`scripts/verify_chat.py`，QA 评估集）

5-8 问覆盖：单轮事实问答 / 元数据问题 / 多轮追问（指代消解）/ 拒答（知识库外问题不编造）。
真模型（bge-m3 + ollama）跑；验收：**引用文档命中 ≥ 80%**（期望文档在 citations 中）+ 回答要点人工抽检；路由层沿用现有 ≥90% 基线。
**元数据问题验收口径（I1）**：chat 链路一期**不暴露 metadata_filters 配置**（该能力属文档管理层属性过滤；检索时随 chunk 返回 documents.metadata，citations 携带供引用展示）；评估用例「2024 年的报销标准」按**纯语义命中**验收（期望文档在 citations 中即可），不要求结构化过滤命中。

### 8.3 前端验收

卡片列表/新建/编排（左右分栏）/调试对话（流式+引用卡）/发布 → 应用中心可见；导航联动（工作台 chat 点亮、应用中心真实页、index 快捷卡）。

## 9. 落地路径（实施顺序）

```
Phase 1a（数据与链路）：
  ① migration（chat_apps + messages.citations）
  ② chat_service + 端点（CRUD/publish/chat SSE/GET /conversations）
  ③ LLMConnector.chat_stream + 修 stream() base_url
  ④ search_chunks 补 kb_id/kb_name/metadata
Phase 1b（前端）：
  ⑤ chat.html 卡片列表 + 新建模态
  ⑥ chat-edit.html 编排页（左配置/右调试预览 + 发布）
  ⑦ apps.html 应用中心（published 展示）
  ⑧ nav.js / index.html 联动
Phase 1c（验证）：
  ⑨ pytest 机制层 + scripts/verify_chat.py 效果评估
  ⑩ OpenAPI 基线同步 + import-linter 保持
```

## 10. 开放项（二期）

1. 发布评审流程 + 可见范围（见 §6）
2. 应用中心最终使用界面（会话列表 + 对话区——本设计早前方案，二期承接；conversations.chat_app_id 已就位）
3. 对话日志引用展示与 UI 升级（conversations.html 静态页 → GET /conversations 真实数据 + messages.citations 渲染，P7）
4. rerank 精排接入检索参数（P3）
5. 测试对话停止/重试按钮
