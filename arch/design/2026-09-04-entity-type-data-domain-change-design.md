# 实体类型数据域变更（审批流 + 实例级联 + 一致性约束）设计

> 状态：设计已确认（2026-09-04）｜评审人：本体管理功能使用者（Admin）｜对应模块：`ontology`（TBox/ABox）
>
> 决策记录：本设计经 4 轮澄清确认——对象=**TBox 实体类型**；存量=**级联迁移实例**（方案 B）；治理=**走审批流新增 `update` 动作**（方案 A）；一致性=**服务层强制对齐**（方案 A）。

## 1. 背景与问题

本体管理页（TBox）的实体类型带 `data_domain_id`（数据域）属性。当前**不存在修改路径**：

- 类型变更仅支持 `create / deprecate / reactivate` 三个动作（`tbox_changes.action` 有 DB CHECK 约束），全部走审批流（tech-debt #12）；
- 无 update 动作、无更新服务函数、无路由、无前端入口 → 「想改数据域，改不了」。

数据域是**角色可见性的安全边界**（角色的 `data_domain_access` 白名单按数据域授权，实体层检索/取数 fail-closed 按实例的 `data_domain_id` 过滤）。把一个类型从 A 域搬到 B 域 = A 域角色失去、B 域角色获得访问 → 属**治理+审计**型操作。

## 2. 现状与关键事实（已核准）

| 事实 | 说明 |
|---|---|
| 两个独立数据域字段 | `entity_types.data_domain_id`（类型级）与 `entities.data_domain_id`（实例级）各自落库，**运行时权限门禁读实例字段** |
| 类型域为数据源链路的事实标准 | 数据源同步/虚拟实体取数：`import_service` 中 `dd_id = et.get("data_domain_id")`——同步产生的**源实体**天然跟随类型域 |
| 现存不一致源 ×3 | ① 实体管理页新建：数据域为**自由下拉**，可与类型不一致；② CSV 导入：`data_domain_id` 逐行填，可与类型不一致；③ **同步关系目标实体**：`import_service` 行 498 目标实体创建时误用**源类型**的域（应落目标实体**自己类型**的域） |
| profile 联动 | `entity_profiles` 读时 freshness（tech-debt #11 D2）：`last_change = GREATEST(entity_timeline MAX, facts.updated_at MAX, entities.updated_at)`，`compiled_at` 过期即重编译。**级联 bump `entities.updated_at` 即自动覆盖，无需批量重编译** |
| 目标域校验口径 | `data_domains` 表（0005）有 `status`（默认 `active`）；校验口径与 `roles_service._validate_domain_access` 一致：须存在且 `status='active'` |
| tbox_changes | `action` CHECK `('create','deprecate','reactivate')`；payload JSONB 可承载新域，**无需新表新列** |

## 3. 目标与非目标

**目标**

1. 本体管理页可对 active 实体类型发起「数据域变更」，走审批流（提交 → 他人批准 → 生效），全程审计。
2. 审批通过时**级联**：类型域 + 该类型名下 active/deprecated 实例域同步迁移（merged 吸收行除外）。
3. 从根上保证「实例数据域 ≡ 所属类型数据域」：实体写入一律以类型域为准，杜绝今后分叉。

**非目标（本迭代不做）**

- 不提供实例批量独立迁移工具（存量不一致由改域动作收敛；如需独立对账脚本另行立项）。
- 不改动关系类型（无数据域字段）、`capability_entity_map`、`data_domains` 本身。
- 不新增「撤回（withdraw）」动作（沿用现有 reject 作为提交者清理路径）。
- 不改审批人角色门禁与「提交者不自审」语义（沿用，见 2026-09 前一轮修复）。

## 4. 设计

### 4.1 审批数据流（动作 `update`）

