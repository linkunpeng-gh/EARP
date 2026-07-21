# M15 Langfuse 可观测性 — 代码评审

**基线**: `ad569cd` | **评审范围**: 未提交改动（git diff ad569cd..HEAD）
**评审日期**: 2026-07-21
**涉及文件**: 7 个（含 1 个新建文件 `infra/langfuse_tracer.py`）

---

## 1. langfuse_tracer.py: SDK 导入降级

**结论: PASS**

`langfuse_tracer.py:18-21` 使用 `try/except ImportError` 包裹 `from langfuse import Langfuse`，标准做法。降级逻辑如下：

```python
try:
    from langfuse import Langfuse as _LangfuseClient
    _HAS_LANGFUSE = True
except ImportError:
    _HAS_LANGFUSE = False
```

- SDK 未安装 → `_HAS_LANGFUSE = False` → `__init__` 中 `_enabled = False` → `_client = None`
- `langfuse_tracer.py:46` `trace_llm` / `trace_embedding` 入口处 `if not self._enabled or not self._client: return` 立即返回
- `connector.py` 和 `embedding_service.py` 中 tracer 引用均在 `TYPE_CHECKING` 块下，运行时不导入外部模块

退化测试：当 `langfuse` 未安装且 key 为空时，全链路无网络调用、无异常抛出。

---

## 2. langfuse_tracer.py: trace_llm / trace_embedding 异常隔离

**结论: PASS** — P3 建议

两个方法均使用 `try/except Exception` 包裹 Langfuse SDK 调用：

```python
try:
    trace = self._client.trace(name=name, metadata=metadata)
    trace.generation(...)
except Exception:
    logger.debug("LangfuseTracer: trace_llm failed", exc_info=True)
```

**分析**:

- Langfuse SDK 3.x 的 `trace()` / `generation()` 是同步非阻塞调用 — 数据仅入列到 SDK 内部队列，由后台线程发送。网络超时/API 错误不会在这里抛出，会在后台线程中自行处理（含重试+内部日志）。
- 因此 `except Exception` 主要捕获编程错误（参数类型不匹配等），而非 API 不可达。异常隔离本身正确。

| 位置 | 严重度 | 说明 |
|------|--------|------|
| langfuse_tracer.py:62,77 | **P3** | `logger.debug` → 建议 `logger.warning`，使配置了 key 但 trace 因参数错误失败的场景在默认日志等级下可发现 |

---

## 3. connector.py + embedding_service: tracer 调用正确性

### 3.1 connector.py `plan()` — 成功路径

**结论: PASS**

[connector.py:203-214](apps/earp-server/src/earp_server/connector.py:203)

```python
t0 = time.monotonic()
steps = await self._call_ollama(prompt, capabilities=capabilities)
latency_ms = int((time.monotonic() - t0) * 1000)
if self.tracer:
    self.tracer.trace_llm("plan", self._model, prompt[:200],
        output=json.dumps(steps)[:500], latency_ms=latency_ms,
        usage={"output_tokens": len(json.dumps(steps).split())},
    )
```

- 计时范围正确包裹 `_call_ollama` ✅
- `if self.tracer` 守卫，无 key 时快速跳过 ✅
- trace name / model / latency 完整 ✅

| 位置 | 严重度 | 说明 |
|------|--------|------|
| connector.py:215 | **P3** | `json.dumps(steps)` 调用了两次（output / usage 各一次）。影响可忽略 |

### 3.2 connector.py `plan()` — 失败 / 降级路径

**结论: ISSUE P2**

[connector.py:218-234](apps/earp-server/src/earp_server/connector.py:218)

当 `_call_ollama` 抛出异常时，代码进入 `except` 降级到 `RuleIntentPlanner`：

```python
except ConnectorError:
    logger.warning("...falling back to RuleIntentPlanner")
except Exception:
    logger.exception("...unexpected error, falling back")
```

此时 LLM 调用失败但没有任何 trace 记录。`trace_llm` 的 `error` 参数在设计上就是为了这个场景，但从未被使用。

| 位置 | 严重度 | 说明 |
|------|--------|------|
| connector.py:218-234 | **P2** | LLM 调用失败 + 降级路径未记录任何 trace，observability 完整度有缺口。建议在 except 块中也调用 `trace_llm(error=...)`。 |

### 3.3 embedding_service.py `_ollama_embed` — 成功 + 失败路径

**结论: PASS**

[embedding_service.py:55-68](apps/earp-server/src/earp_server/knowledge/embedding_service.py:55)

```
# 成功路径（line 55-59）
latency_ms = int((time.monotonic() - t0) * 1000)
if _tracer:
    _tracer.trace_embedding(..., latency_ms=latency_ms)
return data["embeddings"]

# 失败路径（line 63-68）
except httpx.HTTPError as exc:
    logger.error("Ollama embed failed: %s", exc)
    if _tracer:
        _tracer.trace_embedding(..., error=str(exc))
    raise RuntimeError(...)
```

