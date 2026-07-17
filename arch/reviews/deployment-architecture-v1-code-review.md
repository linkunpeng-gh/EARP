Permission allow rule (.claude/settings.local.json): Write(/Users/linkunpeng/work/adp2/**) is not matched by file permission checks — only Edit(path) rules are. Use Edit(/Users/linkunpeng/work/adp2/**) instead (Edit rules cover all file-editing tools).
现在我已拥有所有参考文档。让我进行系统化审查。

---

# EARP 部署架构视图 v1.0 — 审查报告

**文档**：`arch/L1/deployment-architecture-v1.md`  
**审查基准**：PRD-2026-010 v1.2 验收条件 + 交叉引用 Enterprise Architecture / Multi-Tenant Spec v1.1 / Security Spec v1.1 / Observation Spec v1.0  
**审查日期**：2026-07-17

---

## 验收条件逐项检查

### AC-01：拓扑图 7 要素

| 要素 | 状态 | 说明 |
|:-----|:----:|:-----|
| (a) 核心业务组件 | ✅ | Runtime、Planner、Capability Registry、Policy Center、Audit Service、Knowledge Base、Workflow Engine 均已呈现 |
| (b) 所有数据存储 | ✅ | PostgreSQL、Redis、S3/MinIO、Message Bus/RabbitMQ 均已呈现 |
| (c) Gateway/Ingress | ✅ | REST Gateway (Nginx)、WebSocket Gateway (SocketIO)、gRPC Gateway (Envoy)、TLS Termination 层均已呈现 |
| (d) 网络策略边界 | ❌ | **拓扑图中未显式标注 NetworkPolicy 边界**。文中第六章以文字描述了 NetworkPolicy，但图中无线框/虚线/颜色标识策略边界 |
| (e) 外部依赖连接点 | ✅ | Connector Egress 区域列出了 LLM API、企业系统 (SAP/MES/ERP)、Vault/KMS |
| (f) 图例 | ❌ | **拓扑图无图例**。组件形状（矩形/圆角/虚线框）各自含义未说明 |
| (g) 可观测性采集点 | ✅ | Sidecar 区域标注了 Fluentd → Loki、Prometheus Exporter → Prometheus、OTel Agent → Jaeger |

**AC-01 判定：❌ 不通过**——缺少 (d) 和 (f)。

---

### AC-02：组件规格

| 子项 | 状态 | 说明 |
|:-----|:----:|:-----|
| 副本数 | ⚠️ | §1.2 列出 17 个组件含副本数，但 **§2.1 资源表仅覆盖 12 个**。缺失：WebSocket Gateway、gRPC Gateway、Policy Center、Audit Service、Knowledge Base、Workflow Engine、Connector Daemon、Plugin gRPC Daemon |
| 资源 request/limit | ⚠️ | 同上——缺失组件无资源规格 |
| HPA 策略 | ⚠️ | §2.1 部分组件标注 HPA，缺失组件无 HPA |
| 存储挂载 | ⚠️ | §2.1 仅 stateful 组件有存储挂载，正确；但缺失的 stateful/non-stateful 组件无从评估 |
| Pod 反亲和 | ✅ | §2.2 统一声明 `requiredDuringSchedulingIgnoredDuringExecution` |
| 跨 AZ 分布 | ✅ | §2.2 `topologySpreadConstraints` maxSkew=1, DoNotSchedule |
| PDB 配置 | ✅ | §2.2 区分了 ≥2 副本组件和 PostgreSQL Primary |
| 节点池类型 | ⚠️ | §1.2 已标注节点池列，但 Workflow Engine 未出现在 §1.2 中（仅在拓扑图中出现） |
| LLM 并发控制 | ✅ | §2.3 完整（并发上限、排队策略 FIFO 120s、超时 HTTP 429 + Retry-After） |

**AC-02 判定：❌ 不通过**——§1.2 与 §2.1 存在组件覆盖缺口（8 个组件缺资源规格）。

---

### AC-03：网络通信矩阵

| 方向 | 状态 | 说明 |
|:-----|:----:|:-----|
| Ingress 入口 | ✅ | §3.2 覆盖 `/api/*`、`/ws/*`、`/grpc/*`、`/health` |
| 东西向（E-W） | ⚠️ | §3.1 矩阵覆盖了核心路径，但**缺失以下通信关系**：Runtime → Knowledge Base、Runtime → Audit Service、Runtime → Workflow Engine、Policy Center ↔ 各组件的策略评估路径、Gateway → Planner（或明确标注经过 Runtime 代理） |
| Connector Egress | ✅ | §3.3 白名单策略覆盖 |
| 协议+端口 | ✅ | 现有的矩阵每行均有协议和端口 |

**AC-03 判定：⚠️ 基本通过，存在缺失路径**——东西向通信矩阵不完整。

---

### AC-04：环境差异表

| 维度 | 状态 | 说明 |
|:-----|:----:|:-----|
| 集群规模 | ✅ | 明确（节点数 + 资源量级） |
| 密钥源 | ✅ | dev=环境变量, staging=Vault(dev), prod=Vault(HA)+KMS |
| 数据保留 | ✅ | 7/30/90 天明确 |
| 网络隔离度 | ✅ | 逐级递增（无VPC → 独立VPC+NetworkPolicy → +WAF） |
| 外部依赖真实度 | ✅ | Mock → Staging沙箱 → 生产系统 |
| 日志级别 | ✅ | DEBUG/INFO/WARN |
| 资源 request | ⚠️ | 行内容为"见 §2.1"，但 **§2.1 仅给 prod 值**。dev 的"1/4"、staging 的"1/2"基准不明确——是 CPU request 的 1/4 还是所有资源的 1/4？ |

**AC-04 判定：⚠️ 基本通过**——资源 request 的 dev/staging 值需明确计算基准或独立列出。

---

### AC-05：多租户部署决策

| 子项 | 状态 | 说明 |
|:-----|:----:|:-----|
| 选择明确 | ✅ | "共享 K8s 集群 + Namespace 隔离" |
| 分析理由 | ✅ | 运维成本低、资源利用率高、扩展简单 |
| 取舍（tradeoff） | ✅ | 对比表覆盖 5 个维度，Phase 1/2 路线明确 |
| Namespace 规划 | ✅ | `earp-system`、`earp-{tenant_id}`、`earp-data`、`earp-obs` |

**AC-05 判定：✅ 通过。**

---

### AC-06：镜像管理

| 子项 | 状态 | 说明 |
|:-----|:----:|:-----|
| (a) 镜像仓库地址 | ✅ | `harbor.earp.internal/earp/<component>` |
| (b) 标签策略 | ✅ | git-commit-sha (dev) / semver (staging/prod) |
| (c) 安全扫描 | ✅ | Trivy (CI) + Harbor (注册阶段)，阻断 CRITICAL/HIGH CVE |

**AC-06 判定：✅ 通过。**

---

### AC-07：备份 RPO/RTO

| 存储 | RPO | RTO | 方法 | 状态 |
|:-----|:---:|:---:|:-----|:----:|
| PostgreSQL | 5 min | 30 min | WAL 连续归档 + 每日快照 | ✅ |
| Redis | 1 h | 15 min | RDB + AOF | ✅ |
| S3/MinIO | 0（实时） | 4 h | 跨 Bucket 实时复制 | ✅ |
| RabbitMQ | 24 h | 2 h | 配置导出 + 消息日志导出 | ✅ |
| Prometheus | 24 h | 4 h | 远程写入 S3 | ✅ |

**AC-07 判定：✅ 通过。**

---

## AC 汇总

| AC | 状态 |
|:---|:----:|
| AC-01 | ❌ 拓扑图缺网络策略边界 + 图例 |
| AC-02 | ❌ §2.1 缺 8 个组件的资源/HPA 规格 |
| AC-03 | ⚠️ 东西向通信矩阵不完整 |
| AC-04 | ⚠️ dev/staging 资源 request 基准不明确 |
| AC-05 | ✅ |
| AC-06 | ✅ |
| AC-07 | ✅ |

---

## 问题分优先级

### P0 — 阻断（AC 不通过，必须修复）

| # | 类别 | 问题 | 依据 |
|:--|:-----|:-----|:-----|
| **P0-1** | AC-01 阻断 | **拓扑图缺少 (d) 网络策略边界 和 (f) 图例**。拓扑图中看不到 NetworkPolicy 边界的可视化标注（如虚线框、颜色区分、安全域边界线），且无图例说明各类形状/线条的含义。PRD AC-01 明确要求这两个元素。 | PRD §3 AC-01 |
| **P0-2** | AC-02 阻断 | **§2.1 组件资源规格表与 §1.2 组件分布表严重不一致**。§1.2 列出 17 个组件，但 §2.1 仅覆盖 12 个。以下 8 个组件缺少 resource request/limit 和 HPA 策略：WebSocket Gateway、gRPC Gateway、Policy Center、Audit Service、Knowledge Base、Workflow Engine、Connector Daemon、Plugin gRPC Daemon。PRD 要求"每类组件"均明确。 | PRD §3 AC-02 |
| **P0-3** | 内部矛盾 | **Workflow Engine 出现在拓扑图中，但在 §1.2 组件分布表中缺失**。该组件与 §2.1 也未覆盖，造成三重不一致。 | 文档内部一致性 |

### P1 — 重要（影响规范对齐或完整性）

| # | 类别 | 问题 | 依据 |
|:--|:-----|:-----|:-----|
| **P1-1** | Security Spec 交叉引用缺失 | **InputGuard 和 OutputFilter 未出现在部署拓扑中**。Security Spec v1.1 §4.1 明确定义 InputGuard 为 Gateway 层中间件、OutputFilter 为 Capability 链拦截器——这两个是安全架构中的显式组件，部署视图应标注其部署位置（是否作为 Gateway Sidecar、独立 Pod、还是以代码模块嵌入）。 | Security Spec §4.1 |
| **P1-2** | Enterprise Architecture 交叉引用缺失 | **MCP Server (`interfaces/mcp/`) 未出现在部署拓扑中**。Enterprise Architecture 中 MCP Server 是独立接口适配器，与 REST/WebSocket/gRPC 平级。部署视图应明确 MCP Server 是否复用 Gateway 还是独立部署。 | Enterprise Architecture §interfaces/mcp |
| **P1-3** | AC-03 完整性 | **东西向通信矩阵不完整**。缺失路径至少包括：Runtime → Knowledge Base（RAG 检索调用）、Runtime → Audit Service（审计日志写入）、Runtime → Workflow Engine（流程执行编排）、Policy Center → 各被保护组件（策略评估回调）。建议对照 Enterprise Architecture 中 Application 层各 use case 的依赖关系补全。 | PRD §3 AC-03 |
| **P1-4** | Security Spec 对齐 | **TLS 版本未指定**。Security Spec v1.1 §3.1 明确要求 TLS 1.3，但部署文档仅说"TLS 在 Gateway 终止"和"cert-manager 自动管理证书"，未明确 TLS 最低版本。 | Security Spec §3.1 |
| **P1-5** | AC-04 明确性 | **dev/staging 环境的资源 request 基准不明确**。§5.1 环境表中"资源 request"行写"见 §2.1"，但 §2.1 只给出 prod 值。dev 的"1/4"和 staging 的"1/2"是指所有资源（CPU request/limit + Mem request/limit）统一缩放？还是仅 CPU？需要明确。 | PRD §3 AC-04 |
| **P1-6** | Security 策略矛盾 | **dev 环境密钥注入方式与 §6 安全策略存在潜在矛盾**。§6 规定"禁止 ConfigMap/Secret 明文存储 API Key——通过 Vault Agent Injector 注入"，但 §5.1 dev 环境"密钥源"为"环境变量直接注入"。需明确 dev 环境是否豁免此安全策略，以及豁免边界。 | 文档 §5.1 vs §6 |

### P2 — 建议（改进完整性和清晰度）

| # | 类别 | 问题 | 建议 |
|:--|:-----|:-----|:-----|
| **P2-1** | Observation Spec 对齐 | 部署文档未指定 **Prometheus 采集频率**（Obs Spec 要求 30s）和**指标保留期**（Obs Spec 要求 30 天）。§7 可观测性集成表建议增加"采集频率"和"保留周期"两列。 | Observation Spec §2.2 |
| **P2-2** | 端口冲突风险 | §3.1 通信矩阵中 **Gateway → Runtime gRPC 端口 9090** 与 **Prometheus → Exporter HTTP 端口 9090** 使用了相同端口号。如果 Runtime Pod 的 gRPC 服务和 Prometheus Exporter Sidecar 都在同一 Pod 内，会发生端口冲突。建议将 Prometheus Exporter 端口改为非标准端口（如 9099），或明确说明两者位于不同 Pod/不同网络命名空间。 | 文档 §3.1 |
| **P2-3** | Enterprise Architecture 对齐 | Enterprise Architecture 支持多向量数据库（pgvector/qdrant/milvus），部署仅部署了 pgvector。建议在部署文档中标注：Phase 1 使用 pgvector，Phase 2 可选扩展 qdrant/milvus。 | Enterprise Architecture adapters/vector_stores |
| **P2-4** | Enterprise Architecture 对齐 | Enterprise Architecture 消息总线适配器包含 Kafka/RabbitMQ/MQTT/Redis Streams，部署仅使用 RabbitMQ。建议简要说明选型理由，并标注 Kafka 为 Phase 2 选项。 | Enterprise Architecture adapters/message_bus |
| **P2-5** | 备份完整性 | §4.3 备份策略未提及**备份本身的保留周期**（如 WAL 归档保留多久、每日快照保留几个版本）。建议增加"备份保留"列。 | 文档 §4.3 |
| **P2-6** | 亲和性策略过于严格 | §2.2 中 Pod 反亲和使用 `requiredDuringSchedulingIgnoredDuringExecution`。对于部分组件（如 2 副本的 Capability Registry），如果集群节点数 < 副本数，会导致 Pod 永久 Pending。建议对非关键组件降级为 `preferredDuringSchedulingIgnoredDuringExecution`。 | 文档 §2.2 |
| **P2-7** | 节点池规格缺失 | §5.1 环境表给出了节点数（dev=3、staging=5、prod=9），但未说明各节点池的实例规格（如 frontend 池用 4C8G、backend 池用 8C16G）。增加实例规格信息有助于成本估算和容量规划。 | 文档 §5.1 |
| **P2-8** | Istio mTLS 与 Prometheus 抓取兼容性 | §3.1 中 Prometheus 使用 HTTP 直接抓取 Exporter（端口 9090），但 §6 要求 Istio mTLS 覆盖服务间通信。Prometheus 抓取是否豁免 mTLS 需明确说明，否则抓取将因 TLS 握手失败而中断。 | 文档 §3.1, §6 |

---

## 交叉引用一致性矩阵

| 被引用规范 | 关键交叉点 | 一致性 |
|:-----------|:----------|:------:|
| **Enterprise Architecture** | 业务组件映射、MCP Server、多向量数据库、多消息总线 | ⚠️ MCP Server 缺失；仅 pgvector/RabbitMQ |
| **Multi-Tenant Spec v1.1** | tenant_id 传播链、缓存 key 前缀、S3 路径前缀、Metrics 标签 | ✅ 所有交叉点一致 |
| **Security Spec v1.1** | TLS 终端 + mTLS + cert-manager、Vault/KMS、429+Retry-After、Plugin 沙箱 | ⚠️ TLS 版本未指定；InputGuard/OutputFilter 未在拓扑中体现 |
| **Observation Spec v1.0** | Prometheus + Fluentd + OTel → Jaeger、AlertManager | ⚠️ 采集频率和保留期未注明 |

---

## 总结

| 类别 | 数量 | 关键项 |
|:-----|:----:|:------|
| P0（阻断） | 3 | 拓扑图缺图例和网络策略边界；§2.1 缺 8 个组件规格；Workflow Engine 表图不一致 |
| P1（重要） | 6 | InputGuard/OutputFilter 缺失；MCP Server 缺失；通信矩阵不完整；TLS 版本缺失；资源基准不明确；dev 安全策略矛盾 |
| P2（建议） | 8 | 端口冲突风险；亲和性过严；Obs 参数缺失；备份保留周期；节点池规格；向量数据库扩展；消息总线选项；Istio+Prometheus 兼容性 |

**总体评价**：文档在 AC-05（多租户决策）、AC-06（镜像管理）、AC-07（备份策略）三方面完成度高。核心缺陷集中在 **AC-01 拓扑图完整性和 AC-02 组件规格覆盖度**——这两项直接阻断 PRD 验收。建议优先修复 P0-1（补充图例+标注网络策略边界）和 P0-2（补全 §2.1 中 8 个缺失组件的资源规格），再依次处理 P1 层的交叉引用缺口。
