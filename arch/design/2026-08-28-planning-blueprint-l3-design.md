# Planning Blueprint — L3 实现设计

**文档编号：DESIGN-ECMC-BLUEPRINT-L3**
**版本：v0.1（draft）**
**日期：2026-08-28**

> 上游：`arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21，§3.6 Cognitive Model Compiler / §4.4 Cognitive Service Contract）、`arch/L2/02-reasoning/planner-specification.md`（v1.1）
> 定位：ECMC → Planner 的执行规划表示（一等资产）。本文定义 Planning Blueprint 的元模型（表结构）、Compiler 编译管线、Planner 消费流程。
> 技术栈：FastAPI + SQLAlchemy 2 async + PostgreSQL 16 + pgvector，复用 `tenant_session()` / RLS `SET LOCAL` 模式。

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
| `planning_blueprints` | Blueprint 主表（版本化资产） |
| `blueprint_intents` | 意图签名（可响应意图，多值） |
| `blueprint_goal_skeletons` | 目标分解骨架（Goal 模板，结构化） |
| `blueprint_steps` | 步骤蓝图（顺序步骤，引用源模型元素） |
| `blueprint_step_deps` | 步骤依赖（DAG 边，步骤间顺序/条件） |
| `blueprint_capability_reqs` | 能力需求（编译自 §4.4.4 capability_requirements） |
| `blueprint_output_contracts` | 输出契约（输出结构声明） |

## 3.2 planning_blueprints（主表）

```
blueprint_id        VARCHAR(64) PK
tenant_id           VARCHAR(64) NOT NULL
source_model_type   VARCHAR(16) NOT NULL CHECK IN ('causal','decision','scenario')
source_model_id     VARCHAR(64) NOT NULL
source_model_version VARCHAR(32) NOT NULL
version             VARCHAR(32) NOT NULL            -- Blueprint 自身版本（随源）
status              VARCHAR(16) NOT NULL CHECK IN ('compiled','superseded','withdrawn')
compiled_at         TIMESTAMPTZ NOT NULL DEFAULT now()
compiled_by         VARCHAR(64) NOT NULL            -- 触发者（发布/手工）
compiler_version    VARCHAR(16) NOT NULL            -- Compiler 实现版本（可复现）
intent_signature    JSONB NOT NULL                  -- 编译时快照（entry_point/business_objective/domain）
validation_contract JSONB NOT NULL DEFAULT '{}'     -- 输入要求/缺失数据容忍度
output_contract     JSONB                           -- 冗余快照（与 3.7 表对应，便于 Planner 单表读取）
UNIQUE (tenant_id, source_model_id, source_model_version, version)
```

**引用而非复制原则（P2）**：`source_model_id + source_model_version` 是**引用键**；Blueprint 内不存业务规则文本，只存指向源模型元素的引用（见 3.4）。任何业务逻辑变更 → 源模型改 → 重新编译。

## 3.3 blueprint_intents（意图签名，多值）

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

## 3.4 blueprint_steps（步骤蓝图，核心表）

```
step_id             VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
step_seq            INT NOT NULL                   -- 顺序（非执行序，执行序由 deps 决定）
step_type           VARCHAR(16) NOT NULL CHECK IN
                    ('knowledge_query','data_fetch','capability_call','decision_branch','output')
step_name           VARCHAR(128) NOT NULL

-- 引用源模型元素（防双维护核心：引用不复制）
source_ref_type     VARCHAR(16) NOT NULL           -- node | relation | rule | data_requirement
source_ref_id       VARCHAR(64) NOT NULL           -- 源模型元素 id（跨模型域）
source_ref_path     TEXT NOT NULL                  -- 语义路径（如 causal:{model_id}:node:{node_id}）

-- 步骤参数（编译时的投影，非新业务逻辑）
params              JSONB NOT NULL DEFAULT '{}'    -- 如 data_requirement 的时间窗/聚合（来自源）
output_field        VARCHAR(128)                   -- 本步输出字段（供后续步引用）
```

**防双维护落地**：`step_type` 只能是上述五类（知识查询/取数/能力调用/决策分支/输出），**没有**"自定义业务规则"类型；`source_ref_path` 强制指向源模型元素——编译器校验该引用在源模型中真实存在（P5 完整性校验）。

## 3.5 blueprint_step_deps（步骤依赖）

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

## 3.6 blueprint_capability_reqs（能力需求）

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

## 3.7 blueprint_output_contracts（输出契约）

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
  ⑦ 落库：blueprints + 子表（同一事务）
  ⑧ 发布事件：earp.ecmc.blueprint.compiled（Planner 侧缓存失效通知）
```

**编译失败处理**：校验失败 → 不产出 Blueprint，源模型仍可 published（标注 "编译失败" 告警，通知 owner）——编译是独立产物，不阻断模型发布（模型可被 Discovery 查到，但 Blueprint 不可用 → Planner 走运行时推理降级路径）。

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

# 六、与既有契约的对接

| 既有契约 | 对接点 |
|---|---|
| §4.4.2 Model Discovery | blueprint_intents 是 Discovery 的索引；命中 Blueprint 优先于裸模型 |
| §4.4.4 Capability Dependency | blueprint_capability_reqs 编译自该契约，Planner 按它解析能力 |
| §3.6 防双维护 | step_type 五类枚举 + source_ref_path 强制引用 + 编译完整性校验 |
| §3.4.3 版本原则 | Blueprint 随源模型版本不可变；superseded 不删旧版本 |
| §3.5 反馈闭环 | reasoning_trace_id ↔ blueprint_id 关联，绩效统计可下钻到 Blueprint |
| Concept Model | 新增概念对象：PlanningBlueprint |

---

# 七、API 草案（L3 接口，语义对应 §4.4 契约）

```
GET    /v1/ecmc/blueprints?intent=...&objective=...&domain=...   — Discovery（匹配 Blueprint）
GET    /v1/ecmc/blueprints/{id}/versions/{ver}                    — 加载完整 Blueprint
POST   /v1/ecmc/blueprints/{id}/compile                            — 手工重新编译
GET    /v1/ecmc/blueprints/{id}/versions                          — 版本列表
POST   /v1/ecmc/blueprints/{id}/withdraw                           — 下线（走审批）
```

（传输层 HTTP 为参考实现，gRPC/内存/EventBus 由 Runtime 集成层决定——L2 §4.4 原则。）

---

# 八、开放问题（下一轮评审）

1. **步骤粒度**：Blueprint step 与源模型 node 是 1:1 还是可聚合/拆分？（Scenario 的 methodology_steps 可能聚合多个 node）
2. **多模型 Blueprint 组合**：一个 Blueprint 引用多个模型（如 Scenario 引用多个 Causal Model）时的引用解析与版本一致性（跨模型版本钉扎策略）
3. **性能**：Blueprint 缓存策略（Planner 侧缓存 vs 服务端缓存）、intent 匹配索引（复用 Semantic Index / pgvector）
4. **降级 SLA**：编译失败时"直接模型匹配"路径的可用性保证
