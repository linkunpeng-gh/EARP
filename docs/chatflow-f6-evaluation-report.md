# Chatflow F6 — flow 模式端到端评估报告（示例 A/B + 会话上下文摸底）

**日期**：2026-08-24
**状态**：✅ 完成（验收项全过）
**依据**：`tasks/chatflow-f6-evaluation-task-breakdown.md`（D1-D5 既定决策）+ `arch/design/2026-08-18-chatflow-integration-design.md` §5/§7
**环境**：dev 8000 API（--reload）+ 本地 mock 8001（`scripts/f6_mock_server.py`）+ Ollama 11434（qwen2.5:1.5b / bge-m3）；dev DB 0028；tenant-demo

## 0. 一句话结论

**flow 模式端到端可用**：场景 A（设备维修单）/ B（客户投诉分流）两条真实业务线 dev 真 API 全路径跑通
（`scripts/verify_f6.py` 78 项断言全绿）；会话上下文摸底结论 **D3-(b) 差一点 → 已补最小实现**（指代消解
在 flow 内生效）；评估过程发现并修复 4 个真实缺陷（含 1 个 resume 500），另产出分级问题清单 9 项。

## 1. 范围与方法（D5：dev 真 API 脚本化冒烟为主）

- 场景素材 = 本地 REST mock（设备状态/开单/通知/投诉归档 4 端点）+ 知识库投诉样例文档 + 能力中心注册 4 个 REST 能力（D1）
- 场景 A/B 全路径：`scripts/verify_f6.py` 断言关键路径（挂起 202 → 恢复 → 完成 / 分支走向 / 副作用 / 审计 / 无残留）
- 摸底：两轮指代专用 qu-only 应用（免 human_approval 干扰）
- pytest 只补修复用例：`tests/test_flow_f6_fixes.py`（9 用例）

## 2. 维度①：正确性矩阵

| 环节 | 用例 | 结果 | 说明 |
|:---|:---|:---|:---|
| QU 理解 | 「CNC-01 温度异常」→ 实体提取 | ✅ | 规则层提取 CNC-01 设备/指标实体（mention 含实体名）；use_llm=false 纯规则 40-60ms |
| 实体传参 | QU 实体 → 能力节点 | ✅ | `{{#qu1.entities.0.mention#}}` 首实体引用（F6 修复项 2/3）→ mock 按编码子串解析到 CNC-01 |
| 分支走向 | 故障→then / 正常→else | ✅ | `c1.output.rows.0.status == "faulty"` 条件（F6 修复项 1）；未命中分支 skip（trace 可见） |
| 审批挂起 | 202 + waiting_human + pending_node_id=h1 | ✅ | 开单先于挂起完成、通知严格在审批后（mock 日志断言） |
| 审批恢复 | 第二轮同会话消息 → completed | ✅ | 恢复复用 exec_id，pool 快照重放；答复注入 `{{#h1.output.reply#}}` |
| 输出质量 | 正常路径 LLM 答复 | ✅ | qwen2.5:1.5b 生成「设备正常」语义答复（1.3-2.1s） |
| 场景 B 分支 | VIP→then / 普通→else | ✅ | `chunks.0.metadata.vip == true`；归档记录 vip 标志正确（张伟 true / 李明 false） |
| 场景 B 话术 | VIP 专属（24h 专人）/ 普通（3 工作日） | ✅ | 提示词语义命中（qwen 会改写措辞，按语义断言） |
| 归档副作用 | 投诉记录落 mock | ✅ | customer/vip/category 正确透传 |

**正确性结论**：确定性骨架（分支/审批/副作用）100% 正确；LLM 生成部分语义正确、措辞有模型方差（断言按语义不按字面）。

## 3. 维度②：耗时（QU 缓存前后 / 节点级）

表 1 — 场景链路总耗时（dev 本机，qwen2.5:1.5b）

| 链路 | 总耗时 | 节点明细（ms） |
|:---|:---|:---|
| 场景 A 故障：QU→状态→开单→**挂起** | **108ms** | qu1~40 / c1~8 / c2~9 |
| 场景 A 恢复：通知→完成 | **36ms** | c3~7 |
| 场景 A 正常：QU→状态→LLM 答复 | **1.39s** | qu1=43 / c1=8 / **l1(LLM)=1256** |
| 场景 B VIP：检索→归档→话术 | **3.6-4.1s** | k1=17 / c1(归档)=21 / **l1(LLM)=3103** |
| 场景 B 普通：同上 | **1.9-2.9s** | k1=16 / c2(归档)=26 / **l2(LLM)=1794** |

表 2 — QU 节点：规则 vs LLM 升级（缓存前后）

| QU 模式 | 首次 | 再次（同 query） | 说明 |
|:---|:---|:---|:---|
| use_llm=false（纯规则） | 63ms | — | 无 LLM 调用，确定性 |
| use_llm=true（LLM 升级） | **8292ms（冷）/ 62-70ms（热）** | 68-70ms | 见下 |

