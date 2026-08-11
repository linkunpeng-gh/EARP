# Chat 智能体设计评审报告 v1.0

- 日期: 2026-08-11
- 评审对象: `arch/design/2026-08-11-chat-agent-design.md`（定稿，待实施）
- 评审方法: 7 维架构评审（software-architecture-review skill）+ 代码事实核对（migrations / connector / search_service / conversation / routing / nav.js / index.html / audit）
- 结论: **有条件通过** —— 1 个事实错误 + 4 个 P1 决策补丁，修后可开工

## 评审概览

| 维度 | 评分 | 问题数 |
|------|:----:|:------:|
| 一致性 | 8/10 | 2 |
| 完整性 | 7/10 | 5 |
| 合理性 | 8/10 | 1 |
| 可行性&演进性 | 8/10 | 2 |
| 规范质量 | 8/10 | 2 |
| 评审延续性 | 9/10 | 0 |
| **总分** | **8.0/10** | **12** |

## 代码事实核对（全部实证）

| 设计声明 | 核实结果 |
|---|---|
| migration 编号顺延 0013 | ❌ **已存在 `0013_kb_summary_text.py`**，应为 0014 |
| 修 stream() 忽略 model_override base_url | ✅ 属实：`connector.py:295` 直接用 `self._settings.ollama_base_url`，忽略构造器已算好的 `self._base_url` |
| model_config_id REFERENCES model_configs(config_id) | ✅ 0009_model_config.py PK = config_id |
| messages 加 citations JSONB | ✅ 0001_baseline messages 表（message_id/tenant_id/conversation_id/seq/role/content/created_at + UNIQUE(conversation_id,seq)），加列兼容 |
| 会话 seq++ | ✅ add_message 已用 MAX(seq)+1 模式 |
| search_chunks 增量补 kb_id/kb_name/metadata | ✅ `_SELECT_COLS`（search_service.py:68）纯增量可行，kb 已 JOIN |
| 限定 KB + 无权限静默过滤 | ✅ search_chunks 支持 knowledge_base_ids + accessible_roles WHERE 过滤（静默，非硬拒绝） |
| kb_scope 空 = 软路由 | ✅ `/knowledge/search` 无 scope → route_query（retrieval design §0-4），routing.py 有权限过滤 |
| 复用 app.js streamSSE | ✅ js/app.js:54 |
| 导航联动 | ✅ nav.js: workspace/chat planned → chat.html；apps/overview planned → apps.html；index.html:40 快捷卡 |
| chat 概念 / 发布流程 / P7 并入 P1 | ✅ 对齐导航设计 #4/#5、session-record P1 |

## 各维度详情

### 1. 一致性（8/10）

- ✅ 已确认：chat 概念（简单对话，推理留能力中心）对齐导航设计 #4；发布流程对齐 §5；软路由/元数据过滤/评估集对齐 retrieval design；P7 并入 P1 对齐 session-record
- ❌ **I1（P1，高）**：§8.2 评估集含「元数据问题」用例，但 §4.1 `retrieval` 只有 `{mode, top_k, threshold}`，§4.3 链路 ⑤ 不注入 `metadata_filters` —— 评估项与实现能力不一致。"2024 年的报销标准"类问题在 chat 链路里只能靠语义向量命中，无结构化过滤，验收口径需明确（要么 retrieval 加 metadata_filters 字段，要么把该评估项标注为纯语义命中）
- ❌ **I2（P1，高）**：§4.1「编号顺延 0013」—— 0013 已被 kb_summary_text 占用，应为 **0014**（若按 0013 写会撞版本号）

### 2. 完整性（7/10）

- ✅ 已确认：正常路径（§4.3 ①-⑧）、异常路径（§7 错误表）、测试三层（机制/效果/前端）、落地路径（§9）、开放项（§10）均覆盖
- ❌ **CP1（P1，中-高）**：conversations 表无 `chat_app_id` 归属列。一期 GET /conversations（对话日志）+ 二期应用形态（每应用会话列表）都无法区分来源；二期必须迁移。建议一期即加 `conversations.chat_app_id VARCHAR(64) NULL REFERENCES chat_apps`（向后兼容，成本一次 migration 一列）
- ❌ **CP2（P1，中）**：`model_config_id NULL = 系统默认` 的解析链未定义。系统已有 `system_model_settings`（tenant, type='llm' → model_config_id）。应明确三级解析：`chat_apps.model_config_id → system_model_settings(llm) → env`，否则「系统默认」歧义（env 还是 DB 默认？），且与 PRD-031 模型中心语义脱节
- ❌ **CP3（P2）**：引用编号规则未定义 —— prompt 中检索资料如何编号（`[1]..[N]` 前缀）、`citations` 数组顺序与编号的对应关系。结构尾巴内置不可改，此规则应写死在结构尾巴定义里，保证 LLM 标注 [1] 与 citations[0] 对齐
- ❌ **CP4（P2）**：§4.3「单事务编排」与 ⑦ 流式长连接冲突 —— 若真单事务跨越 LLM 流，锁/连接被长时间占用，且 §7「用户消息已落库可重新提问」要求用户消息先可见。建议明确为逐步提交（用户消息先 commit，助手消息 done 后 commit），「单事务」指编排内无独立 API 调用，非 DB 事务
- ❌ **CP5（P2）**：`retrieval JSONB NOT NULL` 无默认值，创建时只收 name+description —— 默认检索参数（mode/top_k/threshold）未指定，需定默认值（建议 hybrid / top_k=5 / threshold 沿用现有基线）

