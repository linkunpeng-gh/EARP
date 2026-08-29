# Planning Blueprint — L3 实现设计

**文档编号：DESIGN-ECMC-BLUEPRINT-L3**
**版本：v0.5（draft，Freeze Patch）**
**日期：2026-08-28**

> 上游：`arch/design/2026-08-28-enterprise-cognitive-model-center-design.md`（v0.21，§3.6 Cognitive Model Compiler / §4.4 Cognitive Service Contract）、`arch/L2/02-reasoning/planner-specification.md`（v1.1）、`arch/design/2026-08-28-planner-runtime-l3-design.md`（v1.0.1，Planner Runtime）、`arch/design/2026-08-28-causal-reasoning-engine-l3-design.md`（v0.5.1，Causal Framework）
> 定位：ECMC → Planner 的执行规划表示（编译产物 / Planner IR）。本文定义 Planning Blueprint 的元模型（表结构）、Compiler 编译管线、Planner 消费流程。
> 技术栈：FastAPI + SQLAlchemy 2 async + PostgreSQL 16 + pgvector，复用 `tenant_session()` / RLS `SET LOCAL` 模式。
> v0.5 变更（Freeze Patch）：⑫ StepType Handler 版本化（P0-1）；⑬ Causal 不静态编译节点 Evidence Capability（P0-2）；⑭ source_models 钉 snapshot（P0-3）；⑮ Logical+Version 数据模型；⑯ goal_skeleton/fallback_policy Schema 补全；⑰ canonical step_type 词汇；⑱ dep 复合 FK + 多 dep_type；⑲ DAG 解耦/Plan≠Workflow；⑳ Compiler LLM 冻结；㉑ 组合来源显式化
> v0.4 变更（跨文档契约收口）：① Blueprint = 编译产物，去独立审批生命周期（P0-1）；② compile_record = 独立 Build Job（P0-2）；③ 消费流程对齐 Goal Resolution 前置（P0-3）；④ knowledge_query = Planning-time Prepare + 取证/Evaluate Tasks（P0-4）；⑤ capability 逻辑化（P0-5）；⑥ constraints 对齐 Planner Hard/Soft（P0-6）；⑦ Step Source 多模型引用 + 去双维护（P1）；⑧ Step Type 收紧（P1）；⑨ conditional eval phase（P1）；⑩ fallback policy（P1）；⑪ validator 分类型（P1）
> v0.3 变更（历史）：⑦ 规划约束 blueprint_constraints；⑧ 生命周期 draft/reviewing/approved（v0.4 废弃）；⑨ Step 多引用 blueprint_step_sources（L3.1 细化）

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
| `blueprint_capability_requirements` | 能力需求（v0.4 逻辑化：requirement_key + contract_ref，非物理 id） |
| `blueprint_constraints` | 规划约束（v0.4 对齐 Planner Hard/Soft：class + type） |
| `blueprint_output_contracts` | 输出契约（输出结构声明） |
| `blueprint_step_sources` | Step 引用（v0.4 唯一事实源：source_model_ref_id + element_key） |

## 3.2 planning_blueprints（主表，v0.5 方案 B：Logical + Version）

> **v0.5（评审 P1-1）**：统一为 Logical Blueprint + Blueprint Version
> （与 Causal Model 同构）——避免 blueprint_id/blueprint_version_id 混用：

```
planning_blueprints（逻辑）
├── blueprint_id      VARCHAR(64) PK
├── tenant_id         VARCHAR(64) NOT NULL
├── primary_model_type / primary_model_id      -- 主源模型（归属用）
├── name / description
└── created_at

planning_blueprint_versions（版本，v0.5）
├── blueprint_version_id VARCHAR(64) PK
├── blueprint_id      VARCHAR(64) NOT NULL FK
├── version           VARCHAR(32) NOT NULL   -- 独立不可变版本（source_fingerprint 驱动）
├── status            VARCHAR(16) NOT NULL CHECK IN
│                     ('compiled','superseded','withdrawn')
├── compile_record_id VARCHAR(64)            -- 关联 Build Job（§3.4）
├── compiler_version  VARCHAR(16)
├── intent_signature  JSONB NOT NULL         -- projection（权威在 blueprint_intents）
├── validation_contract JSONB NOT NULL DEFAULT '{}'  -- v0.5 收缩：仅输入合法性（见下）
├── output_contract   JSONB                  -- projection（权威在 blueprint_output_contracts）
├── fallback_policy   VARCHAR(16) NOT NULL DEFAULT 'allowed'
│                     CHECK IN ('allowed','restricted','forbidden')
│                     -- v0.5 P1-3：来源 = Source Model/Policy 编译，
│                     -- 不允许人工在 Blueprint 修改
└── UNIQUE (blueprint_id, version)

compile_record.blueprint_version_id → 指向版本行（v0.5 P1-1 闭环）
```

