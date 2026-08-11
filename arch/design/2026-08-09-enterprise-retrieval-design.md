# 企业级精准召回设计（软路由 + 分层漏斗 + 元数据过滤）

- 日期: 2026-08-09
- 状态: **Phase 1 已实施**（2026-08-09 会话讨论定稿后落地；决策记录见 `arch/session-record.md`）
- 关联: `arch/design/2026-08-07-ontology-layer-design.md`（三层检索 §7）、`arch/L2/02-reasoning/knowledge-center-specification.md` v1.2、`arch/L2/11-knowledge/knowledge-base-specification-v1.md` v1.1

## 0. Phase 1 实施摘要（2026-08-09 会话定稿）

讨论后相对本设计的修正与决策：

1. **Migration 0012**（非 0010——编号已被 0010_recall_count/0011_kb_description 占用）
2. **GIN + containment**：过滤用 `documents.metadata @> :filters`（走 jsonb_path_ops GIN），非 §4.2 的 `->>` 等值写法；值按 metadata_schema 类型化（number 存 2024 而非 "2024"，过滤同类型）
3. **metadata 是文档级**：documents.metadata 为唯一权威（自动字段 + 手工按 schema 强校验）；chunks.metadata 保留不填充；自动字段存 id、不可手工覆盖、写时级联（KB 改名零级联）。自动字段全集：`source_kb` / `data_domain` + 公共默认（产品需求 2026-08-09）`original_file_name` / `uploaded_at`（快照）/ `updated_at`（随元数据编辑刷新）/ `source`（=documents.source_type，默认 upload）。**`data_classification` 不在自动字段**——它是可变业务值（管理员可改列），快照会过期；分类变更时顺带清除 metadata 中的旧快照
4. **软路由接入点**：`/knowledge/search` 无 KB/DD scope 时自动 route_query → candidate_kbs 内召回；ontology 三层检索 Phase 1 不接（留 Phase 2/3）
5. **DD 描述聚合**：不含文档标题（= DD.name + description + Σ(KB name+description)）；routing_description 空=自动、非空=人工覆盖（含 AI 生成端点）；文档增删只重建 KB summary，不碰 DD。**KB 摘要同构**（2026-08-10）：knowledge_bases.summary_text 空=自动聚合（name+description+文档标题）、非空=人工覆盖，`POST /knowledge/bases/{id}/suggest-summary` AI 生成；调试视图展示 KB 摘要文本
6. **重建**：写时同步局部重建（build_routing_index 支持 dd_ids/kb_ids）+ `/knowledge/routing/rebuild` 手动全量；NULL 向量=关键词 lane 兜底；routing_hash/summary_hash 幂等 + 新鲜度
7. **评估集**：`tests/fixtures/routing_eval.md` + pytest 跑分（CI 大gram 伪向量验证机制）+ `scripts/verify_routing.py`（dev 真 bge-m3 语义量化）；不落库
8. **验证体系**：机制层（pytest test_routing.py）→ 内容层（route_debug 覆盖自检 + 新鲜度）→ 效果层（评估集回归）
9. **关键词表下沉**：_DATA_DOMAIN_KEYWORDS + match_data_domains 从 planner 移至 `knowledge/routing.py`（D-13）

落地：migration 0012 · routing.py · search_chunks +metadata_filters · 5 个新/改端点 · 3 个前端页面 · test_routing.py(8) · verify_routing.py。63 tests passed + import-linter kept。

### 0.1 验证指南（Phase 1 验收，2026-08-09 实测）

四层验证（自底向上）：

**层 1 — 自动化测试（无需启动服务，testcontainers 临时 PG）**
```bash
cd apps/earp-server
make test                                              # 全量 63 项
.venv/bin/python -m pytest tests/test_routing.py -v    # 路由专项 8 项（机制层）
.venv/bin/lint-imports                                 # 模块契约
```
覆盖：重建触发/局部性/幂等、权限过滤、元数据类型敏感过滤、评估集跑分（bigram 伪向量）。

**层 2 — 真实语义评估（需 Ollama bge-m3；实测 5/5 = 100% ≥ 90%）**
```bash
make migrate   # 应用 0012（本地库到 head）
.venv/bin/python scripts/verify_routing.py
```
用真实 bge-m3 建索引 + 跑 routing_eval.md 全部用例，逐例输出候选 DD 与期望对比。
⚠️ 脚本用迁移角色（BYPASSRLS），会清掉跨租户同 id 的 DD（demo 种子也用了 finance_data 等名字）。

