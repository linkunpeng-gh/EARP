# Ontology Layer — L3 实现设计

**文档编号：DESIGN-ONTOLOGY-L3**
**版本：v1.0（draft）**
**日期：2026-08-07**

> 上游：`arch/design/2026-08-07-ontology-layer-design.md`（L2.5 设计）、`arch/L2/02-reasoning/knowledge-center-specification.md` v1.2（第四章 Ontology）、`arch/L2/02-reasoning/planner-specification.md` v1.1（§5.1.5）
> 技术栈：FastAPI + SQLAlchemy 2 async + PostgreSQL 16 + pgvector，复用现有 `tenant_session()` / RLS `SET LOCAL` 模式（M0-M7 已固化）。

---

# 一、目录结构（新增 ontology 模块）

```
apps/earp-server/src/earp_server/
├── ontology/
│   ├── __init__.py
│   ├── models.py            # TBox/ABox SQLAlchemy 表模型（7 张表）
│   ├── tbox_service.py      # 实体类型/关系类型 CRUD + capability_entity_map + 种子初始化
│   ├── abox_service.py      # 实体/事实 CRUD（含 virtual 实体分派）
│   ├── search.py            # 三层检索：entity lookup + 图谱导航 + RRF 融合
│   ├── profile_service.py   # Compiled Truth 档案编译（变更即时 + 定时）
│   ├── enrichment.py        # Enrichment 定时任务（timeline 回填/热度/失效清理）
│   ├── importer.py          # 数据源对接：Connector 导入（中台）+ CSV 兜底
│   └── routes.py            # API 端点（/v1/ontology/...）
├── knowledge/               # 现有模块（search_service 复用，不改动接口）
└── infra/                   # 现有（db/eventbus/task_queue 复用）
```

**依赖方向**：`ontology` 依赖 `infra`（db/eventbus/task_queue）和 `knowledge`（embedding/search 复用）；被 `planner`、`capability`（registry）引用。符合 import-linter 契约（知识域内横向引用）。

---

# 二、数据库 DDL（migration 0007）

`apps/earp-server/migrations/versions/0007_ontology_layer.py`，全部表 tenant-scoped + RLS（复用 0001 模式）。

## 2.1 表结构

