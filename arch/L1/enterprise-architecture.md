# 企业级 AI 运行平台 — 六边形架构设计

> 产品定位：**Enterprise AI Execution Platform（企业级 AI 运行平台）**
>
> 核心设计理念：
> 1. **业务能力优先** — Runtime 调用的是业务能力（获取库存、创建工单），不是技术接口（HTTP API）
> 2. **LLM 是能力之一** — LLM 占 20%，集成与编排占 80%
> 3. **企业 Kernel** — 所有执行经过 Kernel 的 Context/State/Permission/Policy/Audit/Trace
> 4. **天生多租户** — Tenant / Org / User / Role / ServiceAccount 从第一天开始设计

```
api/
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║                   INTERFACES（入站适配器）                    ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── interfaces/                         # ═══ 对外接口层 ═══
│   ├── rest/                           # REST API
│   │   ├── middleware/                 #    认证、限流、审计日志、CORS
│   │   ├── console/                    #    管理控制台 API
│   │   ├── portal/                     #    企业门户 API（员工自助）
│   │   ├── openapi/                    #    开发者 API（第三方集成）
│   │   ├── service_api/                #    系统间集成 API（M2M）
│   │   └── callback/                   #    回调接收（审批回调、外部通知）
│   ├── websocket/                      # 实时推送 + 流式输出
│   ├── message/                        # 消息监听（MQTT / Kafka / RabbitMQ）
│   ├── webhook/                        # Webhook 接收
│   ├── grpc/                           # gRPC（内部服务间 + Plugin Daemon）
│   └── mcp/                            # MCP (Model Context Protocol) Server
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║               APPLICATION（应用层 / 用例层）                  ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── application/                        # ═══ 用例层 ═══
│   │                                    # 业务编排、事务管理、事件发布
│   │                                    # 不直接接触 Domain 内部细节
│   │
│   ├── workspace/                      # ── 工作空间管理 ──
│   │   ├── create_workspace_use_case.py
│   │   ├── invite_member_use_case.py
│   │   ├── manage_org_unit_use_case.py
│   │   └── manage_service_account_use_case.py
│   │
│   ├── capability/                     # ── 业务能力中心 ──
│   │   ├── register_capability_use_case.py    # 注册新业务能力
│   │   ├── discover_capabilities_use_case.py  # 发现可用能力（供 LLM/Runtime 选择）
│   │   ├── configure_capability_use_case.py   # 配置能力（认证、参数、重试策略）
│   │   └── execute_capability_use_case.py     # 执行业务能力（经过 Policy Engine）
│   │
│   ├── conversation/                   # ── 对话与交互 ──
│   │   ├── send_message_use_case.py
│   │   ├── create_conversation_use_case.py
│   │   └── get_history_use_case.py
│   │
│   ├── workflow/                       # ── 业务流程管理 ──
│   │   ├── create_workflow_use_case.py
│   │   ├── update_workflow_use_case.py
│   │   ├── run_workflow_use_case.py
│   │   ├── pause_workflow_use_case.py
│   │   ├── resume_workflow_use_case.py
│   │   ├── approve_task_use_case.py
│   │   └── reject_task_use_case.py
│   │
│   ├── agent/                          # ── AI Agent ──
│   │   ├── run_agent_use_case.py
│   │   └── get_agent_trace_use_case.py
│   │
│   ├── knowledge/                      # ── 企业知识管理 ──
│   │   ├── create_knowledge_base_use_case.py
│   │   ├── index_document_use_case.py
│   │   ├── index_database_use_case.py
│   │   ├── index_api_use_case.py
│   │   ├── retrieve_use_case.py
│   │   └── query_knowledge_graph_use_case.py
│   │
│   ├── schedule/                       # ── 定时/事件调度 ──
│   │   ├── create_schedule_use_case.py
│   │   ├── create_trigger_use_case.py
│   │   └── manage_alert_use_case.py
│   │
│   ├── audit/                          # ── 审计与合规 ──
│   │   ├── query_audit_log_use_case.py
│   │   ├── export_audit_report_use_case.py
│   │   └── trace_decision_chain_use_case.py
│   │
│   ├── report/                         # ── 报表与看板 ──
│   │   ├── generate_daily_report_use_case.py
│   │   ├── get_agent_analytics_use_case.py
│   │   └── get_cost_insight_use_case.py
│   │
│   └── integration/                    # ── 集成管理 ──
│       ├── configure_adapter_use_case.py
│       ├── test_adapter_connection_use_case.py
│       └── monitor_adapter_health_use_case.py
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║               DOMAIN（领域核心层）                            ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── domain/                             # ═══ 领域核心 ═══
│   │                                    # 纯 Python，零框架依赖
│   │                                    # 企业级领域模型
│   │
│   ├── common/                         # ── 公共基类 ──
│   │   ├── entity.py                   #    BaseTenantEntity（含 tenant_id / org_id）
│   │   ├── domain_event.py             #    领域事件基类
│   │   ├── value_objects.py            #     共享值对象
│   │   ├── policies.py                 #     常用策略类型
│   │   └── exceptions.py               #     领域异常
│   │
│   ├── workspace/                      # ── 工作空间 / 多租户 ──
│   │   ├── entity.py                   #    Tenant, OrgUnit, User, Role, ServiceAccount
│   │   ├── value_objects.py            #    RoleName, Permission, ResourceType
│   │   └── service.py                  #    租户隔离、RBAC
│   │
│   ├── capability/                     # ── ★ 业务能力（核心） ──
│   │   ├── entity.py                   #    BusinessCapability, CapabilitySchema, CapabilityCall
│   │   ├── value_objects.py            #    CapabilityId, Domain(manufacturing/erp/...), CallStatus
│   │   ├── service.py                  #    能力注册、能力发现、能力编排
│   │   └── events.py                   #    CapabilityExecuted, CapabilityFailed
│   │
│   ├── conversation/                   # ── 对话 / 交互 ──
│   │   ├── entity.py                   #    Conversation, Message, MessageAttachment
│   │   ├── value_objects.py            #    MessageRole, MessageType
│   │   └── service.py
│   │
│   ├── workflow/                       # ── ★ 企业业务流程 ──
│   │   ├── entity.py                   #    EnterpriseWorkflow, BusinessNode, NodeRun
│   │   ├── value_objects.py            #    NodeType(business/agent/human/decision/approve/...)
│   │   ├── engine/                     #    流程引擎
│   │   │   ├── executor.py             #      拓扑排序 + 并行 + 暂停/恢复
│   │   │   ├── node_runner.py          #      节点运行器
│   │   │   ├── variable_pool.py
│   │   │   └── layers/                 #      横切层
│   │   │       ├── human_in_loop_layer.py    #    人工干预
│   │   │       ├── policy_enforcement_layer.py
│   │   │       └── checkpoint_layer.py
│   │   ├── nodes/                      #    企业节点类型
│   │   │   ├── business_node.py        #      调用业务能力
│   │   │   ├── agent_node.py           #      Agent 智能决策
│   │   │   ├── human_approval_node.py  #      人工审批
│   │   │   ├── decision_node.py        #      条件路由
│   │   │   ├── llm_node.py             #      LLM 辅助
│   │   │   ├── code_node.py            #      自定义脚本
│   │   │   ├── notification_node.py    #      通知（企微/钉钉/邮件/短信）
│   │   │   └── loop_node.py
│   │   └── service.py
│   │
│   ├── agent/                          # ── AI Agent ──
│   │   ├── entity.py                   #    EnterpriseAgent, AgentRun, AgentMemory
│   │   ├── runner/                     #    Agent 执行策略
│   │   │   ├── base_runner.py
│   │   │   ├── react_runner.py
│   │   │   ├── function_call_runner.py
│   │   │   ├── planning_runner.py
│   │   │   └── multi_agent_runner.py
│   │   ├── strategy/
│   │   └── prompt/
│   │
│   ├── knowledge/                      # ── ★ 企业知识 ──
│   │   ├── entity.py                   #    KnowledgeBase, Document, Chunk
│   │   ├── sources/                    #    知识源类型
│   │   │   ├── file_source.py          #      PDF/Word/Excel 文档
│   │   │   ├── database_source.py      #      数据库表
│   │   │   ├── api_source.py           #      API 返回结果
│   │   │   ├── timeseries_source.py    #      时序数据
│   │   │   ├── vector_source.py        #      向量混合
│   │   │   └── graph_source.py         #      知识图谱
│   │   ├── indexing/                   #    索引链路
│   │   ├── retrieval/                  #    多源统一检索
│   │   │   ├── unified_retriever.py    #      统一检索入口
│   │   │   ├── vector_retrieval.py
│   │   │   ├── keyword_retrieval.py
│   │   │   ├── sql_retrieval.py
│   │   │   ├── graph_retrieval.py
│   │   │   └── fusion_retrieval.py     #      多路召回融合
│   │   └── service.py
│   │
│   ├── schedule/                       # ── 调度与触发 ──
│   │   ├── entity.py                   #    Schedule, Trigger(ABC)
│   │   ├── triggers/                   #    触发类型
│   │   │   ├── cron_trigger.py
│   │   │   ├── event_trigger.py
│   │   │   ├── webhook_trigger.py
│   │   │   ├── message_trigger.py      #     MQTT/Kafka 消息触发
│   │   │   └── condition_trigger.py    #     条件触发（如：温度>50度）
│   │   └── engine.py                   #    调度引擎
│   │
│   ├── policy/                         # ── ★ 策略引擎 ──
│   │   ├── entity.py                   #    Policy, PolicyRule, PolicyEvaluation
│   │   ├── evaluator.py                #    策略评估器
│   │   ├── policies/                   #    预置策略类
│   │   │   ├── rbac_policy.py          #      基于角色的访问控制
│   │   │   ├── time_restriction_policy.py   #    时间限制
│   │   │   ├── rate_limit_policy.py
│   │   │   ├── data_scope_policy.py    #      数据范围（只能看本部门）
│   │   │   ├── approval_policy.py      #      需要审批的策略
│   │   │   └── audit_policy.py         #      强制审计的策略
│   │   └── service.py
│   │
│   ├── audit/                          # ── ★ 审计 ├─
│   │   ├── entity.py                   #    AuditLog, DecisionChain
│   │   ├── trace/                      #    链路追踪
│   │   │   ├── decision_tracer.py      #      AI 决策溯源
│   │   │   ├── data_lineage.py         #      数据血缘
│   │   │   └── report_generator.py     #      审计报告
│   │   └── service.py
│   │
│   ├── integration/                    # ── 企业集成 ──
│   │   ├── entity.py                   #    IntegrationAdapter, Connection, Endpoint
│   │   └── service.py                  #    适配器生命周期管理
│   │
│   └── notification/                   # ── 通知 ──
│       ├── entity.py
│       └── service.py
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║         ENTERPRISE KERNEL（企业运行内核）                    ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── kernel/                             # ═══ 企业运行内核 ═══
│   │                                    # Runtime 之上的横切层
│   │                                    # 每一次能力调用必经这里
│   │
│   ├── context.py                      #   请求上下文（租户/用户/角色/会话）
│   ├── permission.py                   #   权限校验（RBAC + 行级数据权限）
│   ├── policy_gate.py                  #   策略关卡（Policy Enforcement Point）
│   ├── human_loop.py                   #   人工介入管理（暂停/审批/恢复/驳回）
│   ├── checkpoint.py                   #   执行检查点（用于恢复/回滚）
│   ├── state.py                        #   执行状态管理
│   ├── artifact.py                     #   产物管理（报告/图片/导出文件）
│   └── orchestrator.py                 #   总协调器（编排 Kernel 各组件）
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║                      PORTS（端口接口层）                     ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── ports/                              # ═══ 端口接口 ═══
│   │                                    # 全部 ABC，零外部依赖
│   │
│   ├── repositories/                   # ── 仓储端口 ──
│   │   ├── workspace_repository.py
│   │   ├── capability_repository.py
│   │   ├── conversation_repository.py
│   │   ├── workflow_repository.py
│   │   ├── knowledge_repository.py
│   │   ├── policy_repository.py
│   │   ├── audit_repository.py
│   │   ├── schedule_repository.py
│   │   └── integration_repository.py
│   │
│   ├── llm_provider.py                 #    LLM 提供商
│   ├── embedding_provider.py
│   ├── rerank_provider.py
│   ├── vector_store.py                 #    向量数据库
│   ├── message_bus.py                  #    消息总线（Kafka/RabbitMQ/MQTT/Redis）
│   ├── cache.py
│   ├── storage.py                      #    对象存储
│   ├── id_generator.py
│   ├── secret_store.py                 #    密钥管理（凭证加密存储）
│   └── policy_decision_point.py        #    外部策略决策点（对接企业 IAM）
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║                 ADAPTERS（出站适配器层）                      ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── adapters/                           # ═══ 适配器实现 ═══
│   │
│   ├── repositories/                   # ── 仓储实现（SQLAlchemy） ──
│   │
│   ├── providers/                      # ── LLM 模型提供商 ──
│   │   ├── openai/
│   │   ├── anthropic/
│   │   ├── azure_openai/
│   │   ├── google_ai/
│   │   ├── local/                      #    Ollama / vLLM
│   │   └── plugin/                     #    插件式提供商
│   │
│   ├── vector_stores/                  # ── 向量数据库 ──
│   │   ├── pgvector/
│   │   ├── qdrant/
│   │   └── milvus/
│   │
│   ├── integrations/                   # ── ★ 企业集成适配器 ──
│   │   ├── __init__.py
│   │   ├── base.py                     #    BaseIntegrationAdapter
│   │   ├── sap/                        #    SAP 适配器（RFC / OData）
│   │   │   ├── adapter.py
│   │   │   └── capabilities.py         #      暴露的业务能力
│   │   ├── kingdee/                    #    金蝶
│   │   ├── yonyou/                     #    用友
│   │   ├── mes/                        #    MES 通用适配器
│   │   │   ├── adapter.py
│   │   │   └── capabilities.py
│   │   ├── erp/                        #    ERP 通用
│   │   ├── database/                   #    数据库适配器
│   │   │   ├── postgres_adapter.py
│   │   │   ├── mysql_adapter.py
│   │   │   ├── sqlserver_adapter.py
│   │   │   └── oracle_adapter.py
│   │   ├── iot/                        #    IoT 适配器
│   │   │   ├── mqtt_adapter.py
│   │   │   ├── opcua_adapter.py
│   │   │   └── modbus_adapter.py
│   │   ├── enterprise_im/              #    企业 IM
│   │   │   ├── wechat_work_adapter.py  #      企业微信
│   │   │   ├── dingtalk_adapter.py     #      钉钉
│   │   │   └── feishu_adapter.py       #      飞书
│   │   ├── oa/                         #    OA 适配器
│   │   ├── rest/                       #    通用 REST
│   │   ├── soap/                       #    SOAP WebService
│   │   └── mcp/                        #    MCP Connector
│   │       └── mcp_connector.py
│   │
│   ├── message_bus/                    # ── 消息总线 ──
│   │   ├── base.py
│   │   ├── kafka_bus.py
│   │   ├── rabbitmq_bus.py
│   │   ├── mqtt_bus.py
│   │   └── redis_streams_bus.py
│   │
│   ├── notification/                   # ── 通知适配器 ──
│   │   ├── email_adapter.py
│   │   ├── sms_adapter.py
│   │   ├── enterprise_wechat_adapter.py
│   │   └── webhook_notification.py
│   │
│   └── policy/                         # ── 外部策略适配 ──
│       ├── opa_adapter.py              #    Open Policy Agent
│       └── iam_adapter.py              #    企业 IAM 对接
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║              MODELS（ORM 数据映射）                           ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── models/                             # ═══ ORM 映射 ═══
│   ├── base.py
│   ├── workspace.py                    #    Tenant, OrgUnit, User, Role, ServiceAccount, Permission
│   ├── capability.py                   #    BusinessCapability, CapabilityConfig
│   ├── conversation.py
│   ├── workflow.py                     #    EnterpriseWorkflow, BusinessNode, NodeRun, ApprovalRecord
│   ├── knowledge.py                    #    KnowledgeBase, KnowledgeSource, Document, Chunk
│   ├── schedule.py                     #    Schedule, Trigger, TriggerLog
│   ├── policy.py                       #    Policy, PolicyRule, PolicyAssignment
│   ├── audit.py                        #    AuditLog, DecisionChain, DataLineage
│   ├── integration.py                  #    IntegrationAdapter, Connection, Credential
│   ├── notification.py
│   ├── artifact.py                     #    Artifact（产物）
│   ├── provider.py
│   └── tool.py
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║        TASKS & SCHEDULER（后台任务与调度）                    ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── tasks/                              # ═══ 后台任务 ═══
│   ├── base_task.py
│   ├── workflow_execution_task.py      #    工作流异步执行
│   ├── document_index_task.py
│   ├── database_index_task.py
│   ├── schedule_evaluation_task.py     #    定时/条件触发评估
│   ├── report_generation_task.py
│   ├── data_cleanup_task.py
│   └── monitor_health_check_task.py
│
│   ╔══════════════════════════════════════════════════════════════╗
│   ║              BOOTSTRAP（启动配置）                            ║
│   ╚══════════════════════════════════════════════════════════════╝
│
├── bootstrap/                          # ═══ 启动配置 ═══
│   ├── container.py                    #    DI 容器
│   ├── app_factory.py                  #    应用工厂
│   ├── config.py                       #    全局配置（pydantic-settings）
│   └── extensions/                     #    框架初始化
│
├── shared/                             # ═══ 共享工具 ═══
│   ├── encryption.py                   #    加密/解密
│   └── logger.py
│
├── migrations/
├── app.py
├── pyproject.toml
├── Dockerfile
└── .env.example
```

