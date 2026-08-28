# Planning Blueprint — L3 实现设计

**文档编号：DESIGN-ECMC-BLUEPRINT-L3**
**版本：v0.2（draft）**
**日期：2026-08-28**

> 上游：`arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21，§3.6 Cognitive Model Compiler / §4.4 Cognitive Service Contract）、`arch/L2/02-reasoning/planner-specification.md`（v1.1）
> 定位：ECMC → Planner 的执行规划表示（一等资产）。本文定义 Planning Blueprint 的元模型（表结构）、Compiler 编译管线、Planner 消费流程。
> 技术栈：FastAPI + SQLAlchemy 2 async + PostgreSQL 16 + pgvector，复用 `tenant_session()` / RLS `SET LOCAL` 模式。
> v0.2 变更（评审采纳）：① Blueprint≠Workflow 边界；② 新增 Compile Record；③ 多模型引用 source_models[]；④ Step Type 扩展机制；⑤ 新增 Blueprint Runtime Semantics 章节；⑥ Blueprint 与 Agent Trace 关联。

---

# 一、设计原则（继承 L2 约束）

```
P1  纯知识变换——Blueprint 由 Compiler 从 ECMC 模型编译产生，不执行动作
P2  防双维护——Blueprint 只引用（不复制）ECMC 模型知识元素；
    任何新业务逻辑必须回到源模型建模（v0.21 §28）
P3  不可变版本——Blueprint 随源模型版本不可变；源模型更新 → 重新编译
    新版本，旧版本仍可消费（同 ECMC §3.4.3）
P4  显式编译——编译是发布时/手工触发，不是运行时隐式编译
P5  可追溯——Blueprint 版本 ↔ 源模型版本 ↔ reasoning_trace 三方可追溯
P6  Blueprint ≠ Workflow（v0.2 新增）——Blueprint 描述**业务推理方法**
    （要做什么：获取数据/分析因素/输出排序），不描述**执行编排**
    （怎么做：调 MES API/等待返回/重试 3 次）。
    区别：关注点（业务方法 vs 执行过程）/ 维护者（FDE vs 开发）/ 
    变化源（业务变化 vs 系统变化）。执行编排属 Workflow 域
    （L2-04），Blueprint 不承载；两者融合即架构失控
