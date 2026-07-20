 # Plugin Daemon 独立进程 — 代码评审
 
 **基线**: `ad569cd` | **评审范围**: 工作树未提交改动（`Makefile`、`plugin_daemon.py`、`test_entrypoints.py`）  
 **评审日期**: 2026-07-20
 
 ---
 
 ## 1. PluginRegistry.load_all() — 动态加载安全性
 
 **结论**: **ISSUE P1**
 
 `load_all()` (plugin_daemon.py:48–75) 使用 `importlib.util.spec_from_file_location()` + `exec_module()` 加载 `./plugins/*.py` 中的文件，无任何沙箱或校验机制。
 
 **具体问题**:
 
 - 任何能写入 `./plugins/` 目录的攻击者均可实现任意 Python 代码执行（RCE）。
 - 无签名验证、哈希校验或模块白名单。
 - 加载后通过 `dir(module)` 全局扫描（L67–68）可能匹配到 import 进来的非插件对象，虽然后续通过 `extension_point` + `name` 属性过滤减轻了误注册风险。
 
 **缓解建议**:
 
 - 在文档或 docstring 中明确声明安全假设：`./plugins` 必须只对受信任写入者开放，生产环境应 mount 只读 volume。
 - 可选增强：插件目录路径应当可通过 `Settings` 配置（目前硬编码为 `DEFAULT_PLUGIN_DIR`），以便不同环境使用不同目录。
 - 可选增强：考虑 `importlib.abc.Loader` 的自定义限制（如禁止 `__import__`），但当前阶段非必要。
 
 ---
 
 ## 2. /execute 端点 — async/sync 方法处理
 
 **结论**: **ISSUE P2**
 
 `execute` handler (L99–120) 在 FastAPI `async def` 中直接同步调用 `method(**req.params)`。
 
 **问题**: 如果插件方法执行同步阻塞 I/O（如 `time.sleep(3)`、`requests.get()`、文件读写），FastAPI async 端的单个事件循环线程会被阻塞，导致整个服务器无响应。
 
 - `asyncio.iscoroutine(result)` 检查（L113）只捕获本身就是 coroutine 的情况，无法区分 "同步但有阻塞" 和 "同步且立即返回"。
 - 缺少 `loop.run_in_executor()` 后备路径。
 
 **建议**: 当结果是普通可调用对象（非 coroutine）时，通过 `run_in_executor(None, method, **params)` 在线程池中执行：
 
 ```python
 if asyncio.iscoroutine(result):
     result = await asyncio.wait_for(result, timeout=req.timeout_seconds)
 else:
     loop = asyncio.get_running_loop()
     result = await asyncio.wait_for(
         loop.run_in_executor(None, lambda: method(**req.params)),
         timeout=req.timeout_seconds,
     )
 ```
 
 ---
 
 ## 3. SIGTERM 优雅退出
 
 **结论**: **PASS**
 
 `_run()` (L131–145) 的信号处理与已有 `audit.py` 模式一致：
 
 1. 通过 `loop.add_signal_handler(sig, stop.set)` 注册自定义处理器。
 2. 将 `uvicorn.Server.serve()` 创建为 async task。
 3. `await stop.wait()` 阻塞直到收到信号，之后设置 `server.should_exit = True` 并等待 server task 完成。
 
 **验证**: uvicorn 的 `capture_signals()` 使用 `signal.signal()`（而非 `loop.add_signal_handler()`），在 `serve()` 期间会保存并恢复原始信号处理器，退出后会通过 `signal.raise_signal()` 重新触发信号，触发 `stop.set()` 回调。整个流程在 asyncio 事件循环中正确衔接，不会挂起。
 
 **备注**: `server.should_exit = True`（L144）在信号到达时实际上是冗余的（`_serve()` 已退出），但无害。建议添加注释说明其作用为确保后续 `await server_task` 时的防御性语义。
 
 ---
 
 ## 4. Makefile 目标
 
 **结论**: **PASS**
 
 ```makefile
 plugin-daemon:
     $(UV) run python -m earp_server.entrypoints.plugin_daemon
 ```
 - `.PHONY` 声明已添加。
 - 拼写与已有 `audit-worker` 目标一致。
 - 无问题。
 
 ---
 
 ## 5. 测试覆盖度
 
 **结论**: **PASS**（基础覆盖，可改进）
 
 `test_plugin_daemon_entrypoint_graceful` (test_entrypoints.py:101–104) 遵循已有的 graceful shutdown 测试模式：
 
 - 启动子进程 → 等待 `"plugin daemon starting"` 标记 → 发送 SIGTERM → 验证 exit code == 0。
 
 **覆盖缺口**：
 
 | 场景 | 缺失 | 建议优先级 |
 |------|------|-----------|
 | 真实 `.py` 插件加载 | ❌ | P2 — 创建临时 `./plugins/` 并注入一个已知返回值的插件 |
 | `/health` 端点 | ❌ | P3 |
 | `/execute` 端点（正常调用、404、400、timeout） | ❌ | P2 — isolate 测试（e.g., `TestClient`）覆盖主要路径 |
 | 并发请求下 SIGTERM | ❌ | P3 — 可在后续集成测试中补充 |
 | 端口冲突等启动失败 | ❌ | P3 |
 
 建议优先补一个 `TestClient` 级测试覆盖 `/execute` 的 200/404/400 路径，再加一个插件加载的黑盒测试。
 
 ---
 
 ## 6. 其他零散发现
 
 | 位置 | 严重度 | 说明 |
 |------|--------|------|
 | plugin_daemon.py:25 | **P3** | `DEFAULT_PLUGIN_DIR` 硬编码为 `"./plugins"`，无 `Settings` 配置入口。建议在 `Settings` 中增加 `plugin_dir` 字段。 |
 | plugin_daemon.py:50–52 | **P3** | 目录不存在时自动 `mkdir(parents=True, exist_ok=True)`。生产环境下意外自动创建空目录可能掩盖配置错误。建议改为 warn + 返回 0 加载计数。 |
 | plugin_daemon.py:136 | **P3** | `log_level=settings.log_level.lower()`。`Settings.log_level` 默认 `"INFO"`，`"info".lower()` → `"info"` 再被 uvicorn upcase 回 `"INFO"`。功能正确，但字符串往返不必要。 |
 
 ---
 
 ## 汇总
 
 | # | 检查项 | 结果 | 严重度 |
 |---|--------|------|--------|
 | 1 | PluginRegistry.load_all() 动态加载安全性 | **ISSUE** | P1 |
 | 2 | /execute 端点 async/sync 方法处理 | **ISSUE** | P2 |
 | 3 | SIGTERM 优雅退出 | **PASS** | — |
 | 4 | Makefile 目标 | **PASS** | — |
 | 5 | 测试覆盖度 | **PASS**（有缺口） | — |
 
 **建议处理顺序**: P1 → P2 → P3。P1 需补充安全文档说明或在代码中增加防护；P2 在 /execute 路径上加入线程池后备即可，改动量小。
