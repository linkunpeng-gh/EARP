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
| 9 | ~~角色域权限管理~~ | ✅ 已清偿（2026-08-18）：roles.is_admin 读侧通用机制（admin 跳过域过滤）+ roles 页开放配置（CRUD/DD 多选/admin 开关）+ TBox 审批人角色门禁（tbox.approve） | ~~P2~~ | ~~多角色/多域接入或新建 DD 后路由权限失效时~~ |
| 10 | `ontology/search.py::knowledge_search` | 三层文本证据 RRF 是合法 recall 层，但缺「角色层」：capability 结构化行无法进 RRF，答案 vs 引用未分层——QU 设计 v0.3 §8.1；Phase D3 叠加角色层（§9.2），不替换 RRF | P3 | Phase D3（QU 设计 §16） |
| 11 | `ontology/abox_service.py`（compile_profile/get_entity_profile）+ `ontology/search.py:103` | **profile 无过期管理**：① 写时失效未实现——`add_fact`/`revoke_fact`/`upsert_entity` 无重编译钩子；② 惰性编译只兜「缺失」不兜「过期」——`knowledge_search` 先查表、有就返回，已存在（哪怕过期）的 profile 会一直读到旧缓存，`get_entity_profile` 无 freshness 校验；③ 夜间 enrichment（ontology 设计 §4.3）未实现——scheduler 进程 idle；④ `entity_timeline` 全库无 INSERT——`stats.recent_events` 恒 0。影响：QU v0.3 recall 层 profile lane 会给出过期事实 | P2 | 事实变更后 profile 提供旧事实 / QU Phase D 角色层依赖 profile lane 时。修复：写时失效（facts 变更→重编译该实体 profile）+ 读时 freshness 校验 + enrichment 落 scheduler |
| 12 | `ontology/tbox_service.py` + `pages/tbox.html` | **TBox 所有操作无审批流**（2026-08-16 定级）：类型管理页支持新增/停用自助，但**所有操作（新增/停用/未来改集合）都应走审批**——当前无 gate（无 draft→approved 状态机、无 owner/管理员校验、无变更审计事件）；改集合/ID 已在页面禁用（引用键+级联风险）。修复：审批流（draft→approved 状态机 + 变更审计事件，管理员/owner 审批后生效；含「停用后启用」的恢复路径）或至少 admin 角色门禁 | P2 | TBox 变更成为高频操作（配合实体导入/多团队协作）时，或需要修改已有类型集合/恢复停用类型时 |
| 13 | `tests/`（conftest 基建） | **测试 seed 单列主键跨租户污染**（debt #7 模式）：entities/sessions/facts/connector_configs 等单列 PK 跨租户共享，硬编码 id 的测试 seed 相互串扰（M3 实测踩 4-5 次：enrichment 测试 entity_profiles JOIN 串租户、sessions/facts PK 冲突、connector 引用 purge 顺序）。修复：conftest.py 加统一「租户隔离 seed helper」——按租户派生唯一 id + 全局 purge 按具体 id（迁移角色），新测试直接复用，不再每文件手写 | P3 | 新增测试文件时（消除 M3 类踩坑的重复成本） |
| 14 | capability 注册链路（`capability/registry.py` seed 写死 + `pages/capabilities.html` 仅 Register Demo）+ 无能力注册 API | **能力节点权限门禁的「能力侧」required_permissions 无可视化配置入口**：角色侧 roles 页能配 `roles.permissions`，但「某能力需要哪些权限」（`business_capabilities.required_permissions`）只能靠 seed 写死（如 demo.echo）或 DB 直改——FDE 无法在界面新建一个带自定义权限的能力（如 `cap-query-alarms` 设 `[alarm:read]`），权限门禁（PolicyLayer 403 / Connector.capability.call 兜底）两端清单缺了能力侧的可配性。修复：能力中心页加「新建能力 + 设 required_permissions」表单 + 后端注册 API（归属能力域，含 audit 事件） | P3 | FDE 需要新建自定义带权限能力，或能力从 demo 演进到多能力/多团队时 |
| 15 | 中台对接归属（`pages/data-source.html` 连接管理块 / `connector_configs`） | **连接管理是跨域通用底座，但现藏在「知识中心 → 结构化知识 → 中台对接」下**：① `connector_configs` 被知识侧（数据源注册/同步/virtual live/enrichment）、chatflow 侧（tool.fetch 节点取数）、规划中的能力侧（REST/DB 作 capability 执行后端）共享——是通用连接基础设施而非纯知识能力；② FDE 用 chatflow tool.fetch 时要去「知识中心→中台对接」找连接，语义错位；③ 设计路线图 `nav.js` 已预留能力中心「连接器」规划项（第三期），M3 落地时仅作为数据源注册前置设施顺手放在了中台对接页。**方向：做能力中心时把「连接管理」拆出中台对接、归能力中心连接器页（对齐规划意图）；知识中心中台对接只保留数据源注册/同步/虚拟取数（本体灌入）**。2026-08-21 会话确认：仅记录不改动，待能力中心任务书实施时一并处理 | P2 | 做能力中心（能力中心任务书 / capability 执行后端连接器页）时 |
| 16 | Chatflow 单节点调试（Dify 第三层调试能力） | **对话画布已能做整图运行 + 逐节点输入/输出/分支 trace（2026-08-21 同会话已交付 `trace` 字段 + 前端展开轨迹），缺「选中一个节点单独跑」**：Dify 支持选中节点用自定义输入（或引用前序节点输出）单独执行看该节点输入输出——对排查某节点参数/提示词尤其有用。实现需：单独端点（按节点 data 构造 capability_call + ctx，跳过图依赖校验）或前端「运行至此节点」截断执行。顺带可补：202 挂起响应带部分 trace（展示挂起到哪一步）。**記 2026-08-21：写入待办，不实施** | P3 | FDE 反馈「只想试某个节点的参数」/ 多节点图排查效率需求时 |
| 17 | Chatflow 运行历史持久化（finished run trace） | **flow_runs 目前只为 waiting_human（F4）持久化 node_state，正常跑完的 run 的 trace/results 不落库**——运行结果只看当次弹层，刷新即失，无「运行日志/历史对比」。方向：finished run 也落一份 trace（或复用 flow_runs 表加列/新增 flow_run_traces），管理侧（chatflow 应用详情或对话日志）可查历史执行轨迹。**記 2026-08-21：写入待办，不实施** | P3 | 需要回看失败/排查历史对话执行轨迹时 |

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
