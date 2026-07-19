# EARP 服务端开发复盘（2026-07-18 → 2026-07-19）

## 量化交付

| 指标 | 数值 |
|:-----|:----:|
| 里程碑 | M0→M7（7 个，全闭环） |
| commits | 8（d466103→a880767） |
| 源文件 | 50+ 模块（10 域：gateway/runtime/capability/policy/planner/knowledge/conversation/schedule/orchestrator/audit + infra/mcp/plugin） |
| DDL | 25 表（14 已用 / 11 M7+ 预留） |
| PRD | 7 份 |
| 测试 | 24/24 服务端 + 37/37 SDK 集成 |
| 评审记录 | 15+ 份（单里程碑 Gate A/B/C + 全景 4 刀） |
| 总行数 | ~5000+ 新增 |

---

## 2. 里程碑演进

| M | 核心交付 | 关键决策/发现 |
|:--|:-----|:-----|
| M0 | 脚手架 + 25表DDL + procrastinate spike | psycopg3代替asyncpg；procrastinate→Celery双栈；checkpoint 3表(非2表) |
| M1 | JWT+Session+Invoke+Audit+Checkpoint | StepRunner三形态一次定义；Orchestrator Layer拦截器链；SET LOCAL不支持参数化绑定 |
| M2 | PolicyLayer鉴权+限流+Capability角色过滤 | psycopg `:`占位符与数组字面量冲突；RBAC种子数据需用exec_driver_sql |
| M3 | RuleIntentPlanner+SimpleTaskPlanner+LLMConnector | Pydantic model需模块顶层(非函数内)；LLMConnector五挂点接口定稿 |
| M4 | Knowledge+Conversation+pgvector+pseudo-embedding | langchain-text-splitters MIT依赖；RecordManager增量索引 |
| M5 | 多步编排+Retry四参数+Saga补偿+Durability三档 | batch()接口设计但M5用for-loop替代；ckpt_writes表未启用 |
| M6 | RedisStreams EventBus+WebSocket Gateway | EventBus publish/subscribe签名零改变；fallback机制 |
| M7 | Plugin五段流程+MCP Server+Egress管控 | JSON-RPC 2.0协议 |

---

## 3. 架构决策回顾

| 决策 | 结果 | 评价 |
|:-----|:-----|:----:|
| ADR-007 模块化单体 | 10域全部在main.py会合，未拆服务 | ✅ 正确——单人开发零运维开销 |
| procrastinate(D6) | M0 spike 4/4 PASS，M1 enqueue_in_session落地 | ✅ 单栈async+事务入队 |
| Layer拦截器链(M1) | M2 PolicyLayer零侵入接入；AuditLayer角色信息在M2补充 | ✅ 接口一次到位 |
| InvokeContext 字段稳定(M1) | tenant_id/execution_id/session_id/user_id/role_id 跨M1-M5无变更 | ✅ 契约稳定 |
| StepRunner三形态(M1) | stream/batch 仍为NotImplementedError；M5用for-loop替代batch | ⚠️ batch存疑——设计时高估需求 |
| LLMConnector五挂点(M3) | 1/5已实现(rate_limiter)，4/5声明留Phase 2/3 | ✅ 接口不返工 |
| EventBus抽象(M1→M6) | 进程内→Redis Streams，publish/subscribe签名0改变 | ✅ 接口稳定 |
| pgvector(pseudo-embedding M4) | 伪随机1536d向量，M4可用，Phase 2替换 | ⚠️ 同query不同结果——known limitation |

---

## 4. 踩坑记录

| 坑 | 里程碑 | 解决 |
|:---|:------|:-----|
| SET LOCAL不支持SQLAlchemy参数化绑定 | M1 | f-string直接插值 |
| psycopg3 dict→JSONB需显式json.dumps | M1 | 全模块统一加json.dumps |
| orchestrator循环导入(layers↔step_runner) | M1 | 引入shared types模块 |
| psycopg `:`在数组字面量中被当占位符 | M2 | exec_driver_sql / ARRAY语法 |
| Pydantic model在create_app()内部无法导出OpenAPI | M3/M4 | 提到模块顶层 |
| ASGITransport不触发FastAPI lifespan | M1 | 改用TestClient |
| Claude Code `--append-system-prompt-file` 比 `cat \| claude` 稳定 | 全流程 | 模板化 |
| Claude Code `tee` 管道吞输出 | 全流程 | 用 `> file 2>&1` |
| Ruff UP042 StrEnum需手动修 | M5 | 手动替换 |

---

## 5. 技术债务（9处，全部标注里程碑）

| 位置 | 债务 | 目标 |
|:-----|:-----|:----:|
| step_runner.py:74 | stream() NotImplementedError | M6 |
| step_runner.py:77 | batch() NotImplementedError | M5 |
| embedding_service.py:14 | 伪随机1536d → 真实模型 | Phase 2 |
| connector.py:70-73 | cache/bind_tools/structured_output/stream | Phase 2/3/M6 |
| checkpoint.py:3 | writes表 + durability多档 | M5+ |
| invoke.py:7 | 多事务孤儿记录recovery | M5 |
| connector.py:93 | plan_structured() placeholder | Phase 3 |

---

## 6. 全链路评审（M0→M6全景，0 P0 / 0 P1 / 3 P2）

P2-1: WebSocket端点无JWT鉴权（dev阶段无外部连接面）
P2-2: batch()接口未被M5使用（M5用for-loop）
P2-3: 11张M7+预留DDL表当前UNUSED

---

## 7. 经验总结

**做得好的：**
1. 接口一次到位策略——InvokeContext、StepRunner三形态、EventBus抽象、Layer Protocol 贯穿全里程碑不变
2. PRD-first + Gate A/B/C 门禁——7个里程碑每个都有PRD、设计、评审、测试闭环
3. 技术选型压力测试——Celery→procrastinate翻案、psycopg3统一、langchain-text-splitters直接依赖而非参考
4. 开源分析先行——LangGraph/Dify/LangChain三份代码级分析为M0-M5的决策提供了证据链

**可改进的：**
1. batch()接口——M1设计时高估了批量需求，M5实际用for-loop。应该在M5时回填batch实现或正式废弃
2. RBAC种子数据——psycopg `:`占位符冲突导致test_rbac_scenarios.py多轮搁浅，应该在M2设计时就明确psycopg的限制
3. 伪随机embedding——M4承担了"Phase 2替换"的技术债务，但consistent embedding对RAG场景是硬需求
4. 全景评审的prompt仍需人工校验——Claude Code在跨文件全景审查中偶有推论错误（需meta-review）
