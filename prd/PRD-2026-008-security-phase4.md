# PRD-2026-008 v1.1

## Security Phase 4 — Plugin 沙箱（权限执行 + Process 隔离）

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-008 |
| **Feature** | Plugin 权限强制执行 + subprocess 隔离 + 加载/卸载审计 |
| **对齐规范** | Security Spec v1.1 §7.1–§7.2 |
| **优先级** | **P0** |
| **版本** | v1.2 |
| **日期** | 2026-07-15 |

> **v1.1 变更**：改用 JSON 替代 pickle（P0-1）；明确 Phase 4 为声明级检查、自动拦截延 Phase 5+（P0-2）；subprocess 用 killpg 杀进程组（P0-3）；max_memory_mb 标注 Linux-only（P1-1）；run() 方法约定文档化（P1-2）；审计事件字段补全（P2-1）。

---

## 1. 背景

当前 Plugin SDK 已有 `Permission` 枚举和 `Plugin.permissions` 声明字段，但权限声明仅在校验阶段检查有效性，尚未在运行时强制执行。Security Spec §7.2 定义了三级隔离：Phase 1 None（当前），Phase 2 Process，Phase 3 Sandbox。Phase 4 落地 Process 级别隔离 + 声明级权限执行。

## 2. 用户故事

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | `PermissionEnforcer(plugin).ensure("network")` 检查 Plugin 是否声明了该权限，未声明抛 `PermissionDeniedError` | 安全 |
| US-02 | `SandboxConfig(timeout_seconds=10, max_memory_mb=256)` 定义 Plugin 隔离参数 | 基础设施 |
| US-03 | `SandboxManager(config).run(plugin, method_name, **kwargs)` 在独立 subprocess 中执行，JSON 序列化结果返回 | 隔离 |
| US-04 | PluginManager 加载/卸载时发布 `PLUGIN_LOADED` / `PLUGIN_UNLOADED` 审计事件 | 审计 |
| US-05 | `PermissionEnforcer` 提供显式权限检查 API；声明级执行依赖调用方自觉调用 `ensure()`。**系统调用级别的自动拦截（seccomp/WASM）留 Phase 5+** | 安全 |

## 3. 验收条件

| ID | 描述 | 影响 SDK |
|:--:|:------|:---------|
| AC-01 | `PermissionEnforcer(plugin).ensure("network")` 在 plugin 未声明 network 时抛 `PermissionDeniedError`；已声明则 pass | Plugin |
| AC-02 | `PermissionEnforcer(plugin).ensure_all(["network", "filesystem"])` 批量检查，任一未声明即抛异常 | Plugin |
| AC-03 | `SandboxConfig(timeout_seconds=5, max_memory_mb=128)` 创建配置。`max_memory_mb` 在 Linux 上通过 `resource.setrlimit(RLIMIT_AS)` 生效，macOS 上 `resource.setrlimit` 不可用——配置值被静默忽略并写入一条 DEBUG 日志 | Plugin |
| AC-04 | `SandboxManager(config).run(plugin, "fetch_data", url="...")` 在 subprocess 中执行，结果通过 JSON 返回；超时抛 `SandboxTimeoutError`。subprocess 使用 `start_new_session=True` + 超时后 `os.killpg()` 杀整个进程组。非零退出码：捕获 stderr 附加到 `SandboxExecutionError`。Plugin 返回不可 JSON 序列化对象时抛 `SandboxExecutionError`（subprocess 侧 TypeError → stderr → 父进程解析为 SandboxExecutionError） | Plugin |
| AC-05 | `SandboxManager.run()` 在 Plugin 未声明所需权限时先抛 `PermissionDeniedError`（不启动 subprocess） | Plugin |
| AC-06 | PluginManager 加载 Plugin 时调用 `publish_audit_event` 记录 `PLUGIN_LOADED`（tenant_id="", user_id="", action="plugin_load"） | Plugin |
| AC-07 | PluginManager 卸载 Plugin 时调用 `publish_audit_event` 记录 `PLUGIN_UNLOADED`（tenant_id="", user_id="", action="plugin_unload"） | Plugin |

## 4. 依赖

| 依赖 | 状态 |
|------|:----:|
| earp-sdk-core (Phase 2 publish_audit_event) | ✅ |
| earp-sdk-plugin | ✅ |
| Security Spec v1.1 §7 | ✅ |

## 5. 不做（Phase 5+）

- WASM / RestrictedPython 沙箱（Security Spec §7.2 Phase 3）
- gRPC 通信通道（subprocess stdin/stdout + JSON 够用）
- 跨机器 sandbox（Phase 2 仅本地 subprocess）
- 系统调用级别的权限拦截（seccomp/ptrace，Phase 5+）
- Plugin 热加载/热卸载

## 6. 接口预览

### 6.1 PermissionEnforcer

```python
from earp_sdk_plugin.permissions import PermissionEnforcer

plugin = MyPlugin(permissions=["network"])
enforcer = PermissionEnforcer(plugin)

enforcer.ensure("network")     # ✅ pass
enforcer.ensure("filesystem")  # ❌ PermissionDeniedError
enforcer.ensure_all(["network", "filesystem"])  # ❌ filesystem not declared
```

