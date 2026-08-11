# PRD-2026-030 v1.0

## Ontology Layer — 本体层（TBox/ABox + 三层检索 + 中台对接 + 知识积累）

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-030 |
| **Feature** | 本体层：TBox（实体类型/关系类型/capability_entity_map）+ ABox（实体/事实，三种来源模式）+ 三层检索（DD 路由 + Ontology 导航 + RAG）+ Compiled Truth / Timeline / Enrichment + 中台对接 |
| **优先级** | **P1** |
| **版本** | v1.0 |
| **上游设计** | `arch/design/2026-08-07-ontology-layer-design.md`（L2.5 设计）、`arch/design/2026-08-07-ontology-layer-l3-design-v1.md`（L3）、`arch/L2/02-reasoning/knowledge-center-specification.md` v1.2（第四章）、`planner-specification.md` v1.1（§5.1.5）、`knowledge-base-specification.md` v1.1（§2.1.1 双层权限） |
| **PRD 链** | ← PRD-2026-024(M4) |

---

## 1. 范围表

### M1 — 建表 + TBox/ABox CRUD + 实体检索

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | DDL | migration 0007：7 张表（entity_types/relation_types/capability_entity_map/entities/facts/entity_profiles/entity_timeline）+ 8 索引 + RLS（FORCE，复用 0001 模式）+ TBox 种子（13 实体类型 + 12 关系类型，幂等 `ON CONFLICT DO NOTHING`） |
| 2 | TBox | entity_types CRUD：`POST/GET /v1/ontology/entity-types`、deprecate（写 audit，实例不受影响）；relation_types CRUD；capability_entity_map 维护：`POST /v1/ontology/capabilities/{capability_id}/entities` |
| 3 | ABox | entities upsert（同 tenant+entity_type+business_code 幂等合并）+ facts CRUD（add_fact 发事件 / revoke 留痕 / supersede）+ 按 source_mode 分派（virtual 经 Connector 取数，synced/extracted 读表） |
| 4 | 检索 | entity lookup：name/business_code 前缀匹配 + 双层权限过滤（classification 天花板 + 行级角色）；Compiled Truth 编译（规则聚合 entity+facts → entity_profiles） |
| 5 | 事件 | 4 个新事件注册进 EventBus 注册表：`runtime.knowledge.fact_created/superseded/revoked/synced`；fact 变更 → 触发档案重编译（高频即时，其余入队） |

### M2 — 三层检索 + 实体识别反查

| # | 域 | 功能 |
|:--|:---|:-----|
| 6 | 检索 | `GET /v1/ontology/search`：knowledge_search 三层流水线——① entity lookup（命中取 profile，零 LLM）② graph_query 递归 CTE 多跳（≤3 跳，环路保护）③ vector+keyword（复用 knowledge/search_service）→ RRF 融合（k=60） |
| 7 | Planner | 实体识别 → capability_entity_map 反查：`find_capabilities_by_entity_type` → Resolution Engine 候选集收窄（planner-spec §5.1.5）；识别失败回退全库语义匹配（不阻塞） |

### M3 — 中台对接 + Enrichment

| # | 域 | 功能 |
|:--|:---|:-----|
| 8 | 导入 | `POST /v1/ontology/import/connector`（中台对接：virtual 建元数据实时取数 / synced 同步副本，经 connector 基础设施）+ `POST /v1/ontology/import/csv`（无中台兜底）+ 定时同步任务（business_code 增量幂等） |
| 9 | Enrichment | 夜间任务（注册 task_queue）：① audit_logs/executions/capability_calls → entity_timeline 回填 ② 热度统计 → 未覆盖实体标记 ③ 失效事实清理（valid_to 过期 → revoked）④ 档案批量重编译 |

### M4 — Admin 页面

| # | 域 | 功能 |
|:--|:---|:-----|
| 10 | 页面 | Data Domains 页面扩展实体类型管理（TBox CRUD：kind/attributes/owner/status）；检索测试页升级显示三层来源（profile/graph/chunk） |

---

## 2. US