**关键发现（缓存）**：QU LLM 升级走 `json_complete`（`understanding.upgrade_with_llm`）——**该路径未接应用层
LLM 缓存**（代码核实：`json_complete`/`complete`/`chat_stream` 均不查 `_cache`，仅 `plan()` 接缓存）；
观察到的「第一次 8.3s → 第二次 68ms」是 **Ollama 模型冷/热加载差异**，不是应用缓存。1.5B 模型本地
短 JSON 生成 ~70ms，但冷启动 ~8s；规则路径稳定 ~60ms。

**耗时结论**：确定性节点（qu 规则/能力/tool/条件）合计 <150ms，LLM 节点占总耗时 >90%；
QU 升级路径建议补缓存或规则优先（问题清单 #4）。

## 4. 维度③：失败恢复

| 用例 | 预期 | 实测 | 结论 |
|:---|:---|:---|:---|
| 节点失败（未知设备 → mock 404） | 流程失败、无副作用 | ✅ status=failed（200），c2/c3 未执行，**无开单副作用**，flow_runs 终态 failed，108ms | StepRunner 捕获 ConnectorFetchError → failed 结果 → 执行器立即终态 |
| 挂起超时（updated_at 回拨 2h） | 惰性超时终态 + 提示 | ✅ 「⏰ 等待超时，流程终止」消息 + 旧 run timeout + 新 run 正常重启挂起 | flow_chat 恢复入口惰性检查（D4） |
| 超时后恢复流 | 无残留 waiting | ✅ 全量 flow_runs 终态（超时测试自清理恢复） | 脚本断言 waiting 残留 = 0 |
| worker 重启 | — | ⚠️ **N/A**：flow 执行在 API 进程内联（非 Procrastinate worker） | 跨进程 checkpoint 恢复属 Phase F 范围（开放问题 3），记缺口 |

**失败恢复结论**：节点失败 → 干净终态 + 无副作用（好）；挂起超时 → 惰性终态（好）；
「worker 重启」维度不适用（flow 非 worker 执行）——记录为架构缺口（低优先级）。

## 5. 维度④：权限审计

- **权限门禁**：4 个能力均声明 required_permissions；角色 r1 合并权限后放行；能力中心注册校验（execution 白名单/格式）通过
- **audit_logs 落库**（dev in-process EventBus → audit handler）：`earp.capability.call.{started,completed,failed}` 事件
  ≥20 条窗口可见；单次执行（3 能力调用）产生 **6 条**（started+completed 各 3）；detail 含
  execution_id/session_id/user_id/role_id/entity_id/latency_ms/error
- **失败也审计**：失败探测产生 `earp.capability.call.failed`（error 字段入 detail）——审计闭环完整
- 权限拒绝路径：Connector 内 required_permissions 双保险 + PolicyLayer（F3 已测，回归绿）

**权限审计结论**：capability 调用全量审计、权限门禁双保险，满足验收。

## 6. D3 会话上下文摸底（指代消解）

**方法**：专用 qu-only 应用两轮对话「CNC-01 温度异常」→「它刚才还报警了」，观察第二轮 qu entities。

| 状态 | 第二轮 qu entities | 结论 |
|:---|:---|:---|
| **修复前**（摸底实测） | `[]` | 指代断链——`_extract_entities` 的 coref 需要 `context.last_entities`，而 qu.answer 传 `context={}` |
| **修复后**（最小实现） | `[{'mention': 'CNC-01 数控机床', 'semantic_type': 'equipment'}]` | 「它」→ CNC-01 解析成功 |

**D3 判定：(b) 差一点 → 已补最小实现（当天量级）**。最小实现 = `connector._history_context`：
qu.answer 从会话历史（`_recent_pairs`）取上一轮用户消息做规则层理解，把其实体作为 `last_entities`
注入本轮 understand/execute_plan（≈20 行，无迁移）。全量方案（`conversations.context` 落库 +
last_intent/last_relations + kb_scope 写路径 + 可见范围）见 `arch/design/2026-08-18-chat-session-context-design.md`
C1-C6——**另立任务书**（后续立项依据）。

> 摸底细节：历史推导取「最近 user 消息」；若上一轮是审批恢复（「确认」），指代源为空——摸底用
> qu-only 应用规避（真实场景的审批+追问组合留给 C 系列）。

## 7. 评估发现并已修复（最小修复，均有回归测试）