---

## 核心架构的变化对比

| 维度 | 之前的通用六边形架构 | 现在企业版架构 |
|------|--------------------|--------------|
| **核心抽象** | `Tool` (技术接口) | `BusinessCapability` (业务能力) |
| **权限控制** | 应用层手动处理 | `kernel/policy_gate.py` 统一策略关卡 |
| **人工介入** | 不支持 | `kernel/human_loop.py` 原生支持暂停/审批/恢复 |
| **知识库** | 仅文档+向量检索 | 多源：File/DB/API/TimeSeries/Vector/Graph |
| **集成** | 无独立集成层 | `adapters/integrations/` 企业适配器体系 |
| **消息总线** | EventBus（进程内） | MessageBus（Kafka/RabbitMQ/MQTT） |
| **调度** | Celery Beat | 完整 `domain/schedule/` 支持 Cron/Event/Webhook/MQTT/Condition |

> **Deprecated**：任务队列选型已改为 procrastinate（见 ADR-007 与 server-side-development-plan v1.4，PRD-2026-020 spike 四场景全 PASS 定案 D6）。本文作业遗留，仅作架构推演参考。
| **审计** | 无 | `domain/audit/` 完整决策链溯源 |
| **产物管理** | 无 | `kernel/artifact.py` 统一管理执行产物 |
| **多租户** | 隐含 tenant_id | 显式 `domain/workspace/` 含 Tenant/Org/User/Role/ServiceAccount |

