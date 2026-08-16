# 任务清单 — Phase B: Query Understanding 理解层

**状态：规划定稿，待开工**
**依据**：`arch/design/query-understanding-query-plan-design-v0.3.md`（§5 QU 设计 / §6 schema 冻结 / §7 derive_needs / §16 Phase B / §17 评估门槛）
**关联**：session-record「下一步：Phase B（QU 理解层）——TBox 缺口已解除，随时可开工（3-5 天）」
**日期**：2026-08-16

## 目标

独立建设 **Query Understanding 理解层**（规则优先 + LLM 低置信度升级）：
- 产出 **Structured Query**（§6.2 schema 冻结落地，Pydantic）+ **derive_needs()** 纯函数（§7）
- 不依赖检索通道，可独立评估（§17 Understanding 层门槛）
- 一期可靠分类子集 `{FACT, RELATION, AGGREGATION}`；其余 7 类显式回落（QP-14），不做关键词分类

**范围边界**（本任务书**不含**，各阶段门槛独立）：
- `select_plan` / `plan_fact` / `plan_relation` / `plan_aggregation` 策略函数 → **Phase C**（§16，后置到 Phase A 度量出真实疼点后）
- `resolve_with_query()`（§6.5 新签名）→ **Phase D1**（`resolve_with_entities` 签名不变，继续服务 `/plan` M2 收窄路径）
- 角色层 Evidence 组装（§9.2）→ **Phase D3**
- rerank 精排接入 → **Phase E**（= roadmap P3）
- 无 DB migration（零新表；评估集为 markdown fixture）

## 既定决策（讨论已对齐，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | 模块落点 | 新建 `src/earp_server/ontology/understanding.py`（schema + 规则层 + derive_needs 同文件）。理由：QU 是 ontology 三层检索的语义前置层，消费 TBox（relation_types）/ entities（lookup）/ routing 关键词；ontology **不在** import-linter independence 域列表 → import knowledge.routing / connector 无新增 ignore（search.py import knowledge.search_service、chat_service import connector 均为既有先例） |
| D2 | 规则层素材（已核实无 business_dictionary 表） | 词典 = `knowledge/routing.py::_DATA_DOMAIN_KEYWORDS`（D-13 已从 planner/business_dictionary 迁入，DD 词条即业务词典）+ entities 表名索引（`lookup_entities` 双向子串匹配，2026-08-16 已修反向）；relation 候选 = `relation_types` 表**动态供给**（`tbox_service.list_relation_types`，不硬编码在 prompt/code） |
| D3 | intent 关键词表 | 新建 `_INTENT_KEYWORDS`（understanding.py 内，与 `_DATA_DOMAIN_KEYWORDS` 分离——后者是 DD 路由维度，前者是问题类型维度，不混用）。只对可靠子集 {FACT, RELATION, AGGREGATION} 设关键词；其余 7 类不建关键词，显式回落并写 reason（QP-14） |
| D4 | LLM 升级 | **方案 A（2026-08-16 讨论定稿）**：新增 `LLMConnector.json_complete(system, prompt, *, model_override, temperature=0.3) -> dict`——**无 DB 依赖**（model_override 参数化，保持 connector 架构红线，同 `resolve_llm_override` 分层先例）；`main.py::_llm_suggest` **保留为薄封装**（DB 解析 + 调 json_complete + 抽 description，签名/响应不变，两处调用点零改动）；QU 升级走**全局默认 LLM**（`load_runtime_models`，与 suggest 一致；Phase C 有需求再 per-app 可配）；只补「未命中字段」不重做已命中字段（§6.1）；LLM 输出必须过 schema 校验 + relation ∈ TBox 过滤，非法回落规则结果 |
| D5 | 置信度 | §6.4 机械计算：`confidence = max(0, min(1, rule_coverage − 0.2 × 多候选字段数))`；阈值默认 0.7（settings 可配：`EARP_QU_CONFIDENCE_THRESHOLD`）；confidence 由代码计算，**不靠 LLM 自报** |
| D6 | 评估集 | `tests/fixtures/understanding_eval.md`（N ≥ 100 标注查询，格式仿 routing_eval.md 扩展列）；pytest runner 机制层验证（不真调 LLM）；`scripts/verify_understanding.py` dev 真模型+真 LLM 验证（§17 数字门槛） |
| D7 | debug 端点 | **方案 A（2026-08-16 讨论定稿）**：后端 `POST /v1/ontology/understanding/debug`（复用 route_debug「分层可解释」模式，§15）：输入 query + 可选 context → StructuredQuery（含各字段命中明细 + confidence 分项 + 是否 LLM 升级）+ derive_needs() 结果；**+ 前端最小调试视图一期做**（标注为调试工具，供 FDE 人工验证规则层语义质量；Phase C 全链路视图为叠加扩展，非重写） |
| D8 | 会话上下文 | §5.2 一期只做「提及 → 上文实体映射」：规则层简单指代（它/这个/该设备/这台机器 → context.last_entities[0] 的 semantic_type）；复杂指代消解（跨句省略主语等）一期不做，记 tech-debt |
| D9 | 时间解析边界 | 规则层只提取 `expression` + `kind`（relative/absolute），`resolved_start/resolved_end` 由运行时回填（§5.5）——不让规则/LLM 猜日期 |

