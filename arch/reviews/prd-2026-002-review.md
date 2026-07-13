# PRD-2026-002 评审报告

## Runtime SDK — Python 第一版

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-002 |
| **Feature** | Runtime SDK（Python） |
| **设计文档** | arch/L3/runtime-sdk-design-v1.md（v1.1，已评审修复） |
| **影响规范** | L2-01-RUNTIME v1.2 |
| **评审人** | Review Agent |
| **日期** | 2026-07-12 |
| **状态** | ✅ 全部 P0/P1/P2 已修复（v1.0 → v1.1） |

> **2026-07-12 更新**：PM Agent 已按本评审报告逐条修复 PRD。修复详情见 PRD §9 评审修复记录。

---

## 总体评价

**骨架正确，对齐了 L3 设计文档 v1.1，定位与 Capability SDK 互补合理。** 6 个用户故事覆盖了正常/异常/边界三类场景，12 条 AC 对齐了设计文档的 9 条 SDKMUST-R 中的大部分。

共发现 **2 个 P0（必须修复）、4 个 P1（建议修改）、2 个 P2（建议性优化）**。

---

## P0 — 必须修复（建议退回修改后再过 Gate 0）

### P0-1：US-02（Session 模式）和 US-03（事件订阅）缺少详细行为描述

**涉及段落：** §3 US-02 / US-03

**问题描述：**

US-02 和 US-03 只有标题，没有预期行为描述：

```markdown
### US-02：Session 模式——多次调用带上下文

> 作为**工单应用的开发者**，我希望**在同一个 Session 中先查报警再创建工单**，以便**两次调用共享上下文和 trace**。

### US-03：事件订阅——事件驱动处理

> 作为**运维平台的开发者**，当 **MES 发出 critical 级报警事件**时，我希望**SDK 自动收到事件并触发处理 Capability**。
```

对比 US-01、US-04、US-05、US-06 都有完整的 `预期流程` / `预期行为` 块，US-02 和 US-03 没有。缺少了：

- **US-02 缺少：** `user_id` 是否必传（SDKMUST-R-001）、`idempotency_key` 的使用场景、Session 关闭语义
- **US-03 缺少：** 订阅方法、事件类型过滤、断开重连行为、如何退出订阅

**建议方案：**

为 US-02 和 US-03 补充预期行为块：

```markdown
### US-02：Session 模式——多次调用带上下文

预期行为：
  - 调用 client.create_session(user_id="...") 创建 Session
  - 在 Session 内多次调用 session.capabilities.invoke()
  - Command 类型传入 idempotency_key 确保幂等
  - 调用 session.close() 关闭 Session
  - user_id 为 MUST 参数（SDKMUST-R-001）

### US-03：事件订阅——事件驱动处理

预期行为：
  - 通过 session.events.subscribe(event_types=[...]) 订阅事件流
  - event_types=None 订阅全部事件
  - 连接断开后自动重连（指数退避，最多 5 次）
  - 通过 break 或 aclose() 退出订阅
```

---

### P0-2：SDKMUST-R 约束与 AC 映射不完整（缺少 4 条）

**涉及段落：** §4 AC 列表、设计文档 §5 SDKMUST-R

设计文档 v1.1 定义了 9 条 SDKMUST-R，但 PRD 的 12 条 AC 只覆盖了其中 **6 条**，有 **3 条 MUST 和 1 条 SHOULD 没有对应 AC**：

| SDKMUST-R | 级别 | 设计文档要求 | AC 状态 |
|:----------|:----:|:-------------|:-------:|
| R-001 | MUST | `user_id` 为 Session 必传参数 | ✅ AC-12 |
| R-002 | MUST | 所有 HTTP 请求含 `Authorization: Bearer <token>` | ❌ **缺失** |
| R-003 | MUST | 所有 HTTP 请求含 `User-Agent: earp-sdk-runtime/{version}` | ❌ **缺失** |
| R-004 | MUST | 自动注入 `X-Trace-Id` | ✅ AC-08 |
| R-005 | MUST | invoke() 经过 Runtime 端点（确保 Resolution Engine 路径） | ❌ **缺失** |
| R-006 | MUST | 错误码对齐 CapabilityErrorCode | ✅ AC-10 |
| R-007 | SHOULD | 连接失败自动重试 | ✅ AC-09 |
| R-008 | SHOULD | 事件订阅自动重连 | ✅ AC-11 |
| R-009 | SHOULD | Command 缺 idempotency_key 时打印警告 | ❌ **缺失** |

