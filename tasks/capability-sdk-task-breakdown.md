# Capability SDK 实现 — Task 拆解

> **来源**：L3 设计文档 `arch/L3/capability-sdk-design-v1.md`
> **阶段**：Phase 3 预拆解（等待 Gate 0 批准后进入正式 Phase 1-3）
> **依赖**：L2-03-CAPABILITY v1.1
> **语言**：Python 3.12+
> **包名**：`earp-sdk-py`

---

## 依赖图

```
Task 1 (骨架+基类) ──▶ Task 2 (配置) ──▶ Task 4 (装饰器+包装)
                                        │
Task 3 (Schema生成) ──────────────────────▶ Task 4
                                        │
                                        ▼ Task 5 (MockRuntime) ──▶ Task 9 (集成测试)
                                        │                           ▲
                                        ▼ Task 6 (注册客户端) ────────┘
                                        ▼ Task 7 (发现客户端)
                                        ▼ Task 8 (CLI) ───────────────┘
```

- 蓝色箭头：依赖前置
- Task 5/6/7/8 可并行开发（都只依赖 Task 4）
- Task 9 是终点，依赖所有前置

---

## Task 清单

### Task 001 — 包脚手架 + 基类

| 字段 | 值 |
|------|-----|
| **标题** | 包脚手架与基类 |
| **子标题** | pyproject.toml、包结构、Capability/QueryCapability/CommandCapability/CapabilityContext**
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第2章 |
| **产出目录** | `libs/earp-sdk-core-py/` + `libs/earp-sdk-capability-py/` |

**acceptance_criteria：**
- `earp-sdk-core-py` 和 `earp-sdk-capability-py` 两个包都可 `pip install -e .`
- `from earp_sdk_core import ConnectorError, CapabilityError` 不报错
- `from earp_sdk_capability import Capability, QueryCapability, CommandCapability, CapabilityContext` 不报错
- QueryCapability 的 `capability_type` 默认为 `"query"`
- CommandCapability 的 `capability_type` 默认为 `"command"`
- CommandCapability 声明空的 `compensate` 方法
- CapabilityContext 包含 `session_id`、`request_id`、`connectors`、`capabilities`、`logger` 字段
- `InputT` / `OutputT` 类型参数约束为 `bound=BaseModel`

**修改的文件：**
```
libs/earp-sdk-core-py/pyproject.toml
libs/earp-sdk-core-py/src/earp_sdk_core/__init__.py
libs/earp-sdk-core-py/src/earp_sdk_core/errors.py
libs/earp-sdk-capability-py/pyproject.toml
libs/earp-sdk-capability-py/src/earp_sdk_capability/__init__.py
libs/earp-sdk-capability-py/src/earp_sdk_capability/base.py
libs/earp-sdk-capability-py/src/earp_sdk_capability/context.py
```

---

### Task 002 — 配置模块

| 字段 | 值 |
|------|-----|
| **标题** | 配置模块 |
| **子标题** | capability.yaml 加载、环境变量插值、配置模型 |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第4章 |
| **依赖** | Task 001 |

**acceptance_criteria：**
- 加载 `capability.yaml` 文件存在则读取，不存在使用默认配置
- 支持 `${ENV_VAR}` 环境变量插值（如 `${MES_BASE_URL}`）
- 支持嵌套配置结构（registry / runtime / connectors 等层级）
- 提供 `Config` 数据类，类型安全
- env var 不存在时抛出明确错误（含变量名）
- CLI 参数覆盖优先级 > 环境变量 > yaml

**修改的文件：**
```
earp-sdk-py/earp_sdk/config.py
earp-sdk-py/capability.yaml.example
```

---

### Task 003 — Schema 自动生成

| 字段 | 值 |
|------|-----|
| **标题** | Schema 自动生成 |
| **子标题** | Pydantic → JSONSchema 转换、类型校验 |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第3.1节 |
| **依赖** | Task 001 |

