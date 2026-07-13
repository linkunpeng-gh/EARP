# Phase 1 — 架构影响分析报告

## PRD-2026-001：Capability SDK（Python）

| 字段 | 值 |
|------|-----|
| **Feature** | Capability SDK（Python 第一版） |
| **PRD 版本** | v1.1 |
| **分析人** | Arch Agent |
| **日期** | 2026-07-12 |
| **状态** | ✅ 无 L1 架构影响 |

---

## 1. 影响判定

### 是否影响 L1 架构？❌ 否

| 判定维度 | 分析 | 结论 |
|---------|------|:----:|
| L0 设计哲学 | SDK 遵循所有 9 条理念：Runtime First / Capability First / CQRS / Reason-Act 解耦 / 规范即契约 | 不变 |
| L1 三层架构（Reasoning / Execution / Coordination） | SDK 不改变三引擎边界。Capability SDK 是对 L2-03 规范的**实现层**，属于 Capability 域的内部细化 | 不变 |
| L1 六域职责 | SDK 归属 SDK/API 域，不影响其他 5 域的边界 | 不变 |
| L2 规范层次 | SDK 不修改 L2-03 的任何 MUST 条款，仅新增 SDK 级别的 SDKMUST | 不变 |

### 2. 关键原因

Capability SDK 定位是 **L3 实现层**，输出的是**可安装的 Python 包**，不是架构文档变更。它解决的问题是"开发者怎么用 Capability"，不是"Capability 是什么"。L2-03 已经冻结了这个问题的答案。

具体来看：

| L2-03 定义 | SDK 实现 | 关系 |
|-----------|---------|:----:|
| 三层结构（Definition / Execution Contract / Policy） | Packager 自动生成该结构 | 实现，不修改 |
| Resolution Engine 是唯一入口 | SDK 注册端推送 Capability 到此引擎，不绕过 | 对齐 |
| Registry API 接口 | SDK 注册/发现客户端对接这些接口 | 客户端，不改变服务端 |
| Connector 规范 | SDK 的 ctx.connectors 提供接口抽象 | 接口抽象，不实现 |

### 3. 唯一新增架构决策

SDK 引入了一个 L1 层面未显式定义的新概念：**跨 Capability 调用**（`ctx.capabilities.invoke()`）。

虽然 L2-03 的 Capability Graph 定义了关系类型（depends_on / composes / substitutes 等），但**没有定义 Capability 运行时调用另一个 Capability 的机制**。

**决策：**
- SDK 的 `invoke()` 在 MockRuntime 做简化直接分发，在真实 Runtime 经过 Resolution Engine
- 此调用方式不改变 L1 架构，因为 Resolution Engine 仍然是唯一执行入口——SDK 只是提供了一个编程方式触发此入口
- 不需要单独的 ADR：这是 Resolution Engine 接口的编程封装，不是新架构组件

---

## 2. L2 规范影响检查

| L2 规范 | 是否受影响 | 说明 |
|---------|:---------:|------|
| L2-01 Runtime Spec | ❌ 否 | SDK 不涉及 Runtime 行为 |
| L2-01 EventBus Spec | ❌ 否 | SDK 不涉及事件 |
| L2-02 Planner Spec | ❌ 否 | SDK 不涉及推理 |
| L2-02 Decision Engine Spec | ❌ 否 | SDK 不涉及决策 |
| L2-02 Knowledge Spec | ❌ 否 | SDK 不涉及知识库 |
| **L2-03 Capability Spec** | **⚠️ 间接** | SDK 是对 L2-03 的实现，但不修改其 MUST 条款 |
| L2-04 Execution Spec | ❌ 否 | SDK 不涉及执行运行时 |
| L2-05 Policy Spec | ❌ 否 | SDK 的 Policy 由 packager 生成，不涉及 Policy 评估 |
| L2-05 Audit Spec | ❌ 否 | SDK 不涉及审计 |
| L2-05 Observation Spec | ❌ 否 | SDK 不涉及可观测性 |

> **结论**：L2 规范无 MUST 条款需要修改。SDK 新增的 6 条 SDKMUST 属于 SDK 自身实现约束，不影响 L2 规范本身。

---

## 3. 跨域接口影响

| 接口 | 影响域 | SDK 侧 | Runtime 侧 |
|------|--------|--------|-----------|
| `POST /capabilities` | SDK → Capability Center Registry | Packager 输出 + HTTP 客户端 | 接收三层结构 JSON |
| `PATCH /capabilities/{id}` | SDK → Capability Center Registry | 状态变更客户端 | 处理激活请求 |
| `GET /capabilities/search` | SDK → Capability Center Registry | 发现客户端 | 返回搜索结果 |

所有跨域接口的 payload 契约已在 PRD §4.3 明确定义。

---

## 4. 风险更新

| 风险 | 当前评估 |
|------|---------|
| Registry 接口尚未实现 | ⚠️ 持续。SDK 测试阶段使用 mock HTTP server |
| SDK 与 Connector SDK 的接口耦合 | ⚠️ 持续。已定义 ConnectorRegistry 接口抽象层 |
| 跨 Capability 调用在 MockRuntime 和真实环境行为不一致 | ⚠️ 已理解并文档化。MockRuntime 的 invoke 简化分发是已知限制 |

---

## 5. 结论

| 项目 | 结果 |
|------|------|
| L1 架构变更 | ❌ 不需要 |
| ADR 起草 | ❌ 不需要 |
| L2 规范 MUST 修改 | ❌ 不需要 |
| 新增跨域接口契约 | ✅ 已在 PRD 中定义 |
| 可进入 Phase 2 | ✅ |

---

## 6. 下一步

1. **Phase 2**：Spec Agent 确认 L2-03 规范无需更新 → 通知 Phase 3 可开始
2. **Phase 3**：Impl Agent 按 `tasks/capability-sdk-task-breakdown.md` 的 Task 依赖图逐个实现
   - 从 Task 001（包脚手架 + 基类）开始
