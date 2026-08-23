# 任务清单 — 能力中心：注册 / 管理（tech-debt #14）

**状态：✅ 已实施（2026-08-21，与「通用能力执行器」合并会话）**
**依据**：tech-debt #14（能力侧 `required_permissions` 无可视化配置入口）+ F3 遗留（capability 节点只认 demo.echo）+ 设计稿 `2026-07-22-capability-four-types-design.md`
**相关**：`capability/registry.py` / `pages/capabilities.html` / `capability.service`（空）
**日期**：2026-08-21

## 目标

1. **能力注册 API**：`POST /capabilities` 从「写死 Register Demo」升级为「按参数注册自定义能力」（capability_id / domain / name / type / input_schema / output_schema / required_permissions / version / execution）
2. **能力管理**：详情 / 更新 / 停用（status=deprecated，不物理删——引用安全）；列表已有 discover（搜索 + 角色过滤）
3. **前端能力中心**：capabilities.html 从「列表 + Register Demo」升级为「新建 / 编辑 / 配参数 schema / 配权限 / 停用」表单
4. **审计 + 门禁**：能力变更落 `earp.capability.*` 审计；写操作 admin 门禁（对齐 connector 先例）
5. **执行方式声明字段**：新增 `execution` JSONB（任务书「通用能力执行器」消费）——本轮先存声明，执行在下一个任务书做
6. **趁此修复 tech-debt #7**：`business_capabilities.capability_id` 单列主键 → 复合主键 `(capability_id, tenant_id)`（跨租户同名能力隔离）

## 现状（已核实，2026-08-21）

- `POST /capabilities`（main.py:501）：写死 `seed_demo_tenant()` 返回 `cap-demo-echo`——无自定义注册
- `GET /capabilities`（main.py:506）：`discover()`（pgvector 语义搜索 + 角色过滤 + LIKE 兜底）
- `capability/` 域：**registry.py**（`_DEMO_CAPABILITY` / `register_demo` / `seed_demo_tenant` / `list_for_planning` / `discover` / `TokenBucketRateLimiter`）+ **service.py 为空**
- `pages/capabilities.html`：仅列表展示 + 「+ Register Demo」按钮
- `business_capabilities` 列（0001:224）：capability_id PK(全局唯一) / tenant_id / domain / name / type CHECK(query|command) / input_schema JSONB / output_schema JSONB / required_permissions TEXT[] / visible_roles TEXT[] / version / status(active 默认)
- **tech-debt #7**：capability_id 单列 PK 跨租户冲突（同一 capability_id 只能属于一个租户——M3/F3 都踩过：cap-demo-echo 被 tenant-demo 占用后其它租户注册 no-op）
- 角色权限门禁（PolicyLayer + Connector.capability.call）已就绪——角色侧 roles 页可配，能力侧 required_permissions 仅 seed 可写（这就是 #14 缺口）
- 权限匹配规则：能力所需 ⊆ 角色所有（全包含）
- 基线：383 tests 全绿

## 决策点（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 能力模型扩展 | 加 `execution` JSONB（默认为空）：`{"adapter": "demo.echo"}`——声明「这个能力怎么执行」（adapter 名 + 参数）。**本轮只存声明 + 校验格式**，执行分派在「通用能力执行器」任务书 |
| D2 | 复合主键 | **趁此修 tech-debt #7**：migration 把 PK 改 `(capability_id, tenant_id)` + 现有单列 PK 数据迁移（tenant-demo 的 cap-demo-echo 归位）。风险：`visible_roles`/`capability_calls`/tbox `capability_entity` 等 FK 引用——需同步改（对齐 data_domains 修复先例 0005） |
| D3 | 端点 | `POST /capabilities` 自定义注册（body: capability_id?/domain/name/type/input_schema/required_permissions/execution）；`PATCH /capabilities/{id}` 更新；`DELETE /capabilities/{id}` → soft-disable（status=deprecated，被 capability_calls/flow 引用仍可读声明但不可用）；`GET /capabilities/{id}` 详情 |
| D4 | 门禁 | 写操作（create/update/delete）admin 角色（对齐 connector/import_rules 门禁 2026-08-18 先例）；读 discover 保持角色可见性 |
| D5 | 审计 | 能力变更落 `earp.capability.registered / updated / deprecated` 事件（entity_type=capability，entity_id=capability_id）——订阅已在 main.py（earp.capability.* → audit_logs，F3 已加） |
| D6 | 校验 | 注册时校验：type ∈ {query, command}；input_schema/output_schema 必须合法 JSON Schema 对象；required_permissions 非空数组；execution 格式合法（adapter ∈ 已知 adapter 白名单，未知仅 warning 不阻断——执行器任务书再严判） |
| D7 | 前端 | capabilities.html：新建弹窗（全字段表单）+ 行内「编辑/停用」+ 详情；权限 required_permissions 用多选/逗号标签编辑；input_schema 用 JSON textarea + 格式校验提示；execution 声明用下拉（adapter 白名单）+ 参数 JSON |
| D8 | 一期不做 | 能力「执行测试」按钮（依赖执行器任务书）；visible_roles 可视化（沿用现可查逻辑）；能力分组/标签 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — migration（复合主键 + execution 列）（0.5-1 天）
**文件**：`migrations/versions/0027_capability_generalize.py`（新）
- `business_capabilities` 加 `execution JSONB NOT NULL DEFAULT '{}'`
- PK 改复合 `(capability_id, tenant_id)`：删单列 PK → 重建（data_domains 0005 先例）；同步引用 `capability_calls.capability_id` / tbox `capability_entity` FK 引用调整
- RLS 不动（已有）；更新 test_migrations EXPECTED_TABLES / test_rls
- 验证：迁移 up/down + 既有 cap-demo-echo 归属 tenant-demo 迁移成功 + tech-debt #7 用例（跨租户同名能力可注册）

