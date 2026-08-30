# EARP 企业认知模型中心（ECMC）设计讨论与评审 — 配套说明

- 日期: 2026-08-29
- 性质: 设计配套说明（记录设计讨论的由来、演进与决策依据，供阅读正式设计文档时对照）
- 来源: ChatGPT 分享对话《业务因果模型设计》https://chatgpt.com/share/6a92439c-8e60-83e8-8456-9b1ca87c61c7
- 说明: 本文档不是独立的设计规范，而是设计与评审讨论的**配套说明文件**。正式规范以 `arch/design/` 下的设计文档与 `arch/L2/` 下的规范为准，本文回答"这些设计为什么长这样"。
- 术语: 与 ECMC 设计文档保持一致——ECMC = Enterprise Cognitive Model Center（企业认知模型中心，原 BMC）；KB = Knowledge Center；FDE = Field Domain Engineer（现场领域工程师）；Blueprint = Planning Blueprint；Plan = 执行计划实例。

---

# 1. 本文档与正式设计文档的关系

```
2026-08-29-ecmc-design-discussion-companion.md   ← 本文：讨论与决策由来（配套说明）
        │
        ├── 2026-08-28-enterprise-cognitive-model-center-design.md   （ECMC，L2 前置设计 v0.21）
        ├── 2026-08-28-planning-blueprint-l3-design.md               （Planning Blueprint L3 v0.3）
        ├── 2026-08-28-planner-runtime-l3-design.md                  （Planner Runtime L3 v0.2）
        └── 2026-08-28-causal-reasoning-engine-l3-design.md          （Causal Reasoning Engine L3）
```

阅读建议：

- 想**快速理解概念**：读本文 §3（一遍读懂）+ §4（分层模型）。
- 想**知道为什么这么设计**：读本文 §5（关键架构决策记录）。
- 想**评审/继续迭代**：读本文 §6（评审结论与遗留问题）+ 正式设计文档。
- 想**核对某次改动是否被采纳**：查本文附录 B（讨论轮次摘要表）。

---

# 2. 讨论背景：为什么要做 ECMC

## 2.1 出发点

主流 Agent 平台（Dify / Coze / LangGraph 等）解决的是"怎么调用大模型"（Prompt 管理、Workflow 编排、Tool 调用、LLM 调度）。

但企业核心业务场景（经营分析、生产调度、设备管理）真正依赖的是：

> 专家经验、业务规律、因果关系、决策逻辑、执行闭环。

一句话差异：

> 普通 Agent 平台解决"怎么调用大模型"；EARP 面向企业，应该解决"AI 如何理解企业业务运行逻辑"。

## 2.2 一个具体场景（贯穿全篇的煤矿例子）

用户问：*为什么 3 号矿产量下降？*

- 普通 Agent：查产量表 → 发现下降 → 回答"下降了 3000 万"。能答"是什么"，不能答"为什么"。
- 经营专家：产量下降 → 收入/成本分解 → 设备/地质/人员/运输/调度归因 → 数据验证 → 措施建议。
- EARP 目标：把后者（专家脑中的**业务因果模型**）结构化、资产化，让 Agent 复现专家的分析方法。

## 2.3 战略判断

> 未来企业 Agent 的竞争，不是模型能力竞争，而是企业业务模型沉淀能力竞争。

大模型大家都能接；但谁能把行业几十年的专家经验变成因果图、决策模型、Capability、Agent 组织，谁才能真正进入企业核心业务。这是 EARP 与 Dify 类平台拉开差异的战略级能力。

---

# 3. 一遍读懂：核心概念配套解读

讨论后期用户说"我有点看不懂了"，于是把整套设计浓缩成四层（这也是本文最值得先读的部分）：

> - **ECMC Model = 企业知道什么**（规律、事实之上的认知）
> - **Scenario = 专家通常怎么解决这类问题**（方法论）
> - **Blueprint = 把专家方法翻译成 Planner 能理解的规划语言**（规划表示）
> - **Plan = 针对这一次具体问题真正准备执行什么**（运行实例）

## 3.1 四层链路总览

