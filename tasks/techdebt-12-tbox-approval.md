# 任务清单 — tech-debt #12: TBox 审批流

**状态：规划定稿，待开工**
**依据**：`arch/tech-debt.md` #12（P2）+ `arch/design/2026-08-07-ontology-layer-design.md`（§3 TBox 治理）
**关联**：2026-08-16 定级——TBox 所有操作（新增/停用/未来改集合）都应走审批；改集合/ID 已在页面禁用（引用键+级联风险）
**日期**：2026-08-17

## 目标

TBox 变更（实体/关系类型新增、停用、恢复）走**审批流**：
1. **变更请求**：所有变更先提交 draft（tbox_changes 表），审批通过后生效
2. **审计事件**：提交/审批/拒绝/生效写 earp.tbox.* 事件
3. **恢复路径**：已停用（deprecated）类型可提交「恢复」变更 → 审批通过后 re-activate（闭合 tech-debt 2026-08-16 定级时「停用=软终态」的限制）
4. **审批人门禁**：提交者不能审批自己的变更（角色权限细化留 #9 统一接入）

## 既定决策（讨论已对齐，开工前置）

| # | 决策点 | 结论 |
|:-:|:---|:---|
| D1 | 审批流形态 | **变更请求表 `tbox_changes`**（方案 A）：每笔变更一行（change_type/action/target_id/payload/status/requested_by/reviewed_by/review_reason）——请求留痕 + 审计 + 拒绝原因，比直接状态机（draft 改类型表）更完整。entity_types.status 已有 draft 值（预留），但**以 tbox_changes 为审批载体**（类型表 status 由 apply 时改） |
| D2 | 操作范围 | **前端 tbox.html 全走审批**（新增/停用/恢复 → 提交请求 → 审批区处理）；**直接 API（create/deprecate）保留**但标注内部路径（seed/导入校验/verify 脚本用），不删除（改动面最小，FDE 自助入口受控即可达成债务目标） |
| D3 | 审批人 | 一期：**任意用户（≠ 提交者）**可审批——dev/单人团队先有 gate；角色权限门禁（admin 角色 / owner）记 tech-debt，随 #9 角色权限体系统一接入（roles.permissions 无 tbox 权限概念，现状为能力权限列表） |
| D4 | 状态机 | `pending → approved（apply 成功 → applied）｜ rejected`；apply 执行真实变更（create/deprecate/reactivate）后请求标 applied；拒绝保留原因 |
| D5 | 恢复路径 | reactivate = deprecated → active（实体类型/关系类型均可）；entity_types/relation_types 的 status CHECK 已支持 active/deprecated ✓（relation_types 无 draft 但不需——审批载体是 tbox_changes） |

## 现状（已核实）

- `entity_types`：status CHECK 含 `'draft'`（预留）+ owner 列 + PRIMARY KEY (entity_type_id, tenant_id)
- `relation_types`：status CHECK 仅 `active/deprecated`（无 draft——不需改，审批载体在 tbox_changes）
- `tbox_service.create_entity_type`：对已存在（含 deprecated）抛错「已停用请走治理流程」——恢复路径缺 reactivate
- `tbox_service.deprecate_entity_type / deprecate_relation_type`：直接 UPDATE deprecated（幂等）
- `chat_app_service._audit`：bus.publish(CloudEvent(type="earp.chat_app.*")) 审计模式可复用
- 前端 `tbox.html`：新增/停用自助按钮（FDE 在用）
- 基线：172 tests 全绿

---

## Task 1 — migration 0018：tbox_changes 表 + RLS

**文件**：`migrations/versions/0018_tbox_changes.py`（新建）

**改动点**：
```sql
CREATE TABLE tbox_changes (
    change_id      VARCHAR(64) PRIMARY KEY,
    tenant_id      VARCHAR(64) NOT NULL,
    change_type    VARCHAR(16) NOT NULL CHECK (change_type IN ('entity_type','relation_type')),
    action         VARCHAR(16) NOT NULL CHECK (action IN ('create','deprecate','reactivate')),
    target_id      VARCHAR(64) NOT NULL,
    payload        JSONB NOT NULL DEFAULT '{}',
    status         VARCHAR(16) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','approved','applied','rejected')),
    requested_by   VARCHAR(64) NOT NULL,
    reviewed_by    VARCHAR(64),
    review_reason  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at    TIMESTAMPTZ
);
```
- RLS 三件套（tenant_id policy + FORCE）同 0008；显式 GRANT earp_app（queue_schema 不覆盖升级新表，对齐 0014 先例）
- 索引：ix_tbox_changes_status (tenant_id, status)

## Task 2 — tbox_service 审批流函数

**文件**：`src/earp_server/ontology/tbox_service.py`

**改动点**：
1. `submit_change(engine, tenant_id, user_id, *, change_type, action, target_id, payload=None) -> dict`：
   - 校验：change_type/action 合法；create 时 target_id 不与现有 active 冲突（复用 create 校验）；payload 完整（create 的 name/kind/source_type 等）
   - INSERT pending → 返回 change_id
