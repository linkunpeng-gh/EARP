# EARP 部署架构视图

## L1 — 部署架构

**文档编号：L1-DEPLOYMENT**  
**版本：v1.1**  
**定位：L1 — 系统架构。定义 EARP 各组件的部署拓扑、网络策略、存储部署、扩缩容策略和环境管理。**  
**依赖：L1/enterprise-architecture.md, L1/dify-hexagonal-architecture.md, L2-07-TENANT v1.1, L2-06-SECURITY v1.1, L2-05-OBSERVATION v1.0**

> **v1.1 变更**：拓扑图增加图例和 NetworkPolicy 边界标注；§2.1 补全 8 个缺失组件资源规格 (§1.2 同步)；Workflow Engine 加入 §1.2；InputGuard/OutputFilter/MCP Server 加入拓扑；通信矩阵补全 Runtime→KB/Audit/WorkflowEngine + Policy Center 路径；TLS 版本明确为 1.3；dev/staging 资源策略独立列表；Prometheus 端口改为 9099；亲和性降级为 preferred；补充采集频率/保留期/节点规格/备份保留。

---

# 第一章：基础设施拓扑

## 1.1 K8s 集群拓扑图

```
    ╔══════════════════════════════════════════════════════════════════╗
    ║                        图    例                                 ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║  ┌──────┐ = 业务组件 (Deployment)    ═══ = 网络策略边界        ║
    ║  ╞══════╡ = 数据存储 (StatefulSet)   ─── = HTTP/gRPC 通信     ║
    ║  ┆┄┄┄┄┄┄┆ = 辅助组件 (Sidecar/代理)  ··· = 出口流量 (Egress)  ║
    ╚══════════════════════════════════════════════════════════════════╝

                                    ┌──────────────────────────────────────┐
                                    │            INTERNET / VPC            │
                                    └──────────────┬───────────────────────┘
                                                   │
                              ╔════════════════════╪════════════════════╗
                              ║  Ingress 安全域     │                    ║
                              ║                ┌────┴────┐               ║
                              ║                │  TLS 1.3│               ║
                              ║                │  Term.  │               ║
                              ║                │(cert-   │               ║
                              ║                │ manager)│               ║
                              ║                └────┬────┘               ║
                              ║   ┌─────────────────┼──────────────┐     ║
                              ║   │                 │              │     ║
                              ║ ┌─┴───┐  ┌─────┐  ┌─┴───┐  ┌─────┴──┐  ║
                              ║ │GW   │  │WS GW│  │gRPC │  │  MCP   │  ║
                              ║ │REST │  │Sock │  │GW   │  │ Server │  ║
                              ║ │Nginx│  │etIO │  │Envoy│  │        │  ║
                              ║ └──┬──┘  └──┬──┘  └──┬──┘  └───┬────┘  ║
                              ║    │        │        │         │       ║
                              ╚════╪════════╪════════╪═════════╪═══════╝
                                   │        │        │         │
                              ╔════╪════════╪════════╪═════════╪═══════╗
                              ║    │  Service Mesh (Istio) + mTLS      ║
                              ║    │  InputGuard: Gateway 中间件        ║
                              ║    └────────────────┬───────────────────║
                              ╚═════════════════════╪═══════════════════╝
                                                    │
         ┌──────────────────────────────────────────┼───────────────────────────────┐
         │                               业务服务域                                  │
         │   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐      │
         │   │Runtime│ │Plan- │ │Capab.│ │Policy│ │Audit │ │Know- │ │Work- │      │
         │   │Svc    │ │ner   │ │Reg.  │ │Center│ │Svc   │ │ledge │ │flow  │      │
         │   │       │ │      │ │      │ │      │ │      │ │Base  │ │Engine│      │
         │   └──┬────┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘      │
         │      │         │        │        │        │        │        │          │
         │      └─────────┴────────┴────────┴────────┴────────┴────────┘          │
         ╞══════════════════════════════════════════════════════════════════════════╡
         │                          安全域 / 沙箱域                                 │
         │   ┌──────────────┐  ┌────────────────────┐                             │
         │   │ OutputFilter │  │ Plugin gRPC Daemon │  (Capability 链拦截器)      │
         │   │ (拦截器)     │  │ (子进程隔离)        │                             │
         │   └──────────────┘  └────────────────────┘                             │
         ╞══════════════════════════════════════════════════════════════════════════╡
         │                           数据存储域                                     │
         │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
         │   │PostgreSQL│ │  Redis   │ │   S3     │ │ Message  │                 │
         │   │(P+R×2)  │ │ Cluster  │ │ (MinIO)  │ │ Bus(Rab) │                 │
         │   │+pgvector │ │          │ │          │ │          │                 │
         │   ╞══════════╡ ╞══════════╡ ╞══════════╡ ╞══════════╡                 │
         ╞══════════════════════════════════════════════════════════════════════════╡
         │                         可观测性域 (Sidecar)                             │
         │   ┆ Fluentd → Loki ┆ ┆ Prometheus Exporter → Prometheus ┆             │
         │   ┆ OTel Agent → Jaeger/Tempo ┆                                        │
         ╞══════════════════════════════════════════════════════════════════════════╡
         │                      Connector Egress (出口白名单)                       │
         │   ··· LLM API (OpenAI/Anthropic) ··· SAP/MES/ERP ··· Vault/KMS ···    │
         ╘══════════════════════════════════════════════════════════════════════════╛
```

