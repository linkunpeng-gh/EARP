# Query Understanding & Knowledge Query Plan 设计评审报告（v0.2 对抗式评审）

- 日期: 2026-08-13
- 评审对象: `arch/design/query-understanding-query-plan-design-v0.2.md`（v0.2 修订版）
- 评审方法: 第一性原理对抗式评审 + 代码事实核对（ontology/search.py · abox_service.py · knowledge/routing.py · search_service.py · conversation/chat_service.py · planner/task_planner.py · main.py · 上游 design 文档）
- 结论: **方向正确、收缩果断，但未达可实施状态。** 核心主张「8 节点/5 策略全部直接映射现有函数」存在 2 处可证伪缺口；最难的跨通道 Evidence 融合被 QP-05 用 RRF 一句带过（范畴错误）；Retrieval Need 被扶正为一等中间层却无派生规则（双真相）。

## 评审概览

| 维度 | 评分 | 问题数 |
|------|:----:|:------:|
| 一致性（对齐现有代码/文档） | 5/10 | 4 |
| 完整性（契约与路径是否闭合） | 5/10 | 6 |
| 合理性（第一性原理） | 6/10 | 3 |
| 可行性 & 演进性 | 7/10 | 2 |
| 规范质量（可冻结/可度量） | 5/10 | 3 |
| 评审延续性 | 7/10 | 1 |
| **总分** | **≈5.8/10** | **19** |

> 评分偏低不是否定方向，而是强调「从『方向稿』到『可实施规范』还差契约冻结与缺口闭合」。

## 代码事实核对（全部实证）

| 设计声明 | 核实结果 |
|---|---|
| §7.2 节点全部「直接映射现有函数」 | ⚠️ **大体属实，但有两处缺口**（见 P1-1/P1-2） |
| `GRAPH_QUERY` → `abox_service.graph_query()` | ⚠️ **只支持前向（source→target）**；§10 例 4 的「located_in 反向取设备」不存在（grep 反向/reverse/incoming 零命中） |
| `RESOLVE_ENTITY` → `lookup_entities()` | ✅ 存在，name/business_code ILIKE 子串匹配（语义弱，需在下游增强） |
| `FUSION_RERANK` → `_rrf_merge` + P3 reranker | ⚠️ RRF 现仅存在于**同构 chunk lane**（search_service）与 ontology 三层的**启发式分**（graph=1/(1+depth)、profile=1.0）；**无跨异构通道 RRF 实现，且数学上不可行** |
| `VECTOR/KEYWORD/METADATA` → `search_chunks()` | ✅ 存在 `mode ∈ {vector, hybrid}` + `metadata_filters` + `accessible_roles`；但三个节点是一个函数的 mode 开关，非三个独立能力 |
| `DD/KB 软路由` → `route_query()` | ✅ 存在，keyword∪vector 权限过滤 + KB 兜底 |
| 问题类型 intent 与 capability intent「在 `resolve_with_entities()` 处汇合」 | ❌ **`resolve_with_entities(engine, tenant_id, intent: str)` 只吃单字符串**，内部实体命中后即丢弃；main.py:519 传 `req_body.intent`；不接收 6 维结构化输出 |
| §1.1「三层融合检索 knowledge_search() 已实现」 | ⚠️ 端点是已实现（ontology/routes.py），但 **chat_service._retrieve() 只调 route_query + search_chunks，从不调 knowledge_search**；用户路径无 profile/graph 通道 |
| §7.3 租户隔离（QP-08） | ⚠️ 一期 Plan 不落库、无 DAG DSL、现有函数均带 tenant_id + SET LOCAL —— **Phase 1–3 无新物需保护**，真正的风险在 Phase 4+ 持久化 Plan 时 |

## 各维度详情

### 1. 一致性（5/10）

- ✅ 已确认：修订 #2（示例对齐 12 类关系）为真改动；修订 #4（砍 DAG DSL）方向正确；QP-05 从硬路由改软融合方向对。
- ❌ **P1-1（高）**：§10 例 4 写 `GRAPH_QUERY(located_in 反向取设备)`，但 `graph_query` 只从 `source_entity_id = :eid` 递归前向。例 4 恰恰需要反向（target=工厂 → source=设备）。**修订 #2 想解决的「示例对齐现实」没改干净。**
- ❌ **P1-2（高）**：§4 说两维 intent 在 `resolve_with_entities()` 汇合，但该函数签名是 `(engine, tenant_id, intent: str)`，不接收 `entities/relations/constraints`。对齐矩阵纸面正确、实现脱节。
- ❌ **P1-3（高）**：§1.1 把 ontology 三层检索列为「已建成」，未区分「端点级已实现」与「chat 链路已接入」。用户路径实际只有 route_query + search_chunks 双通道，无 profile/graph。

### 2. 完整性（5/10）

