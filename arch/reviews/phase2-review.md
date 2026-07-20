<!--
  Generated: 2026-07-20 (r2 — 第二轮)
  Scope: Phase 2 代码评审 — 真实 Embedding + Structured Output + LLM 缓存
  r1: 14 文件, 2 P1 + 6 P2 + 1 P3
  r2: 8 文件修改, 全部 P1/P3 修复, 2/6 P2 修复
-->

# Phase 2 代码评审报告（第二轮）

**r2 结论：可合并，无遗留阻塞级问题。** 上一轮 2 个 P1、1 个 P3 全部修复；6 个 P2 中 2 个修复、3 个保留（可接受）。无新问题引入。

---

## r2 变更总结

| 上次 ISSUE | 原严重度 | r2 修改 | 状态 |
|------------|----------|---------|------|
| A1 embedding 空响应无防御 | P2 | embed_chunks L83-89: count mismatch 检查 + RuntimeError | ✅ 修复 |
| A3 discover exec_driver_sql 拼接 | P1 | registry.py L78-98: text() + 参数化 | ✅ 修复 |
| A2 lock_timeout=5s | P2 | 未改 | ⬜ 可接受 |
| B4 regex 贪婪匹配 | P2 | connector.py L146-162: 括号计数法 | ✅ 修复 |
| B5 多 worker 文档不充分 | P2 | 未改 | ⬜ 可接受 |
| B5 monotonic suspend | P2 | 未改 | ⬜ 可接受 |
| B6 cap_id→adapter_type 脆弱 | P1 | task_planner.py L91-103: _cap_id_to_adapter() + rfind("-") | ✅ 修复 |
| C8 空 dict 存 NULL | P3 | invoke.py L110: `is not None` 判断 | ✅ 修复 |
| E10 httpx 重复声明 | P2 | pyproject.toml: httpx 移出 dev-deps | ✅ 修复 |

---

## r2 逐项复查

### A1. [embedding_service.py:L83-89](/Users/linkunpeng/work/EARP/apps/earp-server/src/earp_server/knowledge/embedding_service.py:83)

```python
if len(all_embeddings) != len(texts_to_embed):
    logger.error(
        "embed_chunks: embedding count mismatch — expected %d, got %d",
        len(texts_to_embed), len(all_embeddings),
    )
    raise RuntimeError(
        f"Ollama returned {len(all_embeddings)} embeddings for {len(texts_to_embed)} texts"
    )
```

**PASS** Ollama 返回的 embedding 数量与输入不匹配时显式抛异常，不再静默跳过。✅

### A2. [migration 0004](/Users/linkunpeng/work/EARP/apps/earp-server/migrations/versions/0004_change_embedding_dim_1024.py): lock_timeout=5s

未修改。当前数据量下 5s 安全，生产部署前可酌情提高到 30s 或环境变量化。⬜

### A3. [registry.py:L78-98](/Users/linkunpeng/work/EARP/apps/earp-server/src/earp_server/capability/registry.py:78)

query 分支从 `exec_driver_sql` + f-string 拼接改为 `text()` + 参数化字典 `{"emb": ..., "tid": tenant_id, "rid": role_id}`。`tenant_id`、`role_id` 现通过 `:tid`、`:rid` 绑定。✅

### B4. [connector.py:L146-162](/Users/linkunpeng/work/EARP/apps/earp-server/src/earp_server/connector.py:146)

JSON 解析失败后的回退从贪婪正则改为括号计数法：

- 找第一个 `{`，用 depth 计数器匹配对应的 `}`
- 深度归零时截取 `content[start:end]`
- 不平衡或未找到 `{` 时抛 ConnectorError

正确处理嵌套 JSON 和含多个 JSON 对象的 LLM 响应。✅

### B5. [llm_cache.py](/Users/linkunpeng/work/EARP/apps/earp-server/src/earp_server/infra/llm_cache.py)

两处 P2 未修改：
- 多 worker 文档：模块 docstring 已有 "per-process lifetime" 提示，虽未显式说明多 uvicon worker 场景，但语义已足够清晰。⬜
- `time.monotonic()` suspend 影响：影响细微（缓存多存活 suspend 时长），低优先级。⬜

