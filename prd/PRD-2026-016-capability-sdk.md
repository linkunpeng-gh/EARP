# PRD-2026-016 v1.0

## Capability SDK — 补齐 Spec v1.3 缺口

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-016 |
| **Feature** | Capability SDK 对齐 Capability Spec v1.3：补 status 字段、fallback_capability_id、CapabilityResult 类型 |
| **优先级** | **P0** |
| **版本** | v1.0 |

---

## 1. 背景

Capability SDK 已有 78 tests 通过，base/contracts/context/decorators/registration/discovery/cli/testing 完整。但与 Capability Spec v1.3 有 3 个缺口。

## 2. 范围

| # | 缺口 | Spec 要求 | 当前状态 | 变更 |
|:-:|:-----|:----------|:---------|:-----|
| 1 | `status` 字段 | MUST: `draft \| active \| deprecated \| retired` | base.py 无此字段 | +status 到 Capability + @capability decorator |
| 2 | `fallback_capability_id` | MUST: Capability 失败时自动切换 | 仅在 ConnectorRetryConfig | +到 Capability 基类 + contracts.py |
| 3 | `CapabilityResult` | 无显式要求，对标 Dify NodeRunResult | 无统一返回类型 | 新增 dataclass |

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | `Capability` 基类新增 `status` 字段，默认 `"draft"`；`@capability` decorator 支持传参 |
| AC-02 | `Capability` 基类新增 `fallback_capability_id: str = ""`；contracts.py 的 `generate_contract` 输出包含此字段 |
| AC-03 | 新增 `CapabilityResult` dataclass（status/output/error/usage），execute() 推荐但不强制使用 |
| AC-04 | 现有 78 tests 无回归 + 新增 ≥5 tests |

## 4. 产出物

| 文件 | 变更 |
|:-----|:----:|
| `base.py` | +status, +fallback_capability_id |
| `decorators.py` | +status, +fallback_capability_id 参数 |
| `contracts.py` | ExecutionContract 输出包含 fallback_capability_id |
| `entities.py` (新建) | CapabilityResult dataclass |
| `__init__.py` | 导出新符号 |
| `tests/test_base.py` (新建) | +5 tests |