**validation_contract 收缩（v0.5，评审 P1-4）**：只负责 Blueprint 输入合法性——

```
required_context_fields / required_entity_bindings / allowed_scope /
  schema_version
MUST: 不表达 minimum_evidence / missing evidence tolerance（那些有权威
      契约：blueprint_constraints + Causal EvidenceRequirement）
```

**生命周期（v0.4，评审 P0-1）：**

```
Source Model（专家治理）
  draft → reviewing → approved → published
      ↓
published Source Model → Compiler → Immutable Blueprint Version
      ↓
Blueprint status：compiled → superseded（源模型更新，重编译）→ withdrawn（下线）

MUST: Blueprint 由 Compiler 从 published Source Model 编译产生，
      不经专家独立审批（审批已发生在 Source Model 层）
MUST: 修改业务逻辑 → 回源模型 → 重编译（防双维护 P2）
```

**引用而非复制原则（P2）**：源模型通过 `blueprint_source_models` 关联表引用（见 3.3）；Blueprint 内不存业务规则文本，只存指向源模型元素的引用（见 3.5）。任何业务逻辑变更 → 源模型改 → 重新编译。

## 3.3 blueprint_source_models（源模型引用表，v0.5 补 snapshot pin）

```
source_ref_id       VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
model_type          VARCHAR(16) NOT NULL CHECK IN ('causal','decision','scenario')
model_id            VARCHAR(64) NOT NULL
model_version       VARCHAR(32) NOT NULL            -- 跨模型版本钉扎
source_snapshot_id  VARCHAR(64) NOT NULL            -- v0.5 P0-3：钉住具体 Immutable Snapshot
source_content_hash VARCHAR(64) NOT NULL            -- v0.5：内容哈希
model_role          VARCHAR(16) NOT NULL CHECK IN ('primary_model','supporting_model')
```

> **v0.5（评审 P0-3）**：只钉 model_version 不够——一个版本可能有多个
> validation snapshots，生产经 published_snapshot_id 钉住实际发布内容。
> Blueprint 必须钉 `source_snapshot_id + content_hash`：
> Blueprint → 具体 Source Snapshot → 具体 Node/Rule/Requirement 完整可复现。

**多模型组合**：一个 Blueprint 可引用多个模型（如 Scenario + Causal + Decision）：

```json
{
  "scenario":  "production_analysis_v1",
  "causal":    ["production_drop_v2"],
  "decision":  ["maintenance_strategy_v1"]
}
```

**组合来源（v0.5，评审 P1-10）**：多模型组合必须来自显式知识关系——

```
MUST: 组合来源于：① Scenario Model 显式引用；② 模型依赖关系；
      ③ 预先注册的 semantic dependency；④ Compiler 确定性规则
MUST: Compiler 可以解析组合，不能创造业务组合关系（禁止 LLM 自由
      组合模型——"我觉得配 Causal A + Decision B 不错"不属于编译）
```

## 3.4 blueprint_compile_records（编译记录 = 独立 Build Job，v0.4 修 P0-2）

> **v0.4（评审 P0-2）**：编译失败时 Blueprint 不存在，但旧 Schema 的
> `blueprint_id NOT NULL FK` 要求它必须存在——结构矛盾。
> 改为独立 Build Job（成功后才关联 Blueprint）：

