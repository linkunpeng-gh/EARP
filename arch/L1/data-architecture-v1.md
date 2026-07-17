# EARP 数据架构视图

## L1 — 数据架构

**文档编号：L1-DATA**  
**版本：v1.0**  
**定位：L1 — 系统架构。定义 EARP 的数据域划分、存储选型、实体关系、生命周期管理和迁移策略。**  
**依赖：L1/enterprise-architecture.md, L1/deployment-architecture-v1.md, L2-07-TENANT v1.1, L2-05-AUDIT v1.1, L2-01-RUNTIME v1.2**

---

# 第一章：数据域划分

## 1.1 八大域总览

| 域 | 核心实体 | 存储引擎 | 关键索引 |
|:---|:---------|:---------|:---------|
| **Runtime** | Session, Execution, Context, Checkpoint | PostgreSQL | `(tenant_id, session_id)`, `(tenant_id, status)`, `(created_at)` |
| **Capability** | BusinessCapability, CapabilitySchema, CapabilityCall, ConnectorBinding | PostgreSQL + pgvector | `(capability_id) UNIQUE`, `(domain, tenant_id)`, 向量索引: `embedding` (cosine) |
| **Governance** | Policy, PolicyBinding, AuditLog, MetricSnapshot | PostgreSQL | `(tenant_id, policy_type)`, `(tenant_id, event_type, created_at)` |
| **Workspace** | Tenant, OrgUnit, User, Role, ServiceAccount | PostgreSQL | `(tenant_id) UNIQUE`, `(org_unit_id, tenant_id)`, `(user_id, tenant_id)` |
| **Security** | EncryptedCredential, APIKey, CertificateFingerprint | PostgreSQL (密文) + Vault | `(tenant_id, credential_type)`, `(connector_id, tenant_id)` |
| **Knowledge** | KnowledgeBase, Document, Chunk, VectorIndex | PostgreSQL + pgvector | `(kb_id, tenant_id)`, `(chunk_id, kb_id)`, `embedding` (cosine) |
| **Conversation** | Conversation, Message, MessageAttachment | PostgreSQL | `(tenant_id, user_id, created_at)`, `(conversation_id, seq)` |
| **Integration** | ConnectorConfig (加密), AdapterHealth, ConnectionPool | PostgreSQL | `(connector_id, tenant_id)`, `(adapter_type, status)` |

## 1.2 域间关系

```
Workspace ──── 所有域的基础（tenant_id 来源）
Runtime ────── 调用 Capability（Execution → CapabilityCall）
Capability ─── 绑定 Integration（Capability ↔ Connector）
Governance ─── 横切所有域（Policy 评估 + Audit 日志）
Knowledge ──── 被 Runtime/Capability 查询（RAG 检索）
Conversation ─ 关联 Workspace.User + Runtime.Execution
Security ───── 保护 Integration（凭证加密） + Workspace（认证）
```

**LLM 数据横切处理**：Prompt/Response、Token 用量等 LLM 相关数据不独立成域——Prompt+Response 作为 Execution.payload 的子字段存储，Token 用量作为 MetricSnapshot 由 Governance 域承载。

---

# 第二章：实体关系图

## 2.1 核心 ER 图

