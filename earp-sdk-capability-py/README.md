# EARP Capability SDK

> Python 第一版 · v0.1.0.dev0

**EARP（Enterprise AI Runtime Platform）Capability SDK** 是开发者编写、测试、注册 Capability 的 Python 工具包。它将 L2 Capability Center 规范的三层结构（Definition / Execution Contract / Policy）封装为简洁的 Python API，让开发者专注于业务逻辑。

## 安装

```bash
pip install earp-sdk-core
pip install earp-sdk-capability
```

## 快速开始

30 分钟内完成一个 Capability 的编写、测试和注册。

### Step 1：定义输入输出模型

```python
from pydantic import BaseModel

class AlarmQuery(BaseModel):
    equipment_id: str
    include_acknowledged: bool = False

class AlarmList(BaseModel):
    alarms: list[dict]
    total: int
```

### Step 2：编写 Capability

```python
from earp_sdk_capability import QueryCapability, CapabilityContext, capability

@capability(
    capability_id="query_equipment_alarm",
    name="查询设备报警",
    description="根据设备ID查询当前报警信息",
    domain="equipment",
    version="1.0.0",
)
class QueryEquipmentAlarm(QueryCapability[AlarmQuery, AlarmList]):
    async def execute(self, ctx: CapabilityContext, params: AlarmQuery) -> AlarmList:
        ctx.logger.info(f"查询设备: {params.equipment_id}")
        result = await ctx.connectors.mes.execute("query_alarms", {
            "equipment_id": params.equipment_id,
        })
        return AlarmList(**result)
```

### Step 3：本地测试

```python
import pytest
from earp_sdk_capability.testing import MockRuntime, MockConnector

@pytest.mark.asyncio
async def test_query_alarm():
    async with MockRuntime() as runtime:
        runtime.connectors.register("mes", MockConnector({
            "query_alarms": lambda p: {"alarms": [], "total": 0},
        }))
        runtime.register(QueryEquipmentAlarm)
        result = await runtime.execute("query_equipment_alarm", {
            "equipment_id": "EQ-001",
        })
        assert result.total == 0
```

### Step 4：注册到平台

```bash
earp register my_capabilities.QueryEquipmentAlarm
earp activate query_equipment_alarm
```

---

## 核心概念

### Capability（能力）

Capability 是 EARP 平台的核心资产。它封装**业务语义**，隐藏技术实现。调用者不需要知道底层是 MES、SAP 还是数据库。

```python
class QueryCapability(QueryCapability[InputT, OutputT]):
    """只读能力。无副作用，幂等。"""
    async def execute(self, ctx, params) -> OutputT: ...

class CommandCapability(CommandCapability[InputT, OutputT]):
    """写能力。可参与 Saga 事务回滚。"""
    async def execute(self, ctx, params) -> OutputT: ...
    async def compensate(self, ctx, params, result) -> None: ...
```

### Query vs Command

| | Query | Command |
|:---|:------|:--------|
| 副作用 | 无 | 有 |
| 幂等 | 是 | 否 |
| 补偿 | 不需要 | 可选实现 |
| 审计级别 | summary | detail |
| 审批 | 不需要 | 需要 |

### CapabilityContext

`execute()` 方法接收一个 `CapabilityContext`，提供：

| 属性 | 说明 |
|:-----|------|
| `ctx.connectors.<name>` | 访问外部系统的连接器 |
| `ctx.capabilities.invoke(id, params)` | 调用另一个 Capability |
| `ctx.logger` | 结构化日志 |
| `ctx.session_id` | 当前 Session |
| `ctx.user_id` | 当前用户 |

---

## 本地测试

### MockRuntime

不依赖任何外部服务，完全离线运行：

```python
async with MockRuntime() as runtime:
    # 注册 Connector mock
    runtime.connectors.register("mes", MockConnector({
        "query_alarms": lambda p: {"alarms": [], "total": 0},
    }))
    # 注册 Capability
    runtime.register(QueryEquipmentAlarm)
    # 执行
    result = await runtime.execute("query_equipment_alarm", {"equipment_id": "EQ-001"})
```

### set_env

模拟环境变量配置，不影响 `os.environ`：

```python
runtime.set_env("MES_BASE_URL", "http://localhost:9999")
runtime.get_env("MES_BASE_URL")  # "http://localhost:9999"
```

---

## 配置

### capability.yaml

```yaml
earp:
  registry:
    api_url: "http://localhost:8080"
    auto_register: false

connectors:
  mes:
    type: rest
    base_url: "${MES_BASE_URL}"
    auth:
      type: bearer
      token: "${MES_API_TOKEN}"
    timeout_ms: 5000
```

支持 `${ENV_VAR}` 环境变量插值，在运行时自动替换。

---

## CLI

```bash
# 查看帮助
earp --help

# 注册 Capability（先本地校验 schema，再发请求）
earp register my_package.MyCapability

# 激活
earp activate my_capability_id

# 列出
earp list
earp list --domain equipment

# 搜索
earp search "设备报警"
earp search "报警" --domain equipment
```

---

## 包结构

```
earp-sdk-core-py/                  # 共享基础包
└── src/earp_sdk_core/
    ├── __init__.py
    └── errors.py                   # ConnectorError(6) + CapabilityError(8)

earp-sdk-capability-py/            # 主 SDK 包
└── src/earp_sdk_capability/
    ├── base.py                     # Capability / QueryCapability / CommandCapability
    ├── context.py                  # CapabilityContext + CapLogger
    ├── config.py                   # capability.yaml 加载
    ├── schema.py                   # Pydantic → JSONSchema Draft-07
    ├── decorators.py               # @capability
    ├── contracts.py                # Execution Contract / Policy 自动生成
    ├── registration/
    │   ├── packager.py             # 类 → 三层结构 JSON
    │   └── client.py               # Registry HTTP 客户端
    ├── discovery/client.py         # 发现客户端（分页）
    ├── testing/
    │   ├── mock_runtime.py         # MockRuntime
    │   ├── mock_connector.py       # MockConnector
    │   └── fixtures.py             # pytest fixtures
    └── cli/main.py                 # CLI（4 命令）
```

---

## 开发

```bash
# 克隆后安装开发依赖
cd earp-sdk-core-py && pip install -e .
cd ../earp-sdk-capability-py && pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 查看覆盖率
pytest tests/ --cov=src/earp_sdk_capability
```

---

## 变更记录

### v0.1.0.dev0（2026-07-12）

- 初始开发版本
- Capability / QueryCapability / CommandCapability 基类
- Pydantic → JSONSchema Draft-07 自动推导
- @capability 装饰器
- Packager：Python 类 → L2-03 三层结构 JSON
- MockRuntime + MockConnector 本地测试框架
- Registry 注册/激活客户端（HTTP）
- Discovery 搜索/发现客户端（分页）
- CLI：register / activate / list / search
- capability.yaml 配置 + 环境变量插值
- 78 个测试，核心模块覆盖率 ~98%

### 已知限制

- `@capability_fn` 装饰器在 v1.1 版本中补充
- `deprecate` / `retire` CLI 在 v1.1 版本中补充
- Registry 服务端由 Runtime 域实现