- 成功/失败两条路径均有 tracer 调用 ✅
- 失败路径携带 `error` 信息 ✅
- `if _tracer` 守卫 ✅

| 位置 | 严重度 | 说明 |
|------|--------|------|
| embedding_service.py:63-66 | **P3** | 错误路径未计算 `latency_ms`（t0 在 except 作用域内可用但未使用）。功能完整，仅可改进 |

---

## 4. docker-compose: langfuse 服务配置

**结论: ISSUE P1**

[docker-compose.yml:33-57](apps/earp-server/docker-compose.yml:33)

### 功能性检查

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Image `ghcr.io/langfuse/langfuse:3` | ✅ | Langfuse v3 官方镜像 |
| Port `3000:3000` | ✅ | EARP config 默认 `langfuse_host` 一致 |
| `depends_on: pg: condition: service_healthy` | ✅ | 等待 pg 就绪 |
| pg 包含 pgvector 扩展 | ✅ | `pgvector/pgvector:pg16` |
| `NEXTAUTH_URL` / `SALT` / `ENCRYPTION_KEY` | ✅ | 格式正确 |
| `LANGFUSE_INIT_*` 变量 | ✅ | 支持 Langfuse v3 种子初始化 |

### 问题

| # | 位置 | 严重度 | 说明 |
|---|------|--------|------|
| A | docker-compose.yml:36 | **P1** | `DATABASE_URL=postgresql://postgres:postgres@pg:5432/langfuse` 引用数据库 `langfuse`，但 pg 服务仅初始化 `POSTGRES_DB: earp`。**无 init 脚本创建 `langfuse` 数据库。** postgres 超级用户理论上会在首次连接时自动创建，但行为未文档化；若 PostgreSQL 配置了 `CREATE DATABASE` 权限限制则会直接失败。建议补充 init SQL 或在注释中说明。 |
| B | docker-compose.yml:39-40 | **P2** | `ENCRYPTION_KEY=0000...0000`（全零）和 `NEXTAUTH_SECRET=mysecret-...` 仅适用于本地开发，建议在注释中标注"生产环境必须替换" |
| C | - | **P2** | Langfuse 默认开启遥测，建议补充 `TELEMETRY_ENABLED=false` 减少本地 dev 流量和首屏提示 |

---

## 5. 无 key 时性能影响

**结论: PASS** — 接近零开销

无 key 场景（默认）：`langfuse_public_key=""` + `langfuse_secret_key=""`

- `LangfuseTracer.__init__` → `_enabled = False`, `_client = None`
- `connector.py`: `if self.tracer` — 实例属性 + None 检查，~ns
- `embedding_service.py`: `if _tracer` — 模块全局 + None 检查，~ns
- `trace_llm` / `trace_embedding`: 首行 `if not self._enabled or not self._client: return` 立即返回
- `time.monotonic()` 和 latency 计算会执行（在 tracer guard 之前），~µs 级别
- 无网络调用 ✅，无额外线程 ✅

---

## 6. 其他发现（跨文件）

| # | 位置 | 严重度 | 说明 |
|---|------|--------|------|
| A | main.py:95-107 | **P2** | `LangfuseTracer.flush()` 从未被调用。Lifespan 启动阶段创建 tracer 后直接 `yield`，shutdown 阶段无 `tracer.flush()`。SDK 后台线程默认每 ~5s flush 一次，应用退出前几秒的 trace 可能丢失。建议在 lifespan shutdown 阶段添加 `tracer.flush()`。 |
| B | 全文件 | **P2** | **零测试覆盖。** `tests/` 下无任何 `langfuse` 或 `LangfuseTracer` 相关测试。建议至少：<br>1) `LangfuseTracer` 单元测试（mock SDK），验证 enabled/disabled/error 路径<br>2) `connector.plan()` 失败路径 trace 缺失的集成测试 |
| C | langfuse_tracer.py:59 | **P3** | `trace_llm` usage key 为 `output_tokens`，Langfuse API 期望 `output`。非标准 key 可能不会在 UI token 仪表盘正确渲染。 |

---

## 汇总

| # | 检查项 | 结果 | 严重度 |
|---|--------|------|--------|
| 1 | SDK 导入降级 | **PASS** | - |
| 2 | trace_llm/trace_embedding 异常隔离 | **PASS** | P3 建议 |
| 3.1 | connector plan() 成功路径 | **PASS** | - |
| 3.2 | connector plan() 失败/降级路径 | **ISSUE** | P2 |
| 3.3 | embedding_service 成功+失败路径 | **PASS** | - |
| 4 | docker-compose langfuse 配置 | **ISSUE** | P1 |
| 5 | 无 key 性能影响 | **PASS** | - |
| - | 无 shutdown flush | **ISSUE** | P2 |
| - | 零测试覆盖 | **ISSUE** | P2 |

**建议修复顺序**: P1(docker-compose 数据库初始化) → P2(connector 失败路径 trace + shutdown flush + 测试) → P3(日志级别 + usage key)