2. `list_changes(engine, tenant_id, *, status=None) -> list[dict]`：审批区列表（pending 优先）
3. `approve_change(engine, tenant_id, reviewer, change_id) -> dict`：
   - 校验 pending + reviewer ≠ requested_by（403）
   - apply 真实变更：
     - create（entity_type/relation_type）→ 复用现有 create 函数（成功后类型 active）
     - deprecate → 现有 deprecate 函数
     - reactivate → 新 `reactivate_entity_type` / `reactivate_relation_type`（UPDATE status='active'，幂等——deprecated 才生效）
   - apply 成功 → 请求 status='applied' + reviewed_by + reviewed_at + 审计
4. `reject_change(engine, tenant_id, reviewer, change_id, reason) -> dict`：pending → rejected + reason + 审计
5. `reactivate_entity_type` / `reactivate_relation_type`（D5 恢复路径）

## Task 3 — 审计事件 + routes

**文件**：`src/earp_server/ontology/routes.py` + `tbox_service.py`

**改动点**：
1. 审计（复用 bus.publish 模式，eventbus 从 request.app.state.bus 或注入）：
   - `earp.tbox.change.submitted`（submitted_by）
   - `earp.tbox.change.approved`（reviewed_by + applied target）
   - `earp.tbox.change.rejected`（reviewed_by + reason）
   - source="earp-server/ontology"
2. routes（`/v1/ontology/tbox/...`）：
   - `POST /v1/ontology/tbox/changes`（提交，body: {change_type, action, target_id, payload}）
   - `GET /v1/ontology/tbox/changes`（列表，?status=）
   - `POST /v1/ontology/tbox/changes/{change_id}/approve`
   - `POST /v1/ontology/tbox/changes/{change_id}/reject`（body: {reason}）

## Task 4 — 前端 tbox.html 审批流适配

**文件**：`apps/earp-admin/pages/tbox.html` + `js/app.js`（如需要）

**改动点**：
1. 「新增实体类型/关系类型」按钮 → 打开模态后提交为**变更请求**（不再直接 POST create）——模态加说明「提交后需审批生效」
2. 行操作「停用」→ 提交 deprecate 变更请求（确认框说明走审批）
3. **恢复路径**：已停用类型行加「恢复」按钮 → 提交 reactivate 请求
4. 新增「待审批」区（顶部或独立 panel）：list_changes(pending) 渲染 → 每条显示 请求人/类型/动作/目标/时间 + 「批准 / 拒绝（原因）」按钮（审批人 ≠ 请求人时可用）
5. 保留「显示已停用」开关；提交成功后刷新 + 提示「已提交审批」

## Task 5 — 测试 `test_tbox_approval.py`

**文件**：`apps/earp-server/tests/test_tbox_approval.py`（新建）

| 用例 | 断言 |
|---|---|
| 提交 create → approve → 生效 | 请求 applied + entity_types 含 active 类型 |
| 提交 create → reject | 类型不存在 + 请求 rejected + review_reason |
| 停用走审批 | deprecate 请求 approve → 类型 deprecated |
| 恢复路径 | reactivate 请求 approve → 类型回 active（再停用→恢复闭环） |
| 自己审自己 | 403/400（reviewer == requested_by） |
| 重复/非法提交 | create 已存在 id → 提交被拒（校验在 submit） |
| list_changes 过滤 | status=pending 只返回 pending |
| 审计事件 | mock bus 断言 submitted/approved/rejected 事件类型 |

## Task 6 — 收尾

- 全量 pytest 回归（172 + 新增）+ import-linter + OpenAPI 基线 + ruff/pyright 零新增
- session-record 更新（#12 清偿）+ commit

---

## 依赖关系

```
Task 1（migration）→ Task 2（服务函数）→ Task 3（routes + 审计）→ Task 4（前端）
Task 2-4 → Task 5（测试）→ Task 6（收尾）
```

**建议执行序**：`1 → 2 → 3 → (4, 5 并行) → 6`

## 验收标准

1. TBox 变更（新增/停用/恢复）全部走审批流（前端入口）；直接 API 保留但前端不再直接调用
2. 审批通过后真实生效（create/deprecate/reactivate），请求状态 applied
3. 恢复路径闭环：deprecated → reactivate 请求 → 审批 → active
4. 审计事件 earp.tbox.change.* 三类型
5. 提交者不能审批自己
6. 全量 pytest 绿 + import-linter + OpenAPI + ruff/pyright 零新增

## 风险提示

1. **直接 API 保留的双轨**：create/deprecate 仍可绕过审批（脚本/API 直调）——债务目标「前端受控」达成，彻底封禁需删 API 或加权限门禁（留 #9 角色体系）。任务书明示：直接路径标注「内部/seed/脚本」
2. **reactivate 的引用安全**：恢复已停用类型时，其引用（实体/facts/capability map）仍在（deprecated 是软状态，facts 保留）——恢复无级联风险；改集合/ID 仍禁用（引用键）
3. **审批人身份**：一期不校验角色（任意非提交者）——多人误审批风险存在，记 tech-debt（随 #9 统一）。dev 单用户环境：测试用两个 user（u1 提交 / u2 审批）模拟
4. **前端变更影响 FDE 流程**：tbox 自助从「即时生效」变「提交-审批」——tbox.html 需明确提示；FDE 指南 §类型管理 同步更新
5. **audit bus 注入**：ontology routes 现无 eventbus 注入点——approve/reject 端点从 request.app.state 取 bus（看 main.py 是否有 app.state.bus）；无 bus 时审计静默跳过（chat_app_service 同模式）

---
**规划定稿，确认后按执行序开工。**
