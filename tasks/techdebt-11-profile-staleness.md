# 任务清单 — tech-debt #11: profile 过期管理

**状态：规划定稿，待开工**
**依据**：`arch/tech-debt.md` #11（P2）+ `arch/design/2026-08-07-ontology-layer-design.md`（§4 Compiled Truth / §4.3 enrichment）
**关联**：QU v0.3 recall 层 profile lane 依赖——事实变更后 profile 提供旧事实会污染回答
**日期**：2026-08-17

## 目标

修复 profile 无过期管理的四项缺失：
1. **写时失效**：add_fact / revoke_fact / upsert_entity 变更后重编译涉及实体 profile（现有：facts 变了 profile 不重算）
2. **读时 freshness 校验**：get_entity_profile 对比 compiled_at vs 实体/事实最近变更时间，过期即重编译（现有：有就返回，哪怕过期）
3. **entity_timeline 写入**：facts/entities 变更写 timeline（现有：全库无 INSERT，stats.recent_events 恒 0）
4. **scheduler enrichment**：周期扫描重编译过期/缺失 profile（现有：scheduler idle，惰性编译只兜缺失不兜过期）

## 既定决策（讨论已对齐，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | 写时失效实现 | **直接重编译**（非 dirty 标记）：add_fact/revoke_fact 对 source+target、upsert_entity 对本实体——仅当该实体**已有 profile**（get_entity_profile 非 None）时重编译（无 profile 实体由惰性编译兜底，避免浪费）；实体量 < 万级，重编译 = 2-3 个 SQL，可接受 |
| D2 | freshness 校验位置 | **集中在 get_entity_profile**（单点）：一次查询该实体的「最近变更时间戳」（entities.updated_at ∪ facts created_at/valid_to 变更 where source/target = 实体）vs profile.compiled_at → 过期则 compile_profile 并返回新值；knowledge_search 的 profile lane 复用该函数（自动获得校验） |
| D3 | scheduler enrichment | **定期扫描重编译**（规则聚合，非 LLM summary）：scheduler tick 每 HOUR 扫描一次——无 profile 或 compiled_at < 最近变更的实体批量重编译；LLM 生成 summary（M2 范畴）不在本期 |
| D4 | timeline 事件 | 新增 `_log_timeline` helper：event_type ∈ {entity.created/entity.updated/fact.added/fact.revoked} + payload + source_ref；供 stats.recent_events 消费 |

## 现状（已核实）

- `abox_service.py`：`add_fact`（INSERT facts）、`revoke_fact`（UPDATE status=revoked）、`upsert_entity`（merge/insert）、`compile_profile`（规则聚合 + UPSERT entity_profiles）、`get_entity_profile`（SELECT profile，**无 freshness 校验**）
- `entity_profiles`：entity_id UNIQUE + profile JSONB + profile_version + compiled_at ✓（字段齐全）
- `entity_timeline`：表已建（event_type/payload/occurred_at/source_ref），**全库无 INSERT**
- `facts`：valid_from/valid_to/status/created_at——revoke 用 status 软删（valid_to 仍 NULL）
- `search.py::knowledge_search` Layer 1：`get_entity_profile` → None 时 `compile_profile`（惰性兜底）——但**不校验过期**
- `entrypoints/scheduler.py`：idle 循环（TICK_SECONDS=1.0），无业务逻辑
- 基线：164 tests 全绿

---

## Task 1 — 写时失效钩子 + timeline 写入

**文件**：`src/earp_server/ontology/abox_service.py`

**改动点**：
1. 新增 `_invalidate_profiles(engine, tenant_id, entity_ids: list[str])`：
   - 对每个 entity_id：get_entity_profile 非 None → compile_profile（重编译）；None → 跳过（惰性兜底）
2. 新增 `_log_timeline(engine, tenant_id, entity_id, event_type, payload, source_ref)`：
   - INSERT entity_timeline（entity_timeline_id = `tl-{uuid}`，occurred_at = now()）
3. 钩子接入：
   - `add_fact`：写后 `_invalidate_profiles([source, target])` + `_log_timeline(source, "fact.added", {relation_type_id, target_entity_id}, fact_id)`
   - `revoke_fact`：写后 `_invalidate_profiles([source])` + `_log_timeline(source, "fact.revoked", {...}, fact_id)`（revoke 需要先查 fact 拿 source）
   - `upsert_entity`（merge 分支）：写后 `_invalidate_profiles([eid])` + `_log_timeline(eid, "entity.updated", {changed: [...]}, source_ref)`；insert 分支：`_log_timeline(eid, "entity.created", ...)`
4. 幂等/异常：钩子失败（如编译 SQL 错）不影响主操作（try/except + logger.warning）——写事实是主操作，profile 重编译是补偿

## Task 2 — 读时 freshness 校验（get_entity_profile 集中式）

**文件**：`src/earp_server/ontology/abox_service.py`

**改动点**：
1. `get_entity_profile` 增强：返回前做 freshness 校验
   - 查询实体最近变更：`GREATEST(entities.updated_at, (SELECT MAX(facts.created_at) FROM facts WHERE source_entity_id=:eid OR target_entity_id=:eid))`（revoke 变更时 facts.updated_at？facts 无 updated_at——revoke 是 status 变更，查 `MAX(created_at)` 不覆盖 revoke。加：facts 变更时间戳用 created_at + 一个 status_changed 时间？**facts 表无 updated_at 列**——revoke 后 created_at 不变 → freshness 检测不到 revoke！）
   - **方案**：facts 表加 `updated_at TIMESTAMPTZ` 列（migration 0017）+ add_fact/revoke_fact 写时更新——或 freshness 用 entity_timeline（Task 1 已写 timeline，occurred_at 即变更时间）：`MAX(entity_timeline.occurred_at WHERE entity_id=:eid)` vs compiled_at——**timeline 是最佳 freshness 源**（每次变更都写）！
   - 决策：freshness = `MAX(entity_timeline.occurred_at)` vs `profile.compiled_at`；timeline 空（存量实体无 timeline）→ 回退 `MAX(facts.created_at)` + `entities.updated_at`（GREATEST）
