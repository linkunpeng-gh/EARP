# 任务清单 — Chatflow F4: Human Approval 节点（挂起/恢复/超时）

**状态：规划定稿，待开工**
**依据**：`arch/design/2026-08-18-chatflow-integration-design.md` §3（Human Approval 节点「人工把关，企业场景关键」）/ §7（F4）/ 开放问题 2（恢复语义：SSE 长连接 vs 轮询）
**依赖**：F0/F1/F2 ✅ + F3 ✅（qu/capability/tool 节点——human_approval 常在 capability 之后「开单→人工确认」）
**日期**：2026-08-20

## 目标

1. **human_approval 节点**：flow 执行到该节点 → **挂起**（不阻塞会话、不失败）→ 等待人工答复 → **恢复**继续执行下游
2. **执行状态持久化**：flow 从「同步跑完即弃」升级为「可挂起/恢复」（pool 序列化落库）——这是 F4 的核心前置
3. **超时治理**：等待人工答复超时 → 明确终态（timeout），不产生僵尸挂起
4. 零回归：F0-F3 全部用例锁；auto 模式 SSE 零改动

## 现状（已核实，2026-08-20）

- `flow_chat`（chat_service:422）**同步非流式**：compile → executor.execute（内存 pool）→ 结果落库 messages → 返回 JSON；`exec_id` 随机 uuid **不落库**——无任何执行状态持久化
- F0 `_execute_plan` 的 pool 是内存 dict（node_id → StepResult）；F2 `flow_input` 模板替换
- `compile_flow_schema` 对 human_approval 报「节点类型未实现（F4）」
- chat 会话机制：conversation + messages（add_message/create_conversation）现成；`_recent_pairs` 历史配对
- 端点：`POST /chat_apps/{id}/chat`（flow 分支非流式 JSON）；`GET /chat_apps/{id}` 拿 flow_schema
- 基线：347 tests 全绿

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 持久化模型 | **migration 0026 `flow_runs` 表**：`execution_id PK / tenant_id / chat_app_id / conversation_id / status CHECK(pending_running\|waiting_human\|completed\|failed\|timeout\|cancelled) / pending_node_id（当前等待的 human_approval 节点）/ node_state JSONB（pool 序列化：node_id→StepResult output）+ flow_input JSONB / attempts INT / created_at / updated_at / finished_at` + RLS 三件套 + 显式 GRANT（对齐 0014 先例） |
| D2 | 挂起语义 | 执行到 human_approval：**暂停执行**（executor 支持「yield 挂起点」——human_approval 适配器抛专用 `ApprovalPending(node_id, question)`，执行器捕获后返回「待恢复」状态）→ pool 序列化落 flow_runs(status=waiting_human, pending_node_id) → assistant 消息落库（「⏸ 等待确认：{question}」）→ 响应 202 `{execution_id, status: waiting_human, pending_node_id, question}` |
| D3 | 恢复语义 | **用户下一轮消息恢复**（复用 conversation，无需独立端点）：`POST /chat` 同 conversation_id 且存在 waiting_human run → 反序列化 pool → 注入答复（`{{#approval.reply#}}` 或节点 data 的 `reply_var`）→ 从挂起节点继续执行 → 完成/再次挂起。多等待点（一个 flow 多个 human_approval）→ 按 pending_node_id 顺序逐个恢复 |
| D4 | 超时 | `waiting_human` 超时：`EARP_APPROVAL_TTL`（默认 3600s）——超时扫描落 scheduler（enrichment 同进程）或恢复时惰性检查（倾向：恢复时惰性检查 + scheduler 定期扫描双保险，仿 T1 心跳模式）；超时 → status=timeout + 消息落库「⏰ 等待超时，流程终止」 |
| D5 | 取消 | `POST /chat_apps/{id}/chat` 无取消端点一期——超时即终态；cancel 语义留 Phase F（与 eval cancel 不同源） |
| D6 | 并发/幂等 | 同 conversation 的 waiting_human run 唯一（再次 chat 且 pending → 409 或恢复？倾向：**无 pending 且无 waiting_human → 新建 run；有 waiting_human → 视为恢复输入**——即「用户下一句即答复」）；不同 conversation 无冲突 |
| D7 | 测试策略 | 纯函数层（pool 序列化/反序列化往返）+ 执行器层（挂起抛错/恢复继续）+ 端点集成（挂起 202 → 恢复 → 完成；超时惰性检查；多挂起点顺序恢复）；回归 F0-F3 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — migration 0026 flow_runs + pool 序列化（0.5-1 天）
**文件**：`migrations/versions/0026_flow_runs.py`（新）、`src/earp_server/orchestrator/workflow_dsl.py`（pool 序列化辅助）
- flow_runs 表（D1）+ RLS + GRANT
- pool 序列化/反序列化纯函数：`serialize_pool(pool) / deserialize_pool(json)`（StepResult output 可 JSON——F2 已证明 output 是 dict；node_state 只存 output 不存函数/句柄）
- 验证：往返单测 + test_migrations EXPECTED_TABLES 更新 + test_rls 更新