## 现状（已核实）

- `ontology/search.py`：`_entity_hits`（tokenize + `lookup_entities`）、`knowledge_search`（三层 RRF）、`resolve_with_entities`（capability 反查，**签名不改**）
- `ontology/abox_service.py`：`lookup_entities`（双向子串匹配，2026-08-16 修复纯中文长查询）、`graph_query`（forward/backward）、`compile_profile` / `get_entity_profile`
- `ontology/tbox_service.py`：`SEED_RELATION_TYPES`（12 类，2026-08-15 方案 A 后 belongs_to/supplied_by 源扩 component）、`list_relation_types(source_type=)`、`find_capabilities_by_entity_type`
- `knowledge/routing.py`：`_DATA_DOMAIN_KEYWORDS`（DD 路由关键词，业务词条）、`match_data_domains()`
- `connector.py`：`LLMConnector.plan()`（Ollama JSON mode + cache + RuleIntentPlanner fallback）、`chat_stream()`；**无通用 JSON 单发 helper**（`_llm_suggest` 在 main.py，DB 模型优先，已被 data-domains suggest-description + KB suggest-summary 两处使用）
- import-linter：ontology 不在 independence 域列表 → 自由 import knowledge/connector；**注意**：若 Phase C 让 `chat_service → understanding`，会构成 `conversation→ontology.understanding→knowledge.routing` 传递违反（conversation/knowledge 均 independence 域），届时需按 P2 先例加 ignore——本任务书不触碰
- 当前基线：102 tests 全绿 + import-linter + OpenAPI 基线同步

---

## Phase B1 — schema + 规则层

### Task 1 — Structured Query schema 冻结落地（前置）

**文件**：`src/earp_server/ontology/understanding.py`（新建）

**改动点**：§6.2 Pydantic 模型**逐字落地**（字段/枚举与设计一致，不得擅自增减）：
```python
class Intent(str, Enum): ...            # FACT/ATTRIBUTE/RELATION/MULTI_HOP/LIST/AGGREGATION/COMPARISON/TREND/CAUSAL/MIXED
class TimeConstraint(BaseModel): ...    # kind: Literal["absolute","relative","none"]; expression; resolved_start/end
class EntityMention(BaseModel): ...     # mention, semantic_type, role(subject/target/intermediate/scope)
class RelationMention(BaseModel): ...   # subject, relation, object_type, object_mention
class Operation(BaseModel): ...         # aggregate/group_by/order_by/limit/compare_subjects
class AnswerRequirement(BaseModel): ... # answer_type Literal["summary"]="summary"; evidence_required; citation_required
class StructuredQuery(BaseModel): ...   # context/entities/relations/intent/constraints/time/operation/answer_requirement/confidence
```
- `_INTENT_KEYWORDS`（D3）：可靠子集关键词表（如「是什么/是什么/定义/含义/包括」→ FACT；「谁/哪个/哪家/由谁/供应商/负责人」→ RELATION；「多少/数量/统计/总计/最多/最少/平均」→ AGGREGATION），保守设计——宁可回落也不误判（风险 #5）
- schema 校验函数 `validate_relation_sources()`：relation ∈ relation_types 表（动态查表，D2）；非法 → 回落