```sql
-- ============ TBox：本体层 ============
CREATE TABLE entity_types (
    entity_type_id  VARCHAR(64) PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    name            TEXT NOT NULL,
    kind            VARCHAR(16) NOT NULL DEFAULT 'object'
                    CHECK (kind IN ('object','concept','metric')),
    description     TEXT,
    data_domain_id  VARCHAR(64) REFERENCES data_domains(data_domain_id),
    attributes      JSONB NOT NULL DEFAULT '{}',       -- JSONSchema 属性定义
    owner           TEXT,
    version         VARCHAR(16) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('draft','active','deprecated')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE relation_types (
    relation_type_id VARCHAR(64) PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    name            TEXT NOT NULL,                     -- 业务动词
    source_type     VARCHAR(64) REFERENCES entity_types(entity_type_id),
    target_type     VARCHAR(64) REFERENCES entity_types(entity_type_id),
    cardinality     VARCHAR(8) NOT NULL CHECK (cardinality IN ('1:1','1:N','N:M')),
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','deprecated')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE capability_entity_map (
    capability_id   VARCHAR(64) NOT NULL,              -- 引用 business_capabilities
    entity_type_id  VARCHAR(64) NOT NULL,
    tenant_id       VARCHAR(64) NOT NULL,
    operation       VARCHAR(8) NOT NULL DEFAULT 'read'
                    CHECK (operation IN ('read','write','both')),
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','deprecated')),
    PRIMARY KEY (capability_id, entity_type_id, tenant_id)
);

-- ============ ABox：数据层 ============
CREATE TABLE entities (
    entity_id       VARCHAR(64) PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    entity_type_id  VARCHAR(64) REFERENCES entity_types(entity_type_id),
    name            TEXT NOT NULL,
    business_code   TEXT,                              -- 业务编码，可重复（跨类型）
    attributes      JSONB NOT NULL DEFAULT '{}',
    source_mode     VARCHAR(16) NOT NULL DEFAULT 'extracted'
                    CHECK (source_mode IN ('virtual','synced','extracted')),
    source_ref      TEXT,                              -- connector 配置 / 导入批次 / 文档 ID
    data_domain_id  VARCHAR(64) REFERENCES data_domains(data_domain_id),
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','deprecated','merged')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE facts (
    fact_id          VARCHAR(64) PRIMARY KEY,
    tenant_id        VARCHAR(64) NOT NULL,
    source_entity_id VARCHAR(64) REFERENCES entities(entity_id),
    relation_type_id VARCHAR(64) REFERENCES relation_types(relation_type_id),
    target_entity_id VARCHAR(64) REFERENCES entities(entity_id),
    confidence       FLOAT NOT NULL DEFAULT 1.0,
    source_ref       TEXT,
    valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to         TIMESTAMPTZ,                      -- NULL = 当前有效
    status           VARCHAR(16) NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active','superseded','revoked')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE entity_profiles (
    entity_profile_id VARCHAR(64) PRIMARY KEY,
    tenant_id         VARCHAR(64) NOT NULL,
    entity_id         VARCHAR(64) NOT NULL UNIQUE REFERENCES entities(entity_id),
    profile           JSONB NOT NULL,                  -- {summary, key_facts[], related_entities[], stats{}}
    profile_version   INT NOT NULL DEFAULT 1,
    compiled_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE entity_timeline (
    entity_timeline_id VARCHAR(64) PRIMARY KEY,
    tenant_id          VARCHAR(64) NOT NULL,
    entity_id          VARCHAR(64) REFERENCES entities(entity_id),
    event_type         VARCHAR(32) NOT NULL,
    payload            JSONB NOT NULL DEFAULT '{}',
    occurred_at        TIMESTAMPTZ NOT NULL,
    source_ref         TEXT
);
```

## 2.2 索引

```sql
CREATE INDEX ix_facts_source_rel    ON facts (source_entity_id, relation_type_id);
CREATE INDEX ix_facts_target        ON facts (target_entity_id);
CREATE INDEX ix_facts_rel_target    ON facts (relation_type_id, target_entity_id);
CREATE INDEX ix_facts_valid_to      ON facts (valid_to);
CREATE INDEX ix_entities_type_dd    ON entities (entity_type_id, data_domain_id);
CREATE INDEX ix_entities_name       ON entities (name);
CREATE INDEX ix_entities_bizcode    ON entities (business_code);
CREATE INDEX ix_timeline_entity_ts  ON entity_timeline (entity_id, occurred_at DESC);
```

## 2.3 RLS（复用 0001 模式）

```sql
-- 对 7 张表执行：
ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {tbl}
    USING (tenant_id = current_setting('earp.tenant_id', true));
```

## 2.4 TBox 种子数据（migration 内嵌，每个租户注册时初始化）

- **13 类实体类型**（kind=object）：equipment / component / production_line / plant / sensor / alarm / work_order / material / product / supplier / customer / employee / department（映射 data_domain：equipment_data / quality_data / production_data / supply_chain_data / hr_data / corporate_data，见设计文档 §3.1）
- **12 类关系类型**：located_in / belongs_to / manufactured_by / supplied_by / maintained_by / responsible_for / produces / consumes / caused_by / monitored_by / relates_to / approved_by（源/目标类型 + 基数见设计文档 §3.2）

> 种子通过 `ontology/tbox_service.py::init_tenant_tbox(engine, tenant_id)` 幂等执行（`INSERT ... ON CONFLICT DO NOTHING`），租户注册钩子调用。

---

# 三、Ontology Service 接口

## 3.1 TBox Service（`tbox_service.py`）

