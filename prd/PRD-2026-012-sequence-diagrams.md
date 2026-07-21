# PRD-2026-012 v1.0

## EARP 时序图 — 核心交互流

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-012 |
| **Feature** | L1 时序图——7 条核心交互链：执行流、Session 生命周期、认证授权、LLM 安全、Plugin 沙箱、审计事件流、知识查询流 |
| **优先级** | **P0** |
| **版本** | v1.0 |
| **日期** | 2026-07-15 |

---

## 1. 背景

EARP 已有部署视图（组件拓扑）和数据视图（存储组织），缺少时序图——说明组件间"谁在什么时候调用谁"。时序图是 L1 架构三角的最后一块拼图。

## 2. 范围

### 2.1 覆盖 — 7 条交互链

| # | 名称 | 涉及组件 | 覆盖关注点 |
|:-:|:-----|:---------|:-----|
| 1 | 核心执行流 | User→Gateway→Runtime→Planner→Capability→Connector→External | JWT 认证、Session、Execution、Policy、Audit |
| 2 | Session 生命周期 | User→Gateway→Runtime | create/invoke/close、tenant_id 传播、TTL |
| 3 | 认证与授权流 | User→Gateway→Runtime→Policy Center | JWT 验证、tenant_id 提取、RBAC |
| 4 | LLM 安全流 | User→InputGuard→LLM→OutputFilter→Capability | 注入检测、sanitize、PII/代码检测 |
| 5 | Plugin 沙箱流 | PluginManager→SandboxManager→subprocess | 权限检查、JSON 序列化、超时/killpg、审计 |
| 6 | 审计事件流 | 各域→EventBus→Audit Service→PG→S3 | 事件发布/订阅、热存储/冷归档 |
| 7 | 知识查询流（v2.1 新增） | User→Runtime→Planner（Domain Routing）→Data Domain→Knowledge Center→RAG→LLM 综合回答 | 二维 Domain Routing、纯知识查询跳过 Execution Runtime、Data Domain 过滤、data_classification 授权检查 |

### 2.2 不做（后续）

- WebSocket 实时推送的时序
- 跨区域容灾切换时序
- Workflow Engine 节点执行详细时序

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | 7 张时序图覆盖全部交互链，每张图标注组件角色和消息方向 |
| AC-02 | 核心执行流覆盖：JWT 验证 → Session 创建 → Plan 生成 → Capability 调用 → Connector → 外部系统 → 结果返回 |
| AC-03 | 每张图至少标注 1 个审计事件发布点（Audit Spec §6.2 安全事件） |
| AC-04 | 时序图与已有规范一致——Security Spec、Multi-Tenant Spec、Audit Spec、Runtime Spec |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| L1 deployment-architecture-v1.md | ✅ |
| L1 data-architecture-v1.md | ✅ |
| L2-01-RUNTIME v1.2 | ✅ |
| L2-06-SECURITY v1.1 | ✅ |
| L2-05-AUDIT v1.1 | ✅ |
| L2-07-TENANT v1.1 | ✅ |

## 5. 产出物

`arch/L1/sequence-diagrams-v1.md` — EARP 时序图（L1）
