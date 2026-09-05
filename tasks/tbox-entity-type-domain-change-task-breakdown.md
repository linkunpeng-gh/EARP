# 任务清单 — 实体类型数据域变更（审批 update 动作 + 实例级联 + 一致性约束）

**状态：设计已确认（2026-09-04），任务书定稿待开工**
**依据**：`arch/design/2026-09-04-entity-type-data-domain-change-design.md`（本文所有决策的唯一事实源）
**关联**：tech-debt #12 TBox 审批流（`tbox_changes` 状态机）；2026-09 前端修复（list 逐项 `own/can_approve/can_reject`）；tech-debt #11 profile 读时 freshness
**日期**：2026-09-04

## 目标

1. 本体管理页可对 **active 实体类型**发起「数据域变更」→ 走审批流（新动作 `update`）→ 他人批准后生效
2. 审批通过时**级联**：类型域 + 名下 active/deprecated 实例域同步迁移（merged 不随迁）；profile 靠读时 freshness 自动覆盖（无需批量重编译）
3. **一致性根治**：实体写入一律以所属类型数据域为准（`upsert_entity` 对齐）；顺带修正同步关系目标实体误用源类型域的隐藏 bug

## 既定决策（讨论已对齐，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | 对象 | **TBox 实体类型**（`entity_types.data_domain_id`），非实体实例 |
| D2 | 存量处理 | **级联迁移实例**（方案 B）：类型 + active/deprecated 实例同迁；merged 吸收行不迁 |
| D3 | 治理路径 | **走审批流**（方案 A）：`tbox_changes` 新增 `action='update'`（payload 带新域）；提交者不自审 403 沿用 |
| D4 | 一致性 | **服务层强制对齐**（方案 A）：`upsert_entity` 写入取类型域；显式传不一致值 → fail-fast 拒绝；省略 → 自动取类型域 |
| D5 | deprecated 类型 | 不可直接改域（先 reactivate 再改）；同域提交 → 拒绝「无变更」；目标域须存在且 `data_domains.status='active'` |
| D6 | 同步修正 | 数据源同步中**关系目标实体**改为落自身类型域（修复现存不一致源 ③） |
| D7 | CSV | 模板去掉 `data_domain_id` 列；旧模板带列 → 逐行校验（一致放行/不一致行错），不静默错位 |
| D8 | 存量对账 | 不做一次性对账脚本（靠改域动作自然收敛）；只读对账查询列为二期 |

## 现状（已核实，与设计文档 §2 一致）

- `tbox_changes.action` CHECK：`('create','deprecate','reactivate')`（0018 内联 CHECK，自动命名 `tbox_changes_action_check`）
- `submit_change`：action 白名单校验 + create 预检 + INSERT pending（payload JSONB）
- `approve_change`：门禁（tbox.approve/is_admin）→ 提交者不自审 403 → 按 action 调 create/deprecate/reactivate（各自独立连接提交）→ UPDATE applied
- `abox_service.upsert_entity`：`data_domain_id` 参数直写（insert）/ `COALESCE(:dd, data_domain_id)`（merge-update）——**可写与类型不一致的值**
- 调用方：`routes.py` POST /entities（EntityIn.data_domain_id）、`import_service` CSV execute（行 dd）、同步源实体（类型域 dd_id）、**同步关系目标实体（误用源类型域 dd_id —— 不一致源 ③）**
- `ENTITIES_TEMPLATE` 列含 `data_domain_id`；导入解析按列取 et/name/code/dd
- profile：读时 freshness（`compiled_at < GREATEST(timeline MAX, facts.updated_at MAX, entities.updated_at)`）→ 级联 bump `entities.updated_at` 即覆盖
- `_role_scope_domains` / live 取数 / 检索按**实例** `data_domain_id` 过滤（fail-closed）——级联后权限即时生效
- 前端 tbox.html：待审批区逐行 own/can_approve/can_reject（2026-09 已修）；实体类型行操作仅 停用/恢复；entities.html 新建弹窗有数据域自由下拉（m-dd）
- 基线：25 passed（test_tbox_approval + test_ontology）；`test-entities-smoke.cjs` **既有失败**（与本任务无关，勿误判回归）