```
compile_id          VARCHAR(64) PK
tenant_id           VARCHAR(64) NOT NULL
primary_model_type / primary_model_id / primary_model_version
source_models_snapshot JSONB NOT NULL       -- 输入模型快照（多模型 + 版本）
source_model_hashes JSONB NOT NULL          -- 各源模型内容 hash（变更检测）
compiler_version    VARCHAR(16) NOT NULL
compiler_config     JSONB NOT NULL DEFAULT '{}'
input_snapshot      JSONB NOT NULL          -- 编译输入快照
validation_result   JSONB NOT NULL          -- 校验结果
status              VARCHAR(16) NOT NULL CHECK IN ('success','failed')
blueprint_version_id VARCHAR(64)            -- 成功 → 关联；失败 → NULL（v0.4 P0-2）
error_log           JSONB DEFAULT '[]'      -- 失败原因/告警（build log）
compile_time        TIMESTAMPTZ NOT NULL DEFAULT now()

MUST: 编译先写 compile_record（build log）→ validation success →
      才创建 Blueprint 并回填 blueprint_version_id
MUST: 编译失败 → blueprint_version_id = NULL，Blueprint 不产生
      （build log 保留用于排查）
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

## 3.6 blueprint_goal_skeletons（目标骨架，v0.5 补全 P1-2）

> **定位**：只负责 Goal Instantiation（SubGoal + skeleton + context → Runtime Goal），
> 不负责 Goal Decomposition（那是 Planner Goal Resolution，Blueprint 之前）。

```
goal_skeleton_id    VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
objective           VARCHAR(16) NOT NULL CHECK IN ('diagnose','predict','optimize','recommend')
goal_template       TEXT NOT NULL              -- Goal 模板（含变量占位）
required_bindings   JSONB NOT NULL DEFAULT '[]'  -- 必须绑定（entity/time_window）
optional_bindings   JSONB NOT NULL DEFAULT '[]'
constraint_refs     JSONB NOT NULL DEFAULT '[]'  -- 关联 blueprint_constraints
output_contract_ref VARCHAR(64)                -- 关联 blueprint_output_contracts
```

## 3.7 blueprint_steps（步骤蓝图，核心表，v0.4 去双维护）

```
step_id             VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
step_seq            INT NOT NULL                   -- 顺序（非执行序，执行序由 deps 决定）
step_type           VARCHAR(32) NOT NULL FK        -- 引用 step_type_registry
step_name           VARCHAR(128) NOT NULL
params              JSONB NOT NULL DEFAULT '{}'    -- 步骤参数（编译时投影，非新业务逻辑）
output_field        VARCHAR(128)                   -- 本步输出字段（供后续步引用）
```

**Step Source 引用（v0.4 重构，评审 P1）**：
- 主表**不再存 source_ref_id/path**（消除双维护）——全部经 `blueprint_step_sources`
- 多模型条件：source 必须关联到具体源模型（防跨模型歧义）：

```
blueprint_step_sources（唯一事实源，v0.4）
├── step_source_id   VARCHAR(64) PK
├── step_id          VARCHAR(64) NOT NULL FK
├── source_model_ref_id VARCHAR(64) NOT NULL FK → blueprint_source_models
│                     -- 明确属于哪个源模型（causal v1.7 / decision v3.1）
├── element_type     VARCHAR(16) NOT NULL  -- node | relation | rule | requirement
├── element_key      VARCHAR(64) NOT NULL  -- 源模型内稳定键（equipment_failure）
├── element_path     TEXT                 -- 展示用语义路径（非事实源）
└── role             VARCHAR(16) NOT NULL CHECK IN ('primary','supporting','optional')

MUST: 所有 Step 引用经 blueprint_step_sources（无主表冗余）
MUST: 多模型时 element_key 由 source_model_ref_id 限定（无歧义）
MUST: 引用必须指向源模型真实元素（编译器校验，防双维护 P2）
```

## 3.8 blueprint_step_deps（步骤依赖，v0.5 补 FK + 多 dep_type）

```
dep_id              VARCHAR(64) PK
blueprint_version_id VARCHAR(64) NOT NULL FK  -- v0.5：属于版本（Logical+Version）
from_step_id        VARCHAR(64) NOT NULL
from_blueprint_version_id VARCHAR(64) NOT NULL
                                    -- v0.5 P1-6：复合 FK 保证两端同版本
to_step_id          VARCHAR(64) NOT NULL
to_blueprint_version_id VARCHAR(64) NOT NULL
dep_type            VARCHAR(16) NOT NULL CHECK IN ('sequential','conditional','data_flow')
condition           JSONB                          -- dep_type=conditional 时（引用源模型 Rule）
condition_eval_phase VARCHAR(16)                   -- planning | execution
                    -- 源自源模型 DecisionRule.scope（Planner 不得自行决定）
UNIQUE (blueprint_version_id, from_step_id, to_step_id, dep_type)
                    -- v0.5：同端对可并存多种 dep（sequential + data_flow）

FOREIGN KEY (from_blueprint_version_id, from_step_id)
  REFERENCES blueprint_steps(blueprint_version_id, step_id)  -- 复合 FK（v0.5 P1-6）
FOREIGN KEY (to_blueprint_version_id, to_step_id)
  REFERENCES blueprint_steps(blueprint_version_id, step_id)
```

**约束（v0.5，评审 P1-7）**：Blueprint Step 图 Phase 1 必须为 DAG——
这是 **Planner Composition / execution planning 的约束**，与 Causal Model
是否有环无关（Causal 存储层允许环，DAG 是推理算法 Profile 约束）。

**conditional 执行边界（v0.4，评审 P1）**：
```
planning scope  → Planner 评估后选分支
Execution scope → Plan 保留 conditional edge，Runtime 到达时由
                  Decision Engine 评估（Planner 不预选）
