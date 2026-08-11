# 任务清单 — Chat 智能体（P1 问答链路一期）

**状态：待确认后开工**
**依据：`arch/design/2026-08-11-chat-agent-design.md`（r1 12/12 + r2 2/2 评审闭环，通过）**
**日期：2026-08-11**

## Phase 1a — 数据与链路（后端）

| # | Task | 关联设计 | 涉及文件 | 预估 |
|:-:|:-----|:------:|:---------|:----:|
| 1 | migration 0014：`chat_apps` 表（含 retrieval 默认值）+ `messages.citations JSONB` + `conversations.chat_app_id`（FK→chat_apps **ON DELETE SET NULL**） | §4.1（CP1/N1/CP5） | migrations/versions/0014_chat_apps.py | 中 |
| 2 | `chat_app_service.py`：chat_apps CRUD（create draft / list RLS / get / update published→draft / delete 硬删）+ publish 状态机 + 审计事件发布（`earp.chat_app.created/updated/deleted/published`） | §4.2/§4.6（F2） | src/earp_server/conversation/chat_app_service.py + service.py 接口导出 | 中 |
| 3 | `chat_apps` 路由组：GET/POST /chat_apps、PATCH/DELETE /chat_apps/{id}、POST /chat_apps/{id}/publish | §4.2 | src/earp_server/main.py | 小 |
| 4 | `GET /conversations` 列表端点（id/标题/chat_app_id/message_count/最后消息时间）+ GET messages 响应补 citations | §4.2（Q1/Q2） | src/earp_server/conversation/conversation_service.py + main.py | 小 |
| 5 | `LLMConnector.chat_stream(system, history, query)` 新增 + 修复 `stream()` 忽略 model_override base_url | §4.4 | src/earp_server/connector.py | 中 |
| 6 | `search_chunks` 结果增强：`_SELECT_COLS` 补 `kb_id/kb_name/d.metadata`（纯增量） | §4.5 | src/earp_server/knowledge/search_service.py | 小 |
| 7 | `chat_service.py`：POST /chat_apps/{id}/chat SSE 编排——会话创建/续接（chat_app_id 归属、标题=首问截断 30 字）、用户消息先 commit、多轮 (user,assistant) 配对取 N 对、检索（kb_scope 空→软路由/限定 KB 静默过滤）、拼提示词（app.system_prompt + 结构尾巴含 `[N]` 编号规则）、chat_stream 流式、done 后助手消息+citations commit | §4.3（CP3/CP4/S1） | src/earp_server/conversation/chat_service.py + main.py（SSE StreamingResponse） | 大 |
| 8 | 模型三级解析 helper：`chat_apps.model_config_id → get_system_model_settings(llm) → env`（复用 admin/model_service） | §4.4（CP2） | src/earp_server/conversation/chat_service.py（内部 helper） | 小 |
| 9 | main.py lifespan 挂 `app.state.llm = llm_connector`；entrypoints/audit.py 增加 `earp.chat_app.*` 订阅 | §4.6（N2） | src/earp_server/main.py + entrypoints/audit.py | 小 |
| 10 | import-linter：conversation → knowledge.embedding_service / knowledge.search_service / knowledge.routing / connector 加 ignore_imports（注明 chat=RAG 编排层） | §4.6 | apps/earp-server/pyproject.toml | 小 |

## Phase 1b — 前端

| # | Task | 关联设计 | 涉及文件 | 预估 |
|:-:|:-----|:------:|:---------|:----:|
| 11 | `chat.html`：智能体卡片网格 + 「+ 新建」模态（命名+描述）→ 创建后跳编排页 | §5.1 | apps/earp-admin/pages/chat.html + css/admin.css | 中 |
| 12 | `chat-edit.html?app=app-xxx`：编排页左右分栏——左（大模型下拉/提示词 textarea+重置/KB 多选+全租户/检索参数/多轮轮数）、右（调试对话：流式+引用卡+error 提示）、顶部保存/发布（已发布保存→回 draft 提示） | §5.2 | apps/earp-admin/pages/chat-edit.html + css/admin.css | 大 |
| 13 | `apps.html`：应用中心新建页——展示 status=published 的 chat 智能体卡片（只读，「我的应用」规划中） | §5.3（F1） | apps/earp-admin/pages/apps.html | 小 |
| 14 | 导航联动：nav.js 工作台 chat→chat.html（去 planned）、PLANNED 删 workspace/chat、应用中心概览→apps.html；index.html 快捷卡「chat 问答」更新 | §5.4 | apps/earp-admin/js/nav.js + index.html | 小 |

## Phase 1c — 验证

| # | Task | 关联设计 | 涉及文件 | 预估 |
|:-:|:-----|:------:|:---------|:----:|
| 15 | pytest `test_chat_apps.py`：CRUD/RLS/发布状态机（published→draft）/删除含会话 app 对话日志保留（SET NULL）/审计事件 | §8.1 | apps/earp-server/tests/test_chat_apps.py | 中 |
| 16 | pytest `test_chat.py`：链路闭环（会话+用户消息+检索+流式+助手消息+citations）、多轮配对、kb_scope 软路由/限定/无权限静默过滤、引用字段完整、SSE token/done/error、chat_stream model_override | §8.1 | apps/earp-server/tests/test_chat.py | 大 |
| 17 | `scripts/verify_chat.py`：QA 评估集（单轮事实/元数据纯语义/多轮追问/拒答）+ 引用命中 ≥80% 跑分（真模型 bge-m3+ollama，人工抽检要点） | §8.2（I1） | scripts/verify_chat.py | 中 |
| 18 | OpenAPI 基线同步 + import-linter 全量 + 全量回归（现 63 tests 保持绿） | §4.6/§8 | apps/earp-server/scripts 或仓库惯例 | 中 |
| 19 | task-log + commit + session-record 更新 + 前端冒烟（test-nav-smoke 补 chat 场景） | — | arch/session-record.md + apps/earp-admin/test-nav-smoke.cjs | 小 |

## 依赖关系

- Task 1（migration）→ 2/4/7（表结构前置）
- Task 5（chat_stream）→ 7（SSE 生成依赖）
- Task 6（search 增强）→ 7（citations 需要 kb_id/kb_name/metadata）
- Task 8 → 7（模型解析在链路内使用）
- Task 2/3/4/9/10 → 15（CRUD/审计测试）
- Task 7 → 16（链路测试）
- Task 2-14 → 19（收尾）
- **建议执行序：1 → (2,3,5,6 并行) → (4,8,9,10 并行) → 7 → (15,16 并行) → 17 → 18 → 11,12 → 13,14 → 19**

## 风险提示

1. **SSE 测试**：FastAPI StreamingResponse + httpx ASGI 客户端逐事件断言；流式中断/异常路径需 mock LLM（MockTransport）
2. **LLM 依赖**：CI 无 Ollama → pytest 全 mock；`verify_chat.py` 需 dev 环境真模型（Ollama + bge-m3），沿用 verify_routing.py 模式
3. **messages.seq 并发**：沿用现有 `MAX(seq)+1`（add_message 模式），chat 链路复用不另造轮子
4. **import-linter**：新 ignore_imports 条目必须在 pyproject.toml 声明并注明原因，CI 强制
5. **前端回归**：nav.js 改动后跑 test-nav-smoke.cjs + 新增 chat 场景断言；流式复用 app.js streamSSE（勿复制新实现）
6. **模型配置语义**：chat_apps.model_config_id 引用不存在/跨租户配置 → 校验返回 422（对齐 model_service 校验模式）

---
**确认后开始 Phase 1a 编码。**