## 1.2 组件分布

| 组件 | K8s 资源 | 副本数 | 节点池 | 说明 |
|:-----|:---------|:------:|:------:|:-----|
| Gateway (REST) | Deployment | 3 | frontend | Nginx, HTTP 路由 + InputGuard 中间件 |
| WebSocket Gateway | Deployment | 2 | frontend | SocketIO, 实时推送 + 流式输出 |
| gRPC Gateway | Deployment | 2 | frontend | Envoy, 内部服务 + Plugin Daemon |
| MCP Server | Deployment | 2 | frontend | Model Context Protocol 服务 |
| Runtime Service | Deployment | 3 | backend | 会话管理、Execution 编排 |
| Planner Service | Deployment | 2 | backend | LLM Plan 生成 |
| Capability Registry | Deployment | 2 | backend | 能力注册/发现 |
| Policy Center | Deployment | 2 | backend | 策略评估 |
| Audit Service | Deployment | 2 | backend | 审计日志订阅+写入 |
| Knowledge Base | Deployment | 2 | backend | RAG 检索、向量搜索 |
| Workflow Engine | Deployment | 2 | backend | 企业流程执行 |
| OutputFilter | — | (嵌入) | backend | Capability 调用链拦截器（代码模块，非独立 Pod） |
| PostgreSQL Primary | StatefulSet | 1 | data | 主库：事务数据、审计日志 |
| PostgreSQL Replica | StatefulSet | 2 | data | 只读副本 |
| Redis Cluster | StatefulSet | 3 | data | 缓存、Session 状态 |
| S3 (MinIO) | StatefulSet | 4 | data | 对象存储 |
| Message Bus | StatefulSet | 3 | data | RabbitMQ：事件总线（Phase 2 可选 Kafka）|
| Connector Daemon | DaemonSet | per-node | connector | 外部系统连接器 |
| Plugin gRPC Daemon | DaemonSet | per-node | backend | Plugin 子进程隔离 |

---

# 第二章：组件规格

## 2.1 资源与扩缩容

