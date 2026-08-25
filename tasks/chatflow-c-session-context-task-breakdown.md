# 任务清单 — Chatflow C 系列: 会话上下文（会话记忆 + 指代消解 + 元数据/可见范围）

**状态：规划定稿，待开工**
**依据**：`arch/design/2026-08-18-chat-session-context-design.md`（C1-C6 拆分草案）+ F6 评估报告（D3 摸底 + 问题清单 #9/#5）
**依赖**：QU 角色层（understand 规则层 ✅，F6 `_history_context` 最小实现已落地 qu.answer 路径）
**日期**：2026-08-24

## 目标

1. **会话上下文落库**：每轮 chat 结束后，把本轮的**结构化理解结果**写回 `conversations.context`（last_entities / last_intent / last_relations）——指代消解从「每轮即时推导」升级为「有据可循」，可溯源、不逐轮重算 LLM
2. **规则层指代消解完整化**：`understand()` 读取 context →「它/这个/该设备」映射上文实体（mention → entity_id，含 semantic_type 回填）——**覆盖 auto（chat_sse）与 flow（qu.answer）两条路径**（F6 只补了 flow 路径）
3. **会话元数据 + 可见范围（二期前置）**：`last_active_at` / `message_count` / `status`；chat_apps 发布后按角色可见（visible_roles）
4. **验收量化**：指代命中率 ≥80%（并入 understanding_eval ctx 用例）；单轮/无 context 零回归

## 现状（已核实，2026-08-24）

- `conversations` 列：`conversation_id / tenant_id / user_id / title / created_at / chat_app_id`——**无 context / last_active_at / message_count / status 列**（C1 需 migration）
- `chat_apps` 列：无 `visible_roles`（C5 需要）
- F6 D3 已补**最小实现**（flow 路径）：`connector._history_context` 从 `_recent_pairs` 取上一轮用户消息做规则层理解，推导 `last_entities` 注入 qu.answer——**不落库、只覆盖 flow 的 qu.answer 路径**、只取「最近 user 消息」（上一条若是审批「确认」则指代源为空）
- `understanding.py` `_COREF_RE` 指代正则已存在：`(它|这个|该设备|该机器|这台|那台)`，映射 `context.last_entities`，但缺「entity_id 回填 + trace 记录」
- `understand()` 的 `context` 参数签名既有；`execute_plan` 透传 `ctx.context`
- **auto 模式（chat_sse）指代消解未接入**（问题清单 #9）——F6 摸底只覆盖 qu.answer 路径
- 最新 migration 0028；下一次从 0029 起

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 数据模型 | **migration 0029：`conversations.context JSONB DEFAULT '{}'` + `last_active_at TIMESTAMPTZ` + `message_count INT DEFAULT 0` + `status`（active/archived，一期先加列不强制）**——只存**上一轮**（last-*，QU §5.2），不存全量历史；对齐 0014 RLS 三件套 + GRANT |
| D2 | 写时机 | chat_sse 走 execute_plan / qu.answer 每轮结束 → upsert `conversations.context`（含 last_entities/last_intent/last_relations + updated_at）；**kb_scope 限定路径一期不写**（无结构化结果，保持理解层单源，设计稿开放问题 2） |
| D3 | 读时机 | `understand()`/`execute_plan` 读 context → 传入 `_extract_entities` 指代映射；**entity_id 回填**（last_entities 存 entity_id，指代直接映射实体，非仅 mention）；**trace 记录 references 映射**（设计稿 §2.4，可溯源非 LLM 盲猜） |
| D4 | F6 最小实现去留 | flow 路径 `_history_context` 保留为**兜底**（无落库 context 时即时推导），C 系列落库后**优先读 context、缺失再即时推导**——不破坏 F6 已验证行为 |
| D5 | 可见范围 | `chat_apps.visible_roles`（空=全员）/发布状态；GET /chat_apps 按角色过滤；会话查询统一走 chat_app 可见性（防「应用隐藏但对话可枚举」缝隙）——C5/C6 |
| D6 | 范围边界 | 会话级共享（同租户其他角色查看对话）**一期不做**（无 use case）；多轮连续指代（A→B→C 逐轮）先 last-*，Phase F 升级为会话记忆 |
| D7 | 测试策略 | 规则层 ctx 单测 + understanding_eval 并入 ctx 用例 + dev 真 API 两轮指代（复用 verify_f6 摸底应用，断言 conversations.context 已写）+ 回归 F0-F6 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5 → 6）