**层 3 — API 手动验证（make api 后，需 Bearer token）**
```bash
# ① 路由调试（三级漏斗 + 覆盖自检 + 新鲜度）
curl -X POST localhost:8000/knowledge/routing/debug -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' -d '{"query": "报销制度是什么"}'
# ② 无 scope 搜索 = 自动软路由
curl -X POST localhost:8000/knowledge/search -H 'Content-Type: application/json' \
  -d '{"query": "2024年的报销标准", "top_k": 5}'
# ③ 元数据过滤（类型敏感：year 传数字）
curl -X POST localhost:8000/knowledge/search -H 'Content-Type: application/json' \
  -d '{"query": "报销标准", "knowledge_base_ids": ["kb-xxx"], "metadata_filters": {"year": 2024}}'
# ④ 重建（幂等：第二次全 skipped）
curl -X POST localhost:8000/knowledge/routing/rebuild -H 'Content-Type: application/json' -d '{}'
# ⑤ AI 生成 DD 描述（需 qwen3.6 可达）
curl -X POST localhost:8000/api/data-domains/finance_data/suggest-description \
  -H 'Content-Type: application/json' -d '{}'
```

**层 4 — 前端全流程体验**
1. knowledge.html → 编辑 KB → 加元数据字段（year/department）→ 保存 → 上传文档 → 🏷️ 填文档元数据
2. test-retrieval.html → 输入查询 → 🛰 路由调试（看 DD→KB 得分/覆盖/新鲜度）→ Search（无 scope 自动软路由）
3. data-domains.html → 编辑 DD → ✨ AI 生成检索描述 → 确认保存

## 1. 背景与问题

当前 RAG 已在**单 KB 内**验证可用（test-retrieval 页可召回正确 chunk）。本设计解决**全公司范围**的精准查询：

```
用户问："财务制度的报销标准是什么？"
  需定位：财务 DD → 费用报销 KB → 正确 chunk
```

本质 = **查询路由（Query Routing）+ 分层召回（Hierarchical Retrieval）**。核心矛盾：全公司知识空间大（多 DD 多 KB），语义路由可能出错（路由错 = 召回空）。

## 2. 方法评估（2026-08-09 讨论结论）

| 方法 | 评价 | 采用 |
|---|---|---|
| 规则/词典路由（现状） | 快但覆盖不全、跨域歧义难处理 | 保留为第一级 |
| **Embedding 语义路由** | 快、可离线缓存、复用现有基础设施 | ✅ **核心** |
| LLM 路由（RouteLLM 思路） | 准但慢贵 | Phase 2 低置信度升级 |
| 多路召回 + RRF | 容错但慢、噪音多 | 软路由替代（见 §3） |
| **rerank 精排** | 精准最后一公里（68%→82% 实测） | ✅ Phase 2（bge-reranker） |
| **元数据过滤** | 结构化精确筛（Dify 参考） | ✅ **核心**（§4） |

**关键决策：软路由（top-N 候选）而非硬路由**——路由层给 top-N 个 DD/KB 都召回，避免路由错误导致全盘皆空，由 rerank 兜底。

## 3. 三级漏斗 + 软路由

```
用户 query
  │
  ├─ Level 1 — DD 路由层（去哪片海域）
  │    关键词匹配（现有一级）+ data_domains.routing_description 向量匹配（新增）
  │    → 候选 DD top-N（默认 3，软路由）
  │    → 权限过滤：无权限 DD 不进候选（RLS + data_domain_access）
  │
  ├─ Level 2 — KB 定位层（海域内哪艘船）
  │    knowledge_bases.summary_embedding 在候选 DD 内匹配
  │    → 候选 KB top-K（默认 3）
  │
  ├─ Level 3 — chunk 召回层（船里哪个货）
  │    候选 KB 内 vector + keyword 召回 → 合并（RRF）
  │    → 元数据过滤（结构化约束，§4）
  │
  └─ 精排 — rerank（Phase 2：bge-reranker-v2-m3）→ top-5 带引用
```

**置信度分层升级（Phase 2）**：Rule/Embedding 最高分 < 阈值（如 0.6）→ 升级 LLM 判断（RouteLLM 模式）。

## 4. 元数据过滤（结构化精确筛）

**定位**：与语义路由正交——语义解决"去哪找"，元数据解决"精确筛"（年份/部门/类型/版本等结构化约束）。

```
"2024 年的报销制度" → 语义路由到财务 KB + metadata 过滤 year=2024 → 精确
（纯语义搜"2024 年"效果差——年份是低语义信息，JSONB 精确匹配一次命中）
```

### 4.1 数据模型变更

```sql
-- knowledge_bases 增加元数据 schema（KB 级字段模板）
ALTER TABLE knowledge_bases ADD COLUMN metadata_schema JSONB NOT NULL DEFAULT '[]';
-- 例: [{"key":"department","type":"string","required":false},
--      {"key":"year","type":"number"},{"key":"doc_type","type":"string"}]

-- chunks.metadata JSONB 已存在（0001 建表即有）——上传/分块时填充：
--   自动：source_kb / data_domain / data_classification / doc_version
--   手动：管理员按 KB metadata_schema 填写（department / year / doc_type…）
```

