# Changelog

All notable changes to the EARP Capability SDK will be documented in this file.

## [0.1.0.dev0] — 2026-07-12

### Added

- **Capability 基类体系** — `Capability` / `QueryCapability` / `CommandCapability`，支持泛型 InputT/OutputT 类型注解
- **@capability 装饰器** — 声明式 Capability 元数据注入
- **三层结构自动生成** — Packager 将 Python 类转换为 L2-03 三层 JSON（Definition / Execution Contract / Policy）
- **MockRuntime 测试框架** — 完全离线执行 Capability，支持 Connector mock 和跨 Capability 调用
- **capability.yaml 配置** — 支持 `${ENV_VAR}` 环境变量插值，多级配置结构
- **Schema 自动推导** — Pydantic BaseModel → JSONSchema Draft-07，含 validate_input() 校验
- **Registry 客户端** — Capability 注册（POST）和激活（PATCH），幂等重试
- **Discovery 客户端** — 语义搜索和领域浏览，分页支持
- **CLI** — `earp register` / `activate` / `list` / `search`，注册前本地 schema 校验
- **错误码对齐** — ConnectorError 6 码（L2-03 §C.6）+ CapabilityError 8 码（L2-03 §8.4），保留原始异常链

### Known Limitations

- `@capability_fn` 装饰器语法未实现（v1.1）
- `deprecate` / `retire` CLI 未实现（v1.1）
- Registry 服务端依赖 Runtime 域实现