### Task 1 — migration 0029 会话上下文列（0.5 天）
**文件**：`migrations/versions/0029_conversation_context.py`（新）
- `conversations.context JSONB DEFAULT '{}'`、`last_active_at`、`message_count`、`status`
- RLS 三件套 + GRANT；`test_migrations.EXPECTED_TABLES` / `test_rls` 更新
- 验证：migration 往返 + RLS 隔离

### Task 2 — 读写在链路（chat_sse + qu.answer）（1 天）
**文件**：`src/earp_server/conversation/chat_service.py`、`src/earp_server/ontology/understanding.py`、`src/earp_server/connector.py`
- `chat_sse`：execute_plan 路径每轮结束 upsert context（last_entities/last_intent/last_relations + updated_at）
- `flow` qu.answer：同上写 context（复用 F6 `_history_context` 的实体提取，改为落库）
- `_recent_pairs`/`context_turns` 语义保持不变
- 验证：单测（写库后读回）+ dev 两轮对话 context 已写

### Task 3 — 规则层指代消解完整化 + entity_id 回填 + trace（1 天）
**文件**：`src/earp_server/ontology/understanding.py`
- `_extract_entities` 读 context.last_entities 中的 entity_id → 指代 direct 映射实体（含 semantic_type 回填）
- 记录 `references` 映射到 RuleResult（trace 可溯源，align 设计稿 §2.4）
- **auto 路径接入**：chat_sse 的 `_retrieve`→`understand` 传 context（补 F6 缺口 #9）
- 验证：指代单测（「CNC-01 供应商」→「它的更换周期呢」）+ understanding_eval ctx 用例

### Task 4 — 评估：understanding_eval ctx 用例 + 命中率门槛（0.5 天）
**文件**：`tests/fixtures/understanding_eval.md`（新 ctx 用例）、`tests/test_understanding_eval.py`
- 并入指代消解用例，QQ 门槛 ≥80%
- 回归：单轮/无 context 零回归
- 验证：评估集全绿 + 门槛达标

### Task 5 — chat_apps 可见范围（visible_roles + 过滤）（1 天）
**文件**：`migrations/versions/0030_chat_apps_visible_roles.py`（新）、`src/earp_server/conversation/chat_app_service.py`、`src/earp_server/conversation/chat_service.py`
- `chat_apps.visible_roles JSONB DEFAULT '[]'`（空=全员 loose 语义）
- GET /chat_apps 按角色过滤；conversations 查询走 chat_app 可见性（防缝隙）
- 验证：角色可见性单测（admin 全员 / 指定角色可见 / 不可见 404）

### Task 6 — 前端对话可见范围（0.5-1 天，可选）
**文件**：`apps/earp-admin/...`（chat-edit 发布面板 + 对话列表）
- 发布面板加「可见角色」选择（visible_roles）；对话列表按角色过滤
- 对齐 C5 后端；进度可在 C5 后串行
- 验证：前端冒烟

## 依赖关系

```
Task 1（migration）→ Task 2（读写链路）→ Task 3（指代消解）→ Task 4（评估门槛）
Task 5（可见范围）独立于 1-4，可与 2 并行；Task 6 依赖 5
```

**建议执行序**：`1 → 2 → 3 → 4`（核心），`5 → 6`（可见范围，可并行/后置）

## 验收标准

1. dev 真 API 两轮指代：`conversations.context` 已写 last_entities；auto 与 flow 两条路径均解析「它→CNC-01」
2. 指代映射可溯源（references 记录，非 LLM 盲猜）；命中率 ≥80%（understanding_eval）
3. 单轮/无 context 零回归
4. chat_apps 发布可见范围按角色过滤；对话不可枚举缝隙闭合
5. 全量 pytest 绿 + ruff/pyright 零新增

## 风险提示

1. **上一条是审批「确认」时指代源为空**（F6 实测）：落库后 last_entities 来自「真正带实体的用户轮次」，审批确认轮覆写 context 会污染——**写 context 只写「实体非空」的轮次**（D2 补充：空实体不覆写 last_entities）
2. **只存上一轮够不够**（开放问题 1）：多轮连续指代留 last-*，Phase F 升级会话记忆——防膨胀
3. **kb_scope 限定路径不写 context**（设计稿决策）：保持理解层单源，不破坏现状
4. **可见范围改动涉及 chat 既有语义**：默认 visible_roles 空=全员，避免存量应用被误隐藏

---
**规划定稿，确认后开工。**
