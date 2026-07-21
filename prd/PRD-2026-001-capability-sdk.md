# PRD-2026-001

## Capability SDK — Python 第一版

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-001 |
| **Feature** | Capability SDK（Python） |
| **影响域** | SDK/API（+ 间接影响 Runtime/Governance） |
| **影响规范** | L2-03-CAPABILITY v1.1 |
| **优先级** | **P0**（基础平台 SDK，后续 SDK 的依赖） |
| **版本** | v1.1（修复评审问题） |
| **作者** | PM Agent |
| **日期** | 2026-07-12 |

---

## 1. 背景与动机

### 1.1 为什么需要 Capability SDK

EARP 架构文档体系（L0→L2）已完成设计定稿。但是**架构只定义了"系统长什么样"，没有给出开发者怎么写 Capability 的工具**。

当前存在三个断层：

**断层 1：架构复杂度与开发者体验的鸿沟**
L2 Capability Center 规范定义了 3 层结构（Definition / Execution Contract / Policy）+ Resolution Engine + Registry + Graph。一个开发者如果按照规范手写 Capability，需要理解整个体系才能开始——这阻止了业务团队接入。

**断层 2：没有本地测试能力**
当前无法在不启动完整 EARP Runtime 的情况下测试一个 Capability 的逻辑。每次修改都需要部署，迭代周期长。

**断层 3：没有统一的开发→注册路径**
每个 Capability 开发者需要自己写注册脚本、手填 JSONSchema、自己处理 Policy 字段。不一致、易出错、不可审计。

### 1.2 SDK 定位

Capability SDK 是 EARP 平台首个 L3 实现层产物。它填补架构（架构设计）到实现（业务代码）之间的空白。

---

## 2. 用户故事

### US-01：正常路径——业务开发者写第一个 Capability

> 作为**设备管理域的后端工程师**，我希望**用最少的代码定义一个 Capability**，以便**快速将已有的 MES 查询接口封装为 EARP Capability 并注册到平台**。

```
预期流程：
  1. pip install earp-sdk-py
  2. 写一个 Python 类，继承 QueryCapability，实现 execute 方法
  3. 输入输出用 Pydantic model 定义
  4. 本地用 MockRuntime 跑通测试（无网络依赖）
  5. 一行 CLI 命令注册到 Capability Center
  6. 一行 CLI 命令激活

总耗时：< 30 分钟（从 pip install 到注册成功）
```

### US-02：异常路径——Connector 故障时的结构化错误处理

> 作为 **Capability 开发者**，当 **底层 Connector 调用外部系统失败**时，我希望**SDK 返回结构化的错误信息**，以便**调用方（Planner / 其他 Capability）能根据错误码决定是否重试或切换 fallback**。

```
预期行为：
  - Connector 错误码全对齐 L2-03 §C.6：

    错误码            可重试    SDK 映射
    ────────────────  ──────  ─────────────────────
    CONNECTION_FAILED  是      ConnectorError(code, msg, retryable=True)
    TIMEOUT            是      ConnectorError(code, msg, retryable=True)
    RATE_LIMITED       是      ConnectorError(code, msg, retryable=True, retry_after=int)
    AUTH_EXPIRED       否      ConnectorError(code, msg, retryable=False)
    INVALID_RESPONSE   否      ConnectorError(code, msg, retryable=False)
    SYSTEM_ERROR       是      ConnectorError(code, msg, retryable=True)

  - Capability.execute 中未捕获的异常 → SDK 包装为 CapabilityError(code="SYSTEM_ERROR", ...)
    含义：Capability 层 SYSTEM_ERROR 是 Connector 层 SYSTEM_ERROR 的超集。
    ConnectorError(code="SYSTEM_ERROR") 表示 Connector 自身异常；
    CapabilityError(code="SYSTEM_ERROR") 表示 execute 内部未预期的异常（包含原始异常 __cause__ 链）。
  - 错误信息包含原始异常 chain（可追溯）
```

