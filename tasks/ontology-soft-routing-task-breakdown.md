# 任务清单 — P2: Ontology 接入软路由（A3）

**状态：规划定稿，待开工**
**依据**：`arch/design/2026-08-07-ontology-layer-design.md`（§7 三层流水线）+ `-l3-design-v1.md`（§3.3 三层检索）+ `arch/design/2026-08-09-enterprise-retrieval-design.md`（软路由 §3/§6）+ `arch/design/query-understanding-query-plan-design-v0.3.md`（§8.1：三层 RRF 是合法 recall 层）
**关联**：session-record P2（A3 ontology 接入软路由：候选 DD 限域喂给三层检索，图谱能力生效）
**日期**：2026-08-11（2026-08-13 补决策点 + 前端任务 + 细化改动点）

## 目标

把 ontology 三层检索（profile / graph / chunk）接入软路由——让实体/图谱能力在**无 scope 查询路径**（`/knowledge/search` 无 KB/DD scope、chat 无 kb_scope）上生效。显式 scope 路径保持现状（一期不接）。

## 既定决策（讨论已对齐，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | graph 跨域 target 权限 | **宽松**：源实体已限域于 candidate_dds（route_query 已权限过滤），跨域 target 接受；记 tech-debt（治理模块统一收紧） |
| D2 | `/knowledge/search` 响应形状 | **混合 items**：返回 RRF 融合结果带 `source` 字段（profile/graph/chunk）；前端 test-retrieval 加 source 徽标 |
| D3 | chat 引用形状 | profile/graph item 转 citation 带 `source/entity_id/entity_type/title/key_facts`；前端 chat-edit 引用卡加「实体/图谱」徽标 |
| D4 | candidate_kbs 空 / fallback 回退 | kbs 空 → Layer 3 回退 `data_domain_ids=candidate_dds`；fallback_used 时实体层**不随 KB 扩域**；candidate_dds 空 → 保持全租户 search_chunks（原行为） |
| D5 | 三层 RRF 定性（v0.3 方案 A） | profile/graph/chunk 文本证据 RRF 是**合法 recall 层，不重构**；P2 不涉及 capability，无边界问题 |

## 现状（已核实）

- `ontology/search.py::knowledge_search()` 三层检索已实现——Layer 1 实体→Compiled Truth profile、Layer 2 图谱多跳（graph_query）、Layer 3 vector chunks（复用 search_chunks），RRF 融合（k=60）；`data_domain_ids` 限域已支持
- `knowledge/routing.py::route_query()` 返回 `candidate_dds` + `candidate_kbs`（权限过滤后的软路由结果）；`search_chunks()` 已支持 `knowledge_base_ids/query_text/mode/threshold/metadata_filters` 全部透传参数，且 `knowledge_base_ids` 优先于 `data_domain_ids`（`_build_conditions` 内 `if kb_ids: ... elif dd_ids: ...`）
- `/knowledge/search` 无 scope 路径：route_query → 只走 `search_chunks(candidate_kbs)`——图谱层未接入
- `chat_service._retrieve`：软路由路径同样只走 search_chunks；kb_scope 限定路径走 search_chunks
- ontology 模块不在 import-linter independence 域列表 → 自由 import knowledge，无新增 ignore_imports 需求

---

## Phase 2a — 后端接入 + 前端适配

### Task 1 — `knowledge_search()` 增强（前置）

**文件**：`src/earp_server/ontology/search.py`

**改动点**：
1. 新增透传参数（Layer 3 直通 `search_chunks`）：
   ```python
   async def knowledge_search(
       engine, tenant_id, query, *,
       embedding=None, role_id,
       data_domain_ids=None, entity_type_ids=None,
       top_k=5, embedding_dim=None,
       # 新增：
       knowledge_base_ids=None,       # Layer 3 KB 限定（candidate_kbs）
       query_text="", mode="vector",  # hybrid 文本 lane 所需
       threshold=None,                # 向量阈值
       metadata_filters=None,         # 文档级 JSONB 过滤
       eventbus=None,                 # 召回失败可观测
   ) -> list[dict]
   ```
2. Layer 3 调用 `search_chunks` 时透传全部新增参数；Layer 1/2 仍用 `data_domain_ids` 限域（不变）。
   - `knowledge_base_ids` 空时传 `None` → search_chunks 自动回退 `data_domain_ids`（决策 D4，无需额外分支）。
