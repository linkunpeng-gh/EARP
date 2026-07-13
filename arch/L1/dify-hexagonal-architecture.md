# Dify 六边形架构目录结构设计

> 基于 Dify 核心领域概念，按六边形架构 (Ports & Adapters) 组织。
> **核心原则**：Domain 层不 import 任何框架代码（Flask/SQLAlchemy/Redis），所有外部依赖通过 Port 接口 + Adapter 实现倒置。

```
api/
│
├── domain/                              # ═══ 领域核心层 ═══
│   │                                     # 纯 Python 代码，零框架依赖
│   │                                     # 只能引用 ports/ 中的接口
│   │
│   ├── common/                          # 领域公共基类
│   │   ├── entity.py                    #   BaseEntity (含 ID, created_at, updated_at)
│   │   ├── aggregate.py                 #   BaseAggregate
│   │   ├── domain_event.py              #   领域事件基类
│   │   └── exceptions.py                #   领域异常 (AppNotFoundError, 等)
│   │
│   ├── app/                             # ── 应用管理子域 ──
│   │   ├── entity.py                    #   App, AppConfig, AppModelConfig
│   │   ├── value_objects.py             #   AppMode(chat/completion/workflow/agent/…), AppStatus
│   │   ├── service.py                   #   领域服务: 应用运行引擎、App 生命周期
│   │   ├── events.py                    #   领域事件: AppCreated, AppDeleted, AppPublished
│   │   └── generator/                   #   应用生成器 (按 AppMode 区分)
│   │       ├── base_generator.py        #     抽象基类
│   │       ├── chat_generator.py
│   │       ├── completion_generator.py
│   │       ├── workflow_generator.py
│   │       └── agent_generator.py
│   │
│   ├── conversation/                    # ── 对话/消息子域 ──
│   │   ├── entity.py                    #   Conversation, Message, MessageFile
│   │   ├── value_objects.py             #   MessageRole(system/user/assistant/tool), MessageStatus
│   │   └── service.py                   #   对话管理、消息流式输出编排
│   │
│   ├── workflow/                        # ── 工作流子域 ──
│   │   ├── entity.py                    #   Workflow, WorkflowNode, WorkflowRun, WorkflowNodeExecution
│   │   ├── value_objects.py             #   NodeType, WorkflowStatus, NodeStatus
│   │   ├── engine/                      #   图执行引擎 (继承 Dify 的 graphon 设计)
│   │   │   ├── graph.py                 #     图数据结构 (DAG)
│   │   │   ├── executor.py              #     拓扑排序 + 并行执行器
│   │   │   ├── variable_pool.py         #     变量池 (命名空间管理)
│   │   │   ├── node_runner.py           #     节点运行器抽象
│   │   │   └── layers/                  #     横切关注点层
│   │   │       ├── base_layer.py
│   │   │       ├── execution_limits_layer.py
│   │   │       ├── logging_layer.py
│   │   │       └── observability_layer.py
│   │   ├── nodes/                       #   工作流节点定义
│   │   │   ├── __init__.py              #     NodeFactory (节点注册与创建)
│   │   │   ├── llm_node.py
│   │   │   ├── code_node.py
│   │   │   ├── http_request_node.py
│   │   │   ├── knowledge_retrieval_node.py
│   │   │   ├── agent_node.py
│   │   │   ├── human_input_node.py
│   │   │   ├── condition_node.py
│   │   │   ├── template_transform_node.py
│   │   │   ├── loop_node.py
│   │   │   └── trigger_webhook_node.py
│   │   └── service.py                   #   工作流领域服务
│   │
│   ├── agent/                           # ── Agent 子域 ──
│   │   ├── entity.py                    #   Agent, AgentConfig, AgentRun
│   │   ├── runner/                      #   Agent 执行策略
│   │   │   ├── base_runner.py           #     抽象基类
│   │   │   ├── react_runner.py          #     ReAct 模式
│   │   │   ├── function_call_runner.py  #     Function Calling 模式
│   │   │   ├── planning_runner.py       #     Plan-and-Execute 模式
│   │   │   └── multi_agent_runner.py    #     多 Agent 协作
│   │   ├── strategy/                    #   Agent 策略插件
│   │   │   ├── base.py
│   │   │   └── plugin_adapter.py
│   │   └── prompt/                      #   Agent Prompt 模板
│   │
│   ├── rag/                             # ── RAG/知识库子域 ──
│   │   ├── dataset/                     #   数据集实体
│   │   │   ├── entity.py                #     Dataset, Document, Segment, ChildChunk
│   │   │   └── value_objects.py         #     DocumentStatus, IndexStatus
│   │   ├── indexing/                    #   索引链路
│   │   │   ├── pipeline.py              #     索引流水线编排
│   │   │   ├── extractor/              #     文档解析器
│   │   │   │   ├── base.py
│   │   │   │   ├── pdf_extractor.py
│   │   │   │   ├── html_extractor.py
│   │   │   │   ├── markdown_extractor.py
│   │   │   │   ├── docx_extractor.py
│   │   │   │   ├── csv_extractor.py
│   │   │   │   └── notion_extractor.py
│   │   │   ├── splitter/               #     文本分割器
│   │   │   │   ├── base.py
│   │   │   │   ├── fixed_splitter.py
│   │   │   │   └── recursive_splitter.py
│   │   │   └── cleaner/                #     文本清洗
│   │   ├── retrieval/                   #   检索策略
│   │   │   ├── __init__.py
│   │   │   ├── vector_retrieval.py
│   │   │   ├── keyword_retrieval.py
│   │   │   ├── hybrid_retrieval.py
│   │   │   └── rerank.py
│   │   └── service.py                   #   RAG 领域服务
│   │
│   ├── tool/                            # ── 工具子域 ──
│   │   ├── entity.py                    #   Tool(ABC), ToolProvider, ToolCall, ToolFile
│   │   ├── engine.py                    #   工具执行引擎
│   │   ├── builtin/                     #   内置工具
│   │   │   ├── web_scraper.py
│   │   │   ├── calculator.py
│   │   │   ├── current_time.py
│   │   │   └── image_generator.py
│   │   └── provider_controller.py      #   工具提供者控制器抽象
│   │
│   └── llm/                             # ── LLM 调用子域 ──
│       ├── entity.py                    #   ModelConfig, ModelInstance, LLMUsage
│       ├── service.py                   #   LLM 调用编排 (重试、fallback、负载均衡)
│       ├── prompt/                      #   Prompt 处理
│       │   ├── template.py
│       │   ├── transform.py
│       │   └── schema.py
│       ├── moderation/                  #   内容审核
│       │   ├── base.py
│       │   └── service.py
│       └── memory/                      #   对话记忆
│           ├── base.py
│           ├── window_memory.py
│           └── summary_memory.py
│
├── ports/                               # ═══ 端口接口层 ═══
│   │                                     # 由 Domain 层定义，由 Adapters 层实现
│   │                                     # 全部为抽象基类 (ABC)
│   │
│   ├── repositories/                    # ── 仓储端口 ──
│   │   ├── __init__.py
│   │   ├── app_repository.py            #   AppRepository(ABC)
│   │   ├── conversation_repository.py
│   │   ├── message_repository.py
│   │   ├── workflow_repository.py
│   │   ├── workflow_run_repository.py
│   │   ├── dataset_repository.py
│   │   ├── document_repository.py
│   │   ├── segment_repository.py
│   │   ├── account_repository.py
│   │   ├── tenant_repository.py
│   │   ├── tool_provider_repository.py
│   │   ├── provider_config_repository.py
│   │   └── file_repository.py
│   │
│   ├── llm_provider.py                  #   LLMProviderPort(ABC)
│   ├── embedding_provider.py            #   EmbeddingProviderPort(ABC)
│   ├── rerank_provider.py               #   RerankProviderPort(ABC)
│   ├── vector_store.py                  #   VectorStorePort(ABC)
│   ├── storage.py                       #   StoragePort(ABC)
│   ├── speech_to_text_provider.py       #   Speech2TextProviderPort(ABC)
│   ├── text_to_speech_provider.py       #   TTSProviderPort(ABC)
│   ├── moderation_provider.py           #   ModerationProviderPort(ABC)
│   ├── event_bus.py                     #   EventBusPort(ABC)
│   ├── cache.py                         #   CachePort(ABC)
│   ├── search_engine.py                 #   SearchEnginePort(ABC)
│   ├── document_parser.py               #   DocumentParserPort(ABC)
│   ├── id_generator.py                  #   IdGeneratorPort(ABC)
│   └── file_storage.py                  #   FileStoragePort(ABC)
│
├── application/                         # ═══ 应用层 (用例) ═══
│   │                                     # 业务编排、事务管理、工作单元
│   │                                     # 调用 Domain + 通过 Port 访问外部资源
│   │
│   ├── common/                          # 通用支撑
│   │   ├── unit_of_work.py              #   工作单元 (UoW)
│   │   ├── pagination.py                #   分页 DTO
│   │   └── dto.py                       #   通用 DTO 基类
│   │
│   ├── app/                             # ── 应用管理用例 ──
│   │   ├── create_app_use_case.py
│   │   ├── update_app_use_case.py
│   │   ├── delete_app_use_case.py
│   │   ├── get_app_use_case.py
│   │   ├── list_apps_use_case.py
│   │   ├── publish_app_use_case.py
│   │   └── copy_app_use_case.py
│   │
│   ├── conversation/                    # ── 对话用例 ──
│   │   ├── create_conversation_use_case.py
│   │   ├── send_message_use_case.py     #   ★ 核心：发送消息并获取回复
│   │   ├── get_conversations_use_case.py
│   │   ├── get_messages_use_case.py
│   │   ├── delete_conversation_use_case.py
│   │   ├── stop_generating_use_case.py
│   │   └── dto.py                       #   对话相关 DTO
│   │
│   ├── workflow/                        # ── 工作流用例 ──
│   │   ├── create_workflow_use_case.py
│   │   ├── update_workflow_use_case.py
│   │   ├── run_workflow_use_case.py
│   │   ├── stop_workflow_use_case.py
│   │   ├── get_workflow_run_use_case.py
│   │   └── get_node_logs_use_case.py
│   │
│   ├── dataset/                         # ── 数据集用例 ──
│   │   ├── create_dataset_use_case.py
│   │   ├── update_dataset_use_case.py
│   │   ├── delete_dataset_use_case.py
│   │   ├── upload_document_use_case.py
│   │   ├── index_document_use_case.py   #   触发索引流程
│   │   ├── retrieve_from_dataset_use_case.py
│   │   └── get_dataset_stats_use_case.py
│   │
│   ├── agent/                           # ── Agent 用例 ──
│   │   ├── run_agent_use_case.py
│   │   └── get_agent_traces_use_case.py
│   │
│   ├── tool/                            # ── 工具用例 ──
│   │   ├── list_tools_use_case.py
│   │   ├── get_tool_schema_use_case.py
│   │   ├── configure_tool_provider_use_case.py
│   │   └── execute_tool_use_case.py
│   │
│   ├── model/                           # ── 模型配置用例 ──
│   │   ├── list_providers_use_case.py
│   │   ├── list_models_use_case.py
│   │   ├── configure_provider_use_case.py
│   │   └── get_model_instance_use_case.py
│   │
│   ├── file/                            # ── 文件用例 ──
│   │   ├── upload_file_use_case.py
│   │   ├── get_file_use_case.py
│   │   └── delete_file_use_case.py
│   │
│   ├── account/                         # ── 账户用例 ──
│   │   ├── register_account_use_case.py
│   │   ├── login_use_case.py
│   │   ├── update_profile_use_case.py
│   │   └── manage_tenant_use_case.py
│   │
│   └── events/                          # ── 事件处理 ──
│       ├── event_handler_register.py    #   事件处理器注册
│       ├── handle_app_deleted.py
│       ├── handle_dataset_deleted.py
│       └── handle_message_created.py
│
├── interfaces/                          # ═══ 入站适配器 ═══
│   │                                     # 驱动侧：接收外部请求并转为用例调用
│   │
│   ├── rest/                            # ── REST API ──
│   │   ├── __init__.py
│   │   ├── middleware/                  #   HTTP 中间件
│   │   │   ├── auth.py                  #     认证
│   │   │   ├── rate_limit.py            #     限流
│   │   │   ├── request_id.py            #     请求追踪 ID
│   │   │   ├── error_handler.py         #     全局异常处理
│   │   │   └── cors.py
│   │   ├── console/                     #   管理后台 API
│   │   │   ├── __init__.py
│   │   │   ├── app_controller.py
│   │   │   ├── dataset_controller.py
│   │   │   ├── workflow_controller.py
│   │   │   ├── agent_controller.py
│   │   │   ├── tool_controller.py
│   │   │   ├── model_controller.py
│   │   │   ├── account_controller.py
│   │   │   └── file_controller.py
│   │   ├── web_app/                     #   终端用户 API
│   │   │   ├── __init__.py
│   │   │   ├── chat_controller.py
│   │   │   ├── completion_controller.py
│   │   │   └── workflow_controller.py
│   │   ├── service_api/                 #   第三方集成 API
│   │   │   ├── __init__.py
│   │   │   └── chat_controller.py
│   │   ├── openapi/                     #   开发者 OpenAPI
│   │   │   ├── __init__.py
│   │   │   └── app_controller.py
│   │   ├── files/                       #   文件上传/预览
│   │   │   ├── __init__.py
│   │   │   └── file_controller.py
│   │   ├── mcp/                         #   MCP 协议端点
│   │   │   ├── __init__.py
│   │   │   └── mcp_server.py
│   │   └── common/                      #   通用装饰器/异常
│   │       ├── decorators.py
│   │       └── errors.py
│   │
│   ├── websocket/                       # ── WebSocket ──
│   │   ├── __init__.py
│   │   ├── handlers.py                  #   SocketIO 事件处理
│   │   └── streaming.py                 #   流式输出管理
│   │
│   └── cli/                             # ── CLI 命令 ──
│       ├── __init__.py
│       ├── migrate_command.py
│       ├── seed_command.py
│       └── manage_command.py
│
├── adapters/                            # ═══ 出站适配器 ═══
│   │                                     # 被驱动侧：实现 Ports 接口
│   │
│   ├── repositories/                    # ── 仓储实现 ──
│   │   ├── __init__.py
│   │   ├── base.py                      #   BaseSQLRepository (SQLAlchemy 通用 CRUD)
│   │   ├── app_repository_impl.py
│   │   ├── conversation_repository_impl.py
│   │   ├── message_repository_impl.py
│   │   ├── workflow_repository_impl.py
│   │   ├── workflow_run_repository_impl.py
│   │   ├── dataset_repository_impl.py
│   │   ├── document_repository_impl.py
│   │   ├── segment_repository_impl.py
│   │   ├── account_repository_impl.py
│   │   ├── tenant_repository_impl.py
│   │   ├── provider_config_repository_impl.py
│   │   └── file_repository_impl.py
│   │
│   ├── providers/                       # ── LLM/模型提供商适配 ──
│   │   ├── __init__.py
│   │   ├── base.py                      #   基础 Provider 实现
│   │   ├── openai/                      #   OpenAI 全家桶
│   │   │   ├── __init__.py
│   │   │   ├── llm.py                  #     GPT-4o, o1, o3 等
│   │   │   ├── embedding.py            #     text-embedding-3-*
│   │   │   ├── moderation.py
│   │   │   ├── speech_to_text.py
│   │   │   └── text_to_speech.py
│   │   ├── anthropic/                   #   Anthropic Claude
│   │   │   ├── __init__.py
│   │   │   ├── llm.py
│   │   │   └── (embedding 等)
│   │   ├── azure_openai/                #   Azure OpenAI
│   │   ├── google_ai/                   #   Gemini
│   │   ├── aws_bedrock/
│   │   ├── local/                       #   本地模型
│   │   │   └── ollama_adapter.py        #     Ollama
│   │   └── plugin/                      #   插件模型提供商
│   │       └── plugin_adapter.py
│   │
│   ├── vector_stores/                   # ── 向量数据库适配 ──
│   │   ├── __init__.py
│   │   ├── base.py                      #   BaseVectorStoreAdapter
│   │   ├── pgvector.py
│   │   ├── qdrant.py
│   │   ├── milvus.py
│   │   ├── weaviate.py
│   │   ├── pinecone.py
│   │   ├── chroma.py
│   │   └── elasticsearch_vector.py
│   │
│   ├── storage/                         # ── 对象存储适配 ──
│   │   ├── __init__.py
│   │   ├── base.py                      #   BaseStorageAdapter
│   │   ├── local_storage.py
│   │   ├── s3_storage.py
│   │   ├── azure_blob_storage.py
│   │   ├── oss_storage.py               #   阿里云 OSS
│   │   └── cos_storage.py               #   腾讯云 COS
│   │
│   ├── cache/                           # ── 缓存适配 ──
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── redis_cache.py
│   │   └── memory_cache.py
│   │
│   ├── event_bus/                       # ── 事件总线适配 ──
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── redis_event_bus.py           #   Redis Streams 实现
│   │   ├── rabbitmq_event_bus.py
│   │   └── in_memory_event_bus.py       #   测试用
│   │
│   ├── search/                          # ── 搜索引擎适配 ──
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── elasticsearch_adapter.py
│   │
│   ├── document_parsers/                # ── 文档解析适配 ──
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── unstructured_adapter.py     #   Unstructured.io API
│   │   └── local_parser_adapter.py
│   │
│   └── speech/                          # ── 语音服务适配 ──
│       ├── __init__.py
│       ├── azure_speech_adapter.py
│       └── openai_speech_adapter.py
│
├── bootstrap/                           # ═══ 启动配置 ═══
│   ├── __init__.py
│   ├── container.py                     #   DI 容器 (依赖注入配置)
│   ├── app_factory.py                   #   应用工厂: create_app()
│   ├── config.py                        #   全局配置 (pydantic-settings)
│   └── extensions/                      #   框架扩展初始化
│       ├── __init__.py
│       ├── ext_database.py              #     SQLAlchemy init
│       ├── ext_redis.py                 #     Redis init
│       ├── ext_celery.py                #     异步任务 init
│       ├── ext_socketio.py              #     WebSocket init
│       ├── ext_sentry.py                #     错误监控 init
│       └── ext_otel.py                  #     OpenTelemetry init
│
├── models/                              # ═══ ORM 数据映射 ═══
│   │                                     # 纯数据映射，不含业务逻辑
│   │                                     # 只被 adapters/repositories/ 引用
│   │
│   ├── __init__.py                      # 轻量导出，避免循环引用
│   ├── base.py                          # Base ORM Model
│   ├── app.py                           # App, AppModelConfig, Site
│   ├── conversation.py                  # Conversation, Message, MessageFeedback
│   ├── workflow.py                      # Workflow, WorkflowNode, WorkflowRun
│   ├── dataset.py                       # Dataset, Document, Segment, ChildChunk
│   ├── account.py                       # Account, Tenant, TenantAccountJoin
│   ├── provider.py                      # Provider, ProviderModel, TenantDefaultModel
│   ├── tool.py                          # ToolProvider, ToolConversation
│   ├── file.py                          # UploadFile
│   ├── plugin.py                        # Plugin, PluginConfig
│   ├── api_token.py                     # ApiToken
│   └── tag.py                           # Tag
│
├── tasks/                               # ═══ 后台任务 (Celery) ═══
│   ├── __init__.py
│   ├── base_task.py                     #   任务基类
│   ├── document_indexing_task.py        #   文档索引入口
│   ├── document_cleanup_task.py         #   文档清理
│   ├── dataset_deletion_task.py
│   ├── email_notification_task.py
│   └── scheduled_tasks.py               #   定时任务调度
│
├── migrations/                          # ═══ 数据库迁移 ═══
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       ├── 001_initial_schema.py
│       └── ...
│
├── shared/                              # ═══ 共享工具 ═══
│   ├── __init__.py
│   ├── utils.py                         #   通用工具函数
│   ├── encryption.py                    #   加密/解密
│   ├── serialization.py                 #   序列化
│   └── logger.py                        #   日志配置
│
├── app.py                               # 应用入口
├── pyproject.toml                       # 项目配置与依赖
├── Dockerfile                           # Docker 构建文件
└── .env.example                         # 环境变量示例
```

