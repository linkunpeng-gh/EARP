 # Spec 实现状态复核 R2 — P0/P1 修复验证

 > 评审基准: HEAD `e36635b` — docs: #5 Security Spec v1.2 + #6 Tenant Spec v1.3 + tech-debt tracker
 > 未提交改动: `tenant_service.py` + `multi-tenant-isolation-specification-v1.md` (2 files, +12/-8)
 > 评审日期: 2026-07-21
 > 评审范围: r1 中 P0/P1 修复验证 + 新问题发现

 ---

 ## 一、r1 P0 修复验证 — DDL/Service 列名对齐

 **r1 结论: ❌ FAIL — 运行时 BUG，必须修复**  
 **r2 结论: ✅ RESOLVED**

 ### 修复内容

 | 问题 | 修复前 | 修复后 | 状态 |
 |:---|:---|:---|:---:|
 | INSERT 列名 | `role_id` | `current_role_id` | ✅ |
 | INSERT 列名 | `org_unit_id` | 移除 | ✅ |
 | ON CONFLICT SET | `role_id = :rid2` | `current_role_id = :rid2` | ✅ |
 | SELECT 列名 | `role_id, org_unit_id` | `current_role_id, user_id` | ✅ |
 | 函数参数 | `org_unit_id: str = ""` | 移除 | ✅ |
 | 参数 bind | `oid: org_unit_id` | 移除 | ✅ |
 | 文件 docstring | 无列说明 | `Columns: tenant_id, user_id, role_ids TEXT[], current_role_id VARCHAR(64)` | ✅ |

 ### 验证依据

 DDL (`migrations/versions/0001_baseline.py:120-126`):
 ```sql
 CREATE TABLE tenant_account_joins (
     tenant_id       VARCHAR(64) NOT NULL,
     user_id         VARCHAR(64) NOT NULL,
     role_ids        TEXT[] NOT NULL DEFAULT '{}',
     current_role_id VARCHAR(64),
     PRIMARY KEY (tenant_id, user_id)
 );
 ```

 Service (`tenant_service.py:20-22`) 所有列名与 DDL 一一对应。`org_unit_id` 已全面移除。**P0 BUG 已修复，运行时不再报错。**

 ---

 ## 二、r1 P1 修复验证

 ### P1-1: data_scope 落点修正 (Tenant Spec #6)

 **r1 结论: ❌ FAIL — `policy/service.py` 为空存根**  
 **r2 结论: ✅ RESOLVED**

 | 项目 | r1 (错误) | r2 (修正) |
 |:---|:---|:---|
 | 落点路径 | `policy/service.py` (data_scope 过滤) | `orchestrator/layers.py:PolicyLayer.after_step()` (data_scope 过滤) |
 | 状态 | ✅ | ✅ (不变) |

 修正准确。实际实现位于 `orchestrator/layers.py:PolicyLayer.after_step()`，查询 `roles.data_scope` 对 result.output 进行 self/department/org 层级过滤。

 ### P1-2: version byte 状态修正 (Tenant Spec #5)

 **r1 结论: ⚠️ 状态 ✅ 过于乐观**  
 **r2 结论: ✅ RESOLVED**

 | 项目 | r1 (过于乐观) | r2 (修正后) |
 |:---|:---|:---|
 | 状态 | ✅ | ⚠️ |
 | 说明 | Phase 2 格式, Phase 3 扩展已定义 | Phase 2 格式不含 version byte, Phase 3 实现 |
 | 落点 | `credential.py` | `credential.py` (设计注释已定义) |

 修正准确。`credential.py` 实际密文格式为 `base64(nonce[12] || ciphertext[N] || tag[16])`，不含 version byte 前缀。修正后的状态标记和描述反映了真实实现状态。

 ---

 ## 三、新发现问题

 ### NEW-P2: `add_account_join()` 返回 key `role_id` vs 列名 `current_role_id`

 - **文件**: `tenant_service.py:27`
 - **代码**: `return {"tenant_id": tenant_id, "user_id": user_id, "role_id": role_id}`
 - **问题**: 返回字典的 key 为 `role_id`，但数据库列名是 `current_role_id`。这不是运行时错误（函数自主控制 dict key），但 API 契约与 DDL 存在命名不一致。
 - **影响面**: 当前无外部调用方 (`add_account_join` 仅在本文件定义，未被其他模块 import)，修复零成本。
 - **建议**: 同步为 `current_role_id`，保持命名统一。
 - **优先级**: P2 — 命名一致性问题，非 BUG。

 ### MINOR: `role_ids TEXT[]` INSERT 未填充

 - **DDL**: `role_ids TEXT[] NOT NULL DEFAULT '{}'`
 - **INSERT**: 仅设置 `tenant_id, user_id, current_role_id`，未设置 `role_ids`
 - **实际效果**: `role_ids` 保持空数组 `'{}'`
 - **评估**: 功能上可接受 — `current_role_id` 为活跃角色，`role_ids` 为历史/全部角色集合。但 `add_account_join` 作为首个用户-租户关联入口，理应同时初始化 `role_ids = ARRAY[:rid]`。
 - **建议**: Phase 2/3 补充时同步写入 `role_ids`。
 - **优先级**: P3 — 非 r2 修复范围，记录备查。

 ---

 ## 四、汇总

 | 项目 | r1 状态 | r2 状态 | 备注 |
 |:---|:---:|:---:|:---|
 | **P0**: DDL/Service 列名对齐 | ❌ FAIL (BUG) | ✅ RESOLVED | 3 处列名 + 1 参数已对齐 |
 | **P1-1**: data_scope 落点修正 | ❌ FAIL | ✅ RESOLVED | `policy/service.py` → `orchestrator/layers.py` |
 | **P1-2**: version byte 状态修正 | ⚠️ 标记过于乐观 | ✅ RESOLVED | ✅→⚠️，说明如实反映无 version byte 现状 |
 | **NEW-P2**: 返回 key `role_id` 命名一致性 | — | ⚠️ 新增 | 建议同步为 `current_role_id` |
 | **MINOR**: `role_ids` 未初始化 | — | ℹ️ 记录在案 | 功能正常，后续补充 |

 **总结: P0/P1 全部 RESOLVED。新增 1 个 P2 命名一致性建议，无新 BUG。**
 **如果接受 P2 修复建议，追加一次小改动后即可落地。**

 ---

 ## 五、完整 diff 快照

 ```diff
 diff --git a/apps/earp-server/src/earp_server/runtime/tenant_service.py
 +++ b/apps/earp-server/src/earp_server/runtime/tenant_service.py
 @@ -10,17 +11,17 @@
 -    engine: AsyncEngine, tenant_id: str, user_id: str, role_id: str, org_unit_id: str = "",
 +    engine: AsyncEngine, tenant_id: str, user_id: str, role_id: str,

 -                "INSERT INTO tenant_account_joins (tenant_id, user_id, role_id, org_unit_id) "
 -                "VALUES (:tid, :uid, :rid, :oid) "
 -                "ON CONFLICT (tenant_id, user_id) DO UPDATE SET role_id = :rid2"
 +                "INSERT INTO tenant_account_joins (tenant_id, user_id, current_role_id) "
 +                "VALUES (:tid, :uid, :rid) "
 +                "ON CONFLICT (tenant_id, user_id) DO UPDATE SET current_role_id = :rid2"

 -            {"tid": tenant_id, "uid": user_id, "rid": role_id, "oid": org_unit_id, "rid2": role_id},
 +            {"tid": tenant_id, "uid": user_id, "rid": role_id, "rid2": role_id},

 -            text("SELECT tenant_id, role_id, org_unit_id FROM tenant_account_joins WHERE user_id = :uid"),
 +            text("SELECT tenant_id, current_role_id, user_id FROM tenant_account_joins WHERE user_id = :uid"),

 diff --git a/arch/L2/07-tenant/multi-tenant-isolation-specification-v1.md
 +++ b/arch/L2/07-tenant/multi-tenant-isolation-specification-v1.md
 @@ -329,8 +329,8 @@
  | 密文格式 version byte 预留 | ✅ Phase 2 格式, Phase 3 扩展已定义 | ...
 -| 密文格式 version byte 预留 | ✅ Phase 2 格式, Phase 3 扩展已定义 | ...
 +| 密文格式 version byte 预留 | ⚠️ Phase 2 格式不含 version byte, Phase 3 实现 | ...
  | 角色级数据隔离 (data_scope) | ✅ self/department/org/all | `policy/service.py` ...
 -| 角色级数据隔离 (data_scope) | ✅ self/department/org/all | `policy/service.py` ...
 +| 角色级数据隔离 (data_scope) | ✅ self/department/org/all | `orchestrator/layers.py:PolicyLayer.after_step()` ...
 ```