### US-03：边界条件——Command Capability 的补偿逻辑

> 作为**工单管理域的后端工程师**，在开发一个 **Command 类型 Capability**（如 `create_work_order`）时，我希望**声明补偿操作**，以便**在 Saga 事务回滚时自动执行逆序操作**。

```
预期行为：
  - 继承 CommandCapability，实现 compensate 方法
  - SDK 自动检测到 compensate 已实现，设置 supports_compensation=True
  - 未实现 compensate 时，supports_compensation=False，不参与事务回滚
```

### US-04：边界条件——跨 Capability 调用

> 作为 **Capability 开发者**，当 **我的 Capability 的执行依赖另一个 Capability 的输出**（如先查设备 ID 再查报警），我希望**在 execute 方法中调用另一个已经注册的 Capability**，以便**复用已有业务能力**。

```
预期行为：
  - 通过 ctx.capabilities.invoke("other_capability_id", params) 调用
  - 在 MockRuntime 中，注册的 Capability 可以被其他 Capability 调用

  MockRuntime 中的 invoke 行为（已知限制）：
    - 简化直接分发（不走 Resolution Engine）
    - 不做 Policy 检查——MockRuntime 没有 Policy Center
    - 仅验证 capability_id 在本地已注册
    - 调用的间传是同步的（真实 Runtime 中可能是异步调度）

  真实 Runtime 中的 invoke 行为：
    - 经过 Resolution Engine：语义匹配 + Policy 过滤 + 可用性检查
    - Policy 检查在 Runtime 侧执行，不在 MockRuntime 中模拟

  invoke 失败时的错误传播：
    - 如果被调 Capability（B）抛出异常，B 的异常向上冒泡到调用方（A）
    - SDK 不自动包装——A 的 execute 内需要 try/except 处理
    - 将来版本可考虑提供 CapabilityInvocationError 包装（当前版本不做）
```

### US-05：异常路径——注册时 Schema 校验失败

> 作为 **Capability 开发者**，当我**注册的 Capability 的 input_schema 定义有误**（如字段名包含非法字符、类型不支持）时，我希望**CLI 在注册前给出明确的校验错误**，而不是等到服务端返回 400 才报错。

```
预期行为：
  - CLI 在注册前本地校验 schema
  - 错误信息包含：字段路径 + 错误原因
  - 所有错误一次性列出（非逐个修复逐个报错）
  - 校验通过后才发送网络请求
```

### US-06：边界条件——离线/无网络环境下的本地开发

> 作为 **Capability 开发者**，当**我的开发环境没有外网访问权限**时，我希望**MockRuntime 完全离线工作**，以便**不依赖网络环境也能完成 Capability 的开发、测试、调试**。

```
预期行为：
  - MockRuntime 执行 Capability 时不产生任何外部网络请求
  - capability.yaml 中的 ${ENV_VAR} 在 MockRuntime 中从进程环境变量读取
  - MockRuntime 提供 runtime.connectors.env.set("MES_BASE_URL", "http://localhost:9999") 方法覆盖环境变量
  - 注册/发现客户端在未配置 Registry URL 时，应给出明确错误而非挂起
```

### US-07：边界条件——多环境配置切换

> 作为 **Capability 开发者**，当我**在开发/测试/预发环境中切换时**，我希望**通过一份 capability.yaml + 环境变量覆盖 Connector 地址和凭证**，以便**不修改代码就能切换目标系统**。

```
预期行为：
  - capability.yaml 中 `${MES_BASE_URL}`、`${MES_API_TOKEN}` 在部署时由环境变量注入
  - 未设置环境变量时，CLI 启动时给出警告（非阻塞）
  - MockRuntime 测试时可通过 set_env() 覆盖，不影响系统环境变量
```

---

## 3. 验收条件（AC）