```python
@dataclass
class EntityTypeDef:
    entity_type_id: str
    name: str
    kind: Literal["object", "concept", "metric"]
    description: str | None = None
    data_domain_id: str | None = None
    attributes: dict = field(default_factory=dict)   # JSONSchema
    owner: str | None = None

# 实体类型
async def init_tenant_tbox(engine, tenant_id) -> None          # 种子幂等初始化（注册钩子）
async def create_entity_type(engine, tenant_id, defn: EntityTypeDef) -> dict
async def list_entity_types(engine, tenant_id, data_domain_id: str | None = None,
                            kind: str | None = None, status: str = "active") -> list[dict]
async def deprecate_entity_type(engine, tenant_id, entity_type_id) -> None   # 需审批，写 audit

# 关系类型
async def create_relation_type(engine, tenant_id, defn) -> dict
async def list_relation_types(engine, tenant_id, source_type: str | None = None) -> list[dict]

# capability 关联
async def map_capability_entity(engine, tenant_id, capability_id, entity_type_id,
                                operation: Literal["read","write","both"]) -> None
async def find_capabilities_by_entity_type(engine, tenant_id, entity_type_id,
                                           role_id: str | None = None) -> list[dict]
    # 反查可操作该实体类型的 Capability（供 Resolution Engine 候选收窄，§planner 5.1.5）
async def find_entity_types_by_capability(engine, tenant_id, capability_id) -> list[dict]
```

## 3.2 ABox Service（`abox_service.py`）

```python
@dataclass
class EntityIn:
    entity_id: str | None = None          # None → EARP 生成（uuid4 hex）
    entity_type_id: str
    name: str
    business_code: str | None = None
    attributes: dict = field(default_factory=dict)
    source_mode: Literal["virtual","synced","extracted"] = "extracted"
    source_ref: str | None = None
    data_domain_id: str | None = None     # 默认继承 entity_type 的 DD

@dataclass
class FactIn:
    source_entity_id: str
    relation_type_id: str
    target_entity_id: str
    confidence: float = 1.0
    source_ref: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

async def upsert_entity(engine, tenant_id, ent: EntityIn) -> dict
    # 同 (tenant, entity_type, business_code) 幂等合并（merged 语义）
async def get_entity(engine, tenant_id, entity_id) -> dict | None
async def lookup_entities(engine, tenant_id, query: str, role_id: str,
                          entity_type_ids: list[str] | None = None,
                          data_domain_ids: list[str] | None = None, top_k: int = 5) -> list[dict]
    # 名称/business_code 前缀匹配 + data_classification 天花板 + 行级角色过滤
async def add_fact(engine, tenant_id, fact: FactIn) -> dict
    # 写 facts + 发布 runtime.knowledge.fact_created 事件（触发档案重编译）
async def revoke_fact(engine, tenant_id, fact_id, reason: str) -> None
    # status → revoked（留痕），同因审计日志
async def supersede_fact(engine, tenant_id, fact_id, new_fact: FactIn) -> None
async def graph_query(engine, tenant_id, entity_id, max_hops: int = 3,
                      relation_type_ids: list[str] | None = None) -> list[dict]
    # 递归 CTE 多跳遍历，只取 valid_to IS NULL 的活跃事实（§设计文档 5 节示例）
async def get_entity_profile(engine, tenant_id, entity_id) -> dict | None   # Compiled Truth
```

## 3.3 三层检索（`search.py`）

```python
@dataclass
class KnowledgeSearchRequest:
    query: str
    embedding: list[float] | None = None          # 由调用方预生成（复用 knowledge/embedding_service）
    role_id: str
    data_domain_ids: list[str] | None = None      # DD 路由结果（Planner 传入）
    entity_type_ids: list[str] | None = None
    top_k: int = 5

@dataclass
class KnowledgeHit:
    source: Literal["profile","graph","chunk","keyword"]
    entity_id: str | None = None
    chunk_id: str | None = None
    content: str
    score: float

async def knowledge_search(engine, tenant_id, req: KnowledgeSearchRequest) -> list[KnowledgeHit]:
    """三层流水线（设计文档 §7.1）：
    1. entity lookup（名称/business_code 前缀匹配）→ 命中取 entity_profile（Compiled Truth）
    2. 实体命中 → graph_query 多跳扩展（关联事实/邻居实体）
    3. vector + keyword（复用 knowledge/search_service.search_chunks + tsvector）
    → RRF 融合（k=60）→ 返回排序结果
    """

# Resolution Engine 集成
async def resolve_with_entities(engine, tenant_id, intent_entities: list[str],
                                role_id: str, goal: dict) -> list[dict]:
    """实体 → entity_type → capability_entity_map 反查 → 候选 Capability 列表
    （供 planner §5.1.5 收窄 Resolution Engine 候选集）"""
```

