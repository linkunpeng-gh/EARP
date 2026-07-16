# PRD-2026-008 二次评审报告

## Security Phase 4 — Plugin 沙箱（权限执行 + Process 隔离）

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-008 |
| **版本** | v1.1 |
| **评审人** | Review Agent |
| **日期** | 2026-07-15 |
| **上一轮** | [prd-2026-008-review.md](../reviews/prd-2026-008-review.md) — 7 个问题（3 P0 / 2 P1 / 2 P2） |
| **本轮** | P0: 0 / P1: 1 / P2: 2 → **共 3 个** |

---

## 总体评价

**上一轮的 7 个问题全部修复。** v1.1 质量高，可以进入 Gate 0。

本轮新增 1 个 P1（JSON 序列化的数据限制）和 2 个 P2（AC-03 macOS 忽略语义 + §7 预期行为 vs AC 细粒度），均不阻塞 Gate 0。

---

## 上一轮问题修复确认（7/7 ✅）

### P0-1：pickle.loads 任意代码执行风险 ✅

**修复**：§6.2 + §7 — `json.dumps` / `json.loads` 替代 pickle。

```
结果: json.dumps → stdout, 父进程 json.loads
```

并要求"返回值 JSON 可序列化"。安全性从根本上解决——JSON 不会执行代码。✅

---

### P0-2：权限无自动拦截 ✅

**修复三处**：
1. US-05 描述明确："PermissionEnforcer 提供显式权限检查 API；……系统调用级别的自动拦截（seccomp/WASM）留 Phase 5+"
2. §5 OOS 新增："系统调用级别的权限拦截（seccomp/ptrace，Phase 5+）"
3. §7 US-01/05 预期行为标注："Phase 4 为声明级检查（显式 guard），调用方需自觉调用 ensure()"

Security Spec 的 "自动拒绝" 在 Phase 4 的语义准确定义为"声明级自动检查"。syscall 级拦截的分期合法。✅

---

### P0-3：subprocess.kill 不杀孙进程 ✅

**修复**：AC-04 + §7 —
```
subprocess.Popen([...], start_new_session=True)
超时后 os.killpg(pgid, SIGKILL) + 2s wait
非零退出: 捕获 stderr → SandboxExecutionError
```

进程组 kill 确保孙进程无法逃逸。2s wait 作为优雅退出的最后尝试。✅

---

### P1-1：max_memory_mb macOS 不可用 ✅

**修复**：AC-03 —
```
max_memory_mb 在 Linux 上通过 resource.setrlimit(RLIMIT_AS) 生效，
macOS 上忽略（ulimit -v 不生效）
```

平台差异已文档化。⚠️ 见本轮 P2-1：AC-03 的"忽略"行为与测试可验证性。

---

### P1-2：SandboxManager.run 调用模型未规范 ✅

**修复**：§6.2 —
```
# 要求: plugin 有名为 method_name 的可调用方法，接受 **kwargs，返回 JSON 可序列化值
```

调用约定明确。✅

---

### P2-1：审计事件字段补全 ✅

**修复**：AC-06/AC-07 和 §6.3 — `tenant_id=""`, `user_id=""`, `action="plugin_load"/"plugin_unload"`。与 Phase 2/3 审计模式一致。✅

---

### P2-2：PermissionEnforcer 单 plugin 绑定 ✅

维持当前设计。✅

---

## 本轮发现的新问题（3 个）

### P1-1：JSON 序列化的数据类型限制需在 AC 中明确

**涉及段落**：§3 AC-04, §6.2

AC-04 要求"结果通过 JSON 返回"。JSON 不能直接序列化 `datetime`、`bytes`、`set`、自定义类等 Python 类型。如果 Plugin 返回了包含这些类型的 dict，`json.dumps()` 会抛 `TypeError`，subprocess 以非零退出码退出，父进程收到 `SandboxExecutionError` —— 但根因不清（是业务逻辑错误还是序列化错误？）。

**建议**：在 AC-04 或 §7 中补充：

```
AC-04 补充: 若 Plugin 返回值包含 JSON 不可序列化的类型，
subprocess 以非零退出 + SandboxExecutionError 返回。
调用方应确保返回值仅含 dict/str/list/int/float/bool/None。
```

或在 §7 预期行为中增加一行说明。

---

### P2-1：AC-03 max_memory_mb 在 macOS 上"忽略"的行为未定义