---

## 依赖规则速查

| 层级 | 可以引用 | 不可以引用 |
|------|----------|-----------|
| `interfaces/*` | `application/*`, `ports/*` | `domain/*`（间接通过 application） |
| `application/*` | `domain/*`, `ports/*` | `models/*`（ORM）, Flask/SQLAlchemy/Redis |
| `domain/*` | `ports/*`（接口）, Python 标准库 | Flask/SQLAlchemy/Redis, `models/*` |
| `ports/*` | ABC（标准库） | 任何框架 |
| `adapters/*` | `ports/*`, `models/*` | `domain/*`（实现 Port 接口） |
| `models/*` | SQLAlchemy | 业务逻辑 |

---

## 核心数据流

### 一次对话请求的完整链路

```
HTTP POST /chat-messages
       │
       ▼
interfaces/rest/web_app/chat_controller.py    ← 解析请求、认证
       │
       ▼
application/conversation/send_message_use_case.py  ← 业务编排
       │
       ├─▶ domain/conversation/service.py          ← 对话领域逻辑
       ├─▶ domain/app/generator/chat_generator.py  ← 应用生成
       ├─▶ domain/llm/service.py                   ← LLM 调用编排
       │       │
       │       ▼
       │   ports/llm_provider.py                   ← Port 接口
       │       │
       │       ▼
       │   adapters/providers/openai/llm.py        ← Adapter 实现
       │
       ├─▶ ports/repositories/message_repository.py
       │       │
       │       ▼
       │   adapters/repositories/message_repository_impl.py
       │
       └─▶ ports/event_bus.py
               │
               ▼
           adapters/event_bus/redis_event_bus.py
               │
               ▼
           (异步事件处理)
```