```

## 3.9 step_type_registry（Step Type 扩展注册表，v0.5 版本化）

> **v0.5（评审 P0-1）**：StepType Handler 必须版本化——否则 Blueprint 虽不可变，
> 但解释它的 Handler 升级后 PlanFragment 会变，破坏可复现。

```
step_types（逻辑类型）：
  type_id     VARCHAR(32) PK        -- 'knowledge_query' | 'data_fetch' |
                                    -- 'capability_requirement' |
                                    -- 'decision_evaluate' | 'output'
  type_name   VARCHAR(64) NOT NULL
  is_core     BOOLEAN NOT NULL DEFAULT false

step_type_versions（版本，v0.5 P0-1）：
  step_type_version_id VARCHAR(64) PK
  type_id          VARCHAR(32) NOT NULL FK
  version          VARCHAR(32) NOT NULL
  handler_version  VARCHAR(32) NOT NULL    -- Handler 实现版本
  handler_hash     VARCHAR(64) NOT NULL    -- 实现哈希（可定位/审计）
  params_schema    JSONB NOT NULL DEFAULT '{}'
  semantic_contract_version VARCHAR(16) NOT NULL
  status           VARCHAR(16) CHECK IN ('active','deprecated')
  UNIQUE (type_id, version)

Blueprint Step 编译时 pin（v0.5）：
  step_type_version_id  → 解释语义冻结（Handler 升级不改变旧 Blueprint
    的 PlanFragment）
Compile Record / Plan Trace 记录：
  step_type_version + handler_version + handler_hash
  ——Source Model → Blueprint → Interpreter Version → PlanFragment 全链可复现
```

**canonical step_type 词汇（v0.5，评审 P1-5 统一）：**

```
Phase 1 正式五个：knowledge_query / data_fetch / capability_requirement /
  decision_evaluate / output
旧名 capability_call → capability_requirement；decision_branch →
  decision_evaluate（alias/migration，Planner Handler 名称完全一致）
```

**扩展机制（v0.2，v0.4 收紧——防 Blueprint 变成第二个 Workflow Engine）：**
```
- step_type 是扩展点，但必须守住**业务语义型**边界：
  允许扩展（业务语义型）：knowledge_query / data_fetch /
    capability_requirement / decision_evaluate / output 的细化变体
  （如 human_confirm 若表达"业务知识要求专家确认"可作为 business
    confirmation requirement；审批流程/等待/超时归 Policy/Workflow）
  禁止扩展（执行编排型，评审 P1）：parallel_group / retry /
    approval_execution / external_agent_call 等——并发/重试/编排
    是 Workflow / Resource 层职责，Blueprint 不承载
- 新类型 = 注册表新行 + Handler 实现（两步），不改 Blueprint 表结构
- 约束：
  MUST: 新类型必须是业务语义扩展，不是执行编排载体（业务规则永远
        回源模型 P2；并发/重试永远归 Workflow/Resource）
  MUST: 新类型需 Handler 实现并经测试；未注册类型编译期拒绝
  MUST: 内置五类 is_core=true 不可删除；扩展类型可 deprecated
```

## 3.10 blueprint_capability_requirements（能力需求，v0.4 逻辑化 P0-5）

> **v0.4（评审 P0-5）**：不绑物理 capability_id——Blueprint 是逻辑需求，
> 物理解析由 Planner/Capability Resolver 在运行时完成（跨租户/行业复用）。

```
cap_req_id          VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
requirement_key     VARCHAR(128) NOT NULL       -- 逻辑需求键（equipment_health_query）
capability_contract_ref VARCHAR(128) NOT NULL  -- 逻辑 Capability Contract（非物理实例）
required            BOOLEAN NOT NULL DEFAULT true
purpose             TEXT NOT NULL              -- 对应哪个步骤/节点
input_contract      JSONB NOT NULL DEFAULT '{}'
output_contract     JSONB NOT NULL DEFAULT '{}'
```

```
MUST: Compiler 只校验 Capability Contract 是否存在、语义合法
      （不检查当前 Provider 是否 active——那是运行时 readiness）
MUST: 物理 capability/provider 解析由 Planner + Capability Resolver
      运行时完成（ResolvedCapabilityRequirement.binding_status）
MUST: 不新增能力需求（防双维护——编译自源模型 Capability Binding）
```

## 3.11 blueprint_constraints（规划约束，v0.4 与 Planner Hard/Soft 统一 P0-6）

> **v0.4（评审 P0-6）**：直接复用 Planner v1.0 的 Hard/Soft 契约，
> 不发明第二套——Blueprint Constraint → Planner Constraint Merge 零转换。

```
constraint_id       VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
constraint_class    VARCHAR(16) NOT NULL CHECK IN ('hard','soft')
constraint_type     VARCHAR(32) NOT NULL CHECK IN
                    ('mandatory_check','prohibition','mandatory_capability',
                     'minimum_evidence','compliance_rule',    -- hard
                     'priority','scheduling_weight','cost_vs_speed',
                     'explain_level','recommendation_count')  -- soft
