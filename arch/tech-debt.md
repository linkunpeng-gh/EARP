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
| 10 | `ontology/search.py::knowledge_search` | 三层文本证据 RRF 是合法 recall 层，但缺「角色层」：capability 结构化行无法进 RRF，答案 vs 引用未分层——QU 设计 v0.3 §8.1；Phase D3 叠加角色层（§9.2），不替换 RRF | P3 | Phase D3（QU 设计 §16） |
| 11 | `ontology/abox_service.py`（compile_profile/get_entity_profile）+ `ontology/search.py:103` | **profile 无过期管理**：① 写时失效未实现——`add_fact`/`revoke_fact`/`upsert_entity` 无重编译钩子；② 惰性编译只兜「缺失」不兜「过期」——`knowledge_search` 先查表、有就返回，已存在（哪怕过期）的 profile 会一直读到旧缓存，`get_entity_profile` 无 freshness 校验；③ 夜间 enrichment（ontology 设计 §4.3）未实现——scheduler 进程 idle；④ `entity_timeline` 全库无 INSERT——`stats.recent_events` 恒 0。影响：QU v0.3 recall 层 profile lane 会给出过期事实 | P2 | 事实变更后 profile 提供旧事实 / QU Phase D 角色层依赖 profile lane 时。修复：写时失效（facts 变更→重编译该实体 profile）+ 读时 freshness 校验 + enrichment 落 scheduler |

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