### Task 2 — 注册/管理 API（0.5 天）
**文件**：`src/earp_server/capability/service.py`（从空补全）、`main.py`
- `create_capability(engine, tenant, ..., execution)` / `update_capability` / `deprecate_capability` / `get_capability` / `list` (复用 discover)
- 门禁 admin（D4）+ 校验（D6）+ 审计事件（D5）
- 端点：POST/PATCH/DELETE/GET /capabilities（扩展现有 POST）
- 验证：注册新能力（自定义权限/execution）→ GET 列表可见 → PATCH → DELETE 停用；admin 拒绝 403；审计落 audit_logs

### Task 3 — 前端能力中心表单（0.5-1 天）
**文件**：`pages/capabilities.html`
- 新建弹窗：全字段（domain/name/type/capability_id 可选/input_schema JSON/required_permissions 标签/execution 下拉+JSON）
- 行内操作：编辑（PATCH）/ 停用（DELETE）；详情（GET）
- 列表增强：显示 required_permissions / execution 摘要
- 验证：新建 → 列表见 → 编辑 → 停用；坏 JSON 表单中断；前后端校验一致

### Task 4 — 单测 + 集成（0.5-1 天）
**文件**：`tests/test_capability_admin.py`（新）、`tests/test_capability_query.py`（扩展）
- 复合主键：跨租户同名能力各自注册（tech-debt #7 用例）
- service：create/update/deprecate + 校验（type/schema/permissions/execution）+ 审计事件
- 端点：admin 门禁 403 / 422 校验 / 正常 200-201
- 回归：既有 capability discover / flow capability 节点（cap-demo-echo 仍可执行）

### Task 5 — 质量门 + dev 冒烟 + 收尾（0.5 天）
- 全量 pytest + import-linter + OpenAPI 基线同步（新端点）+ ruff/pyright 零新增
- dev 真 API：能力中心页注册一个自定义能力（含权限/execution 声明）→ 列表/详情/停用；审计落库
- FDE 指南补能力中心说明；session-record 补记 + tech-debt #14 标 ✅（#7 一并标 ✅）

## 依赖关系

```
Task 1（迁移）→ Task 2（API）→ Task 3（前端）→ Task 4（测试）→ Task 5（收尾）
Task 3 依赖 Task 2 的端点
「通用能力执行器」任务书可选依赖本任务的 execution 声明（独立排期）
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`

## 验收标准

1. 能力中心可**新建自定义能力**（含 required_permissions / input_schema / execution 声明），列表/详情/编辑/停用全通
2. **跨租户同名能力可注册**（tech-debt #7 复合主键修复，回归用例顶住）
3. 写操作 admin 门禁（403）+ 变更落 earp.capability.* 审计
4. 能力变更不破坏既有 cap-demo-echo 的 flow 执行；全量 383+ 零回归
5. `execution` 声明字段落库（供「通用能力执行器」消费）；tech-debt #14/#7 标 ✅
6. FDE 指南补能力中心操作；dev 冒烟通过

## 风险提示

1. **复合主键影响面**：FK 引用 + 现有 seed 用 `ON CONFLICT (capability_id) DO NOTHING` 需改 `(capability_id, tenant_id)`；capability_calls/tbox 映射表都要动——务必先盘点所有引用列（对齐 data_domains 修复先例，避免回归）
2. **execution 声明 vs 执行器**：本轮只存声明不执行——若 FDE 注册了非 demo 能力但没执行器，flow 里调仍报「无执行 adapter」——需在 FDE 指南注明「注册 ≠ 可执行，通用执行器后续」避免误解
3. **soft-disable 语义**：deprecated 能力被 flow 引用时报「已停用」而非「不存在」（明确区分）
4. **input_schema 校验**：JSON Schema 格式校验需轻量（不引 jsonschema 大库——只查是合法 JSON 对象 + 有 properties 结构即可，其余执行器/调用方兜底）

---
**规划定稿，确认后独立新会话开工。**