constraint_value    JSONB NOT NULL
source_ref          TEXT                       -- 来源（源模型哪个元素/规则）
rationale           TEXT                       -- 为什么（业务理由，供 Planner/审计）
```

**语义边界（关键，v0.4）：**

```
MUST: 安全不可违反 → constraint_class='hard' + type=mandatory_check /
      prohibition / compliance_rule——不能只靠 priority 排序表达
      （priority 归 soft，仅影响调度偏好）
MUST: 不引入新业务规则（防双维护 P2 的规划侧延伸）
MUST: 与 Planner v1.0 约束合并链兼容：Policy/Compliance → Blueprint
      Hard → User（只能收紧）→ Blueprint Soft → Planner 偏好
SHOULD: 约束可被 Planner 消费并在 Plan 中体现（mandatory → 规划失败/
      缺失降级；soft priority → 排序）
```

示例：
```
设备诊断 Blueprint:
  hard: { mandatory_check: safety_check, minimum_evidence: 2,
          mandatory_capability: equipment_health_query }
  soft: { priority: cost_vs_speed, explain_level: detailed }
```

## 3.12 blueprint_output_contracts（输出契约）

```
output_id           VARCHAR(64) PK
blueprint_id        VARCHAR(64) NOT NULL FK
output_type         VARCHAR(16) NOT NULL CHECK IN
                    ('cause_ranking','report','recommendation','workflow')
output_schema       JSONB NOT NULL                 -- 输出结构（字段/嵌套/必填）
```

**用途**：Planner 生成 Plan 时声明输出目标；Agent 据此格式化结果。

---

# 四、Compiler 编译管线（v0.4 分类型 validator）

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
     - Causal   → intent_signature + goal_skeleton + knowledge_query step
                  + source model ref + output contract（v0.4 P0-4：
                  生成 knowledge_query step 供 Planner 进入 Causal
                  Reasoning Prepare；不预编译路径/证据能力）
  ④ 引用解析（reference_resolver）：每步经 blueprint_step_sources
     （source_model_ref_id + element_key）→ 校验源模型元素存在（P5）
  ⑤ 能力需求编译（v0.5 P0-2 按模型类型区分）：
     - Scenario Model → 编译静态 Capability Requirements（方法论固定）
     - Decision Model → 编译明确要求的 Capability Requirements
     - Causal Model → 不编译节点级 Evidence Capability（动态证据需求
       由 Reasoning Prepare 运行时产生——按 target/window/instance/algorithm
       Profile 确定实际需要的证据）；仅当存在模型级 Hard Requirement
       （无论分析哪个子图都必须具备的能力）才进 blueprint_capability_
       requirements
  ⑥ 完整性校验（validator，v0.4 P1 按模型类型）：
     - Scenario Validator → methodology coverage（步骤覆盖方法论）
     - Decision Validator → rule/decision coverage
     - Causal Validator → model ref + entrypoint + contract validity
       （不要求全部节点被引用——Causal 路径运行时由 Prepare 决定）
     - 能力 contract 可解析（Capability Contract 存在，非 Provider active）
     - 步骤图 DAG 无环
     - 防双维护检查（无自定义规则类型 / 无孤儿业务逻辑）
  ⑦ 写入 compile_record（Build Job，v0.4 P0-2）：先写 build log →
     validation success → 才创建 Blueprint（blueprint_version_id 回填）
  ⑧ 落库：blueprints + 子表（同一事务，compile_record.status=success 才落）
  ⑨ 发布事件：earp.ecmc.blueprint.compiled（Planner 侧缓存失效通知）
```

**编译失败处理**：校验失败 → compile_record 记 failed + error_log（build log 保留，
blueprint_version_id=NULL），不产出 Blueprint；源模型仍可 published（标注
"编译失败"告警，通知 owner）——编译是独立产物，不阻断模型发布。

**Fallback Policy（v0.4，评审 P1）**：是否允许降级由业务风险/Policy 决定——

```
blueprint.fallback_policy：allowed | restricted | forbidden
  诊断分析类（allowed）→ 编译失败可 direct model reasoning
  安全决策/设备控制/生产执行（forbidden）→ 缺方法论时 FAIL CLOSED
MUST: 任何降级继承 Hard Constraints（同 Planner v1.0）
```

**Compiler 可复现（v0.5，评审 P1-9）**：

