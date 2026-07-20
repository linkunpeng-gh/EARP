# Plugin Daemon r2 修复复核

**基线**: `ad569cd` | **评审范围**: 工作树未提交改动（`Makefile`、`test_entrypoints.py`、新文件 `plugin_daemon.py`）
**评审日期**: 2026-07-20 | **关联**: [plugin-daemon-review.md](/Users/linkunpeng/work/EARP/arch/reviews/plugin-daemon-review.md) (r1)

---

## 1. [P1] PluginRegistry 安全文档

**结论**: **RESOLVED**

`PluginRegistry` docstring 已补充安全声明：

> Security: plugins are loaded via importlib from a trusted directory.
> Production deployments MUST mount ./plugins as a read-only volume …
> the plugin directory is the trust boundary. No runtime code signature verification
> is performed; rely on filesystem-level access control.

明确标注了信任边界、只读挂载要求、运行时不做签名校验。符合期望。

---

## 2. [P2] /execute 同步方法 — `run_in_executor` 线程池

**结论**: **NOT-RESOLVED** — 实现存在严重缺陷

### 实现现状 (plugin_daemon.py:120-127)

```python
result = method(**req.params)                           # ← ① 第一遍调用（同步，事件循环线程）
if asyncio.iscoroutine(result):
    result = await asyncio.wait_for(result, ...)
else:
    loop = asyncio.get_running_loop()
    result = await asyncio.wait_for(
        loop.run_in_executor(None, lambda: method(**req.params)),  # ← ② 第二遍调用（线程池）
        timeout=req.timeout_seconds,
    )
```

### 问题分析 — 双重调用 + 事件循环阻塞

第 ① 步 `method(**req.params)` 在**事件循环线程**上同步执行。对同步方法：

- 事件循环在第一次调用期间被完全阻塞（违背线程池设计的初衷）。
- 第一次调用的结果被丢弃（进入 `else` 分支后从未使用 `result`）。
- 第 ② 步在线程池中再次调用 `method(**req.params)`，方法被执行**两次**。
- 如果方法有副作用（写入文件、发送请求、累加计数器），副作用被触发两次。
- 如果方法本身耗时（如 `time.sleep(3)`），事件循环被阻塞 3 秒，然后线程池再执行一次。

这是一个 **P0 级缺陷**: 修复意图正确但实现错了。

### 正确做法

使用 `asyncio.iscoroutinefunction(method)` 在调用前判明函数类型，避免先调后判：

```python
if asyncio.iscoroutinefunction(method):
    result = await asyncio.wait_for(method(**req.params), timeout=req.timeout_seconds)
else:
    loop = asyncio.get_running_loop()
    result = await asyncio.wait_for(
        loop.run_in_executor(None, lambda: method(**req.params)),
        timeout=req.timeout_seconds,
    )
```

变更只影响 `if` 条件值（从 `iscoroutine(result)` 改为 `iscoroutinefunction(method)`）和删除多余的第一次调用。

---

## 3. 是否引入新问题

### 3.1 新发现

| # | 位置 | 严重度 | 说明 |
|---|------|--------|------|
| A | plugin_daemon.py:120 | **P0** | 同步方法双重调用 + 事件循环阻塞（详见上文第 2 节） |
| B | test_entrypoints.py:99-104 | **P3** | **测试副作用**: 若 `./plugins` 不存在，`load_all()` 中 `mkdir(parents=True, exist_ok=True)` 会在 cwd 下创建空目录。生产行为可接受，但测试应在临时目录或 mock 下运行以避免污染。 |
| C | test_entrypoints.py:101 | **P3** | **日志匹配标记**: 期望标记 `"plugin daemon starting"` 仅匹配日志前缀，`_run_entrypoint` 通过子进程 stdout 匹配。`_run()` 中使用 `logging.info()`（无 `StreamHandler` 绑定到 stderr/stdout），默认情况下日志可能只到 stderr，取决于 pytest 的 caplog/setup。建议确认该测试在 CI 中确实可捕获到此日志行。 |

### 3.2 r1 遗留问题（未修复，仍存在）

| 位置 | 严重度 | 说明 |
|------|--------|------|
| plugin_daemon.py:25 | **P3** | `DEFAULT_PLUGIN_DIR` 硬编码 `"./plugins"`，无 `Settings` 配置入口 |
| plugin_daemon.py:56 | **P3** | 目录不存在时自动 `mkdir(parents=True, exist_ok=True)`，可能掩盖配置错误 |
| plugin_daemon.py:136 | **P3** | `log_level.lower()` 字符串往返，功能正确但多余 |
| 测试覆盖缺口 | **P2** | `/execute` 200/404/400 路径无覆盖，真实插件加载无覆盖（r1 已记录） |

---

## 汇总

| # | 检查项 | 结果 | 严重度 |
|---|--------|------|--------|
| 1 | PluginRegistry 安全文档补充 | **RESOLVED** | - |
| 2 | /execute 同步方法 `run_in_executor` | **NOT-RESOLVED** | **P0** |
| 3 | 是否引入新问题 | **YES** - 见 3.1 |

**关键风险**: P0 缺陷意味着当前 r2 实现比不做修复更糟——如果有同步插件注册，事件循环会被首次阻塞，且方法被调两次。建议**先修 P0 再合并**。

**建议修复顺序**: P0(双重调用) → P2(测试覆盖 /execute) → P3(遗留项)。