```text
                企业专家经验
                     ↓
                   ECMC
         （Causal Model / Decision Knowledge / Scenario Template）
                     ↓
            Cognitive Model Compiler
                     ↓
             Planning Blueprint          ← “这类事情通常应该怎么做”
                     ↓
用户：“为什么3号矿最近30天产量下降？”
                     ↓
                  Planner Runtime        ← “这一次具体怎么做”（解释 + 实例化）
                     ↓
                    Plan                 ← 这一次的 Task 列表
                     ↓
            Execution Runtime / Workflow / Capability
                     ↓
                  业务结果 → 反馈 → ECMC 模型演进
```

## 3.2 用煤矿例子说明各层存什么

**ECMC（源认知资产，源代码）**

- Causal Model（为什么）：`产量下降 ← 设备因素/地质因素/人员因素/运输因素/调度因素`，节点可绑定数据需求、Capability、专家规则。
- Decision Knowledge（怎么办）：`IF 设备异常是主要因素 AND 健康度 < 阈值 THEN 建议诊断/检修`。
- Scenario Template（专家方法论）："生产异常分析" = 确认异常 → 因果归因 → 检查主因 → 建议 → 输出报告。

**Blueprint（编译产物，中间表示 IR）**

- Compiler 把上面组装成 Planner 可消费的"作战提纲"：Goal Skeleton、Step 序列（获取生产数据 → 执行因果归因 → 取证据 → 决策分析 → 输出原因排序）、能力需求、输出契约。
- 关键约束：**只引用、不复制** ECMC 知识元素（防双维护，P2）。

**Plan（运行实例）**

- 把"3 号矿、最近 30 天"实例化进去：Task 1 查 3 号矿日产量，Task 2 查停机记录，Task 3 调设备健康 Capability，Task 4 因果推理，Task 5 汇总排序。Planner 只负责排计划，不执行。

## 3.3 三个最容易混淆的边界

1. **Blueprint ⊂ ECMC 吗？** 从模块归属看"是"（Derived Asset 归 ECMC 管理）；从语义层次看"不是"（Blueprint 是编译产物，不是源认知模型）。
2. **ECMC vs KB？** KB 答"是什么"（事实/状态/文档）；ECMC 答"为什么/怎么办/怎么用"（规律/对策/方法论）。
3. **ECMC vs Planner/Decision Engine？** ECMC 只提供认知资产，不规划、不执行、不做执行时分支决策。

---

# 4. 设计演进主线（讨论中走过的路）

本次讨论实际上完成了 EARP"企业认知"从**一个想法**到**四份可评审文档**的演进：

```
阶段0 想法：业务因果图（Business Causal Graph）是让 Agent 理解企业的方式
        ↓
阶段1 提出三类业务模型：Causal（为什么）/ Decision（怎么做）/ Process（怎么执行）
        ↓
阶段2 子模块设计：Business Intelligence Model Center（6 子模块：Ontology/Causal/
      Decision/Process/Scenario/Governance）
        ↓
阶段3  L2 初稿 v0.1（消息 9）→ 首轮评审（消息 21，8.8/10）
        ↓
阶段4  用户修正：去掉独立 Model Evaluation（消息 22）→ 二轮评审（消息 39，9.2/10）
        ↓
阶段5  用户盘点三章缺口：Planner 交互协议 / Causal 元模型 / FDE 工作流（消息 40）
        ↓
阶段6  更新 v0.16（更名 ECMC、Ontology 归语义层等）→ 评审（消息 67，9.3/10）
        ↓
阶段7  更新 v0.2x、引入 Cognitive Model Compiler → 评审（消息 95，9.5/10）
        ↓
阶段8  Planning Blueprint L3 v0.1（消息 100，9.4/10）→ v0.2（消息 105，9.7/10，定基线）
        ↓
阶段9  Planner Runtime L3 v0.1（消息 118，9.2/10，提出 5 项 P0/P1 修改）
        ↓
阶段10 概念澄清：ECMC × Blueprint × Plan 边界、Goal 多模型/多 Blueprint 组合（消息 125）
```

途中几次关键收敛（详见 §5）：

- Process Model 被砍掉（回归 Workflow + Scheduler 域）；
- Ontology 从"归 BMC"调整为"Enterprise Semantic Layer 共建、无人拥有"；
- 独立 Model Evaluation 被否决，改为 Governance 内的"模型演进闭环"；
- BMC 更名 ECMC；
- 新增 Cognitive Model Compiler 概念，产出 Planning Blueprint。

---

# 5. 关键架构决策记录（伴随评审逐步拍板）