| ID | 描述 | 对应 US | 可测试 |
|:--:|------|:-------:|:------:|
| AC-01 | 开发者从零开始，按 SDK 文档在 30 分钟内完成一个 Capability 的编写、测试、注册 | US-01 | ✅ 走通全程并计时 |
| AC-02 | SDK 包可通过 `pip install earp-sdk-py` 安装 | US-01 | ✅ |
| AC-03 | 基于 SDK 编写的 Capability 可在 MockRuntime 中本地执行，不依赖任何外部服务 | US-01, US-06 | ✅ 在无网络环境跑通测试 |
| AC-04 | MockRuntime 支持注册 connector handler 来模拟外部系统响应 | US-02 | ✅ |
| AC-05 | Connector 错误码全对齐 L2-03 §C.6：6 个错误码都有对应 SDK 异常类型，且 retryable 属性正确 | US-02 | ✅ 单元测试 |
| AC-06 | CommandCapability 实现 compensate 方法后，包装器自动设置 supports_compensation=True | US-03 | ✅ |
| AC-07 | ctx.capabilities.invoke() 在 MockRuntime 中可跨 Capability 调用，调用失败时异常向上冒泡 | US-04 | ✅ 集成测试 |
| AC-08 | CLI `earp capability register` 在发送请求前做本地 schema 校验，错误一次性列出 | US-05 | ✅ |
| AC-09 | 注册后 CLI 返回 capability_id、version、status（draft） | US-01 | ✅ |
| AC-10 | Schema 自动生成：输入 Pydantic BaseModel 输出 JSONSchema Draft-07，支持嵌套模型和可选字段 | US-01 | ✅ 单元测试 |
| AC-11 | 三层结构（Definition / Execution Contract / Policy）由 SDK 自动生成，开发者只需要填写业务字段 | US-01 | ✅ 输出 JSON 对齐 L2-03 §3.4 格式 |
| AC-12 | capability.yaml 支持 `${ENV_VAR}` 环境变量插值 | US-01, US-07 | ✅ |
| AC-13 | 覆盖率目标：SDK 核心模块（base/schema/contracts/packager/mock_runtime）单元测试覆盖率 ≥ 85% | — | ✅ `pytest --cov` |
| AC-14 | Capability.execute 未捕获异常时，SDK 包装的 CapabilityError 包含原始异常的 traceback 或 __cause__ | US-02 | ✅ 单元测试 |
| AC-15 | MockRuntime 提供 set_env(key, value) 方法覆盖配置变量，不影响进程环境变量 | US-06 | ✅ |

> **AC-10 与 AC-11 的关系**：AC-10 验证 schema 推导功能本身的正确性（输入模型→输出 JSONSchema）；AC-11 验证整个三层结构包装的完整性（输入类→输出 L2 对齐 JSON）。AC-10 是 AC-11 的子集但测试粒度不同，故分别保留。

---

## 4. 依赖分析

### 4.1 内部依赖

| 依赖 | 状态 | 说明 |
|------|:----:|------|
| L2-03-CAPABILITY v1.1 | ✅ 已冻结 | SDK 实现的三层结构完全对齐此规范 |
| Capability Center（Runtime 端） | 📝 未实现 | SDK 注册端依赖 Capability Center 的 REST API |
| Python 3.12+ | ✅ 可用 | 最低支持 3.12，CI 测试矩阵覆盖 3.12 / 3.13 |

### 4.2 外部依赖

| 依赖 | 用途 | 是否新增 |
|------|------|:--------:|
| pydantic ≥ 2.0 | 输入输出模型定义 + Schema 生成 | ✅ 新增 |
| httpx | 注册/发现客户端的 HTTP 请求 | ✅ 新增 |
| pytest + pytest-asyncio | 测试框架 | ✅ 新增 |
| rich | CLI 输出格式化 | ✅ 新增 |
| pyyaml | capability.yaml 解析 | ✅ 新增 |
| typer 或 click | CLI 框架 | ✅ 新增 |

### 4.3 跨域接口（Payload 契约）

以下定义 Packager（SDK 侧）输出和 Registry（Runtime 侧）期望的接口合约。

