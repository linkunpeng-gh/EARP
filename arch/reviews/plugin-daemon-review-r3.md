 # Plugin Daemon r3 修复复核 — P0
 
 **日期**: 2026-07-20
 **范围**: `/execute` 端点中 `iscoroutinefunction` + `run_in_executor` 双重调用检查
 **基准**: `apps/earp-server/src/earp_server/entrypoints/plugin_daemon.py`（未提交，untracked file vs HEAD）
 
 ---
 
 ## 检查项：双重调用（double invocation）
 
 审查目标代码（`/execute` 端点，第 120–128 行）：
 
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
 
 ### 异步路径（line 120–121）
 
 - `iscoroutinefunction(method)` 判断 method 是否为 `async def` 定义的协程函数。
 - `method(**req.params)` 调用一次，返回 coroutine 对象，立即传给 `wait_for`。
 - `wait_for` 负责 await 该 coroutine，不会再次调用 `method`。
 - **结论：恰好一次调用，无双重调用。** ✅
 
 ### 同步路径（line 123–128）
 
 - method 为普通同步函数，需要 offload 到线程池以免阻塞事件循环。
 - `lambda: method(**req.params)` 是一个闭包包裹的可调用对象，**此时尚未执行 method**。
 - `run_in_executor(None, callback)` 将 callback 提交到默认线程池，由工作线程**执行一次**。
 - `run_in_executor` 返回 `asyncio.Future`，`wait_for` 等待其完成。
 - **结论：恰好一次调用，无双重调用。** ✅
 
 ---
 
 ## 结果
 
 **P0 RESOLVED。**
 
 `iscoroutinefunction` + `run_in_executor` 分支逻辑正确，method 在两条路径中各被调用且仅被调用一次，不存在双重调用问题。
 
 ### 备注（非 P0，仅观察）
 
 - 同步路径在 `wait_for` 超时取消 Future 后，底层线程池中的 method 仍会继续执行到完成，其结果被丢弃。这是 `run_in_executor` 的已知行为，不影响正确性，但在有副作用的方法上可能产生非预期效果。若后续需要严格取消，可考虑 `concurrent.futures` 原语或进程级隔离。
 - 资源释放方面：FastAPI 应用未挂载 shutdown handler 来关闭线程池，默认线程池跟随事件循环生命周期，当前规模下可接受。
 - 当前代码（untracked）无历史版本可 diff，请确认在 PR 合入前有无其他需要补充的提交。
 - method 如果是返回 coroutine 的普通函数（非 `async def`），`iscoroutinefunction` 返回 False，会走同步路径，此时 `lambda: method(**req.params)` 会返回一个 coroutine 对象而非执行结果。但这不是典型用法，当前视为设计边界而非缺陷。
