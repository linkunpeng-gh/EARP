# PRD-2026-008 评审报告

## Security Phase 4 — Plugin 沙箱（权限执行 + Process 隔离）

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-008 |
| **Feature** | Plugin 权限强制执行 + subprocess 隔离 + 加载/卸载审计 |
| **对齐规范** | Security Spec v1.1 §7.1–§7.2 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **状态** | ⚠️ 3 个 P0 需修复后再进入 Gate 0 |

---

## 总体评价

**方向正确，5 个 US 精确覆盖了 Security Spec §7 的权限执行和 Phase 2 Process 隔离。** 接口设计务实——`PermissionEnforcer`（权限检查）、`SandboxManager`（subprocess 隔离）、PluginManager 审计（加载/卸载事件），三层抽象清晰。§5 OOS 合理延期了 WASM 沙箱和 gRPC 通信。

但存在 **3 个 P0**：`SandboxManager.run()` 的跨进程语义有严重的安全漏洞（pickle 反序列化 + 不限制 import），Plugin Sandbox 的执行模型中缺少对权限的真正**拦截**（PermissionEnforcer 是显式调用的 guard，不是自动拦截），以及沙箱超时后的资源清理不完整。

---

## P0 — 必须修复（3 个）

### P0-1：`SandboxManager.run()` 使用 pickle 反序列化 subprocess 结果 — 存在任意代码执行风险

**涉及段落**：§7 US-02/03 预期行为

```
结果 pickle.dumps → stdout, 父进程 pickle.loads
```

**问题**：`pickle.loads()` 在父进程中反序列化来自 subprocess 的数据。pickle 反序列化可以执行任意代码——如果 Plugin 被攻破或恶意 Plugin 植入了构造的 pickle payload，父进程 `pickle.loads()` 时就会被代码注入。

在沙箱场景中，这个风险被**部分缓解**——因为 Plugin 代码本身就是用户安装的，不是不可信的外部数据。但如果沙箱的目的是限制 Plugin 的行为，而 Plugin 可以通过 pickle 逃逸到父进程，则沙箱形同虚设。

**建议**：

方案 A（推荐）：使用 JSON 而非 pickle 传递结果。Plugin 的返回值通常是 dict/str/number，JSON 足够：
```python
# subprocess: json.dumps(result) → stdout
# parent: json.loads(stdout)
```
这对常见返回值（dict/str/list/number/bool/None）完全够用。复杂对象可以要求 Plugin 返回可序列化的 dict。

方案 B：在 pickle 前对数据进行约束（如 `restricted_loads` 白名单）。

方案 C：如果坚持用 pickle，至少要在 PRD 中注明风险评估：
```
安全声明：pickle 反序列化存在代码执行风险。
Phase 4 的 subprocess 隔离仅提供资源隔离（timeout/内存），
不提供代码级 sandbox。完整沙箱（WASM/RestrictedPython）在 Phase 5+ 实现。
```

**推荐方案 A**，因为 `json` 改动小，安全性显著提升。

---

### P0-2：权限强制执行缺乏**自动拦截**机制 — PermissionEnforcer 是显式调用 guard，不是拦截器

**涉及段落**：§3 AC-01, AC-05, §7 US-05

**Security Spec §7.1**：
```
MUST: Plugin 未声明的权限操作自动拒绝
```

**PRD 设计**：
```python
enforcer = PermissionEnforcer(plugin)
enforcer.ensure("network")     # Plugin 调用方自己检查
enforcer.ensure_all(["network", "filesystem"])
```

**问题**：`PermissionEnforcer` 是一个**被动 guard**——需要 Plugin 调用方在每个 `network`/`filesystem`/`llm_call` 操作前显式调用 `enforcer.ensure("network")`。如果调用方忘了、或第三方 Plugin 绕过了这个检查直接发起 HTTP 请求，权限系统完全没有拦截能力。

Security Spec 要求的"自动拒绝"意味着**即使 Plugin 不主动调用 guard，未声明的权限操作也应该被阻止**。

当前 Plugin SDK 的结构：
- `Plugin.permissions: list[str]` — 声明字段存在
- `PluginManager.register()` — 校验权限是否在 `Permission` 枚举中（第 23-25 行）
- 但**没有任何运行时的拦截点**——Plugin 的 `on_load()` / 自定义方法中可以自由调用 `requests.get()`、`open()` 等，不受限制

**建议**：区分两个层次的权限执行，并在 PRD 中明确 Phase 4 的定位：

1. **声明级执行**（Phase 4 实现）：`PermissionEnforcer` 在 Plugin 代码调用前显式检查——这是**调用方自觉**的方式。依赖 Plugin 开发者在操作前调用 `enforcer.ensure()`。
2. **拦截级执行**（Phase 5+ 实现）：通过沙箱环境限制系统调用——在 subprocess 中通过 `seccomp`/`ptrace` 或 WASM 运行时限制 `network`/`filesystem` syscall。这才是真正的"自动拒绝"。

