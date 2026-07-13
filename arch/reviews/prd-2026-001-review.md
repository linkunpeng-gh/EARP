# PRD-2026-001 评审报告

## Capability SDK — Python 第一版

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-001 |
| **Feature** | Capability SDK（Python） |
| **评审人** | Review Agent |
| **日期** | 2026-07-12 |
| **状态** | ✅ 所有 P0/P1/P2 问题已修复（PRD v1.1） |\n\n> **2026-07-12 更新**：PM Agent 已按本评审报告逐条修复 PRD（v1.0 → v1.1）。修复详情见 PRD §9 评审修复记录。\n> 当前 PRD 就绪，可进入 **Gate 0 人工验收**。

---

## 总体评价

**方向正确，结构完整，达到 Gate 0 要求的正式评审门槛。**

对齐了已冻结的 L2-03 v1.1、覆盖了开发流程模板要求的全部章节、用户故事覆盖了正常 + 异常 + 边界场景。

共发现 **3 个 P0（必须解决）、5 个 P1（建议修改）、5 个 P2（建议性优化）**。

---

## P0 — 必须解决（建议退回修改后再过 Gate 0）

### P0-1：跨 Capability 调用（US-04）与 MockRuntime（Out of Scope）存在逻辑冲突

**涉及段落：** US-04（§2.3）、§6「不做」第 4 项

**问题描述：**

PRD US-04 要求 `ctx.capabilities.invoke()` 调用链**经过 Resolution Engine**（「调用链经过 Resolution Engine，Policy 检查不会被跳过」），但 §6「不做」明确说 **"MockRuntime 直接调用 Capability，不经过 Resolution"**。

这意味着：
- MockRuntime 中测试通过的跨 Capability 调用，在真实环境可能被 Policy/Resolution 拦截
- **开发者可能在 MockRuntime 里跑通测试，部署后调用失败**

**建议方案：**

MockRuntime 的 `invoke()` 依然走简化的直接分发（不依赖真实的 Resolution Engine 服务），但 SDK 必须在注册阶段的 packager 中**自动推导 `depends_on` 关系并注入三层结构**——这样真实 Runtime 的 Resolution Engine 在收到注册请求时能正确计算调用链。

PRD 需要明确：
1. MockRuntime 中的 invoke 是简化版（跳过 Policy 检查——因为本地没有 Policy Center）
2. 真实的 Policy 检查由 Runtime 侧的 Resolution Engine 执行
3. Packager 需要从 Python 源码中解析 `ctx.capabilities.invoke()` 调用来自动生成 `depends_on` 关系

---

### P0-2：SDK → Registry 的接口契约缺失

**涉及段落：** §4.3 跨域接口

**问题描述：**

§4.3 只写了 API 路径名（`POST /capabilities` / `GET /capabilities/search` / `PATCH /capabilities/{id}`），**没有定义请求体 payload 格式**。

这是重大缺口——Packager 输出什么格式、Registry 接收什么格式，是 SDK 与 Runtime 两个域的关键接口边界。即使 Registry 服务端未实现，这个**接口契约也必须在 PRD 中定义**（至少是结构化的 payload schema），否则 Phase 5 集成时必然冲突。

**建议方案：**

在 §4.3 中增加 Packager 输出与 Registry 期望的 payload 合约：
- 请求体必须是 L2-03 §3.4 定义的三层结构 JSON（`definition` / `execution_contract` / `policy`）
- 用 TypeScript 接口或 JSON Schema 定义请求/响应体的结构
- 注册响应体包含 `capability_id`、`version`、`status`

---

### P0-3：ConnectorError 只覆盖了 2/6 错误码，未对齐 L2-03 §C.6

**涉及段落：** US-02（§2.2）、L2-03 §C.6

**问题描述：**

US-02 只示例了 `CONNECTION_FAILED` 和 `AUTH_EXPIRED`，但 L2-03 Appendix C.6 定义了 **6 个统一错误码**：

| 错误码 | US-02 已覆盖？ | L2-03 定 可重试 |
|:-------|:--------------:|:----------------:|
| CONNECTION_FAILED | ✅ | 是 |
| TIMEOUT | ❌ | 是 |
| RATE_LIMITED | ❌ | 是 |
| AUTH_EXPIRED | ✅ | 否 |
| INVALID_RESPONSE | ❌ | 否 |
| SYSTEM_ERROR | ❌（PRD 中另有定义但不等价于C.6） | 是 |

US-02 中的 `SYSTEM_ERROR` 是 Capability 层包装异常（§预期行为第3条），不是 Connector 错误码——和 L2-03 §C.6 的 SYSTEM_ERROR 语义重叠但不等价。

**建议方案：**

US-02 的 Connector 错误覆盖需要对齐 L2-03 §C.6 全部 6 个错误码，至少在预期行为中覆盖：
1. 显式列出全部 Connector 错误码（或声明 SDK 支持 L2-03 §C.6 的子集）
2. 明确 Capability 层 `SYSTEM_ERROR` 与 Connector 层 `SYSTEM_ERROR` 的关系

