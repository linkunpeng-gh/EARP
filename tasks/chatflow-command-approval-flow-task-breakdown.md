# 任务清单 — 命令审批流（Command Approval Flow）: 命令能力审批治理 + Saga 补偿细化

**状态：规划定稿，待开工**
**依据**：F6 评估报告 §10（D2：命令审批流 = 下一阶段立项依据）+ `arch/design/2026-08-18-chatflow-integration-design.md` 开放问题 2 + 能力中心 task（type=command 走审批）
**依赖**：F4 human_approval ✅（挂起/恢复/超时）+ 能力中心 ✅（execution 声明 + command 类型）+ MultiStep 补偿 ✅（M12 minimal）
**日期**：2026-08-24

## 目标

1. **命令能力审批门禁**：`type=command` 的能力调用（如 `create_maintenance_order` / `notify_owner` / `archive_complaint`）**强制走人工审批**——不只是 flow 里显式放了 human_approval 节点才审批，而是**能力层兜底**（任意入口调用 command 能力都过审批），治理"命令类操作不可无监管执行"
2. **Saga 补偿细化**（F6 明确「补偿未实现/未验证」）：`create_maintenance_order` 等命令的**补偿语义**——失败时反向撤销已做的命令副作用（开单→撤单/通知→撤回），并**真实 rollback 验证**
3. **审批流治理**：审批决策（批准/驳回）、审批人角色、超时、审批记录落审计——从 F4 的「单节点等待」升级为「可治理的命令审批」
4. 零回归：F0-F6 全绿；flow 内显式 human_approval 兼容（不破坏现有场景 A/B）

## 现状（已核实，2026-08-24）

- **MultiStep 补偿（M12 minimal）**：`SagaCompensation.register` + `rollback()`（LIFO）——flow 路径也注册了 `step.compensate_call`（`_compensate` → `Connector.execute(compensate_call)`），**但真实 rollback 效果未验证**（评估报告 §10 明确「多步失败回滚仅 legacy 路径有，flow 路径补偿注册存在但未验证」）
- **F4 human_approval**：flow 里显式放 human_approval 节点 → 挂起 202 / 恢复 / 超时（已交付）
- **能力中心**：`business_capabilities.type ∈ {query, command}`；execution 声明（adapter + params）已落库；`capability.call` 适配器已做「required_permissions 门禁 + 审计」
- **但**：目前**没有能力层审批**——command 能力在 flow 里不手动放 human_approval 节点就直接执行（能力中心 `type=command` 只是声明，没被强制执行）
- 场景 A 的 `create_maintenance_order` / `notify_owner` 是 command 型能力但走显式 human_approval——审批发生在 flow 层，非能力层
- 审计：`earp.capability.call.*`（started/completed/failed）已落库；审批决策无专门事件

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 审批在哪一层 | **能力层兜底 + flow 层显式兼容**：① `capability.call` 执行 `type=command` 能力时，若**未在 gate 内经过 human_approval** → 强制审批（复用 human_approval 挂起机制）或返回「需审批」；② flow 里显式放了 human_approval 已算「人工把关」，避免双审批。倾向：**能力层为兜底门禁**（command 能力默认不可无审批执行），flow 显式 human_approval 视为已把关（需要标记/判定机制） |
| D2 | 审批决策 | 批准→继续执行命令；驳回→流程终态 rejected（不执行下游）。决策来源：用户对话下一句（复用 F4 恢复语义）或独立审批端点 |
| D3 | 补偿语义 | 命令能力声明 `compensate_call`（execution 里加）→ 失败/Saga 回滚时调用；`create_maintenance_order` 补偿 = mock 撤单端点（生产 = 对应企业 API）；**真实 rollback 验证**（F6 缺口补上） |
| D4 | 审批记录/审计 | 新增 `earp.approval.*` 事件（requested/approved/rejected/timed_out），含 approver / decision / execution_id 入 audit_logs |
| D5 | 审批人角色 | 可配：应用级审单人（`approval_roles`）或复用 command 能力 required_permissions 的 holder；一期倾向命令能力的权限 holder 或指定角色 |
| D6 | 范围边界 | 审批流**不做**复杂多级审批/委托/表单动态生成（Phase F）；一期 = 单级人工批准/驳回 + 超时 + 审计；命令审批的"治理防线下沉"（tech-debt 规划）单列 |
| D7 | 测试策略 | 能力层强制审批单测 + flow 兼容 + Saga 真实回滚（含 flow 路径）+ 审计事件 + 端点集成 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — 能力层 command 审批门禁（1 天）
**文件**：`src/earp_server/connector.py`（capability.call）、`src/earp_server/orchestrator/types.py`
- `capability.call` 执行 `type=command` 且未过审批 gate → 触发审批（抛 ApprovalPending / 或 gate 标记检查）
- **gate 判定机制**：flow 里显式 human_approval 已把关 → 跳过能力层强制审批（识别：capability 节点上游已含 human_approval，或能力节点标记 `already_approved`）
- legacy/非 flow 入口调用 command 能力 → 一律需审批
- 验证：command 无审批拒绝 / command 有审批放行 / query 不受影响（零回归）

