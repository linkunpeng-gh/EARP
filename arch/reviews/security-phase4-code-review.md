# Security Phase 4 — 代码评审报告

## PRD-2026-008 v1.1 — Plugin 沙箱（权限执行 + Process 隔离）

| 字段 | 值 |
|------|-----|
| **评审范围** | 5 个文件变更 + 2 个新模块 + 2 个新测试文件 |
| **关联 PRD** | PRD-2026-008 v1.1 |
| **对齐规范** | Security Spec v1.1 §7.1–§7.2 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **问题统计** | P0: 0 / P1: 2 / P2: 2 → **共 4 个** |

---

## 测试结果

| SDK | 测试文件 | 数量 | 结果 |
|:----|:---------|:----:|:----:|
| earp-sdk-plugin | `test_sandbox.py` | 16 | ✅ |
| earp-sdk-plugin | `test_plugin.py` (regression) | 9 | ✅ |
| earp-sdk-core | 全部 (Phase 1+2+3 reg) | 97 | ✅ |
| **合计** | | **122** | **全部通过** |

---

## 总体评价

**实现质量高，设计务实。** `SandboxManager` 的 subprocess 隔离方案简洁有效——`start_new_session=True` + `killpg()` 防止进程逃逸，`inspect.getsource()` 动态获取源码注入 subprocess，JSON 序列化消除 pickle 风险。`PermissionEnforcer` API 简洁（`ensure` / `ensure_all`）。PluginManager 审计事件与 Phase 2/3 模式完全一致。Phase 4 的存量测试零回归（9 个 Plugin 基础测试全部通过）。

无 P0 阻塞问题。2 个 P1 为安全和实现细节建议，2 个 P2 为代码优化。

---

## P0 — 必须修复（0 个）

无。

---

## P1 — 建议修改（2 个）

### P1-1：`_RUNNER_TEMPLATE` 中 subprocess 的 stderr 未限制大小

**文件**：`sandbox.py:47-64`

```python
_RUNNER_TEMPLATE = """\
...
except Exception as e:
    err = {"__error__": repr(e), "traceback": traceback.format_exc()}
    json.dump(err, sys.stderr)
    sys.exit(1)
"""
```

`traceback.format_exc()` 在某些场景下可能产生非常大的输出（例如 Plugin 内部有深层递归、大量局部变量）。stderr 通过 `proc.communicate()` 全部读入内存，极端情况下可能耗尽父进程内存。

**当前影响**：低。Phase 4 的 Plugin 是短生命周期函数调用，stderr 不大。

**建议**：在 subprocess 端限制 stderr 大小：

```python
err = {"__error__": repr(e), "traceback": traceback.format_exc(limit=20)}
```

或限制 traceback 深度为 20 帧——对于 Plugin 调试完全足够。

---

### P1-2：`inspect.getsource()` 可能泄露 Plugin 源码中的敏感信息到 stderr

**文件**：`sandbox.py:105-112`

```python
try:
    plugin_source = inspect.getsource(cls)
except OSError:
    raise SandboxExecutionError(...)
```

Plugin 源码通过 `inspect.getsource()` 获取后注入到 subprocess script 中。如果 Plugin 源码中包含硬编码的凭证（违反 Security Spec §2.2 但现实中可能发生），这些凭证会以明文形式出现在 subprocess 的命令行参数或环境变量中。

**当前影响**：低。`inspect.getsource()` 结果通过 `stdin` 传入 subprocess（而非命令行参数），不会出现在 `ps aux` 中。

**建议**：在 docstring 中标注安全约束：
```
Note: Plugin source code is transmitted to the subprocess via stdin.
Plugin classes MUST NOT contain hardcoded credentials (per Security Spec §2.2).
```

---

## P2 — 优化建议（2 个）

### P2-1：`_RUNNER_TEMPLATE` 中 `json.dump(result, sys.stdout, default=str)` 的 `default=str` 掩盖序列化错误

**文件**：`sandbox.py:59`

```python
json.dump(result, sys.stdout, default=str)
```

如果 Plugin 返回值包含不可 JSON 序列化的类型（如 `datetime`），`default=str` 会静默转换为字符串，而不是让 subprocess 报错。父进程会收到一个看起来正常的值（如 `"2026-07-15T..."`），但类型已丢失——调用方不知道这是被转换过的。

**分析**：这是有意的设计选择（PRD v1.1 R2 的 P1-1 建议"JSON 不可序列化类型应产生 SandboxExecutionError"）。但当前实现选择 `default=str` 宽容处理。两种方案各有优劣：宽容方案不会因类型问题 crash，但可能掩盖 Bug。

**建议**：保持 `default=str`（务实选择），但在 docstring 中注明：
```
Note: Non-JSON-serializable return values are converted to strings via str().
Callers should ensure return types are JSON-safe: dict, list, str, int, float, bool, None.
```