| 组件 | CPU req | CPU lim | Mem req | Mem lim | HPA | 存储 |
|:-----|:------:|:------:|:------:|:------:|:-----|:-----|
| Gateway (REST) | 500m | 2000m | 512Mi | 2Gi | CPU>70%, 3-10 | — |
| WebSocket Gateway | 500m | 2000m | 512Mi | 2Gi | Conn>70%, 2-6 | — |
| gRPC Gateway | 500m | 2000m | 512Mi | 2Gi | CPU>70%, 2-6 | — |
| MCP Server | 500m | 2000m | 512Mi | 2Gi | CPU>70%, 2-6 | — |
| Runtime | 1000m | 4000m | 1Gi | 4Gi | CPU>60%, 3-8 | — |
| Planner | 2000m | 8000m | 2Gi | 8Gi | CPU>70%, 2-6 | — |
| Capability Registry | 500m | 2000m | 512Mi | 2Gi | — | — |
| Policy Center | 500m | 2000m | 512Mi | 2Gi | — | — |
| Audit Service | 500m | 2000m | 512Mi | 2Gi | — | — |
| Knowledge Base | 1000m | 4000m | 1Gi | 4Gi | CPU>70%, 2-4 | — |
| Workflow Engine | 500m | 2000m | 512Mi | 2Gi | — | — |
| Connector Daemon | 500m | 2000m | 512Mi | 2Gi | — | — |
| Plugin gRPC Daemon | 500m | 2000m | 512Mi | 2Gi | — | — |
| PostgreSQL Primary | 2000m | 8000m | 4Gi | 16Gi | — | `/var/lib/postgresql/data` 100Gi SSD |
| PostgreSQL Replica | 1000m | 4000m | 2Gi | 8Gi | Conn>70%, 2-4 | `/var/lib/postgresql/data` 100Gi SSD |
| Redis Cluster | 500m | 2000m | 2Gi | 8Gi | — | `/data` 50Gi SSD |
| S3 (MinIO) | 1000m | 4000m | 2Gi | 8Gi | — | `/data` 500Gi HDD |
| Message Bus | 1000m | 4000m | 2Gi | 8Gi | Q depth>10K, 3-5 | `/var/lib/rabbitmq` 50Gi SSD |
| Fluentd Sidecar | 100m | 500m | 128Mi | 512Mi | — | — |
| Prometheus Export | 50m | 200m | 64Mi | 256Mi | — | — |
| OTel Agent | 100m | 500m | 128Mi | 512Mi | — | — |

## 2.2 高可用配置

| 配置项 | 值 |
|:-----|:-----|
| Pod 反亲和 | `preferredDuringSchedulingIgnoredDuringExecution`（同组件优先分布到不同节点） |
| 跨 AZ 分布 | `topologySpreadConstraints` — maxSkew=1, whenUnsatisfiable=ScheduleAnyway |
| PDB | ≥2 副本组件：`maxUnavailable: 1`（PostgreSQL Primary：`maxUnavailable: 0`） |
| 健康检查 | livenessProbe: `/health`, readinessProbe: `/ready`，间隔 10s |
| 滚动更新 | maxSurge=1, maxUnavailable=0 |

## 2.3 LLM 并发控制

| 配置项 | 值 |
|:-----|:-----|
| 每 Planner 实例并发 LLM 调用 | 10 |
| 全局上限 | 20（2 副本 × 10） |
| 排队策略 | FIFO，超时 120s |
| 超时处理 | HTTP 429 + Retry-After（Security Spec §5.2） |
| Per-tenant 限流 | Policy Center rate_limit |

---

# 第三章：网络拓扑

## 3.1 通信矩阵

| 源 → 目标 | 协议 | 端口 | 认证 | 说明 |
|:----------|:-----|:----:|:-----|:-----|
| 外部 → Gateway | HTTPS | 443 | JWT | 用户/API 请求入口 |
| 外部 → MCP Server | HTTPS | 444 | JWT/API Key | MCP 客户端连接 |
| Gateway → Runtime | gRPC | 9090 | mTLS | 请求路由 |
| Gateway → WebSocket | WSS | 9443 | JWT | 实时推送 |
| Runtime → Planner | gRPC | 9091 | mTLS | Plan 生成 |
| Runtime → Capability Registry | gRPC | 9092 | mTLS | 能力发现 |
| Runtime → Policy Center | gRPC | 9093 | mTLS | 策略评估 |
| Runtime → Knowledge Base | gRPC | 9097 | mTLS | RAG 检索 |
| Runtime → Audit Service | gRPC | 9098 | mTLS | 审计写入 |
| Runtime → Workflow Engine | gRPC | 9099 | mTLS | 流程执行 |
| Policy Center ↔ 被保护组件 | gRPC | 9100 | mTLS | 策略评估回调 |
| Capability → Connector Daemon | gRPC | 9094 | mTLS | 外部调用 |
| OutputFilter → Capability | (嵌入) | — | — | 拦截器，同进程 |
| Plugin → gRPC Daemon | gRPC | 9095 | — | 子进程隔离 |
| Connector → LLM API | HTTPS | 443 | API Key | OpenAI/Anthropic |
| Connector → 企业系统 | HTTPS/gRPC | 443/9101 | mTLS/Key | SAP/MES/ERP |
| Fluentd → Loki | gRPC | 9096 | — | 日志推送 |
| Prometheus → Exporter | HTTP | 9099 | — | 指标抓取（非 9090，避免与 gRPC 冲突） |
| OTel Agent → Jaeger | gRPC | 4317 | — | Trace 导出 |