| US | 描述 |
|:--:|:-----|
| US-01 | 租户注册 → init_tenant_tbox 幂等落种子（13 实体类型 + 12 关系类型） |
| US-02 | 管理员创建实体类型（kind=object, dd=equipment_data）→ 201 → 列表可见 |
| US-03 | 导入设备台账 CSV（business_code=CNC-01）→ entity 落库 → 二次导入同编码 → 合并不重复（幂等） |
| US-04 | add_fact（CNC-01 —manufactured_by→ 供应商B）→ facts 行 + fact_created 事件 → 档案重编 |
| US-05 | 检索 "CNC-01 的制造商" → entity lookup 命中 → 直接返回 Compiled Truth 档案（无 LLM） |
| US-06 | 检索 "华东一厂 CNC 设备主轴轴承故障率" → 三层检索：DD 路由（equipment_data+quality_data）→ 图谱多跳（Alarm→Component→Equipment→Supplier）→ RRF 融合返回 |
| US-07 | 检索无实体命中（如模糊问题）→ 回退纯 vector 检索，不报错 |
| US-08 | 无权限角色检索实体 → classification 天花板 + 行级角色过滤 → 静默过滤 |
| US-09 | 中台指标 API 注册为 metric 类型（virtual）→ 查询实时经 Connector 取数 |
| US-10 | 夜间 enrichment → timeline 回填 + 失效事实清理 + 档案重编 → 统计报告 |
| US-11 | capability_entity_map 配置后，Planner 意图含实体 → 候选 Capability 收窄为可操作该实体类型的列表 |

---

## 3. AC

| AC | 内容 | 验证 |
|:--:|:-----|:----|
| AC-01 | migration 0007 后 7 表存在 + RLS FORCE 生效（跨租户不可见） | pytest + testcontainers |
| AC-02 | 种子 13+12 幂等（重复 init 不报错不重复） | pytest |
| AC-03 | entity upsert 幂等：同 business_code 二次导入 → 1 行 | pytest |
| AC-04 | add_fact → facts 行 + 事件发布（EventBus 订阅收到） | pytest |
| AC-05 | revoke_fact → status=revoked + audit 记录 | pytest |
| AC-06 | lookup_entities 前缀匹配 + 双层权限过滤（分类天花板 + 行级角色） | pytest |
| AC-07 | compile_profile 聚合 entity+活跃 facts → entity_profiles 行（version+1） | pytest |
| AC-08 | knowledge_search 返回多源 RRF 结果（profile/graph/chunk 混合） | pytest |
| AC-09 | graph_query ≤3 跳正确 + 环路保护（不无限递归） | pytest |
| AC-10 | 实体命中 → 返回 profile 无需 LLM；无实体命中 → 回退纯 vector 不报错 | pytest |
| AC-11 | 实体识别 → capability_entity_map 反查 → 候选收窄（"CNC-01 高温报警" → equipment 类 Capability 列表） | pytest |
| AC-12 | import_csv → 实体+事实落库（confidence=1.0，规则生成关系） | pytest |
| AC-13 | virtual 实体查询经 Connector 取数；synced 读副本 | pytest（mock connector） |
| AC-14 | enrichment_run → timeline 回填 + 失效事实 revoked + 档案重编，返回统计 | pytest |
| AC-15 | 管理页实体类型 CRUD 走通；检索测试页显示三层来源标签 | 手工 + pytest（API 层） |

---

## 4. 依赖

| 依赖 | 来源 | 引用 |
|:-----|:-----|:------|
| data_domains / business_capabilities 表 | M0 DDL / 0005 | TBox 外键 + capability_entity_map |
| knowledge/search_service | M4（已实现） | vector 检索复用 |
| embedding_service | M4 | 检索 embedding 生成 |
| EventBus 注册表 | eventbus-spec v1.1 | 4 个新事件类型注册 |
| task_queue（procrastinate） | M1 infra | enrichment 定时任务 |
| connector 基础设施 | M0-M7 | virtual/synced 取数 |
| tenant_session / RLS | M0 | 全部表 tenant 隔离 |

---

## 5. 对齐检查

| 规范 | 关键条款 | 对齐 |
|:-----|:---------|:----:|
| knowledge-center-spec v1.2 第四章 | TBox/ABox 双层、三种来源模式、capability_entity_map、知识积累机制 | ✅ |
| planner-spec v1.1 §5.1.5 | 实体识别 + 候选收窄（不阻塞路由） | ✅ |
| KB spec v1.1 §2.1.1 | 双层访问模型（分类天花板 + 行级角色） | ✅ |
| EventBus spec v1.1 | 新事件注册进唯一注册表 | ✅ |
| 本体层设计（arch/design） | 13+12 种子、三层流水线、Compiled Truth/Enrichment | ✅ |
| 数据中台分工 | EARP 不重复数据整理；中台为数据源（virtual/synced） | ✅ |

---

## 6. Gate 检查

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确 | ✅ 7 项 |
| 2 | AC 可测试（全部自动化，M4 含手工） | ✅ 15 条 |
| 3 | M0-M4 遗留已处理 | ✅ 复用 search_service/embedding_service |
| 4 | 与冻结规范无矛盾 | ✅ 已对齐 v1.2/v1.1 |