```
                         ┌──────────────┐
                         │   Tenant     │
                         │ (tenant_id)  │
                         └──────┬───────┘
                                │ 1
                                │
                    ┌───────────┼───────────┐
                    │           │           │
                    ▼           ▼           ▼
             ┌──────────┐ ┌──────────┐ ┌──────────┐
             │ OrgUnit  │ │   User   │ │ Service  │
             │(org_id,  │ │(user_id, │ │ Account  │
             │ tenant)  │ │ tenant)  │ │(sa_id,   │
             └──────────┘ └────┬─────┘ │ tenant)   │
                               │       └──────────┘
                               │ creates
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                        Runtime 域                             │
│                                                              │
│  ┌──────────┐    1:N    ┌───────────┐    1:N   ┌──────────┐ │
│  │ Session  │──────────▶│ Execution │─────────▶│Checkpoint│ │
│  │(sess_id, │           │(exec_id,  │          │(ckpt_id, │ │
│  │ tenant,  │           │ session,  │          │ exec,    │ │
│  │ user)    │           │ tenant)   │          │ seq)     │ │
│  └──────────┘           └─────┬─────┘          └──────────┘ │
│                               │                              │
└───────────────────────────────┼──────────────────────────────┘
                                │ calls
                                ▼
┌──────────────────────────────────────────────────────────────┐
│                      Capability 域                            │
│                                                              │
│  ┌────────────────┐     1:N    ┌───────────────┐            │
│  │BusinessCapability│──────────▶│ CapabilityCall│            │
│  │(cap_id UNIQUE,  │           │(call_id,      │            │
│  │ tenant, domain) │           │ exec, cap,    │            │
│  └───────┬─────────┘           │ tenant)       │            │
│          │                     └───────────────┘            │
│          │ binds                                             │
│          ▼                                                   │
│  ┌────────────────┐    引用   ┌──────────────────┐         │
│  │ConnectorBinding│──────────▶│ Integration.Conn │         │
│  │(cap_id+conn_id,│           │ ectorConfig      │         │
│  │ tenant)        │           │ (conn_id,tenant) │         │
│  └────────────────┘           └──────────────────┘         │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    Governance 域（横切）                      │
│                                                              │
│  ┌──────────┐   1:N   ┌───────────────┐                    │
│  │ Policy   │────────▶│ PolicyBinding │                    │
│  │(policy_id│         │(policy_id,    │                    │
│  │ tenant,  │         │ capability_id,│  entity_type        │
│  │ type)    │         │ tenant)       │  + entity_id        │
│  └──────────┘         └───────────────┘  引用 ─────────────▶│
│                                                              │
│  ┌──────────┐                                              │
│  │AuditLog  │── entity_type + entity_id ──▶ 引用各域实体    │
│  │(log_id,  │   (如 "session"/"sess-1")                     │
│  │ tenant,  │                                              │
│  │ event)   │                                              │
│  └──────────┘                                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                   Knowledge 域                               │
│                                                              │
│  ┌─────────────┐  1:N  ┌──────────┐  1:N  ┌───────┐       │
│  │KnowledgeBase│──────▶│ Document │──────▶│ Chunk │       │
│  │(kb_id,      │       │(doc_id,  │       │(chunk │       │
│  │ tenant)     │       │ kb)      │       │ +embed│       │
│  └─────────────┘       └──────────┘       └───────┘       │
└──────────────────────────────────────────────────────────────┘
```

## 2.2 关系说明

| 关系 | 基数 | 说明 |
|:-----|:----:|:-----|
| Tenant → Session | 1:N | 一个租户可以有多个会话 |
| Session → Execution | 1:N | 一个会话包含多个执行 |
| Execution → CapabilityCall | 1:N | 一次执行可调用多个能力 |
| CapabilityCall → ConnectorBinding | N:1 | 每次调用通过一个 connector 完成 |
| Policy → PolicyBinding | 1:N | 一个策略绑定到多个能力 |
| AuditLog → 各域实体 | N:1 (逻辑) | 通过 entity_type+entity_id 引用 |
| KnowledgeBase → Document → Chunk | 1:N:N | 知识库→文档→分块 |
| User → Session | 1:N | 用户创建会话 |

---

# 第三章：存储技术选型

## 3.1 选型对比

| 数据需求 | 选择 | 替代方案 | 选择理由 |
|:---------|:-----|:---------|:---------|
| 事务数据 (Session/Execution/User) | **PostgreSQL** | MySQL | ACID 完整、JSONB 灵活、RLS 原生支持多租户、丰富扩展生态 |
| 向量搜索 (Capability 语义匹配/RAG) | **pgvector** (PG 扩展) | Milvus/Qdrant | 零额外运维（同 PG 集群）、事务一致性（向量与元数据同库）、SQL 查询无需跨库 JOIN |
| 缓存/状态 (Session 热数据/限流) | **Redis** | KeyDB/Dragonfly | 成熟稳定、Cluster 模式、丰富数据结构 (Hash/SortedSet/Stream) |
| 对象存储 (文件/日志归档) | **S3 (MinIO)** | Ceph/Local PV | S3 API 兼容、Erasure Code、MinIO 轻量运维 |
| 事件总线 | **RabbitMQ** | Kafka/Redis Streams | 低延迟（ms 级）、灵活路由（Exchange/Queue）、Phase 2 可选 Kafka 提升吞吐 |
| 指标 (Metrics) | **Prometheus** | InfluxDB/VictoriaMetrics | K8s 原生、Pull 模型、多维标签（含 tenant_id）、PromQL 强大 |
| 日志聚合 | **Loki** | ELK/Graylog | 低资源占用、与 Prometheus/Grafana 统一栈、标签索引（非全文） |

## 3.2 为什么不是多模型数据库

| 候选 | 排除理由 |
|:-----|:---------|
| MongoDB | 事务支持弱（多文档 ACID 4.0+）、无原生 RLS、缺乏向量搜索 |
| CockroachDB | 运维复杂、向量搜索需扩展、RLS 不成熟 |
| TiDB | MySQL 兼容但 pgvector 不兼容、KV 层引入额外延迟 |
| Neo4j | 专用图数据库，引入新的运维负担；PG 的关系查询足以覆盖 |

