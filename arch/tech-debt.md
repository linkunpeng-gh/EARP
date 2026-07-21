# EARP 技术债务追踪

> 2026-07-21，基于 M0-M7 回顾 + Phase 2→M15 全部交付后的盘点。
> 所有债务均标注严重度、影响范围、建议处理时机。

---

## 活跃债务

| # | 位置 | 内容 | 严重度 | 触发条件 |
|:--|:---|:---|:---|:---|
| 1 | `step_runner.py:77` | `batch()` NotImplementedError → M5 用 for-loop 替代，接口未删除 | P3 | 真正的并行批量执行需求出现时 |
| 2 | `checkpoint.py` | checkpoint_writes 表已建 DDL 但无写入逻辑；durability 多档 (sync/async/exit) 仅有 async 实现 | P3 | 需要跨进程 checkpoint 恢复或严格持久性保证时 |
| 3 | `invoke.py:7` | 多事务孤儿 execution 定期 recovery — `DELETE FROM executions WHERE status='pending' AND created_at < NOW() - INTERVAL '1h'` 未实现 | P3 | 生产环境出现 pending 超时 execution 堆积时 |
| 4 | DDL | 6 张 M7+ 预留表 UNUSED：`api_keys`, `service_accounts`, `encrypted_credentials`, `connector_configs`, `capability_calls`, `connector_bindings` | P3 | 对应功能需求触发时按需启用 |
| 5 | `connector.py` | `_bind_tools: bool = False` → Phase 3 动态注入 Capability 候选到 LLM tool calling | P3 | LLM tool calling 需求出现时 |
| 6 | SDK 版本 | `libs/` 与 `earp-sdk-*` 双份 SDK 副本存在，版本号不一致 (0.1.0.dev0 vs 0.1.0) | P3 | SDK 正式发布打包时清理 |

## 已清偿

| # | 原始位置 | 内容 | 清偿于 |
|:--|:---|:---|:---|
| 1 | `embedding_service.py:14` | 伪随机 1536d → 真实模型 | Phase 2 (bge-m3 1024d) |
| 2 | `connector.py:70-73` | cache/bind_tools/structured_output/stream 四挂点 | Phase 2 (cache + structured_output) + M8 (stream) |
| 3 | `connector.py:93` | plan_structured() placeholder | Phase 2 (plan() 已实现) |
| 4 | `step_runner.py:74` | stream() NotImplementedError | M8 (SSE streaming endpoint + StepRunner.stream) |
| 5 | Websocket JWT 鉴权 | P2-1 全链路评审发现 | M6 P2 修复 (e49f404) |
