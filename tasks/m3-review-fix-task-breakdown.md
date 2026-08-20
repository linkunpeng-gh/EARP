# 任务清单 — M3 Review 修复（timeline 数据源 / live 门禁 / sync 心跳竞态）

**状态：✅ 已完成（2026-08-20）**——A/B/C/D/E 五条全落地，351 passed 全绿，verify_m3 timeline_added=9 真实链路验证；详见 `arch/session-record.md`（2026-08-20 Review 修复段）
**依据**：M3 代码 review（2026-08-20，commit e0dbe1e/94d77ac/466f4a8）——2 高 + 2 中问题
**关联**：M3 交付后 review 发现的功能/权限/并发缺陷，修复后 M3 才算真正闭环
**日期**：2026-08-20

## 背景（review 结论摘要）

| # | 严重度 | 问题 |
|:-:|:---:|------|
| A | 🔴 高 | **Enrichment ① timeline 回填是死功能**——`executions.result` 生产链路无 citations（executions 仅 invoke 写、chat 引用在 `messages.citations`、plan-debug 不落库）；测试手工插行掩盖 |
| B | 🔴 高 | **`/entities/{id}/live` 无角色域权限校验**——任何登录角色可读任意 metric virtual 实体实时值（实体层门禁缺口，对照本会话已修 lookup/list） |
| C | 🟡 中 | **sync_jobs 心跳不刷新 `last_synced_at`**——docstring 与实现不符；长同步 > TTL 触发误判「并发恢复」→ 双同步竞态 |
| D | 🟡 中 | 卡死恢复只在「下次触发时」检查（无 worker 启动扫描，比 T1 弱）——并入修复 C |
| E | 🟢 低 | `fetch_rest` 的 `resp.json()` ValueError 未包装（live 500 应 503）——顺手修 |

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| A1 | timeline 数据源 | **`messages.citations` 为主源**（chat 真实引用，source_ref=message_id 去重，event_type 映射复用 `_SOURCE_EVENT`）；`executions.result` 兼容路径**移除**（无真实写入方，避免死代码维护）——若保留需标注「兼容旧数据」 |
| B1 | live 门禁语义 | 实体 data_domain_id ∈ 角色允许域（admin 全权限）；不在域 → **404**（不暴露实体存在性，对齐 get_entity 单实体访问语义）；角色缺失/无授权 fail-closed |
| C1 | 心跳字段 | `_beat` 传 `synced_at=_now()`（刷新 last_synced_at，消除竞态）；不引入新列（last_synced_at 语义即「最后活跃」） |
| D1 | 启动扫描 | `recover_interrupted_sync_all(engine, ttl)` 扫描全部 running 数据源（仿 T1 `recover_stale_runs` 逐租户），worker 启动时调用 |

## Task 拆解（建议执行序 A → B → C → 收尾）

### Task 1 — 修复 A：timeline 回填改 messages.citations（0.5 天）
**文件**：`src/earp_server/ontology/enrichment.py`、`tests/test_enrichment.py`、`scripts/verify_m3.py`
- `enrichment_run` ①：查询近窗 `messages`（`citations IS NOT NULL`）→ 逐条 `_extract_entity_refs(citations)`（适配：messages.citations 是数组，非 `{citations:[...]}` 包装）→ `_add_timeline_once(source_ref=message_id)`
- 移除 executions.result 路径（或保留兼容分支，按 A1 拍板）
- `_extract_entity_refs` 泛化：接受「citations 数组」与「含 citations 字段的 dict」两种形状（容错）
- 测试：真实 chat 链路模拟（messages 落 citations）→ timeline_added > 0 + source_ref=message_id 去重
- verify_m3：enrichment 断言补 `timeline_added > 0`（造真实 messages 素材）

### Task 2 — 修复 B：live 端点角色域门禁（0.5 天）
**文件**：`src/earp_server/ontology/routes.py`、`tests/test_virtual_live.py`
- `entity_live_value_endpoint`：解析角色允许域（`_role_scope_domains` 复用 / roles_service）→ 实体 data_domain_id 不在域 → 404
- admin 全权限（None 不过滤）；角色缺失 → 404（fail-closed）
- 测试：无权限角色 live → 404；admin → 200；本域角色 → 200

### Task 3 — 修复 C+D：心跳刷新 + worker 启动扫描（0.5 天）
**文件**：`src/earp_server/ontology/sync_jobs.py`、`src/earp_server/entrypoints/worker.py`、`tests/test_sync_execution.py`
- `_beat` 传 `synced_at=_now()`（心跳刷新时间戳）
- `recover_interrupted_sync_all(engine, ttl)`：扫描全部 running 数据源 → 心跳旧 → interrupted（逐租户，仿 T1）
- worker 启动：`sync_jobs.register(queue)` 后调 recover_all（失败不阻塞）
- 测试：长同步模拟（last_synced_at 旧 + running）→ 不误判（心跳刷新后新鲜）；崩溃场景 → 启动扫描标 interrupted

### Task 4 — 收尾（0.5 天，含 E 顺手）
**文件**：`src/earp_server/ontology/data_adapter.py`、`scripts/verify_m3.py`、`arch/session-record.md`
- E：`fetch_rest` 捕获 `json.JSONDecodeError` → `ConnectorFetchError`（live 503 语义）
- verify_m3 全链路重跑（含真实 timeline 素材断言）
- session-record 补记 review 结论 + 修复
- 全量 pytest + import-linter + OpenAPI（无变化）+ ruff/pyright 零新增

## 依赖关系

```
Task 1（timeline）→ 独立；Task 2（live 门禁）→ 独立；Task 3（心跳/扫描）→ 独立
三者无依赖可并行；Task 4 收尾
```

**建议执行序**：`(1, 2, 3 并行) → 4`

## 验收标准

1. chat 真实链路产生引用 → enrichment ① timeline 回填 > 0（source_ref=message_id 去重）
2. 无权限角色 live → 404；admin/本域角色 → 200
3. 长同步（>TTL）不被误判并发；进程崩溃后 worker 启动扫描恢复 running
4. verify_m3 全链路含真实素材断言；全量 pytest 绿 + lint 零新增

## 风险提示

1. **messages.citations 体量**：近窗 messages 全扫——chat 高频租户量可能大；先 window_days（默认 7）+ LIMIT 分批，必要时加 citations 索引（二期）
2. **A1 移除 executions 路径**：若未来 QU Phase F 把 plan 执行落 executions，届时再回填该源——勿在本次加回
3. **live 404 vs 403**：404 不暴露实体存在性，但 FDE 排障时会困惑「实体明明在」——文档（FDE 指南 §12 virtual 取数）注明「无权限角色 404 属预期」
4. **心跳竞态修复验证**：需模拟「同步进行中再次触发」的并发场景（test 用直接调 job + 手工改 last_synced_at）

---
**规划定稿，确认后开工（建议下会话）。**