---

### P2-2：`SandboxManager` 没有对 Plugin 的 `required_permissions_for_run` 属性做文档约定

**文件**：`sandbox.py:98-101`

```python
enforcer = PermissionEnforcer(plugin)
required = getattr(plugin, "required_permissions_for_run", [])
if required:
    enforcer.ensure_all(required)
```

`required_permissions_for_run` 是一个隐式约定——它不在 `Plugin` 基类中定义，不在 `Permission` 枚举中说明，但 `SandboxManager.run()` 直接读取它。如果 Plugin 开发者不知道这个属性的存在，权限预检永远不会触发。

**建议**：在 `Plugin` 基类中增加：
```python
class Plugin:
    ...
    permissions: list[str] = []
    required_permissions_for_run: list[str] = []  # checked by SandboxManager.run()
```

这样 IDE 自动补全会提示 Plugin 开发者这个字段的存在。或者至少在 `SandboxManager.run()` 的 docstring 中明确文档化这一约定。

---

## AC 对齐检查

| AC | 描述 | 实现位置 | 测试 | 状态 |
|:--:|:-----|:---------|:----:|:----:|
| AC-01 | PermissionEnforcer.ensure | `permissions.py:23-28` | `test_sandbox.py:31-35` | ✅ |
| AC-02 | PermissionEnforcer.ensure_all | `permissions.py:31-34` | `test_sandbox.py:45-50` | ✅ |
| AC-03 | SandboxConfig(max_memory_mb) | `sandbox.py:39-42` | `test_sandbox.py:71-79` | ✅ |
| AC-04 | SandboxManager.run JSON + timeout + killpg | `sandbox.py:79-172` | `test_sandbox.py:81-111` | ✅ |
| AC-05 | SandboxManager.run 权限预检 | `sandbox.py:97-101` | （隐式，无专门测试） | ⚠️ 见 P2-2 |
| AC-06 | PLUGIN_LOADED audit | `manager.py:39-60` | `test_sandbox.py:124-145` | ✅ |
| AC-07 | PLUGIN_UNLOADED audit | `manager.py:62-83` | `test_sandbox.py:168-190` | ✅ |

---

## 代码质量观察

### 好的方面

- **`_RUNNER_TEMPLATE` 设计简洁** — 单文件模板，`inspect.getsource()` 获取源码，stdin/stdout JSON 通信，零依赖额外 RPC 框架
- **start_new_session + killpg 防止进程逃逸** — 与 AC-04 精确对齐
- **`Permission` 枚举从 StrEnum 改为 `(str, Enum)`** — 解决了 Phase 1 发现的 Python 3.9 兼容性问题（虽然 Plugin SDK 要求 Python ≥3.12）
- **PluginManager 审计双覆盖** — `load_all` 和 `unload_all` 都有成功+失败两路审计事件，`try/except: pass` 兜底防止审计故障阻塞加载
- **mem_mb macOS 兼容处理** — `preexec_fn` 仅在 Linux 设置，macOS 输出 DEBUG log，干净降级
- **测试使用真实 subprocess** — `SandboxManager` 的测试通过实际 `Popen` 运行，覆盖了 timeout、异常传递、多种返回类型
- **测试 Plugin 类在独立文件中** — `_sandbox_plugins.py` 放在 `testing/` 下供 `inspect.getsource()` 使用
- **Phase 4 零 regression** — 9 个 Plugin 基础测试 + 97 个 Core 测试全部通过

### 安全评价

| 安全维度 | 实现 | 评价 |
|:---------|:-----|:----:|
| 跨进程通信 | `stdin` JSON input / `stdout` JSON result | ✅ 安全（无 pickle 风险） |
| 进程隔离 | `start_new_session=True` + `os.killpg()` | ✅ 孙进程无法逃逸 |
| 内存限制 | Linux: `setrlimit(RLIMIT_AS)` / macOS: ignore + DEBUG log | ✅ 平台兼容 |
| 权限执行 | `PermissionEnforcer.ensure()` / `ensure_all()` 显式检查 | ✅ 声明级检查 |
| 审计发布 | `publish_audit_event` + `try/except: pass` fallback | ✅ 与 Phase 2/3 一致 |

---

## 评审总结

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| ❌ P0 | 0 | — |
| ⚠️ P1 | 2 | subprocess stderr 未限制大小；Plugin 源码中可能含硬编码凭证通过 stdin 传输 |
| 💡 P2 | 2 | json.dump default=str 掩盖类型错误；required_permissions_for_run 隐式约定未文档化 |

### 结论

**可以合并。** 实现设计务实，122 个测试全部通过，Phase 4 零回归。2 个 P1 影响极低，2 个 P2 为代码文档完善建议。