### 3. 合理性（8/10）

- ✅ 已确认：检索 embedding 只用当前问题原文（指代消解靠 LLM 上下文）合理；结构尾巴内置不可改（引用机制不坏）合理；kb_scope 空=软路由复用现有语义；无权限 KB 静默过滤对齐现有 accessible_roles 行为
- ❌ **S1（P2）**：多轮历史取「最近 N 轮」未定义配对规则 —— 若失败轮（用户消息已落库、助手消息未落库）混入历史，会出现连续两条 user 消息破坏 role 交替。建议按 (user, assistant) 配对取最近 N 对，孤立 user 消息跳过

### 4. 可行性&演进性（8/10）

- ✅ 已确认：所有依赖基建均存在且路径明确（见事实核对表）；stream() base_url bug 修复范围小（改一处 URL 拼接）；chat_stream 新方法无阻塞
- ❌ **F1（P2）**：§5.3「占位页升级为真实页」表述不实 —— `apps.html` 当前**不存在**（nav.js apps → `planned.html?section=apps`），是新建页而非升级
- ⚠️ **F2（P2）**：审计事件类型未指定 —— audit consumer 当前只订阅 `earp.execution.*`（entrypoints/audit.py:32）。chat_app 审计事件需落入该命名空间或新增订阅，设计中未提

### 5. 规范质量（8/10）

- ✅ 已确认：端点清单、SSE 事件（token/done/error）、citations JSON 结构、落地路径 ①-⑩、测试用例表（§8.1 对齐 §4.3 链路）具体可测
- ❌ **Q1（P2）**：§4.2 `GET /conversations` 未标注为新端点 —— 当前 main.py 只有 POST /conversations、POST/GET /conversations/{id}/messages，列表端点需新建（设计隐含但未明示）
- ⚠️ **Q2（P2）**：现有 conversations.html（运行监控·对话日志）是静态页（无 fetch 调用），本设计 GET /conversations 实为对话日志的第一个真实数据源，建议在 §4.2 或 §5 点明承接关系

### 6. 评审延续性（9/10）

新设计文档，无历史评审遗留。关联引用完整（session-record / 导航改版 / retrieval 设计三向对齐），版本号标注「定稿（待实施）」清晰。

## Top 5 优先修复

| 优先级 | 问题 | 维度 | 影响 | 建议方案 |
|:------:|------|:----:|:----:|---------|
| P0 | I2: migration 编号 0013 已占用 | 一致性 | 高（撞版本号） | 改为 0014 |
| P1 | CP1: conversations 无 chat_app_id 归属 | 完整性 | 中-高（二期返工） | 一期 migration 加可空 chat_app_id 列 |
| P1 | CP2: 系统默认模型解析链未定义 | 完整性 | 中（语义歧义） | 明确 NULL → system_model_settings(llm) → env 三级解析 |
| P1 | I1: 元数据问题评估 vs 链路无 metadata_filters | 一致性 | 中（验收口径漂移） | retrieval 加 metadata_filters 字段，或评估项改标注为纯语义命中 |
| P2 | CP3: 引用编号规则未定义 | 完整性 | 低-中（引用对齐） | 结构尾巴写死编号规则（[N] 前缀 + citations 顺序对应） |

## 总体结论

**有条件通过。** 设计整体质量高：链路编排（①-⑧）、SSE 协议、citations 结构、三层验证体系均已接口级细化，且所有基建依赖经代码核对属实（含 stream() base_url bug 的真实性）。开工前只需修 1 个事实错误（migration 编号 → 0014）并补齐 3 个 P1 决策（chat_app_id 归属列、系统默认模型解析链、元数据问题验收口径），其余 P2 可在实施中顺手落实（编号规则写进结构尾巴、事务边界注明逐步提交、审计事件命名空间）。