**建议方案：**

新增 4 条 AC：

```markdown
| AC-13 | 所有 HTTP 请求自动注入 `Authorization: Bearer <token>` | SDKMUST-R-002 |
| AC-14 | 所有 HTTP 请求包含 `User-Agent: earp-sdk-runtime/{version}` | SDKMUST-R-003 |
| AC-15 | invoke() 必须发送请求到 Runtime 端点，不直接调 Capability | SDKMUST-R-005 |
| AC-16 | Command Capability 调用缺少 idempotency_key 时打印警告 | SDKMUST-R-009 |
```

---

## P1 — 建议修改

### P1-1：`RuntimeClient.call()` 的返回值未说明与 Capability SDK 的关系

**涉及段落：** US-01 预期流程

US-01 说"拿回 dict 结果"，但对比 Capability SDK（返回 Pydantic 模型），调用方可能困惑为什么类型不一。虽然设计文档 §3.1 已有说明，**PRD 作为面向评审和开发者的文档，应体现此决策**。

**建议：** 在 US-01 预期流程第 4 步后补充说明：

> 返回 dict 而非 Pydantic 模型：应用开发者没有 Capability 的 Pydantic 模型源码。
> 可通过 Discovery API 查询 Capability 的 output_schema 了解返回字段。

---

### P1-2：架构决策（传输协议/认证方式/重试策略/流式协议）未在 PRD 中体现

**涉及段落：** §6 不做、§5 依赖分析

设计文档 v1.1 新增了 §2 架构决策章节（HTTP + JWT + SSE + 指数退避），但 PRD 没有引用或体现这些决策。

- 当前 PRD 只在 §6 中说"gRPC 传输 → 第二阶段"，但没说明**第一阶段的传输协议是什么**
- 认证方式完全没有在 PRD 中提及

**建议：** 在 §5 依赖分析中新增一行：

| 传输协议 | HTTP/REST（v1），gRPC（v2） |
| 认证方式 | Bearer JWT |
| 流式协议 | SSE（v1），WebSocket（v2） |

---

### P1-3：缺少与 Capability SDK PRD 的差异对比表

**涉及段落：** 全文

作为 EARP 平台的第二个 SDK，PRD 应该展示与 Capability SDK PRD 的结构差异。当前两个 PRD 看起来是独立的——评审人需要手动对比。

**建议：** 在 §2 设计文档后新增一段快速差异表：

| 维度 | Capability SDK | Runtime SDK |
|:----|:---------------|:------------|
| 使用者 | Capability 开发者 | 应用开发者 |
| 核心 API | `class Capability.execute()` | `session.capabilities.invoke()` |
| 测试工具 | MockRuntime（MockCapabilityCenter） | MockRuntimeClient（MockRuntime） |
| 错误类型 | ConnectorError + CapabilityError | CapabilityNotFoundError 等 |
| 交付物大小 | 17 个源文件 + CLI | 7 个源文件 + 无 CLI |

---

### P1-4：Out of Scope 缺少 `CapabilityNotFoundError` 等 3 个异常类的定义位置

**涉及段落：** §6

PRD US-04/US-05 引用了 `CapabilityNotFoundError` 和 `PermissionDeniedError`，但没有说明这些类定义在哪里。设计文档 §4.6 说"在 earp-sdk-core 中新增"，但 PRD 应确认这点。

**建议：** 新增 OOS 条目，或明确说明"新增异常类型定义在 earp-sdk-core-py 中，与 Capability SDK 共享"。

---

## P2 — 建议性优化

### P2-1：缺少 §8 验收总结表和 §9 评审修复记录

