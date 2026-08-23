# 任务清单 — 通用能力执行器（Phase F，capability.call 真实执行）

**状态：✅ 已实施（2026-08-21，与「能力中心：注册/管理」合并会话）**
**依据**：F3 遗留（capability 节点只认 demo.echo ≈ 通用执行器未做）+ tech-debt #14 配套 + `2026-07-22-capability-four-types-design.md`
**相关**：`connector.py`（capability.call）/ `capability.registry` / `ontology.capability_query`
**日期**：2026-08-21

## 目标

1. **能力真实执行**：flow 的 capability 节点不再只认 `demo.echo`——按**能力的执行声明**分派到真实执行后端
2. **执行声明模型**：`business_capabilities.execution` JSONB（`{"adapter": "<adapter名>", ...参数}`）——一个能力注册时声明"怎么跑"
3. **分派**：`Connector._execute_capability_call` 读能力 execution → 分派到对应后端；无声明/未知 adapter → 明确报错（回退 demo.echo 兼容，供纯 demo 图）
4. 保留权限门禁（PolicyLayer 403 + capability.call ConnectorError）+ 审计
5. 零回归：cap-demo-echo（无 execution）继续按 demo.echo 执行

## 现状（已核实，2026-08-21）

- `Connector._execute_capability_call`（connector.py:248）：注册表校验（存在 + active）→ 权限门禁 → 按 `f"{domain}.{name}"` **猜 adapter**——只认 `_FLOW_ADAPTER_TYPES`（demo.echo / llm.prompt / knowledge.search / chat.history / qu.answer / tool.fetch），其余报「无执行 adapter（Phase F 通用执行器）」
- **猜 adapter 的缺陷**：业务能力（如 `cap-plan-alarm` domain=equipment name=query_equipment_alarm → "equipment.query_equipment_alarm"）命中不了任何 adapter——用 domain.name 猜测不是可靠的能力→执行映射
- 已有可复用执行后端：`Connector` 6 个对话/取数 adapter + `ontology.capability_query.execute_capability_query`（ontology 事实聚合，需 StructuredQuery）+ `demo.echo`
- `business_capabilities` 现无 execution 列（「能力中心：注册/管理」任务书 D1 将新增；本任务书可选先以 seed/DB 直插声明，或等该任务书）
- 能力节点输入形状：`capability_call {adapter_type, capability_id, input}`，capability 参数在 `input`
- 基线：383 tests 全绿

## 决策点（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 执行声明模型 | `execution JSONB = {"adapter": "<adapter_key>", "params": {...}}`；adapter_key ∈ 白名单（**adapter 中点名**：`demo.echo` / `llm.prompt` / `knowledge.search` / `chat.history` / `qu.answer` / `tool.fetch`）——能力注册时选，比 domain.name 猜测可靠 |
| D2 | capability.call 分派 | 执行序：读 `capacity.execution` → 有则按 adapter 白名单分派（`await self.execute({**call, "adapter_type": execution.adapter}, ctx)`，input 仍用能力 input）；无 execution → 回退 `f"{domain}.{name}"` 猜测（兼容 demo.echo / 现有 seed 能力）；仍不中 → 明确报错「能力 X 无执行声明/未知 adapter」 |
| D3 | 输入映射 | 能力 `input`（capability 参数）原样传给 adapter 的 input；execution.params 提供 adapter 固定默认（如 tool.fetch 的 connector_id 可由能力声明带，也可被 capability input 覆盖） |
| D4 | 不做的执行后端 | **一期不做**：ontology StructuredQuery 聚合（execute_capability_query 需要 StructuredQuery，而能力节点输入是普通 dict——那是 QU/规划层的执行，非能力节点模型）；MCP adapter（未实现）；自定义脚本/插件执行（Plugin SDK，后续方仓储） |
| D5 | 错误语义 | 未知 adapter / 无声明 → ConnectorError「capability X 无执行 adapter（执行声明缺失或未实现）」→ flow 执行失败提示；deprecated 能力 → 「已停用」（能力中心任务书 D3 soft-disable 衔接） |
| D6 | 权限/审计 | 保持现状：PolicyLayer 403 + capability.call 权限门禁（required_permissions ⊆ 角色）+ earp.capability.call.* 审计——本任务书只改「执行分派」，不改门禁 |
| D7 | 默认演示能力 | seed 的 cap-demo-echo 补 `execution: {"adapter": "demo.echo"}`（显式声明），或靠 D2 无声明回退 demo.echo 也行——倾向显式声明更清晰，但兼容回退保留 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4）

