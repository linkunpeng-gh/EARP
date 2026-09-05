# 关系类型编辑（源/目标集合 + 名称 + 基数，走审批）设计

> 状态：设计已确认（2026-09-04）｜对应：TBox 审批流（tech-debt #12）+ 2026-09 实体类型数据域变更同线
> 决策记录：对象=**active 关系类型**；语义=**同一谓词共用一条、编辑扩集合**（方案 A）；字段=集合+名称+基数（方案 B）；收窄守护=**禁止移除仍有 active 事实的组合**（方案 a）

## 1. 背景与问题

本体管理页的关系类型建好后**无任何字段编辑路径**（仅 create/deprecate/reactivate；update 预检硬编码"仅支持实体类型"）。relation_type_id 唯一是有意约束（防同义谓词两条记录造成事实/导入/检索/审计歧义）；但用户需要「设备 located_in 工厂」之外再表达「人员 located_in 矿山」时，正路应是**扩展既有 located_in 的源/目标集合**（seed 本就多选建模：源=equipment,sensor,production_line），而非新建重复 id（409）。缺口=缺少受治理的编辑能力。

## 2. 目标与非目标

**目标**
1. active 关系类型可发起「编辑」变更请求（源/目标集合 + 名称 + 基数），走审批流、全程审计。
2. 扩集合（纯加法）无限制；**收窄**受守护：被移除组合仍有 active 事实 → 拒绝。
3. 运行时消费方（导入校验/事实新建/理解关系候选/图谱）实时读到新集合（它们直接读 relation_types 行）。

**非目标**
- 不改 relation_type_id（改语义=停用旧+新建）；不改 status（沿用 deprecate/reactivate）。
- 不做实例/事实级联（编辑只动类型行；存量事实天然保留，收窄守护保证不产生"非法组合"）。
- 关系类型无 updated_at 列 → 不补列（留痕靠 tbox_changes 审批行 + 审计事件）。

## 3. 校验规则（submit 预检 + approve apply 复检，同一函数双处执行）

输入 payload（任一/组合，逗号分隔集合同 create 形状）：`{name?, source_type?, target_type?, cardinality?}`

1. 目标关系类型存在且 `status='active'`。
2. `name` 非空；`cardinality` ∈ {1:1, 1:N, N:1, N:M}（若传）。
3. 集合非空；每个源/目标 id 存在于 `entity_types`（tenant 内，status 任意——允许引用已停用类型）。
4. **收窄守护（方案 a）**：设新集合 = 传入值或现值。存在 active 事实 `f (relation_type_id=R)`，其源实体类型 ∉ 新源 或 目标实体类型 ∉ 新目标（即落将被移除的组合）→ 拒绝并提示「该组合存在 N 条事实，先停用/清理」。
5. 传入字段与现值完全相同（或全未传）→ 「数据未变更」拒绝。

## 4. 数据流

```
submit（action='update', change_type='relation_type', payload 如上）
  → pending → 他人批准（提交者不自审 403 沿用）
  → apply（单事务，approve_change 按 change_type 分流）：
      UPDATE relation_types SET 传入字段（name/source_type/target_type/cardinality）
      → tbox_changes applied
  → 审计 earp.tbox.change.approved（extra 附字段摘要 fields_changed）
```

- `submit_change` 的 update 预检由「仅 entity_type」改为按 change_type 分流：entity_type 走现有数据域校验（回归不动）；relation_type 走 §3。
- 新 helper `_plan_relation_update(conn, tenant_id, target_id, payload) -> {old, new, changed}`：接收已 SET LOCAL 的 conn，供 submit 与 apply 双处复用（校验逻辑唯一来源）。
- apply：`_apply_relation_update(engine, tenant_id, reviewer, change_id, r)` 单事务内复检 + UPDATE + applied；返回 `{change_id, status, fields_changed}`。
- 无新 migration（`tbox_changes.action` CHECK 已含 update）。

## 5. 前端（tbox.html）

- 关系类型表 active 行操作列新增「编辑」入口 → 弹窗：名称输入 + 源类型多选 + 目标类型多选 + 基数下拉（预填现值）→ 提交 `action='update', change_type='relation_type'`，payload 全量四字段。
- 待审批区动作标签按 change_type 区分：entity_type 的 update →「迁移数据域」；relation_type 的 update →「编辑关系」。
- 收窄被拒（409 detail 提示）由 fetchJSON 透出（上轮已支持 detail 透传）。

## 6. 测试

| 层 | 覆盖 |
|---|---|
| 预检 | 关系类型不存在 / deprecated / 空集合 / 源目标 id 不存在 / 非法基数 / 无变更 |
| 收窄守护 | 有 active 事实的组合移除 → 拒绝（submit 与 apply 复检两路径）；无事实组合移除 → 通过；apply 前插入事实 → 批准被拒 |
| 批准链路 | 扩集合 + 改名 + 改基数 → 生效且存量 facts 保留；他人批准 / 自审 403 / reject 沿用 |
| 前端冒烟 | 关系编辑提交 action=update & change_type=relation_type；pending 标签「编辑关系」 |

## 7. 涉及文件

- 后端：`ontology/tbox_service.py`（分流 + `_plan_relation_update` + `_apply_relation_update`）
- 前端：`pages/tbox.html`（编辑入口/弹窗/标签）
- 测试：`test_tbox_approval.py`、`test-tbox-approval-smoke.cjs`
- 文档：本设计

## 8. 风险与影响

- 收窄守护依赖 facts.status/valid_to 语义（active 且未撤）——与 profile/compile 的过滤口径一致。
- 集合编辑后旧约束放宽/收窄只影响**新建**事实与导入校验；存量事实不受影响（守护保证不出现"新建规则禁止、存量仍存在"外的硬冲突：移除被拒即不会出现该窗口）。
- entity_type 数据域 update 语义零改动（回归由既有测试锁定）。