#### POST /capabilities — 注册

**请求体（三层结构 JSON，对齐 L2-03 §3.4）：**

```json
{
  "definition": {
    "capability_id": "query_equipment_alarm",
    "name": "查询设备报警",
    "description": "根据设备ID查询当前报警信息",
    "domain": "equipment",
    "version": "1.0.0",
    "capability_type": "query",
    "tags": ["equipment", "alarm"],
    "input_schema": { "$schema": "https://json-schema.org/draft-07/schema#", ... },
    "output_schema": { "$schema": "https://json-schema.org/draft-07/schema#", ... }
  },
  "execution_contract": {
    "protocol": "sdk",
    "timeout": 30000,
    "retry_policy": { "max_attempts": 0, "backoff": "exponential" },
    "idempotent": true,
    "transaction_scope": "none",
    "supports_compensation": false,
    "compensating_capability": null
  },
  "policy": {
    "auth_required": true,
    "required_permissions": [],
    "approval_required": false,
    "audit_level": "summary",
    "constraints": []
  }
}
```

**成功响应（201 Created）：**

```json
{
  "capability_id": "query_equipment_alarm",
  "version": "1.0.0",
  "status": "draft",
  "created_at": "2026-07-12T10:00:00Z"
}
```

**失败响应（4xx/5xx）：**

```json
{
  "error": "SCHEMA_VALIDATION_FAILED",
  "message": "...",
  "details": [
    { "field": "definition.input_schema", "reason": "..." }
  ]
}
```

#### GET /capabilities/search?q={query}&domain={domain}&page={n}&page_size={n}
（注：domain 参数始终指 Business Domain，v2.1 起与 Data Domain 平行概念）

**成功响应（200 OK）：**

```json
{
  "results": [
    { "capability_id": "...", "name": "...", "version": "...", "confidence": 0.95 }
  ],
  "page": 1,
  "page_size": 20,
  "total": 42
}
```

#### PATCH /capabilities/{capability_id} — 状态变更

```json
// 请求体
{ "status": "active" }

// 成功响应
{
  "capability_id": "query_equipment_alarm",
  "version": "1.0.0",
  "status": "active",
  "updated_at": "2026-07-12T12:00:00Z"
}
```

> **注意**：以上接口定义是 SDK 与 Runtime 两个域的**接口边界契约**。Registry 服务端实现在此 PRD 范围内不实现，但 SDK 的 HTTP 客户端和 Packager 按此协议开发。当 Registry 服务端实现后，SDK 侧应无缝对接。

### 4.4 风险

| 风险 | 概率 | 影响 | 应对 |
|:----:|:----:|:----:|------|
| Capability Center 的 Registry API 未实现 | 高 | SDK 注册客户端不可端到端测试 | SDK 侧保留 mock HTTP server 用于测试；文档注明依赖关系 |
| Capability SDK 与 Connector SDK 之间的接口耦合 | 中 | ctx.connectors 接口可能变动 | 先定义 ConnectorRegistry 接口抽象层，不与具体 Connector SDK 绑定 |
| Python 3.12 async 惯用法对同步开发者不友好 | 低 | 开发者初次体验折损 | 文档提供同步→异步迁移示例；装饰器层自动包装同步函数 |
| 注册请求网络超时导致重复创建 Capability | 低 | 违反 capability_id 全局唯一约束 | 注册客户端实现幂等重试：携带 capability_id，Registry 服务端应做 upsert 或返回已存在记录 |
| SDK 发布到 PyPI 前的版本号冲突 | 低 | 早期开发阶段版本混乱 | 使用 pre-release 版本号（0.1.0.dev0），正式 v1.0 再发第一个 stable 版本 |

### 4.5 SDK 分发策略