### Task 2 — 规则层：时间/数字提取

**文件**：`src/earp_server/ontology/understanding.py`

**改动点**：
- 正则提取时间（「昨天/最近三个月/2024 年/2024-03」→ `TimeConstraint{kind, expression}`；`resolved_*` 留空待运行时回填，D9）
- 正则提取结构化数字/枚举约束（「2024 年」→ `constraints["year"]`；「财务部」等 → 交由实体/词典维度，不重复识别）
- `constraints` 与 `time` 分开建模（§5.5，类型安全优先于字段合并）

### Task 3 — 规则层：实体提及识别

**文件**：`src/earp_server/ontology/understanding.py`

**改动点**：
- 复用/增强 `ontology/search.py::_entity_hits` 逻辑：tokenize + `lookup_entities`（双向子串，已修反向）→ 命中实体 → `EntityMention{mention, semantic_type=entity_type_id}`
- 词典维度：`_DATA_DOMAIN_KEYWORDS` 词条（业务术语）作为词典补充（D2）——仅当与实体名索引合并命中时产出 semantic_type，纯词条命中不产 mention（避免把「设备」这种泛词当实体）
- 指代消解（D8）：query 含 它/这个/该设备/这台机器 且 `context.last_entities` 非空 → 映射上文实体 semantic_type
- `role` 标注：`谁/哪个/哪家` 后置成分 → target；其余默认 subject（一期只可靠标注，不确定留 None）

### Task 4 — 规则层：intent 分类

**文件**：`src/earp_server/ontology/understanding.py`

**改动点**：
- `_INTENT_KEYWORDS`（Task 1 定义）关键词匹配 → intent ∈ {FACT, RELATION, AGGREGATION}
- 多候选 → 计入 ambiguity_penalty（§6.4）；无候选 → intent=None（进入 LLM 升级判定或回落）
- 其余 7 类（ATTRIBUTE/MULTI_HOP/LIST/COMPARISON/TREND/CAUSAL/MIXED）**不建关键词**——显式回落，`intent` 留 None + trace 标注「未分类，Phase C 回落策略」（QP-14，不静默当 FACT）

### Task 5 — 规则层：relation 提取

**文件**：`src/earp_server/ontology/understanding.py`

**改动点**：
- relation 候选集 = `tbox_service.list_relation_types()` 动态拉取（D2，不硬编码）
- 动词词典（understanding.py 内常量）：「谁生产/由谁制造」→ manufactured_by、「谁负责」→ responsible_for、「位于/在哪个」→ located_in、「属于/哪个设备」→ belongs_to、「谁供应」→ supplied_by 等（映射到 relation_type_id）
- 模式：实体命中 + 动词命中 → `RelationMention{subject=实体mention, relation, object_type=候选关系 target_type}`；方向校验：subject 实体类型 ∈ 该 relation 的 source_type 集合（relation_types 表有 source_type/target_type）
- 一期只识别单跳「实体 + 动词 → relation」；多跳（MULTI_HOP）一期不识别（回落）

### Task 6 — 置信度计算 + 升级判定（§6.4）

**文件**：`src/earp_server/ontology/understanding.py`

**改动点**：
- `rule_coverage = 命中字段数 / 应提取字段数`（字段：时间、实体、关系、intent、约束、operation——按 query 实际相关度判定应提取集）
- `ambiguity_penalty = 0.2 × 多候选字段数`（intent 多候选 / 实体多歧义 / relation 多候选）
- `confidence = max(0, min(1, rule_coverage − ambiguity_penalty))`（机械计算，D5）
- `confidence ≥ threshold(0.7)` → 直接产出 Structured Query（零 LLM）；`< 0.7` → 标记 `needs_llm=True` + **未命中字段清单**（供 Task 7 只补缺失字段）
- 输出带各字段命中/未命中明细（供 debug 端点 + 评估集溯源）

