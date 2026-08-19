# 任务清单 — Chatflow F0: workflow 真实化（声明式 JSON → 编译 → 执行闭环）

**状态：✅ 已完成（2026-08-19）**，验证见 `arch/session-record.md`（追加 2026-08-19 Chatflow F0 段）
**依据**：`arch/design/2026-08-18-chatflow-integration-design.md` §7（F0 定义）+ §8（schema 形状对齐 Dify `{nodes, edges}`）+ 2026-08-18 会话决策（不引 graphon，自研）
**关联**：F0 是 Chatflow 融入第一块——把死代码 `workflow_dsl` 变成「声明式 JSON → 编译 → 执行」的闭环，作为 Chatflow 图执行器与能力编排共用的骨架
**日期**：2026-08-19

## 目标

1. **声明式 JSON 可驱动 MultiStepExecutor 执行**：graph-shaped schema（`{nodes:[{id,type,data}], edges:[{source,target}]}`，ReactFlow 兼容）→ compile → 扁平 Step 列表 + 分支元数据 → 真实执行（checkpoint/Saga/retry 全复用）
2. **Conditional 运行时求值/分支选择**：现 flatten 两分支都编译执行（死代码无此路径），F0 实现运行时 skip——**不执行未命中分支的副作用**
3. **零回归**：MultiStepExecutor 既有语义不动（legacy 路径无 plan 参数时行为完全一致）；全量 223+ tests + import-linter + ruff/pyright 零新增

## 现状（已核实，2026-08-19）

- **MultiStepExecutor**（`orchestrator/multi_step.py`）✅ 真实可用：`execute(steps, ctx, layers, resume_from_checkpoint_id, durability)` 顺序执行 + checkpoint-after-each-step + Saga 补偿 + interrupt/resume 状态机；StepRunner.invoke 每步写 checkpoint（`checkpoint_ns=plan:{step_id}`）
- **workflow_dsl**（`orchestrator/workflow_dsl.py`）❌ 死代码：Sequential/Conditional/Parallel/StepNode 树形 dataclass + `compile_workflow(root) -> list[Step]`——**零调用方、零测试**；Conditional.flatten 两分支都编译进 Step 列表，docstring 声称「运行时由 MultiStepExecutor skip 逻辑处理」——**该逻辑不存在**
- `Step` = `{step_id, capability_call, retry_config, timeout_seconds, compensate_call}`；`StepResult.status: Literal["completed","failed","retrying"]`
- `resume_from_checkpoint_id` 无任何调用方（仅签名存在）；checkpoint blob `step_results` 存 `str(results)`（Python repr）
- Layers 消费 `ctx.step`（PolicyLayer 权限查 capability_id）——plan 路径逐步替换 `ctx.step` 后调用
- 测试基建：`migrated`/`app_url` fixture（PG16+pgvector 单容器，session 级）；`demo.echo` 适配器返回 `{"echo": input}`；`nonexistent.fail` 触发失败
- 基线：223 tests 全绿、工作树干净；pytest 需 `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 EARP_OLLAMA_CHAT_MODEL=qwen2.5:1.5b`

## 既定决策（2026-08-18 设计稿 §7/§8 + 会话，勿推翻）