```
Phase 1 尽量确定性规则编译；若内部使用 LLM（如 Scenario 步骤结构化
辅助），compiler_config 必须冻结：provider / model / prompt_version /
  temperature / seed（若支持）/ structured_output_schema_version
MUST: 同 source hash + 同 compiler_version + 同 config → 同 Blueprint
MUST: LLM 只做候选建议，不成为不可复现的业务逻辑生成器
```

---

# 五、Planner 消费流程（v0.4 对齐 Planner Runtime v1.0）

```
① Goal Resolution / Decomposition（v0.4 P0-3，Blueprint Discovery 之前）：
   Request → Intent → 1..N SubGoal（先定"要解决几个问题"）
② 每个 SubGoal 独立 Discovery（Model Discovery §4.4.2）：
   命中 compiled Blueprint（或直接命中模型）
③ Blueprint 加载（只读）：
   intents / steps / deps / capability_requirements / constraints /
   output_contract
④ Goal Instantiation（v0.4 P0-3，与 Resolution 区分）：
   SubGoal + Blueprint goal_skeleton + entity/time/context
   → Runtime Goal（goal_skeleton 不负责"用户有几个目标"，
     只负责"这个 SubGoal 如何实例化"）
⑤ PlanFragment 生成（StepType Handler）：
   steps + deps → PlanFragment（0..N Tasks + Edges + Constraints）
   knowledge_query 步 →（v0.4 P0-4）Planning-time 调用 Causal
     Reasoning Prepare → Evidence Requirements → Handler 产出
     PlanFragment = 0..N 取证 Task + 1 reasoning_evaluate Task
   data_fetch 步 → 按引用 data_requirement 生成取数 Step
   capability_requirement 步 → 经 Capability Resolver 解析物理
     capability（逻辑 contract → 当前租户 provider，v0.4 P0-5）
   decision_evaluate 步 → 按 condition_eval_phase（planning 由
     Planner 评估；execution 由 Decision Engine 运行时评估）
   output 步 → 按 output_contract 声明输出目标
⑥ Execution Trace 记录：
   blueprint_id + version + compile_id 记入 trace（可复现性，P5）
```

**降级路径（v0.4 修正）**：是否允许降级由 fallback_policy/Policy 决定
（§四）——不是统一允许；任何降级继承 Hard Constraints（Planner v1.0）。

---

# 六、Blueprint Runtime Semantics（执行语义，v0.4 对齐 Step→Fragment）

> **定位**：Blueprint 描述"要做什么"（业务方法），Planner/Runtime 解释时
> 需要明确的执行语义——不是 Workflow 编排（P6），而是 Blueprint 步骤的
> 解释规则。

## 6.1 Step 生命周期（v0.4 统一 Step → Fragment）

```
Blueprint Step（静态定义）
  → StepType Handler（确定性解释）
  → Planning Fragment（0..N Tasks + Edges + Constraints）
  → Execution 执行（Runtime 负责）
  → 结果回填（output_field）
```

## 6.2 Step 执行语义（语义级，非编排细节）

```
同步性（由 Handler 声明，step_type_registry 注册）：
  capability_requirement: 默认同步；handler 声明 async 时 Planner 可并行调度
数据流（deps.data_flow）：
  后续步可引用前步 output_field；缺失字段时 Planner 报规划错误（不静默）
失败语义（v0.2 定义，防"静默假成功"）：
  MUST: 步骤失败 → Plan 标记对应步骤 failed，不伪造成功
  MUST: required 取证失败 → Evaluate 标注 missing_required（Causal 语义）
  SHOULD: 非关键步失败可标记 degraded（Blueprint 允许降级的能力）
条件分支（deps.conditional，v0.4）：
  条件引用源模型 Rule（不是新规则）；condition_eval_phase 决定：
    planning → Planner 评估后选分支
    execution → Plan 保留 conditional edge，Runtime 到达时由
      Decision Engine 评估（Planner 不预选）
knowledge_query（v0.4 P0-4）：
  Planning-time 调用 Causal Reasoning Prepare → Evidence Requirements
  → 取证 Tasks + Evaluate Task（运行时推理，不预编译路径）
```

## 6.3 与 Workflow 的边界（P6 落地，v0.5 修正 P1-8）

```
Blueprint 不定义：重试次数 / 超时 / 并发度 / 具体端点 / 重试退避
  ——这些是 Workflow / Resource Spec 的执行编排细节
Blueprint 定义：步骤顺序（业务方法）/ 数据依赖 / 条件分支（业务规则）
  ——业务方法层

实现（v0.5）：Planner 将 Blueprint 投影为 Plan/Task（PlanFragment →
  Plan）；执行形态由任务决定——直接 Runtime Task / Workflow 编排 /
  Scheduler / 人工审批 / 事件驱动执行，由 Execution/Workflow 层承载
  执行细节（Plan ≠ Workflow，不绑死）
```

