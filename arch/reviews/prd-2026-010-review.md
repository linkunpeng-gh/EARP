Permission allow rule (.claude/settings.local.json): Write(/Users/linkunpeng/work/adp2/**) is not matched by file permission checks — only Edit(path) rules are. Use Edit(/Users/linkunpeng/work/adp2/**) instead (Edit rules cover all file-editing tools).
Now I have all the context needed for a thorough review. Let me compile the analysis.

---

# PRD-2026-010 部署架构视图 — 结构化评审

## 总体评价

PRD 对 L1 部署架构视图的范围界定清晰，七个维度选取得当，AC 主要可测。但 **Security Spec 依赖版本声明与实际文件名不一致**（P0），且缺少容灾/备份/可观测性基础设施集成点这几个对部署视图至关重要的维度（P1）。

---

## P0（必须修复，阻塞）

### P0-1: Security Spec 依赖版本声明与文件名不匹配

- **问题**: PRD 第 4 节声明依赖 `Security Spec v1.1`，但仓库中实际文件名为 `security-specification-v1.md`（不含 v1.1 后缀）。文件头部声明版本为 v1.1，但文件名仍是 v1。这会让读者困惑——究竟是引用 v1 还是 v1.1？
- **建议**: 确认 Security Spec 的正式版本号。如果确实是 v1.1，建议文件名同步更新为 `security-specification-v1.1.md`，或至少在 PRD 中注明 "Security Spec v1.1（文件路径: `arch/L2/06-security/security-specification-v1.md`，文档头部版本为 v1.1）"以避免歧义。

### P0-2: AC-05 将设计决策预设为验收条件，削弱 AC 的验证语义

- **问题**: AC-05 写的是 "多租户部署选择明确：共享 K8s 集群 + namespace 隔离，附理由"。这句话把答案（共享集群 + namespace）写进了验收条件——验收条件应该验证**是否做出了选择并附有理由**，而不是**选了什么**。当前写法：如果最终设计分析后认为独立实例更合适，这条 AC 会 failed，但这是设计质量失败而非验收失败。
- **建议**: 改为 `"多租户部署选择明确（共享集群 vs 独立实例），附分析理由与取舍"`——让 AC 验证产出物的决策质量，而非预设答案。

### P0-3: AC-01 "完整" 一词无定义，不可客观验证

- **问题**: "完整的一张 K8s 集群拓扑图"——什么是"完整"？缺了 Ingress Controller 算不算不完整？缺了 ServiceAccount/RBAC 配置算不算？没有明确的标准，验收时 reviewer 和 author 对"完整"的理解可能完全不同。
- **建议**: 明确拓扑图至少应包含的元素：(a) 核心业务组件，(b) 所有数据存储，(c) Gateway/Ingress，(d) 网络策略边界，(e) 外部依赖连接点，(f) 图例。或者拆成 AC-01a: "包含所有核心组件的拓扑图" + AC-01b: "图中标注了组件间通信关系"。

---

## P1（应该修复）

### P1-1: 缺少容灾/高可用维度

- **问题**: 范围 2.2 将"灾备/多活架构"标记为 Phase 2 不做，但 AC-02 要求明确副本数——副本数本身暗示了高可用。如果不在范围中涉及基本的 HA 策略（如 pod anti-affinity、跨 AZ 分布、PDB），那么副本数只是一个数字，缺乏实际的部署意义。"
灾备/多活"（geo-redundancy）和"单集群高可用"（HA within a single cluster）是两个不同层面，不应混为一谈。
- **建议**: 在范围中增加"单集群高可用（pod 反亲和、跨 AZ、PDB）"，与 Phase 2 的"灾备/多活"区分开。

### P1-2: 缺少数据备份与恢复集成点

- **问题**: 范围提到 PostgreSQL、Redis、S3 的物理部署，但没有提到备份策略。PostgreSQL 的 WAL 归档、Redis 的 RDB/AOF 持久化、S3 的跨区域复制——这些都是部署视图必须考虑的。即使不要求写完整的备份方案，至少应该标注"标注备份集成点"。
- **建议**: 在范围中增加一项 "数据备份（标注各存储的备份策略与 RPO/RTO 目标，详细方案独立文档）"。

### P1-3: 缺少可观测性基础设施集成点

- **问题**: 2.2 不做中说"监控告警配置（Observation Spec 已有，部署视图只标注集成点）"——但范围表中并没有对应的行来标注这个集成点。日志收集器（Fluentd/Loki）、指标采集（Prometheus）、链路追踪（Jaeger/Tempo）的部署位置应该在拓扑图中体现。
- **建议**: 在范围中增加 "可观测性集成（Prometheus 采集点、日志收集 Sidecar、Trace 后端标注）" 一行。

### P1-4: 缺少容器镜像管理

- **问题**: K8s 部署的核心依赖是容器镜像，但 PRD 中没有提到镜像仓库、镜像扫描、镜像标签策略。这些是部署架构的基础。
- **建议**: 在范围中增加 "镜像管理（镜像仓库、标签策略、镜像安全扫描）"，或在 2.2 不做中明确标出（如果打算在 CI/CD PRD 中覆盖的话）。

### P1-5: AC-02 未覆盖 LLM 并发控制的具体要求

- **问题**: 范围 §2.1 中明确写了"LLM 并发控制"，但 AC-02 只覆盖了"副本数、资源 request/limit、HPA 策略、存储挂载"，没有提到 LLM 并发控制的验证标准。这个重要维度在 AC 层面是空白的。
- **建议**: 增加 AC-02a: "LLM 并发控制策略明确（并发上限、排队策略、超时处理）" 或在 AC-02 中补充相关要求。

### P1-6: NetworkPolicy 缺少 Egress 控制

- **问题**: AC-03 的"组件间通信矩阵（谁可以调谁、协议、端口）"只覆盖了东西向流量（组件间），没有覆盖南北向——尤其是 Connector 的 Egress 出口（连接到外部 SAP/MES/ERP 系统的流量）。这对于企业部署至关重要，因为安全团队会要求 Egress 白名单。
- **建议**: 在 AC-03 中补充"包含 Gateway Ingress 和 Connector Egress 的网络策略"。

---

## P2（锦上添花）

### P2-1: 缺少对 Plugin 沙箱部署模型的考虑

- **问题**: Security Spec §7 定义了 Plugin 沙箱的三个 Phase（Process → Sandbox → WASM），对应的部署模型差异很大——子进程隔离需要额外的 gRPC sidecar，WASM 需要特定 runtime。部署视图不一定要给出最终方案，但应该在拓扑中标注 Plugin 的执行边界。
- **建议**: 在基础设施拓扑中增加"Plugin 执行环境（当前 Phase: Process 隔离，gRPC Daemon 部署位置）"。

### P2-2: 缺少成本/规模估算维度

- **问题**: L1 架构视图通常包含规模参考——至少给出 dev/staging/prod 的节点数、预期 QPS、存储量级的数量级估算。这对后续 PRD（如 CI/CD、监控）提供了关键的输入。
- **建议**: 在环境策略或产出物中增加"各环境规模参考（节点数/预期 QPS/存储量级）"。

### P2-3: 缺少数仓/分析型数据存储

- **问题**: 范围只提到 PostgreSQL、Redis、S3、向量数据库，但架构中的审计日志、Metrics 时序数据、分析报表需要数据仓库或时序数据库作为支撑。Enterprise Architecture 中有 `domain/audit/` 和 `domain/report/`，部署视图应标注审计存储的物理部署位置。
- **建议**: 在数据存储部署中增加"审计/分析存储（如 ClickHouse/TimescaleDB/ELK）的标注"，即使标注为"复用 PostgreSQL，Phase 2 拆分"也行。

### P2-4: AC-04 可以增加环境间差异的检查维度

- **问题**: AC-04 目前检查"规模、密钥源、数据保留"三项差异。还可以补充：(a) 网络隔离度（dev/staging 是否在同一 VPC）、(b) 外部依赖真实度（staging 对接 mock 还是真实 SAP）、(c) 日志级别差异。
- **建议**: 根据实际情况选择性补充。

### P2-5: 缺少对 Message Bus 部署拓扑的明确覆盖

- **问题**: Enterprise Architecture 中有 `adapters/message_bus/`（Kafka/RabbitMQ/MQTT/Redis Streams），网络拓扑提到"gRPC/HTTP 通信"，但未明确 Message Bus 是作为 K8s 集群内组件部署还是外部托管服务。这对于部署决策很重要。
- **建议**: 在基础设施拓扑或网络拓扑中明确 Message Bus 的部署位置。

---

## 对齐检查表

| 依赖文档 | 对齐状态 | 说明 |
|:---------|:--------:|:-----|
| **L1 enterprise-architecture.md** | ✅ 对齐 | PRD 的七维度覆盖了 Enterprise Architecture 中的组件拓扑需求。`kernel/`、`domain/` 各模块的部署形态将在产出物中体现。缺少对 `adapters/message_bus/` 的部署拓扑标注（见 P2-5）。 |
| **L1 dify-hexagonal-architecture.md** | ✅ 对齐 | 六边形架构的 Port/Adapter 模式要求清晰的组件边界——这与 AC-03 的网络策略矩阵一致。Dify 架构中的 `bootstrap/extensions/`（Redis、Celery、SocketIO、OTel）对应的物理部署应在产出物中覆盖。 |
| **Multi-Tenant Isolation Spec v1.1** | ⚠️ 部分对齐 | **已覆盖**: namespace 隔离（§2.1）、共享集群选择（AC-05）。**未覆盖**: (a) RLS 作为第二道防线是否需要数据库配置（§5.1）；(b) 缓存 key tenant_id 前缀是否需要 Redis namespace 规划（§5.2）；(c) 文件存储 tenant_id 前缀是否需要 S3 bucket/prefix 规划（§5.3）；(d) LLM API Key per-tenant 存储（§4.3）需要 Vault/KMS 的对应配置。 |
| **Security Spec v1.1** | ⚠️ 部分对齐 | **已覆盖**: TLS 终端、Vault/KMS、网络策略（§2.1）。**未覆盖**: (a) Plugin 沙箱的部署模型（§7——Process/gRPC 隔离 vs WASM 对部署拓扑有不同影响）；(b) mTLS 服务间通信（§2.1——如果启用 mTLS，需要 cert-manager + Istio/Consul 的支持，应在安全边界中体现）；(c) InputGuard 作为 Gateway 中间件的部署位置（§4.1——应在网络拓扑中标注）。 |
| **Observation Spec**（未列出但相关） | ❌ 缺依赖 | PRD 2.2 不做中明确提到 "Observation Spec 已有，部署视图只标注集成点"，但没有将 Observation Spec 列入依赖表。建议补充，因为集成点的标注需要参考该规范的 Metrics/Trace/Log 输出格式。 |

---

## 总结

| 类别 | 数量 | 要点 |
|:-----|:----:|:-----|
| P0 | 3 | Security Spec 文件名不一致、AC-05 预设答案、AC-01 "完整"无定义 |
| P1 | 6 | 缺 HA、备份、可观测性集成点、镜像管理、LLM 并发 AC、Egress 策略 |
| P2 | 5 | Plugin 沙箱部署、成本估算、审计存储、环境差异补充、Message Bus 拓扑 |
| 对齐全绿 | 2/5 | Enterprise Architecture 和 Dify Architecture 对齐良好；Tenant/Security Spec 部分缺失；Observation Spec 缺依赖声明 |