| # | 决策点 | 方案 |
|:-:|:---|:---|
| D1 | schema 形状 | **graph-shaped**：`{nodes:[{id,type,data}], edges:[{source,target,sourceHandle}]}`——对齐 Dify/graphon + ReactFlow 兼容（F1 flow_schema JSONB 直接存，F5b Drawflow 导出即此形状）。**不用**树形嵌套 DSL |
| D2 | 节点类型白名单（F0） | `start` / `end` / `step` / `condition`（F2+ 加 LLM/Knowledge/QU/Capability 等） |
| D3 | 条件求值 | **结构化 ConditionExpr**：`{left: "n1.output.echo.msg", op: "==", right: "hello"}`——确定性、可测、无 LLM；left 为点路径（首段 node_id，次段 `output`，其余为 output dict 路径）；op ∈ `== != > >= < <= contains exists`；right 为字面量（F0 无右值引用，`{{#node.output#}}` 模板引用是 F2+） |
| D4 | 编译产物 | `CompiledWorkflow`：`sequence: list[StepExec|CondExec]`（线性执行序，含条件决策点）+ 派生的 `steps/step_ids`。**gate**（分支上下文）由前向遍历 + join 处取交集计算：节点被条件 c 门控 ⟺ 所有路径都必须经 c 的某分支边 |
| D5 | 接线方式 | `MultiStepExecutor.execute(..., plan: CompiledWorkflow | None = None)`——plan=None 走 legacy 路径（逐字节不变）；plan 提供走 `_execute_plan`（复用 runner/checkpoint/Saga 逻辑）；`StepResult.status` 扩展 `"skipped"` |
| D6 | skip 语义 | 未命中分支的 StepExec **不调 StepRunner.invoke**（无 Layers/无副作用），直接产出 `StepResult(status="skipped")` + 轻量 checkpoint（`current_step_index` 推进保持一致）；被门控的 CondExec 不求值（命中分支的条件才求值） |
| D7 | 校验 | `validate_workflow(graph) -> list[str]`（F5a 前端复用）+ `compile_workflow` 校验失败抛 `WorkflowValidationError`。校验项：节点 id 唯一/边引用存在/恰一 start·end/start 无入边·end 无出边/**无环（Kahn 拓扑）**/全节点 start 可达且可达 end/非 condition 节点出边 ≤1（F0 无并行）/condition 恰 2 出边且 sourceHandle ∈ {true,false} 各一/step 节点必有 capability_call/节点类型白名单 |
| D8 | 失败语义 | 条件求值错误（引用缺失节点/类型不符）→ 该条件作为 `failed` 结果返回 + 状态 FAILED（**不触发 Saga 回滚**——条件是控制流非业务步骤，记遗留）；条件分支与 checkpoint resume 的池恢复：resume 时从 step_results blob（ast.literal_eval 兼容 repr）重建 pool——数据已存在，F0 顺带做但不加专属测试 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — workflow_dsl 重写：schema + 校验 + 编译 + 条件求值（1 天）
**文件**：`src/earp_server/orchestrator/workflow_dsl.py`（重写，删树形 dataclass）
- Pydantic 模型：`WorkflowNode{id,type,data}` / `WorkflowEdge{source,target,sourceHandle}` / `WorkflowGraph{nodes,edges}` / `ConditionExpr{left,op,right}`（op 校验 ∈ 白名单）
- `validate_workflow(graph) -> list[str]`：D7 全部校验项（Kahn 拓扑排序判环 + 可达性 BFS）
- `compile_workflow(graph) -> CompiledWorkflow`：校验 → 拓扑序 → gate 前向计算（join 交集）→ `sequence`（StepExec/CondExec，start/end 不产出执行项）
- `evaluate_condition(expr, pool: dict[str, StepResult]) -> bool`：纯函数；路径解析（首段 node_id → pool → output 点路径）；数值比较 type-coerce、字符串 str() 比较；`exists` 判路径存在；引用缺失/类型不符抛 `ConditionEvaluationError`
- 数据类型：`CompiledWorkflow{sequence, steps, step_ids, step_index}`、`StepExec{node_id, step, gate: frozenset[tuple[str,str]]}`、`CondExec{node_id, branch_id, condition, gate}`；`WorkflowValidationError` / `ConditionEvaluationError`
- 验证：`python -c` 冒烟编译样例图（顺序/分支/嵌套/空图/非法图各一）

### Task 2 — MultiStepExecutor 接线（0.5 天）
**文件**：`src/earp_server/orchestrator/multi_step.py`、`src/earp_server/orchestrator/types.py`
- `types.py`：`StepResult.status` Literal 扩 `"skipped"`
- `execute(..., plan: CompiledWorkflow | None = None)`：plan 非 None 时委托 `_execute_plan`
- `_execute_plan(plan, ctx, layers, resume_from_checkpoint_id)`：
  - pool（node_id → StepResult）+ chosen（branch_id → "then"/"else"）；resume 时从 step_results blob（ast.literal_eval）重建 pool，`current_step_index` 语义保持（计 StepExec 数）
  - 循环 `plan.sequence`：CondExec → gate 满足才 `evaluate_condition`（错误 → failed 结果 + FAILED 返回）；StepExec → gate 不满足 → skipped 结果 + 轻量 checkpoint；满足 → `dataclasses.replace(ctx, step=item.step)` + `runner.invoke`（Saga 注册/失败回滚/checkpoint/interrupt 全镜像 legacy）
- 验证：既有 test_saga 全绿（legacy 零改动）

