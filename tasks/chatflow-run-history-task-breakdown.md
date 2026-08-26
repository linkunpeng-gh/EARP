# 任务清单 — Chatflow 运行历史持久化（finished run trace，tech-debt #17）

**状态：✅ Task 1-5 代码交付（2026-08-27，commit 2fe4b92）——新增 10 项测试全绿 + ruff/pyright 零新增；全量回归与 verify_f6 待 VPN 恢复补跑（.env EARP_OLLAMA_BASE_URL=10.188.2.230 需 VPN）**
**依据**：`arch/tech-debt.md` #17（P3，2026-08-21 记入待办）+ FDE 排查需求（回看失败/历史对话执行轨迹）
**依赖**：F4 flow_runs ✅（0026 挂起/恢复载体 + 0031 rejected 终态）+ 对话日志 ✅（conversations + chat_app_id 归属 + C 系列可见性过滤）+ 前端运行抽屉 ✅（trace 展示/画布着色现成）
**日期**：2026-08-26

## 目标

1. **运行留痕**：flow 每次执行（成功/失败/驳回/超时）落一份**执行轨迹档案**——node_id/status/branch/input/output/error/error_code/latency_ms，刷新不丢
2. **可查**：管理侧按应用（chatflow 详情）与会话（对话日志）查历史执行轨迹，排查「上次为什么失败」「卡在哪个节点」
3. **零回归**：不改执行语义——只加「终态写档案」动作；内部 JWT / 对外 API（#18）路径共享同一写入点；verify_f6 80 绿

## 现状（已核实，2026-08-26）

- **flow_runs 表**（0026 + 0031）：`execution_id / tenant_id / chat_app_id / conversation_id / status(running|waiting_human|completed|failed|timeout|cancelled|rejected) / pending_node_id / node_state JSONB / flow_input JSONB / attempts / created_at / updated_at / finished_at`——**已覆盖全部关联维度，只缺 trace 列**
- **写入现状**：挂起（waiting_human）→ `update_waiting` 落 node_state（pool 序列化，仅 completed 节点）；**终态（completed/failed/rejected/timeout）→ `finish_run` 只写 status+finished_at，过程轨迹不落库**
- **trace 已构造**：`flow_chat` 返回前已组装完整 trace（按拓扑序，CondExec 分支决策来自 state.chosen；StepResult 带 input/output/error/error_code/latency_ms）——**只放在 HTTP 响应里，即用即弃**
- **恢复路径**：同 conversation 的 waiting_human run 存在 → resume（attempts+1，flow_input 用挂起快照）；命令审批驳回 → rejected 终态
- **超时路径**：`expire_waiting_approvals`（scheduler + 恢复时惰性检查）→ timeout 终态，node_state 保留挂起时状态
- **前端**：chatflow-edit.html 运行抽屉 `state.lastTrace = d.trace` + `applyRunState` 画布着色（trace 字段现成）；对话日志页 conversations.html 已按 chat_app_id 过滤（`GET /conversations?chat_app_id=`）
- 最新 migration **0033_api_keys_chat_app**；下一次从 **0034** 起

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 存储形态 | **flow_runs 加 `trace JSONB` 列**（复用现表，一行一 run，天然按 app/conversation 查）——不新表；终态时与 finish_run 同事务写入 |
| D2 | 写入时机 | **终态化时写完整 trace**（completed/failed/rejected 走 flow_chat 统一写入点）；**timeout** 由 node_state 转译（挂起时 completed 节点 → 同构 trace，保证超时也有轨迹）；waiting_human 挂起保留 node_state（恢复数据源），不写 trace |
| D3 | 多 attempt（挂起→恢复） | **trace 以最终一次执行为准**（attempts 字段已有；不按 attempt 分段）——保持 trace 结构与前端渲染现成兼容 |
| D4 | 查询端点 | `GET /chat_apps/{chat_app_id}/runs`（应用维度，分页）+ `GET /conversations/{conv_id}/runs`（会话维度，对话日志页展开）——**权限沿用 conversations 可见性过滤**（C 系列：非 admin 按 chat_app access_mode/角色白名单，防缝隙） |
| D5 | 审计 | **不加新事件**——run 生命周期已有 earp.execution.* / earp.api.*（对外调用）；trace 落库本身即审计载体 |
| D6 | 前端入口 | 一期：**对话日志页（conversations.html）会话详情展开「运行历史」**（列表：时间/状态/耗时/attempts + 选中展开 trace 只读表格）；chatflow 列表页入口按需（二期） |
| D7 | 边界 | 一期**不做**：单节点重放（那是 #16）、历史 diff/耗时图表、TTL 清理（与 conversations 同生命周期）、前端画布重放着色（历史页只读表格） |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — migration 0034 flow_runs.trace 列 + service 扩展（0.5 天）
**文件**：`migrations/versions/0034_flow_runs_trace.py`（新）、`src/earp_server/conversation/flow_runs.py`
- `flow_runs` 增 `trace JSONB NOT NULL DEFAULT '{}'`（存量行默认空对象，无需 backfill）
- service：`finish_run` 增加 `trace` 参数（同事务写入）；新增 `list_runs(tenant, chat_app_id, limit, offset)`、`get_conversation_runs(tenant, conversation_id)`
- 验证：迁移幂等/降级 + 单测（终态带 trace 落库/查询分页）