- ❌ **P0-2（高）**：10 类 intent（§5.4）vs 5 个策略函数（§11）vs §9 六行通道表，三者对不齐。`LIST / COMPARISON / TREND / MIXED` 无策略落点，`select_plan` 映射表对它们未定义。
- ❌ **P0-4（高）**：Evidence Set 全程被引用（§2/§3.2/§14/§20-5），但 **schema 从未定义**。三个来源（chunk / graph fact / capability 任意 JSON）如何归一成一个 Evidence，是 citations、Answer、eval 的共同下游契约，契约不定则「组装 Evidence Set」是空话。
- ❌ **P0-1（高）**：Retrieval Need（§8）7 个布尔每个都能由 Structured Query 机械推导，却未定义推导规则 → 两层必须同步但无约束保证，重蹈 v0.1 自相矛盾。
- ❌ **P2-2（中）**：Phase 1 宣称「schema 冻结」，但全文只有示意 JSON，无 Pydantic/JSON Schema；relations 数组/对象形状前后不一致。

### 3. 合理性（6/10）

- ✅ 已确认：§2.2「不做成 Intent 分类器」正确；§1.2「缺的是理解层而非新检索」是全文档最值钱的一句；§13「LLM 不直接选工具」理由充分。
- ❌ **P0-3（高）**：QP-05「可用通道始终参与 RRF 融合」是范畴错误——RRF 要求同构 ranked list，capability 输出是结构化行（非 ranked list），进不了 RRF；§14 的冲突消解又需要类型语义，与 RRF 相悖。
- ❌ **P2-5（中）**：`answer_requirement` 的 `answer_type=table`、`source_preference` 一期无消费者（chat_service 固定流式文本 + citations），违反文档自己 §21 错误 4 的 YAGNI 原则。

### 4. 可行性 & 演进性（7/10）

- ✅ 已确认：Phase 1–3 净增量小（QU + 固定策略），大部分能力已有；DAG 推 Phase 4+ 评估避免与 orchestrator 并行造引擎，合理。
- ❌ **P2-1（中）**：§7.2「8 节点类型」与 §11「5 策略函数（无 DAG 解析）」是两套并行抽象，节点表在实现里无载体，成纯文档装饰——重蹈 v0.1「并行重造」之嫌（只是从「引擎」变成「命名」）。

### 5. 规范质量（5/10）

- ❌ **P2-3（中）**：§6 规则层「置信度评估」是定性描述，无可计算信号；全文无端到端 p95 延迟预算；CAUSAL 是最慢路径且是核心场景，规则优先省的延迟在此全吐回。
- ❌ **P2-4（中）**：v0.2 删掉了 v0.1 的量化门槛（Plan 正确率 ≥95% 等），§17 只说「扩展三层」，无规模、无门槛 → QP-10「四层评估跑通」不可证伪。
- ⚠️ **P2-2（中）**：intent 用自然语言枚举、relation 候选「是否必须来自 TBox」仍留成开放问题（§20-2 只是「建议」），未写死。

### 6. 评审延续性（7/10）

- ✅ 修订表（§0）逐条回应 v0.1 评审，追溯清晰；交叉引用带版本号（§19）。
- ⚠️ **P2-6（低）**：修订 #7（Retrieval Need 扶正）与修订 #11（租户隔离）是「批注消解」而非「设计收紧」——前者用「提升为一等公民」治标，后者在无新物需保护的阶段 check the box。

## Top 优先级修复清单

| 优先级 | 问题 | 维度 | 影响 | 建议方案 |
|:------:|------|:----:|:----:|---------|
| P0 | Evidence schema 未定义 | 完整性 | 高（下游契约悬空） | 冻结 `channel/source/source_ref/confidence/valid_from/valid_to/payload` 多态 schema |
| P0 | QP-05 把 RRF 用到异构通道 | 合理性 | 高（数学不可行） | 拆「通道内 RRF」与「跨通道 Evidence 组装」两层 |
| P0 | Retrieval Need 无派生规则 | 完整性 | 高（双真相） | 降为纯函数 `derive_needs(structured_query)`，加 QP「派生不存储」 |
| P0 | 10 intent vs 5 策略对不齐 | 完整性 | 高（运行时未定义） | 出完整 `intent → 策略 → fallback` 映射表 |
| P1 | §10 例 4 反向遍历不存在 | 一致性 | 高（示例调用不存在语义） | 补反向查询或改示例 + 标注缺口 |
| P1 | `resolve_with_entities` 不接收结构化输出 | 一致性 | 高（产出无消费者） | 定义接收 entities 数组的新签名/重载 |
| P1 | §1.1 端点级 vs chat 链路未区分 | 一致性 | 中（低估 Phase 3 工作量） | 明确区分，写 Phase 3 硬任务 |
| P2 | 无量化验收门槛 | 规范质量 | 中（QP-10 不可证伪） | 恢复 Understanding/Plan 层数字门槛 + eval 规模下限 |

## 总体结论

**有条件通过（需 v0.3 闭合 P0/P1）。** v0.2 在「不要重造」上做到了位，但在「到底造什么、按什么契约造」上仍有实质缺口：跨通道融合的载体（Evidence schema）与通道边界（RRF 适用范围）未定义、intent→策略映射不闭合、两处代码映射可证伪。建议 v0.3 只保留两类工作——**（a）可证伪的正确性缺口闭合（P1），（b）必须冻结的契约（P0 的 schema 们）**；「建议值待实验」类直接收进 backlog，不再在文档里来回倒。

关联产出: `arch/design/query-understanding-query-plan-design-v0.3.md`（按本报告逐项修订）。
