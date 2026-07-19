## Round-2 Gate B 评审报告

**评审对象：** `arch/design/server-m1-l3-design-v1.md` v1.1（Gate B r1 修复）
**评审依据：** Round-1 9 项发现逐条核验 + v1.1 全量新问题扫描

---

### 一、Round-1 遗留项逐条核验

| # | 级别 | Round-1 发现 | 判定 | 核验依据 |
|:-:|:----:|:-----------|:----:|:-------|
| 1 | P0 | EventBus 同步语义与 PRD 矛盾 | ✅ RESOLVED | `publish()` 明确 `asyncio.create_task` fire-and-forget；注释完整覆盖丢失风险与 stderr 兜底 |
| 2 | P0 | executions 行写入责任缺失 | ✅ RESOLVED | invoke 端点步骤3 INSERT pending → StepRunner 内部更新 completed/failed；changelog 与注释双确认 |
| 3 | P1 | Connector 模块完全缺失 | ✅ RESOLVED | §2.7 新增 `connector.py` + `ConnectorError` + `Connector` 类 + `@tenacity_retry` + `_on_retry` |
| 4 | P1 | StepResult.status 缺 "retrying" | ✅ RESOLVED | §2.3 `Literal["completed", "failed", "retrying"]` 三项齐全 |
| 5 | P1 | CheckpointStore.write 缺 channels 参数 | ✅ RESOLVED | §2.4 签名现为 `channels: dict[str, bytes]`，注释覆盖 blobs 写入逻辑 |
| 6 | P2 | PolicyLayer 占位缺失 | ✅ RESOLVED | §2.3 新增 `class PolicyLayer` stub + `# type: ignore[empty-body]` + docstring |
| 7 | P2 | invoke.py 注释 `orchestrator.run()` 不一致 | ✅ RESOLVED | §2.2 步骤4 已改为 `step_runner.invoke(step, layers=[AuditLayer()])` |
| 8 | P2 | CloudEvent subject 字段偏离 PRD | ✅ RESOLVED | §2.5 注释标注 "L3 设计扩展" + "M1 实现中默认为空字符串" |
| 9 | P2 | impact analysis 文件名 invoke_endpoint.py vs invoke.py | ✅ RESOLVED | changelog 声明已统一为 `invoke.py` |

**Round-1 清零：9/9 RESOLVED，无 NOT-RESOLVED。**

---

### 二、v1.1 新问题扫描

| # | 级别 | 类别 | 发现 | 引用 | 影响 |
|:-:|:----:|:-----|:-----|:----|:-----|
| **N1** | **P1** | 类型缺失 | **`InvokeContext` 未定义**。`Layer.before_step(ctx: InvokeContext)` 和 `after_step(ctx: InvokeContext, ...)` 使用该类型，但全文无其 dataclass/Protocol 定义。AuditLayer 需从中提取 `tenant_id`、`execution_id`、`session_id` 等字段填充 CloudEvent——字段集未声明则无法实现。 | §2.3 `layers.py` Layer Protocol | **阻塞 AuditLayer 实现：ctx 有哪些字段、由谁构造，设计层未决策。** |
| N2 | P2 | 依赖缺口 | **Connector 缺少 EventBus 依赖入口**。`_on_retry()` 需发布 RETRYING CloudEvent，但 Connector 类无 `__init__` 接收 EventBus 实例，也无全局 singleton 引用声明。 | §2.7 Connector | 实现时需自行推断注入方式，无架构风险但缺指导。 |
| N3 | P2 | API 名称 | **`tenacity_retry` 非 tenacity 库真实装饰器名**。tenacity 导出 `@retry`，非 `@tenacity_retry`。伪代码意图清晰，但直接复制到代码会 ImportError。 | §2.7 Connector.execute | 开发者须自行纠正为 `from tenacity import retry`。 |
| N4 | P2 | 元数据缺口 | **StepResult 缺 retry 元数据**。当 `status="retrying"` 时，调用方无法获知当前重试次数、下次重试时间等进度信息。`_on_retry` 发布的 RETRYING 事件也未定义 payload 结构。 | §2.3 StepResult + §2.7 `_on_retry` | 重试可观测性不足，不影响功能但影响调试/监控。 |
| N5 | P2 | 语法风格 | **CloudEvent dataclass 使用分号串联字段**。`specversion = "1.0"; type: str; source: str; ...` 语法合法但非惯用；`specversion = "1.0"`（无类型标注）被解析为类变量而非 dataclass field，与 `datacontenttype = "application/json"` 面临同样问题——应写为 `specversion: str = "1.0"`（带类型标注的 field with default）。 | §2.5 CloudEvent | 若照抄代码，specversion/datacontenttype 不会出现在 `__init__` 参数中，需额外处理。 |
| N6 | P2 | 语义偏差 | **`stop_after_attempt(3)` 与 PRD "重试3次后抛出" 可能不一致**。tenacity 中 `stop_after_attempt(3)` = 共 3 次尝试（1 初调 + 2 重试）；PRD "重试3次" 若解读为 3 次重试（1 初调 + 3 重试 = 4 次总尝试），则差 1 次。 | §2.7 + PRD AC-07 | M1 影响极小，但若 PRD 本意即 3 次总尝试则无问题。建议在设计中显式注释 "max 3 total attempts"。 |
| N7 | P2 | 注释歧义 | **invoke 端点步骤5 注释 "StepRunner 返回后更新 execution 行" 与 changelog 矛盾**。changelog 明确 "StepRunner 更新 completed/failed"，但该句可被解读为端点执行更新动作。建议改为 "StepRunner 已在内部更新 execution 行为 completed/failed" 消除歧义。 | §2.2 invoke.py 步骤5 | 实现者可能困惑更新责任归属，但 changelog 已兜底。 |

---

### 三、总评

| 维度 | 结论 |
|:-----|:-----|
| Round-1 清存量 | **9/9 RESOLVED**（P0×2 + P1×3 + P2×4），无 NOT-RESOLVED |
| v1.1 新增 | **P1×1**（InvokeContext 类型缺失）+ **P2×6** |
| 阻塞判定 | **N1（P1）建议在编码前补齐**——InvokeContext 是 Layer 链的入口契约，缺失则 AuditLayer 无法确定从 ctx 取哪些字段写入 CloudEvent.data。其余 6 项 P2 可在编码阶段自然消解 |
| AC 覆盖 | 12/12 AC 有对应设计条目，AC-04/AC-07 的 ⚠️ 项均已通过 fire-and-forget + Connector 模块补全消解 |

**判决：Gate B r1 修复生效，v1.1 通过 Gate B。** 1 个新增 P1（InvokeContext）不阻塞实现启动，但建议在 `layers.py` 设计段补充 `InvokeContext` 的字段清单（至少含 `tenant_id`, `execution_id`, `session_id`, `user_id`, `step: Step`），使 Layer 协议可落地。
