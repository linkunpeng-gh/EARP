# LangChain → EARP 对照分析

## 目标

对 LangChain 框架本体（langchain-core / langchain / langchain-text-splitters）做代码级分析，识别 EARP 服务端可复用的接口设计、横切机制与数据模型，并用 LangGraph 本地源码修正既有概念级结论。

**勘察对象（本地实码）：**
- `langchain_core 0.3.86` / `langchain 0.3.30` / `langchain_text_splitters 0.3.11`（PyPI wheel 解包于 /tmp/lc/）
- LangGraph master 快照：`~/code/langchain/langgraph-main/`（libs/checkpoint-postgres 等，DDL 修正见 langgraph-earp-mapping.md v1.1）

**License**: 全线 MIT — 概念、接口、代码均可自由参考与引用。

---

# 一、组件映射总表

| LangChain 模块 | EARP 对应 | 映射度 | 参考方式 |
|:---------------|:----------|:-----:|:---------|
| `core/callbacks`（19 个事件钩子） | Audit/Observation 拦截器 + EventBus 事件注册表 | **85%** | 钩子清单对照，查漏 EARP 事件类型 |
| `core/runnables`（invoke/stream/batch + with_retry/with_fallbacks） | Step/Capability 统一调用协议 + 重试/降级 | **80%** | 模式参考（EARP SDK 已有自己的协议） |
| `core/tools.BaseTool`（args_schema/ToolException） | Capability 契约（Pydantic→JSONSchema） | **90%** | 互证——EARP Capability SDK 已同构 |
| `core/language_models.BaseChatModel` | M3 LLM Provider 抽象层 | **85%** | 接口设计直接参考 |
| `langchain.chat_models.init_chat_model` | LLM provider 路由 + LLM Key 管理 | **75%** | 模式参考 |
| `core/indexing`（RecordManager + index API） | **M4 KB 增量索引去重**（此前分析空白点） | **90%** | 算法直接复用 |
| `langchain-text-splitters` | M4 Document→Chunk 分块 | **95%** | **可直接引为依赖**（MIT，33KB，无重依赖） |
| `core/rate_limiters.InMemoryRateLimiter` | Policy rate_limit 进程内实现 | **70%** | 令牌桶参数模型参考 |
| LangGraph Platform 资源模型（sdk-py schema.py） | Runtime 服务端 API 资源命名 | **85%** | Assistant/Thread/Run ↔ Agent/Session/Execution 互证 |
| `langchain.chains` / `langchain.agents`（legacy） | — | **0%** | 官方已弃用转向 LangGraph，不参考 |

---

# 二、逐模块深度分析

## 2.1 Callbacks 事件钩子体系 → EARP 审计/观测拦截清单

`langchain_core/callbacks/base.py` 定义的完整钩子（实测 19 个）：

```
on_llm_start / on_llm_new_token / on_llm_end / on_llm_error
on_chat_model_start
on_chain_start / on_chain_end / on_chain_error
on_tool_start / on_tool_end / on_tool_error
on_retriever_start / on_retriever_end / on_retriever_error
on_agent_action / on_agent_finish
on_retry / on_text / on_custom_event
```

**对 EARP 的价值——用作事件类型完备性检查表：**

| LangChain 钩子 | EARP EventBus 事件（v1.1 注册表） | 状态 |
|:---------------|:----------------------------------|:----:|
| on_llm_start/end/error | LLM 调用事件（Audit Spec §LLM） | ✅ 已有 |
| on_tool_start/end/error | CAPABILITY_CALL 系列 | ✅ 已有 |
| on_chain_start/end/error | EXECUTION_STARTED/COMPLETED/FAILED | ✅ 已有 |
| on_retriever_start/end/error | KNOWLEDGE_RETRIEVAL | ⚠️ 仅一条——**建议 M4 补 RETRIEVAL_FAILED**（检索失败可观测） |
| on_llm_new_token | 流式 token 事件 | ⚠️ M6 WebSocket 推送需要，EventBus 注册表暂无——**M6 PRD 补** |
| on_retry | 重试事件 | ⚠️ 建议 M5 补 STEP_RETRIED（重试可观测是 Temporal 结论的配套） |
| on_custom_event | 插件自定义事件 | ⚠️ M7 Plugin 事件通道设计时评估 |

**结论**：LangChain 用"每资源三事件（start/end/error）+ 流式 token + 重试"覆盖全链路。EARP 事件注册表按此模式查漏，M4/M5/M6 各补 1-2 个事件类型即可对齐。

## 2.2 Runnable 协议与 with_retry/with_fallbacks

`runnables/base.py`：所有可执行单元实现统一协议 `invoke/ainvoke/stream/astream/batch/abatch`，横切能力通过包装器叠加：

```python
runnable.with_retry(retry_if_exception_type=(ValueError,),
                    wait_exponential_jitter=True,   # tenacity 实现
                    stop_after_attempt=2)
        .with_fallbacks([alt_runnable], exception_key="error")
        .with_config(tags=..., metadata=...)
```