---

# 七、与既有契约的对接

| 既有契约 | 对接点 |
|---|---|
| §4.4.2 Model Discovery | blueprint_intents 是 Discovery 的索引；命中 Blueprint 优先于裸模型 |
| §4.4.4 Capability Dependency | blueprint_capability_requirements 编译自该契约（逻辑 contract）；Planner + Capability Resolver 运行时解析物理能力 |
| §3.6 防双维护 | step_type 业务语义收紧 + blueprint_step_sources 强制引用 + 编译完整性校验 |
| §3.4.3 版本原则 | Blueprint 随源模型版本不可变；superseded 不删旧版本 |
| §3.5 反馈闭环 | reasoning_trace_id ↔ blueprint_id 关联，绩效统计可下钻到 Blueprint |
| **Planner Runtime v1.0.1（v0.4 新增）** | Goal Resolution 前置 → per-SubGoal Discovery → Blueprint → StepType Handler → PlanFragment（knowledge_query → Prepare + 取证/Evaluate Tasks）；constraints/conditional eval phase/fallback policy 对齐 |
| **Causal Framework v0.5.1（v0.4 新增）** | knowledge_query step → Planning-time Reasoning Prepare → Evidence Requirements → 取证 Tasks + Evaluate Task（消费 prepare_id，不预编译路径） |
| Agent Trace（v0.2） | Execution Trace 记录 blueprint_id + version + step 级引用（每步 source_model_ref_id + element_key）——可回溯到"哪个 Blueprint 哪步"再到"源模型哪个元素"（P5 三方追溯） |
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

# 九、开放问题（v0.5 更新，实现期/Phase 2）

1. **步骤粒度**：v0.4 已用 blueprint_step_sources（唯一事实源）支持 Step 多引用；Node→多 Step 的生成规则 L3.1 细化
2. **多模型组合冲突**：同一节点被两模型引用语义不一致的检测 L3.1 细化
3. **性能**：Blueprint 缓存策略、intent 匹配索引（Semantic Index / pgvector）
4. **降级 SLA**：fallback_policy=allowed 时"直接模型匹配"路径的可用性保证
5. **Step Type 扩展治理**：业务语义型扩展（human_confirm/simulation）的 Handler 测试标准与 Planner 适配
6. **knowledge_query Handler 细化**：Reasoning Prepare 集成（Evidence Requirements → 取证/Evaluate Tasks）的具体编排——与 Causal Framework 对接实现
7. **StepType 版本迁移**：canonical 词汇（capability_requirement/decision_evaluate）对旧 Blueprint 的 alias/migration 策略

---

# 十、v0.4 跨文档契约收口记录（v0.3 → v0.4）

**背景**：Blueprint v0.3 停在 Planner Runtime v1.0 和 Causal Framework 收口之前，存在版本漂移。v0.4 只做跨文档收口（删错误职责、统一契约），不加新功能。

| 级别 | 评审意见 | 处置 |
|---|---|---|
| P0-1 | Blueprint 独立 draft/reviewing/approved 生命周期与"编译产物"冲突（双维护风险） | §3.2：Blueprint = Compiled Artifact / Planner IR；治理生命周期归 Source Model（专家审批认知模型，不是 Compiler 输出）；Blueprint 仅 compiled/superseded/withdrawn |
| P0-2 | compile_record.blueprint_id NOT NULL FK 与"失败无 Blueprint"矛盾 | §3.4：compile_record = 独立 Build Job（primary_model refs + 输入快照 + status）；成功才创建 Blueprint 并回填 blueprint_version_id；失败 → NULL |
| P0-3 | Planner 消费流程未对齐 Goal Resolution 前置 | §五：Goal Resolution → per-SubGoal Discovery → Blueprint → Goal Instantiation（与 Resolution 区分）→ StepType Handler → PlanFragment |
| P0-4 | knowledge_query = 运行时调 Causal Reasoning 已过时 | §五/§六：knowledge_query = Planning-time Reasoning Prepare → Evidence Requirements → 0..N 取证 Task + 1 Evaluate Task（Causal Framework v0.5.1 咬合） |
| P0-5 | capability 绑物理 capability_id（跨租户失效） | §3.9：blueprint_capability_requirements（requirement_key + capability_contract_ref 逻辑化）；Compiler 只校验 Contract 存在；物理解析由 Planner/Capability Resolver 运行时完成 |
| P0-6 | constraints 未对齐 Planner Hard/Soft | §3.10：constraint_class（hard/soft）+ type（mandatory_check/prohibition/mandatory_capability/minimum_evidence/compliance_rule | priority/scheduling_weight/cost_vs_speed/explain_level）；安全必须 hard 表达，不靠 priority |
| P1 | Step Source 多模型歧义 + 双维护 | §3.6：blueprint_step_sources 唯一事实源（source_model_ref_id + element_type + element_key）；主表去 source_ref_*；多模型由 ref 限定 |
| P1 | Step Type 有 Workflow 化风险 | §3.8：收紧——禁 parallel_group/retry/approval_execution/external_agent_call（编排归 Workflow/Resource）；只允许业务语义型扩展 |
| P1 | conditional 执行边界过时 | §3.7/§六：condition_eval_phase（planning/execution 源自 DecisionRule.scope）——execution 分支由 Decision Engine 运行时评估 |
| P1 | Fallback 统一允许过绝对 | §四：fallback_policy（allowed/restricted/forbidden）+ Policy 决定；任何降级继承 Hard Constraints（FAIL CLOSED 于安全场景） |
| P1 | Validator 需按模型类型 | §四：Scenario/Decision/Causal 分类型 validator（Causal 不要求全节点引用——路径运行时由 Prepare 决定） |
| P2 | 唯一键/version/JSON projection | §3.2：UNIQUE 加 primary_model_type；version 由 source_fingerprint 驱动；intent_signature/output_contract 标注为 projection（权威在子表） |