## 3.2 入口流量

```
外部请求 → Nginx Ingress (L7)
  ├── /api/*       → Gateway REST（console/portal/openapi）
  ├── /ws/*        → WebSocket Gateway
  ├── /grpc/*      → gRPC Gateway
  ├── /mcp/*       → MCP Server
  └── /health      → 无需认证
```

## 3.3 出口流量

```
Connector Daemon → 白名单外部端点
  ├── api.openai.com:443
  ├── api.anthropic.com:443
  ├── <customer-sap>:443
  ├── <vault-endpoint>:8200
  └── <oci-registry>:443
```

## 3.4 Istio mTLS 与可观测性兼容

Prometheus 抓取 Prometheus Exporter 时使用 HTTP（非 mTLS），通过 Istio `PeerAuthentication` 对端口 9099 设置 `PERMISSIVE` 模式。其他所有服务间通信强制 `STRICT` mTLS。

---

# 第四章：数据存储部署

## 4.1 存储拓扑

| 存储 | 部署 | 数据内容 |
|:-----|:-----|:---------|
| PostgreSQL | Primary + 2 Replica (StatefulSet) | Session、Execution、Capability 注册、Policy、Audit 热数据 |
| pgvector | PostgreSQL Extension（同集群） | 向量搜索（Phase 2 可选 qdrant/milvus） |
| Redis | 3 节点 Cluster (StatefulSet) | Session 状态、限流计数、分布式锁 |
| S3 (MinIO) | 4 节点 (StatefulSet, erasure code) | 文件上传、审计归档、LLM Prompt/Response 归档 |
| RabbitMQ | 3 节点 (StatefulSet) | EventBus（Phase 2 可选 Kafka） |
| Prometheus TSDB | Prometheus Operator | 指标（采集频率 30s，保留 30 天，Obs Spec §2.2） |
| Loki | StatefulSet | 日志聚合 |

## 4.2 多租户数据隔离

| 存储 | 隔离方式 |
|:-----|:---------|
| PostgreSQL | 共享数据库 + RLS (`WHERE tenant_id = current_tenant_id()`) |
| Redis | Key 前缀 `t:{tenant_id}:...`（Multi-Tenant Spec §5.2） |
| S3 | Prefix `earp/{tenant_id}/...` |
| RabbitMQ | 共享 Exchange + tenant_id routing key |

## 4.3 备份策略

| 存储 | RPO | RTO | 备份方式 | 备份保留 |
|:-----|:----:|:----:|:---------|:--------:|
| PostgreSQL | 5 min | 30 min | WAL 连续归档 + 每日快照 | WAL 7d, 快照 30d |
| Redis | 1 h | 15 min | RDB 60min + AOF | 7 天 |
| S3 (MinIO) | 0（实时） | 4 h | 跨 Bucket 实时复制 | 源 Bucket 策略 |
| RabbitMQ | 24 h | 2 h | 配置导出 + 消息日志 | 30 天 |
| Prometheus | 24 h | 4 h | 远程写入 S3 | 30 天 |

---

# 第五章：环境策略

## 5.1 三环境差异

| 维度 | dev | staging | prod |
|:-----|:-----|:-----|:-----|
| **集群规模** | 3 节点 (kind/minikube) | 5 节点（跨 2 AZ） | ≥9 节点（跨 3 AZ） |
| **节点规格** | 4C8G | backend:8C16G, data:4C16G | backend:8C32G, data:4C32G, frontend:4C16G |
| **副本数** | 1（全部） | 2（核心），1（辅助） | 3（Gateway/Runtime），2（其余） |
| **资源 request** | 见下表 | 见下表 | 见 §2.1 |
| **密钥源** | 环境变量（dev 豁免 §6 安全策略） | Vault（dev 实例） | Vault（HA）+ KMS |
| **数据保留** | 7 天 | 30 天 | 90 天（审计）/ 30 天（其他） |
| **网络隔离** | 无 VPC | 独立 VPC + NetworkPolicy | 独立 VPC + NetworkPolicy + WAF |
| **外部依赖** | Mock（SAP/MES stub） | Staging 沙箱 | 生产系统 |
| **日志级别** | DEBUG | INFO | WARN |