---

## 业务能力（Capability）的设计

这是整个架构中最核心的变化。

### 什么是 Business Capability

```
┌──────────────────────────────────────────────┐
│            Business Capability                │
│                                              │
│  capability_id: "query_work_order"           │
│  domain: "manufacturing.production"          │
│  name: "查询工单"                             │
│  description: "根据工单号或日期查询生产工单"     │
│                                              │
│  input_schema: {                             │
│    work_order_id: string,                    │
│    date_range: [date, date]                  │
│  }                                           │
│  output_schema: {                            │
│    work_orders: [...]                        │
│  }                                           │
│                                              │
│  auth_required: true                         │
│  rate_limit: 100/minute                      │
│  approval_required: false                    │
│  audit_level: "detail"                       │
│                                              │
│  adapter: "sap_adapter"                      │
│  adapter_method: "query_orders"              │
└──────────────────────────────────────────────┘
```

### Capability 的分层映射

```
Runtime 视角：
  agent.execute("query_work_order", {"id": "WO20240701"})
                    │
                    ▼
          BusinessCapability("query_work_order")
                    │
                    ▼
        IntegrationAdapter.sap_adapter.query_orders()
                    │
                    ▼
        SAP RFC/BAPI → SAP ERP 系统
```

### Capability vs Tool 的区别