## 3.4 Compiled Truth（`profile_service.py`）

```python
async def compile_profile(engine, tenant_id, entity_id) -> dict
    # 聚合：entity.attributes + 活跃 facts + 最近 timeline 事件
    # profile = {summary(LLM 可选), key_facts[], related_entities[], stats{}}
    # 写入 entity_profiles（profile_version +1），审计 compiled 记录
async def compile_stale_profiles(engine, tenant_id, limit: int = 100) -> int
    # 定时巡检：facts 变更后未重编的实体（profile_version 落后标记）
async def on_fact_event(event: CloudEvent) -> None
    # EventBus 订阅 runtime.knowledge.fact_created/superseded/revoked
    # 高频实体 → 即时重编；其余入待编队列（夜间批量）
```

## 3.5 Enrichment（`enrichment.py`）

```python
async def enrichment_run(engine, tenant_id) -> dict
    """夜间任务（注册到 task_queue，复用 schedule 域）：
    1. timeline 回填：audit_logs / executions / capability_calls → entity_timeline
       （按 capability_entity_map + entity 名称匹配关联）
    2. 热度统计：capability_calls 高频实体 → 未覆盖实体标记（供 importer 候选）
    3. 失效事实清理：valid_to < now() 批量标记 revoked
    4. compile_stale_profiles 批量重编
    返回统计 {timeline_added, stale_compiled, revoked, hot_missing[]}
    """
```

## 3.6 数据导入（`importer.py`）

```python
@dataclass
class MappingRule:                      # 外部字段 → 实体/事实 映射
    entity_type_id: str
    name_field: str
    business_code_field: str | None = None
    attr_fields: dict = field(default_factory=dict)   # {attr: field}
    relations: list[dict] = field(default_factory=list)  # [{relation_type, target_field}]

async def import_from_connector(engine, tenant_id, connector_config_id, rules: list[MappingRule]) -> ImportResult
    # 中台对接（virtual/synced）：经 connector 基础设施拉数据 → upsert_entity + add_fact
    # virtual 模式：仅建元数据（entity + source_ref），数据实时取
    # synced 模式：数据落库副本（source_mode=synced）
async def import_csv(engine, tenant_id, csv_bytes, rules: list[MappingRule]) -> ImportResult
    # 无中台兜底：CSV → upsert_entity + add_fact（confidence=1.0，规则生成关系）
async def sync_from_connector(engine, tenant_id, connector_config_id, rules, incremental=True) -> ImportResult
    # 定时同步任务（主数据增量，按 business_code upsert）
```

## 3.7 API 路由（`routes.py`）

```
GET    /v1/ontology/entity-types?data_domain_id=&kind=
POST   /v1/ontology/entity-types
POST   /v1/ontology/entity-types/{id}/deprecate
GET    /v1/ontology/relation-types?source_type=
POST   /v1/ontology/relation-types
POST   /v1/ontology/capabilities/{capability_id}/entities      # capability_entity_map
GET    /v1/ontology/search                                    # knowledge_search（三层）
GET    /v1/ontology/entities/{id}/profile                     # Compiled Truth
POST   /v1/ontology/entities/{id}/facts
POST   /v1/ontology/facts/{id}/revoke
POST   /v1/ontology/import/connector                          # 中台对接
POST   /v1/ontology/import/csv
POST   /v1/ontology/enrichment/run                            # 手动触发（调试用）
```

全部端点走 `jwt_middleware` + `tenant_session(engine, tenant_id)` + RLS。

---

# 四、关键实现流程

## 4.1 三层检索时序