---

## Phase B2 — LLM 升级 + derive_needs

### Task 7 — LLM 低置信度升级（`json_complete` 抽取，决策 D4 方案 A）

**文件**：`src/earp_server/connector.py`（新方法）+ `src/earp_server/main.py`（`_llm_suggest` 改薄封装）+ `src/earp_server/ontology/understanding.py`

**改动点**：
1. **新增**：`connector.py::LLMConnector.json_complete(system, user_prompt, *, model_override=None, temperature=0.3, timeout=120) -> dict | None`——ollama `/api/chat` + openai `/chat/completions`（response_format json_object）统一 JSON 单发；**无 DB 依赖**（model_override 由调用方解析，同 `resolve_llm_override` 先例）；provider 不可达/异常 → 返回 None（调用方回落）；可像 chat_stream 一样 mock httpx 测试
2. **薄封装**：`main.py::_llm_suggest` 保留签名 `(engine, tenant_id, settings, prompt) -> str`——内部改为「`load_runtime_models` 解析 model_override → `json_complete` → 抽 `description` 字段」；**两处调用点（suggest-description / suggest-summary）零改动**，响应形状不变（风险 #5 回归面 = 内部实现替换）
3. **QU 升级**：`understanding.py::_llm_upgrade(query, missing_fields, candidates)`——`load_runtime_models` 解析全局默认 LLM（D4：一期全局默认，与 suggest 一致）→ `json_complete` → prompt 携带：query + 未命中字段 + relation_types 候选集（D2 动态）+ TBox 实体类型候选 + 约束「只能从候选集选 relation，禁止发明；intent 只能选枚举值」+ 输出 JSON 结构
4. **校验**：LLM 输出过 `StructuredQuery.model_validate` + relation ∈ TBox + intent ∈ 枚举；任一非法 → 该字段回落规则结果（schema 合规率 100% 是验收门槛，D4）
5. 升级结果 merge 进规则结果（已命中字段保留规则值）

### Task 8 — derive_needs() 纯函数（§7）

**文件**：`src/earp_server/ontology/understanding.py`

**改动点**：§7 推导规则**逐条落地**（单一来源 = §8.2 通道角色表，禁止另立第二套判断）：
```python
def derive_needs(q: StructuredQuery) -> RetrievalNeed:  # RetrievalNeed = dict[str, bool]（纯派生，不落库，QP-12）
    # entity_resolution: entities 非空
    # relation_reasoning: relations 非空
    # document_evidence: intent ∉ {AGGREGATION, COMPARISON, TREND}
    # structured_data:   intent ∈ {AGGREGATION, COMPARISON, TREND, CAUSAL, MIXED}
    # metadata_filter:   constraints 非空
    # aggregation:       operation.aggregate 非空
    # real_time:         time.kind ∈ {relative, absolute} and structured_data
```
- 纯函数（无 IO）、不落库、仅 debug/评估展示（QP-12「派生不存储，存储不派生」）

---

## Phase B3 — 端点

### Task 9 — `POST /v1/ontology/understanding/debug`（§15 可解释，后端必做）

**文件**：`src/earp_server/ontology/routes.py`（+ schemas 或内联 Body model）

**改动点**：
- 请求：`{query, context?: {conversation_id?, last_entities?: [], last_intent?}}`
- 响应：
  ```json
  {
    "structured_query": {...},            // 含 confidence + 各字段命中/未命中明细
    "rule_fields": {"time": "hit", "entities": "miss", ...},
    "derive_needs": {"entity_resolution": true, ...},
    "llm_upgraded": false,                // 是否走了 LLM 升级（低置信度时 true）
    "relation_candidates_used": [...]     // 本次实际使用的 relation 候选（溯源）
  }
  ```
- 读端点、无写库、无迁移；复用 route_debug 的「分层可解释」展示模式

### Task F1 — 前端最小调试视图（决策 D7 方案 A，一期做）