### 6.2 SandboxManager

```python
from earp_sdk_plugin.sandbox import SandboxConfig, SandboxManager

config = SandboxConfig(timeout_seconds=10, max_memory_mb=256)
mgr = SandboxManager(config)

# 在 subprocess 中执行 plugin 方法
# 要求: plugin 有名为 method_name 的可调用方法，接受 **kwargs，返回 JSON 可序列化值
result = mgr.run(plugin, "fetch_data", url="https://api.example.com")
# → subprocess 执行 plugin.fetch_data(url=...), json.dumps(result) → stdout
# → 父进程 json.loads(stdout) 返回

# 超时保护（kill 整个进程组，防止孙进程残留）
config = SandboxConfig(timeout_seconds=1)
mgr = SandboxManager(config)
mgr.run(slow_plugin, "compute")  # → SandboxTimeoutError after 1s

# 权限预检
mgr.run(no_perm_plugin, "call_api")  # → PermissionDeniedError（不启动 subprocess）
```

### 6.3 PluginManager 审计

```python
# PluginManager.load_all() 内部:
for plugin in self._all:
    try:
        await plugin.on_load()
        publish_audit_event(AuditEvent(
            source="security", event_type="PLUGIN_LOADED",
            tenant_id="", user_id="",
            action="plugin_load", result="success",
            detail={"plugin_name": plugin.name, "version": plugin.version},
        ))
    except Exception as e:
        publish_audit_event(AuditEvent(
            source="security", event_type="PLUGIN_LOADED",
            tenant_id="", user_id="",
            action="plugin_load", result="failure",
            detail={"plugin_name": plugin.name, "error": str(e)},
        ))
```

## 7. 用户故事预期行为

### US-01/05：权限强制执行

```
  - enforcer.ensure(perm) 检查 plugin.permissions 列表
  - 未声明 → PermissionDeniedError
  - 已声明 → 无异常；空 permissions → 所有操作拒绝
  - Phase 4 为声明级检查（显式 guard），调用方需自觉调用 ensure()
  - 系统调用级自动拦截（seccomp/WASM）留 Phase 5+
```

### US-02/03：Process 隔离

```
  - SandboxManager.run(plugin, method_name, **kwargs):
    → subprocess.Popen([sys.executable, '-c', script], start_new_session=True,
                        stdout=PIPE, stderr=PIPE)
    → 超时: os.killpg(pgid, SIGKILL) + 等待 2s → SandboxTimeoutError
    → 非零退出: stderr.read() 附加到 SandboxExecutionError.stderr
    → 不可 JSON 序列化: subprocess 侧 TypeError → stderr → 父进程解析为 SandboxExecutionError
    → 正常: json.loads(stdout) 返回结果
  - 权限预检: SandboxManager.run() 先调 enforcer.ensure_all() 检查 plugin.permissions，
    失败不启动 subprocess → PermissionDeniedError
```

### US-04：审计

```
  - load_all(): 每个 plugin → publish_audit_event(PLUGIN_LOADED)
  - unload_all(): 每个 plugin → publish_audit_event(PLUGIN_UNLOADED)
  - 系统事件: tenant_id="", user_id=""
```

## 8. 验收总结表

| # | 检查项 | 状态 |
|:-:|--------|:----:|
| 1 | US 完整 | ✅ 5 个 US |
| 2 | AC 可测试 | ✅ 7 条 |
| 3 | 依赖完整 | ✅ |
| 4 | P0 合理 | ✅ |

## 9. 评审修复记录

| 编号 | 问题 | 修复方式 |
|:----:|:-----|:---------|
| P0-1 | pickle.loads 任意代码执行风险 | 改用 JSON 序列化/反序列化传递 subprocess 结果 |
| P0-2 | 权限无自动拦截（被动 guard） | US-05 + §5 OOS 明确 Phase 4 为声明级检查，真正的自动拦截（seccomp/WASM）延 Phase 5+ |
| P0-3 | subprocess.kill 不杀孙进程 | AC-04 改用 `start_new_session=True` + `os.killpg()` 杀整个进程组 |
| P1-1 | max_memory_mb macOS 不可用 | AC-03 补充：Linux 用 `setrlimit(RLIMIT_AS)`，macOS 忽略 |
| P1-2 | SandboxManager.run 调用模型未规范 | §6.2 注：method 接受 **kwargs，返回 JSON 可序列化值 |
| P2-1 | audit 事件 tenant_id/user_id 未定义 | §6.3 补全：系统事件 tenant_id="", user_id="" |
| P2-2 | PermissionEnforcer 单 plugin 绑定 | 维持（合理设计） |
| P1-1 | JSON 不可序列化类型的错误处理 | AC-04 补充：subprocess 侧 TypeError → stderr → SandboxExecutionError |
| P2-1' | max_memory_mb macOS 语义不精确 | AC-03 明确：静默忽略 + DEBUG 日志 |
| P2-2' | §7 非零退出与 AC-04 不完全匹配 | §7 补充 stderr 捕获 + JSON TypeError 路径细节 |
