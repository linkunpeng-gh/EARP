# EARP 业务流程说明

## 场景化运行流程

**定位：L1 — 业务流程层。本文通过具体业务场景演示各模块的协作流程，帮助理解 EARP 的整体运行机制。**
**覆盖模块：Runtime / Planner / Decision Engine / Capability Center / Knowledge Center / Execution / Policy / Audit / EventBus / Coordination**

---

# 一、整体运行流程

一个 EARP 业务请求从触发到完成的完整生命周期：

```
用户 / 系统 / 定时器 / 事件
    │
    ▼
① 触发 — Coordination Runtime（Scheduler / Webhook / API）
   接收请求 → 创建 Request + Session → 交给 Planner
    │
    ▼
② 理解 — Reasoning Runtime（Planner）
   Intent Parsing → Knowledge Center(Business Dict) → Goal → Domain Routing
    │
    ▼
③ 发现 — Planner → Capability Center（Resolution Engine）
   Semantic Match + Graph Traversal + Policy Filtering
    │
    ▼
④ 规划 — Task Planner
   Plan Generation（DAG）+ Plan Validation（调用 Policy Center）
    │
    ▼
⑤ 决策 — Execution Runtime（Decision Engine）
   读取执行状态 → 分支选择（Rule / LLM / ML）
    │
    ▼
⑥ 执行 — Execution Runtime（Executor）
   Task → Step → Capability → Service → Connector
   Business Transaction + Compensation（失败回滚）
    │
    ▼
⑦ 反馈 — EventBus → Audit → Observation → Feedback → Evaluation → Learning
   · Memory（执行经验记录）
   · Knowledge Center（更新权重）
   · Planner（下次更聪明）
    │
    ▼
⑧ 结果 — Runtime Result → 返回给调用方
```

---

# 二、场景一：Chat — "查询昨天产线异常"

**特点：单轮对话、只读查询、快速响应。**

```
用户输入："查询昨天所有产线异常"
    │
    ▼
① Runtime 创建 Request + Session（Context）
    │
    ▼
② Intent Planner（调用 Business Dictionary）：
   "异常" → "Alarm"（设备上下文）
   Domain：Equipment
    │
    ▼
③ Goal Generation → Domain Routing（Equipment Domain）
   Resolution Engine：query_equipment_alarm（匹配度 96%）
    │
    ▼
④ Task Planner → Plan（单步 Task）
   Plan Validation → Valid（Schema / 权限 / 领域一致）
    │
    ▼
⑤ Execution Runtime：
   └── Step: capability_call(query_equipment_alarm)
       · Policy Check（rate_limit）：通过
       · Service：AlarmService
       · Connector：MES Connector
       · MES 返回数据 → 加工 → Step Succeeded
    │
    ▼
⑥ Runtime Result 返回（耗时 2.3s）
   并行：EventBus → Audit 记录 / Observation 采集 / Feedback 收集
```

**涉及模块**：Runtime → Planner → Knowledge Center → Capability Center → Policy Center → Execution → Connector → EventBus → Audit → Observation

---

# 三、场景二：实时流 Workflow — "设备故障自动处理"

**特点：预定义流程、多步骤、审批、补偿。**

```
设备 MQTT 消息："A-102 温度超限，critical 报警"
    │
    ▼
① Scheduler 匹配 Trigger → 查找 Workflow → 编译为 Plan（DAG，6 个 Task）
    │
    ▼
② Plan Validation → Valid
    │
    ▼
③ Execution Runtime：
   │
   ├── Task1(query_equipment_status) → MES → Succeeded
   ├── Task2(query_equipment_alarm) → MES → Succeeded
   │
   ├── Task3(decision) → Decision Engine
   │   Rule: IF critical AND running THEN emergency_stop
   │   → 选择分支: emergency_stop
   │
   ├── Task4(human_approval)
   │   → 企业微信通知主管 → Waiting（等待 3 小时 20 分钟）
   │   → 主管审批通过 → Resume
   │
   ├── Task5(create_work_order) — Command
   │   · Business Transaction 开始
   │   · MES Connector → 创建工单成功
   │   · 注册补偿: void_work_order
   │
   └── Task6(notification) → 企微通知维修团队
    │
    ▼
④ Execution Completed
   → Audit 记录完整链（6 个 Step、3 次 Capability 调用、1 次审批）
   → Feedback → Evaluation → Memory（报警到修复间隔 3.5h 存入记忆）
```