```

---

# 二、目录结构（新增 bmc_compiler 模块）

```
apps/earp-server/src/earp_server/
├── bmc/                        # ECMC 领域（新，L3 前瞻已声明）
│   ├── __init__.py
│   ├── compiler/
│   │   ├── __init__.py
│   │   ├── models.py           # Planning Blueprint SQLAlchemy 表模型（7 张表）
│   │   ├── compile_service.py  # 编译管线：模型 → Blueprint
│   │   ├── reference_resolver.py # 引用解析：模型知识元素 → Blueprint 引用
│   │   ├── validator.py        # 编译完整性校验（引用无遗漏/能力可解析）
│   │   └── routes.py           # API 端点（/v1/ecmc/blueprints/...）
│   ├── metamodel/              # 元模型服务（Node/Relation/Rule/DataBinding/CapabilityBinding）
│   └── governance/             # Model Governance（issue/change_log/审批）
├── ontology/                   # 现有模块（Enterprise Semantic Layer，复用）
├── planner/                    # 现有模块（消费 Blueprint）
└── infra/                      # 现有（db/eventbus/task_queue 复用）
```

**依赖方向**：`bmc.compiler` 依赖 `bmc.metamodel`（源模型读取）+ `ontology`（TBox 词汇引用）+ `infra`；被 `planner` 消费。符合 import-linter 契约（新增 `planner -> bmc.compiler` 例外，理由：Planner 消费编译产物）。

---

# 三、Planning Blueprint 元模型（表结构）

## 3.1 表总览

| 表 | 说明 |
|---|---|
| `planning_blueprints` | Blueprint 主表（版本化资产，**多模型引用** v0.2） |
| `blueprint_source_models` | 源模型引用表（多模型组合 + 跨模型版本钉扎，v0.2 新增） |
| `blueprint_compile_records` | 编译记录（build log，v0.2 新增） |
| `blueprint_intents` | 意图签名（可响应意图，多值） |
| `blueprint_goal_skeletons` | 目标分解骨架（Goal 模板，结构化） |
| `blueprint_steps` | 步骤蓝图（引用源模型元素 + 注册表 step_type） |
| `blueprint_step_deps` | 步骤依赖（DAG 边） |
| `step_type_registry` | Step Type 扩展注册表（v0.2 新增） |
| `blueprint_capability_reqs` | 能力需求（编译自 §4.4.4） |
| `blueprint_output_contracts` | 输出契约（输出结构声明） |

## 3.2 planning_blueprints（主表）

```
blueprint_id        VARCHAR(64) PK
tenant_id           VARCHAR(64) NOT NULL
primary_model_type  VARCHAR(16) NOT NULL CHECK IN ('causal','decision','scenario')
primary_model_id    VARCHAR(64) NOT NULL         -- 主源模型（归属用）
version             VARCHAR(32) NOT NULL            -- Blueprint 自身版本（随主源）
status              VARCHAR(16) NOT NULL CHECK IN ('compiled','superseded','withdrawn')
compiled_at         TIMESTAMPTZ NOT NULL DEFAULT now()
compiled_by         VARCHAR(64) NOT NULL            -- 触发者（发布/手工）
compiler_version    VARCHAR(16) NOT NULL            -- Compiler 实现版本（可复现）
intent_signature    JSONB NOT NULL                  -- 编译时快照（entry_point/business_objective/domain）
validation_contract JSONB NOT NULL DEFAULT '{}'     -- 输入要求/缺失数据容忍度
output_contract     JSONB                           -- 冗余快照（与 3.7 表对应，便于 Planner 单表读取）
UNIQUE (tenant_id, primary_model_id, version)
```

**引用而非复制原则（P2）**：源模型通过 `blueprint_source_models` 关联表引用（见 3.3）；Blueprint 内不存业务规则文本，只存指向源模型元素的引用（见 3.5）。任何业务逻辑变更 → 源模型改 → 重新编译。

## 3.3 blueprint_source_models（源模型引用表，v0.2）

```
source_ref_id       VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
model_type          VARCHAR(16) NOT NULL CHECK IN ('causal','decision','scenario')
model_id            VARCHAR(64) NOT NULL
model_version       VARCHAR(32) NOT NULL            -- 跨模型版本钉扎（每个源模型独立版本）
role                VARCHAR(16) NOT NULL CHECK IN ('primary','supporting')
```

**多模型组合**：一个 Blueprint 可引用多个模型（如 Scenario + Causal + Decision）：

```json
{
  "scenario":  "production_analysis_v1",
  "causal":    ["production_drop_v2"],
  "decision":  ["maintenance_strategy_v1"]
}
```

**版本钉扎（MUST）**：每个源模型独立钉扎版本——任一源模型更新 → 重新编译新 Blueprint 版本（保留旧版本可消费）；跨模型版本组合在编译记录中可追溯。

## 3.4 blueprint_compile_records（编译记录，v0.2）

```
compile_id          VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
compile_time        TIMESTAMPTZ NOT NULL DEFAULT now()
compiler_version    VARCHAR(16) NOT NULL
source_model_hashes JSONB NOT NULL                -- 各源模型内容 hash（变更检测）
input_snapshot      JSONB NOT NULL                -- 编译输入快照（模型版本 + 元素引用）
validation_result   JSONB NOT NULL                -- 校验结果（引用完整性/能力可解析/DAG）
status              VARCHAR(16) NOT NULL CHECK IN ('success','failed','partial')
error_log           JSONB DEFAULT '[]'            -- 失败原因/告警（build log）
```

**用途（类似编译器 build log）**：
```
- Debug："为什么 Blueprint v3.0 多了这个步骤？" → 查 compile_record 输入/校验
- 复现：同 source_model_hashes + compiler_version → 期望同输出
- 审计：变更链路（模型改了什么 → 编译记录 → 新 Blueprint）
```

## 3.5 blueprint_intents（意图签名，多值）

```
intent_id           VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
entry_point         VARCHAR(128) NOT NULL          -- 语义描述（供语义匹配）
direction           VARCHAR(8) NOT NULL CHECK IN ('up','down')
domain              VARCHAR(64) NOT NULL
business_objective  VARCHAR(16) NOT NULL CHECK IN ('diagnose','predict','optimize','recommend')
UNIQUE (blueprint_id, entry_point, direction, domain, business_objective)
```

**用途**：Planner Model Discovery（§4.4.2）的匹配键——意图四元组命中 Blueprint。

## 3.6 blueprint_steps（步骤蓝图，核心表）

```
step_id             VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
step_seq            INT NOT NULL                   -- 顺序（非执行序，执行序由 deps 决定）
step_type           VARCHAR(32) NOT NULL FK        -- 引用 step_type_registry（扩展机制，v0.2）
step_name           VARCHAR(128) NOT NULL