### Task 3 — 单测（0.5-1 天）
**文件**：`tests/test_workflow_f0.py`（新）
- 编译层（纯函数，无 DB）：顺序图 steps 顺序正确 / 分支图两分支都编译 / 嵌套 gate 正确 / 空图（start+end）sequence 空 / 非法图各校验项（环、未知类型、缺 start/end、悬空边、condition 出边数错、step 无 capability_call、fan-out>1、不可达）
- 条件求值（纯函数）：各 op（==/!=/>/>=/</<=/contains/exists）+ 数值 coerce + 嵌套 output 路径 + 缺失节点抛错
- 执行层（app + migrated fixture，镜像 test_saga 模式）：
  1. **顺序**：start→n1→n2→end，两 step 均 completed，顺序正确，state COMPLETED
  2. **分支命中**：n1 echo "hello" → condition `n1.output.echo.msg == "hello"` → true 分支 n2 执行、false 分支 n3 **skipped**（n3 无副作用：output None、未 invoke）
  3. **分支未命中**：condition 反向 → n3 执行 n2 skipped
  4. **嵌套**：c1 true → n2 → c2 false → n4；c1 false → n3 —— n2/n4 completed、n3/n5 skipped
  5. **空图**：nodes=[start,end] → 0 steps → results 空、COMPLETED
  6. **条件求值错误**：condition 引用不存在的 node → failed 结果 + FAILED 状态
- 断言 skip 副作用的方式：demo.echo 的 output 即输入——skipped 分支的 echo msg 绝不出现在任何 completed output 中

### Task 4 — 校验 + 收尾（0.5 天）
- `make lint`（ruff check/format + pyright）零新增；import-linter（`pytest tests/test_import_linter.py`）通过
- 全量 pytest（223 + 新增）绿
- dev 冒烟：编译示例图（分支场景）真跑 MultiStepExecutor（Ollama env 带上），观察 checkpoint 落库、skipped 步无副作用

### Task 5 — dev 实测 + 会话记录（0.5 天）
- dev 真 API 侧验证不引端点（F0 无端点变化）；用一段脚本直调 compile + execute 冒烟（复用 earp_app 角色 + tenant_session 语义，或本地 dev DB 直跑）
- `arch/session-record.md` 末尾追加 2026-08-19 Chatflow F0 段（含遗留：checkpoint resume 条件池恢复测试未做/条件失败不回滚/Parallel 移除）
- 设计稿 §7 F0 行标 ✅（如需）

## 依赖关系

```
Task 1（schema+编译+求值）→ Task 2（接线）→ Task 3（测试）→ Task 4（质量门）→ Task 5（收尾）
Task 1 的条件求值纯函数可与 Task 3 部分并行
```

## 验收标准

1. 声明式 JSON（graph-shaped）可驱动 MultiStepExecutor 真实执行（checkpoint/Saga/retry 复用）
2. Conditional 只走命中分支：未命中分支的 step **不被 invoke**（无副作用）——以 echo output 断言验证
3. 顺序/分支/嵌套/空图单测绿；非法图校验项全覆盖
4. 全量 pytest 绿（223 基线 + 新增）+ import-linter + ruff/pyright 零新增；OpenAPI 无变化（F0 无端点）
5. legacy 路径零改动：`execute(steps, ...)` 不带 plan 行为与之前完全一致（test_saga 等既有用例验证）

## 风险提示

1. **skip 与 checkpoint 的一致性**：skipped 步也写 checkpoint（index 推进）——resume 时决策确定性依赖 pool 重建；若 blob 解析失败（旧 repr 格式），条件引用前序输出会求值报错 → 以 failed 结果暴露而非静默错分支（F2+ 对话节点接入时补 pool 恢复专属测试）
2. **gate 计算正确性**：join（多入边）节点的门控 = 各入边上下文交集——series-parallel 结构下即「嵌套分支上下文」；实现用前向遍历 + 交集，单测覆盖嵌套场景
3. **ctx.step 逐步替换**：plan 路径 PolicyLayer 权限检查依赖当前步——务必 `dataclasses.replace` 后传入，勿复用起始 ctx
4. **类型放宽**：`StepResult.status` 加 `"skipped"` 是类型扩展——审计该 Literal 的所有消费方（multi_step/layers/invoke 均已核实，skipped 不经过 layers、invoke 单步不可见）
5. **F0 无端点**：不建任何 API 路由（F1 才存 flow_schema JSONB）；OpenAPI 基线必须无变化

---
**规划定稿，确认后按执行序开工。**
