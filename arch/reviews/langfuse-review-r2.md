# M15 Langfuse r2 修复复核

**基线**: HEAD（未提交改动 vs HEAD）
**评审日期**: 2026-07-21
**复核范围**: 针对 r1 review 中 P1/P2 项目的修复验证 + 新发现

---

## 一、r1 问题修复 — 逐项验证

### P1: docker-compose + init-langfuse-db.sql 建库

| 项目 | 状态 | 证据 |
|------|------|------|
| docker-compose.yml 挂载 init-langfuse-db.sql | **RESOLVED** | diff +23: `./scripts/init-langfuse-db.sql:/docker-entrypoint-initdb.d/02-langfuse.sql:ro` |
| SQL 脚本正确创建 langfuse 库 | **RESOLVED** | `scripts/init-langfuse-db.sql` 使用 `\gexec` 条件化 `CREATE DATABASE langfuse`，安全幂等 |

**结论**: P1 RESOLVED。Postgres 启动时自动执行 `02-langfuse.sql` 创建 `langfuse` 数据库，Langfuse 容器依赖 `pg:condition: service_healthy` 等待 pg 就绪，时序安全。

---

### P2: connector plan() 失败/降级路径加 trace_llm(error=...)

| 异常分支 | 状态 | 证据 |
|---------|------|------|
| `except ConnectorError:` | **RESOLVED** | diff +235-240: `if self.tracer: self.tracer.trace_llm("plan", ..., error="Ollama failed — fell back to RuleIntentPlanner", latency_ms=0)` |
| `except Exception:` | **RESOLVED** | diff +241-246: `if self.tracer: self.tracer.trace_llm("plan", ..., error="unexpected error", latency_ms=0)` |

**结论**: P2 RESOLVED。两条降级路径均已补充 `trace_llm(error=...)` 调用。

---

### P2: main.py lifespan finally 加 tracer.flush()

| 项目 | 状态 | 证据 |
|------|------|------|
| `tracer.flush()` 在 shutdown 阶段被调用 | **RESOLVED** | diff +126: `finally: tracer.flush()` — 位于 lifespan `finally` 块中，在 engine.dispose() 之前 |

**结论**: P2 RESOLVED。应用退出前可确保 pending traces 被刷新。

---

## 二、遗留问题（r1 已识别，本 diff 未修复）

| # | 位置 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | 全文件 | **P2** | **零测试覆盖。** r1 review 已标注，本 diff 未包含任何测试文件。`tests/` 下无 `langfuse_tracer` / `LangfuseTracer` 相关测试。建议至少补充单元测试（mock SDK）覆盖 enabled/disabled/error 路径。 |
| 2 | docker-compose.yml:39-40 | **P2** | `ENCRYPTION_KEY=0000...0000`（全零）和 `NEXTAUTH_SECRET=mysecret-...` 仍为占位值。建议标注"生产环境必须替换"。 |
| 3 | docker-compose.yml | **P2** | 未设置 `TELEMETRY_ENABLED=false`，本地 dev 环境建议关闭 Langfuse 遥测。 |
| 4 | langfuse_tracer.py:62,77 | **P3** | `logger.debug` → 建议 `logger.warning`，使配置了 key 但 trace 因参数错误失败的场景在默认日志等级下可发现。 |
| 5 | langfuse_tracer.py:59 | **P3** | `trace_llm` usage key 为 `output_tokens`，Langfuse API 期望 `output`。非标准 key 不会在 UI token 仪表盘正确渲染。 |

---

## 三、本次 diff 新发现

| # | 位置 | 严重度 | 说明 |
|---|------|--------|------|
| A | connector.py:206 | **P3** | `import time` 在 `plan()` 方法内部引入。Python 惯例将 `import` 放在文件顶部。运行正确但编码风格不统一。建议移至文件头部。 |
| B | connector.py:236,246 | **P3** | 降级路径 `trace_llm(error=...)` 中 `latency_ms=0`。`t0` 变量在 `try` 外部定义（line 207），在 except 块中依然可访问，可传递真实延迟。当前传 0 丢失了故障前的耗时信息，虽不影响功能但损失可观测性精度。 |

---

## 四、汇总

| 检查项 | r1 问题 | r2 状态 | 本次评级 |
|--------|---------|---------|---------|
| docker-compose + init-langfuse-db.sql 建库 | P1 | **RESOLVED** | — |
| connector plan() 失败/降级路径 trace | P2 | **RESOLVED** | — |
| main.py lifespan finally tracer.flush() | P2 | **RESOLVED** | — |
| 测试覆盖 | P2 | **NOT-RESOLVED**（同 r1） | P2 |
| docker-compose 占位密钥 / TELEMETRY | P2 | **NOT-RESOLVED**（同 r1） | P2 |
| usage key `output_tokens` → `output` | P3 | **NOT-RESOLVED**（同 r1） | P3 |
| logger.debug → logger.warning | P3 | **NOT-RESOLVED**（同 r1） | P3 |
| 新: connector.py import time 位置 | — | 新发现 | P3 |
| 新: 降级路径 latency_ms 传递 | — | 新发现 | P3 |

**整体结论**: 3 个 P1/P2 核心问题全部 RESOLVED。4 个 P2/P3 遗留问题（测试、密钥标注、TELEMETRY、usage key、日志级别）未涉及，2 个 P3 风格/精度问题为本 diff 新增。建议后续按 P2（测试+密钥标注）→ P3 顺序补齐。
