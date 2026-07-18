# EARP 开源对比发现汇总

**文档编号：REF-OSS-FINDINGS**
**版本：v1.0**
**日期：2026-07-18**
**定位：开源参考分析的总入口——汇总 Dify / LangGraph / LangChain 等项目的代码级对比发现、对 EARP 服务端决策的影响、以及各详细分析文档的索引。新增开源分析后应同步更新本文档。**

---

# 一、分析文档索引

| # | 文档 | 层级 | 勘察方式 | 日期 |
|:-:|:-----|:-----|:---------|:-----|
| 1 | `opensource-analysis.md` | 8 项目全景 + 收益排序 | 资料级 | 07-17 |
| 2 | `dify-earp-mapping.md` | Dify 全栈组件映射（11 组件） | 代码级（本地库） | 07-17 |
| 3 | `langgraph-earp-mapping.md` **v1.1** | LangGraph 状态管理/Checkpoint | v1.0 概念级 → **v1.1 代码级校验** | 07-17 / 07-18 |
| 4 | `server-side-tech-reference-v1.md` | Dify v1.15 服务端工程形态 | 代码级（本地库） | 07-18 |
| 5 | `langchain-earp-mapping.md` | LangChain 框架本体（core/main/splitters） | 代码级（PyPI 源码） | 07-18 |

勘察的本地代码：
- Dify v1.15.0 — `/Users/linkunpeng/code/dify-code/dify/`
- LangGraph master — `~/code/langchain/langgraph-main/`
- langchain-core 0.3.86 / langchain 0.3.30 / langchain-text-splitters 0.3.11 — PyPI wheel 解包

---

# 二、跨项目对比总表（发现 → 采纳 → 去向）

| 发现 | 来源项目 | EARP 采纳决策 | 落点 | 详细出处 |
|:-----|:---------|:-------------|:----:|:---------|
| 生产级多租户 SaaS 用模块化单体承载（7 组 controller 一个 app） | Dify | ADR-007 单体先行获生产佐证 | D1 | tech-ref §2.1 |
| 一镜像四进程（api/websocket/worker/beat），拆进程不拆代码库 | Dify | M0 脚手架三进程角色，M6 加 websocket | M0/M6 | tech-ref §2.1 |
| 仅安全边界独立成服务（sandbox/plugin_daemon/ssrf_proxy） | Dify | Plugin Daemon/沙箱/出口代理 M7 独立 | M7 | tech-ref §2.1 |
| Flask+gevent 补丁栈是历史包袱代价（gRPC/psycopg2 都要 patch） | Dify | 反向佐证选 FastAPI 原生 async | D2 | tech-ref §2.2 |
| Celery+Beat 承载异步任务与定时调度（14 个 beat 任务） | Dify | D6 建议 Celery；Schedule 域+TTL 清理落 beat | D6/M5 | tech-ref §2.2/§2.4 |
| 图引擎产出事件流，审计/观测/配额是消费者或横切层（graphon Layers） | Dify | M1 审计=事件流消费者；Orchestrator 预留拦截器链 | M1/M2 | tech-ref §2.3 |
| ext_* 装配模式 + repositories 仓储接口层 | Dify | 服务端代码组织采纳 | M0 | tech-ref §2.2 |
| Dify 无 RLS（纯应用层租户过滤） | Dify | EARP 保留 RLS 兜底（强于 Dify） | M0 | tech-ref §2.5 |
| Checkpoint 真实 DDL 是 3 表：checkpoints/blobs/writes，大小值分离 | LangGraph | **修正 v1.0 结论**——M0 DDL 按 3 表建，防存储线性膨胀 | M0 | langgraph v1.1 §2.5 |
| checkpoint_writes.task_path 列（嵌套子图寻址） | LangGraph | 嵌套 Workflow 场景预留 | M5 | langgraph v1.1 §2.5 |
| Durability 三档 sync/async/exit | LangGraph | Command 步骤强制 sync，常规默认 async | M5 | langgraph v1.1 §2.6 |
| Pregel 循环：plan→execute→update→checkpoint，步级重试在引擎层 | LangGraph | Orchestrator 骨架 + Retry 位置印证 | M5 | langgraph v1.1 §2.6 |
| interrupt() = 异常驱动 Checkpoint+Resume | LangGraph | human_approval 暂停/恢复实现模式 | M5 | langgraph §2.4 |
| callbacks 19 钩子（资源×start/end/error + token + retry） | LangChain | 事件注册表查漏：补 RETRIEVAL_FAILED/STEP_RETRIED/流式 token | M4/M5/M6 | langchain §2.1 |
| 重试底层就是 tenacity（jitter/stop_after_attempt/if_exception_type） | LangChain | 不手写退避；tenacity 入 M0 依赖 | M0 | langchain §2.2 |
| fallback 携带失败上下文（exception_key） | LangChain | fallback_capability_id 实现语义 | M5 | langchain §2.2 |
| BaseChatModel 挂点清单（限流/缓存/bind_tools/structured_output/流式开关） | LangChain | LLMConnector 接口字段清单；Plan 用 structured_output 约束 | M3 | langchain §2.4 |
| RecordManager 增量索引（content_hash 去重 + incremental 清理） | LangChain | KB Spec 空白的现成答案；chunks 表加 hash 列 | M0/M4 | langchain §2.5 |
| text-splitters 可直接引为依赖（MIT/33KB/无框架绑定） | LangChain | M4 分块依赖（PRD 定稿） | M4 | langchain §2.6 |
| 令牌桶三参数（rps/检查间隔/突发桶） | LangChain | rate_limit 策略参数模型 | M2 | langchain §2.7 |
| Assistant/Thread/Run/Checkpoint 资源模型 | LangGraph Platform | EARP Agent/Session/Execution API 形态第三方印证 | M1 | langchain §2.8 |
| ToolException + handle_tool_error 三态错误策略 | LangChain | 业务性失败不炸 Plan 的可配置策略 | M5 | langchain §2.3 |
| Retry Policy 四参数 + Saga 补偿注册 + Heartbeat | Temporal | ConnectorRetryConfig 增强 / Command 补偿 / 长任务进度 | M5 | opensource §2.3 |
| NodeRunResult 统一结果 + RetriableError/FatalError 分类 | Dify | StepResult 统一类型 + 错误分类（v6 §8 已有错误码体系） | M1/M5 | dify §3.1 |
| Plugin install 五段流程（download→verify→unpack→register→health_check） | Dify | PluginManager 补 verify/health_check | M7 | dify §3.2 |
| vLLM 作为推理后端经 Connector 对接（不自建推理层） | vLLM | LLM 供给形态 | M3 | opensource §2.5 |
| Document/Chunk/Retriever 抽象（vector/keyword/hybrid 三检索器留扩展点） | Haystack/Dify | KB 服务分层；EARP 先 pgvector 单选 | M4 | opensource §2.6 |

