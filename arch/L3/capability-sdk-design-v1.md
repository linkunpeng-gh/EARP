# Capability SDK 设计 v1

> **定位**：L3 — 实现层设计。定义 Capability SDK 的接口契约、开发体验、测试框架和注册流程。
> **目标语言**：Python（第一版）
> **依赖**：L2-03-CAPABILITY v1.1（Capability Center 规范）

---

## 1. 设计目标

### 1.1 SDK 要解决什么

| 问题 | SDK 的应对 |
|------|-----------|
| 开发者必须理解三层结构 + Resolution Engine + Registry 才能写一个 Capability | SDK 隐藏平台细节，开发者只关心业务逻辑 |
| Capability 需要声明 input_schema / output_schema，手写 JSONSchema 很繁琐 | SDK 从 Python 类型注解自动推导 |
| 写完 Capability 需要部署到完整平台才能测试 | SDK 提供本地 mock Runtime，不依赖任何外部服务 |
| 每个 Capability 都需要写注册脚本 | SDK 提供一行命令注册 |

### 1.2 SDK 不做什么

- ❌ 不负责 Capability 的运行（由 Execution Runtime 负责）
- ❌ 不负责 Policy 评估（由 Policy Center 负责）
- ❌ 不负责 Planner 决策（由 Planner 负责）
- ❌ 不自动补偿（但提供补偿回调接口）

---

## 2. 核心接口

### 2.1 Capability 类的契约

```python
# earp_sdk/__init__.py

from abc import ABC, abstractmethod
from typing import Generic, TypeVar
from pydantic import BaseModel

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class CapabilityContext:
    """
    每个 Capability 执行时传入的运行时上下文。
    开发者通过 ctx 访问连接器、日志、Session 信息。
    """
    session_id: str
    request_id: str
    user_id: str | None
    tenant_id: str | None
    connectors: "ConnectorRegistry"
    capabilities: "CapabilityRegistry"   # 用于 Capability 间调用
    logger: "CapLogger"
    metadata: dict


class Capability(ABC, Generic[InputT, OutputT]):
    """
    Capability 基类。
    开发者继承此类，实现 execute 方法即可。
    SDK 负责：Schema 推导、Contract 生成、Policy 绑定。
    """

    # ===== 必需字段（开发者 MUST 声明） =====

    capability_id: str = ""       # 必填
    name: str = ""                # 必填
    description: str = ""         # 必填
    domain: str = ""              # 必填
    capability_type: str = ""     # "query" | "command"

    # ===== 可选字段（SDK 提供默认值） =====

    version: str = "0.1.0"
    tags: list[str] = []

    # ===== 执行入口 =====

    @abstractmethod
    async def execute(
        self,
        ctx: CapabilityContext,
        params: InputT,
    ) -> OutputT:
        """业务逻辑入口。开发者在这里写真正的代码。"""
        ...
```

> **异步优先原则**：`execute` 统一使用 `async def`。如果开发者实现的是纯同步逻辑（如简单 SQL 查询），SDK 在注册时自动将其包装为异步调用，开发者无需关心。

### 2.2 Query 与 Command 的区分

```python
from earp_sdk import Capability


class QueryCapability(Capability[InputT, OutputT]):
    """
    只读 Capability。
    SDK 自动设置 capability_type="query"。
    自动标记 idempotent=True、supports_compensation=False。
    """
    capability_type = "query"

    async def execute(self, ctx, params) -> OutputT:
        ...


class CommandCapability(Capability[InputT, OutputT]):
    """
    写 Capability。
    SDK 自动设置 capability_type="command"。
    必须实现 compensate 方法（可空实现）。
    """
    capability_type = "command"

    @abstractmethod
    async def execute(self, ctx, params) -> OutputT:
        ...

    async def compensate(
        self,
        ctx: CapabilityContext,
        params: InputT,
        result: OutputT,
    ) -> None:
        """
        补偿操作。Saga 回滚时调用。
        默认是空实现（不补偿），Command 建议实现。
        """
        pass
```