每条决策给出：结论 / 理由 / 采纳状态。采纳状态与 `arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21）一致。

## D1. 平台定位：EARP 要解决"AI 如何理解企业业务运行逻辑"

- 结论：EARP 与普通 Agent 平台的差异点是**企业业务模型沉淀**，而非模型调用。
- 理由：普通平台解决"怎么调大模型"；企业要的是"懂业务规律"。
- 采纳：✅ 已进入 ECMC 设计文档背景章（§1）。

## D2. 三类业务模型 → 收敛为"因果 / 决策 / 场景"

- 结论：业务模型由三类构成——Causal Model（为什么）、Decision Model（怎么做）、Process Model（怎么执行），最终 Process 被砍（见 D4），增加 Scenario Template（怎么用）。
- 理由：企业 Agent 需要"分析 → 决策 → 执行"三件套；其中"怎么执行"已有 Workflow/Scheduler 覆盖。
- 采纳：✅ ECMC 子模块 = Causal / Decision / Scenario + Governance。

## D3. BMC 更名 ECMC（Enterprise Cognitive Model Center）

- 结论：采用"企业认知模型中心"，弃用 Business Model Center / Business Intelligence Model Center。
- 理由：Business Model 在企业软件语境易被误解为"业务模式/商业模式"；实际承载的是**企业认知**（规律、对策、专家经验），且与 EARP"Runtime + Cognitive Model + Capability"的定位更匹配。
- 采纳：✅ v0.12 更名，正式文档沿用 ECMC。

## D4. 砍掉 Process Model Center

- 结论：不设独立业务流程模型子模块；`事件 → 任务映射知识`保留在 ECMC，流程执行复用 Workflow + Scheduler。
- 理由：避免 ECMC 逐渐变成 BPM 系统；"怎么执行"属于执行域。
- 采纳：✅ 文档中明确"Process 回归 Workflow / Scheduler / Execution"。

## D5. Ontology 归 Enterprise Semantic Layer（共建，不归 ECMC）

- 结论：不说"Ontology 属于 ECMC"，而是"**Enterprise Semantic Layer（企业语义层）由 KB/ECMC 共建，双方消费、无人拥有**"。
- 理由：Ontology 是"企业世界的语言体系"（设备、矿井、订单…），服务 RAG、数据理解、因果分析、Planner 多个消费方；归任何单方都会造成"两个世界"。
- 层次：Semantic Layer（有什么）→ KB Facts（现在发生了什么）→ ECMC Reasoning（为什么/怎么办）。
- 采纳：✅ 已进入正式文档（v0.21 关联 `2026-08-07-ontology-layer-design.md`）。

## D6. 不做独立 Model Evaluation；模型优化 = Governance 内的演进闭环

- 结论：否决"增加 Model Evaluation 模块"。改为：Runtime 收集运行反馈 → Governance 管理问题(Issue) → 修改模型 → 版本升级 → 重新发布。
- 理由：ECMC 不是训练/评估 AI 模型的平台，而是**企业业务认知资产管理平台**；企业关注"业务有效性"（是否减少停机、提升产量），不是 accuracy/precision/recall。模型优化本质是"业务认知修正"，不是"重新训练"。
- 采纳：✅ 独立 Evaluation 不进 ECMC；Model Validation（历史案例命中验证）作为发布前步骤进入 FDE 工作流（v0.21 Step 5 展开）。

## D7. Decision Model 独立存在，是知识资产而非执行引擎

- 结论：Decision Knowledge 存于 ECMC（目标/约束/规则/事件-任务映射）；Decision Engine 只做执行时分支判断；Planner 只做任务规划。
- 理由：三条线混在一起必然失控—— Planner 里写规则、Decision Engine 里写业务逻辑、ECMC 里又写流程。
- 采纳：✅ 边界写入正式文档（ECMC 提供认知资产 → Planner 生成计划 → Decision Engine 执行规则 → Runtime 执行动作）。

## D8. Scenario Template 是"专家业务方案模板"，不是 Agent

- 结论：Scenario 定义目标、关联模型、所需 Capability、输入输出；Planner 据此动态生成执行计划。避免 ECMC 变成 Agent Builder。
- 采纳：✅ 正式文档明确"Scenario Template 与 Agent 解耦"。

## D9. Causal 推理"契约化"，不固化为算法

- 结论：L2 只定义 Causal Reasoning Contract（输入 Causal Model + Observation + Evidence，输出 Cause Ranking + Evidence Chain），算法（图搜索 / 贝叶斯 / LLM 推理 / 规则推理 / 时序模型）留到 L3 并保持可替换。
- 理由：过早固定 `score(path) = strength × confidence × obs_match` 等公式会把架构绑死。
- 采纳：✅ 见 `2026-08-28-causal-reasoning-engine-l3-design.md`。

## D10. 引入 Cognitive Model Compiler → 产出 Planning Blueprint（一等资产）

- 结论：ECMC 认知模型不直接进入 Planner；经 **Model Compiler** 显式编译为 **Planning Blueprint**（ECMC → Planner 的执行规划表示）。
- 理由：类比 源码 → 编译器 → 机器码：认知模型（源代码）→ Blueprint（中间表示 IR）→ Plan（运行实例）。解决"Causal 怎么进 Planner、Scenario 怎么变计划"的断层。
- 关键约束：编译是**显式动作**（发布/手工触发），不做运行时隐式编译；Blueprint 必须可追溯（source_hash / compile_time / compiler_version）。
- 采纳：✅ Blueprint L3 已落盘（v0.3）。

## D11. Blueprint ≠ Workflow

- 结论：Blueprint 描述**业务推理方法（要做什么）**；Workflow 描述**执行编排（怎么做）**。执行编排属 Workflow 域，Blueprint 不承载。
- 对照：Blueprint（业务方法，FDE 维护，随业务变化）；Workflow（执行过程，开发/管理员维护，随系统变化）。
- 采纳：✅ Blueprint L3 设计原则 P6。

## D12. Blueprint 只引用、不复制 ECMC 知识元素（防双维护）

- 结论：Blueprint 不允许定义新的业务规则，只允许引用 ECMC 模型中的知识元素；新业务逻辑必须回源模型修改。
- 理由：否则会出现 Causal Model 一套逻辑、Blueprint 一套逻辑、Planner 又一套逻辑，最终失控。
- 采纳：✅ Blueprint L3 设计原则 P2（v0.21 §28）。

## D13. 多模型引用：source_model_id → source_models[]

- 结论：一个 Blueprint 可同时引用 Scenario / Causal / Decision 多个源模型，并分别钉扎版本（primary/supporting）。
- 理由：真实企业场景"生产异常分析"必然是 Scenario + 产量下降 Causal + 维修策略 Decision 的组合。
- 关键原则：任一源模型更新 → 重新编译新 Blueprint 版本。
- 采纳：✅ Blueprint L3 v0.2（`blueprint_source_models` 表）。

## D14. Step Type 是扩展点，不是固定枚举全集

- 结论：`step_type`（knowledge_query / data_fetch / capability_call / decision_branch / output）通过 **Step Type Registry** 扩展，L3 保留枚举但架构上定义"Step → Step Type → Handler"三层。
- 理由：防止 step_type 枚举膨胀成 Workflow Engine。
- 关键约束：新类型必须是**执行语义扩展**，不能是业务规则载体。
- 采纳：✅ Blueprint L3 v0.2（`step_type_registry`）。

## D15. 编译与 Plan 的版本冻结

- 结论：
  - Compile Record（compile_id / source_model_hash / compiler_version / compile_time / validation_result / error_log）支撑审计；
  - **Plan 创建时完成版本冻结**：Plan 记录 blueprint 版本 + source_models 版本 + compile_record；执行中 ECMC 发布新版本不影响当前 Plan，下一个 Request 才用新版本。
- 理由：企业需要"为什么 AI 当时这样分析"的完整审计链：Agent Trace → Plan → Blueprint → Compile Record → Source Models → 专家修改记录。
- 采纳：✅ Blueprint L3（Compile Record）+ Planner Runtime L3（版本冻结）。

## D16. 规划约束分级：Hard / Soft Constraint

- 结论：用户约束不能简单覆盖 Blueprint 约束。约束分两级：
  - **Hard Constraint**（安全、mandatory_capability、minimum_evidence、合规边界、禁止动作）：不可被 Planner/用户弱化；
  - **Soft Constraint**（优先成本/速度、解释深度、方案数量）：允许用户调整。
- 优先级：Policy/Compliance → Blueprint Hard → User → Blueprint Soft → Planner 偏好。用户只能**增加或收紧 Hard Constraint，不能削弱**（MUST）。
- 采纳：✅ Planner Runtime L3 v0.2（P0 修改项之一）。

## D17. 失败降级不能绕过业务约束

- 结论：Blueprint 不可用 → 降级到"直接模型匹配 + 运行时推理" → 再不行 → Rule Planner。但 **Fallback 只能降低规划质量，不能降低业务约束等级**：必须继承 Hard Constraints / Policy / Permission / mandatory capability / minimum evidence / output contract；仍不满足 → FAILED，不无限降级。
- 采纳：✅ Planner Runtime L3 v0.2（P0 修改项）。

## D18. Step → Task 不绑定 1:1 基数

- 结论：改成更通用的抽象：**Interpreter 将 Step 投影为 Planning Fragment（Task 0..N + Edge 0..N + Constraint 0..N）**。
- 理由：data_fetch 一个业务步骤可拆成多个并行 Task（EAM 故障记录 / IoT 状态 / 维修记录）；decision_branch 可能 0 Task + N 个条件边。写死"1 step ≥ 1 task"会与未来并行展开矛盾。
- 采纳：✅ Planner Runtime L3（P1 修改项，v0.2 建议）。

## D19. Replanning 修改范围受限 + 重试次数配置化

- 结论：Plan Validation 失败后的 Replanning 只允许修改 Task 拆分/合并、Capability 解析、并行度、Soft Constraint 排序、资源选择；**不允许修改** Goal 语义、source_ref、源模型 Rule、Hard Constraint、mandatory capability、业务输出契约。`≤3` 次为默认值，可配置。
- 理由：否则 LLM 自由修改 = 退回自由 Agent。
- 采纳：✅ Planner Runtime L3（P1 修改项）。

## D20. Goal × 模型 × Blueprint 的倍数关系

- 结论：
  - **一个 Goal → 多个 ECMC Model**：常态（归因 + 设备健康 + 维修策略 + 调度策略…）。
  - **简单 Goal → 1 个 Blueprint → N 个 Model**：最常见、最推荐。
  - **复杂 Goal → Goal Decomposition → 多个 Blueprint → 1 个 Plan**：示例子目标（为什么下降 / 怎么优化 / 有什么风险）分别命中诊断 / 优化 / 风险评估 Blueprint。
- 三个组合层次不要混淆：Model Composition（知识组合）、Blueprint Composition（方法组合）、Plan Composition（运行任务组合）。
- 采纳：✅ 结论已进入 Blueprint L3（source_models[]）；"复杂 Goal 拆多 Blueprint"列为后续重点研究方向（L3.1+）。

## D21. ECMC 服务契约的三个细化

- 结论（评审第 1 章《Planner 交互协议》后采纳）：
  1. 协议命名为 **Cognitive Service Contract**（Model Discovery + Reasoning Service + Capability Dependency + Feedback），而非 REST API 设计——不绑定 HTTP/gRPC/Event Bus，L3 决定通信方式；
  2. Model Discovery 增加 `business_objective`（diagnose / predict / optimize / recommend），提升匹配准确度；返回 `capability_requirements`（模型运行所必需，非 hint）；
  3. Reasoning 增加 `explain_level`（basic / detailed / audit）；隐藏 algorithm 参数，改用 `reasoning_mode`（default / fast / explainable / high_accuracy）；错误码增加 422（模型存在但输入不足，返回 missing_requirements）。
- 采纳：✅ 已进入 ECMC 设计文档 §4.4。

## D22. Causal Model 元模型六要素（Evidence 不进入模型）

- 结论：统一元模型六要素 = Node / Relation / Evidence / Rule / Data Binding / Capability Binding。
- 关键边界：**Evidence 是运行时产物，不写入模型对象**——模型存规律（设备故障 → 产量下降），运行时才产生实例证据（某设备某天报警 100 次）。否则会污染模型。
- 采纳：✅ 已进入 ECMC 设计文档（§3.6 整合视图）。

---

# 6. 评审结论与遗留问题

## 6.1 评审演进与评分

| 阶段 | 对象 | 评分 | 主要结论 |
|---|---|---|---|
| 首轮（消息 21） | BMC L2 v0.10 | 8.8/10 | 边界与 KB 分离清晰；5 个待决策问题（更名 / 语义层 / 契约化 / Scenario 边界 / Evaluation） |
| 二轮（消息 39） | ECMC（去 Evaluation 后） | 9.2/10 | 职责边界收敛；Scenario Template 定位需写死 |
| 三轮（消息 67） | ECMC v0.16 | 9.3/10 | 已是"架构决策文档"；提出 Cognitive Model Compiler |
| 四轮（消息 95） | ECMC v0.2x（含 Compiler） | 9.5/10 | 升级为"生命周期 + 编译 + 服务运行体系"；补 FDE Step5 验证 |
| Blueprint v0.1（消息 100） | Planning Blueprint L3 | 9.4/10 | 核心链路打通；6 项必改/建议（Blueprint≠Workflow、Compile Record、多模型、Step Type 注册、Runtime Semantics、Trace） |
| Blueprint v0.2（消息 105） | Planning Blueprint L3 | 9.7/10 | 6 问题全部闭环，定为基线；3 个精化点留 L3.1（Planning Constraint、生命周期 draft→approved、Step 多引用） |
| Planner Runtime（消息 118） | Planner Runtime L3 v0.1 | 9.2/10 | 链路闭合；5 项 P0/P1 修改（Hard/Soft Constraint、降级继承、Step→Fragment、Replanning 边界、版本冻结） |

## 6.2 已达成共识、等待落盘的遗留问题

1. **复杂 Goal 的多 Blueprint 组合**（Goal Decomposition → 多 BP → 单 Plan）——被明确为下一阶段比"单个 Blueprint Step→Task"更值得研究的方向（Blueprint L3.1）。
2. **Blueprint 生命周期补 draft / reviewing / approved**（与 ECMC Governance 对齐）——v0.3 已补。
3. **Step 多节点引用**（`blueprint_step_sources` 拆表，类似 source_models 设计）——L3.1 细化。
4. **蓝图市场（Blueprint Marketplace）**：行业 Blueprint 资产复用，远期产品能力（非本期）。
5. **Causal Model 存储与推理引擎** L3——已由 `2026-08-28-causal-reasoning-engine-l3-design.md` 承接。

## 6.3 阅读正式文档时的三条主线

1. **边界主线**：ECMC 负责（因果 / 决策 / 场景 / 治理）vs 不负责（执行、规划、执行时分支、流程执行）；
2. **消费主线**：ECMC 模型 → Compiler → Blueprint → Planner Runtime → Plan → Runtime/Workflow/Capability → 反馈 → Governance；
3. **治理主线**：Feedback → Issue → Model 修改 → Version 升级 → 重新发布（对应 D6 演化闭环）。

---

# 7. ECMC 与周边模块的职责边界速查

| 模块 | 负责 | 与 ECMC 的关系 |
|---|---|---|
| **KB（Knowledge Center）** | 事实、状态、文档、ABox 实例 | ECB："是什么"；ECMC："为什么/怎么办" |
| **Enterprise Semantic Layer** | TBox 语言体系（对象、指标、关系类型） | KB 与 ECMC 共建、无人拥有 |
| **Planner** | 意图解析 → 计划生成 | 消费 ECMC 认知资产（经 Blueprint）；ECMC 是其知识源之一 |
| **Decision Engine** | 执行时分支选择（规则/LLM/ML） | 执行 ECMC 提供的 Decision Knowledge，不持有业务逻辑 |
| **Runtime / Orchestrator / Workflow / Scheduler** | 执行动作、编排、调度 | ECMC 不执行；Process 化的执行知识归此处 |
| **Capability Center** | 能力注册、发现、执行 | ECMC 只声明 capability_requirements，不调用 |
| **Policy** | 权限（模型可见性 + 行级可见性，D21 双层权限） | 模型消费需过 Policy 过滤 |

---

# 附录 A. 配套文档索引

| 文档 | 定位 | 与讨论的对应 |
|---|---|---|
| `arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21） | ECMC L2 前置设计：模块边界、子模块、消费方契约 | 阶段 3–7（消息 2→95）的全部决策 |
| `arch/design/2026-08-28-planning-blueprint-l3-design.md`（v0.3 基线） | Blueprint 元模型、Compiler 管线、Planner 消费流程 | 阶段 8（消息 100/105）评审采纳项 |
| `arch/design/2026-08-28-planner-runtime-l3-design.md`（v0.2 draft） | Blueprint → Plan 解释执行层 | 阶段 9（消息 118）评审采纳项 |
| `arch/design/2026-08-28-causal-reasoning-engine-l3-design.md` | Causal 存储与推理引擎（算法契约） | 对应 D9（推理契约化） |
| `arch/design/2026-08-07-ontology-layer-design.md` | Enterprise Semantic Layer / Ontology | 对应 D5 |
| `arch/L2/02-reasoning/planner-specification.md`（v1.1） | Planner L2 契约 | Blueprint/Planner Runtime L3 的上游规范 |
| `arch/L2/02-reasoning/decision-engine-specification.md`（v1.0） | 决策引擎规范 | 对应 D7 边界 |