**acceptance_criteria：**
- 输入任意 Pydantic BaseModel → 输出 JSONSchema（Python dict）
- 支持嵌套模型（如 `EquipmentAlarmList` 含 `list[AlarmItem]`）
- 输出符合 JSONSchema Draft-07
- 支持可选字段（`field(default=...)` → JSON 中标记 optional）
- 提供 `schema_of(model: type[BaseModel]) -> dict` 公共函数
- 单元测试：覆盖基础类型（str/int/bool/float/list/dict/Optional）

**修改的文件：**
```
earp-sdk-py/earp_sdk/schema.py
```

---

### Task 004 — Decorator + 三层结构包装器

| 字段 | 值 |
|------|-----|
| **标题** | Decorator 与三层结构包装 |
| **子标题** | @capability 装饰器、@capability_fn 装饰器、Capability 类 → 三层结构 JSON |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第2章 + 第3章 + 第6章 |
| **依赖** | Task 001, Task 002, Task 003 |

**acceptance_criteria：**
- `@capability(...)` 装饰器能接受 `capability_id`、`name`、`description`、`domain`、`version`、`tags` 参数
- 装饰后的类仍能被 `pytest` 和 `isinstance` 正常使用
- `@capability_fn(...)` 装饰纯函数为 Capability 实例
- `packager.py` 接受 Capability 类 → 输出符合 L2 规范的三层结构 dict
  - Definition Layer: capability_id, name, description, domain, version, tags, input_schema, output_schema, capability_type
  - Execution Contract Layer: protocol, timeout, retry_policy, idempotent, transaction_scope, supports_compensation, compensating_capability
  - Policy Layer: auth_required, required_permissions, approval_required, audit_level, constraints
- schema 由 Task 003 自动生成（非手动填写）
- Execution Contract 从 capability_type 自动推断
- 未标记 `@capability` 的 Capability 子类也能被 packager 处理（仅缺装饰器参数时使用默认值）

**修改的文件：**
```
earp-sdk-py/earp_sdk/decorators.py
earp-sdk-py/earp_sdk/contracts.py
earp-sdk-py/earp_sdk/registration/packager.py
```

---

### Task 005 — MockRuntime + MockConnector 测试框架

| 字段 | 值 |
|------|-----|
| **标题** | MockRuntime 测试框架 |
| **子标题** | MockRuntime、MockConnector、pytest fixtures |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第5.1节 |
| **依赖** | Task 004 |

**acceptance_criteria：**
- `MockRuntime.register(cls)` 注册 Capability 类到 mock 环境
- `MockRuntime.execute(capability_id, params)` 本地执行 Capability（不走 Resolution Engine）
- 支持 `async with runtime:` 上下文管理
- `MockConnector` 注册时传入 `{operation_name: handler_fn}` 映射
- handler_fn 支持 async 和 sync 两种签名
- 跨 Capability 调用 `ctx.capabilities.invoke(id, params)` 在 mock 环境中也能工作
- 提供 `pytest.fixture` 一键创建空的 MockRuntime

**修改的文件：**
```
earp-sdk-py/earp_sdk/testing/__init__.py
earp-sdk-py/earp_sdk/testing/mock_runtime.py
earp-sdk-py/earp_sdk/testing/mock_connector.py
earp-sdk-py/earp_sdk/testing/fixtures.py
```

---

### Task 006 — 注册客户端

| 字段 | 值 |
|------|-----|
| **标题** | Capability 注册客户端 |
| **子标题** | HTTP 客户端、prepare → register → activate 流程 |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第5.2节 |
| **依赖** | Task 004, Task 002 |

**acceptance_criteria：**
- `CapabilityRegistryClient.prepare(cls)` 调用 Task 004 的 packager 生成三层结构
- `CapabilityRegistryClient.register(package)` 发送 POST 到 Capability Center 的 `/capabilities` 端点
- `CapabilityRegistryClient.activate(capability_id)` 发送状态变更请求
- 支持配置 base_url（从 config 读取）
- 请求失败时抛出 `RegistryError`，包含 HTTP 状态码和响应 body
- register 返回注册结果（含 capability_id、version、status）

**修改的文件：**
```
earp-sdk-py/earp_sdk/registration/__init__.py
earp-sdk-py/earp_sdk/registration/client.py
```

---

### Task 007 — 发现客户端

