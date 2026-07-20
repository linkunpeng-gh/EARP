# Phase 2 评审 Prompt

> 一刀。改动 15 个文件（13 修改 + 2 新建）。输出 `arch/reviews/phase2-review.md`。

```bash
cd /Users/linkunpeng/work/EARP && codex exec "Phase 2 代码评审：真实 Embedding + Structured Output + LLM 缓存。

评审对象（核心新功能，7 个文件）：

1. apps/earp-server/src/earp_server/config.py (+ollama_base_url, ollama_embedding_model, ollama_chat_model, embedding_dim, llm_cache_ttl)
2. apps/earp-server/src/earp_server/knowledge/embedding_service.py (伪随机→Ollama bge-m3，httpx 异步，批量 32)
3. apps/earp-server/migrations/versions/0004_change_embedding_dim_1024.py (新建：ALTER vector(1536)→vector(1024))
4. apps/earp-server/src/earp_server/connector.py (LLMConnector: ollama /api/chat + format:json + cache)
5. apps/earp-server/src/earp_server/infra/llm_cache.py (新建：Redis+内存双栈，SHA256 key，TTL)
6. apps/earp-server/src/earp_server/planner/task_planner.py (SimpleTaskPlanner: async plan, LLM 优先→规则回退)
7. apps/earp-server/src/earp_server/main.py (lifespan: LLMCache + LLMConnector 注入 planner)

评审对象（配套变更，6 个文件）：

8. apps/earp-server/src/earp_server/knowledge/search_service.py (vector(1536)→动态 embedding_dim)
9. apps/earp-server/src/earp_server/capability/registry.py (同上 + discover 加 settings 参数)
10. apps/earp-server/src/earp_server/runtime/invoke.py (discover 传 settings + result dict→json.dumps)
11. apps/earp-server/src/earp_server/infra/checkpoint.py (state dict→json.dumps)
12. apps/earp-server/src/earp_server/audit/consumer.py (detail dict→json.dumps)
13. apps/earp-server/pyproject.toml (+httpx 主依赖)
14. apps/earp-server/tests/test_e2e.py (3处列名修复: role_id→user_id, execution_id→entity_id, checkpoint_id→thread_id)

检查项：

A. 真实 Embedding (#7 bge-m3)：

1. embedding_service.py：
   - _ollama_embed() 使用 httpx.AsyncClient(timeout=60)——超时是否合理？失败时是否正确 raise RuntimeError？
   - embed_chunks 先读 chunk content 再批量 embed——_BATCH_SIZE=32 对 bge-m3 是否安全？
   - embed_chunks UPDATE 用 :emb::vector({dim})——dim 从 settings.embedding_dim 传入，与 DDL 列维度是否一致？（migration 0004 改为 1024）
   - 是否有对空 chunk_ids 或 Ollama 返回空 embeddings 的防御？

2. migration 0004：
   - ALTER COLUMN embedding TYPE vector(1024)——pgvector 是否支持直接 ALTER TYPE？（已知：支持）
   - downgrade 是否正确回退到 vector(1536)？
   - lock_timeout=5s + statement_timeout=120s 是否合适？

3. search_service.py / registry.py：
   - vector({embedding_dim}) 用 f-string 拼接——embedding_dim 来自 config 非用户输入，安全。但调用方是否都正确传入？
   - registry.discover() 加 settings= 参数后，所有调用方是否已更新？（invoke.py + main.py 两处）

B. Structured Output (#8 Ollama JSON mode)：

4. connector.py LLMConnector：
   - _call_ollama() 用 format:\"json\" + temperature=0.1——是否合理？
   - JSON 解析失败后尝试 re.search(r'\\{[\\s\\S]*\\}', content)——这个回退策略是否足够健壮？
   - plan() 的缓存检查在 LLM 调用之前——cache key 用 SHA256(model||prompt) 是否防碰撞？
   - plan() 回退链：cache hit → Ollama → RuleIntentPlanner。Ollama 失败时 cache 是否不写入？（当前正确：except ConnectorError 不写 cache）
   - LLMConnector.__init__ 需要 Settings 对象——是否与 Connector（不需要 Settings）的接口一致？调用方是否都传入 Settings？

5. llm_cache.py：
   - Redis 连接失败→内存 fallback——内存缓存在多进程（uvicorn workers）场景下是否共享？（不共享——注释应该说明）
   - setex 在 Redis 成功后仍写内存——是故意双写还是冗余？
   - _mem dict 使用 time.monotonic() 做过期——进程暂停（sleep/hibernate）后 monotonic 是否受影响？（monotonic 不受系统时间调整影响，但受 suspend 影响——进程挂起期间不计时）
   - TTL 硬编码 3600——是否应可配置？（已通过 Settings.llm_cache_ttl 配置 ✅）

6. task_planner.py：
   - plan() 改为 async——所有调用方是否已 await？（main.py /plan endpoint ✅）
   - LLM 返回 steps 用 Step 包装——capability_call 的 adapter_type 用 capability_id.replace——这个转换是否适用于所有 capability_id 格式？（例如 cap-demo-echo → demo.echo ✅，cap-query-users → query.users ✅）
   - LLM 失败后 fallback 到 RuleIntentPlanner——是否吞掉了异常日志？（logger.warning(..., exc_info=True) ✅）

7. main.py lifespan：
   - LLMCache 和 LLMConnector 在 lifespan 创建——测试环境(app_env=test)是否也会尝试创建？（是——但 LLMCache 的 Redis 连接是 lazy 的，test 不会触发连接 ✅）
   - llm_connector.cache 通过 setter 注入——这个 setter 是否需要防御 None？（setter 接受 None ✅）

C. psycopg3 dict→JSONB 修复（3 处预存坑）：

8. checkpoint.py / consumer.py / invoke.py：
   - json.dumps 是否覆盖了所有 dict→JSONB 路径？搜索其他可能遗漏的 INSERT/UPDATE 参数中的 dict 值。
   - invoke.py:104 result.output 可能为 None——json.dumps(None) 返回 'null'，传入 JSONB 列是否正确？
   - consumer.py:34 event.data 是 dict——json.dumps 后 detail 列存的是 JSON 字符串而非 JSONB 对象。查询时是否需要 ::jsonb 转换？

D. e2e 测试修复：

9. test_e2e.py：
   - role_id→user_id：audit_logs 表确实没有 role_id 列（只有 user_id）——验证了 DDL。
   - 同理 execution_id→entity_id：audit_logs 用 entity_id 存 execution_id。
   - checkpoint_id→thread_id：checkpoint_blobs 用 thread_id（=execution_id）关联。

E. 依赖与整体：

10. pyproject.toml：
    - httpx 从 dev-deps 移到主 deps——是否有循环依赖或版本冲突？
    - httpx>=0.27 与 starlette TestClient 内置的 httpx 版本是否兼容？（已知警告：starlette 推荐 httpx2）

11. Ollama 可用性：
    - Ollama 地址硬编码在 config 默认值 (http://10.188.2.230:11434)——生产环境是否应通过环境变量覆盖？（Settings 已支持 EARP_OLLAMA_BASE_URL ✅）
    - bge-m3 和 qwen3.6:35b 两个模型都在该 Ollama 实例上——如果模型未 pull，embedding/plan 会报什么错误？（RuntimeError with HTTP error）

输出：逐项 PASS/ISSUE + P0/P1/P2 + file:line。中文。
已知限制：Ollama 不可达时 embedding 会抛 RuntimeError（不降级），LLMConnector.plan() 会回退到 RuleIntentPlanner。" > arch/reviews/phase2-review.md 2>&1
```