**修复**：在 PRD §5 OOS 中增加一条，并调整 US-05 的描述：
```
US-05 调整: PermissionEnforcer 提供显式权限检查 API。
Phase 4 依赖调用方自觉调用 ensure()。
真正的自动拦截（seccomp/WASM 运行时限制 syscall）留 Phase 5+。
```

同时在 §5 增加：
```
- 系统调用级别的权限拦截（seccomp/ptrace，Phase 5+）
```

---

### P0-3：SandboxManager 超时后 subprocess 资源清理不完整

**涉及段落**：§7 US-02/03 预期行为

```
超时 → subprocess.kill() → SandboxTimeoutError
subprocess 非零退出 → SandboxExecutionError
```

**问题**：`subprocess.kill()` 发送 `SIGKILL` 给子进程，但：
1. 子进程可能已经 fork 了孙进程——`kill()` 不会自动杀孙进程
2. 子进程可能已打开文件句柄、网络连接——这些不会自动关闭
3. 没有超时后的清理回调（cleanup hook）

在 Plugin 沙箱场景中，这些风险相对可控（Plugin 通常是短生命周期的函数调用），但 PRD 应该提及这些限制。

**建议**：在 §7 预期行为中补充：
```
- 超时 → subprocess.kill() + 等待 2s → 若未退出则 kill 整个进程组
- 非零退出码 → 捕获 stderr 附加到 SandboxExecutionError
```

或简化为：使用 `subprocess.Popen([...], start_new_session=True)` + `os.killpg()` 杀掉整个进程组。

---

## P1 — 建议修改（2 个）

### P1-1：`SandboxConfig.max_memory_mb` 在当前设计中没有实现路径

**涉及段落**：§3 AC-03, §6.2

```python
config = SandboxConfig(timeout_seconds=10, max_memory_mb=256)
```

**问题**：限制 subprocess 的内存使用需要操作系统级别的机制（如 Linux `cgroups`、`ulimit -v`、`prlimit`）。在 macOS 上 `ulimit -v` 不生效，`cgroups` 不可用。Python 标准库没有跨平台的内存限制 API。

如果 `max_memory_mb` 无法在 macOS（开发环境）上实现，建议要么：
1. 明确这是 Linux-only 特性（生产环境用 cgroups），macOS 上忽略
2. 或者降级为 SHOULD 并在 OOS 中标注实现约束

**建议**：在 AC-03 中补充：
```
AC-03 补充: max_memory_mb 在 Linux 上通过 resource.setrlimit(RLIMIT_AS) 实现；
macOS 上 ulimit -v 不生效，此参数被忽略。
```

---

### P1-2：`SandboxManager.run()` 的 method_name + kwargs 调用模型与 Plugin 现有接口不一致

**涉及段落**：§6.2, §7

```python
result = mgr.run(plugin, "fetch_data", url="https://api.example.com")
```

**问题**：Plugin 基类目前没有定义统一的调用接口——`Plugin` 是一个 marker 基类，`on_load()`/`on_unload()` 是生命周期方法，但具体的业务方法（如 `fetch_data`）由各 Plugin 自行定义。`SandboxManager.run()` 用字符串 `"fetch_data"` 调用 `getattr(plugin, method_name)(**kwargs)`，假设 Plugin 有一个与 method_name 同名的可调用方法。

这与 Plugin SDK 的现有设计契合——Plugin 确实可以有任意方法。但 PRD 应该明确 `run()` 支持的方法签名约定。

**建议**：在 §6.2 补充：
```
注: mgr.run(plugin, method_name, **kwargs) 要求 plugin 有一个名为
method_name 的可调用方法，且该方法接受 **kwargs。
方法的 return 值必须是 JSON 可序列化的。
```

---

## P2 — 优化建议（2 个）

### P2-1：缺少与 Phase 2 `publish_audit_event` 的集成细节

AC-06/AC-07 提到调用 `publish_audit_event` 记录 Plugin 加载/卸载审计事件，但 3 个 MUST 字段（`tenant_id`、`user_id`、`action`）的值未定义。

Phase 2/3 的审计事件中使用 `tenant_id=""` 和 `user_id=""`（系统事件）。Phase 4 应沿用相同模式，但在 PRD 中明确。

**建议**：在 §6.3 示例中补全 `tenant_id` 和 `user_id`：
```python
publish_audit_event(AuditEvent(
    source="security", event_type="PLUGIN_LOADED",
    tenant_id="", user_id="",          # 系统事件
    action="plugin_load", result="success",
    detail={"plugin_name": "my-plugin", "version": "0.1.0"},
))
```

