# 任务清单 — Server M1（PRD-2026-021 v1.1）

**状态：待人工确认（Phase 3 → Phase 4 门禁）**
**依据：PRD-2026-021 v1.1（Gate A PASS）+ server-m1-l3-design v1.1（Gate B r2 PASS）**
**日期：2026-07-19**

| # | Task | 关联 AC | 涉及文件 | 预估工作量 |
|:-:|:-----|:------:|:---------|:----------:|
| 1 | M0 顺手修 F1-F5：SDK 版本号 + CI matrix + utcnow + enqueue_in_session + RLS 全表矩阵+幂等 | AC-12 | libs/earp-sdk-core-py/pyproject.toml + .github/workflows/test.yml + libs/earp-sdk-{core,runtime}-py/*.py + apps/earp-server/tests/test_rls.py + test_migrations.py | 中 |
| 2 | gateway/auth.py：JWT 中间件（HS256 dev→注入 tenant_id/role_id/user_id）+ 401/403 路径 | AC-01,05 | src/earp_server/gateway/auth.py | 中 |
| 3 | gateway/input_guard.py：Body 注入模式黑名单（UNION SELECT/DROP TABLE/1=1/xp_cmdshell→400） | AC-11 | src/earp_server/gateway/input_guard.py | 小 |
| 4 | runtime/session_service.py：Session CRUD（create/get/close，租户作用域，对齐 Tenant Spec v1.2） | AC-01,02,08 | src/earp_server/runtime/session_service.py | 中 |
| 5 | infra/eventbus.py：进程内 EventBus（publish/subscribe，fire-and-forget via asyncio.create_task，CloudEvents 1.0 格式） | AC-04 | src/earp_server/infra/eventbus.py | 中 |
| 6 | audit/consumer.py：订阅 EventBus → audit_logs DB 写入（不阻塞 invoke，失败 stderr） | AC-04 | src/earp_server/audit/consumer.py | 小 |
| 7 | orchestrator/step_runner.py：Step/StepResult 数据类 + StepRunner 三形态（invoke 实现，stream/batch NotImplemented）+ InvokeContext | AC-06 | src/earp_server/orchestrator/step_runner.py | 大 |
| 8 | orchestrator/layers.py：Layer Protocol + AuditLayer（EXECUTION_STARTED/COMPLETED/FAILED CloudEvent）+ PolicyLayer 占位 | AC-04,06 | src/earp_server/orchestrator/layers.py | 中 |
| 9 | infra/checkpoint.py：CheckpointStore（write→checkpoints+blobs，channels 参数，不写 writes） | AC-05 | src/earp_server/infra/checkpoint.py | 中 |
| 10 | connector.py：Connector 接口 + tenacity @retry（3 次总尝试）+ echo adapter demo | AC-07 | src/earp_server/connector.py | 中 |
| 11 | capability/registry.py：Capability 注册+精确发现（LIKE '%q%'）+ echo capability 注册 | AC-10 | src/earp_server/capability/registry.py | 小 |
| 12 | runtime/invoke.py：POST /v1/sessions/{id}/invoke 路由（创建 execution pending 行→StepRunner.invoke→更新 execution 行→返回 InvokeResponse） | AC-03,04,05 | src/earp_server/runtime/invoke.py | 大 |
| 13 | main.py：注册新路由（/v1/sessions, /capabilities）+ EventBus 启动时绑定 audit_handler | AC-01~11 | src/earp_server/main.py | 小 |
| 14 | 测试套件：test_jwt_auth/test_sessions_api/test_invoke_checkpoint/test_step_runner/test_eventbus_audit/test_capability_registry/test_input_guard + testcontainers conftest 扩展 | AC-01~08,10,11 | tests/*.py | 大 |
| 15 | SDK 集成验证（AC-09）：CI server job 启动真实服务端→run runtime-py 37 测试（--earp-endpoint fixture）+ 流式/批处理 skip 标记 | AC-09 | .github/workflows/test.yml + tests/conftest.py（earp_endpoint fixture） | 中 |
| 16 | Phase 5+Gate C+task-log+commit | AC-12 | — | 中 |

### 依赖关系
- Task 1（M0 修复）→ 其余一切（SDK 版本号修复是 F1 的 breaking change 前提）
- Task 2 → 4/5/12/13（JWT 中间件是所有端点的前置）
- Task 5 → 6（EventBus 就绪后消费者才能绑定）
- Task 7/8 → 12（StepRunner + Layers 就绪后 invoke 端点才能集成）
- Task 9/10 → 7（CheckpointStore + Connector 被 StepRunner 内部调用）
- Task 11 → 12（Registry 就绪后 invoke 才能查 capability 定义）
- Task 2-13 → 14（所有代码就绪后跑测试）
- Task 14 → 15（测试绿后跑 SDK 集成验证）
- **建议执行序：1 → (2,3,5 并行) → (4,6,7,8,9,10,11 并行) → 12 → 13 → 14 → 15 → 16**

### 风险提示
1. F1 SDK 版本号变更后需全量回归（AC-12）——但这是 PRD 明确要求的 breaking change
2. AC-09 runtime-py invoker_http 12 测试中可能涉及未实现的流式/批处理——按 L3 策略 `pytest.skip` 标记，不阻塞 CI
3. tenacity `stop_after_attempt(3)` = 3 次总尝试（1 初调+2 重试），与 M0 spike 的 procrastinate `retry=3`（3 次重试=4 次总尝试）语义不同——不影响 M1 但记入编码注释防混

---
**确认后进入 Phase 4 编码。**