### 2.3 Capability 间调用

一个 Capability 内部可以通过 `ctx.capabilities.invoke()` 调用另一个 Capability，SDK 会自动路由到 Capability Center：

```python
async def execute(self, ctx, params) -> OutputT:
    # 调用另一个 Capability（经过 Resolution Engine 的完整路径）
    intermediate = await ctx.capabilities.invoke(
        "normalize_equipment_id",
        params={"raw_id": params.equipment_id},
    )
    params.equipment_id = intermediate["normalized_id"]

    # 用标准化后的参数继续执行
    result = await ctx.connectors.mes.execute("query_alarms", ...)
    return result
```

> **设计决策**：统一通过 `ctx.capabilities.invoke(id, params)` 调用，不走直接类调用。原因：
> - 保持 Resolution Engine 作为单一入口，Policy 检查不会被跳过
> - 开发者侧不感知调用链（如果 B 被替换为 substitutes，调用方也不知道）
> - 方便日后加 tracing 和审计

### 2.4 示例：完整的一个 Capability

```python
from pydantic import BaseModel
from earp_sdk import QueryCapability, CapabilityContext, capability


# --- 1. 定义输入输出模型 ---

class EquipmentAlarmQuery(BaseModel):
    equipment_id: str
    include_acknowledged: bool = False

class AlarmItem(BaseModel):
    alarm_id: str
    alarm_code: str
    message: str
    severity: str  # "critical" | "major" | "minor"
    timestamp: str

class EquipmentAlarmList(BaseModel):
    alarms: list[AlarmItem]
    total_count: int


# --- 2. 实现 Capability ---

@capability(
    capability_id="query_equipment_alarm",
    name="查询设备报警",
    description="根据设备ID查询当前报警信息",
    domain="equipment",
    version="1.0.0",
    tags=["equipment", "alarm", "monitoring"],
)
class QueryEquipmentAlarm(QueryCapability[EquipmentAlarmQuery, EquipmentAlarmList]):

    async def execute(
        self,
        ctx: CapabilityContext,
        params: EquipmentAlarmQuery,
    ) -> EquipmentAlarmList:
        ctx.logger.info(f"查询设备报警: {params.equipment_id}")

        # 通过连接器调用外部系统
        result = await ctx.connectors.mes.execute(
            operation="query_alarms",
            params={
                "equipment_id": params.equipment_id,
                "include_acknowledged": params.include_acknowledged,
            },
        )
        return EquipmentAlarmList(**result)
```

---

## 3. 自动派生机制

SDK 在开发者提交注册时自动完成以下工作：

### 3.1 Schema 自动生成

```python
# 从 Python 类型注解自动生成 JSONSchema
input_schema = pydantic_to_jsonschema(EquipmentAlarmQuery)
output_schema = pydantic_to_jsonschema(EquipmentAlarmList)

# 开发者不需要手写 JSONSchema
```

### 3.2 Execution Contract 自动生成

```python
# SDK 根据 capability_type 和 execute 方法特征自动推断
execution_contract = {
    "protocol": "sdk",           # SDK 类型的 Capability
    "timeout": 30000,            # 默认 30 秒
    "retry_policy": {
        "max_attempts": 0,       # SDK Capability 默认不重试
        "backoff": "exponential",
    },
    "idempotent": True,          # Query 自动 true，Command 由开发者指定
    "transaction_scope": "none",
    "supports_compensation": hasattr(cls, "compensate") and cls.compensate is not CommandCapability.compensate,
    "compensating_capability": None,
}
```

### 3.3 Policy Layer 默认值

```python
# 开发者可以在 @capability 中覆盖
policy = {
    "auth_required": True,
    "required_permissions": [],  # 开发者需明确声明
    "approval_required": False,  # Command 默认 False，可覆盖
    "audit_level": "summary",    # Command 自动设为 "detail"
    "constraints": [],
}
```

---

## 4. 配置管理

### 4.1 配置文件

