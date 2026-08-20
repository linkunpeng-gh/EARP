# 任务清单 — M3: 中台 importer + Enrichment（PRD-2026-030 M3）

**状态：✅ 已完成（2026-08-20）**——12 Task 全落地，347 passed 全绿（298 基线 + 49 新增），dev 真 API 冒烟全链路通过；验证与遗留见 `arch/session-record.md`（2026-08-20 M3 段）
**依据**：`prd/PRD-2026-030-ontology-layer.md`（§1 M3 功能 #8/#9 + US-09/10 + AC-12/13/14）、`arch/design/2026-08-07-ontology-layer-design.md`（§4.6 ABox 数据源模式 + §6 CSV 兜底 + Phase 2c Enrichment）、`arch/design/2026-08-07-ontology-layer-l3-design-v1.md`（§3.5/§3.6/§4.4）
**关联**：T1 任务书（`tasks/t1-eval-worker-task-breakdown.md`，queue+心跳+stale 模式模板）、tech-debt #11（profile 过期管理已清偿，Enrichment ④ 载体）
**日期**：2026-08-19

## 目标

1. **中台对接**：`POST /v1/ontology/import/connector` 数据源注册（virtual 建元数据 / synced 同步副本）+ 定时同步任务（business_code 增量幂等，queue 消费）+ 真实 REST/DB 取数 adapter + **《中台对接数据契约规范》**（给中台团队的最小契约 + 推荐模板交付物）
2. **Enrichment ①②③**：夜间任务补齐——③ 失效事实清理、① timeline 回填、② 热度统计（降级为报告），与既有 ④（profile 重编）在 scheduler 循环合并
3. **零回归**：CSV 兜底路径（`/import` + entity-import 页）不动；既有 231 tests 全绿

## 现状（已核实，2026-08-19）

- ✅ CSV 导入：`ontology/import_service.py` + `POST /v1/ontology/import`（multipart + dry_run）+ `pages/entity-import.html`
- ✅ Enrichment ④：`entrypoints/scheduler.py` 每 `EARP_ENRICHMENT_INTERVAL_SECONDS`（默认 3600s）`find_stale_profiles` 批量重编（tech-debt #11 D3）
- ✅ 队列载体：`eval_jobs.py` 模板现成——async task 注册、worker 侧 `Settings()` 构造 engine、心跳 `heartbeat_at` + TTL stale 恢复（T1）
- ✅ `entities.source_mode` 列已建（0008，virtual/synced/extracted）；`_log_timeline` 已接（entity.created/updated、fact.added/revoked）——timeline 基础设施已活
- ✅ 素材路径已确认：`executions.result` → citations[].entity_id / PlanResult evidence matched_entity_ids 已流动（planning.py:583、chat_service.py:216-268）——timeline 回填的实例级关联来源
- ❌ 无 `import/connector` / data-sources 端点；无定时同步任务
- ❌ server 无真实取数 adapter：`connector.py` 仅 demo.echo + llm.*；SDK `RESTConnector` 可用但 server 无依赖、`DatabaseConnector` 是 NotImplementedError stub
- ❌ `connector_configs` 表存在（adapter_type/config_ciphertext/status）但**零代码引用**——无管理端点
- ❌ Enrichment ①②③ 未实现
- ⚠️ 基线（2026-08-19 复验，F2 提交后干净树）：**298 passed 全绿**；dev DB 到 **0024**（chatflow F1 已提交 `3d6cd76`）
- ✅ **工作树干净**：chatflow F2 已提交（`50f887f`+`dd84928`），与 M3 文件零重叠已核实（M3 动 ontology/ + scheduler + migration 0025），可开工

## 既定决策（2026-08-19 讨论定稿，勿推翻）

| # | 决策点 | 定稿 |
|:-:|:---|:---|
| D1 | 一期范围 | **synced 主干 + virtual 最小路径**：synced 走完整闭环（注册→同步→幂等 upsert→profile 联动）；virtual 只做 **metric 类型实时取数执行器**（有真实消费者），object 类型 virtual 实时事实**明确排除**（G1 消费语义未定义，留二期） |
| D2 | 对接形态 | migration 0024 加 `import_rules` 表（引用 connector_configs，含 field_mapping/last_synced_at/status）+ `connector_configs` 最小 CRUD（复用 credential_crypto AES-256-GCM）；端点统一 `/v1/ontology/connectors` + `/v1/ontology/data-sources`（见 §API 形状） |
| D3 | Enrichment 顺序 | **③ 失效清理 → ① timeline 回填 → ② 降级为热度报告**（不落标记——Phase 2b 未实现无消费方） |
| D4 | 载体 | **Enrichment ①②③④ 全走 scheduler 循环**（与既有 ④ 同进程同节奏）；**定时同步走 queue（T1 模式）**——触发型 + 重负载，需要心跳/重试 |
| D5 | adapter 落位 | **server 内置轻量 adapter**（`ontology/data_adapter.py`）：REST = httpx 直连（connector.py 已有 httpx 先例）、DB = SQLAlchemy 直连外部库（capability_query 直连先例）；不引 connector SDK 依赖（DatabaseConnector 是 stub 无复用价值） |

