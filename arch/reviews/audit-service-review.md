# Audit Service 独立进程 代码评审

**评审范围**: `2f390cc..0e98227` (#10 Audit Service 拆独立进程)
**评审日期**: 2026-07-20
**评审人**: Codex

---

## 1. 进程生命周期 — Redis 不可达时是否优雅退出？

**ISSUE (P1)** — `entrypoints/audit.py:30`

`start_consumer()` 内部 `_ensure_redis()` 若连接失败，consumer task 立即返回（`redis_eventbus.py:88`），不留任何重试路径。进程进入 `stop.wait()` 后不再做任何有用工作，即使 Redis 后续恢复也不会重新连接。

生产环境下，若 Redis 在审计 Worker 启动时不可用，进程将处于「存活但永远不做任何事」的静默失败状态，exit code = 0 掩盖了故障。

建议：在 `start_consumer()` 入口加入带指数退避的重试循环。

---

## 2. SIGTERM / SIGINT 处理是否正确？

**PASS** — `entrypoints/audit.py:33-48`

通过 `loop.add_signal_handler` 注册 SIGTERM/SIGINT，`asyncio.Event.set()` 触发停止。收到信号后：取消 consumer task → 吞 CancelledError → 关闭连接池 → 返回 0。无资源泄漏，与已存在的 worker.py / scheduler.py 模式一致。

---

## 3. main.py lifespan — prod 模式移除 audit 订阅后，dev/test 仍正常工作？

**PASS** — `main.py:94-97`

- dev/test：`EventBus` 进程内总线，订阅生效，审计由 API 进程直接消费
- prod：`RedisStreamsEventBus`，订阅跳过，API 进程仅发布事件，消费由独立 `entrypoints/audit.py` 负责

`app.state.eventbus` 初始化也已正确按模式分支（`main.py:85-88`），prod 下 API 进程不调用 `start_consumer()`，避免双重消费。

---

## 4. Makefile audit-worker 目标是否正确？

**PASS** — `Makefile:5,42-43`

模块路径正确，`python -m` 触发 `__main__` 路径，`.PHONY` 声明正确，风格与已有目标一致。

---

## 5. 测试覆盖度

**ISSUE (P2)** — `tests/test_entrypoints.py:92-98`

### 有效覆盖 ✅
- 进程启动后收到 SIGTERM 能在 `GRACE_SECONDS` (5s) 内优雅退出，返回 0
- Redis 不可用不是致命错误
- 测试基础设施与 worker/scheduler 测试一致

### 未覆盖 ❌
1. **Redis 可用路径从未被测试** — 测试环境无 Redis，`start_consumer()` 从未进入消费循环。生产链路（连接 → 消费 → 解包 → 分发 → 写入）零覆盖。
2. 测试 marker "audit worker starting" 仅表示进程启动，而非实际连接 Redis 成功或进入消费循环。
3. 未测试「正通过 xreadgroup 阻塞时收到 SIGTERM」时序，`CancelledError` 路径虽有代码但未被实际触发。

建议：引入 `fakeredis` 或复用现有 Docker Compose 的 Redis 6380 端口，增加带 Redis 的审计 Worker 集成测试。

---

## 总结

| # | 检查项 | 结论 | 严重度 |
|---|--------|------|--------|
| 1 | 进程生命周期 — Redis 不可达时优雅退出 | ISSUE — 无重试，进程空跑，永不复原 | P1 |
| 2 | SIGTERM/SIGINT 处理 | PASS | — |
| 3 | main.py lifespan prod 模式审计订阅分离 | PASS | — |
| 4 | Makefile audit-worker 目标 | PASS | — |
| 5 | 测试覆盖度 | ISSUE — 缺少 Redis 可用路径覆盖 | P2 |

**P0: 0 | P1: 1 | P2: 1 | PASS: 3/5**