### Task 2 — Saga 补偿细化 + 真实 rollback（1-1.5 天）
**文件**：`src/earp_server/orchestrator/multi_step.py`、`scripts/f6_mock_server.py`（补撤单/撤通知端点）、`src/earp_server/connector.py`
- mock 加 `POST /_control/cancel-order` / `POST /_control/cancel-notify`（补偿端点）
- 能力 execution 声明 `compensate_call`（`{"adapter_type":"capability.call", ...}` 指向补偿能力/连接）
- **flow 路径真实回滚验证**：构造「开单成功→通知失败」→ 断言撤单被调用（mock 日志）→ flow status = rolled_back
- 验证：Saga reverse 顺序 + flow 路径 rollback 集成测试（补 F6 缺口）

### Task 3 — 审批决策流 + 端点（1 天）
**文件**：`src/earp_server/conversation/chat_service.py`、`src/earp_server/ontology/routes.py`、`src/earp_server/conversation/flow_runs.py`
- 批准/驳回语义：对话下一句「批准/驳回」或独立 `POST /chat_apps/{id}/approvals/{exec_id}` 决策端点
- 驳回 → flow 终态 rejected，下游不执行（复用 flow_runs 终态，加 rejected 状态）
- 审批超时：复用 `EARP_APPROVAL_TTL`
- 验证：批准 → 继续 / 驳回 → rejected / 超时 → timeout

### Task 4 — 审批审计事件（0.5 天）
**文件**：`src/earp_server/audit/`、`src/earp_server/...（审批触发处）`
- `earp.approval.requested / approved / rejected / timed_out` 事件，含 approver / decision / execution_id / capability_id
- audit_logs 落库 + 消费 handler 订阅 `earp.approval.*`
- 验证：审计单测 + 端点集成（审批后能查到 event）

### Task 5 — 兼容回归 + FDE 指南（0.5 天）
**文件**：`tests/`、`arch/guides/earp-chatflow-guide.md`、`arch/guides/earp-fde-user-guide.md`
- 场景 A/B 回归（flow 显式 human_approval 不双审批）
- FDE 指南补「命令能力需审批」说明 + 能力中心注册 command 时声明审批/补偿
- 验证：全量 pytest 绿 + ruff/pyright 零新增 + verify_f6 仍 78 绿

## 依赖关系

```
Task 1（命令审批门禁）→ 与 Task 3（审批决策流）相互依赖
Task 2（Saga 补偿）→ 相对独立，需 mock 补端点
Task 4（审计）→ 依赖 1/3 的审批触发点
Task 5（兼容回归）→ 最后
```

**建议执行序**：`1 → 3 → 4 → 2 → 5`（先审批门禁与决策流成闭环，再补 Saga，最后回归）

## 验收标准

1. command 能力任意入口（含 flow 不显式放 human_approval）不可无审批执行；flow 显式 human_approval 不双审批
2. 批准→继续 / 驳回→rejected / 超时→timeout，决策影响下游执行
3. Saga 真实回滚：开单→通知失败 → 撤单被调用（mock 日志断言），flow status=rolled_back —— **F6「补偿未验证」缺口闭合**
4. `earp.approval.*` 审计事件齐全
5. 场景 A/B 零回归；全量 pytest 绿 + ruff/pyright 零新增 + verify_f6 78 绿

## 风险提示

1. **双审批风险**：flow 显式 human_approval + 能力层强制审批叠加 → 用户被问两次。gate 判定机制要稳（D1）
2. **补偿的真实性**：mock 撤单只验证机制；生产补偿需企业真实 API（execution 声明切换点，FDE 指南注明）
3. **legacy 影响面**：capability.call 被 invoke/query 后台也复用——能力层强制审批要避免误伤 query 能力与后台自动任务（command 才审）
4. **驳回状态机**：flow_runs 加 rejected 状态需同步 CHECK 约束 / 前端状态识别 / F4 测试

---
**规划定稿，确认后开工。**