### 设计评审补录（G1-G7 落地要点，随任务固化）

- **G1 virtual 边界**：virtual 实体 `entity_type.kind` 必须 = metric（注册时校验）；取数结果不进 facts/不进 RRF，经 live 端点 / plan_fact profile lane 附 value 消费；object 类型 virtual 注册直接 400（一期拒绝）
- **G2 timeline 素材规则**：回填来源 = `executions.result` 的 citations[].entity_id / PlanResult matched_entity_ids（**不用名称匹配**——audit_logs 无实体名，capability_entity_map 是类型级）；event_type 按来源映射（plan_fact→`query.entity`、plan_relation→`graph.entity`、plan_aggregation→`agg.entity`）；幂等去重 source_ref=execution_id（同 execution 只回填一次）
- **G3 热度报告**：与 ① 同源素材（executions.result 实体引用频次 top-N），返回统计不落库
- **G4 失效清理**：批量 revoke 走 `revoke_fact` 完整流程（timeline + audit + updated_at + 写时失效钩子）→ profile 自动 stale → ④ 下一轮重编；只处理 `status='active' AND valid_to < now()`，limit 分批，重复 run 幂等
- **G5 规则落库**：`import_rules` 承载 field_mapping（对齐 MappingRule：name_field/business_code_field/attr_fields/relations）+ incremental 配置（一期全量拉取 + upsert 幂等；since/last_synced_at 透传为 connector 配置可选字段）
- **G6 路径兼容**：`/import`（CSV）保持不动；新增 `/import/connector`；不拆 `/import/csv`（PRD 路径差异在任务书注明，避免前端改动）
- **G7 权限**：virtual 取数在外部系统绕过 RLS，结果按实体 `data_domain_id` 继承分类声明；同步任务逐租户 `tenant_session`；connector/data-sources 写端点 admin 门禁（is_admin，2026-08-18 先例）

## API 形状（对齐 PRD §1 #8）

```
POST   /v1/ontology/connectors                      # connector_configs 创建（adapter_type + 配置加密落库）
GET    /v1/ontology/connectors                      # 列表（不返回配置明文）
PATCH  /v1/ontology/connectors/{id}                 # 配置更新（重加密）
DELETE /v1/ontology/connectors/{id}                 # 停用/删除（被 data-sources 引用时 409）
POST   /v1/ontology/import/connector                # 数据源注册 + 立即同步入队
        # body: {connector_id, entity_type_id, source_mode(virtual|synced), field_mapping, incremental?}
        # 返回: {data_source_id, job_status}（import_rules 落库；synced → enqueue sync）
GET    /v1/ontology/data-sources                     # 数据源列表（含 last_synced_at/status）
GET    /v1/ontology/data-sources/{id}               # 详情（field_mapping/同步历史）
POST   /v1/ontology/data-sources/{id}/sync          # 触发同步（入队；running 中 409）
POST   /v1/ontology/enrichment/run                  # 手动触发 enrichment（调试/测试，PRD §3.7）
```

## Task 拆解（建议执行序 A1 ∥ A2 ∥ A3 → B1 → B2 → B3 → C1 → D1 → D2 → E1 → E2）

### Phase A — 基础设施（A1、A2、A3 可并行）

#### Task A1 — migration 0024 + connector_configs CRUD（0.5-1 天）
**文件**：`migrations/versions/0024_import_rules.py`（新）、`src/earp_server/ontology/connector_service.py`（新）、`routes.py`
- migration 0024：`import_rules` 表（tenant-scoped + RLS 三件套 + 显式 GRANT earp_app）：
  ```
  data_source_id  VARCHAR(64) PK
  tenant_id       VARCHAR(64)
  connector_id    VARCHAR(64) REFERENCES connector_configs
  entity_type_id  VARCHAR(64) REFERENCES entity_types
  source_mode     VARCHAR(16) CHECK (IN ('virtual','synced'))
  field_mapping   JSONB NOT NULL      -- {name_field, business_code_field, attr_fields{}, relations[]}
  incremental     JSONB DEFAULT '{}'  -- {enabled, since_field, page_size}
  status          VARCHAR(16) DEFAULT 'active'
  last_synced_at  TIMESTAMPTZ
  last_sync_status VARCHAR(16)        -- running | completed | failed | interrupted
  created_at / updated_at
  ```