3. profile/graph item **补 `title` 字段**（供 chat context block + citation + 前端消费，避免 `未命名`）：
   - profile：`title = f"{p.get('name', ent['entity_id'])}（实体档案）"`
   - graph：`title = f"图谱：{relation_type_id} → {target_name}"`

### Task 2 — `/knowledge/search` 无 scope 路径集成

**文件**：`src/earp_server/main.py`（`search_knowledge`）

**改动点**（替换现有无 scope 分支）：
```python
if kb_ids is None and req_body.data_domain_ids is None:
    routed = await route_query(engine, tenant_id, query, q_emb, role_id)
    cand_dds = [dd["data_domain_id"] for dd in routed["candidate_dds"]]
    cand_kbs = [kb["knowledge_base_id"] for kb in routed["candidate_kbs"]]
    if cand_dds:
        # 有候选 DD → 三层检索（L1/L2 限 DD，L3 限 KB）
        return await knowledge_search(
            engine, tenant_id, query, embedding=q_emb, role_id,
            data_domain_ids=cand_dds,
            knowledge_base_ids=cand_kbs or None,   # 空 → L3 回退 DD（D4）
            top_k=req_body.top_k, embedding_dim=settings.embedding_dim,
            query_text=req_body.query, mode=req_body.mode,
            threshold=req_body.threshold, metadata_filters=req_body.metadata_filters,
            eventbus=bus,
        )
    # 无候选 DD → 全租户 chunk 兜底（原行为，D4）
    return await search_chunks(..., knowledge_base_ids=cand_kbs or None, ...)
# 显式 scope 路径：保持现状（search_chunks）
```

### Task 3 — `chat_service._retrieve` 软路由路径接入三层

**文件**：`src/earp_server/conversation/chat_service.py`

**改动点**：
1. 无 `kb_scope` 路径：`route_query` → `candidate_dds` + `candidate_kbs` → `knowledge_search`（同 Task 2 语义）；candidate_dds 空 → 全租户 search_chunks 兜底。
2. `kb_scope` 限定路径：保持现状（search_chunks，一期不接三层）。
3. citations 三源转换（决策 D3）：
   - chunk item → 现有 citation 结构（不变）
   - profile item → `{source:"profile", entity_id, entity_type, title, key_facts}`
   - graph item → `{source:"graph", entity_id, entity_type, title}`
4. `_build_context_block`：profile/graph item 用 `title`（Task 1 已补）+ `content` 组装块，与 chunk 块格式一致。

### Task 4 — 权限核对（验证，并入测试）

三层权限一致性断言（设计 §8 治理）：
- profile/graph 层实体按 `data_domain_ids`（= candidate_dds，route_query 已权限过滤）限域
- graph 跨域 target 宽松（决策 D1），源实体必须在许可域
- Layer 3 chunk 走既有 `accessible_roles` + DD 过滤

### Task F1 — 前端 test-retrieval 结果卡 source 徽标

**文件**：`apps/earp-admin/pages/test-retrieval.html`

**改动点**：结果卡渲染兼容混合 item——按 `source` 显示徽标（`profile`→📇实体档案 / `graph`→🕸图谱 / `chunk`→📄文档），chunk_id 缺失时不渲染 `#` 编号；score 用 `rrf_score` 或 `similarity`。

### Task F2 — 前端 chat-edit 引用卡实体/图谱徽标

**文件**：`apps/earp-admin/pages/chat-edit.html`（`appendCitations`）

**改动点**：引用聚合 key 兼容 `source=profile/graph`（无 document_id 时用 `entity_id`）；实体引用显示「📇 实体」徽标 + `title`，图谱引用显示「🕸 图谱」徽标。

---

## Phase 2b — 测试

### Task 5 — `test_ontology_search.py` 扩展

**文件**：`apps/earp-server/tests/test_ontology_search.py`

| 用例 | 断言 |
|---|---|
| 实体命中（seed 实体+facts+profile → 无 scope 查询） | profile/graph 层参与 RRF、实体类问题 P@5 提升 |
| 纯 chunk 查询回归（无实体命中） | = 原 search_chunks 行为（现有用例不回归） |
| 权限（无权限 DD 实体/chunk） | 均不返回（决策 D1 源实体限域） |
| `knowledge_base_ids` 透传 | Layer 3 限定到候选 KB，跨 KB 同 DD 场景正确 |

### Task 6 — `test_chat.py` 扩展