| | Dify Tool | Business Capability |
|---|---|---|
| 关注点 | "怎么调" | "做什么" |
| 命名 | `execute_sql` | `query_inventory` |
| 参数 | 技术参数 (host/port/sql) | 业务参数 (material_id/date) |
| 权限 | 无 | 有（谁可以调） |
| 审计 | 无 | 有（调用全记录） |
| 策略 | 无 | 有（限流/审批/数据范围） |
| 底层 | HTTP API | SAP/MES/DB/API 任意 |

---

## 企业级执行流程（一次完整的调度）

```
┌─ 触发 ──────────────────────────────────────────────┐
│                                                      │
│  Cron: 每天 8:00 / MQTT: 设备报警 / Webhook: 用户请求   │
│                                                      │
├─ 鉴权 ──────────────────────────────────────────────┤
│                                                      │
│  Kernel.context → 确认 谁 / 在哪 / 做什么              │
│  Kernel.permission → RBAC 校验                       │
│                                                      │
├─ 执行 ──────────────────────────────────────────────┤
│                                                      │
│  Runtime.executor                                    │
│    ├─▶ Agent: "统计昨天所有产线异常"                   │
│    │      ├─▶ Capability: query_equipment_alarms     │
│    │      │      └─▶ MES Adapter → MES              │
│    │      ├─▶ Capability: query_sql                  │
│    │      │      └─▶ Database Adapter → PostgreSQL   │
│    │      ├─▶ Knowledge: retrieve_sop                │
│    │      │      └─▶ Vector + Keyword 混合检索       │
│    │      ├─▶ Capability: generate_report            │
│    │      └─▶ Kernel.human_loop: 人工审核报告         │
│    │             ├─▶ Pause → 通知审批人               │
│    │             ├─▶ Approve → Resume                │
│    │             └─▶ Reject → 回退+记录               │
│    └─▶ Capability: send_oa_notification              │
│           └─▶ OA Adapter → 企业微信/钉钉/OA系统       │
│                                                      │
├─ 记录 ──────────────────────────────────────────────┤
│                                                      │
│  AuditLog: 完整记录每一步                             │
│  DecisionChain: AI 决策溯源                          │
│  Artifact: 生成的报告文件 → Object Storage            │
│                                                      │
└──────────────────────────────────────────────────────┘
```