**文件**：`apps/earp-admin/pages/understanding-debug.html`（新建）+ `apps/earp-admin/js/nav.js`（知识中心「探索验证」组加项）

**改动点**：
- 最小调试视图（标注「调试工具」）：query 输入 + 可选 context（last_entities 简易输入）→ 调 debug 端点 → 分层渲染：
  - QU 结果卡：intent（含回落标注）/ entities（mention + semantic_type + role）/ relations（relation ∈ TBox 校验标识）/ time / constraints / confidence 分项（rule_coverage − ambiguity_penalty）
  - derive_needs 布尔表
  - llm_upgraded 徽标（低置信度 → LLM 升级路径可视化）
- 风格复用 test-retrieval.html 的分层调试模式；纯 vanilla JS，无后端新增
- 一期标注为调试工具（非正式功能）；Phase C 全链路视图在此之上叠加（QU → 策略 → trace → Evidence）

---

## Phase B4 — 测试 + 评估

### Task 10 — 规则层单元测试 `test_understanding.py`

**文件**：`apps/earp-server/tests/test_understanding.py`（新建）

| 用例 | 断言 |
|---|---|
| schema 冻结（Intent 枚举 10 值 / TimeConstraint / StructuredQuery 字段） | 与 §6.2 逐字段一致 |
| 时间提取（昨天/最近三个月/2024 年/2024-03） | kind+expression 正确；resolved_* 为 None |
| 约束提取（2024 年 → constraints.year） | 与 time 分离建模 |
| 实体提及（纯中文长查询「主变压器是哪个公司生产的」） | mention/semantic_type 命中（依赖已修反向子串） |
| 实体提及（泛词「设备」不进词典误判） | 不产 mention 或标注低置信 |
| 指代消解（「它」+ context.last_entities） | 映射上文实体 semantic_type |
| intent 分类（可靠子集各关键词） | FACT/RELATION/AGGREGATION 正确 |
| intent 回落（COMPARISON/CAUSAL 等 7 类） | intent=None + reason 标注，不静默当 FACT |
| relation 提取（谁生产/谁负责/位于/属于/谁供应） | relation ∈ TBox、方向校验（source_type 含 subject 类型） |
| relation 非法（LLM 发明关系场景 mock） | schema 校验拒绝 + 回落 |
| 置信度（rule_coverage − 0.2×多候选） | 机械计算正确、阈值判定正确 |
| derive_needs 各推导规则 | §8.2 表逐条 |

### Task 11 — 评估集 fixture + pytest runner（§17 Understanding 层）

**文件**：`tests/fixtures/understanding_eval.md`（新建，N ≥ 100）+ `tests/test_understanding_eval.py`（新建）

- fixture 格式（仿 routing_eval.md 扩展）：
  ```
  | # | query | intent(期望) | entities(期望 mention/semantic_type) | relations(期望) | time/constraints | 备注 |
  ```
  - 覆盖：可靠子集三类各 ≥ 25 条 + 回落类（7 类抽样，标注「回落即正确」）+ 时间/约束/指代场景 + 纯中文长查询（已知边界回归）
  - 标注的 intent 只对可靠子集计分（§17）；relation 期望值必须 ∈ TBox（评估集自身合规）
- pytest runner（机制层，**不真调 LLM**，bigram/stub）：
  - intent 准确率 ≥ 85%（仅可靠子集计分；回落类「回落即正确」）
  - 实体提及召回 ≥ 90%
  - relation 准确率 ≥ 80%
  - schema 合规率 = 100%
  - 规则覆盖率报告（多少 query 走规则、多少需 LLM——机制层只测规则路径，LLM 路径由 verify 脚本覆盖）

### Task 12 — `scripts/verify_understanding.py`（dev 真模型，§17 gating）

**文件**：`scripts/verify_understanding.py`（新建，仿 verify_routing.py 结构）

- 读取 understanding_eval.md 全量 N ≥ 100
- dev 真 LLM（qwen2.5 等，走 Task 7 升级路径）+ 真实 TBox/entities（verify-ontology 租户 seed 或本脚本自建）
- 报告：规则覆盖率 / LLM 升级率 / intent 准确率（可靠子集）/ 实体提及召回 / relation 准确率 / schema 合规率 / p95 延迟（§11.3：规则层 < 50ms）
- **gating**（§17）：Understanding 层门槛未达 → 不启动 Phase C