**涉及段落**：§3 AC-03

```
max_memory_mb 在 Linux 上通过 resource.setrlimit(RLIMIT_AS) 生效，macOS 上忽略
```

"忽略"的具体语义不明确：
- 是 SandboxManager 在 macOS 上完全不设置 rlimit？
- 还是设置但不起作用，但产生一个 warning？
- 还是 `SandboxConfig(max_memory_mb=128)` 在 macOS 上创建时抛 `NotImplementedError`？

**建议**：明确 macOS 上的行为：
```
macOS 上 max_memory_mb 参数仍可设置但无效果。不抛异常，不产生 warning。
```

---

### P2-2：§7 预期行为与 AC-04 之间的细节不匹配

**涉及段落**：§7 US-02/03

```
§7: 非零退出: 捕获 stderr → SandboxExecutionError
```

但 AC-04 没有提到"非零退出"的情况：

```
AC-04: 超时抛 SandboxTimeoutError
```

L3 设计时需要知道非零退出时 `SandboxExecutionError` 携带哪些信息（stderr 内容？退出码？）。

**建议**：在 AC 中增加一条或在 §7 中保持现状——§7 的描述足够指导 L3 设计。标记为 P2 供参考。

---

## 变更摘要

### 修复统计

| 级别 | 上一轮 | 已修复 | 本轮新增 | 当前未修复 |
|:----:|:------:|:------:|:--------:|:----------:|
| P0 | 3 | 3 | 0 | **0** |
| P1 | 2 | 2 | 1 | **1** |
| P2 | 2 | 2 | 2 | **2** |

### v1.1 新增/变更亮点

| 变更 | 说明 |
|:-----|:-----|
| pickle → JSON | 消除沙箱逃逸风险，返回值仅限 JSON 可序列化类型 |
| US-05 定位调整 | 声明级检查（Phase 4）+ 自动拦截（Phase 5+） |
| start_new_session + killpg | 进程组杀，防止孙进程逃逸 |
| max_memory_mb Linux-only | 平台差异已文档化 |
| run() 调用约定 | method_name + **kwargs + JSON return |
| §6.3 审计事件完整 | tenant_id/user_id/action 全部补全 |
| §9 评审修复记录 | 7 项完整追踪 |

---

## 对齐检查表 v1.1 终审

### 与 Security Spec v1.1 §7

| 要求 | 覆盖 | 状态 |
|:-----|:---:|:----:|
| §7.1 MUST: Plugin 声明权限 | Phase 1 已有 | ✅ |
| §7.1 MUST: 未声明权限自动拒绝 | US-01 — 声明级检查（Phase 4），syscall 级（Phase 5+） | ✅ |
| §7.1 SHOULD: 加载时初始化沙箱 | US-02/03 — SandboxConfig + SandboxManager | ✅ |
| §7.2 Phase 2: Process 隔离 | US-03 — subprocess + start_new_session + killpg | ✅ |
| §7.1 权限: network/filesystem/llm_call | Permission 枚举（已有）| ✅ |
| §6.2 MUST: Plugin 加载/卸载审计 | US-04, AC-06/07 | ✅ |

### 审计事件一致性（跨 Phase）

| Phase | event_type | tenant_id | user_id | action |
|:------|:-----------|:---------:|:-------:|:------|
| P2 | AUTH_EXPIRED | `""` | `""` | `connector_auth` |
| P3 | PROMPT_INJECTION_DETECTED | `""` | `""` | `input_guard_check` |
| P3 | SYSTEM_PROMPT_LEAK | `""` | `""` | `output_filter_check` |
| P3 | DANGEROUS_CODE | `""` | `""` | `output_filter_check` |
| P4 | PLUGIN_LOADED | `""` | `""` | `plugin_load` |
| P4 | PLUGIN_UNLOADED | `""` | `""` | `plugin_unload` |

模式完全一致。✅

---

## 评审总结

| 类别 | 数量 | 关键项 |
|:----|:----:|:-------|
| P0 | **0** | — |
| P1 | **1** | JSON 不可序列化类型的错误处理未定义 |
| P2 | **2** | max_memory_mb macOS "忽略"语义不够精确；§7 与 AC-04 细节不匹配 |

**v1.1 可以进入 Gate 0。** 3 个新问题均为低优先级，可在 L3 设计或实现阶段处理。