---

# 十一、v0.5 Freeze Patch 处置记录（v0.4 → v0.5）

| 级别 | 评审意见 | 处置 |
|---|---|---|
| P0-1 | StepType Handler 未版本化（Blueprint 不可变但解释语义会变，破坏可复现） | §3.9：step_types + step_type_versions（version/handler_version/handler_hash/params_schema/semantic_contract_version）；Blueprint Step 编译时 pin step_type_version_id；Compile Record/Plan Trace 记录 handler 版本 |
| P0-2 | Causal Compiler 提前把全部节点 Evidence Capability 编进 Blueprint（破坏 Prepare 价值） | §四⑤：按模型类型——Scenario/Decision 编译静态 Capability；Causal 不编译节点级（动态证据由 Reasoning Prepare 运行时产生）；仅模型级 Hard Requirement 进 Blueprint |
| P0-3 | source_models 只钉 model_version（一个版本多 snapshot，生产 pin published_snapshot_id） | §3.3：补 source_snapshot_id + source_content_hash——Blueprint → 具体 Snapshot → 具体元素完整可复现 |
| P1-1 | blueprint_id/blueprint_version_id 概念混用 | §3.2：方案 B（Logical Blueprint + Blueprint Version，与 Causal 同构）；compile_record.blueprint_version_id 指向版本行 |
| P1-2 | goal_skeleton 无 Schema | §3.6：blueprint_goal_skeletons（objective/goal_template/required_bindings/optional_bindings/constraint_refs/output_contract_ref）；明确只负责 Instantiation 不负责 Decomposition |
| P1-3 | fallback_policy 被使用但 Schema 无字段 | §3.2：fallback_policy 字段（allowed/restricted/forbidden），来源 = Source Model/Policy 编译，禁人工修改 |
| P1-4 | validation_contract 模糊（与 minimum_evidence/required 重复） | §3.2：收缩为输入合法性（required_context_fields/required_entity_bindings/allowed_scope/schema_version）——不表达证据相关（有权威契约） |
| P1-5 | step_type 名称不统一 | §3.9：canonical 五类（knowledge_query/data_fetch/capability_requirement/decision_evaluate/output）；旧名 alias/migration |
| P1-6 | dep 唯一键过严（A→B 只能一种关系）+ 无真实 FK | §3.8：UNIQUE 加 dep_type；复合 FK（blueprint_version_id, step_id）保证两端同版本 |
| P1-7 | "同 Causal DAG 原则"表述过时 | §3.8：Blueprint Step 图 DAG 是 Planner 编排约束，与 Causal 是否有环无关 |
| P1-8 | "投影为 Workflow"绑死 Plan=Workflow | §6.3：投影为 Plan/Task；执行形态由任务决定（Runtime/Workflow/Scheduler/审批/事件），不绑死 |
| P1-9 | Compiler 用 LLM 时不可复现 | §四：compiler_config 冻结（provider/model/prompt_version/temperature/seed/schema_version）；LLM 只做候选建议 |
| P1-10 | 多模型组合可由 Compiler/LLM 自由创造 | §3.3：组合必须来自显式知识关系（Scenario 引用/模型依赖/semantic dependency/确定性规则）；Compiler 解析不创造 |