---

# 三、修正记录（实码推翻既有结论的条目）

| # | 原结论（出处） | 实码事实 | 影响 |
|:-:|:---------------|:---------|:-----|
| 1 | PostgresSaver 为 2 表：checkpoints + writes（langgraph v1.0 §2.5，参照 SqliteSaver 推断） | 3 表——checkpoint_blobs 独立存大值，按 (channel,version) 版本化，同版本不重复落盘 | M0 checkpoints DDL 改 3 表；EARP earp_checkpoints 的 state 拆"小快照 JSONB + 大值引用" |
| 2 | Dify 流式输出走 SSE（早期认知） | v1.15 为独立 socketio 进程（api_websocket 服务） | M6 WebSocket Gateway 独立进程形态与业界一致（EARP 用原生 WS 不用 socketio 协议） |
| 3 | Dify workflow 引擎内嵌于 api（dify-mapping v1.0 认知） | v1.15 已抽为独立库 graphon（事件流 + Layers + command channel） | 佐证 EARP runtime 模块"无框架依赖、可单测"的边界纪律 |

---

# 四、对服务端决策项（D1-D6）的证据闭环

| 决策 | 结论 | 证据链 |
|:----:|:-----|:-------|
| D1 工程形态 | 模块化单体先行 | Dify 生产实践（tech-ref §2.1）+ v6 §9 Phase 1 允许 |
| D2 Web 框架 | FastAPI | Dify gevent 包袱反证（tech-ref §2.2）+ SDK asyncio 同源 |
| D3 目录 | apps/earp-server/ monorepo 内 | 交叉引用校验依赖 monorepo |
| D4 里程碑 | M0-M7（v1.2 已含本轮增量） | server-side-development-plan-v1.md v1.2 |
| D5 PRD 编号 | 2026-020 起 | — |
| D6 异步任务 | Celery + Beat | Dify 生产验证 + OTel instrumentation 现成（tech-ref §2.2） |

**M0 依赖清单（本轮固化）**：FastAPI / SQLAlchemy 2 async / Alembic / Celery+Beat / tenacity / langchain-text-splitters（M4 PRD 终审）/ OTel instrumentation 套件。

---

# 五、遗留可选分析（不阻塞 M0）

| 项目 | 时机 | 关注点 |
|:-----|:-----|:-------|
| LiteLLM (MIT) | M3 前 | LLM 网关：per-tenant key/预算/限流——对接 or 自研补齐 |
| Langfuse (MIT 核心) | Phase 2 | LLM trace/eval 观测 |
| Temporal 代码级细读 | M5 L3 设计时 | Saga/重试实现细节（模式级结论已够用） |

---

# 六、License 汇总

| 项目 | License | 约束 |
|:-----|:--------|:-----|
| LangChain / LangGraph / Temporal / LiteLLM | MIT | 概念、接口、代码可自由参考引用 |
| vLLM / Haystack | Apache 2.0 | 同上 |
| Dify v0.6+ | 限制性（Apache 2.0 变体） | **只学架构不抄代码**；实现处注释 `# Inspired by Dify <path>` |
| n8n | Sustainable Use License | 不可商用参考实现，仅 UI 交互模式 |