-- 引用源模型元素（防双维护核心：引用不复制）
source_ref_type     VARCHAR(16) NOT NULL           -- node | relation | rule | data_requirement
source_ref_id       VARCHAR(64) NOT NULL           -- 源模型元素 id（跨模型域）
source_ref_path     TEXT NOT NULL                  -- 语义路径（如 causal:{model_id}:node:{node_id}）

-- 步骤参数（编译时的投影，非新业务逻辑）
params              JSONB NOT NULL DEFAULT '{}'    -- 如 data_requirement 的时间窗/聚合（来自源）
output_field        VARCHAR(128)                   -- 本步输出字段（供后续步引用）
```

**防双维护落地**：`step_type` 必须注册于 `step_type_registry`（扩展点，见 3.8）——内置五类（knowledge_query / data_fetch / capability_call / decision_branch / output）为起点，**没有**"自定义业务规则"类型；`source_ref_path` 强制指向源模型元素——编译器校验该引用在源模型中真实存在（P5 完整性校验）。

## 3.7 blueprint_step_deps（步骤依赖）

```
dep_id              VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
from_step_id        VARCHAR(64) NOT NULL
to_step_id          VARCHAR(64) NOT NULL
dep_type            VARCHAR(16) NOT NULL CHECK IN ('sequential','conditional','data_flow')
condition           JSONB                          -- dep_type=conditional 时（引用源模型 Rule）
UNIQUE (blueprint_id, from_step_id, to_step_id)
```

**约束**：`blueprint_steps + blueprint_step_deps` 构成 DAG（编译期校验，同 Causal Model DAG 原则）。

## 3.8 step_type_registry（Step Type 扩展注册表，v0.2）

```
type_id             VARCHAR(32) PK                 -- 如 'capability_call'、'human_confirm'
type_name           VARCHAR(64) NOT NULL
description         TEXT NOT NULL
handler_id          VARCHAR(64) NOT NULL           -- 处理器实现（Handler Registry 注册）
params_schema       JSONB NOT NULL DEFAULT '{}'    -- 该类型步骤的参数 JSON Schema（校验）
is_core             BOOLEAN NOT NULL DEFAULT false -- 内置五类=true；扩展=false
status              VARCHAR(16) NOT NULL CHECK IN ('active','deprecated')
added_at            TIMESTAMPTZ NOT NULL DEFAULT now()
```

**扩展机制（v0.2，评审采纳）**：
```
- step_type 是**扩展点**，不是固定业务类型全集——未来可能增加
  human_confirm / simulation / optimization / approval /
  external_agent_call / parallel_group 等
- 新类型 = 注册表新行 + Handler 实现（两步），不改 Blueprint 表结构
- 结构：Blueprint Step → step_type（注册表）→ Handler（执行/解释器）
- 约束：
  MUST: 新类型必须是**执行语义的扩展**（如并行/人工确认），
        不是业务规则载体（业务规则永远回源模型，P2）
  MUST: 新类型需 Handler 实现并经测试；未注册类型编译期拒绝
  MUST: 内置五类 is_core=true 不可删除；扩展类型可 deprecated