2. 过期判定：`compiled_at < last_change` → compile_profile 返回新 profile（并更新 profile_version）
3. `search.py::knowledge_search` Layer 1 不变（复用 get_entity_profile 自动获得校验）——仅当 get_entity_profile 返回 None 时惰性编译（现有逻辑）

## Task 3 — scheduler enrichment（周期扫描重编译）

**文件**：`src/earp_server/entrypoints/scheduler.py` + `src/earp_server/ontology/abox_service.py`

**改动点**：
1. `abox_service.py` 新增 `find_stale_profiles(engine, tenant_id, *, max_n=100) -> list[str]`：
   ```sql
   SELECT e.entity_id FROM entities e LEFT JOIN entity_profiles p ON p.entity_id = e.entity_id
   WHERE e.tenant_id = :tid AND e.status = 'active'
     AND (p.entity_id IS NULL  -- 无 profile
          OR p.compiled_at < COALESCE((SELECT MAX(t.occurred_at) FROM entity_timeline t WHERE t.entity_id = e.entity_id), e.updated_at))
   LIMIT :n
   ```
2. scheduler 加 enrichment tick：每 HOUR（ENV `EARP_ENRICHMENT_INTERVAL_SECONDS`，默认 3600）扫描 `find_stale_profiles` 每租户 → compile_profile 批量重编译
   - 租户列表：`SELECT tenant_id FROM tenants`（无 RLS 顶层表）
   - scheduler 进程独立于 API（entrypoints/scheduler.py 已存在，`make scheduler` 目标？看 Makefile——有 scheduler 目标吗？之前 grep Makefile 没看到 scheduler。补 Makefile 目标或沿用 python -m）
3. 日志：每轮报告重编译实体数

## Task 4 — 测试 `test_profile_staleness.py`

**文件**：`apps/earp-server/tests/test_profile_staleness.py`（新建）

| 用例 | 断言 |
|---|---|
| add_fact 写时失效 | seed 实体+profile → add_fact → get_entity_profile 返回的 key_facts 含新事实（自动重编译） |
| revoke_fact 写时失效 | revoke 后 profile key_facts 不含被撤销事实 |
| upsert_entity merge 写时失效 | 改名后 profile name 更新 |
| 读时 freshness（timeline 覆盖） | 直接改 facts（绕过钩子模拟存量）→ get_entity_profile 过期重编译 |
| timeline 写入 | add_fact/revoke/upsert 后 entity_timeline 有对应 event_type；compile_profile 的 stats.recent_events > 0 |
| find_stale_profiles | 无 profile 实体 + 过期 profile 实体被扫出；新鲜 profile 不扫出 |
| scheduler enrichment 冒烟 | 直接调 enrichment 函数 → 过期实体被重编译（不真跑进程） |

## Task 5 — 收尾

- 全量 pytest 回归（164 + 新增）+ import-linter + ruff/pyright 零新增
- session-record 更新（#11 清偿）+ commit

---

## 依赖关系

```
Task 1（写时失效 + timeline）→ Task 2（freshness 依赖 timeline 写入）→ Task 3（stale 扫描依赖 timeline）
Task 1-3 → Task 4（测试）→ Task 5（收尾）
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`

## 验收标准

1. add_fact/revoke_fact/upsert_entity 后 profile 自动重编译（写时失效）
2. 存量过期 profile（无 timeline 或 timeline 更新）读时自动重编译（freshness 校验）
3. entity_timeline 有写入（recent_events > 0）
4. scheduler enrichment 周期扫描重编译 stale profile
5. 全量 pytest 绿 + import-linter + ruff/pyright 零新增
6. 性能：profile lane 每次检索多 1 个 SQL（timeline MAX 查询）——实体 < 万级可接受，不 gate

## 风险提示

1. **facts 无 updated_at**：revoke 变更依赖 timeline 感知——Task 1 的钩子必须保证 revoke 也写 timeline；存量已 revoke 数据（无 timeline）靠「回退 GREATEST(facts.created_at, entities.updated_at)」部分感知（created_at 早于 revoke 时刻——若 profile 在 revoke 之后编译，freshness 判断 compiled_at > created_at → 认为新鲜 → 漏检）。缓解：migration 0017 给 facts 加 updated_at + 写时更新，作为更可靠 freshness 源（timeline 为主，facts.updated_at 回退）
2. **写时重编译成本**：批量导入（import_service）逐个 add_fact 会多次重编译——import_service 可批量失效（一次 compile_profile 多实体）或接受当前成本（实体量小）。一期 import_service 不动（其 profile 联动已存在），如测试发现慢再优化
3. **scheduler 与 API 并发**：enrichment 重编译与请求读并发——compile_profile 是 UPSERT（ON CONFLICT DO UPDATE），幂等，无锁问题
4. **freshness 查询频次**：get_entity_profile 每读 1 次多 1 个 SQL（timeline MAX）——QU profile lane 每检索读 N 个 profile → N 个 SQL。可接受（top_k 小）；优化方向（批量 JOIN）留后续

---
**规划定稿，确认后按执行序开工。**
