# PRD-2026-011 v1.1

## EARP 数据架构视图

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-011 |
| **Feature** | L1 数据架构视图——数据域划分、存储选型、实体关系、生命周期、多租户隔离、迁移策略 |
| **优先级** | **P0** |
| **版本** | v1.1 |
| **日期** | 2026-07-15 |

> **v2.1 备注**：该 PRD 描述的数据域划分（八大域）为存储域，与 Concept Model 中 Data Domain 概念无关，Data Domain v2.1 变更对此 PRD 无影响。
---

## 1. 背景

EARP 架构已有 L1 部署视图，缺少对应的数据视图。数据视图是 L1 架构的另一个核心侧面——说明系统数据的组织方式、存储技术选型、实体关系和生命周期管理。

## 2. 范围

### 2.1 覆盖

| 章节 | 内容 |
|:-----|:-----|
| 数据域划分 | 八大域：Runtime / Capability / Governance / Workspace / Security / Knowledge / Conversation / Integration |
| 存储技术选型 | PostgreSQL/pgvector/Redis/S3/Prometheus/Loki 的选型理由与对比 |
| 实体关系图 | 核心 ER 图：Tenant→Session→Execution→CapabilityCall；Capability↔Connector；Policy↔Capability；Audit 引用各域 (entity_type+entity_id) |
| 数据生命周期 | 每类数据 TTL/归档策略/清理方式 + 备份 RPO/RTO（引用 Deployment Architecture §4.3） |
| 多租户隔离 | BaseTenantEntity、RLS、缓存 key 前缀、S3 路径前缀 |
| 数据迁移策略 | Alembic 版本管理、多环境 schema 同步 |

### 2.2 不做（后续）

- 数据库物理调优参数（PG 配置、连接池细节）
- 向量索引调优（HNSW/IVF 参数选择）
- 具体表结构 DDL（L3 实现层）
- 数据一致性模型（强一致 vs 最终一致）、事件溯源、CQRS（独立架构决策）

## 3. 验收条件

| ID | 优先级 | 描述 |
|:--:|:------:|:-----|
| AC-01 | P0 | ER 图至少包含：Tenant→Session→Execution→CapabilityCall 主链路；Capability↔Connector；Policy↔Capability；Audit 通过 entity_type+entity_id 引用各域实体（标注引用方式） |
| AC-02 | P0 | 八大域每域明确：(a) 核心实体，(b) 存储引擎，(c) 关键索引策略 |
| AC-03 | P0 | 每个存储引擎选型附理由（vs 主流替代方案） |
| AC-04 | P1 | 数据生命周期表：每类数据 TTL、归档策略、清理方式，逐条对齐已有规范（Audit Spec/Deployment Arch/Tenant Spec） |
| AC-05 | P1 | 多租户数据隔离方案——每类存储隔离方式与 Tenant Spec v1.1 对齐 |
| AC-06 | P1 | 数据迁移策略：Alembic 版本管理、多环境 schema 同步流程 |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| L1 enterprise-architecture.md | ✅ |
| L1 deployment-architecture-v1.md | ✅ |
| Multi-Tenant Isolation Spec v1.1 | ✅ |
| Security Spec v1.1 | ✅ |
| Audit Spec v1.1 | ✅ |
| EventBus Spec v1.1 | ✅ |

## 5. 产出物

`arch/L1/data-architecture-v1.md` — EARP 数据架构视图（L1）

## 6. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | 六域不对齐企业架构 | 扩展为八大域：+Knowledge、+Conversation、+Integration |
| P0-2 | LLM 错分为独立数据域 | 移除 LLM 域（LLM 数据归入 Execution/审计横切），Knowledge 域承载向量存储 |
| P1-3 | AC-01 "关系" 边界模糊 | 明确 Audit 通过 entity_type+entity_id 引用各域 |
| P1-4 | AC-04 缺对齐锚点 | 逐条引用 Audit Spec(LLM 30d)、Deployment Arch(Prometheus/WAL/快照)、Tenant Spec(配额) |
| P1-5 | 缺 EventBus 依赖 | §4 新增 EventBus Spec v1.1 |
| P1-6 | Knowledge/Vector 域未处理 | 归入独立 Knowledge 域 |
| P2-7 | §2.2 OOS 缺 L1 排除项 | 补充数据一致性模型/事件溯源/CQRS |
| P2-8 | AC 缺优先级 | 标注 P0/P1 分级 |
| P2-9 | AC 编号跳跃 | §6 修复记录补齐 P2-9 |