### 4.2 检索过滤

```
POST /knowledge/search 增加可选参数:
  metadata_filters: {"year": "2024", "doc_type": "制度"}
  → WHERE chunks.metadata->>'year' = '2024' AND chunks.metadata->>'doc_type' = '制度'

GIN 索引：chunks.metadata 建 GIN（jsonb_path_ops）支撑 JSONB 过滤
```

### 4.3 溯源增强

chunk 结果携带元数据 → LLM 回答引用"依据：财务部《报销制度》v3（2024-03）"。

## 5. 数据模型变更汇总（migration 0010）

| 表 | 变更 |
|---|---|
| `data_domains` | + `routing_description` TEXT（域级检索描述，自动聚合：域下 KB 名+文档标题；人工可覆盖） |
| `data_domains` | + `routing_embedding` vector(1024)（DD 描述向量，离线生成 + 增量更新） |
| `knowledge_bases` | + `summary_embedding` vector(1024)（KB 摘要向量，文档增删时重算） |
| `knowledge_bases` | + `metadata_schema` JSONB（KB 级元数据字段模板） |
| `chunks` | metadata JSONB 已有——补 GIN 索引；上传流程填充 |
| `documents` | + `metadata` JSONB（文档级元数据，填充进 chunks） |

## 6. 服务与 API 变更

```
新模块 knowledge/routing.py：
  build_routing_index(engine, tenant)      # 离线：DD 描述向量 + KB 摘要向量批量生成
  route_query(engine, tenant, query_emb, role_id) → {candidate_dds: [...], candidate_kbs: [...]}
    # 软路由：DD top-N（权限过滤）→ KB top-K → 返回候选

升级 knowledge/search_service.search_chunks：
  + metadata_filters 参数 → SQL JSONB 过滤

新增/升级端点：
  POST /knowledge/routing/debug            # 路由调试视图：query → DD/KB 各层得分
  POST /knowledge/routing/rebuild          # 重建路由索引（文档变更后）
  POST /knowledge/search  + metadata_filters
```

## 7. 评估集（验收基线）

`tests/fixtures/routing_eval.md`——(query → 期望 DD → 期望 KB) 用例，量化每层准确率：

| # | query | 期望 DD | 期望 KB | 备注 |
|---|---|---|---|---|
| 1 | 报销制度是什么 | finance_data | 费用报销流程手册 | 语义路由 |
| 2 | 2024 年的报销标准 | finance_data | 费用报销流程手册 | 元数据过滤 |
| 3 | 设备报警阈值 | equipment_data | 报警阈值配置 | 语义路由 |
| 4 | 员工休假政策 | hr_data | 公司政策 | 语义路由 |
| 5 | 主轴轴承更换周期 | equipment_data | 设备手册 | 三层检索 |

**验收指标**：路由准确率（期望 DD 在 top-N 候选）≥ 90%；召回 P@5 不低于现有基线。

## 8. 落地路径

```
Phase 1（零新组件，现有 embedding）：
  ① migration 0010（routing_description/summary_embedding/metadata_schema/GIN 索引）
  ② routing.py：离线建索引 + route_query 软路由
  ③ search_chunks + metadata_filters
  ④ 上传流程填充 chunks.metadata（自动字段）
  ⑤ test-retrieval 升级：路由调试视图（DD→KB→chunk 三级得分）
  ⑥ 评估集落库 + 验收

Phase 2（有 LLM/rerank 后）：
  ⑦ 低置信度升级 LLM 路由
  ⑧ bge-reranker-v2-m3 精排

Phase 3：
  ⑨ 跨域查询自动聚合（query 命中多 DD → 各域召回 → 融合回答）
```

## 9. 关键成功因素

1. **DD/KB 描述质量**：路由准度一半取决于描述——自动聚合 + 人工可覆盖（KB 页建库时鼓励填描述）
2. **评估集驱动**：无评估集无法迭代路由——先落基线
3. **路由失败可观测**：调试视图必须显示每层得分（哪层断了一眼可见）
4. **权限贯穿路由**：无权限 DD 不进候选（避免白费召回）
5. **元数据 schema 克制**：KB 级 3-6 个字段足够（department/year/doc_type/version），避免过度治理

## 10. 开放问题

1. DD 描述向量的自动聚合策略：域下全部文档标题拼合 vs KB 摘要加权？——倾向"KB 摘要 × KB 权重"聚合
2. 路由索引重建触发：文档增删事件驱动 vs 定时（enrichment 夜间）？——倾向事件驱动 + 定时兜底
3. metadata_schema 的维护入口：KB 页扩展 vs 独立管理？——倾向 KB 创建/编辑模态框内嵌