| # | 缺陷 | 影响 | 修复 | 测试 |
|:--|:---|:---|:---|:---|
| 1 | 条件求值不支持列表索引（`_resolve` 仅 dict 路径） | 场景 A `rows.0.status` / 场景 B `chunks.0.metadata.vip` 分支无法表达 | `workflow_dsl._resolve` 支持数字下标 | `test_flow_f6_fixes::TestListIndexPaths` |
| 2 | 模板解析不支持列表索引 | capability 节点无法取 QU 首实体 `{{#qu1.entities.0.mention#}}` | `resolve_templates` 支持数字下标 | 同上 |
| 3 | qu.answer 不输出实体、不接会话上下文 | 指代消解断链 + 能力节点无设备引用 | `_execute_qu_answer` 输出 `entities` + `_history_context` | `TestQuAnswerF6` |
| 4 | **resume 重放时 else 分支 skipped 节点重写同名 checkpoint 命名空间 → `checkpoint_blobs` 唯一键冲突 500**（场景 A 拓扑即触发） | 审批恢复直接 500 | `checkpoint.write` blob 插入 upsert 化 | `TestCheckpointResumeIdempotent` |

> 修复 4 是最严重的：**评估直接踩到**（挂起→恢复第二句必现 500）。触发条件 = 拓扑序上 else 分支
> 节点先于 human_approval 被处理（场景 A 布局正好如此）；F4 冒烟流没触发（其 else 节点在挂起点之后）。

## 8. 问题清单（分级）

### 高（建议下一批任务书排入）
1. **QU 升级路径无 LLM 缓存**（表 2）：同 query 重复全量 LLM 调用；冷启动 8s。→ 给 `upgrade_with_llm`
   接 LLMConnector 缓存或「规则命中优先/缓存键含 query+missing」
2. **flow 节点失败语义与错误归一**：失败返回 `200 + status=failed`（合理但前端需区分）；`ConnectorFetchError`
   未归一到 `ConnectorError`（chat_ep 422 捕获名单不含它——当前靠 StepRunner 兜底免 500，但语义不统一）
3. **「答案 = 最后一个节点输出」**：场景 B 若把归档（副作用）节点放最后，答复会被 JSON 覆盖（已用
   「LLM 放最后」规避并在指南提示）；长期加「指定答案节点」

### 中（backlog）
4. **resume trace 的 latency_ms 归零**：pool 反序列化的 StepResult 无 latency（trace 显示 0）——评估耗时
   需从首轮/DB 侧取数；建议 flow_runs 存节点级耗时快照
5. **超时后「确认」消息语义**：超时后用户仍发「确认」会被当作新流程查询（无实体→失败）；UX 可加
   「流程已超时，请重新描述问题」引导
6. **QU entities 首项可能是指标实体**（OEE）而非设备（实体提取排序）——mock 按编码子串兜底；
   QU Phase B 实体识别增强时收敛（mention 取 business_code 优先）

### 低
7. **flow 执行在 API 进程内联**（非 worker）：worker 重启恢复维度 N/A；跨进程 checkpoint 恢复留 Phase F
8. **mock 是演示素材**：生产接真实系统（FDE 指南已注明；能力 execution 声明即切换点）
9. **摸底仅覆盖 qu.answer 路径**：chat_sse auto 模式指代消解未接入（C 系列范围）
10. **既有：openapi 导出失败（AC-08 门禁破）**：copilot 提交（f0a2d1a）把 `CopilotAssistRequest` 定义为 create_app 内的本地模型 → pydantic v2 ForwardRef 生成 schema 报 `PydanticUserError`，`test_openapi_export` 3 用例全挂（HEAD 上同样失败，非 F6 引入；与并行 copilot 工作流同源，建议由该工作流修——类移出函数作用域或加 `model_rebuild()`）

## 9. 验收对照

| 验收项 | 状态 |
|:---|:---|
| 场景 A 两路径（故障→开单→审批→通知 / 正常→LLM 答复）dev 真 API 全通 | ✅ `verify_f6.py` 全绿（78/78） |
| 场景 B 两分支（VIP/普通）全通 | ✅ |
| 会话上下文摸底明确结论 | ✅ (b) 档已补最小实现 + 缺口清单（C 系列任务书） |
| 评估报告四维度 + 问题清单分级 | ✅ 本文档 |
| FDE 指南可照着搭出场景 A/B | ✅ `arch/guides/earp-chatflow-guide.md` §7.5/§7.6 |
| 全量 pytest 绿 + ruff/pyright 零新增 + OpenAPI 无变化 | ✅ 431 passed / 3 failed（**3 个全为既有 openapi 导出失败**——copilot 提交引入的本地模型 ForwardRef 问题，HEAD 上同样失败，非 F6 新增，见 §8 问题清单 #10）；ruff/pyright 改动文件零新增（仅既有 ASYNC109/reportUnnecessaryComparison）；OpenAPI 契约无变化 |

## 10. 遗留与后续

- **命令审批流任务书**（Saga 补偿细化、create_maintenance_order 补偿语义、审批流治理）——D2 已定，
  本评估未实现/未验证补偿（多步失败回滚仅 legacy 路径有，flow 路径 compensation 注册存在但未验证
  真实 rollback 效果——列为下一阶段立项依据）
- **会话上下文 C 系列任务书**（C1-C6 全量落库）
- **问题清单高优 1-3** 排期

---
**评估完成（2026-08-24）。**
