# 任务清单 — Chatflow F6: flow 模式端到端评估（示例 A/B + 会话上下文摸底）

**状态：✅ 已完成（2026-08-24）**——验收项全过；产出见 `docs/chatflow-f6-evaluation-report.md`
**依据**：`arch/design/2026-08-18-chatflow-integration-design.md` §5（示例 A/B 场景）/ §7（F6：flow 模式端到端验证 + 会话上下文联动）
**依赖**：F0-F5 ✅（workflow 真实化 → flow_schema → 执行器 → qu/capability/tool 节点 → human_approval → 画布编辑器）+ 能力中心 ✅（#7/#14，Capability 真实执行前置）
**日期**：2026-08-24

## 目标

1. **端到端验证**：示例 A（设备维修单）/ 示例 B（客户投诉分流）两条真实业务线，在 dev 环境完整跑通——「每个零件都能转」→「整台机器能干活」的验收
2. **会话上下文摸底**：flow 对话里的指代消解（「它刚才报警了」的「它」= CNC-01）现状如何——能则验证，不能则记缺口（不膨胀为功能开发）
3. **产出评估报告**：各环节正确性 / 耗时 / 失败恢复 / 权限审计四维度结论 + 问题清单——作为下一批优化的输入
4. **FDE 实操指南**：FDE 指南补「搭 Chatflow 场景」手把手教程（照着能搭出场景 A/B）

## 现状（已核实，2026-08-24）

- F3/F4 已实施：qu 节点（含 LLM 升级开关 + 模板 + 缓存）、capability 节点（权限+审计）、tool 节点（M3 data_adapter）、human_approval（ApprovalPending + flow_runs 挂起/恢复/超时）
- **能力中心已完成**（migration 0028 复合主键 + execution 声明 + 通用能力执行器分派）——F6 场景 A 的 `query_equipment_status / create_maintenance_order / notify_owner` 需要注册为真实能力（能力中心 UI 或 seed）
- F5b 画布 + 调试工作台完成（节点步进调试可用）
- **会话上下文 C 系列未落地**（planning/chat_service 无 context 落库）；`execute_plan` 有 `context` 参数、`_recent_pairs` 历史配对即时构建——指代消解现状未摸底
- dev 环境：8000 API（--reload）运行中；worker 需带 Ollama env；dev DB 到 0028
- 基线：全量 pytest 绿（能力中心/copilot 后基线，开工时以实际为准）

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 场景素材 | **本地 REST mock 服务**（设备状态查询/开单/通知三个 mock 端点，`scripts/f6_mock_server.py` 起 8001 端口）——注册为 REST 能力走能力中心；投诉历史用知识库素材（KB 导入投诉样例文档）；不依赖任何真实外部系统 |
| D2 | 场景 A 的 Saga 补偿 | **验证现状 + 标记缺口**：F6 是评估，create_maintenance_order 的补偿语义细化（命令审批流）属后续任务书；评估报告记录「补偿未验证/未实现」状态 |
| D3 | 会话上下文 | **摸底优先**：F6 先跑「两轮对话指代」用例，看 `_recent_pairs`/QU context 现状到哪一步；结论分三档——(a) 已能用 → 直接验证入报告 (b) 差一点 → 补最小实现（当天量级）(c) 差得远 → 记缺口 + 列后续任务书（会话上下文 C 系列）。**不预先决定做多少** |
| D4 | 评估维度 | ① 正确性：QU 理解（CNC-01 → 设备实体）/ 分支走向 / 审批挂起-恢复 / 输出质量 ② 耗时：QU 节点（缓存后）、LLM 生成、全链总时长 ③ 失败恢复：节点失败 / 挂起超时 / worker 重启 ④ 权限审计：capability 权限门禁 + audit_logs 事件落库 |
| D5 | 测试策略 | **评估以 dev 真 API 脚本化冒烟为主**（`scripts/verify_f6.py` 断言场景 A/B 关键路径）；pytest 只补摸底/修复引入的用例——F6 是评估不是功能开发，不为测试而测试 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — 场景准备：mock 服务 + 能力注册 + 素材（1 天） ✅
**文件**：`scripts/f6_mock_server.py`（新）、能力中心 UI / seed 脚本、`scripts/verify_f6.py`（骨架）
- mock 服务：`GET /equipment/{id}/status`（返回 fault/ok + 温度值）、`POST /maintenance-orders`（开单，返回单号）、`POST /notify`（通知，返回 ack）——三个端点供 REST 能力指向
- 能力中心注册 3 个 REST 能力（execution 声明=rest）+ 权限/审计门禁验证前置
- 知识库素材：投诉历史样例文档（含 VIP 客户样本）导入 KB
- 画布搭场景 A/B 图（F5b 编辑器），保存 flow_schema
- 验证：mock 服务 curl 通、能力注册可见、flow 图保存成功