**文件**：`apps/earp-server/tests/test_chat.py`

| 用例 | 断言 |
|---|---|
| chat 软路由路径三层生效 | 实体命中场景 citations 含 profile/graph 来源（决策 D3 形状） |
| 无实体场景回归 | = 原双通道行为 |
| kb_scope 限定路径 | 保持 search_chunks，不接三层（回归） |

### Task 7 — `scripts/verify_ontology.py` 效果评估

**文件**：`scripts/verify_ontology.py`（新建）

- seed 实体图谱 + 实体类问题集（「CNC-01 主轴轴承由谁供应」等 5-8 问）
- 对照纯 vector 基线测 P@5（验收 +10）
- dev 真模型（bge-m3）跑；CI 用 bigram 伪向量跑机制层

---

## Phase 2c — 收尾

### Task 8 — OpenAPI 基线 + import-linter + 全量回归

**文件**：`apps/earp-server/openapi.yaml` + tests

- OpenAPI 基线同步（`/knowledge/search` 响应形状含 `source` 字段）
- import-linter 保持（无新增跨域 import）
- 全量 pytest 回归（现 79 tests + 新增保持绿）

### Task 9 — session-record 更新 + commit

- P2 状态 → 已完成；记 test_routing 弱点顺手修（若 Task 5 触及）；下一步 P3 rerank

---

## 依赖关系

```
Task 1（knowledge_search 增强 + title）
  → Task 2（/knowledge/search）→ Task 5（测试）
  → Task 3（chat 三层）       → Task 6（测试）
Task 2 → F1；Task 3 → F2（前端随对应后端并行）
Task 5/6/F1/F2 并行 → Task 7（verify 脚本，需 Task 1-3 完成）
Task 1-7 → Task 8（回归）→ Task 9（收尾）
```

**建议执行序**：`1 → (2, 3 并行) → (5, 6, F1, F2 并行) → 7 → 8 → 9`

## 验收标准

1. 实体类问题 P@5 高于纯 vector 基线 **+10**（`verify_ontology.py`，dev 真模型）
2. 全量 pytest 回归绿（现 79 + 新增）
3. chat 引用命中率不降（`verify_chat.py` ≥ 80%）
4. 权限一致性：无权限 DD 的实体/chunk 均不返回
5. 行为兼容：无实体命中 = 原 chunk 行为（现有 5/8 用例不回归）
6. import-linter + OpenAPI 基线同步

## 风险提示

1. **行为兼容**：无实体命中时三层退化为纯 chunk（RRF 单通道 = 原 search_chunks 结果）——确保现有用例不回归；有实体命中时结果排序变化属预期
2. **Layer 3 限域语义**：candidate_kbs（KB 限定）vs candidate_dds（DD 限定）——L3 用 KB 限定（复用路由精度），L1/L2 用 DD 限域；search_chunks 的 kb 优先于 dd 已天然实现回退（D4）
3. **RRF 权重**：设计 §11 开放项 4（实体通道命中是否加权）——本次不调权，仅接入；P@5 提升不足时再实验
4. **profile 编译依赖**：Layer 1 依赖 entity_profiles（compile_profile 兜底生成）——无 profile 时现场编译，注意性能（高频实体缓存）
5. **chat 链路回归**：软路由路径行为变化 → verify_chat.py 需跑一遍确认引用命中率不降（实体层加入可能改变 top_k 融合结果）
6. **【tech-debt #10】三层 RRF 是合法 recall 层，缺角色层（2026-08-13 QU v0.3 §8.1）**：Task 1/2 的「三层 RRF 融合」（profile/graph/chunk 文本证据）合法，**非债、无需重构**；后续 Phase D3 叠加「角色层」（capability 结构化行作主证据、答案 vs 引用分层，§9.2），**叠加而非替换**。实施时不得把 capability 结构化行塞进 `_rrf_merge`（唯一真实边界；P2 不涉及 capability，无影响）。
7. **graph 跨域 target 宽松（决策 D1）**：源实体限域 candidate_dds，target 可跨域——治理模块统一收紧前为已知行为，记 tech-debt。

---

## 人工测试指南（2026-08-15 实施完成版）

> 前置：`make migrate` + `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 make api`（API:8000）。
> Seed：跑一次 `scripts/verify_ontology.py` 即完成数据准备（verify-ontology 租户：equipment_data 域 + kb-manual/kb-alarm + 实体 CNC-01/华东一厂/A产线/上海某精机/张工/高温报警 + facts + profile）。