- `connector_service.py`：connector_configs CRUD（配置加密复用 `infra/credential_crypto.py`——**先确认 config_ciphertext BYTEA 与 encrypt() 返回的 {ciphertext,nonce} 格式映射，必要时 migration 列改 JSONB**）；写端点 admin 门禁（is_admin 依赖，2026-08-18 先例）；列表脱敏（不返回明文）
- 验证：test_connector_service（CRUD/加密往返/脱敏/409 引用中/403 非 admin）；RLS 隔离

#### Task A2 — 轻量取数 adapter（0.5-1 天）
**文件**：`src/earp_server/ontology/data_adapter.py`（新）
- `fetch_rest(base_url, path, method, headers, query_params, timeout=30)`：httpx 直连 + Basic/Bearer auth 支持 + 超时/失败抛 ConnectorError（调用方兜底）——connector.py 的 httpx 先例
- `fetch_db(conn_url, table_or_query, columns, where?, limit)`：SQLAlchemy 外部 engine 直连（只读 SELECT，防注入：列/表名白名单校验）；**URL 从 connector 配置解密后取**
- 统一 `DataSourceAdapter.fetch(source_mode, connector_config, params) -> rows[]` 接口——同步与 virtual live 共用
- 验证：test_data_adapter（REST mock httpx：auth/query/超时；DB 用 testcontainers 内建第二 schema 或跳过 DB 用例标二期——**DB 用例可先 mock 引擎层**）

#### Task A3 — 中台对接数据契约规范（0.5 天，与 A1/A2 并行）
**文件**：`arch/guides/earp-data-contract.md`（新，给中台团队看的交付物——「CSV 模板的中台版」；field_mapping 结构与 B1 schema 同源，**先文档后代码**）
- **最小契约（synced 表/视图）**：一个数据源 = 一类实体；`business_code` 列必填（唯一稳定，幂等同步锚点）；名称列必填；建议 `update_time`（增量同步）与 `is_deleted`（软删同步）列
- **最小契约（virtual API）**：GET 端点 + 稳定路径；支持按 business_code 单查或分页全量拉取；JSON 响应（裸数组或 `{data:[...]}` 包装均兼容）；`/health` 连接测试；响应超时 ≤30s（超时 EARP 侧兜底，不假造值）
- **field_mapping 结构定义**：`{name_field, business_code_field, attr_fields{}, relations[]}`；relations 的 `target_field` 语义 = **目标实体 business_code**（反查/创建目标实体后建关系，与 CSV facts 引用方式一致）
- **推荐模板**：设备台账 DM 表示例（DDL）+ 指标 API 示例（URL + 响应 JSON）+ 对应 field_mapping 示例（中台/注册时照抄）
- **dry-run 校验规则**：映射字段存在性/类型、business_code 判重、relation 方向校验（复用 import_service 既有校验逻辑）——B1 实现行为与文档一致
- 验证：文档评审（覆盖上述 6 点）+ B1 dry-run 行为与文档对齐

### Phase B — synced 同步通道（B1 → B2 → B3 串行）

#### Task B1 — 数据源注册端点（0.5-1 天）
**文件**：`src/earp_server/ontology/import_service.py`（扩展）、`routes.py`
- `POST /v1/ontology/import/connector`：校验（connector 存在且 active、entity_type 存在、synced→kind 任意、virtual→kind 必须 metric（G1）、field_mapping 字段引用 entity_type.attributes、DD 继承）→ import_rules 落库（幂等：同 (connector_id, entity_type_id, source_mode) 复用或 409）
- synced → 立即入队 `ontology.sync_data_source`；virtual → 只建元数据不取数
- `GET /v1/ontology/data-sources` + `{id}` 详情 + `POST /{id}/sync`（running 409；入队）
- 验证：test_data_sources（注册校验/幂等/409/virtual 非 metric 400/admin 门禁）