---

## Phase B5 — 收尾

### Task 13 — OpenAPI 基线 + import-linter + 全量回归

**文件**：`apps/earp-server/openapi.yaml` + tests

- OpenAPI 基线同步（新 debug 端点）
- import-linter 保持（ontology 域 import knowledge/connector 无新增 ignore；`_llm_suggest` 抽取不改跨域结构）
- 全量 pytest 回归（现 102 + 新增保持绿）；**回归既有 suggest 两处调用点**（main.py 抽取后）

### Task 14 — session-record 更新 + commit

- Phase B 状态 → 已完成；记录评估结果（门槛数字）；下一步 Phase C（最小 planner，等 Phase A 疼点度量）或 tech-debt 治理
- 记 tech-debt（如适用）：复杂指代消解（D8 边界）、AGGREGATION 关键词保守化待评估数据支撑

---

## 依赖关系

```
Task 1（schema 冻结 + _INTENT_KEYWORDS）
  → Task 2/3/4/5（规则层各维度，并行）
      → Task 6（置信度，依赖各字段命中状态）
          → Task 7（LLM 升级，仅低置信度触发）
Task 3/5 → Task 8（derive_needs 依赖 entities/relations 非空）
Task 1-8 → Task 9（debug 端点，依赖全链路）→ Task F1（前端视图）
Task 1-8 → Task 10（单元测试）
Task 1-9 → Task 11（评估集 runner）
Task 11 → Task 12（verify 脚本，dev 门槛）
Task 9/F1/10/11 → Task 13（收尾）→ Task 14（文档 + commit）
```

**建议执行序**：`1 → (2, 3, 4, 5 并行) → (6, 8 并行) → (7, 9) → (10, 11, F1 并行) → 12 → 13 → 14`

## 验收标准（§17 Understanding 层数字门槛）

1. intent 准确率 ≥ **85%**（仅对可靠子集 {FACT, RELATION, AGGREGATION} 计分；其余 7 类回落即正确，不设门槛）
2. 实体提及召回 ≥ **90%**
3. relation（来自 TBox）准确率 ≥ **80%**
4. schema 合规率 = **100%**（relation ∈ TBox、intent ∈ 枚举、confidence 机械计算非 LLM 自报）
5. 全量 pytest 回归绿（102 + 新增）
6. import-linter + OpenAPI 基线同步；`_llm_suggest` 薄封装后签名/响应不变（suggest-description / suggest-summary 零改动回归）
7. 规则层 p95 延迟 < 50ms（§11.3 预算）
8. QU 前端最小调试视图可用（FDE 可人工验证 QU 分层结果；nav 抽屉可达）

## 风险提示