### Task 1 — 执行声明解析 + capability.call 分派（0.5-1 天）
**文件**：`src/earp_server/connector.py`
- `_execute_capability_call` 重构：查能力时同时取 `execution` 列 → 分派逻辑（D2）
- 新增小工具：读 `execution.adapter` + 白名单校验 + params 合并（D3）
- 兼容：无 execution → 回退 domain.name 猜测（现有行为）；cap-demo-echo 继续 demo.echo
- 验证：假设能力带 execution → 正确分派；不带 → 回退；未知 → 明确报错

### Task 2 — 测试（0.5-1 天）
**文件**：`tests/test_flow_f3_nodes.py`（扩展 capability 用例）、`tests/test_capability_admin.py`（如已建，加 execution 分派）
- 构造带 `execution: {adapter: "llm.prompt"}` 的能力 → capability 节点 → 真实走 llm.prompt（FakeLLM 断言）
- 带 `execution: {adapter: "tool.fetch", connector_id}` → 走 tool.fetch（mock fetch）
- 无 execution → demo.echo（兼容）
- 未知 adapter → ConnectorError「无执行 adapter」
- deprecated 能力 → 「已停用」（若能力中心任务书已做）
- 回归：cap-demo-echo flow 执行 + 权限门禁 + 审计不变

### Task 3 — 冒烟 + 文档（0.5 天）
- dev 真 API：注册一个带 `execution: {adapter:"tool.fetch"}` 的能力 → flow 里能力节点真实取数；带 llm.prompt 的能力 → 真实生成
- FDE 指南 §15 补：能力注册时选「执行方式」（adapter）；「注册 ≠ 自动可执行，需配执行声明」
- session-record 补记 + F3 遗留「通用执行器」标 ✅

## 依赖关系

```
Task 1（分派）→ Task 2（测试）→ Task 3（冒烟/文档）
可选前置：「能力中心：注册/管理」新增 execution 列；否则本任务书先以 seed/DB 直插声明 + server 端容忍列缺失
```

**建议执行序**：`1 → 2 → 3`

## 验收标准

1. flow 能力节点能真实执行**多种 adapter**（llm.prompt / tool.fetch / demo.echo…），不再只 demo.echo
2. 能力注册的 `execution` 声明被 capability.call 正确消费（分派到对应后端）
3. 无声明/未知 adapter → 明确错误；cap-demo-echo 兼容回退；权限门禁 + 审计不变
4. 全量 pytest 零回归 + dev 冒烟（带 execution 能力真实跑通）

## 风险提示

1. **execution 字段依赖**：若「能力中心」任务书未先做（无列），本任务书需先在 server 容忍 execution 列缺失（`SELECT ... execution` 用 `COALESCE` 或加列的最小迁移）——建议两任务书并行时统一 schema
2. **adapter 白名单即「能力能调什么」**：映射到 Connector 对话/取数 adapter 意味着能力是这些 adapter 的**命名封装**——不要在能力里引入 adapter 之外的新执行逻辑（避免重复；ontology 聚合走 QU/规划层）
3. **params 合并优先级**：能力 execution.params（默认）< capability input（调用方覆写）——文档写清，避免歧义
4. **错误语义**：无声明 ≠ 能力坏了——是"没配执行方式"，报错要可操作（提示去能力中心配 execution）

---
**规划定稿，确认后独立新会话开工。**