---

## P1 — 建议修改

### P1-1：AC-10 和 AC-11 边界重叠

**涉及段落：** §3 验收条件（AC-10 / AC-11）

| AC | 描述 | 重叠部分 |
|:--:|------|:--------:|
| AC-10 | 输入输出 schema 从 Pydantic 自动推导，开发者不需要手写 JSONSchema | 这是 AC-11 的子集 |
| AC-11 | 三层结构（Definition / Execution Contract / Policy）由 SDK 自动生成，开发者只需要填写业务字段 | AC-10 是"三层结构"中 Definition Layer 的一部分 |

**建议：** 合并 AC-10 到 AC-11，或明确区分——AC-10 测 schema 推导功能本身，AC-11 测三层结构完整性。

---

### P1-2：生命周期只覆盖了 register/activate，缺少 deprecate/retire

**涉及段落：** §3 AC-09（注册后返回 draft 状态）、§7 CLI 命令设计

L2-03 §4 定义了 Draft → Active → Deprecated → Retired 的完整生命周期。PRD CLI 只支持 `register`（→ Draft）和 `activate`（→ Active），缺少 `deprecate` 和 `retire`。

**建议：** 在 §6 Out of Scope 中新增一项声明 deprecate/retire 不在第一版范围，或在 §4.4 风险中注明此缺口。

---

### P1-3：Discovery 客户端缺少分页支持

**涉及段落：** §7 交付物 `discovery/client.py`

`client.search()` 没有关于分页（pagination）、排序（sorting）、结果截断的讨论。当 Registry 中有数百个 Capability 时，返回全部结果是不合理的。

**建议：** SDK 的 search 接口设计应考虑分页参数（`page_size`、`page_token`），至少在设计阶段预留接口参数。

---

### P1-4：注册客户端缺少幂等性支持

**涉及段落：** §7 `registration/client.py`

如果开发者运行 `earp capability register` 时网络超时（但服务端已成功注册），重试会创建重复 capability。L2-03 §2.2 要求 `capability_id` 全局唯一——重试应该基于 `capability_id` 幂等。

**建议：** 在 registration client 中实现幂等重试（基于 `capability_id` 去重），或至少在 PRD §4.4 风险中说明此风险及应对。

---

### P1-5：开发流程模板要求用户故事覆盖正常/异常/边界，当前边界只覆盖 2 个场景

**涉及段落：** §2 用户故事、`arch/development-process.md` §3.2 PRD 模板

| 类型 | 当前 US | 建议 |
|:----:|:--------:|:----:|
| 正常 | US-01 | ✅ 充足 |
| 异常 | US-02、US-05 | ✅ 充足 |
| 边界 | US-03、US-04 | 可补充一个离线环境的用户故事 |

**建议：** 为 AC-03（离线测试）增加一个对应的用户故事，将 AC-12（环境变量插值）也抽象为一个边界条件用户故事。

---

### P1-6：SDK 分发方式未定义

**涉及段落：** §4 依赖分析

PRD 说 `pip install earp-sdk-py` 但不讨论发布机制：
- 发布到 PyPI 还是私有 index？
- 版本 publish 流程是什么？
- pre-release 版本命名规则？

**建议：** 在 §4 依赖分析中增加一项"SDK 发布与分发策略"。

---

## P2 — 建议性优化

### P2-1：测试隔离的细节缺口

**涉及段落：** AC-03 / SDKMUST-003

AC-03 / SDKMUST-003 要求 MockRuntime 无外部网络请求。但 `capability.yaml` 中的 `${MES_BASE_URL}` 等环境变量在离线环境下如何解析？PRD 应说明 MockRuntime 的环境变量解析策略：
- 直接从进程环境变量读取？→ 那依赖环境变量提前设置
- MockRuntime 提供 `set_env()` 方法？→ 更好的测试隔离

---

### P2-2：Python 版本策略

**涉及段落：** §4.1 内部依赖（Python 3.12+）

Python 3.13 已发布，3.12 的 ending-of-life 约为 2028 年。考虑到 SDK 的生命周期：

**建议：**
- 明确最低支持版本（建议 3.11 包容更多企业用户，或至少声明 3.12+ 的原因）
- CI 测试矩阵覆盖所有声明支持的版本

---

### P2-3：内部异常链的测试要求

**涉及段落：** US-02（错误信息包含原始异常 chain）

US-02 要求"错误信息包含原始异常 chain（可追溯）"，但 AC 列表中没有对应的验收条件。

**建议：** 新增 AC：`未捕获异常时，SDK 包装的 SYSTEM_ERROR 包含原始异常的 traceback / __cause__`。

---

### P2-4：跨 Capability 调用的错误传播策略

**涉及段落：** US-04（`ctx.capabilities.invoke()`）

如果 `ctx.capabilities.invoke("B", params)` 中的 B 失败（如 B 抛出 `BUSINESS_ERROR`），A 会发生什么？
- 异常向上冒泡？→ A 需要 try/except
- SDK 包装为 `CapabilityInvocationError`？→ 更结构化的处理