#### Task B2 — 同步任务注册（0.5 天）
**文件**：`src/earp_server/ontology/sync_jobs.py`（新，eval_jobs 模板复制）、`main.py`（lifespan 已建 queue，仅加 worker 侧注册）、`entrypoints/worker.py`
- `@queue.task(name="ontology.sync_data_source")`：payload `{tenant_id, data_source_id}`；worker 侧 `Settings()` 构造 engine；job 内：running 状态 + 每 N 行心跳（`last_synced_at` 刷新或加 heartbeat 列）→ 调同步执行 → completed/failed（异常兜底 + error 记录）
- 卡死恢复：下次触发时前次 `last_sync_status=running` 且心跳旧 → 标 interrupted 再开始（**复用 T1 心跳判定，不必起 worker 启动扫描**——同步是触发型非周期）
- 验证：test_sync_jobs（enqueue → 直调 job → 状态机/幂等/卡死恢复）

#### Task B3 — 同步执行语义（1 天）
**文件**：`src/earp_server/ontology/import_service.py`（`sync_from_connector`）
- 全量拉取（adapter.fetch）→ 逐行 `upsert_entity`（source_mode='synced' + source_ref=data_source_id，business_code 幂等合并）→ 规则生成 facts（confidence=1.0，relations 按 field_mapping）→ **profile 联动重编**（导入后受影响实体 compile_profile，import_service 既有模式）→ timeline 记录（`sync.imported`）→ 发布 `runtime.knowledge.synced` 事件（**注册表登记**，EventBus 4 事件之一）
- 增量（可选字段）：`incremental.since_field` 配置后透传 since=last_synced_at（REST query_params / DB WHERE），一期默认全量
- 返回 `ImportResult`（rows_processed/created/merged/facts_added/errors[]）+ 写回 last_synced_at
- 验证：test_sync_execution（mock adapter 返回行 → 幂等二次同步不重复、facts 正确、profile 联动、事件发布、错误行收集不中断）

### Phase C — virtual 最小路径（C1，可在 B 之后）

#### Task C1 — metric 类型 virtual 实时取数（0.5-1 天）
**文件**：`routes.py`、`abox_service.py`（或 data_adapter 消费者）
- `GET /v1/ontology/entities/{entity_id}/live`：entity.source_mode='virtual'（校验 kind=metric）→ adapter 实时取数 → 返回 `{entity_id, metric_value, fetched_at, connector_id}`；取数失败 → 503 + 日志（不假造值）
- **plan_fact 接入（可选，工作量允许则做）**：profile lane 命中 metric 类型 virtual 实体时附 `live_value`（进 Evidence）——给 virtual 一条真实回答链路；不做则 live 端点即 AC-13 验收载体，链路集成明确写二期
- 验证：test_virtual_live（mock adapter：virtual metric 取数成功/失败 503/非 virtual 400/非 metric 400/RLS 域过滤）

### Phase D — Enrichment ①②③④（D1 → D2 串行）

#### Task D1 — enrichment 模块（1 天）
**文件**：`src/earp_server/ontology/enrichment.py`（新）
- `enrichment_run(engine, tenant_id) -> dict` 按序执行（统计返回）：
  1. **④ profile 重编**：复用 scheduler 既有逻辑（find_stale_profiles + compile_profile）
  2. **③ 失效清理**：`SELECT facts WHERE status='active' AND valid_to < now() LIMIT 200` → 逐条 `revoke_fact`（G4 完整流程）→ 计数 revoked
  3. **① timeline 回填**：近窗（如 7 天）`executions.result` JSONB 提取 citations/evidence entity_id → `INSERT entity_timeline`（event_type 按 G2 映射，source_ref=execution_id，**去重：同 (entity_id, source_ref) 跳过**）→ 计数 timeline_added
  4. **② 热度报告**：同窗实体引用频次 top-N → `hot_missing[]`（仅报告）
- 手动触发端点 `POST /v1/ontology/enrichment/run`（admin 门禁）
- 验证：test_enrichment（伪造 executions.result 素材 → 回填/去重/映射正确；伪造过期 fact → revoked + timeline + profile stale；热度 top-N 正确；重复 run 幂等）

#### Task D2 — scheduler 集成（0.5 天）
**文件**：`entrypoints/scheduler.py`
- `_run_enrichment_once` 从「只重编 profile」改为调 `enrichment_run` 全流程（④③①②）；interval/心跳模式不变；日志输出分项统计
- 验证：test_entrypoints scheduler 冒烟更新 + dev 实测一轮 enrichment 报告

### Phase E — 收尾（E1 → E2）

