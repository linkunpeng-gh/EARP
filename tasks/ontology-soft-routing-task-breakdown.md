# 任务清单 — P2: Ontology 接入软路由（A3）

**状态：待确认后开工（新会话）**
**依据：`arch/design/2026-08-07-ontology-layer-design.md`（§7 三层流水线）+ `-l3-design-v1.md`（§3.3 三层检索）+ `arch/design/2026-08-09-enterprise-retrieval-design.md`（软路由 §3/§6）**
**关联：session-record P2（A3 ontology 接入软路由：候选 DD 限域喂给三层检索，图谱能力生效）**
**日期：2026-08-11**

## 现状（已核实）

- `ontology/search.py`：`knowledge_search()` 三层检索已实现——Layer 1 实体→Compiled Truth profile、Layer 2 图谱多跳（graph_query）、Layer 3 vector chunks（复用 search_chunks），RRF 融合（k=60）；`data_domain_ids` 限域已支持
- `knowledge/routing.py`：`route_query()` 返回 `candidate_dds` + `candidate_kbs`（权限过滤后的软路由结果）
- `/knowledge/search` 无 scope 路径：route_query → **只走 `search_chunks`（candidate_kbs 限定）**——图谱层未接入（2026-08-09 决策「ontology 三层检索留未来」= 本次实施）
- `chat_service._retrieve`：软路由路径同样只走 search_chunks
- ontology 模块不在 import-linter independence 域列表 → 自由 import knowledge，无新增 ignore_imports 需求

## Phase 2a — 后端接入

| # | Task | 关联设计 | 涉及文件 | 预估 |
|:-:|:-----|:------:|:---------|:----:|
| 1 | `knowledge_search()` 增强：Layer 3 支持 `knowledge_base_ids` 透传（复用 route_query 的 candidate_kbs 限定 chunk；Layer 1/2 实体层用 `data_domain_ids` 限域）——候选 DD 限域喂三层 | 设计 §7.1/§3.3 | src/earp_server/ontology/search.py | 中 |
| 2 | `/knowledge/search` 无 scope 路径集成：route_query → candidate_dds + candidate_kbs → `knowledge_search`（三层融合）；无候选 DD（fallback）→ 保持全租户 search_chunks；**实体无命中时自然只剩 chunk 层**（RRF 单通道=原行为，兼容回归） | §7.1 集成点 | src/earp_server/main.py | 中 |
| 3 | `chat_service._retrieve` 软路由路径接入三层（同 Task 2 语义；kb_scope 限定路径保持现状，一期不接） | §7.3 Chat/Agent | src/earp_server/conversation/chat_service.py | 小 |
| 4 | 权限核对：profile/graph 层实体按 DD 过滤（现有 `data_domain_ids` 已带权限过滤语义），Layer 3 chunk 走既有 accessible_roles + DD 过滤——三层权限一致性验证 | 设计 §8 治理 | 验证（并入测试） | 小 |

## Phase 2b — 测试

| # | Task | 关联设计 | 涉及文件 | 预估 |
|:-:|:-----|:------:|:---------|:----:|
| 5 | pytest `test_ontology_search.py` 扩展：实体命中场景（seed 实体+facts+profile → 无 scope 查询 → profile/graph 层参与 RRF、实体类问题 P@5 提升）；纯 chunk 查询回归（无实体命中 = 原行为）；权限（无权限 DD 实体/chunk 均不返回） | 验收「实体类 P@5 高于纯 vector +10」 | apps/earp-server/tests/test_ontology_search.py | 中 |
| 6 | pytest `test_chat.py` 扩展：chat 软路由路径三层生效（实体命中场景 citations 含 profile/graph 来源或回答引用实体档案）；无实体场景回归 | §7.3 | apps/earp-server/tests/test_chat.py | 中 |
| 7 | `scripts/verify_ontology.py`：效果评估——seed 实体图谱 + 实体类问题集（「CNC-01 主轴轴承由谁供应」等 5-8 问），对照纯 vector 基线测 P@5（验收 +10）；dev 真模型跑 | 设计 §9 验收指标 2 | scripts/verify_ontology.py | 中 |

## Phase 2c — 收尾

| # | Task | 关联设计 | 涉及文件 | 预估 |
|:-:|:-----|:------:|:---------|:----:|
| 8 | OpenAPI 基线同步 + import-linter + 全量回归（现 79 tests 保持绿） | 仓库惯例 | apps/earp-server/openapi.yaml + tests/ | 中 |
| 9 | session-record 更新 + commit（P2 状态 → 已完成，下一步 P3 rerank） | 仓库惯例 | arch/session-record.md | 小 |

## 依赖关系

- Task 1 → 2/3（knowledge_search 增强前置）
- Task 2 → 5（/knowledge/search 行为测试）
- Task 3 → 6（chat 链路测试）
- Task 7 独立（效果评估，需 dev 真模型 + 实体种子）
- Task 1-7 → 8（回归）
- **建议执行序：1 → (2,3 并行) → (5,6 并行) → 7 → 8 → 9**

## 风险提示

1. **行为兼容**：无实体命中时三层退化为纯 chunk（RRF 单通道 = 原 search_chunks 结果）——确保现有 5/8 用例不回归；有实体命中时结果排序变化属预期
2. **Layer 3 限域语义**：candidate_kbs（KB 限定，权限已路由层过滤）vs candidate_dds（DD 限定）——Task 1 决策 Layer 3 用 KB 限定（复用路由精度），Layer 1/2 用 DD 限域；实施时验证跨 KB 同 DD 场景
3. **RRF 权重**：设计 §11 开放项 4（实体通道命中是否加权）——本次不调权，仅接入；P@5 提升不足时再实验
4. **profile 编译依赖**：Layer 1 依赖 entity_profiles（compile_profile 兜底生成）——无 profile 时需现场编译，注意性能（高频实体缓存）
5. **chat 链路回归**：软路由路径行为变化 → verify_chat.py 需跑一遍确认引用命中率不降（实体层加入可能改变 top_k 融合结果）

---
**确认后开始 P2 编码（新对话按此计划执行）。**