```
提交（POST /tbox/changes, action='update', payload={data_domain_id: 新域}）
  → pending（预检通过）
  → 他人批准（tbox.approve / is_admin；提交者不自审 → 403，沿用）
  → apply（单事务，tbox_service.approve_change 新增 update 分支）：
      ① UPDATE entity_types  SET data_domain_id=:new, updated_at=now()
         WHERE entity_type_id=:t AND tenant_id=:tid
      ② UPDATE entities SET data_domain_id=:new, updated_at=now()
         WHERE entity_type_id=:t AND tenant_id=:tid
           AND status IN ('active','deprecated')          -- merged 不随迁
      ③ UPDATE tbox_changes SET status='applied', reviewed_by, reviewed_at
  → 审计 earp.tbox.change.approved（沿用；extra 含 domain_from/domain_to/entity_count）
```

- ①②③ 若中途失败 → 整体抛错，请求保持 pending 可重试（沿用 create 语义）。
- ② 的 `updated_at` bump 使名下 profile 读时过期 → 下次读取自动重编译（含新域），无批量重编译。
- 拒绝路径原样（pending → rejected + reason，域不变）。

### 4.2 校验规则

**提交预检（submit_change 新增 update 分支）**——不满足即 `ValueError`（路由映射 409）：

1. `change_type` 必须 `entity_type`（关系类型无数据域）。
2. 目标类型存在且 `status='active'`（deprecated 类型需先 reactivate 再改域）。
3. `payload.data_domain_id` 必填、非空。
4. 新域 ≠ 当前域（同域 → 「无变更」拒绝）。
5. 新域存在且 `data_domains.status='active'`。

**apply 时复检**同预检（防提交后、批准前目标被改/被停用/域被删）；失败 → 抛错保持 pending。

### 4.3 数据库迁移（1 个，无新表新列）

`tbox_changes.action` CHECK 放宽：

```sql
ALTER TABLE tbox_changes DROP CONSTRAINT IF EXISTS tbox_changes_action_check;
ALTER TABLE tbox_changes ADD CONSTRAINT tbox_changes_action_check
  CHECK (action IN ('create','deprecate','reactivate','update'));
```

（0008/0018 先例：内联 CHECK 自动命名 `tbox_changes_action_check`，显式 drop+add 幂等。）

### 4.4 一致性约束落点

**服务层（核心，`abox_service.upsert_entity`）**

- 实体写入（insert 与 merge-update 两路径）的 `data_domain_id` **一律取所属类型的 `data_domain_id`**（同连接先查 `entity_types`）。
- 调用方显式传入的值：**与类型域一致 → 放行**；**不一致 → 抛错拒绝（fail-fast，400/409 语义）**，错误信息引导省略该字段。省略 → 自动取类型域。
- 兼容性：`EntityIn.data_domain_id` 字段保留（老客户端不受影响）；服务端以类型域为唯一事实。

**同步链路顺带修正（行为变更，须知会）**

- `import_service` 同步中**关系目标实体**创建改为落**目标实体自己类型**的域（当前误用源类型域 → 现存不一致源 ③，本设计修掉）。

**CSV 导入**

- `ENTITIES_TEMPLATE` 去掉 `data_domain_id` 列（列 = `entity_type_id,name,business_code[,attributes]`）。
- 旧模板兼容：头部仍含 `data_domain_id` 时照常解析，但**逐行校验**——与类型域一致放行、不一致报行错（不静默错位）。

**实体管理页（entities.html）**

- 新建弹窗移除数据域自由下拉 → 只读提示「数据域随类型」。
- 列表「数据域」列与按域筛选保留（收敛后 ≡ 类型域，查询语义不变）。

### 4.5 前端交互

**本体管理页（tbox.html）**

- 实体类型表 active 行操作列新增「**改域**」入口（deprecated 行不提供）。
- 弹窗：类型 ID/名称 + 当前域 + 新域下拉（仅 active 数据域）+ 级联影响提示「该类型名下 N 条实体将随迁」——N 由**提交接口响应**返回（`entity_count`，提交预检时一并统计）。
- 提交 `POST /tbox/changes`（`action='update'`），响应含 `entity_count`（预计随迁实例数）与 `domain_from`。
- 待审批区：`actLabel` 增加 `update → 迁移数据域`；批准/拒绝逐行逻辑沿用（own/can_approve/can_reject）。
- 批准后刷新即生效（类型列表数据域列、实体列表数据域列一致）。