#### Task E1 — 全量回归 + 验收（0.5 天）
- 全量 pytest（带 `EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 EARP_OLLAMA_CHAT_MODEL=qwen2.5:1.5b`）+ import-linter + OpenAPI 基线同步 + ruff/pyright 零新增
- AC 对表：AC-12（CSV 回归不动）/ AC-13（virtual live + synced 副本，mock adapter）/ AC-14（enrichment_run 三件套 + 统计）/ US-09 / US-10
- **前端零改动**（M3 是 API-only；数据源管理页并入 M4 候选）

#### Task E2 — dev 实测 + 文档（0.5 天）
- dev 真库冒烟：注册 connector（REST mock 或本地 stub 服务）→ import/connector 注册 → 同步入队 → worker 消费 → 幂等二次 → virtual metric live 取数 → 手动 enrichment/run 全流程报告
- FDE 指南补中台对接 + enrichment 说明（§4/§5 新增或追加）；session-record 补记

## 依赖关系

```
Phase A: A1（migration+CRUD）∥ A2（adapter）∥ A3（数据契约文档）可并行；A3 先于 B1 定稿 field_mapping 结构
Phase B: B1（注册端点）→ B2（队列任务）→ B3（执行语义）
Phase C: C1 依赖 A2（adapter）与 B1（import_rules 注册）
Phase D: D1（enrichment 模块）→ D2（scheduler 集成）——与 Phase B/C 独立可并行
Phase E: 全量回归依赖所有 Phase
```

**建议执行序**：`A1 ∥ A2 ∥ A3 → B1 → B2 → B3 → C1 → D1 → D2 → E1 → E2`（D 线可与 B/C 线并行推进）

## 验收标准

1. `POST /v1/ontology/import/connector` 注册 virtual/synced 数据源 → import_rules 落库；virtual 仅 metric 类型放行（object 400）
2. synced 同步经 queue 消费：business_code 幂等（二次同步不重复行）、facts 规则生成 confidence=1.0、profile 联动重编、`runtime.knowledge.synced` 事件发布；running 卡死 → 下次触发标 interrupted
3. virtual 实体 `GET /entities/{id}/live` 实时经 adapter 取数（mock 测试）；取数失败 503 不假造
4. `enrichment_run`（手动 + scheduler 循环）按 ④③①② 执行：过期 facts revoked（完整流程 + 幂等）、timeline 从 executions.result 回填（去重）、热度 top-N 报告，返回分项统计
5. 《中台对接数据契约规范》（`arch/guides/earp-data-contract.md`）产出：覆盖最小契约（表/API）、field_mapping 结构、推荐模板、dry-run 规则，且与 B1 实现行为一致
6. CSV 兜底路径（`/import` + entity-import 页）零改动零回归
7. 全量 pytest 绿（基线 231 + 新增）+ import-linter + OpenAPI 基线同步 + ruff/pyright 零新增
8. dev 实测：注册→同步→live→enrichment 全链路跑通；FDE 指南 + session-record 补记

## 风险提示

1. **工作树在途改动（chatflow F2 进行中）**——**归属策略已拍板（2026-08-19）：等 F2 提交后开工**。与 M3 文件零重叠已核实（M3 动 ontology/ + scheduler + migration 0025，F2 动 connector/chat/orchestrator）；F2 落定后先复验干净树基线（281 全绿）再按执行序开工；若 F2 提交后出现意外文件冲突（不应发生）以 F2 为准重新评估
2. **executions.result 结构未完全定型**（随 QU Phase D/E 演进）——timeline 提取规则做容错：无 citations/evidence 的 execution 跳过，不阻断整轮
3. **virtual 边界蔓延**——object 类型 virtual 实时事实明确排除（G1），任何「virtual 事实进 facts/RRF」的需求走二期评审
4. **connector_configs 加解密格式**——config_ciphertext BYTEA vs credential_crypto {ciphertext,nonce} JSON 需 Task A1 先行确认，必要时列类型调整（migration 0024 内处理，不动存量）
5. **批量 revoke 写放大**——③ 每批 200 条走完整流程（timeline+audit），limit 分批 + 只处理 active，防止长事务
6. **import-linter**——data_adapter 只用 infra（httpx/SQLAlchemy 无新跨域）；connector_service 若需引用 policy（is_admin）按 2026-08-18 roles_service 先例加 ignore 条目
7. **RLS 与外部连接**——adapter 连外部库不经 EARP RLS（数据在外部系统）；virtual 结果权限靠实体 data_domain_id 继承声明，文档明示
8. **测试环境**——DB 取数 adapter 用例 mock 引擎层（testcontainers 单容器不便建第二库）；真实 DB 同步留 dev 实测

---
**讨论定稿，确认后按执行序开工。**
