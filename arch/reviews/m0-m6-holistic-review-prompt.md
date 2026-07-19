# 服务端全成果评审 Prompt（M0→M6）

> 四刀分审。输出 `arch/reviews/m0-m6-holistic-review.md`。
> M0-M5 的里程碑级评审已各自完成（见 arch/reviews/m*-holistic-review*.md），本轮聚焦跨里程碑一致性与全链路完整性。

---

## 第 1 刀：全链路 PRD→代码追溯（AC 矩阵）

```bash
cd /Users/linkunpeng/work/EARP && claude -p "跨里程碑全链路追溯审计。

覆盖 6 个里程碑：M0(脚手架+DDL) → M1(Walking Skeleton) → M2(Policy+RBAC) → M3(Reasoning) → M4(Knowledge+Conversation) → M5(Execution 可靠性) → M6(事件与流式)。

评审对象（按域组织，取关键文件）：
- apps/earp-server/migrations/versions/0001_baseline.py (M0 — 25表基线)
- apps/earp-server/src/earp_server/main.py (M0-M6 全集成的 create_app)
- apps/earp-server/src/earp_server/runtime/invoke.py (M1+M2+M5 invoke 路径)
- apps/earp-server/src/earp_server/orchestrator/layers.py (M1+M2 PolicyLayer+AuditLayer)
- apps/earp-server/src/earp_server/orchestrator/multi_step.py (M5 多步编排)
- apps/earp-server/src/earp_server/planner/ (M3 RuleIntentPlanner+SimpleTaskPlanner)
- apps/earp-server/src/earp_server/knowledge/ (M4 KB 全域)
- apps/earp-server/src/earp_server/conversation/ (M4 Conversation)
- apps/earp-server/src/earp_server/infra/ (M0-M6 基础设施层)

验证事实（可信任）：
- 24/24 测试全绿，SDK 集成 37/37 绿
- ruff/pyright/import-linter 净
- 各里程碑 Gate A/B/C 已闭环（M0 3 轮+M1 3 轮全景+M2 17 轮+M3-M6 编码后提交）

审查维度：

A. 跨里程碑契约一致性：
   - M1 定义的 StepRunner.invoke(Step) 接口——在 M5 MultiStepExecutor 和 M3 SimpleTaskPlanner.plan() 中是否保持兼容？
   - M1 InvokeContext 字段（tenant_id/execution_id/session_id/user_id/role_id）——在 M2 PolicyLayer/M5 MultiStep/M3 Planner 中是否全部被正确传递？
   - M0 DDL 的 25 表——M1-M4 的实际业务代码是否覆盖了所有表？（列出 '已用 / 未用' 对照）

B. Layer 链演化：
   - M1: [AuditLayer] → M2: [AuditLayer, PolicyLayer] — M5 多步编排是否保留此顺序？
   - M2 PolicyLayer 的 before_step→after_step 在 M5 多步中每步都调用还是仅一次？

C. Checkpoint 演化：
   - M1: checkpoint 单步→M5: checkpoint 多步+durability——writes 表在 M5 是否启用？
   - M1 CheckpointStore.write 接口在 M5 MultiStepExecutor 中兼容？

D. EventBus 演化：
   - M1: 进程内→M6: Redis Streams——接口(publish/subscribe)是否未变？
   - M6 WebSocket push_event 是否与 M1 CloudEvent 格式兼容？

E. 跨域数据流：
   - M3 SimpleTaskPlanner.plan(intent)→M1 invoke(Step)→M2 PolicyLayer 鉴权→M5 retry 策略→这个完整链路在代码中可追踪吗？
   - M4 文档上传→chunk 分块→embedding→search 流水线的事务边界在跨文件调用中是否一致？

输出：逐维度 PASS/ISSUE + file:line 证据 + P0/P1/P2。中文，表格。" --max-turns 15 --output-format text > arch/reviews/m0-m6-holistic-review.md 2>&1
```

---

## 第 2 刀：DDL 表使用率 + 技术债务清单