---

## Task 1 — migration 0047：放宽 tbox_changes.action CHECK

**文件**：`migrations/versions/0047_widen_tbox_change_action.py`（新建；编号以实际 head 为准）

**改动点**：
```sql
-- upgrade
ALTER TABLE tbox_changes DROP CONSTRAINT IF EXISTS tbox_changes_action_check;
ALTER TABLE tbox_changes ADD CONSTRAINT tbox_changes_action_check
  CHECK (action IN ('create','deprecate','reactivate','update'));
-- downgrade：恢复原约束（drop + add 旧 CHECK）
```
- 无新表新列；RLS/GRANT 不动（表已就绪）
- `test_migrations` EXPECTED_TABLES **不变**（无表增减）；确认迁移链 upgrade→downgrade 通过

## Task 2 — tbox_service：submit 预检 + approve apply（update 分支）

**文件**：`src/earp_server/ontology/tbox_service.py`

**改动点**：
1. `submit_change`：
   - action 白名单加 `'update'`；`_get_tbox_row(engine, tid, "entity_types", target_id)` 预检分支：
     - 类型不存在 → `ValueError("实体类型不存在: ...")`
     - `status != 'active'` → `ValueError(... 已停用，请先提交 reactivate 恢复后再改域)`
     - `payload.data_domain_id` 缺失/空 → `ValueError("update 缺少 data_domain_id")`
     - 新域 == 当前域 → `ValueError("数据域未变更: ...")`
     - 新域存在且 active：`SELECT 1 FROM data_domains WHERE tenant_id=:tid AND data_domain_id=:dd AND status='active'`，无 → `ValueError("目标数据域不存在或未启用")`
   - **返回扩展（仅 update 动作）**：`{"change_id", "status":"pending", "domain_from": 旧域, "entity_count": 随迁实例数}`；其余动作返回不变（兼容既有断言）
   - entity_count = `SELECT count(*) FROM entities WHERE tenant_id=:tid AND entity_type_id=:t AND status IN ('active','deprecated')`
2. `approve_change` apply 新增 `elif r.action == "update":` 分支——**单连接单事务**（不复用独立连接函数）：
   ```
   conn: SET LOCAL tenant
   复检：类型存在且 active；目标域 active（同 submit 口径；不查同域——幂等 UPDATE 无害）
   UPDATE entity_types  SET data_domain_id=:new, updated_at=now()
     WHERE entity_type_id=:t AND tenant_id=:tid
   UPDATE entities SET data_domain_id=:new, updated_at=now()
     WHERE entity_type_id=:t AND tenant_id=:tid AND status IN ('active','deprecated')
   UPDATE tbox_changes SET status='applied', reviewed_by=:r, reviewed_at=now() ...
   conn.commit()
   ```
   - 返回扩展：`{"change_id", "status":"applied", "domain_from", "domain_to", "entity_count"}`
   - apply 前需要 r.payload 的 data_domain_id；payload 是 JSONB text → `json.loads`（对齐 create 分支既有 `p = r.payload` 用法，先确认该字段解析形态再实现）
3. docstring 更新（update 语义 + 级联 + merged 排除）

## Task 3 — abox_service.upsert_entity：按类型域对齐（核心一致性）

**文件**：`src/earp_server/ontology/abox_service.py`

**改动点**：
1. insert 与 merge-update 两路径：**同连接先取类型域** `SELECT data_domain_id FROM entity_types WHERE entity_type_id=:et AND tenant_id=:tid`（复用既有 conn，不额外开连接）
2. 落库值规则：
   - 调用方 `data_domain_id=None` → 落类型域（类型无域则 NULL）
   - 显式传入 == 类型域 → 落类型域（放行）
   - 显式传入 ≠ 类型域（含类型无域却传了值）→ **抛 `ValueError`**（fail-fast；文案引导「数据域以类型为准，请省略该字段」）
   - merge-update 的 `COALESCE(:dd, data_domain_id)` 改为直接写对齐值（顺带纠正历史不一致实例）