| 字段 | 值 |
|------|-----|
| **标题** | Capability 发现客户端 |
| **子标题** | 语义搜索、领域浏览 |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第7章 |
| **依赖** | Task 004, Task 002 |

**acceptance_criteria：**
- `CapabilityDiscoveryClient.search(query, domain=None)` 发送 GET 请求到 Capability Center
- `CapabilityDiscoveryClient.list_by_domain(domain)` 按领域列出所有 Capability
- 返回结果包含 capability_id、name、description、version、confidence（仅 search）
- 支持分页参数（page、page_size）
- 空结果返回空列表而非 None

**修改的文件：**
```
earp-sdk-py/earp_sdk/discovery/__init__.py
earp-sdk-py/earp_sdk/discovery/client.py
```

---

### Task 008 — CLI 工具

| 字段 | 值 |
|------|-----|
| **标题** | CLI 工具 |
| **子标题** | earp capability register/activate/list/search |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第5.2节 |
| **依赖** | Task 006, Task 007, Task 002 |

**acceptance_criteria：**
- `earp capability register <module_path>` — 注册 Capability
- `earp capability activate <capability_id>` — 激活
- `earp capability list [--domain]` — 列出
- `earp capability search <query>` — 搜索
- 输出使用表格/颜色格式化（rich 或 tabulate）
- 错误时输出人类可读的错误信息（非原始 traceback）
- 支持 `--config` 指定配置文件路径
- 通过 `pyproject.toml [project.scripts]` 注册为可执行命令

**修改的文件：**
```
earp-sdk-py/pyproject.toml (scripts entry)
earp-sdk-py/earp_sdk/cli/__init__.py
earp-sdk-py/earp_sdk/cli/main.py
earp-sdk-py/earp_sdk/cli/commands.py
```

---

### Task 009 — 完整示例 + 端到端测试

| 字段 | 值 |
|------|-----|
| **标题** | 完整示例与端到端测试 |
| **子标题** | 一个完整的 Capability 示例、走通测试→注册全流程 |
| **输入** | `arch/L3/capability-sdk-design-v1.md` 第2.4节 + 全部前述 Task |
| **依赖** | Task 001-008（全部） |

**acceptance_criteria：**
- 实现 `examples/query_equipment_alarm.py`：完整的 Capability（定义 + 输入输出模型 + execute）
- 实现 `examples/capability.yaml`：配置文件示例
- 实现 `tests/test_e2e_capability.py`：使用 MockRuntime 测试该 Capability
  - 测试正常执行路径
  - 测试空结果路径
  - 测试 connector 错误路径
- 实现 `tests/test_e2e_cli.py`：CLI 命令的端到端测试（使用 mock HTTP server）
- 所有测试通过（`pytest tests/` 全绿）
- `pip install -e . && earp capability list` 不报错

**修改的文件：**
```
earp-sdk-py/examples/query_equipment_alarm.py
earp-sdk-py/examples/capability.yaml
earp-sdk-py/examples/__init__.py
earp-sdk-py/tests/test_e2e_capability.py
earp-sdk-py/tests/test_e2e_cli.py
```

---

## Task 拆解说明

| 维度 | 说明 |
|------|------|
| **粒度** | 每个 Task 可独立发 PR，独立测试，审查时长 ≤ 30 分钟 |
| **依赖** | 按依赖图先执行前置 Task（001→002→003→004→005/006/007/008→009） |
| **并行** | Task 005/006/007/008 在 Task 004 完成后可并行执行 |
| **工作量** | 预估每个 Task 0.5-1 天（Python 代码） |
| **验收** | 每个 Task 完成后必须跑通该 Task 的单元测试 |

---

## 下一步：走 Phase 0 → Gate 0

1. **Phase 0**：PM Agent 将本文转化为 PRD（补充业务价值描述、ROI、风险）
2. **Gate 0**：人工验收 PRD + Task 拆解 →
3. **Phase 1**：Arch Agent 评估是否有架构影响
4. **Phase 2**：Spec Agent 判断是否需要更新 L2 规范
5. **Phase 3**：Impl Agent 按 Task 依赖顺序逐个实现