**涉及模块**：Scheduler → Workflow Compiler → Runtime → Planner → Execution(Decision/Approval/Transaction/Checkpoint) → Connector(MES/IM) → Policy → EventBus → Audit → Feedback → Memory

---

# 四、场景三：Agent — "生成产线日报"

**特点：多轮推理、动态调用、反思重规划。**

```
用户请求："生成昨天产线的日报"
    │
    ▼
① Agent Session 创建（planning 模式，max_iterations=15）
    │
    ▼
② Agent 调用 Planner：
   → Goal + Constraints（跨域：production + equipment + quality）
   → Resolution Engine 分别检索三个 Domain
   → Plan（4 个 Task：query_production_data / query_equipment_alarm / query_quality_data / generate_report）
    │
    ▼
③ Execution 执行 Plan → 全部 Succeeded
    │
    ▼
④ Agent Reflection：
   "报告已完成，但报警部分缺少分析"
   → Decision：需要深挖
   → RePlan：新增 query_alarm_analysis
    │
    ▼
⑤ Execution 执行新增 Task → Succeeded
    │
    ▼
⑥ Agent 再次反思："目标已达成" → Agent Completed
    │
    ▼
⑦ 闭环：
   → 报告 Markdown → Artifact Center
   → Feedback → Evaluation → Learning（组合路径存入 Long Memory）
   → "日报"下次可直接按此路径执行
```

**涉及模块**：Coordination → Agent → Planner → Resolution Engine → Execution → Agent Reflection → RePlan → Artifact → Feedback → Memory

---

# 五、场景四：定时调度 — "每日 8 点分析良率"

**特点：定时触发、自动执行、无人工干预。**

```
CronTrigger "0 8 * * 1-5" 触发
    │
    ▼
Scheduler → RuntimeRequest → Planner → Execution → 结果自动分发
```

流程同场景一，但：
- Domain：quality
- 不需要返回用户，结果直接 → Artifact Center + Dashboard 更新
- 如果良率 < 95% → 自动触发告警 Workflow

---

# 六、场景五：事务补偿 — "采购单创建失败回滚"

**特点：Command 跨多系统、失败需 Saga 补偿。**

```
用户："为库存低于安全库存的物料创建采购单"
    │
    ▼
Plan（4 个 Task）→ Validation → Execution

Business Transaction 开始（Saga）
    │
    ├── Task1(query_inventory) — Query → Succeeded（3 种物料不足）
    │
    ├── Task2(create_purchase_order) — Command
    │   → Policy → ERP Connector → 采购单 PO-001 创建 → Succeeded
    │   → 注册补偿：void_purchase_order(PO-001)
    │
    ├── Task3(lock_inventory) — Command
    │   → 库存锁定 100 件 → Succeeded
    │   → 注册补偿：unlock_inventory(100)
    │
    └── Task4(notify_buyer) — Command → 企微服务异常 ❌
        → Retry ×3 → 全部失败
        → 事务进入 Compensating
        · 逆序补偿：unlock_inventory(100) → Succeeded
        · 逆序补偿：void_purchase_order(PO-001) → Succeeded
        → Compensated
        → 标记人工介入 → 通知管理员
```

**涉及模块**：Planner → Execution → Transaction → Compensation → Connector(ERP/IM) → Audit → Notification

---

# 七、模块覆盖矩阵

| 场景 | Runtime | Planner | Decision | Know. | Cap. | Execution | Policy | Audit | EventBus | Coord. | Connector | Artifact | Memory |
|:----:|:-------:|:-------:|:--------:|:----:|:----:|:---------:|:-----:|:----:|:--------:|:------:|:---------:|:--------:|:------:|
| Chat | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | — | — |
| Workflow | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Agent | ✅ | ✅ | — | — | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Schedule | ✅ | ✅ | — | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Transaction | ✅ | ✅ | — | — | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | — | — |

五种场景覆盖全部 14 个模块。