| 维度 | 策略 |
|------|------|
| **第一版发布渠道** | 私有 PyPI index（如 GitLab Package Registry 或 AWS CodeArtifact），不上 PyPI 公网 |
| **版本命名规则** | `0.1.0.dev{N}`（开发迭代）→ `0.1.0`（功能完整）→ `1.0.0`（API 冻结） |
| **发布流程** | 手动触发 CI Job → 构建 wheel → push 到私有 index → tag Git commit |
| **消费者** | 内部 EARP 开发团队 `pip install -i <private-index> earp-sdk-py` |

---

## 5. 技术约束（MUST 条款对齐）

### 5.1 本 PRD 涉及的 L2 MUST 条款

| L2 引用 | 内容 | SDK 实现要求 |
|---------|------|-------------|
| L2-03 §2.2 | capability_id 全局唯一，snake_case | SDK 在注册时验证 ID 格式 |
| L2-03 §2.2 | 版本号遵循语义化版本 | SDK 自动校验 MAJOR.MINOR.PATCH |
| L2-03 §3.1 | input_schema、output_schema 必须为 JSONSchema | SDK 自动从 Pydantic 生成符合 Draft-07 的 JSONSchema |
| L2-03 §3.2 | execution_contract 必须包含 protocol/timeout/retry_policy/idempotent/transaction_scope | SDK packager 自动生成，开发者可覆盖 |
| L2-03 §3.3 | policy 必须包含 auth_required/required_permissions/approval_required/audit_level | SDK packager 生成默认值，开发者覆盖 |
| L2-03 §C.6 | Connector 统一错误码（6 个） | SDK ConnectorError 全对齐 |

### 5.2 本 PRD 新增的 MUST（SDK 级别）

| MUST ID | 内容 | 验证方式 |
|---------|------|---------|
| SDKMUST-001 | SDK 不得修改或绕过 Capability 的三层结构，packager 输出必须严格对齐 L2-03 §3 格式 | schema 校验测试 |
| SDKMUST-002 | 所有 SDK 产生的 HTTP 请求必须包含 User-Agent: earp-sdk-py/{version} | 集成测试 |
| SDKMUST-003 | MockRuntime 不得产生任何外部网络请求 | 网络隔离测试 |
| SDKMUST-004 | schema 本地校验失败时 CLI 不得发送注册请求 | 单元测试 |
| SDKMUST-005 | 错误码必须对齐 L2-03 §8.4 定义（CAPABILITY_NOT_FOUND / SCHEMA_VALIDATION_FAILED 等） | 映射表一致性检查 |
| SDKMUST-006 | ConnectorError 必须覆盖 L2-03 §C.6 全部 6 个错误码，retryable 属性对齐 | 枚举完整性测试 |

---

## 6. 不做（Out of Scope）

| 事项 | 原因 |
|------|------|
| Capability Center Registry 的服务端实现 | 属于 Runtime 域，本 PRD 只做 SDK |
| Connector SDK | 独立依赖，本 PRD 的 ctx.connectors 只是接口抽象 |
| Capability Graph 的本地构建 | 属于 Runtime 端行为，SDK 不参与 |
| Resolution Engine 的模拟 | MockRuntime 的 invoke() 做**简化直接分发**，不经过 Resolution Engine。这是**已知限制**——Policy 检查仅在真实 Runtime 的 Resolution Engine 中执行。详见 US-04 中 MockRuntime 边界说明 |
| 生命周期 deprecate/retire CLI | 第一版 CLI 仅支持 `register` → `activate`。deprecate 命令在 v1.1 版本中补充 |
| `@capability_fn` 装饰器语法 | 第一版主推类继承 API（QueryCapability / CommandCapability）。装饰器语法作为备选 API，在 v1.1 版本中补充 |
| Multi-language SDK（Java/Go） | 第一版仅 Python |
| Capability 热加载/热更新 | 第一版仅支持冷注册 |

---

## 7. 交付物清单