```
Planner（§5.1.5 实体识别）
    │ intent_entities: ["CNC-01", "高温报警"]
    ▼
ontology.search.knowledge_search(engine, tenant, query, embedding, role_id, dd_ids)
    │
    ├─ ① lookup_entities("CNC-01") → equipment 实例命中
    │     └─ get_entity_profile(CNC-01) → Compiled Truth 档案（零 LLM）
    │
    ├─ ② graph_query(CNC-01, hops≤3) → 递归 CTE
    │     CNC-01 —caused_by← Alarm ×12 → Component(主轴轴承)
    │     → related_entities: [主轴轴承, 华东一厂, 供应商B(上月初)]
    │
    ├─ ③ search_chunks（复用现有 pgvector + 双层权限过滤）
    │
    └─ RRF 融合（profile/图事实/chunks，k=60）→ 结果
```

## 4.2 实体识别接入 Resolution Engine

```
Planner Intent "CNC-01 的高温报警"
  → find_capabilities_by_entity_type(engine, tenant, "equipment", role_id)
  → [query_equipment_alarm, create_work_order, start_equipment]   ← 候选收窄
  → Resolution Engine 在此候选集内语义匹配 → 选中 query_equipment_alarm
```

## 4.3 事件流（档案重编译）

```
abox_service.add_fact → publish runtime.knowledge.fact_created
    → profile_service.on_fact_event
         ├─ 高频实体（热度表标记）→ 即时 compile_profile
         └─ 其余 → 待编队列（enrichment 夜间批量 compile_stale_profiles）
```

## 4.4 中台同步任务

```
task_queue.enqueue("ontology.sync_from_connector", {connector_id, rules})
  → importer.sync_from_connector（主数据增量 upsert，business_code 幂等）
  → 发布 runtime.knowledge.synced 事件（audit + timeline 回填）
```

---

# 五、里程碑与验收

| 里程碑 | 内容 | 验收 |
|:---|:---|:---|
| **M1** | migration 0007 + models + tbox/abox CRUD + 种子 + entity lookup + profile 编译 | 种子 13+12 落库；upsert/lookup/revoke 单测通过；RLS 隔离验证 |
| **M2** | knowledge_search 三层检索 + RRF + 实体识别反查 + /v1/ontology/search | "CNC-01 报警"检索 P@5 高于纯 vector 基线（目标 +10 分）；capability 候选收窄生效 |
| **M3** | importer（connector + csv）+ enrichment 定时 + timeline 回填 | 中台数据源导入闭环；夜间 enrichment 报告正常；时间线可查 |
| **M4** | admin 页面（Data Domains 扩展实体类型管理 + 检索测试页） | 页面 CRUD 走通 |

**单测重点**：递归 CTE 多跳正确性（含环路保护 depth 上限）；virtual 实体分派；双层权限过滤（分类天花板 + 行级角色）；fact 失效（valid_to）不参与检索；幂等导入（同 business_code）。

---

# 六、影响分析与开放问题

## 影响

| 项 | 说明 |
|:---|:---|
| 现有代码 | 仅新增 ontology 模块 + migration 0007；knowledge/search_service 复用不改；planner 候选收窄为可选调用（不阻塞） |
| 事件 | 新增事件类型：runtime.knowledge.fact_created / superseded / revoked / synced（注册进 EventBus 唯一注册表） |
| 权限 | 复用双层模型（分类天花板 + 行级角色），不新增权限机制 |
| RLS | 7 张新表全部 tenant-scoped + FORCE RLS（与 0001 一致） |

## 开放问题

1. **profile.summary 是否用 LLM 生成**：M1 先用规则聚合（key_facts/stats），summary 的 LLM 生成留 M2（有 embedding/LLM 基础设施后）——倾向此方案
2. **virtual 实体的缓存策略**：Compiled Truth 缓存 + TTL 刷新（如 60s）还是每次实时取——M3 中台对接时按数据源实测决定
3. **graph_query 环路保护**：递归 CTE 用 depth 上限（3）+ 访问路径去重（path NOT LIKE '%id%'）——按设计文档示例实现，无需图数据库