### Task 2 — flow_chat 终态落 trace（0.5 天）
**文件**：`src/earp_server/conversation/chat_service.py`
- 终态分支（completed/failed/rejected）：构造 trace 后传给 `finish_run(trace=...)`——**与返回响应同点，内部 JWT 与对外 API 自动共享**
- timeout 路径（`expire_waiting_approvals` + 惰性检查）：由 node_state 转译同构 trace 写入
- 验证：终态后 `SELECT trace FROM flow_runs` 非空且与响应 trace 一致；waiting_human 挂起不写 trace

### Task 3 — 查询端点（0.5 天）
**文件**：`src/earp_server/main.py`、`src/earp_server/conversation/flow_runs.py`
- `GET /chat_apps/{chat_app_id}/runs?limit&offset`：应用维度（404 应用不存在；权限同 conversations 可见性）
- `GET /conversations/{conv_id}/runs`：会话维度（404 会话不存在/不可见）
- OpenAPI 同步（export_openapi）
- 验证：分页/空结果/越权 403/404；`test_openapi_export` 基线

### Task 4 — 前端运行历史（0.5-1 天）
**文件**：`apps/earp-admin/pages/conversations.html`、`apps/earp-admin/js/conversations.js`（如为内联则扩展内联）
- 会话详情区加「运行历史」：列表（时间/状态/耗时/attempts）+ 选中展开 trace 只读表格（node/status/branch/input/output/error/error_code/latency，样式复用 chatflow-edit 运行抽屉）
- 空态：该会话无 flow 运行 → 显示提示不报错
- 验证：前端冒烟（fake DOM 渲染列表/trace 展开）+ 手工：跑一个 flow → 对话日志可见完整轨迹

### Task 5 — 测试 + 回归 + 指南（0.5 天）
**文件**：`tests/test_flow_run_history.py`（新）、`arch/guides/earp-chatflow-guide.md`、`arch/guides/earp-fde-user-guide.md`
- pytest：终态 trace 落库（completed/failed/rejected/timeout）/ 恢复路径最终 trace / 查询权限（非 admin 越权）/ 挂起不写 trace
- 指南补：「运行历史」一节（对话日志查看流程轨迹、排查失败定位到节点、trace 字段含义）
- 验证：全量 pytest 绿 + verify_f6 80/0 + ruff/pyright 零新增

## 依赖关系

```
Task 1（migration+service）→ Task 2（写入）→ Task 3（查询端点）
Task 4（前端）依赖 1-3；Task 5（测试/指南）依赖 1-4
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`，合计 2.5-3.5 天

## 验收标准

1. flow 跑完（含挂起 202 → 恢复）→ 对话日志/运行历史可见完整 trace；**刷新页面后仍在**
2. failed / rejected / timeout 均有记录；timeout 有挂起时节点状态
3. `GET /chat_apps/{id}/runs` 与 `GET /conversations/{id}/runs` 权限与 conversations 可见性一致（非 admin 越权 403/404）
4. 内部 JWT 与对外 API（#18）调用产生的 run 都落 trace（共享写入点）
5. 全量 pytest 绿（526+新增）+ verify_f6 80/0 + ruff/pyright 零新增 + openapi 同步

## 风险提示

1. **trace 含敏感 input**（用户问题/LLM prompt/工具取数）——查询权限沿用 conversations 可见性过滤；管理端（admin）全量可见
2. **多 attempt 语义**：挂起→恢复的 trace 以最终执行为准（D3）；若未来要按 attempt 复盘需另加分段列
3. **超时路径 trace 来源**：node_state 只含挂起时 completed 节点——转译后缺失未执行节点属预期（标注 status 可区分）
4. **存量数据**：已终态的旧 run trace 为空 `{}`（无 backfill）——前端空态容错
5. **写入点唯一性**：所有终态必须经 finish_run（含超时扫描/惰性检查两处调用）——Task 2 统一覆盖，防漏写

---
**规划定稿，确认后开工。**
