# EARP 技术债务追踪

> 2026-07-21，基于 M0-M7 回顾 + Phase 2→M15 全部交付后的盘点。
> 所有债务均标注严重度、影响范围、建议处理时机。

---

## 活跃债务

| # | 位置 | 内容 | 严重度 | 触发条件 |
|:--|:---|:---|:---|:---|
| 1 | `step_runner.py:77` | `batch()` 废弃标注，推荐使用 MultiStepExecutor.execute() | ✅ 已清偿 | 2026-07-21 |
| 2 | `checkpoint.py` | checkpoint_writes 表已建 DDL 但无写入逻辑；durability 多档 (sync/async/exit) 仅有 async 实现 | P3 | 需要跨进程 checkpoint 恢复或严格持久性保证时 |
| 3 | `invoke.py:7` | 多事务孤儿 execution 定期 recovery — `DELETE FROM executions WHERE status='pending' AND created_at < NOW() - INTERVAL '1h'` 未实现 | P3 | 生产环境出现 pending 超时 execution 堆积时 |
| 4 | DDL | 6 张 M7+ 预留表 UNUSED | P3 | 对应功能需求触发时 |
| 5 | `connector.py` | `_bind_tools: bool = False` → Phase 3 动态注入 Capability 候选 | P3 | LLM tool calling 需求 |
| 6 | SDK 版本 | `libs/` 与 `earp-sdk-*` 双份 SDK 副本，版本号不一致 | P3 | SDK 正式发布时 |
| 7 | `business_capabilities.capability_id` 主键 | 全局唯一（不含 tenant），跨租户同名 capability 冲突（与 data_domains 同病，后者已修）——应改复合主键 (capability_id, tenant_id) | P2 | 多租户 capability 隔离需求时 |
| 8 | `knowledge_bases.indexing_technique` | high_quality/economy 仅存储未生效——检索逻辑（search_service）不读该字段，改值不改变任何行为（Dify 概念迁移残留）；应定义差异化行为（如是否建关键词索引/向量索引）或移除 | P3 | 需要按 KB 区分索引成本/策略时 |
| 9 | 角色域权限管理 | Admin 全权限非通用机制：seed 特判（建角色时查租户 DD 配全）+ 存量手动修；新建 DD 不会自动加入已有角色的 data_domain_access；roles 管理页仍 disabled。应：roles 页开放配置 + 通用「admin 角色跳过域过滤」或「新 DD 自动授权 admin」机制 | P2 | 多角色/多域接入或新建 DD 后路由权限失效时 |

## 已清偿

| # | 原始位置 | 内容 | 清偿于 |
|:--|:---|:---|:---|
| 1 | `embedding_service.py:14` | 伪随机 1536d → 真实模型 | Phase 2 (bge-m3 1024d) |
| 2 | `connector.py:70-73` | cache/bind_tools/structured_output/stream 四挂点 | Phase 2 + M8 |
| 3 | `connector.py:93` | plan_structured() placeholder | Phase 2 |
| 4 | `step_runner.py:74` | stream() NotImplementedError | M8 |
| 5 | Websocket JWT 鉴权 | P2-1 全链路评审发现 | M6 P2 修复 |
| 6 | `step_runner.py:77` | batch() 废弃标注 | 2026-07-21 |
| 7 | `infra/ext/ext_logging.py` | 凭证 key 主动日志脱敏 (CredentialMaskingFilter) | 2026-07-21 |
| 8 | `infra/db.py` + `tenant_service.py` | tenant_session() 推荐模式文档化 + 示范迁移 | 2026-07-21 |