`capability.yaml` 放在 SDK 包根目录：

```yaml
# capability.yaml — SDK 和 Connector 等配置
earp:
  registry:
    api_url: "http://localhost:8080"      # Capability Center 地址
    auto_register: false                   # 自动注册（debug 模式开启）
  
  runtime:
    default_timeout_ms: 30000
    max_retries: 0

connectors:
  mes:
    type: rest
    base_url: "${MES_BASE_URL}"            # 支持环境变量插值
    auth:
      type: bearer
      token: "${MES_API_TOKEN}"
    timeout_ms: 5000
    retry:
      max_attempts: 3
      backoff: exponential
  
  database:
    type: jdbc
    dsn: "${DB_DSN}"
    pool_size: 10
```

### 4.2 配置解析顺序

```
capability.yaml（项目级）→ 环境变量覆盖（${VAR}）→ CLI 参数覆盖
```

---

## 5. 开发者体验流程

```
开发一个 Capability 的标准流程：

  Step 1: 定义输入输出 Pydantic 模型
  Step 2: 继承 QueryCapability / CommandCapability
  Step 3: 实现 execute 方法（和可选的 compensate）
  Step 4: 本地测试（mock runtime）
  Step 5: 注册到 Capability Center（一行命令）
```

### 5.1 本地测试

```python
# tests/test_query_equipment_alarm.py

import pytest
from earp_sdk.testing import MockRuntime, MockConnector

from my_capabilities.equipment import QueryEquipmentAlarm, EquipmentAlarmQuery


@pytest.mark.asyncio
async def test_query_alarm_success():
    # 1. 创建 mock runtime
    runtime = MockRuntime()

    # 2. 注册 mock connector
    runtime.connectors.register(
        "mes",
        MockConnector({
            "query_alarms": lambda params: {
                "alarms": [
                    {
                        "alarm_id": "ALM-001",
                        "alarm_code": "OVTEMP",
                        "message": "温度超标",
                        "severity": "critical",
                        "timestamp": "2026-07-12T10:00:00Z",
                    }
                ],
                "total_count": 1,
            },
        }),
    )

    # 3. 注册 Capability
    runtime.register(QueryEquipmentAlarm)

    # 4. 执行（不经过 Resolution Engine，直接调用）
    result = await runtime.execute(
        "query_equipment_alarm",
        EquipmentAlarmQuery(equipment_id="EQ-001"),
    )

    assert result.total_count == 1
    assert result.alarms[0].alarm_code == "OVTEMP"


@pytest.mark.asyncio
async def test_query_alarm_empty():
    runtime = MockRuntime()
    runtime.connectors.register(
        "mes",
        MockConnector({"query_alarms": lambda params: {"alarms": [], "total_count": 0}}),
    )
    runtime.register(QueryEquipmentAlarm)

    result = await runtime.execute(
        "query_equipment_alarm",
        EquipmentAlarmQuery(equipment_id="EQ-NONEXIST"),
    )
    assert result.total_count == 0
    assert len(result.alarms) == 0
```

### 5.2 注册

```python
# 一行命令注册到 Capability Center
# CLI 方式（推荐）

$ earp capability register my_capabilities.equipment.QueryEquipmentAlarm
  ✅ Schema 校验通过
  ✅ Policy 校验通过
  ✅ Capability "query_equipment_alarm" (v1.0.0) 已注册
  📍 状态: draft（需要手动激活）

$ earp capability activate query_equipment_alarm
  ✅ Capability 已激活
```

```python
# SDK 编程方式

from earp_sdk.registration import CapabilityRegistryClient

client = CapabilityRegistryClient()

# 准备三层结构
capability_package = client.prepare(QueryEquipmentAlarm)

# 注册（返回 draft 状态）
result = client.register(capability_package)
print(f"注册成功: {result.capability_id} v{result.version}")

# 激活
client.activate("query_equipment_alarm")
```

---

## 6. 装饰器语法（备选 API）

类继承是主推荐方式。对于简单场景，提供装饰器语法：