> **Vault 说明**：HashiCorp Vault 定位为外部密钥管理服务，而非通用存储引擎。Security 域的凭证密文存储在 PostgreSQL 中，解密密钥由 Vault 管理。Vault 自身的数据持久化依赖其内置的 Raft 存储后端（或 Consul），不在 EARP 数据架构的直接管辖范围内。

---

# 第四章：数据生命周期

## 4.1 TTL 与归档策略

| 数据类型 | 存储 | TTL (prod) | 归档策略 | 清理方式 | 对齐规范 |
|:---------|:-----|:----------:|:---------|:---------|:---------|
| Session | PG | 24h (completed) | S3 归档（JSON dump） | 定时任务，每日 02:00 | Tenant Spec (存储配额) |
| Execution | PG | 30d (completed) | S3 归档（JSON dump） | 定时任务，每日 03:00 | — |
| Checkpoint | PG | 跟随 Execution | S3 随 Execution 归档 | — | — |
| CapabilityCall | PG | 90d | S3 归档 | 定时任务 | — |
| AuditLog (热) | PG | 90d | S3 归档 → 冷存储 | 定时任务 | Audit Spec |
| LLM Prompt+Response | PG (AuditLog.detail) | 30d | S3 归档 | 跟随 AuditLog | Audit Spec §LLM |
| Prometheus 指标 | TSDB | 30d | 远程写入 S3 | 自动 | Deployment Arch §4.3 |
| Loki 日志 | Loki | 30d | — | 自动 | — |
| WAL 归档 | S3 | 7d | — | 自动清理 | Deployment Arch §4.3 |
| PG 快照 | S3 | 30d | — | 自动清理 | Deployment Arch §4.3 |
| Redis Session 热数据 | Redis | 跟随 Session TTL | — | TTL 自动过期 | — |
| 文件上传 | S3 | 永久 | — | 租户手动管理 | — |

## 4.2 备份 RPO/RTO

| 存储 | RPO | RTO | 备份方式 |
|:-----|:----:|:----:|:---------|
| PostgreSQL | 5 min | 30 min | WAL 连续归档 + 每日快照 |
| Redis | 1 h | 15 min | RDB 60min + AOF |
| S3 (MinIO) | 0（实时） | 4 h | 跨 Bucket 实时复制 |
| RabbitMQ | 24 h | 2 h | 配置导出 + 消息日志 |

---

# 第五章：多租户数据隔离

| 存储 | 隔离方式 | 规范引用 |
|:-----|:---------|:---------|
| PostgreSQL | 共享数据库 + Row-Level Security (`WHERE tenant_id = current_tenant_id()`) | Tenant Spec §5.1 |
| pgvector | 同 PG（向量与元数据同表，RLS 自动覆盖） | — |
| Redis | Key 前缀 `t:{tenant_id}:session:{id}` | Tenant Spec §5.2 |
| S3 | Bucket 内前缀 `earp/{tenant_id}/...` | Tenant Spec §5.3 |
| RabbitMQ | 共享 Exchange + tenant_id routing key | — |
| Prometheus | 指标标签 `tenant_id`，跨租户聚合仅管理员 | Tenant Spec §7.2 |
| Loki | 日志标签 `tenant_id` | — |

**关键设计**：所有持久的 `BaseTenantEntity` 子类在 ORM 层自动注入 `WHERE tenant_id = ?`，开发者无需手写租户过滤条件。RLS 作为第二道防线——即使 ORM 层被绕过，数据库层仍然阻止跨租户访问。

---

# 第六章：数据迁移策略

## 6.1 版本管理

| 维度 | 策略 |
|:-----|:-----|
| 工具 | Alembic（Python SQLAlchemy 生态） |
| 版本文件 | `migrations/versions/{revision}_desc.py` |
| 命名约定 | `{timestamp}_{description}` |
| 多环境同步 | dev 自动执行（CI），staging/prod 手动触发 |

## 6.2 迁移流程

```
开发环境：
  1. 修改 SQLAlchemy 模型
  2. alembic revision --autogenerate -m "add_xxx_table"
  3. alembic upgrade head (dev)
  4. 提交 migration 文件到 Git

staging/prod：
  1. PR merge → CI 检查 migration 有无冲突
  2. 部署前：alembic upgrade head（由部署脚本执行）
  3. 回滚：alembic downgrade -1
```

## 6.3 大表迁移

对于 Session/Execution/AuditLog 等预期增长较快的表：
- 新增列/索引：`ALTER TABLE ... ADD COLUMN`（在线 DDL，PG 11+ 不锁表）
- 重命名列：分两步（新建列 + 双写 → 切换读取 → 删除旧列）
- 数据迁移（如分区）：新建分区表 → 后台批量迁移 → 切换表名
- 禁止：`ALTER TABLE ... ALTER COLUMN TYPE`（需全表重写，锁表）