```

## 3.9 blueprint_capability_reqs（能力需求）

```
cap_req_id          VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
capability_id       VARCHAR(64) NOT NULL           -- Capability Center 注册 id
purpose             TEXT NOT NULL                  -- 对应哪个步骤/节点
required            BOOLEAN NOT NULL DEFAULT true
input_schema        JSONB NOT NULL DEFAULT '{}'
output_usage        JSONB NOT NULL DEFAULT '{}'
```

**来源**：编译自 ECMC 模型节点 Capability Binding（§3.1.0 ⑥ + §4.4.4）；**不新增**能力需求（防双维护——Planner 按此解析能力，见 §4.4.4 链路）。

## 3.10 blueprint_output_contracts（输出契约）

```
output_id           VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
output_type         VARCHAR(16) NOT NULL CHECK IN
                    ('cause_ranking','report','recommendation','workflow')
output_schema       JSONB NOT NULL                 -- 输出结构（字段/嵌套/必填）
```

**用途**：Planner 生成 Plan 时声明输出目标；Agent 据此格式化结果。

---

# 四、Compiler 编译管线

```
触发（显式）：
  源模型发布（Publish Approval 通过）→ 自动触发编译
  手工触发（Compile API）→ 重新编译当前版本

管线：
  ① 读取源模型（metamodel 服务，取已发布版本快照）
  ② 意图签名提取 → blueprint_intents
  ③ 步骤蓝图生成（按模型类型）：
     - Scenario → 全量：methodology_steps → steps + deps
     - Decision → goal_skeleton + 规则序列
     - Causal   → intent_signature + capability_reqs（不预编译路径）
  ④ 引用解析（reference_resolver）：每步 source_ref_path → 校验源模型
     元素存在（P5）
  ⑤ 能力需求编译：节点 Capability Binding → blueprint_capability_reqs
  ⑥ 完整性校验（validator）：
     - 引用无遗漏（源模型所有节点/规则均被引用或显式标记不编译）
     - 能力需求可解析（capability_id 在 Capability Center 注册且 active）
     - 步骤图 DAG 无环
     - 防双维护检查（无自定义规则类型 / 无孤儿业务逻辑）
  ⑦ 写入 compile_record（v0.2）：source_model_hashes / input_snapshot /
     validation_result / status / error_log（编译记录先于 Blueprint 落库）
  ⑧ 落库：blueprints + 子表（同一事务，compile_record.status=success 才落）
  ⑨ 发布事件：earp.ecmc.blueprint.compiled（Planner 侧缓存失效通知）
```

**编译失败处理**：校验失败 → compile_record 记 failed + error_log（build log 保留），
不产出 Blueprint；源模型仍可 published（标注 "编译失败" 告警，通知 owner）——
编译是独立产物，不阻断模型发布（模型可被 Discovery 查到，但 Blueprint 不可用
→ Planner 走运行时推理降级路径）。后续可用 compile_record 排查失败原因。

---

# 五、Planner 消费流程

```
① 意图匹配（Model Discovery，§4.4.2）：
   intent 四元组 → 命中 published Blueprint（或直接命中模型）
② Blueprint 加载：
   Planner 读取 blueprint_intents / steps / deps / capability_reqs /
   output_contract（单次读取，含 output_contract 冗余快照）
③ 目标生成：
   goal_skeleton → Goal 分解（Planner 已有 Goal Generation 机制）
④ Plan 生成：
   steps + deps → Plan Step 序列
   capability_reqs → 向 Capability Center 解析能力（§4.4.4 链路）
   knowledge_query 步 → Causal Reasoning Contract 调用（§4.4.3，运行时）
   data_fetch 步 → 按 source_ref 引用的 data_requirement 生成取数 Step
   decision_branch 步 → Decision Engine 规则（§4.2）
   output 步 → 按 output_contract 声明输出目标
⑤ Execution Trace 记录：
   blueprint_id + version 记入 trace（可复现性，P5）
```

**降级路径**：Blueprint 编译失败/被 withdraw → Planner 回退到"直接模型匹配 + 运行时推理"（功能可用、规划效率降级）——Blueprint 是优化层，不是必需层。

---

# 六、Blueprint Runtime Semantics（执行语义，v0.2 新增）

> **定位**：Blueprint 描述"要做什么"（业务方法），但 Planner/Runtime 解释时
> 需要明确的执行语义——这不是 Workflow 编排（P6），而是 Blueprint 步骤的
> 解释规则。

## 5.1 Step 生命周期（解释视角）

```
Blueprint Step（静态定义）
  → Planner 实例化为 Plan Step（运行时对象）
  → Execution 执行（Runtime 负责）
  → 结果回填（output_field）