**对 EARP 的价值：**
1. **重试实现直接用 tenacity**（`RunnableRetry` 内部即 tenacity 的 `retry_if_exception_type + wait_exponential_jitter + stop_after_attempt`）——EARP 服务端 Step 重试不必手写退避逻辑，`ConnectorRetryConfig` 字段可 1:1 映射到 tenacity 参数。M0 依赖清单加 `tenacity`（MIT）。
2. **fallback 携带失败上下文**（`exception_key` 把上游异常注入 fallback 输入）——EARP Capability `fallback_capability_id`（Closed-loop 深化已加规范）的实现语义参考：fallback 收到原始错误而非裸输入。
3. **stream/batch 与 invoke 同协议**——EARP Orchestrator 的 Step Runner 接口应同样一次定义三形态（同步结果/流式事件/批量），避免 M6 流式改造时重构接口。

## 2.3 BaseTool ↔ Capability 契约互证

`tools/base.py`：`BaseTool(name, description, args_schema: Type[BaseModel], return_direct, handle_tool_error)` + `ToolException`。

- EARP Capability SDK 已同构（Pydantic → JSONSchema 自动推导），**互证通过，无需变更**。
- 增量收获：`handle_tool_error` 支持 bool/str/callable 三态（吞错返回预设消息 vs 抛出）——EARP Capability 执行器对"业务性失败不该炸掉整个 Plan"的场景可采纳同款可配置错误策略（M5 Orchestrator 错误分类的补充）。
- `SchemaAnnotationError`（args_schema 类型注解错误在类定义期即报错）——注册期快速失败模式，EARP Capability Registry 注册校验已有等价物（manifest 验证）。

## 2.4 BaseChatModel → M3 LLM Provider 抽象层设计模板

`language_models/chat_models.py` 实测要点：

| 机制 | 实现 | EARP M3 采纳 |
|:-----|:-----|:-------------|
| `rate_limiter: BaseRateLimiter` 字段 | 调用前 `acquire(blocking=True)`（同步/异步双路径，L516/L607） | LLM Connector 内置限流挂点；EARP 用 Redis 令牌桶实现同一接口（对齐部署架构 §2.3 LLM 并发控制：每实例并发 10） |
| `cache` + `_generate_with_cache` | 请求级缓存（L1040） | LLM 响应缓存挂点预留（Phase 2 开启） |
| `bind_tools(tools)` | 把工具 schema 绑定进请求 | Planner 的 Capability 候选注入方式 |
| `with_structured_output(schema)` | 强制结构化输出（Pydantic） | **Planner 产出 Execution Plan 的关键机制**——Plan JSON 用 schema 约束 + 校验失败即 ERR-PL-VALIDATION-001 |
| `disable_streaming: bool \| "tool_calling"` | 工具调用时可单独关流式 | M6 流式推送的边界处理参考 |
| `init_chat_model(model, model_provider, configurable_fields)`（langchain 包） | 字符串路由到 provider 实现 | LLM Key 管理（Phase 2 深化已有）+ provider 注册表的初始化入口形态 |

**结论**：EARP 的 LLM 调用层（M3）不引 LangChain 依赖，但 BaseChatModel 的**挂点清单**（限流/缓存/工具绑定/结构化输出/流式开关）就是 EARP `LLMConnector` 接口的字段清单——直接照此设计，避免 M3 之后逐个补挂点。

## 2.5 indexing API → M4 KB 增量索引（既有分析的空白点）⭐

`core/indexing/api.py` 的 `index()` 是文档增量入库的完整方案：

```python
index(docs_source, record_manager, vector_store,
      batch_size=100,
      cleanup="incremental" | "full" | "scoped_full" | None,
      source_id_key="source")   # 文档源标识（str | callable）
```

机制：`RecordManager` 记录每个 chunk 的 `(key=内容hash, group_id=source_id, updated_at)`；重复内容跳过（去重），`cleanup=incremental` 删除同 source 下已消失的旧 chunk，`full` 清理整库孤儿。

**对 EARP M4 的价值：**
- Knowledge Base Spec v1.0 定义了 Document→Chunk 模型，但**未定义"文档更新时旧 Chunk 如何清理"**——RecordManager 的三种 cleanup 语义是现成答案。
- 落地：EARP 不引依赖，在 documents/chunks 表上加 `content_hash` + `source_updated_at` 列（M0 DDL 顺手加），M4 索引任务（Celery worker）实现同款 hash 去重 + incremental 清理。
- **建议**：M4 PRD 的 AC 增加"重复内容不重复嵌入（省 embedding 费用）+ 文档删除后 chunk 不残留（防幽灵检索）"两条——正是 RecordManager 解决的两个生产问题。

## 2.6 text-splitters → M4 分块（建议直接引为依赖）