### Task 2 — 场景 A 端到端（1 天） ✅
**文件**：`scripts/verify_f6.py`、dev 真 API
- 跑通：`POST /chat_apps/{id}/chat`（orchestration=flow）→ QU 理解「CNC-01 温度异常」→ 状态查询（mock）→ 分支（faulty）→ 开维修单（mock）→ **human_approval 挂起（202）** → 第二轮消息恢复 → 通知（mock）→ 完成
- 另跑反例：设备正常 → 分支走 no → LLM 生成「设备正常」答复
- 记录四维度数据（正确性/耗时/失败恢复/权限审计）——脚本断言关键路径 + 手工记录评估表
- 验证：两条路径全通；audit_logs 有 capability 事件；挂起-恢复无残留 flow_runs

### Task 3 — 场景 B 端到端 + 会话上下文摸底（1 天） ✅
**文件**：`scripts/verify_f6.py`、`arch/session-record.md`、评估报告
- 场景 B：`start → knowledge(查历史投诉) → condition(VIP?) → 分支话术 → 归档`——VIP 与普通各跑一遍
- **指代摸底**：两轮对话「CNC-01 温度异常」→「它刚才还报警了」——按 D3 三档判定并落地（验证/最小实现/缺口清单）
- 验证：场景 B 两分支通；摸底结论记录 + 决策（是否引出新任务书）

### Task 4 — 评估报告 + 问题清单（0.5 天） ✅
**文件**：`docs/chatflow-f6-evaluation-report.md`（新，或并入 session-record）
- 四维度结论汇总：各环节正确性矩阵、耗时表（QU 缓存前后）、失败恢复用例结果、权限审计抽查
- 问题清单分级（高/中/低）——高优先级问题即时修复，中低进 backlog

### Task 5 — FDE 指南 + 收尾（0.5 天） ✅
**文件**：`docs/fde-guide.md`（或对应指南文件）、`tasks/chatflow-f6-evaluation-task-breakdown.md`（标 ✅）、`arch/session-record.md`
- FDE 指南补「搭 Chatflow 场景」实操：注册能力 → 建 flow → 调试 → 发布 → 对话验证（对齐 §15.6 能力中心教程风格）
- 全量 pytest + ruff/pyright + OpenAPI 基线（新增 mock 脚本不入服务，应无变化）
- 任务书状态更新 + session-record 补记

## 依赖关系

```
Task 1（场景准备）→ Task 2（场景 A）→ Task 3（场景 B + 摸底）→ Task 4（报告）→ Task 5（收尾）
Task 3 的摸底结论可能引出一个「最小实现」子任务（视 D3 判定）
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`，合计 4 天

## 验收标准

1. 场景 A 两条路径（故障→开单→审批→通知 / 正常→LLM 答复）dev 真 API 全通
2. 场景 B 两分支（VIP / 普通）全通
3. 会话上下文摸底有明确结论（已能用 / 已补最小 / 缺口清单+后续任务书）
4. 评估报告产出：四维度 + 问题清单（分级）
5. FDE 指南可照着搭出场景 A/B
6. 全量 pytest 绿 + ruff/pyright 零新增 + OpenAPI 无变化

## 风险提示

1. **小模型理解力**：qwen2.5:1.5b 解析「CNC-01 温度异常」可能不准——QU 节点先关 LLM 升级（use_llm=false 规则理解）跑通骨架，再开升级对比；评估报告如实记录两档差异
2. **mock 服务依赖**：mock 是评估素材不是产品功能——FDE 指南注明「演示用 mock，生产接真实系统」
3. **摸底变功能开发的边界**：D3 的三档判定要硬——(b) 档最小实现以「当天量级」为上限，超了就落 (c) 记缺口（防 F6 膨胀）
4. **human_approval 真 API 验证**：挂起 202 → 第二轮恢复需要脚本化两步调用（非单请求）——verify_f6 里串两个 HTTP 调用并断言中间态
5. **Saga 补偿缺口**：评估报告明确「补偿未实现/未验证」状态——不要含糊带过（这是下一阶段（命令审批流）的立项依据）

---
**规划定稿，确认后开工。**