---

### P2-2：`PermissionEnforcer` 缺少 `permissions` 属性访问入口

AC-01/AC-02 中 `PermissionEnforcer(plugin).ensure("network")` 每次都要传 plugin。如果同一个 plugin 需要多次检查，构造时传 plugin 没问题。但如果需要检查多个不同的 plugin，需要构造多个 enforcer。

**建议**：当前设计合理——`PermissionEnforcer` 是无状态的，绑定到单个 plugin。保持即可。

---

## 对齐检查表

### 与 Security Spec v1.1 §7 的对齐

| Security Spec 要求 | PRD 对应 | 状态 |
|:-------------------|:---------|:----:|
| §7.1 MUST: Plugin 声明所需权限 | Phase 1 已有 `Plugin.permissions` | ✅ |
| §7.1 MUST: 未声明权限自动拒绝 | US-01, AC-01/02 | ⚠️ P0-2 无自动拦截 |
| §7.1 SHOULD: PluginManager 加载时初始化沙箱 | US-02, US-03, AC-03/04 | ✅ |
| §7.2 Phase 2: Process 隔离 | US-03, AC-04/05 | ⚠️ P0-1 pickle 风险 |
| §7.2 权限: network / filesystem / llm_call | Permission 枚举（已有） | ✅ |

### 与已有 Plugin SDK 代码的对齐

| 已有代码 | Phase 4 变更 | 兼容性 |
|:---------|:-----------|:------:|
| `Permission` 枚举 | 不变 | ✅ |
| `Plugin.permissions: list[str]` | PermissionEnforcer 读取 | ✅ |
| `PluginManager.register()` | 权限校验已有 | ✅ |
| `PluginManager.load_all()` | 新增审计发布 | ✅ |
| `PluginManager.unload_all()` | 新增审计发布 | ✅ |
| `Plugin` 基类 | 不变 | ✅ |

### 与其他 Phase 的审计一致性

| Phase | 审计事件 | tenant_id | user_id | action |
|:------|:---------|:---------:|:-------:|:------|
| Phase 2 | AUTH_EXPIRED | `""` | `""` | `connector_auth` |
| Phase 3 | PROMPT_INJECTION_DETECTED | `""` | `""` | `input_guard_check` |
| Phase 3 | SYSTEM_PROMPT_LEAK | `""` | `""` | `output_filter_check` |
| Phase 3 | DANGEROUS_CODE | `""` | `""` | `output_filter_check` |
| Phase 4 | **PLUGIN_LOADED** | `""` | `""` | **`plugin_load`** ✅ |
| Phase 4 | **PLUGIN_UNLOADED** | `""` | `""` | **`plugin_unload`** (推论) |

模式一致。✅

---

## 评审总结

### 数据统计

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0 | 3 | pickle.loads 任意代码执行风险；权限无自动拦截（仅被动 guard）；subprocess.kill 资源清理不完整 |
| ⚠️ P1 | 2 | max_memory_mb macOS 不可实现；SandboxManager.run 调用模型未规范 |
| 💡 P2 | 2 | audit 字段未补全（延续 P2/P3 模式即可）；PermissionEnforcer 为单 plugin 绑定（合理） |

### P0 影响分析

| # | 问题 | 影响 | 修复复杂度 |
|:-:|:-----|:-----|:----------:|
| P0-1 | pickle.loads 任意代码执行 | 恶意 Plugin 可通过 pickle 逃逸到父进程 | **低**（改用 json） |
| P0-2 | 无自动拦截 | Plugin 可绕过权限检查直接 syscall | **中**（PRD 调整 + OOS 标注—真正的自动拦截需 seccomp/WASM） |
| P0-3 | subprocess.kill 不杀孙进程 | 恶意 Plugin 可 fork 子进程绕过 kill | **低**（改用 start_new_session + killpg） |

### 修复优先级

1. **P0-1** — 改用 json（改动最小，安全提升最大）
2. **P0-2** — PRD 调整：明确 Phase 4 是声明级检查，自动拦截延 Phase 5+
3. **P0-3** — subprocess 用 `start_new_session=True` + `os.killpg()`
4. **P1/P2** — 可在 L3 设计或实现中处理

### 好的方面

- **5 个 US 精准覆盖** — 权限执行 + Process 隔离 + 审计，没有贪多
- **§5 OOS 清晰** — WASM、gRPC、跨机器沙箱全部延后
- **`PermissionEnforcer` API 简洁** — `ensure(perm)` / `ensure_all(perms)` 两个方法
- **AC 可测试** — 7 条 AC 均可在单元测试中验证
- **与 Phase 2 审计基础设施衔接自然** — PluginManager 直接使用 `publish_audit_event`
- **与已有代码兼容** — Plugin 基类和 PluginManager 无需破坏性变更