---

# 附录 B. 讨论轮次摘要（对话转写概要）

| # | 角色 | 要点 |
|---|---|---|
| 1 | 用户 | 业务因果图是 EARP 差异化核心；EARP 应解决"AI 理解企业运行逻辑"；建议增加业务模型层；三类模型（因果/决策/流程） |
| 2 | AI | 提出 Business Intelligence Model Center 六子模块（Ontology/Causal/Decision/Process/Scenario/Governance）；关键判断：Ontology + Causal 是护城河 |
| 3 | 用户 | 先写一份 L2 设计文档供评审 |
| 4 | AI | 输出 L2 初稿 v0.1（背景/目标/位置/六子模块/集成/范围） |
| 5 | 用户 | 评审下这个设计文档 |
| 6 | AI | 首轮评审：KB/BMC 边界 ★5；Ontology 建议改 Enterprise Semantic Layer；砍 Process Model；Causal 契约化；建议加 Evaluation；评分 8.8/10；提 5 个架构决策问题 |
| 7 | 用户 | 修正：不需要独立 Evaluation，纳入模型升级/版本进化 |
| 8 | AI | 同意；模型演进闭环（Feedback → Governance → Version → 再发布）；Business Model Improvement 而非 Evaluation |
| 9 | 用户 | 再次评审 |
| 10 | AI | 二轮评审 9.2/10：建议更名 ECMC；Semantic Layer 提升地位；Scenario Template 定位写死；下一步补三章（交互协议/元模型/FDE 工作流） |
| 11 | 用户 | 盘点三章缺口并给出第 1 章《ECMC × Planner 交互协议》草案（ModelQuery/ReasoningInvoke + 契约 MUST） |
| 12 | AI | 评审第 1 章：改"服务契约"；加 business_objective；capability_hint→capability_requirements；加 explain_level；隐藏 algorithm；加 422；建议 5 小节结构 |
| 13 | 用户 | 更新了一版（v0.16） |
| 14 | AI | 三轮评审 9.3/10：已从"模块设计文档"进化成"架构决策文档"；确认 Ontology 归语义层、Decision/KB/ECMC 边界 |
| 15 | 用户 | 更新了一版（v0.2x） |
| 16 | AI | 四轮评审 9.5/10：引入 Cognitive Model Compiler 正确；Blueprint 可追溯（source_hash/compile_time/compiler_version）；元模型六要素；FDE 补 Step5 模型验证 |
| 17 | 用户 | 请评审（Planning Blueprint L3 v0.1） |
| 18 | AI | Blueprint v0.1 评审 9.4/10：Blueprint≠Workflow；Compile Record；source_models[]；Step Type 扩展机制；Runtime Semantics；6 项修改清单 |
| 19 | 用户 | 更新了（v0.2） |
| 20 | AI | Blueprint v0.2 评审 9.7/10：6 问题闭环，定为基线；3 个精化点；建议下一步做 Planner Runtime Specification 与 Causal Storage L3 |
| 21 | 用户 | 评审（Planner Runtime L3 v0.1） |
| 22 | AI | Planner Runtime 评审 9.2/10：5 项 P0/P1（Hard/Soft Constraint、降级继承 Hard、Step→Planning Fragment、Replanning 修改边界、版本冻结）；状态机泛化 |
| 23 | 用户 | 看不懂，请浅显介绍 |
| 24 | AI | 一遍读懂：ECMC 教"懂业务"、Blueprint 教"这类事通常怎么做"、Planner 制定"这一次怎么做"、Runtime 负责执行 |
| 25 | 用户 | ECMC 与 Blueprint 边界？一个目标是否需要多个 ECMC/Blueprint？ |
| 26 | AI | 边界：Blueprint 是 ECMC 的派生资产（中间表示）；三个组合层次（Model/Blueprint/Plan Composition）；1 Goal → N Models 常态，复杂 Goal → 分解 → 多 Blueprint → 1 Plan |

---

*本文件为配套说明，不替代正式设计文档；如与正式文档冲突，以正式文档为准。*