### Task 2 — 执行器挂起点（0.5-1 天）
**文件**：`src/earp_server/orchestrator/multi_step.py`、`src/earp_server/ontology/...`（如需）
- `ApprovalPending(Exception)`：`{node_id, question}`——human_approval 适配器抛；`MultiStepExecutor.execute` 捕获 → 返回挂起状态（`state.status = waiting_human` + 已执行结果 + 挂起信息）
- executor 支持 `resume(pool_restored, pending_node_id, reply)`：从挂起节点继续（跳过已完成）
- 验证：执行器单测（挂起/恢复/多挂起点）

### Task 3 — human_approval 适配器 + flow_chat 改造（0.5-1 天）
**文件**：`src/earp_server/connector.py`、`src/earp_server/conversation/chat_service.py`、`src/earp_server/ontology/routes.py`
- `human.approval` 适配器：data `{question: 模板表达式, reply_var?: "{{#approval.reply#}}"}` → 抛 ApprovalPending（question 渲染后）；恢复时 `reply` 注入 pool 供下游引用
- `flow_chat`：compile 后查 waiting_human run（同 conversation）→ 有则恢复、无则新建；挂起 → 202 响应 + assistant 消息；完成/超时路径落库
- 端点：`POST /chat` 响应 status 含 waiting_human；前端（F5a）后续消费 202
- 验证：端点集成（挂起 202 → 第二轮恢复 → 完成；超时惰性检查）

### Task 4 — 超时扫描 + 单测（0.5 天）
**文件**：`src/earp_server/entrypoints/scheduler.py`、`src/earp_server/ontology/flow_runs.py`（如需）、`tests/test_flow_approval.py`（新）
- `expire_waiting_approvals(engine, ttl)`：逐租户扫描 waiting_human + updated_at 超时 → timeout + 消息落库；scheduler 循环接入（仿 enrichment）
- 单测：pool 往返 / 挂起-恢复 / 多挂起点 / 超时 / 并发（waiting_human 唯一）

### Task 5 — 质量门 + dev 冒烟 + 收尾（0.5 天）
- 全量 pytest + import-linter + OpenAPI 基线同步（chat 端点响应加 waiting_human 状态）+ ruff/pyright 零新增
- dev 真 API：flow 图 `start→llm→human_approval→llm→end` 全链路（挂起 → 答复 → 完成）；超时验证（改 TTL 短值）
- FDE 指南补 human_approval 说明；session-record 补记 + F4 标 ✅

## 依赖关系

```
Task 1（migration+序列化）→ Task 2（执行器挂起）→ Task 3（适配器+端点）→ Task 4（超时+测试）→ Task 5（收尾）
Task 1 与 F3 可并行（不同表/模块）
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`（依赖 F3 完成，Task 1 可与 F3 并行）

## 验收标准

1. flow 含 human_approval → 执行到挂起点返回 202（waiting_human + question + pending_node_id）
2. 同 conversation 下一轮消息 → 恢复执行至完成（答复经 `{{#approval.reply#}}` 供下游）
3. 多挂起点按序恢复；超时 → timeout 终态（无僵尸挂起）
4. pool 序列化往返无损；同 conversation 无重复挂起
5. auto 模式 SSE 零改动；全量 pytest 绿 + import-linter + OpenAPI 基线同步 + ruff/pyright 零新增

## 风险提示

1. **执行模型变更面**：F2 的同步执行 → 挂起/恢复是 executor 级改动（`ApprovalPending` + resume）——必须保持 F0-F3 全部用例绿（无 human_approval 的图行为不变）
2. **pool 序列化边界**：StepResult 只存 output（dict）——若未来节点 output 含非 JSON（如文件句柄）需排除；一期约束 output 必须 JSON 可序列化（编译期校验或运行时断言）
3. **恢复的输入来源**：用户下一句即答复 vs 独立 resume 端点——D3 选「复用 conversation」省端点，但语义上「用户下一句必须是答复」——若用户答非所问则按答复对待（FDE 指南注明）
4. **超时双保险**：恢复时惰性检查 + scheduler 扫描——scheduler 进程未跑时惰性检查兜底
5. **多挂起点的会话体验**：连续两个 human_approval 需两轮用户输入——每轮恢复后再次挂起（202）——前端 F5a 需处理「再次等待」状态

---
**规划定稿，确认后开工（依赖 F3 完成）。**