### B6. [task_planner.py:L91-103](/Users/linkunpeng/work/EARP/apps/earp-server/src/earp_server/planner/task_planner.py:91)

```python
def _cap_id_to_adapter(capability_id: str) -> str:
    """Convert capability_id to adapter_type.

    Convention: capability_id = "cap-{domain}-{name}", adapter_type = "{domain}.{name}".
    Only replaces hyphen between domain and name (the last segment boundary).
    """
    if capability_id.startswith("cap-"):
        rest = capability_id[4:]
    else:
        rest = capability_id
    idx = rest.rfind("-")
    if idx != -1:
        return f"{rest[:idx]}.{rest[idx + 1:]}"
    return rest
```

**PASS** 用 `rfind("-")` 仅替换最后一段连字符。验证：

| 输入 | 输出 | 预期 |
|------|------|------|
| `cap-demo-echo` | `demo.echo` | ✅ |
| `cap-query-users` | `query.users` | ✅ |
| `cap-create-alarm` | `create.alarm` | ✅ |
| `cap-my-service` | `my.service` | ✅ |
| `cap-a-b-c` | `a-b.c` | ⚠️ 不在当前命名规范内 |

回退路径（[L82](/Users/linkunpeng/work/EARP/apps/earp-server/src/earp_server/planner/task_planner.py:82)）直接用 `match.adapter_type` 从 business_dictionary 取值，不再依赖字符串推导。✅

### C8. [invoke.py:L110](/Users/linkunpeng/work/EARP/apps/earp-server/src/earp_server/runtime/invoke.py:110)

```python
"res": json.dumps(result.output) if result.output is not None else None,
```

**PASS** 改为 `is not None` 判断，空 dict `{}` 不会被 Python falsy 语义误判而存 NULL。✅

### E10. [pyproject.toml](/Users/linkunpeng/work/EARP/apps/earp-server/pyproject.toml)

`httpx>=0.27` 已从 `[dependency-groups].dev` 中移除，仅保留在主 `dependencies`。✅

---

## 第一轮已 PASS 项（r2 不变）

以下 15 项 r1 即为 PASS，r2 未变更，确认持续有效：

| 检查项 | 说明 |
|--------|------|
| A1 timeout=60s | 批量 embedding 合理 |
| A1 _BATCH_SIZE=32 | bge-m3 保守安全 |
| A1 dim 一致 | embedding_dim=1024 与 DDL 一致 |
| A1 空 chunk_ids | 早期返回 |
| A2 ALTER TYPE | pgvector 支持 |
| A2 downgrade | 正确回退 1536 |
| A2 statement_timeout=120s | 合理 |
| A3 search_service embedding_dim | f-string 来自 config，安全 |
| A3 search_knowledge 传入 | main.py:203 正确 |
| A3 discover settings 参数 | invoke.py + main.py 已更新 |
| B4 format:json+temperature=0.1 | 合理 |
| B4 SHA256 cache key | 防碰撞充分 |
| B4 缓存写时机 | 仅成功结果写缓存 |
| B5 TTL 可配置 | Settings.llm_cache_ttl |
| B6 plan async | 调用方已 await |
| B6 LLM 异常日志 | logger.warning(..., exc_info=True) |
| B7 测试环境 LLMCache | lazy Redis 连接，不阻塞 |
| B7 cache setter | 接受 None |
| C8 checkpoint.py:40 | json.dumps(state) |
| C8 consumer.py:35 | json.dumps(event.data) |
| C8 全局扫描 | 无遗漏 dict→JSONB |
| D9 test_e2e 列名 | user_id/entity_id/thread_id 正确 |
| E10 httpx 主依赖 | 已移到 dependencies |
| E11 ollama_base_url | 环境变量可覆盖 |

---

## 最终汇总

| 严重度 | 数量 | 状态 |
|--------|------|------|
| P0 | 0 | — |
| P1 | 0 | 全部修复 |
| P2 | 3（遗留）| A2 lock_timeout / B5 多worker文档 / B5 monotonic |
| P3 | 0 | 已修复 |

三个遗留 P2 均属可接受的非阻塞项：建议生产部署前调整 A2 lock_timeout；其余两项影响极小，可在后续迭代中处理。
