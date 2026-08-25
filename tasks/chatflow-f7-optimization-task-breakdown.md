# 任务清单 — Chatflow F7 优化: 评估问题高优 1-3（QU 缓存 / 失败归一 / 指定答案节点）

**状态：规划定稿，待开工**
**依据**：`docs/chatflow-f6-evaluation-report.md` §8 问题清单高优 1-3（F6 评估产出）
**依赖**：F0-F6 ✅（评估已完成，问题已定位）
**日期**：2026-08-24

## 目标

F6 评估发现的三个**高优先级**问题，修复后消除「评估明确点名的高优短板」：

1. **QU 升级路径接 LLM 缓存**（#1）：消除同 query 重复全量 LLM 调用 + 冷启动 8s
2. **flow 节点失败语义与错误归一**（#2）：`ConnectorFetchError` 归一到 `ConnectorError`，失败语义统一（flow 前端可正确区分「流程失败」vs「请求失败」）
3. **「指定答案节点」**（#3）：告别「答案 = 最后一个执行节点输出」的隐性语义，支持显式指定答案来源（多分支/副作用节点不再覆盖答复）

## 现状（已核实，2026-08-24）

- **#1 QU 缓存**：`understanding.upgrade_with_llm` 调用 `LLMConnector.json_complete`——该路径**不查 `self._cache`**（代码核实：仅 `plan()` 查缓存，`json_complete`/`complete`/`chat_stream` 都不查）；且 `upgrade_with_llm` 每次 new 一个无 cache 的 LLMConnector。实测：规则 QU ~60ms；LLM 升级冷启动 ~8s、热 ~70ms（同 query 两次仍 ~70ms 无缓存收益）
- **#2 失败归一**：`data_adapter.ConnectorFetchError` 独立于 `connector.ConnectorError`；`_execute_tool_fetch`/`_execute_capability_call` 抛 ConnectorFetchError **不包成 ConnectorError**；`chat_ep` 的 422 捕获名单 `(ConnectorError, ChatError, WorkflowValidationError)` 不含它——当前靠 StepRunner `except Exception` 兜底成 status=failed（200），但错误类型语义不统一、无法精确分类
- **#3 答案节点**：`flow_chat` 答案 = `completed[-1].output`（最后完成的节点）；场景 B 已用「LLM 放最后」规避（副作用节点放最后会覆盖答复）
- 基线：431 tests（3 个 openapi 失败系既有 copilot 问题，非本任务范围）

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | QU 缓存键 | `upgrade_with_llm` 复用 LLMConnector 缓存：键 = model + QU 升级 prompt（含 query/missing/relation_candidates/context）——**在 connector 统一加 cache**，而非只给 upgrade 加；或 `json_complete` 本身支持 cache（一次改，plan/suggest/upgrade 全受益） |
| D2 | 缓存失效/时效 | 复用 `EARP_LLM_CACHE_TTL`；同 query 同 missing 命中；升级结果带 `llm_upgraded` 标记，不影响非缓存路径 |
| D3 | 失败归一 | `ConnectorFetchError` 继承或包装进 `ConnectorError`（统一 `earp-server` 连接异常）；`chat_ep` 422 名单统一收口——**前端仍能拿到结构化错误，不再 fallthrough 500** |
| D4 | 失败呈现 | 保留 `200 + status=failed` 语义（合理，前端区分「流程失败」），但 error 字段带**一致性分类**（如 `connection/unknown_capability/permission/validation`），便于前端精确提示 |
| D5 | 指定答案节点 | flow_schema 顶层加 `answer_from: "<node_id>"`（可选）；缺省回落「最后完成节点」保兼容；画布/JSON 均可配；前端展示用 answer_from 节点输出 |
| D6 | 兼容 | 所有改动默认值保持现状行为（不加 answer_from = 原语义；连接异常分类不变更既有 200/skip 行为） |
| D7 | 测试策略 | 各问题单元 + 集成 + verify_f6 78 绿回归；不新增评估维度外的功能 |

## Task 拆解（建议执行序 1 → 2 → 3）

### Task 1 — QU 升级路径 LLM 缓存（0.5-1 天）
**文件**：`src/earp_server/connector.py`（json_complete/upgrade_with_llm 缓存）、`src/earp_server/ontology/understanding.py`、`tests/test_understanding.py`/`tests/test_connector_service.py`
- `json_complete` 接 `self._cache`（读 + 写，键 = model + messages 序列化）；`upgrade_with_llm` 复用带缓存的 LLMConnector
- 评估：同 query 两次升级调用，第二次命中缓存（显著变快）——补 F6 报告「无缓存」结论的修复验证
- 验证：缓存单测（命中/未命中/TTL）+ 耗时断言；规则路径零回归

### Task 2 — 失败语义归一 + 分类（0.5-1 天）
**文件**：`src/earp_server/ontology/data_adapter.py`、`src/earp_server/connector.py`、`src/earp_server/main.py`（chat_ep 名单）、`tests/test_flow_f3_nodes.py`
- `ConnectorFetchError` 归一到 `ConnectorError`（继承 或 包装）；`capability.call`/`tool.fetch` 连接类错误统一分类
- `chat_ep` 422 名单收口（含归一后的错误），不再 fallthrough 500
- error 字段带分类码（connection/unknown_capability/permission/validation）
- 验证：连接失败 → 422 且分类正确；query 能力 403 仍 403（零回归）；场景 A/B 仍走 flow 前端可读错误

### Task 3 — 指定答案节点（0.5-1 天）
**文件**：`src/earp_server/orchestrator/workflow_dsl.py`（schema 校验允许 answer_from）、`src/earp_server/conversation/chat_service.py`（flow_chat 读 answer_from）、`apps/earp-admin/...`（画布「答案节点」配置，可选）、`tests/test_flow_executor.py`
- flow_schema 顶层 `answer_from`（可选，String）；compile 校验其为已存在节点；flow_chat 用它取 answer（output.text 优先，否则 JSON 摘要）
- 缺省回落「最后完成节点」（保兼容）
- 验证：多分支/副作用节点置后 + answer_from 指向 LLM → 答案正确展示；缺省回归

## 依赖关系

```
Task 1 / Task 2 / Task 3 相对独立，可并行；统一收尾回归
```

## 验收标准

1. QU 同 query 两次升级第二次命中缓存（耗时显著下降）；规则路径零回归
2. 连接类失败不再 fallthrough 500，422 统一 + 错误分类码；query 403 / flow 语义零回归
3. flow 可用 `answer_from` 显式指定答案节点（多分支/副作用不覆盖）；缺省兼容
4. 全量 pytest 绿 + ruff/pyright 零新增 + verify_f6 78 绿

## 风险提示

1. **缓存误命中**：QU 升级 prompt 含 relation_candidates/context——键要精确（query+missing+上下文哈希），避免不同问题互相污染
2. **失败归一影响面**：ConnectorFetchError 被多处 catch（StepRunner/invoke）——归一后确保不改变既有 200+failed 语义，只统一分类
3. **answer_from 兼容**：存量 flow_schema 无该字段 → 回落原语义，避免存量应用答案变化
4. **改 connector 缓存**：`plan()` 已有缓存逻辑——统一时避免双重缓存/键冲突

---
**规划定稿，确认后开工。**