**建议：** 在 US-04 或 AC-07 中明确错误传播策略。

---

### P2-5：`@capability` 装饰器语法在交付物中未充分体现

**涉及段落：** §7 交付物清单、L3 设计 v1 §6

L3 设计定义了 `@capability` 和 `@capability_fn` 装饰器 API，但 PRD §7 交付物中只列出 `decorators.py` 文件但未在 AC 或 US 中测试装饰器语法。如果装饰器是二等公民 API（推荐类继承为主），PRD 应该声明其定位。

**建议：** 在 §6 新增 Out of Scope 条目说明装饰器语法的定位（主推 vs 次选），或增加一个简单的 AC 覆盖装饰器路径。

---

## 对齐检查表

### 与 L2-03 v1.1 Capability Center 规范的对齐

| 检查项 | v1.0 结果 | v1.1 结果 | 备注 |
|:-------|:---------:|:---------:|------|
| 三层结构（Definition / Execution Contract / Policy） | ✅ | ✅ | AC-11、SDKMUST-001 |
| capability_id snake_case、语义化版本 | ✅ | ✅ | §5.1 两条 MUST |
| JSONSchema Draft-07 | ✅ | ✅ | L2-03 §3.1 → SDK §5.1 |
| Execution Contract 全部 MUST 字段 | ✅ | ✅ | §5.1 |
| Policy Layer 全部 MUST 字段 | ✅ | ✅ | §5.1 |
| Lifecycle（Draft/Active/Deprecated/Retired） | ⚠️ 缺少 deprecate/retire CLI | ✅ 已声明 OOS v1.1 补充 | §6 |
| Registry API payload 契约 | ❌ 缺失 | ✅ 完整 JSON Schema | §4.3 |
| Discovery 检索模式 | ⚠️ 缺少分页 | ✅ 已增 page/page_size | §4.3 接口契约 |
| Connector 错误码 | ❌ 只覆盖 2/6 | ✅ 全 6 错误码 + SDKMUST-006 | US-02 + §5.2 |
| 错误码对齐 L2-03 §8.4 | ✅ | ✅ | SDKMUST-005 |

### 与 L0 设计哲学的对齐

| 理念 | 对齐度 | 说明 |
|:----|:------:|------|
| Runtime First | ✅ | SDK 不 Runtime，只负责开发/注册 |
| Capability First | ✅ | SDK 围绕 Capability 建模 |
| CQRS | ✅ | QueryCapability / CommandCapability 分离 |
| Reason-Act 解耦 | ✅ | SDK 不涉及 Reasoning |
| 规范 ≠ 文档 | ✅ | 实现对齐 L2 MUST 条款 |

### 与开发流程模板的对齐

| 检查项 | v1.0 结果 | v1.1 结果 | 备注 |
|:-------|:---------:|:---------:|------|
| 用户故事：正常路径 | ✅ US-01 | ✅ | 不变 |
| 用户故事：异常路径 | ✅ US-02、US-05 | ✅ | 不变 |
| 用户故事：边界条件 | ⚠️ US-03、US-04 | ✅ 新增 US-06、US-07 | 离线环境 + 多环境配置 |
| 验收条件可测试性 | ✅ 13 条 AC | ✅ 15 条 AC | 新增 AC-14（错误链）、AC-15（set_env） |
| 依赖分析完整性 | ⚠️ 缺少 SDK 分发策略 | ✅ 新增 §4.5 分发策略 | 私有 PyPI index + 版本规则 |
| 优先级合理性 | ✅ P0 | ✅ | 不变 |
| 无矛盾需求 | ⚠️ US-04 与 MockRuntime OOS 矛盾 | ✅ 明确边界 | MockRuntime invoke = 简化分发 |

---

## 评审总结

### 数据统计

| 类别 | v1.0 发现 | v1.1 修复状态 |
|:----|:---------:|:-------------:|
| ✅ 通过的检查项 | 15+ | 仍然全部通过 |
| ❌ P0（必须解决） | 3 | ✅ 全部已修复 |
| ⚠️ P1（建议修改） | 6 | ✅ 全部已修复 |
| 💡 P2（建议性优化） | 5 | ✅ 全部已修复或以明确声明覆盖 |

### 三个 P0 拦截石（已全部修复）

| 问题 | 修复位置 | 修复内容 |
|:----|:--------|---------|
| P0-1 US-04 与 MockRuntime OOS 冲突 | US-04 + §6 OOS | 明确 MockRuntime invoke = 简化直接分发，不替代 Resolution；已知限制全部文档化 |
| P0-2 Registry 接口 payload 契约缺失 | §4.3 | 新增三层结构 JSON 请求体/成功响应/失败响应完整格式 |
| P0-3 Connector 错误码只覆盖 2/6 | US-02 + §5.2 | 新增 6 个错误码完整映射表 + Capability/Connector 层级别区分 + SDKMUST-006 |

### 下一步

PRD v1.1 已完成所有评审问题修复，建议进入 **Gate 0 人工验收**。验收通过后进入 Phase 1（架构影响分析）。