1. **实体提及 vs 实体解析边界**：understanding 只产 mention/semantic_type，**不解析 entity_id**（那是 Phase C `plan_relation` 的 `lookup_entities` 职责）——实现时不得提前耦合 entity_id，否则 Phase C 无法复用
2. **LLM 升级 schema 合规**：LLM 可能发明 relation / 编造 intent → 必须 `model_validate` + relation ∈ TBox 过滤 + intent ∈ 枚举，任一非法回落规则结果（验收门槛 4 依赖此）
3. **评估集标注工作量与质量**：N ≥ 100 是门槛规模下限（§17），标注需覆盖可靠子集三类 + 回落类抽样 + 时间/约束/指代 + 纯中文长查询（已知边界回归）；标注偏差直接动摇门槛可信度——评审时抽查标注一致性
4. **AGGREGATION 规则识别最弱**：关键词（多少/数量/统计/最多）语义歧义高——关键词表保守设计，宁可回落也不误判；评估集 AGGREGATION 条目标注 intent 时必须给出期望值，runner 对「规则未命中 → 回落」按正确计（回落即正确）
5. **`_llm_suggest` 薄封装回归面（D4 方案 A）**：`json_complete` 无 DB、model_override 由调用方解析；`_llm_suggest` 保留签名/响应不变（薄封装：DB 解析 + 调 json_complete + 抽 description）——两处调用点零改动，回归面 = 内部实现替换（Task 13 验证 suggest-description / suggest-summary 输出形状不变）
6. **import-linter 传递风险（Phase C 预留）**：本任务书 ontology 域内自由 import knowledge/connector；但 Phase C 若让 `conversation.chat_service → ontology.understanding`，将构成 `conversation→ontology.understanding→knowledge.routing` 传递违反（conversation/knowledge 均 independence 域）——届时按 P2 先例加 ignore，本任务书不触碰
7. **阈值敏感度**：0.7 阈值决定规则 vs LLM 比例（成本/延迟）——verify 脚本报告规则覆盖率与升级率，评估后按数据微调（settings 可配，不硬编码）
8. **纯中文长查询边界**：实体提及依赖 `lookup_entities` 双向子串（已修），但超长句/多实体句仍可能漏召回——评估集含此类用例，若实体提及召回 < 90% 需先增强 `_entity_hits`（tokenize 改进或实体名索引）再谈 LLM

## 人工测试指南（方案，实施后补全）

> 前置：`make migrate` + `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 make api`（API:8000）。
> Seed：跑一次 `scripts/verify_ontology.py`（verify-ontology 租户：实体 CNC-01/华东一厂/A产线/上海某精机 + facts + profile）。

```bash
# token（tenant=verify-ontology, role=verify-role）
TOKEN=$(cd apps/earp-server && .venv/bin/python -c "
import jwt; print(jwt.encode({'sub':'u1','tenant_id':'verify-ontology','role_id':'verify-role','exp':9999999999},'earp-dev-secret-change-in-production',algorithm='HS256'))")
```

### 场景 1：规则层零 LLM（高置信度 FACT）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"2024 年财务部的报销制度是什么"}'
#   期望：intent=FACT、constraints={year:2024, department:财务部}、confidence ≥ 0.7、llm_upgraded=false、rule_fields 全 hit
```

### 场景 2：规则层 RELATION + 实体命中

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 由哪家供应商制造"}'
#   期望：entities=[CNC-01/equipment]、relations=[CNC-01 → manufactured_by → supplier]、intent=RELATION、derive_needs.relation_reasoning=true
```

### 场景 3：低置信度 → LLM 升级

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"为什么主轴轴承最近故障变多了"}'
#   期望：confidence < 0.7、llm_upgraded=true、LLM 只补未命中字段、relation ∈ TBox（caused_by 等候选集内）、schema 合规
```

### 场景 4：回落类 intent 显式回落（不静默当 FACT）

```bash
curl -s -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"A产线和B产线的设备故障率对比"}'
#   期望：intent 回落标注（COMPARISON 未分类）、reason 说明、非 FACT
```

### 场景 5：评估集门槛

```bash
cd apps/earp-server && uv run pytest tests/test_understanding_eval.py -q
#   机制层（不真调 LLM）：intent ≥85%（可靠子集）/ 实体提及 ≥90% / relation ≥80% / schema 100%
.venv/bin/python scripts/verify_understanding.py
#   dev 真 LLM：同上门槛 + 规则覆盖率/升级率/p95 延迟报告
```

### 场景 6：前端 QU 调试视图（决策 D7 方案 A）

```bash
cd apps/earp-admin && python3 -m http.server 8080   # 打开 localhost:8080
```
- 知识中心 → 「探索验证」组 → 「QU 调试」页（understanding-debug.html）
- 输入 `2024 年财务部的报销制度是什么` → 期望：intent=FACT、constraints 命中、confidence ≥ 0.7、无 LLM 升级徽标
- 输入 `为什么主轴轴承最近故障变多了` → 期望：低置信度 + LLM 升级徽标 + derive_needs 布尔表
- 输入 `A产线和B产线的设备故障率对比` → 期望：intent 回落标注（COMPARISON 未分类，非 FACT）

---
**规划定稿，确认后按执行序开工。**