3. docstring 更新（数据域唯一事实 = 类型域；2026-09 语义变更）
4. 影响审计：既有调用方全部传「类型域或 None」→ 无破坏；`routes.py` EntityIn 兼容不动

## Task 4 — import_service：模板去列 + 旧列校验 + 同步目标实体域修正

**文件**：`src/earp_server/ontology/import_service.py`

**改动点**：
1. `ENTITIES_TEMPLATE` 表头：去掉 `data_domain_id`（列 = `entity_type_id,name,business_code[,attributes]`）
2. 解析（dry_run + execute 两路径一致）：
   - 新模板：按新列序解析
   - **旧模板兼容**：头部仍含 `data_domain_id` → 保留列解析但不再下传；逐行校验行 dd == 该行类型域（预取 `type→dd` 映射一次），不一致 → 该行报错（`data_domain_id 与类型数据域不一致`），不静默错位
   - execute 调 `upsert_entity` 一律 `data_domain_id=None`（服务层对齐，Task 3）
3. **同步关系目标实体修正（不一致源 ③）**：行 ~498 目标实体创建去掉 `data_domain_id=dd_id`（改为 None → upsert 自动取目标类型域）
4. 同步源实体（行 ~471）保持传类型域（等价于 None，可顺手统一为 None——实现择一，行为一致）
5. 模板/说明文案更新（导入模板下载接口返回新模板）

## Task 5 — routes + 审计透传

**文件**：`src/earp_server/ontology/routes.py`

**改动点**：
1. `submit_tbox_change`：成功响应原样返回（Task 2 已在返回里带 domain_from/entity_count）；审计 submitted extra 保持（或补 payload 摘要——实现择一，事件已含 target/action）
2. `approve_tbox_change`：`_audit_tbox` extra 由 `{"status": ...}` 扩展为补 `domain_from/domain_to/entity_count`（从 result 取，缺失容忍——兼容非 update 动作）
3. TboxChangeIn/TboxRejectIn 不变；OpenAPI 预计无变化（body 字段为 str，无枚举约束）

## Task 6 — 前端

**文件**：`apps/earp-admin/pages/tbox.html`、`apps/earp-admin/pages/entities.html`

**tbox.html**：
1. 实体类型表 active 行操作列新增「**改域**」链接（deprecated 行不显示）→ `showDomainModal(t)` 弹窗：类型 ID/名称 + 当前域只读 + 新域下拉（DDS 仅 active）+ 说明「名下实体将随迁，审批通过后生效」
2. 提交：`POST /tbox/changes {change_type:'entity_type', action:'update', target_id, payload:{data_domain_id}}`；成功 alert **「已提交变更请求，预计 N 条实体将随迁」**（N = 提交响应 `entity_count`）→ loadPending/loadEt
3. 待审批区 `actLabel` 增加 `update:'迁移数据域'`；目标列补显示 `→ 新域`（payload.data_domain_id）；approved/rejected 展示沿用
4. 确认文案含级联提示（数量以提交后响应为准）

**entities.html**：
1. 新建弹窗移除数据域自由下拉（m-dd）→ 只读提示「数据域随类型：X」；类型选择变化时联动更新 X（TYPES 元素含 data_domain_id）
2. `saveEntity` body 去掉 `data_domain_id`
3. 列表「数据域」列/筛选保留不动

## Task 7 — 测试

**后端**：
- `tests/test_tbox_approval.py` 新增（沿用 _seed 结构）：
  - 提交预检：relation_type 拒绝 / 类型不存在 / deprecated 类型 / 同域 no-op / 目标域不存在 / 目标域非 active（各 1 断言 ValueError）
  - update 链路：造类型 + active/deprecated/merged 三类实例 → submit（断言 domain_from/entity_count）→ 他人批准 → 类型域变 + active/deprecated 实例域变 + **merged 不变** + 请求 applied
  - 自审 403 沿用（现有用例已覆盖同函数，无需重复）
  - reject 原样（域不变）