---

## 依赖规则

| 层级 | 可以引用 | 不可以引用 |
|------|----------|-----------|
| `interfaces/*` | `application/*`, `ports/*` | `domain/*` |
| `application/*` | `domain/*`, `ports/*`, `kernel/*` | `models/*`, Flask/SQLAlchemy/Redis |
| `kernel/*` | `domain/*`, `ports/*` | `models/*`, 框架代码 |
| `domain/*` | `ports/*` (接口), Python 标准库 | Flask/SQLAlchemy/Redis, `models/*` |
| `ports/*` | ABC (标准库) | 任何框架 |
| `adapters/*` | `ports/*`, `models/*` | `domain/*` (实现 Port 接口) |
| `models/*` | SQLAlchemy | 业务逻辑 |

---

## 演进建议

### Phase 1：MVP（1-3 个月）— 核心能力搭建
- `domain/workspace/`（多租户骨架）
- `domain/capability/`（业务能力注册与执行）
- `domain/conversation/`（基础对话）
- `domain/workflow/`（基础业务流程引擎）
- `kernel/policy_gate.py`（统一策略入口）
- `adapters/integrations/database/`（数据库适配器）

### Phase 2：成熟（3-6 个月）— 企业级特性补齐
- `domain/policy/`（完整策略引擎）
- `domain/audit/`（审计与决策链溯源）
- `kernel/human_loop.py`（人工审批流）
- `adapters/integrations/`（SAP/金蝶/用友/MQTT/OPC-UA）
- `domain/knowledge/sources/`（多源知识库）
- `domain/schedule/`（调度引擎）

### Phase 3：规模化（6-12 个月）— 生态与深度集成
- `adapters/integrations/`（适配器生态扩展）
- `adapters/message_bus/`（Kafka/RabbitMQ 全面对接）
- 多租户自服务 Portal
- 企业 IAM / SSO 对接
- 高可用部署架构