`langchain_text_splitters 0.3.11`：33KB wheel、仅依赖 langchain-core，含 `RecursiveCharacterTextSplitter`（递归分隔符降级：段→句→词）、`MarkdownHeaderTextSplitter`（按标题层级保留结构元数据）、token 分块（tiktoken）、代码语言感知分块（python/js 等）。

| 选项 | 评估 |
|:-----|:-----|
| A. 直接依赖 langchain-text-splitters | MIT、体积小、算法生产验证充分；引入 langchain-core 传递依赖（~450KB，纯 Python） |
| B. 自研 Recursive 分块 | 核心算法 ~100 行可控，但 Markdown 结构分块 + token 精确分块的边界情况多 |

**建议 A**——这是 LangChain 生态中少数"工具级、无框架绑定"的包，符合"对接而非 fork"原则。M4 PRD 定稿。

## 2.7 InMemoryRateLimiter → Policy rate_limit 参数模型

`rate_limiters.py`：令牌桶三参数 `requests_per_second / check_every_n_seconds / max_bucket_size`（突发上限）。EARP Policy Center 的 rate_limit 策略（M2，Redis 实现）沿用同一参数模型，语义与 LangChain/业界一致，避免自造术语。

## 2.8 LangGraph Platform 资源模型 → EARP API 命名互证

`sdk-py/langgraph_sdk/schema.py` 实测资源：`Assistant / AssistantVersion / Thread / ThreadState / ThreadTask / Run / Checkpoint / Cron`。

| LangGraph Platform | EARP | 互证结论 |
|:-------------------|:-----|:---------|
| Assistant（图 + 配置的命名版本） | Agent 定义（Agent Spec） | EARP Agent 注册应含版本（AssistantVersion 模式） |
| Thread / ThreadState | Session / Execution Context | 一致 |
| Run（一次执行，挂在 Thread 下） | Execution（挂在 Session 下） | 一致——`POST /v1/sessions/{id}/...` 层级与业界同构 |
| Cron | Schedule 域定时触发 | 一致（M5） |

**结论**：EARP 的 REST 资源层级（runtime-py SDK 已锁定）与 LangGraph Platform 服务端同构，API 形态无需调整——这是对既有契约的第三方印证。

---

# 三、不可复用部分

| LangChain 特性 | 不可复用原因 |
|:---------------|:------------|
| `langchain.chains` / `langchain.agents`（legacy AgentExecutor） | 官方已弃用转向 LangGraph；EARP 编排走自己的 Orchestrator |
| `core/pydantic_v1` 兼容层 | 历史包袱，EARP 纯 Pydantic v2 |
| LCEL 管道语法（`prompt | model | parser`） | DSL 语法糖，EARP 的 Plan 是数据（DAG JSON）非代码组合 |
| `hub`（提示词云端拉取） | EARP Prompt Lib 归 Knowledge Center，企业内管理 |
| `memory`（legacy 会话记忆） | EARP Conversation 域 + Concept Model v2.0 Memory 对象自有定义 |
| Runnable 全家桶作为运行时依赖 | EARP SDK/服务端已有统一调用协议；引入会造成双协议混乱 |

---

# 四、依赖引入决策表（服务端 M0 定稿）

| 包 | 决策 | 理由 |
|:---|:----:|:-----|
| `tenacity` | **引入** | RunnableRetry 的底层；EARP Step/Connector 重试直接用（MIT，零传递依赖） |
| `langchain-text-splitters` | **建议引入**（M4 PRD 确认） | §2.6 评估 A 优于 B |
| `langchain-core` | 不引入（除非 text-splitters 传递） | 只取接口设计模式 |
| `langchain` / `langgraph` | 不引入 | 模式参考；LangGraph 引擎化引入按 langgraph-earp-mapping §4.4 在 M5 后重评估 |

---

# 五、实施建议（映射到服务端里程碑）

| 里程碑 | 采纳内容 | 出处 |
|:------:|:---------|:-----|
| M0 | 依赖清单：tenacity；DDL：chunks 表加 content_hash / source_updated_at | §2.2 / §2.5 |
| M2 | rate_limit 策略参数模型（rps / 检查间隔 / 突发桶） | §2.7 |
| M3 | LLMConnector 接口挂点清单（限流/缓存/bind_tools/structured_output/流式开关）；Plan 产出用 with_structured_output 模式约束 | §2.4 |
| M4 | RecordManager 式增量索引（hash 去重 + incremental 清理）；text-splitters 依赖决策；补 RETRIEVAL_FAILED 事件 | §2.5 / §2.6 / §2.1 |
| M5 | handle_tool_error 三态错误策略；补 STEP_RETRIED 事件 | §2.3 / §2.1 |
| M6 | 流式 token 事件类型；disable_streaming 边界 | §2.1 / §2.4 |

---

# 六、License 说明

langchain-core / langchain / langchain-text-splitters / langgraph 全线 **MIT**——接口、模式、算法可自由参考，依赖可直接引入。相比 Dify（限制性 License，只能学不能碰）约束宽松得多；EARP 实现处仍建议注释标注参考来源以便溯源。