- upsert 一致性（放 `tests/test_ontology.py`，app_engine fixture）：
  - 不传域 → 取类型域（insert + merge-update 两路径）
  - 传一致 → 放行；传不一致 → ValueError
  - 类型无域 + 显式传值 → ValueError
- 导入（`tests/test_ontology_import.py`）：新模板无域列导入成功（实例域 = 类型域）；旧模板带列：一致放行 / 不一致行报错
- 同步目标实体域回归：同步场景下目标实体 `data_domain_id` == 目标类型域（不一致源 ③）
- 迁移：`tests/test_migrations.py` 链 upgrade→downgrade 通过（表集合不变）

**前端冒烟**：`apps/earp-admin/test-tbox-approval-smoke.cjs`
- 「改域」提交调 `/tbox/changes`（POST, action=update 可见于 body 或调用记录）
- 待审批行 update 标签渲染（actLabel）
- 确认/成功文案含级联字样（如存在断言点）
- 注意：`test-entities-smoke.cjs` 为既有失败，不在本任务范围（勿新增该文件的依赖）

## Task 8 — 收尾与验证

1. 全量 `pytest` 绿（基线 25+ 新增）；`import-linter`、ruff、pyright 零新增
2. OpenAPI 基线：预计无变化（如需再生成 `openapi.yaml`）
3. dev 真库冒烟（tenant-demo）：u1 提交改域 → u2（审批员）批准 → 验证：类型与实例域一致迁移、`/v1/ontology/tbox/changes` 逐项 own/can_approve 正确、profile 检索结果含新域（读时 freshness）
4. 文档：`arch/design/2026-09-04-entity-type-data-domain-change-design.md`（已定稿）+ 本任务书；FDE 指南（§类型管理/实体管理）如涉及自助路径说明则同步更新；`arch/tech-debt.md` **无需**新增（新功能非债项）
5. 行为变更明示（同步目标实体域修正、显式不一致 400）写入任务书收尾备注/发布说明

---

## 依赖关系

```
Task 1（migration）→ Task 2（service 审批）→ Task 3（upsert 对齐）→ Task 4（import）
Task 3 → Task 5（routes，依赖 submit/approve 返回扩展）
Task 2/4 → Task 6（前端，依赖 submit 响应 entity_count）
Task 1-6 → Task 7（测试）→ Task 8（收尾）
```

**建议执行序**：`1 → 2 → 3 → 4 → 5 → 6 → 7 → 8`（Task 3/4 可先于 2 无碍，但迁移先行）

## 验收标准

1. tbox.html 可对 active 类型提交「改域」变更请求；待审批区显示 update 动作（迁移数据域）
2. 他人批准后：类型域 + active/deprecated 实例域一致迁移；merged 不变；`earp.tbox.change.approved` 审计含 domain_from/to/entity_count
3. 自审 403、拒绝路径、预检 6 条全部生效（409/错误文案友好）
4. `upsert_entity` 写入实例域 ≡ 类型域；显式不一致 → fail-fast；CSV 新模板无域列、旧模板不一致行报错
5. 同步关系目标实体域 = 自身类型域（回归锁定）
6. 全量 pytest 绿 + import-linter + ruff/pyright 零新增；OpenAPI 无变化

## 风险提示

1. **级联的权限即时性**：批准即改实例域——旧域角色立即失去可见性。治理兜底（审批 + 审计 + 确认提示）；dev 冒烟用 u2 审批验证角色域过滤
2. **同步行为修正**：关系目标实体域变更可能让旧同步数据与历史不同——只影响后续写入的域标签；历史不一致靠级联收敛（D8）
3. **merge-update 语义变化**：`COALESCE(:dd, data_domain_id)` → 强制对齐——会把老不一致实例在下次更新时纠正为类型域（预期内，符合 D4）
4. **CSV 旧模板**：带 dd 列且值不一致的行将报错——文案需可定位（行号 + 原因）
5. **CHECK 约束名**：若历史环境约束名非默认（手工建的），`IF EXISTS` drop 兜底；实施时先查 `pg_constraint` 实名校验

---
**规划定稿，确认后按执行序开工。**