```bash
cd /Users/linkunpeng/work/EARP && claude -p "M0 DDL 25 表使用率扫描 + 技术债务盘点。

DDL 表清单（来自 apps/earp-server/migrations/versions/0001_baseline.py TENANT_TABLES）：
org_units, users, roles, service_accounts, tenant_account_joins,
sessions, executions, checkpoints, checkpoint_blobs, checkpoint_writes,
business_capabilities, capability_calls, connector_bindings,
policies, policy_bindings, audit_logs,
encrypted_credentials, api_keys,
knowledge_bases, documents, chunks,
conversations, messages, connector_configs

逐表判定：
- 搜索全部 src/earp_server/**/*.py 中每张表的 INSERT/SELECT/UPDATE/DELETE 引用
- 标记: USED / UNUSED / TABLE_EXISTS_ONLY
- 未使用的表是否为已规划的未来里程碑（M7+）预留？

技术债务盘点（跨里程碑搜索）：
- 'TODO' / 'FIXME' / 'Phase 2' / 'Phase 3' / 'M5' / 'M6' / 'M7' 注释的出现次数和分布
- 'NotImplementedError' 的出现位置和对应里程碑
- 伪随机 embedding (M4 embedding_service.py) 的替换计划是否注明

输出：表使用率矩阵 + 技术债务清单 + P0/P1/P2。中文，表格。" --max-turns 10 --output-format text >> arch/reviews/m0-m6-holistic-review.md 2>&1
```

---

## 第 3 刀：对抗性安全全链审计

```bash
cd /Users/linkunpeng/work/EARP && claude -p "全链路安全审计（M0→M6）。

审查维度：

A. RLS 覆盖完整性：
   - 所有 DB 操作是否携带 SET LOCAL earp.tenant_id？（全局 grep）
   - 是否有模块绕过 tenant_session/手动 SET LOCAL 而直接用裸 engine.connect()？
   - M5 execute_with_retry 在多步重试中 tenant_id 是否始终保持？

B. JWT 鉴权覆盖：
   - 所有端点是否经过 JWTMiddleware？（/health /ready 排除）
   - M6 WebSocket /ws/events/{session_id} 有无鉴权？（当前无——这是缺陷还是 by design？）

C. 异常安全：
   - 所有 HTTP 异常是否通过 HTTPException 返回（不泄露 stacktrace）？
   - EventBus fire-and-forget (asyncio.create_task) 的异常是否被 _safe_invoke 吞掉？
   - M5 补偿 rollback 异常是否吞掉（compensation.py:33 logger.exception）？

D. 资源泄漏：
   - MultiStepExecutor 长循环中 engine.connect() 是否复用连接池（非每次新建）？
   - RedisStreamsEventBus 消费者循环中的 xreadgroup → xack 是否保证 ack 不丢？
   - WebSocket 连接注册表 (_connections) 的 dead connection 清理是否完整？

输出：逐维度 PASS/ISSUE + file:line + P0/P1/P2。中文，表格。" --max-turns 10 --output-format text >> arch/reviews/m0-m6-holistic-review.md 2>&1
```

---

## 第 4 刀：架构决策一致性 + 未来演进能力

```bash
cd /Users/linkunpeng/work/EARP && claude -p "架构决策一致性终审。

检查项：

A. ADR-007（模块化单体）忠实度：
   - 是否所有 10 域模块通过 main.py create_app 注册（非独立部署）？
   - ext_* 装配模式是否正确使用？

B. TaskQueue 迁移路径：
   - ProcrastinateTaskQueue 的 Protocol 抽象是否保留 Celery fallback 位？
   - enqueue_in_session 是否在 M1 后未被其他模块使用（搜索调用方=0）？

C. 接口一次到位原则：
   - StepRunner 三形态 (invoke/stream/batch) 在 M5 后 stream/batch 仍为 NotImplementedError？（预期 M6 后 batch 应被 M5 多步编排部分实现——但当前 M5 用的是 for-loop 而非 batch 接口）
   - LLMConnector 五挂点在 M3 声明后，M4-M6 是否有新增使用？（搜索 bind_tools/structured_output/stream_enabled 调用方）

D. 未来拆分准备：
   - Audit Service 是否可拆为独立进程？（当前在 main.py lifespan 中注册，依赖 EventBus subscribe）
   - WebSocket 是否可独立进程？（当前在 main.py 内 via websocket_gateway）

E. 6 个月后的新人 onboard 可读性：
   - 核心调用链路（invoke → PolicyLayer → StepRunner → Connector.execute → CheckpointStore.write）是否可以在 5 分钟内从代码追踪清楚？

输出：逐项 PASS/ISSUE + P0/P1/P2。中文，表格。" --max-turns 10 --output-format text >> arch/reviews/m0-m6-holistic-review.md 2>&1
```

---

## r2 重评模板

```bash
claude -p "Round-2 复核。r1：arch/reviews/m0-m6-holistic-review.md。已修：...。逐项 RESOLVED/NOT-RESOLVED；新 P0/P1 扫描；verdict。中文。" --max-turns 8 --output-format text >> arch/reviews/m0-m6-holistic-review-r2.md 2>&1
```