```bash
# token（tenant=verify-ontology, role=verify-role）
TOKEN=$(cd apps/earp-server && .venv/bin/python -c "
import jwt; print(jwt.encode({'sub':'u1','tenant_id':'verify-ontology','role_id':'verify-role','exp':9999999999},'earp-dev-secret-change-in-production',algorithm='HS256'))")
```

### 场景 1：无 scope 三层检索（P2 核心）

```bash
curl -X POST localhost:8000/knowledge/search -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query": "CNC-01 位于哪个工厂", "top_k": 5}'
#   期望：混合 items —— {"source":"profile","title":"CNC-01（实体档案）"...} + {"source":"graph","title":"图谱：located_in → 华东一厂"...}
curl -X POST localhost:8000/knowledge/search -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query": "设备维护保养", "top_k": 5}'
#   期望：全 chunk（无实体命中 = 原行为回归），且带 kb_id/kb_name/similarity
```

### 场景 2：显式 scope（原行为不变）

```bash
curl -X POST localhost:8000/knowledge/search -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"报警阈值","knowledge_base_ids":["kb-alarm"]}'
#   期望：只返回 kb-alarm 的 chunk（无实体层）
```

### 场景 3：路由调试视图

```bash
curl -X POST localhost:8000/knowledge/routing/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 设备报警"}'
#   期望：dd_keyword_hits=["equipment_data"]、candidate_dds/KBs 非空、freshness 无 stale
```

### 场景 4：chat 软路由三层 + 引用（SSE）

```bash
APP_ID=$(curl -s -X POST localhost:8000/chat_apps -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"人工测试助手"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['chat_app_id'])")
# ① 实体命中 → citations 含 profile/graph 来源
curl -N -X POST localhost:8000/chat_apps/$APP_ID/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 的供应商是谁"}'
#   期望：done 事件 citations 含 {"source":"graph","title":"图谱：manufactured_by → 上海某精机"...}
# ② 无实体 → 纯 chunk 引用（kb_id 非空）
curl -N -X POST localhost:8000/chat_apps/$APP_ID/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"报警阈值是多少"}'
```

### 场景 5/6：前端

```bash
cd apps/earp-admin && python3 -m http.server 8080   # 打开 localhost:8080
```
- `pages/test-retrieval.html`：Scope 选「全局」→ 搜 `CNC-01 位于哪个工厂` → 期望结果卡出现 📇实体档案 / 🕸图谱 徽标（场景 5）
- `pages/chat-edit.html`：调试面板问 `CNC-01 的供应商是谁` → 期望「依据」引用卡出现 📇/🕸 徽标（场景 6）

### 场景 7：实体/事实批量导入（模板 + 干跑 + 执行，2026-08-15 新增）

```bash
# ① 下载模板（含说明头 + 示例行，Excel 可直接编辑）
curl -s "localhost:8000/v1/ontology/import/templates" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# ② 干跑校验（不写库，返回逐行错误）：上传 entities.csv + facts.csv
curl -s -X POST "localhost:8000/v1/ontology/import" -H "Authorization: Bearer $TOKEN" \
  -F "entities_file=@entities.csv" -F "facts_file=@facts.csv" -F "dry_run=true" | python3 -m json.tool
#   期望：{"dry_run":true,"entities":{"total":N,"ok":N,"errors":[]},"facts":{...}}
# ③ 确认后执行（写库 + 联动重编涉及实体 profile）
curl -s -X POST "localhost:8000/v1/ontology/import" -H "Authorization: Bearer $TOKEN" \
  -F "entities_file=@entities.csv" -F "facts_file=@facts.csv" -F "dry_run=false" | python3 -m json.tool
# ④ 验证：导入后查 profile 应含新事实
curl -s "localhost:8000/v1/ontology/entities/lookup?q=CNC-01" -H "Authorization: Bearer $TOKEN"
```

### 已知边界（非 bug）

1. 纯中文实体长查询（「A产线由谁负责」）实体层不命中 → 三层退化为纯 chunk——实体识别局限，QU Phase B 范畴
2. 「CNC-01 由哪家供应商制造」的 graph 命中可能被 RRF top-5 截断（graph lane 按 entity_id 排序，与查询无关）——QU Phase C plan_relation 范畴

---
**规划定稿，确认后按执行序开工。**
