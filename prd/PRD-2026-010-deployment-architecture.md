# PRD-2026-010 v1.1

## EARP 部署架构视图

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-010 |
| **Feature** | L1 部署架构视图——基础设施拓扑、网络、存储、扩缩容、环境策略 |
| **优先级** | **P0** |
| **版本** | v1.2 |
| **日期** | 2026-07-15 |

---

## 1. 背景

EARP 架构文档当前覆盖了四层治理（L0 理念 → L1 架构 → L2 规范 → L3 产品需求），但缺少部署视图。部署视图是 L1 架构的核心组成部分——说明系统各组件的运行拓扑、网络通信、存储部署和扩缩容策略。

## 2. 范围

### 2.1 覆盖

| 章节 | 内容 |
|:-----|:-----|
| 基础设施拓扑 | K8s 集群结构、组件分布、节点池、Message Bus 部署位置 |
| 多租户部署模型 | 共享集群 vs 独立实例、namespace 隔离 |
| 网络拓扑 | Gateway、Service Mesh、gRPC/HTTP 通信、Connector Egress 出口、Ingress 入口 |
| 数据存储部署 | PostgreSQL、Redis、S3、向量数据库、审计/分析存储的物理部署；备份集成点标注（RPO/RTO 目标） |
| 扩缩容策略 | HPA（无状态）、有状态约束、LLM 并发控制（并发上限、排队策略） |
| 单集群高可用 | Pod 反亲和、跨 AZ 分布、PDB |
| 环境策略 | dev/staging/prod 三套环境差异；dev/staging 网络隔离度、外部依赖真实度、日志级别 |
| 安全边界 | TLS 终端、Vault/KMS、mTLS（如需）、InputGuard Gateway 中间件部署位置 |
| 可观测性集成 | Prometheus 采集点、日志收集 Sidecar（Fluentd）、Trace 后端（Jaeger/Tempo）标注 |
| 镜像管理 | 镜像仓库、标签策略、镜像安全扫描 |

### 2.2 不做（后续）

- CI/CD 流水线具体实现（独立 PRD）
- 灾备/多活架构（Phase 2）
- 监控告警规则配置（Observation Spec 已有，部署视图只标注采集点）

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | 拓扑图至少包含：(a) 核心业务组件，(b) 所有数据存储，(c) Gateway/Ingress，(d) 网络策略边界，(e) 外部依赖连接点，(f) 图例，(g) 可观测性采集点（Prometheus 抓取端点、Fluentd Sidecar、Trace 导出目标）。组件间通信关系标注清晰 |
| AC-02 | 每类组件明确：副本数、资源 request/limit、HPA 策略、存储挂载、Pod 反亲和规则、跨 AZ 分布策略、PDB 配置。无状态组件标注所属节点池类型。LLM 并发控制策略明确（并发上限、排队策略、超时处理） |
| AC-03 | 网络策略表：组件间通信矩阵（Ingress 入口 + 东西向 + Connector Egress 出口），含协议和端口 |
| AC-04 | 环境表：dev/staging/prod 三套环境的差异——集群规模（节点数/资源总量）、密钥源、数据保留、网络隔离度、外部依赖真实度、日志级别 |
| AC-05 | 多租户部署选择明确（共享集群 vs 独立实例），附分析理由与取舍 |
| AC-06 | 镜像管理策略明确：(a) 镜像仓库地址，(b) 标签策略（git-commit / semver），(c) 安全扫描流程（扫描工具、阻断策略） |
| AC-07 | 每个有状态数据存储标注备份集成点：(a) RPO 目标，(b) RTO 目标，(c) 备份方式（快照/逻辑导出/连续归档） |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| L1 enterprise-architecture.md | ✅ |
| L1 dify-hexagonal-architecture.md | ✅ |
| Multi-Tenant Isolation Spec v1.1 | ✅ |
| Security Spec v1.1（`arch/L2/06-security/security-specification-v1.md`） | ✅ |
| Observation Spec（`arch/L2/05-governance/observation-specification.md`） | ✅ |

## 5. 产出物

`arch/L1/deployment-architecture-v1.md` — EARP 部署架构视图（L1）

## 6. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | Security Spec 文件名不一致 | §4 依赖表标注实际文件路径 |
| P0-2 | AC-05 预设答案为共享集群 | 改为"明确选择 + 附分析理由与取舍" |
| P0-3 | AC-01 "完整"无定义 | 拆为 6 个具体元素 |
| P1-1 | 缺单集群 HA | §2.1 新增独立维度（pod 反亲和、AZ、PDB） |
| P1-2 | 缺数据备份 | §2.1 数据存储增加"备份集成点标注（RPO/RTO 目标）" |
| P1-3 | 缺可观测性集成点 | §2.1 新增独立维度（Prometheus/Fluentd/Jaeger） |
| P1-4 | 缺镜像管理 | §2.1 新增独立维度（仓库/标签/扫描） |
| P1-5 | LLM 并发 AC 缺失 | AC-02 补充 LLM 并发控制验证标准 |
| P1-6 | 缺 Egress 控制 | AC-03 补充 Ingress + Egress |
| P2-1 | Plugin 沙箱部署模型 | 留 Phase 2，当前标注为 Process 隔离 |
| P2-2 | 成本/规模估算 | AC-04 环境表包含规模参考 |
| P2-3 | 缺审计/分析存储 | §2.1 数据存储增加审计/分析存储标注 |
| P2-4 | AC-04 环境差异不完整 | AC-04 增加网络隔离度/外部依赖真实度/日志级别 |
| P2-5 | Message Bus 拓扑缺失 | §2.1 基础设施拓扑包含 Message Bus 部署位置 |
| — | Scope-AC 闭环缺口 (P1-A~D) | 新增 AC-06（镜像管理）、AC-07（备份 RPO/RTO）；AC-01 补充可观测性元素 (g)；AC-02 补充 HA（亲和性/AZ/PDB/节点池）；AC-04 明确"规模"为"集群规模（节点数/资源总量）" |