### 文档索引流程

```
upload_document_use_case.py
       │
       ├─▶ domain/rag/dataset/service.py       ← 创建 Document/Segment 记录
       ├─▶ ports/storage.py                    ← 存原始文件
       │       └─▶ adapters/storage/s3_storage.py
       │
       ├─▶ tasks/document_indexing_task.py     ← (Celery 异步)
       │       ├─▶ domain/rag/indexing/pipeline.py
       │       │       ├─▶ extractor/ → ports/document_parser.py → adapters/document_parsers/unstructured_adapter.py
       │       │       ├─▶ splitter/
       │       │       ├─▶ cleaner/
       │       │       └─▶ ports/embedding_provider.py → adapters/providers/openai/embedding.py
       │       ├─▶ ports/vector_store.py
       │       │       └─▶ adapters/vector_stores/pgvector.py
       │       └─▶ ports/repositories/segment_repository.py
```

---

## 模块间的关系图

```
                              ┌──────────────────┐
                              │   Domain Core     │
                              │                   │
                              │  app / workflow   │
                              │  agent / rag      │
                              │  tool / llm       │
                              │  conversation     │
                              └────────┬──────────┘
                                       │ 定义接口契约
                                       ▼
                              ┌──────────────────┐
                              │     Ports         │
                              │  (ABC interfaces) │
                              │                   │
                              │  *Repository      │
                              │  *Provider        │
                              │  *Store / *Bus    │
                              └────────┬──────────┘
                     ┌─────────────────┼──────────────────┐
                     ▼                 ▼                   ▼
            ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐
            │ Application  │  │   Adapters       │  │   Frontend   │
            │  (UseCases)  │  │  (Impls)         │  │  (Next.js)   │
            │              │  │                  │  │              │
            │  编排          │  │  providers/     │  │  REST API    │
            │  事务          │  │  repositories/  │  │  WebSocket   │
            │  事件派发      │  │  vector_stores/ │  └──────────────┘
            └──────────────┘  │  storage/        │
                              └──────────────────┘
```

---

## 建议的演进路径

### Phase 1：MVP（1-3 个月）

- 保留 Dify 的 Controller → Service → Core 分层，**不重构现有逻辑**
- 仅新增：`ports/` 目录下的接口定义（先定义不实现）
- Service 层按子域拆分（`dataset_service.py` 拆成 5 个文件）
- 新模块优先使用 Repository 模式

### Phase 2：成熟期（3-6 个月）

- Core 中的 Infrastructure 依赖逐步替换为 Port 调用
- 引入依赖注入（手动 DI 或 `dependency-injector`）
- 事件系统升级为消息队列（Redis Streams）
- 全面 Repository 化

### Phase 3：规模化（6-12 个月）

- 模块按限界上下文独立部署（如需拆微服务）
- 仅对审计要求高的模块（如 Billing）引入 Event Sourcing
- 前端同步适配模块化 API
