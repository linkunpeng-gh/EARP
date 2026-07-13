# Phase 3 — Capability SDK 实现

## Phase 2 确认

| 检查项 | 结果 |
|--------|:----:|
| L2 规范 MUST 变更 | ❌ 不需要 |
| 跨域接口契约 | ✅ 已在 PRD §4.3 定义 |
| ADR | ❌ 不需要 |
| 可进入 Phase 3 | ✅ |

## 当前进度

| Task | 状态 | 验收 |
|:----:|:----:|:----:|
| 001 — 包脚手架 + 基类 | **done** | ✅ 10 项检查全通过 |
| 002 — 配置模块 | **done** | ✅ 4 项检查全通过 | |
| 003 — Schema 自动生成 | **done** | ✅ 11 项测试全通过 | |
| 004 — Decorator + 三层结构包装器 | **done** | ✅ 11 项测试全通过 | |
| 005 — MockRuntime 测试框架 | **done** | ✅ 14 项测试全通过 |
| 006 — 注册客户端 | **done** | ✅ 6 项测试全通过 |
| 007 — 发现客户端 | **done** | ✅ 8 项测试全通过 |
| 008 — CLI 工具 | **done** | ✅ 13 项测试全通过 |
| 009 — 完整示例 + 端到端测试 | **done** | ✅ 15 项测试全通过 |

## Task 001 交付物清单

```
libs/earp-sdk-core-py/                   # 共享基础包
├── pyproject.toml
└── src/earp_sdk_core/
    ├── __init__.py                  # 导出 ConnectorError, CapabilityError
    └── errors.py                    # 6 个 ConnectorErrorCode + 8 个 CapabilityErrorCode

libs/earp-sdk-capability-py/             # Capability SDK 本体
├── pyproject.toml
└── src/earp_sdk_capability/
    ├── __init__.py                  # 公共导出（依赖 earp_sdk_core）
    ├── base.py                      # Capability / QueryCapability / CommandCapability
    ├── context.py                   # CapabilityContext + CapLogger
    ├── schema.py                    # schema_of() Pydantic → JSONSchema Draft-07
    ├── decorators.py                # @capability 装饰器
    ├── errors.py                    # ❌ 删除（已移至 core）
    ├── cli/main.py                  # CLI 入口（4 个命令，stub）
    ├── registration/__init__.py
    ├── discovery/__init__.py
    └── testing/__init__.py
```

## Task 001 验收结果

| AC | 检查项 | 结果 |
|:--:|--------|:----:|
| — | pyproject.toml 可被 pip install -e . 安装 | ✅ |
| — | `from earp_sdk import Capability, QueryCapability, CommandCapability, CapabilityContext` 不报错 | ✅ |
| — | QueryCapability.capability_type == "query" | ✅ |
| — | CommandCapability.capability_type == "command" | ✅ |
| — | CommandCapability 声明空的 compensate 方法 | ✅ |
| — | CapabilityContext 包含所有必需字段 | ✅ |
| — | InputT / OutputT 类型参数约束为 BaseModel | ✅ |
| — | schema_of() 生成 Draft-07 JSONSchema | ✅ |
| — | ConnectorError 覆盖 L2-03 §C.6 全部 6 个错误码 | ✅ |
| — | @capability 装饰器正确赋值 | ✅ |