```

## 5.2 Step 执行语义（语义级，非编排细节）

```
同步性（由 Handler 声明，step_type_registry 注册）：
  capability_call: 默认同步；handler 声明 async 时 Planner 可并行调度
数据流（deps.data_flow）：
  后续步可引用前步 output_field；缺失字段时 Planner 报规划错误（不静默）
失败语义（v0.2 定义，防"静默假成功"）：
  MUST: 步骤失败 → Plan 标记对应步骤 failed，不伪造成功
  MUST: required capability 失败 → 影响下游依赖步（依赖传播）
  SHOULD: 非关键步失败可标记 degraded（Blueprint 允许降级的能力）
条件分支（deps.conditional）：
  条件引用源模型 Rule（不是新规则）——Planner 评估后选分支
```

## 5.3 与 Workflow 的边界（P6 落地）

```
Blueprint 不定义：重试次数 / 超时 / 并发度 / 具体端点 / 重试退避
  ——这些是 Workflow / Resource Spec 的执行编排细节
Blueprint 定义：步骤顺序（业务方法）/ 数据依赖 / 条件分支（业务规则）
  ——业务方法层
实现：Planner 把 Blueprint 步骤投影为 Workflow 节点时，编排细节
  由 Workflow/Resource 层补充（L2-04）
```

---

# 七、与既有契约的对接

| 既有契约 | 对接点 |
|---|---|
| §4.4.2 Model Discovery | blueprint_intents 是 Discovery 的索引；命中 Blueprint 优先于裸模型 |
| §4.4.4 Capability Dependency | blueprint_capability_reqs 编译自该契约，Planner 按它解析能力 |
| §3.6 防双维护 | step_type 五类枚举 + source_ref_path 强制引用 + 编译完整性校验 |
| §3.4.3 版本原则 | Blueprint 随源模型版本不可变；superseded 不删旧版本 |
| §3.5 反馈闭环 | reasoning_trace_id ↔ blueprint_id 关联，绩效统计可下钻到 Blueprint |
| Agent Trace（v0.2） | Execution Trace 记录 blueprint_id + version + step 级引用（每步 source_ref_path）——Agent 执行可回溯到"哪个 Blueprint 哪步"再到"源模型哪个元素"（P5 三方追溯） |
| Concept Model | 新增概念对象：PlanningBlueprint |

---

# 八、API 草案（L3 接口，语义对应 §4.4 契约）

```
GET    /v1/ecmc/blueprints?intent=...&objective=...&domain=...   — Discovery（匹配 Blueprint）
GET    /v1/ecmc/blueprints/{id}/versions/{ver}                    — 加载完整 Blueprint
POST   /v1/ecmc/blueprints/{id}/compile                            — 手工重新编译
GET    /v1/ecmc/blueprints/{id}/versions                          — 版本列表
POST   /v1/ecmc/blueprints/{id}/withdraw                           — 下线（走审批）
```

（传输层 HTTP 为参考实现，gRPC/内存/EventBus 由 Runtime 集成层决定——L2 §4.4 原则。）

---

# 九、开放问题（下一轮评审）

1. **步骤粒度**：Blueprint step 与源模型 node 是 1:1 还是可聚合/拆分？
   评审建议**不绑定**：Node 可生成多个 Step；Step 可引用多个 Node
   （业务模型粒度 ≠ 执行粒度）。v0.2 保留灵活性（source_ref 可多对多），
   具体映射规则待细化
2. **多模型 Blueprint 组合**：v0.2 已用 blueprint_source_models 支持多模型
   引用 + 跨模型版本钉扎；多模型组合的引用冲突（同一节点被两模型引用
   语义不一致）待细化
3. **性能**：Blueprint 缓存策略（Planner 侧缓存 vs 服务端缓存）、
   intent 匹配索引（复用 Semantic Index / pgvector）
4. **降级 SLA**：编译失败时"直接模型匹配"路径的可用性保证
5. **Step Type 扩展治理**（v0.2）：扩展类型（human_confirm/simulation/…）
   的审批流程、Handler 测试标准、对 Planner 的影响（Planner 需理解新类型
   的执行语义）
