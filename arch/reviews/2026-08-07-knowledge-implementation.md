# 知识资产方向实施记录（2026-08-07）

**定位**：一次完整会话记录——从技术路线讨论 → 架构决策 → 规范回填 → PRD 对齐 → 代码实施 → 端到端验证。
**下次继续**：PRD-2026-030 M3（中台对接 importer + Enrichment）、M4（admin 实体管理页）。

---

## 一、会话主线（讨论 → 决策）

### 1.1 知识库技术路线（核心决策）

| 决策 | 内容 |
|:---|:---|
| **知识库优先** | 企业知识理解是所有 AI 操作的基础（v2.1 知识链）——最先实现 |
| **渐进路线** | RAG 打底（Phase 1）→ 实体积累层/本体层（Phase 2）→ 图谱推理点缀（Phase 3，仅多跳场景） |
| **图谱不替代 RAG** | gBrain/GraphRAG 研究结论：图谱索引慢 40-57 倍、token 贵 6000 倍、权限难投影——补充而非替代（行业共识 + gBrain 自身即三通道混合） |
| **gBrain 借鉴三机制** | Self-wiring 零 LLM 建图（→ 规则抽取）、Compiled Truth（→ 事实档案）、Enrichment + Timeline（→ 定时回填） |
| **TBox/ABox 双层** | 本体层（抽象实体/关系，人工低频）与数据层（实例/事实，自动高频）分离 |
| **ABox 三种来源模式** | virtual（API 直连）/ synced（ETL 同步）/ extracted（文档抽取）——ABox 是统一访问层不是存储层 |
| **数据中台分工** | 数据整理（抽取/治理/指标计算/API）归中台，EARP 聚焦**知识资产**（语义层/知识抽取/检索推理） |

### 1.2 概念澄清（BD vs DD + 检索思路）

- **Business Domain = 能力归属（能做什么）**；**Data Domain = 知识归属（知道什么）**——N:M 映射、非包含
- 实体类型属于 **DD** 不直接属于 BD；Capability 属 BD，经 **capability_entity_map** 操作实体类型
- **检索双思路正交**：DD 路由（空间裁剪）与 Ontology 导航（语义线索）同时使用——三层流水线：
  `DD 路由 →（Ontology 导航 + vector + keyword）→ Capability 结构化数据（第三通道）`

### 1.3 关键设计决策（全部写入文档）

| 决策 | 落点 |
|:---|:---|
| 13 实体类型 + 12 关系类型种子（首批） | ontology-layer-design §3 |
| entity 用 EARP 生成 ID + `business_code` 属性 | §4.1 |
| 新增 `component` 一级部件类型（不建层级） | §3.1 |
| 档案重编译：定时批量 + 高频即时 | §4.3 |
| `capability_entity_map` 必建 | §3.3、§5 |
| `entity_types.kind`（object/concept/metric） | §4.5 |
| 三层流水线 + 设备故障示例（替换"销售额"指标例） | §7 |
| **Capability 类型正交模型**：capability_type（query/command 操作语义）+ source_type（skill/mcp/workflow/restful 来源形态）——restful 默认 GET→query、POST/PUT/DELETE→command | 四类型设计文档修订 |
| 双层权限：DD classification 天花板 + 行级角色（accessible_roles） | KB spec v1.1 |

---

## 二、产出文档（新增/修订）

| 文档 | 变更 |
|:---|:---|
| `arch/design/2026-08-07-ontology-layer-design.md` | **新增**：本体层 L2.5 设计（TBox/ABox/三层检索/中台对接/治理） |
| `arch/design/2026-08-07-ontology-layer-l3-design-v1.md` | **新增**：L3 实现设计（DDL/接口/里程碑 M1-M4） |
| `arch/L2/02-reasoning/knowledge-center-specification.md` | v1.1→**v1.2**：第四章 TBox/ABox 重构 + 数据中台对接 |
| `arch/L2/02-reasoning/planner-specification.md` | v1.0→**v1.1**：§5.1.5 实体识别 + 候选收窄 |
| `arch/L2/11-knowledge/knowledge-base-specification-v1.md` | v1.0→**v1.1**：双层访问模型 |
| `arch/L2/01-runtime/runtime-specification.md` | v1.3→**v1.4**：ABox 属 Knowledge 不属 Memory |
| `arch/design/2026-07-22-capability-four-types-design.md` | 修订：query/command 与四类型正交 |
| `prd/PRD-2026-030-ontology-layer.md` | **新增**：本体层 PRD（M1-M4，15 AC） |
| `prd/PRD-2026-028-admin-dashboard.md` | 修订：Test Retrieval 页 + Capabilities 双标签 + TBox 管理 |
| `prd/PRD-2026-023-server-m3-reasoning.md` | 修订：补实体识别 + 候选收窄 |
| `arch/tech-debt.md` | +1 条：business_capabilities 单列主键 |

---

## 三、代码实施（apps/earp-server，51 测试全过）

### 阶段 1：接通既有断点 + schema 对齐