### dev/staging 资源表

| 组件 | dev CPU/mem | staging CPU/mem |
|:-----|:----------:|:-------------:|
| Gateway / Runtime / Planner | prod × 1/4 | prod × 1/2 |
| 其他业务组件 | 250m / 256Mi | 500m / 512Mi |
| 数据存储 | 500m / 1Gi | 1000m / 2Gi |

## 5.2 CI/CD 对接

- dev：Git push → 自动构建 + 部署
- staging：PR merge to main → 自动部署
- prod：手动触发 + 审批

---

# 第六章：安全边界

| 边界 | 实现 |
|:-----|:-----|
| TLS 终端 | Gateway 层，TLS 1.3（Security Spec §3.1），cert-manager 自动签发/续签（90 天轮换） |
| 服务间 mTLS | Istio Service Mesh，STRICT 模式（除 Prometheus 抓取端口 9099 为 PERMISSIVE） |
| 网络策略 | Kubernetes NetworkPolicy — 默认禁止跨 namespace 流量 |
| Vault/KMS | 凭证加密密钥存储；Connector API Key 通过 Vault Agent Injector 注入 |
| 镜像安全 | Trivy（CI）+ Harbor（注册），阻断 CRITICAL/HIGH CVE |
| 密钥注入 | 禁止 ConfigMap/Secret 明文存储 API Key（dev 环境豁免） |
| InputGuard | Gateway REST Pod 内中间件，在请求路由到 Runtime 前执行 |
| OutputFilter | Capability 调用链拦截器（代码模块，同进程嵌入） |

---

# 第七章：可观测性集成

| 维度 | 组件 | 部署 | 采集频率 | 保留周期 |
|:-----|:-----|:-----|:--------:|:--------:|
| 日志 | Fluentd → Loki | Sidecar（每个业务 Pod） | 实时 | 30 天 |
| 指标 | Prometheus → Grafana | Operator + ServiceMonitor | 30s | 30 天 |
| 链路追踪 | OTel Agent → Jaeger | Sidecar，gRPC OTLP | 实时 | 7 天 |
| 告警 | AlertManager | Prometheus Operator | — | — |

所有指标标签强制包含 `tenant_id`（Multi-Tenant Spec §7.2）。

---

# 第八章：镜像管理

| 维度 | 策略 |
|:-----|:-----|
| 镜像仓库 | Harbor `harbor.earp.internal/earp/<component>` |
| 标签策略 | `git-commit-sha` (dev)，`semver` (staging/prod：`v1.2.3`) |
| 安全扫描 | Trivy (CI) + Harbor (注册)，阻断 CRITICAL/HIGH CVE |
| 基础镜像 | `python:3.12-slim` / `nginx:alpine` / `envoy:distroless` |

---

# 第九章：多租户部署决策

**选择：共享 K8s 集群 + Namespace 隔离。**

| 因素 | 共享集群 | 独立集群 |
|:-----|:------:|:------:|
| 运维成本 | 低 | 高 |
| 隔离强度 | namespace + NetworkPolicy + RLS | 物理隔离 |
| 资源利用率 | 高 | 低 |
| 合规要求 | 多数企业适用 | 金融/政府高合规场景 |
| 扩展复杂度 | 低（新 namespace） | 高（provision + cert + DNS） |

**取舍**：Phase 1 共享集群 + namespace，满足绝大多数企业。独立集群为 Phase 2 选项。

**Namespace 规划：**
- `earp-system` — 平台组件（Gateway、Istio、cert-manager、Vault）
- `earp-{tenant_id}` — per-tenant（Runtime、Planner、Connector）
- `earp-data` — 共享存储（PG/Redis/S3，RLS + key 前缀隔离）
- `earp-obs` — 可观测性（Prometheus、Loki、Jaeger）