```
earp-sdk-py/
├── pyproject.toml                  # 项目配置 + 依赖 + CLI entrypoint
├── capability.yaml.example         # 配置文件模板
├── README.md                       # SDK 使用说明
├── examples/
│   └── query_equipment_alarm.py    # 完整示例
├── earp_sdk/
│   ├── __init__.py                 # 公共导出
│   ├── base.py                     # Capability / QueryCapability / CommandCapability
│   ├── context.py                  # CapabilityContext
│   ├── config.py                   # capability.yaml 加载
│   ├── schema.py                   # Pydantic → JSONSchema
│   ├── decorators.py               # @capability（主推类 API 的辅助装饰器）
│   ├── contracts.py                # Execution Contract / Policy 自动生成
│   ├── errors.py                   # ConnectorError / CapabilityError
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                 # CLI 入口
│   │   └── commands.py             # register / activate / list / search
│   ├── registration/
│   │   ├── __init__.py
│   │   ├── client.py               # Registry HTTP 客户端（幂等重试）
│   │   └── packager.py             # 类 → 三层结构 JSON
│   ├── discovery/
│   │   ├── __init__.py
│   │   └── client.py               # 发现客户端（支持分页）
│   └── testing/
│       ├── __init__.py
│       ├── mock_runtime.py         # MockRuntime（set_env 支持）
│       ├── mock_connector.py       # MockConnector
│       └── fixtures.py             # pytest fixtures
└── tests/
    ├── test_base.py
    ├── test_config.py
    ├── test_schema.py
    ├── test_decorators.py
    ├── test_errors.py
    ├── test_mock_runtime.py
    ├── test_registration_client.py
    ├── test_discovery_client.py
    ├── test_cli.py
    ├── test_e2e_capability.py
    └── test_e2e_cli.py
```

---

## 8. 验收总结表

| # | 检查项 | 状态 | 备注 |
|:-:|--------|:----:|------|
| 1 | 用户故事完整性 | ✅ US-01~US-07 覆盖正常+异常+边界 | 正常(1) + 异常(2) + 边界(4) |
| 2 | 验收条件可测试性 | ✅ 15 条 AC，全部可写自动化测试 | 含集成测试 & 覆盖率 & 错误链 |
| 3 | 依赖分析完整性 | ✅ 内/外部/跨域/风险/分发均覆盖 | 含 Registry payload 契约 |
| 4 | 优先级合理性 | ✅ P0 | 其他 SDK 的依赖基础 |
| 5 | 无矛盾需求 | ✅ US-04 与 MockRuntime OOS 已明确边界 | MockRuntime invoke = 简化分发，不替代 Resolution |

---

## 9. 评审修复记录

| 编号 | 评审问题 | 修复方式 |
|:----:|---------|---------|
| P0-1 | US-04 与 MockRuntime OOS 逻辑冲突 | 已补充 MockRuntime invoke 的已知限制说明；OOS 中明确简化分发不做 Policy |
| P0-2 | Registry API payload 契约缺失 | §4.3 新增请求体/响应体 JSON Schema，含成功/失败场景 |
| P0-3 | Connector 错误码只覆盖 2/6 | US-02 补充 6 个错误码完整映射表；新增 SDKMUST-006 |
| P1-1 | AC-10/AC-11 重叠 | 已分别定义验证粒度，保留两条 |
| P1-2 | 缺少 deprecate/retire CLI | §6 OOS 新增声明，v1.1 补充 |
| P1-3 | Discovery 缺少分页 | §4.3 接口契约中新增 page/page_size 参数 |
| P1-4 | 注册缺少幂等性 | §4.4 风险表 + §7 registration client 标注幂等重试 |
| P1-5 | 边界故事偏少 | 新增 US-06（离线开发）+ US-07（多环境配置） |
| P1-6 | SDK 分发未定义 | §4.5 新增分发策略 |
| P2-3 | 错误链无 AC | AC-14 新增 |
| P2-4 | 跨 Capability 错误传播未定义 | US-04 补充错误传播语义（异常向上冒泡） |
| P2-5 | 装饰器 API 定位不明确 | §6 OOS 明确 v1 主推类继承，装饰器语法延至 v1.1 |
