# Gate B — L3 设计 v1.0 评审报告

**评审对象：** `arch/design/server-m1-l3-design-v1.md`（DESIGN-SERVER-M1-L3 v1.0）
**上游契约：** PRD-2026-021 v1.1（11 US，12 AC）
**评审标准：** AC 逐条→设计条目覆盖、接口签名完整、Checkpoint 3 表语义正确、Step Runner 三形态锁定、Layer 链、EventBus 设计、AC-09 策略、F1-F5 设计

---

## 评审结论：🔴 2 P0 + 3 P1 + 4 P2（P0 阻塞实现启动）

| 级别 | # | 类别 | 发现 | AC/PRD 引用 | 影响 |
|:---|:--:|:-----|:-----|:-----------|:-----|
| **P0** | 1 | 设计矛盾 | **EventBus "同步调用所有订阅者" 与 PRD "异步不阻塞 invoke 返回" 直接矛盾**。L3 §2.5 注释 `# 内部: dict[str, list[Callable]]，同步调用所有订阅者` + handler 签名 `Callable[[CloudEvent], Awaitable[None]]`。若 publish() 同步 await audit_handler → DB INSERT，则 invoke 返回被审计写盘阻塞；若不 await，handler 返回的 coroutine 未调度永不执行。两种解读均不可接受。 | PRD §3.1 #10："异步，不阻塞 invoke 返回"；AC-04 audit 记录生成 | **阻塞：audit 路径语义不明确无法编码。** 须在 `publish()` 签名层明确 fire-and-forget（`asyncio.create_task`）或显式声明 M1 简化策略并更新 PRD。 |
| **P0** | 2 | 设计缺失 | **executions 表行写入在设计流程中无体现**。PRD §3.1 #4 要求 invoke 中写 executions 行（status pending→completed/failed）。invoke.py 流程注释仅 4 步（获取ctx→解析capability→构造Step→返回Response），StepRunner.invoke() 签名也未提及 execution 行的创建/状态转换。execution_id 出现在 InvokeResponse 中但无来源。 | PRD §3.1 #4："写 executions 行（status 从 pending→completed/failed）" | **阻塞：execution_id 从何处生成、execution 行由哪个模块（invoke端点/StepRunner/orchestrator）写入，设计未决策。** |
| **P1** | 3 | 模块缺失 | **Connector 模块完全缺失——无文件、无接口签名、无 tenacity 集成**。PRD §3.1 #12 明确列出 Connector 模块 + tenacity 重试策略（`retry=retry_if_exception_type(ConnectorError), wait=wait_exponential_jitter, max_attempts=3`）。目录结构 §一 共 10 个文件，无 connector.py。仅 Step.retry_config 字段间接提及，但 Connector 本身不存在——StepRunner 调用谁？谁持有 tenacity 装饰器？impact analysis §1.4 也将 AC-07 映射到 "connector（增强重试）"，确认该模块属于交付范围。 | PRD §3.1 #12；AC-07："Connector 调用失败后重试 3 次后抛出"；impact §1.4 AC-07→connector | **实现风险：Connector 是 StepRunner 调用 capability 的唯一通道，缺失则 invoke 路径断裂。** 须补充 `connector.py` 文件、`Connector` 类签名、tenacity 装饰器位置。 |
| **P1** | 4 | 接口不一致 | **StepResult.status 缺失 "retrying" 状态值**。PRD §4.3 定义 `status: Literal["completed", "failed", "retrying"]`；L3 §2.3 仅 `Literal["completed", "failed"]`。"retrying" 是 AC-07 Connector 重试的关键中间状态——若 StepResult 无法表达重试中，AuditLayer 无对应事件可发布。 | PRD §4.3；AC-07 Connector retry 触发 | **接口契约断裂：retry 状态无法传递到 Layer 链和上层调用方。** |
| **P1** | 5 | 签名不完整 | **CheckpointStore.write() 缺少 channels/blobs 参数入口**。L3 §2.4 签名 `async def write(self, execution_id, session_id, tenant_id, state: dict) -> str`，注释称"写 checkpoint_blobs 行（每个 channel 值 BYTEA）"。但：(a) channels 列表从何而来？state dict 内嵌还是独立参数？(b) 若从 state 提取，提取规则未定义。§三 3 表语义表进一步要求 blobs 写入 ≥1 行，与签名不一致。 | PRD §3.1 #8；AC-05："checkpoints + checkpoint_blobs 表在 invoke 后有数据" | **实现歧义：开发者无法从签名推断 blob 写入逻辑。** 须在签名中增加 `channels: dict[str, bytes]` 或在设计注释中说明 state 内部的 channel 提取契约。 |
| **P2** | 6 | 占位缺失 | **PolicyLayer 挂载位无显式 stub 类或注释**。PRD §3.1 #7 要求"接口留 PolicyLayer 挂载位（M2 填充）"。L3 通过 `layers: list[Layer]` 参数隐含支持，但 layers.py 仅含 `Layer(Protocol)` + `AuditLayer`，无 PolicyLayer 占位类、无 `# M2: PolicyLayer goes here` 注释。对比 stream/batch 的显式 NotImplemented 占位，PolicyLayer 缺乏同等防护。 | PRD §3.1 #7："接口留 PolicyLayer 挂载位（M2 填充）" | **M2 接入时可能遗漏挂载点。** 建议在 layers.py 增加 `class PolicyLayer: ...  # M2` 空实现或模块级注释标记。 |
| **P2** | 7 | 命名不一致 | **invoke.py 注释 `orchestrator.run()` 与 StepRunner 方法名 `invoke()` 不一致**。L3 §2.2 invoke.py 注释写 `orchestrator.run(step, layers=[AuditLayer()])`，但 §2.3 StepRunner 实际方法为 `async def invoke(...)`。`orchestrator` 是包名，`run` 函数在设计其他位置未定义。 | — | **实现混淆：开发者可能去寻找不存在的 `run` 函数。** 统一为 `step_runner.invoke(step, layers=[...])`。 |
| **P2** | 8 | 数据字段偏离 | **CloudEvent 新增 `subject` 字段不在 PRD 数据契约中**。PRD §4.4 CloudEvent 含 8 个字段（specversion/type/source/id/time/tenant_id/datacontenttype/data）；L3 §2.5 增加 `subject: str`，CloudEvents 1.0 规范中 subject 为可选字段，功能无影响但偏离 PRD 契约。 | PRD §4.4 | **无功能影响，但评审追溯时产生差异噪音。** 建议在设计中标注 `subject` 为 L3 扩展或回归 PRD 字段集。 |
| **P2** | 9 | 文件名不一致 | **impact analysis 用 `invoke_endpoint.py`，L3 设计用 `invoke.py`**。impact §1.1 列出 `runtime/invoke_endpoint.py`，L3 §一 目录结构为 `runtime/invoke.py`。同一个文件两个名字。 | impact §1.1 vs L3 §一 | **创建文件时可能用错名字。** 统一为一个（建议 `invoke.py`，简洁且包路径已含 runtime 语义）。 |

