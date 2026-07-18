# PRD-2026-017 v1.0

## Plugin Manager 完善 — 插件状态跟踪 + 健康检查 + Manifest 验证

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-017 |
| **Feature** | PluginManager 增加插件状态机（installing/active/error/inactive）、load_all 后健康检查、register 时 manifest 验证 |
| **优先级** | **P1** |
| **参考** | Dify core/plugin/plugin_service.py (PluginInstallation 状态)、core/plugin/entities/plugin.py (PluginDeclaration) |
| **版本** | v1.0 |

---

## 1. 背景

PluginManager 当前只有 register/load/unload 三种操作。缺少状态跟踪——无法知道一个 Plugin 是正在加载、已激活还是出错。对标 Dify 的 `PluginInstallation.status` 和 `PluginDeclaration` 验证模式。

## 2. 范围

| # | 特性 | Dify 参考 | EARP 实现 |
|:-:|:-----|:----------|:---------|
| 1 | PluginStatus 枚举 | `PluginInstallation.status` | `str, Enum`: installing/active/error/inactive |
| 2 | 健康检查 | `PluginInstaller.health_check` | `Plugin.health_check()` → bool (同 `on_load` 后自动执行) |
| 3 | Manifest 验证 | `PluginDeclaration` fields | `register()` 时验证 capability_id/name/version/extension_point 必需字段 |

## 3. 验收条件

| ID | 描述 |
|:--:|:-----|
| AC-01 | `Plugin` 基类新增 `status: PluginStatus = PluginStatus.INACTIVE`；register 后 → INSTALLING → on_load 成功后 → ACTIVE，失败 → ERROR |
| AC-02 | `Plugin.health_check()` 返回 bool，默认 True；PluginManager.load_all 后自动调用；失败 → status=ERROR + audit |
| AC-03 | `PluginManager.register()` 验证必需字段（name/capability_id/version/extension_point）非空，缺失→raise ValueError |
| AC-04 | 现有 26 tests 无回归 + ≥5 new tests |

## 4. 产出物

| 文件 | 变更 |
|:-----|:----:|
| `base.py` | +PluginStatus, +status 字段, +health_check() |
| `manager.py` | register() 验证字段, load_all() 健康检查 + status 变更 |
| `__init__.py` | 导出 PluginStatus |
| `tests/test_sandbox.py` | +5 tests |