```python
from earp_sdk import capability_fn


@capability_fn(
    capability_id="ping",
    name="健康检查",
    domain="system",
    type="query",
    version="1.0.0",
)
async def ping(ctx: CapabilityContext, params: PingInput) -> PingOutput:
    return PingOutput(status="ok", timestamp=datetime.now().isoformat())
```

装饰器背后仍然使用相同的 SDK 基础设施，只是减少了类定义的开销。

---

## 7. Capability 发现接口（开发者侧）

SDK 也提供 Capability 发现能力——开发者可以查询当前可用的 Capability：

```python
from earp_sdk.discovery import CapabilityDiscoveryClient

client = CapabilityDiscoveryClient()

# 语义搜索
results = await client.search("查询设备报警", domain="equipment")
for cap in results:
    print(f"{cap.capability_id} ({cap.confidence:.2f})")

# 按领域浏览
equipment_caps = await client.list_by_domain("equipment")
```

---

## 8. SDK 包结构

```
earp-sdk-core-py/                  # 共享基础包（所有 SDK 依赖）
├── pyproject.toml
└── src/earp_sdk_core/
    ├── __init__.py                 # 导出: ConnectorError, CapabilityError
    └── errors.py                   # ConnectorErrorCode(6) + CapabilityErrorCode(8)

earp-sdk-capability-py/            # Capability SDK
├── pyproject.toml                  # 依赖: earp-sdk-core, pydantic, httpx, rich, typer
├── capability.yaml.example
├── README.md
├── examples/
│   └── query_equipment_alarm.py
├── src/earp_sdk_capability/
│   ├── __init__.py                 # 公共导出
│   ├── base.py                     # Capability / QueryCapability / CommandCapability
│   ├── context.py                  # CapabilityContext
│   ├── schema.py                   # Pydantic → JSONSchema
│   ├── decorators.py               # @capability
│   ├── config.py                   # capability.yaml 加载与解析
│   ├── contracts.py                # Execution Contract / Policy 自动生成
│   ├── registration/
│   │   ├── __init__.py
│   │   ├── client.py               # Registry HTTP 客户端（幂等重试）
│   │   └── packager.py             # 类 → 三层结构 JSON
│   ├── discovery/
│   │   ├── __init__.py
│   │   └── client.py               # 发现客户端（支持分页）
│   ├── testing/
│   │   ├── __init__.py
│   │   ├── mock_runtime.py         # MockRuntime（set_env 支持）
│   │   ├── mock_connector.py       # MockConnector
│   │   └── fixtures.py             # pytest fixtures
│   └── cli/
│       ├── __init__.py
│       ├── main.py                 # CLI 入口
│       └── commands.py             # register / activate / list / search
└── tests/
    ├── test_base.py
    └── ...
```

---

## 9. 与现有架构的映射

| 架构层 | SDK 中对应 | 说明 |
|--------|-----------|------|
| Capability Definition | `@capability` 装饰器 + 类声明 | `capability_id` / `name` / `version` 等元数据 |
| Definition: input_schema | `InputT` 类型参数（Pydantic model） | SDK 自动转 JSONSchema |
| Definition: output_schema | `OutputT` 类型参数（Pydantic model） | SDK 自动转 JSONSchema |
| Execution Contract | SDK 自动生成 + 装饰器参数覆盖 | `timeout`, `retry_policy`, `idempotent` 等 |
| Policy Layer | 装饰器参数声明 + SDK 默认值 | `auth_required`, `required_permissions` 等 |
| Connector | `ctx.connectors.*` | Capability 内部通过 context 访问 |
| 跨 Capability 调用 | `ctx.capabilities.invoke()` | 始终经过 Resolution Engine |
| Resolution Engine | ❌ SDK 不处理 | Runtime 侧负责 |
| Registry | `registration.client` | SDK 负责推送三层结构到 Registry |
| 配置 | `capability.yaml` | yaml + 环境变量插值 + CLI 覆盖 |
