# 设计稿（草案）— Chat 会话上下文 + 会话可见范围（QU 二期前置）

**状态：讨论稿，待评审**
**依据**：`arch/design/query-understanding-query-plan-design-v0.3.md` §5.2（context 维度）+ chat 一期实现 + QU Phase F 方向
**日期**：2026-08-18

## 1. 现状（已核实）

| 项 | 现状 |
|----|------|
| 对话容器 | `conversations`（conversation_id/tenant_id/user_id/title/created_at，0014 加 chat_app_id） |
| 消息 | `messages`（seq/role/content/citations） |
| 多轮上下文 | `_recent_pairs` 按 (user,assistant) 配对取最近 `context_turns`（默认 6，可配 1-20）注入 LLM |
| 指代消解 | **仅靠 LLM 的多轮历史盲猜**——QU 的 structured context（§5.2：last_entities/last_intent/references）未接入 chat 链路 |
| 会话生命周期 | 无（无最后活跃/归档/状态） |
| 会话可见范围 | 无角色级可见性（仅 tenant+user 隔离）；chat_apps 发布评审+可见范围为二期 |

## 2. 会话上下文（QU §5.2 → chat 落地）

### 2.1 目标
每轮 chat 结束时，把本轮的**结构化理解结果**（StructuredQuery 的实体/意图）写回会话上下文；下一轮理解时注入做**规则层指代消解**（提及 → 上文实体映射），比 LLM 盲猜准、可溯源、不耗 token。

### 2.2 数据模型
```jsonc
// conversations.context（JSONB，0014 后追加列或独立表）
{
  "last_entities": [{"mention": "CNC-01", "entity_id": "ent-cnc01", "semantic_type": "equipment"}],
  "last_intent": "RELATION",
  "last_relations": [{"subject": "CNC-01", "relation": "manufactured_by"}],
  "updated_at": "2026-08-18T10:00:00Z"
}
```
- 追加列 `conversations.context JSONB DEFAULT '{}'`（migration 0022 之后新编号）
- 只存**上一轮**（last-*），不存全量历史——QU §5.2 语义即「最近一轮已解析实体」

### 2.3 读写时机（chat 软路由路径）
- **写**：chat_sse 走 execute_plan 路径时，PlanResult 含 StructuredQuery → 每轮结束后 upsert `conversations.context`（kb_scope 限定路径一期不写，无结构化结果）
- **读**：`understand()` 的 `context` 参数（既有签名）→ chat 传 `{"conversation_id", "last_entities", "last_intent"}` → 理解层规则：提及「它/这个/该设备」等指代词 → 映射 last_entities 的 entity_id（含 semantic_type 回填）
- **降级**：context 缺失/指代无法解析 → 维持现状（LLM 历史兜底）；不破坏单轮问答

### 2.4 验收
- dev 实测多轮：问「CNC-01 供应商」→ 追问「它的更换周期呢」→ 指代解析到 CNC-01（trace 可见 references 映射，非 LLM 盲猜）
- 规则层指代解析命中率 ≥80%（评估集可并入 understanding_eval 的 ctx 用例）
- 单轮/无 context 场景零回归

## 3. 会话元数据 + 可见范围

### 3.1 会话元数据（chat 二期前置，小）
- `conversations` 加：`last_active_at`（每轮更新）、`message_count`（或 count 查询）、`status`（active/archived，一期可只加前两个）
- title 自动生成：首问截断前 N 字（无 LLM 调用）

### 3.2 会话可见范围（分级）
| 级 | 语义 | 落地 |
|----|------|------|
| 1. 用户归属 | 用户只看自己的对话（现状已有：user_id 隔离） | 无改动 |
| 2. 应用可见 | chat_app 发布后，哪些角色可见该应用+其对话 | chat_apps 二期：`visible_roles`（空=全员）/发布状态；GET /chat_apps 按角色过滤 |
| 3. 会话级共享 | 同租户其他角色查看对话（运营/审计） | **一期不做**——无明确 use case；审计已由 earp.audit 事件覆盖（消息内容不入审计） |

- 边界：conversations 查询统一走 chat_app 可见性过滤（应用不可见 → 其对话不可见），避免「应用隐藏但对话可枚举」的缝隙

## 4. 与 QU Phase F / Dify Chatflow 的关系（方向参考）

- 一期/二期 Plan 层（select_plan 固定策略）= Dify **Chat**（线性简化编排器）位置
- Phase F 通用 DAG = Dify **Chatflow**（节点化对话工作流）方向——见会话记录 Dify 对比分析
- 会话上下文是两者的共同底座：Chatflow 的「会话状态」节点可读写 conversations.context

## 5. 落点（Task 拆解草案，QU 二期排期）

| Task | 内容 | 依赖 |
|------|------|------|
| C1 | migration：conversations.context + last_active_at + title 自动生成 | — |
| C2 | chat_sse 写 context（execute_plan 路径）+ 会话元数据更新 | C1 |
| C3 | understand() 规则层指代消解（context 注入 + 提及映射 + trace） | C2 |
| C4 | 评估：understanding_eval ctx 用例扩展 + 指代命中率门槛 | C3 |
| C5 | chat_apps 可见范围（visible_roles + 发布后按角色过滤 GET） | — |
| C6 | 前端：chat-edit 发布面板（可见角色选择）+ 对话列表按角色过滤 | C5 |

## 6. 开放问题

1. context 只存「上一轮」够不够？多轮连续指代（A→B→C 逐轮指代）需要「最近 K 轮实体」——倾向先 last-*（QU §5.2 语义），Phase F 需要时升级为会话记忆（类似 Dify Memory 节点）
2. kb_scope 限定路径（chat 一期不走 planner）要不要也写 context？——kb_scope 无结构化结果，倾向不写（保持理解层单源）
3. 可见范围「应用级」是否需要角色而非固定名单？（roles 体系已有——倾向 `visible_roles` 存 role_id 列表，空=全员）

---
**评审后并入 QU 二期任务书。**