**数据源（改动受控）**

- 后端 `POST /tbox/changes`（`submit_change`）在 update 动作预检时统计级联规模，响应返回 `entity_count` 供确认文案与审计使用。

### 4.6 接口与审计

- `POST /v1/ontology/tbox/changes`：入参不变（action 新增合法值 `update`）；**提交响应**增返 `entity_count`（预计随迁实例数）与 `domain_from`（随 `submit_change` 预检统计）。
- 审计事件沿用 `earp.tbox.change.submitted/approved/rejected`；approved extra 增补 `domain_from/domain_to/entity_count`。

## 5. 边界与假设（评审点）

1. **merged 实例不随迁**（已被吸收的冗余行，不在 active/deprecated 生命期内）。
2. **deprecated 类型不可直接改域**（先 reactivate，同样走审批）；若评审认为应允许，改动仅限预检删一条。
3. 显式传不一致域 → **拒绝**（fail-fast），非静默纠正——防止 API 客户端误传被无声覆盖。
4. 同步关系目标实体域改为**自身类型域**：属行为修正，需在发布说明/变更记录中明示。
5. 存量已不一致的实例（历史上手工/CSV 造成）：**不单独对账**，由任意一次改域动作收敛；如需一次性对账脚本列为二期。

## 6. 测试

| 层 | 覆盖 |
|---|---|
| 迁移 | `tbox_changes.action` CHECK 放宽可 upgrade/downgrade（`test_migrations` 模式沿用） |
| 审批流（`test_tbox_approval.py` 新增） | 提交预检 6 条（change_type/类型不存在/deprecated/同域/域不存在或非 active）；批准链路：造 active+deprecated+merged 三类实例 → 改域批准 → 类型 + active/deprecated 实例域变、merged 不动、profile 读时重编译含新域；自审 403 沿用；reject 原样 |
| 一致性（abox/import） | upsert 不传域 → 取类型域；传一致 → 通过；传不一致 → 拒绝；同步目标实体落自身类型域（回归 ③） |
| CSV | 无域列模板正常导入；旧模板带列：一致放行 / 不一致行报错 |
| 前端冒烟（cjs） | 「改域」提交 `action=update`；待审批 update 标签渲染；确认文案含级联提示 |

## 7. 涉及文件（预估）

- 迁移：`migrations/versions/0047_*.py`（1 个，CHECK 放宽）
- 后端：`ontology/tbox_service.py`（submit 预检 + approve apply update 分支 + entity_count）、`ontology/abox_service.py`（upsert 对齐）、`ontology/import_service.py`（模板/目标实体域）、`ontology/routes.py`（提交响应透传 entity_count/domain_from）
- 前端：`pages/tbox.html`（改域入口/弹窗/标签）、`pages/entities.html`（去下拉）
- 测试：`test_tbox_approval.py`、`test_ontology_import.py`（或新增 abox 一致性用例文件）、`test-tbox-approval-smoke.cjs`
- 文档：本设计 + `tasks/` 任务书（参照 `tasks/techdebt-12-tbox-approval.md` 格式）；`arch/tech-debt.md` **无需**新增（新功能非债项）

## 8. 风险与影响

| 影响 | 说明 | 缓解 |
|---|---|---|
| 权限即时变更 | 批准后旧域角色立失、新域角色立得可见性 | 治理兜底（审批+审计）；确认弹窗明示级联范围 |
| 同步行为修正 | 关系目标实体域变更为自身类型域 | 变更记录明示；回归测试锁定 |
| API 兼容 | `EntityIn.data_domain_id` 保留但语义变为「须与类型一致，否则 400」 | 老客户端传一致值不受影响；错误信息引导 |
| CSV 兼容 | 模板去列 + 旧列逐行校验 | 模板版本号/说明更新；行错可定位 |