| 变更 | 说明 |
|:---|:---|
| **migration 0007_schema_alignment** | 列名对齐 `kb_id→knowledge_base_id`、`doc_id→document_id`（3 表）；documents 补 title/content/content_hash；chunks 补 chunk_index/content_hash；**data_domains 复合主键** (id, tenant_id) |
| `planner/business_dictionary.py` | +`match_data_domains()`（中英关键词 → DD） |
| `planner/service.py` | `resolve_data_domains` 从 stub 实现（关键词 + 租户已注册过滤） |
| `knowledge/admin_service.py` + main.py | **8 个 admin 端点**：KB CRUD（含聚合计数）/ documents 列表/分类修改/删除 + DD 列表/创建 |
| `knowledge/document_service.py` | +`find_duplicate()`；create_document 补 name 列 |
| `knowledge/chunk_service.py` | create_chunks 补 knowledge_base_id（查 documents） |
| 前端接线 | knowledge.html / data-domains.html / test-retrieval.html mock → 真实 API；capabilities.html Type 双标签 |

### 阶段 2：PRD-2026-030 M1（本体层）

| 变更 | 说明 |
|:---|:---|
| **migration 0008_ontology** | 7 表（TBox 3 + ABox 4）+ 8 索引 + RLS；**复合主键**（修复单列 PK 跨租户冲突） |
| `ontology/tbox_service.py` | 种子（13 实体 + 12 关系，幂等）+ 类型 CRUD + capability_entity_map（含反查） |
| `ontology/abox_service.py` | 实体幂等 upsert + lookup + facts CRUD + **graph_query（递归 CTE 3 跳 + 环路保护）** + **Compiled Truth** |
| `ontology/routes.py` | 12 个端点 + **惰性种子**（首次访问自动 init） |

### 阶段 3：PRD-2026-030 M2（三层检索）

| 变更 | 说明 |
|:---|:---|
| `ontology/search.py` | `knowledge_search()`：profile + graph + vector 三通道 **RRF 融合**（k=60）；`resolve_with_entities()`：实体识别 → capability_entity_map 反查收窄 |
| main.py `/plan` | 实体感知候选收窄（失败静默回退不阻塞） |
| `GET /v1/ontology/search` | 三层检索端点（embedding 失败优雅降级） |

### 实施中发现并修复的 4 个存量 bug

| Bug | 说明 |
|:---|:---|
| **M4 schema 脱节** | 代码用新列名（knowledge_base_id/document_id），0001 DDL 是旧名（kb_id/doc_id）——**M4 入库代码从未跑通**（无集成测试覆盖）；0007 修复 + 补全链路测试 |
| **上传永远 "unchanged, chunks: 0"** | 去重逻辑对比刚插入的行（必然命中）——`find_duplicate` 按 KB+content_hash 修复 |
| **embedding provider 从未初始化** | `init_all` 缺 `ext_embedding.init_app`——首次 embed 必 500 |
| **单列主键跨租户冲突** | data_domains（0007 修）/ entity_types/relation_types（0008 修）——ON CONFLICT 静默吞掉跨租户种子 |

---

## 四、验证

### 测试：51 passed（基线 38 → 51，+13）

```
test_planner_dd (6) + test_knowledge_pipeline (1) + test_knowledge_admin (3)
+ test_ontology (5) + test_ontology_search (4) = 19 新增
ruff 干净；openapi.yaml 同步
```

### 端到端（scripts/verify_knowledge.py，已跑通）

```
✅ health / TBox 惰性种子（13+12）✅ Data Domain / KB 创建
⚠️ 上传（Ollama embedding 不可达降级，文档行已创建）
✅ 实体×4 + 事实×3 ✅ Compiled Truth 档案 ✅ 图谱 3 跳
✅ 三层检索（profile + graph，无 embedding 可用）✅ /plan 实体收窄
```

**环境要求**：Docker（PG/valkey）+ Ollama bge-m3（vector 层；当前 10.188.2.230:11434 返回 502，设 `EARP_OLLAMA_BASE_URL` 解锁完整三层）

---

## 五、待办

| 优先级 | 事项 |
|:---|:---|
| P1 | PRD-2026-030 **M3**：中台对接 importer（virtual/synced + CSV 兜底）+ Enrichment 定时任务（timeline 回填/热度/失效清理） |
| P1 | PRD-2026-030 **M4**：admin 实体类型管理页（TBox CRUD）+ 检索测试页三层来源标签 |
| P2 | `business_capabilities` 复合主键（tech-debt #7） |
| P2 | knowledge.html 的 KB chunk/retrieval 配置字段持久化（retrieval_model JSONB） |
| P3 | role access admin API（Data Domains 页面 Phase 2 项） |

---

## 追加（2026-08-09）：LLM 模型配置中心（PRD-2026-031）

**设计**：`arch/design/2026-08-09-llm-config-design.md`（参考 Dify 三层体系：Provider 目录 / Model Config / System Settings）；PRD-2026-031。

**决策**：ollama + openai 两供应商；credentials JSONB 内嵌 AES（EARP_CREDENTIALS_KEY）；右上角齿轮图标入口；rerank 占位。

**实施**：
- migration 0009：model_configs + system_model_settings（2 表 + RLS）
- `infra/model_registry.py`（供应商目录）+ `infra/credential_crypto.py`（AES-256-GCM）+ `admin/model_service.py`（CRUD/默认/测试/load_runtime_models）+ `admin/model_routes.py`（8 端点）
- LLMConnector 支持 model_override（DB 优先 env 兜底）；lifespan 加载 DB 默认模型重建 embedding provider
- 前端 models.html + 全部页面 header 右上角 ⚙️ 入口
- 测试：test_model_config.py（4 个）；全量 55 passed
- 实测：添加 ollama llm/embedding 模型、设默认、测试连接真实调用成功、凭证不明文