---

## AC 覆盖逐条验证（附注）

| AC | L3 设计覆盖 | 判定 |
|:--:|:-----------|:----:|
| AC-01 | `auth.py jwt_middleware` + `session_service.create_session` + 测试 `test_jwt_auth.py` / `test_sessions_api.py` | ✅ |
| AC-02 | `session_service.get_session` + 测试 `test_sessions_api.py` | ✅ |
| AC-03 | `invoke.py` 路由 + `StepRunner.invoke` + 测试 `test_sessions_api.py` | ✅ |
| AC-04 | `AuditLayer` → `EventBus.publish` → `audit_handler` → DB INSERT + 测试 `test_invoke_checkpoint.py` / `test_eventbus_audit.py` | ⚠️ P0-#1 事件路径阻塞语义不明确 |
| AC-05 | `CheckpointStore.write` → checkpoints + blobs + 测试 `test_invoke_checkpoint.py` | ⚠️ P1-#5 签名缺 channels 参数 |
| AC-06 | `StepRunner.invoke/stream/batch` 三形态 + 测试 `test_step_runner.py` | ✅ stream→`AsyncGenerator[StepEvent]` + NotImplemented；batch→`list[StepResult]` + NotImplemented |
| AC-07 | `Step.retry_config` + 测试 `test_step_runner.py` "Connector retry 触发" | 🔴 P1-#3 Connector 模块不存在，retry 无法落地 |
| AC-08 | `session_service.close_session` + 测试 `test_sessions_api.py` "全生命周期" | ✅ |
| AC-09 | §五 3 组 37 测试策略 + CI 4 步 + `--earp-endpoint` fixture | ✅ 分组清晰，skip 理由（流式/批处理未实现）合理 |
| AC-10 | `registry.py discover(q)` + 测试 `test_capability_registry.py` | ✅ 精确匹配 `LIKE '%q%'`，无 pgvector |
| AC-11 | `input_guard.py sanitize_body` + 测试 `test_input_guard.py` | ✅ UNION SELECT/DROP TABLE/1=1/xp_cmdshell 黑名单 |
| AC-12 | §六 F1-F5 设计 + 测试 RLS 全表矩阵/幂等/SDK 版本回归 | ✅ F4 `enqueue_in_session` 签名完整，F5 "24 表逐表 INSERT+SELECT+UPDATE+DELETE" |

---

## 整体评价

**设计质量：中上。** AC 覆盖度完整（12/12 有对应设计条目），Step Runner 三形态锁定、Layer Protocol 链、3 表 Checkpoint 语义（特别是 writes 表 M1 不写入的边界声明）、AC-09 SDK 分组策略均**设计到位**。

**2 个 P0 须在实现启动前修复：** EventBus 阻塞语义（fire-and-forget vs await）和 executions 行写入责任归属。前者是架构语义缺陷，后者是流程断链。**3 个 P1 中 Connector 模块缺失最为紧迫**——StepRunner 调用 capability 的通道在设计层不存在，实现将无法推进。其余 P1/P2 为接口细节修正，可在编码阶段边写边修。