Capability SDK PRD 有 §8 验收总结表和 §9 评审修复记录。本 PRD 没有。对于 Gate 0 流程来说这不是硬性要求，但有总比没有好。

**建议：** 增加 §8 验收总结表（5 个检查项）和 §9 评审修复记录（预留结构，修复后填充）。

---

### P2-2：PRD 版本号建议更新为 v1.1（引用设计文档 v1.1）

**涉及段落：** 文档头

当前 PRD 版本为 `v1.0`，但引用的设计文档已经是 `arch/L3/runtime-sdk-design-v1.md`（经过评审修复的 v1.1）。PRD 版本与设计文档版本不同步可能引起混淆。

**建议：** 统一将 PRD 版本标记为 `v1.1`，并在文档头注明"对齐 L3 设计文档 v1.1"。

---

## 对齐检查表

### 与 L3 设计文档 v1.1 的对齐

| 设计文档要求 | PRD 对应 | 状态 | 备注 |
|:------------|:---------|:----:|------|
| 9 条 SDKMUST-R | 12 条 AC | ⚠️ | 缺少 4 条 AC 对应 R-002/R-003/R-005/R-009（P0-2） |
| HTTP/REST 协议 | §6 提及"gRPC 第二阶段"但未明确 HTTP | ⚠️ | P1-2 |
| Bearer JWT 认证 | 未提及 | ❌ P1-2 | |
| SSE 流式 | 未提及 | ⚠️ | 可选引用的细节 |
| MockRuntimeClient 设计 | AC-07 覆盖 | ✅ | |
| user_id MUST | AC-12 覆盖 | ✅ | |
| 异常映射表（7 种） | US-04/US-05 覆盖 2 种 | ⚠️ | 建议补充更多场景说明 |

### 与开发流程模板的对齐

| 检查项 | 结果 | 备注 |
|:-------|:----:|------|
| 用户故事：正常路径 | ✅ US-01 | |
| 用户故事：异常路径 | ✅ US-04/US-05 | |
| 用户故事：边界条件 | ✅ US-06 | |
| 验收条件可测试性 | ✅ 12 条 AC | 但缺少 4 条（P0-2） |
| 依赖分析完整性 | ⚠️ | 缺少协议/认证声明（P1-2） |
| 优先级合理性 | ✅ P0 | |
| 无矛盾需求 | ✅ | 与设计文档 v1.1 一致 |

### 与 Capability SDK PRD 的对比

| 维度 | Capability SDK PRD (v1.1) | Runtime SDK PRD (v1.0) | 状态 |
|:----|:------------------------:|:---------------------:|:----:|
| 用户故事 | 7 个 US | 6 个 US | 合理（范围略小） |
| 验收条件 | 15 条 AC | 12 条 AC | P0-2 缺少 4 条 |
| 依赖分析 | 内/外/跨域/风险/分发 | 缺少传输协议声明 | P1-2 |
| OOS | 9 项 | 3 项 | 缺少认证/协议声明 |
| 交付物清单 | 详细目录 + 包结构 | 仅包结构 | 合理（规模较小） |
| 验收总结表 | §8 ✅ | ❌ | P2-1 |
| 评审修复记录 | §9 ✅ | ❌ | P2-1 |

---

## 评审总结

### 数据统计

| 类别 | 数量 |
|:----|:----:|
| ✅ 通过的检查项 | 8+ |
| ❌ P0（必须解决） | 2 |
| ⚠️ P1（建议修改） | 4 |
| 💡 P2（建议性优化） | 2 |

### 两个 P0 拦路石

1. **P0-1** — US-02（Session 模式）和 US-03（事件订阅）缺少预期行为描述，不可测试
2. **P0-2** — 设计文档的 9 条 SDKMUST-R 有 4 条在 PRD 中没有对应 AC（缺少 Authorization header / User-Agent / Resolution Engine 路径 / idempotency_key 警告的验收条件）

### 总体建议

PRD 整体质量好，结构完整，但相比 Capability SDK PRD（已通过 Gate 0）少了**验收总结表**和**评审修复记录**两个章节，建议补齐。两个 P0 问题修复后进入 Gate 0 人工验收。
