# EARP Catalog Phase 1 人工验证测试方案

> 版本：v1.0  
> 日期：2026-09-03  
> 适用对象：FDE、交付测试、产品验收、后端联调人员  
> 测试目标：确认 Catalog Phase 1 在**隔离的 Mock/Test 环境**中能够完成受控语义引用的登记、治理、解析和页面操作闭环。  
> 重要结论：本方案通过，不等于生产上线通过。真实源系统、真实 owner、真实 Pack hash 和生产调度尚未就绪的项目，必须保留 readiness HOLD。

---

## 1. 先读这一页：本次测试测什么、不测什么

### 1.1 本次要验证的能力

把 Catalog 想成“已盖章业务词典的索引和门禁”。本次人工测试要确认：

1. FDE 能登记来自权威源的**精确版本**引用；系统自行校验 hash，用户不能伪造 hash。
2. 已登记引用可以组成平台、行业、企业三层 Pack；Pack 的发布要经过申请、审批、履约。
3. Profile 可以限制业务范围、数据域和治理角色。
4. 已发布 Pack 可以生成 Manifest 预览；只有签署材料正确时才能激活。
5. 激活后 Resolver 只返回当前租户、数据域和 Manifest 内的准确引用；不满足条件时拒绝。
6. 无权限、跨租户、撤销、签署材料篡改等场景不会被悄悄放行。
7. 5 个 Catalog 页面能清晰展示可操作内容或明确的 readiness HOLD，不伪造数据。

### 1.2 本次明确不作为“通过”依据的内容

以下内容尚处于生产 HOLD；看到空列表、禁用按钮或 readiness HOLD 是**预期保护行为**，请记录为“待生产接入验证”，不要提缺陷：

- 真实指标、单位、时间窗口、规则模式、绑定模板的列表和编辑；
- 真实 Source Adapter、真实 pull 调度、真实 webhook 密钥和通知通道；
- 真实 Pack version/content hash 与真实 JQMK 初始引用；
- 业务 owner/RACI 的最终确认；
- `suspected_missing` 的人工确认、墓碑和生产 LKG 告警演练；
- 缓存 TTL/容量、outbox 消费/死信等运行增强能力。

不要用生产租户、客户真实数据、生产 token 或生产 webhook secret 执行本方案。

---

## 2. 测试前准备

### 2.1 环境检查

测试负责人在开始前逐项确认。任一项未完成，停止测试并先解决环境问题。

| 检查项 | 怎样确认 | 通过标准 |
|---|---|---|
| 隔离环境 | 地址明确标为 test / staging，且使用独立租户 | 不是生产环境 |
| 服务可用 | 登录 EARP Admin，页面可正常打开 | 无全局错误页 |
| 数据库迁移 | 由部署人员确认 Catalog migration 已执行 | Catalog 页面打开不因表缺失报错 |
| Mock/Test Adapter | 部署人员提供一个测试来源系统名称和至少两条已发布对象 | 可登记指定测试引用 |
| 签署材料 | 测试负责人准备一份与预览 Manifest 精确匹配的有效 attestation，以及一份篡改副本 | 可分别用于正向和负向测试 |
| 测试记录 | 建立缺陷单/测试记录表，能贴截图和 correlation ID | 每个用例可追踪 |

### 2.2 测试账号与权限

不要多人共用同一个账号。至少准备以下 5 个账号；用户 ID 必须不同。

| 代号 | 建议权限 | 用途 |
|---|---|---|
| U1 申请人 | `ecmc.catalog.read`、`ecmc.catalog.request` | 登记引用、建 Pack 草稿、提交发布申请、撤销引用 |
| U2 审批人 / Pack owner | `ecmc.catalog.read`、`ecmc.catalog.approve` | 审批 U1 的 Pack 发布申请 |
| U3 Manifest 发布人 | `ecmc.catalog.read`、`ecmc.catalog.manifest.publish` | 建 Profile、预览并激活/撤销 Manifest |
| U4 只读用户 | 仅 `ecmc.catalog.read` | 验证可查看、不可写 |
| U5 无权用户 | 不授予 Catalog 权限 | 验证 403 拒绝 |
| U6 租户 B 用户（可选但强烈建议） | 与 U4 类似，属于另一个测试租户 | 验证跨租户不可见 |

> U1 与 U2 必须是不同的**用户 ID**。即使两人显示名相同、拥有不同角色，也不能用同一个用户 ID 代替。

### 2.3 测试数据卡

不要自行猜测 stable ID、版本或 hash。部署/后端负责人应在测试开始前填写并签字确认下表；下文以“对象 A/B”称呼它们。

| 项目 | 对象 A | 对象 B |
|---|---|---|
| 来源系统名称 | `________________` | `________________` |
| kind | `________________` | `________________` |
| stable ID | `________________` | `________________` |
| 精确版本 | `________________` | `________________` |
| 数据域 | `________________` | `________________` |
| 权威 hash（只用于核对，不在 UI 输入） | `________________` | `________________` |

建议用一个 `unit` 和一个 `metric`；两个对象都必须处于 active 状态，且属于同一测试数据域。

本方案使用下列测试名称，避免与历史数据混淆。若已存在，请在末尾加本次日期或批次号。

```text
Profile ID:          cat-u1-profile-<批次>
Catalog Profile ID:  test.enterprise.<tenant>.production
平台 Pack:           cat-u1-platform-<批次>@1.0.0
行业 Pack:           cat-u1-industry-<批次>@1.0.0
企业 Pack:           cat-u1-enterprise-<批次>@1.0.0
Manifest ID:         cat-u1-manifest-<批次>
数据域:              <填写测试数据域>
```

### 2.4 页面入口

登录后，进入 **知识中心 → 目录管理**。本次会用到：

- **Catalog 治理**：统一查看、引用注册、Pack 管理、Manifest 管理、审批中心；
- **项目配置**：创建和查看 Profile；
- **指标管理**：查看运行摘要；
- **基础配置**、**绑定模板**：确认源未接入时的说明与空态。

后端辅助验证使用 Swagger：`<测试环境地址>/docs`。在 Swagger 中选择 `catalog` 分组；它仅用于本方案标为“辅助 API 验证”的用例。不会使用接口的 FDE 可由联调人员协助执行并记录结果。

---

## 3. 执行规则与记录方式

1. 按编号顺序执行；依赖前一用例数据的项目不可跳过。
2. 每个写操作只点击一次。若网络中断，使用同一个操作的幂等键重试应由联调人员协助；不要重复点击创建按钮。
3. 出现错误时，截取整页和错误提示；若页面显示 correlation ID，一并记录。
4. 通过 = “结果符合预期”；不通过 = “结果与预期不符”；阻塞 = “环境/外部依赖未就绪”。不要把阻塞写成通过。
5. 测试结束后仅清理本方案创建、带 `cat-u1-` 前缀的测试数据；不得清理不属于本轮测试的数据。

建议使用以下记录列：`用例编号 / 执行人 / 日期时间 / 实际结果 / 截图或请求证据 / correlation ID / 结论 / 缺陷号`。

---

## 4. 核心人工测试用例

### A. 页面入口、空态与权限

| 编号 | 操作步骤 | 预期结果 |
|---|---|---|
| CAT-M-01 | 以 U4 登录，依次打开 5 个 Catalog 页面。 | 每页可打开；Catalog 治理显示 5 个 Tab；页面不展示虚构的客户语义数据。 |
| CAT-M-02 | 以 U5 登录 Catalog 治理，再尝试直接访问页面或刷新。 | 读取/写入被拒绝（通常为 403 或明确无权限提示）；不得显示其他用户的引用、Pack 或 Manifest。 |
| CAT-M-03 | 以 U4 打开 Catalog 治理 → 引用注册，尝试提交对象 A。 | 写入被拒绝；已有列表仍可读取。 |
| CAT-M-04 | 打开基础配置、绑定模板，观察空态或禁用的新建按钮；打开指标管理，观察运行摘要区。 | 说明清楚表达“由权威源维护 / 尚未接入”，不允许在 Catalog 创建第二份语义定义。指标页可展示已有运行摘要；无真实源数据时空数组/零值可接受。 |

### B. 建立 Profile 与登记权威引用

| 编号 | 操作步骤 | 预期结果 |
|---|---|---|
| CAT-M-05 | 以 U3 打开 **项目配置** → 填写测试 Profile。行业/企业范围填测试值；数据域填数据卡中的值；角色 JSON 至少包含 `product_owner` 和 `backup_owner` 两项，`backup_approver` 填 `backup_owner`。提交。 | 提示“Profile 草稿已创建”，列表出现 Profile ID、数据域和角色数量。Profile 不要求填写业务指标定义。 |
| CAT-M-06 | 用相同 Profile ID 再次提交，但故意修改企业范围。 | 被拒绝为冲突/不同请求；原 Profile 未被静默覆盖。 |
| CAT-M-07 | 以 U1 打开 **Catalog 治理 → 引用注册**，按数据卡登记对象 A。 | 注册成功；统一查看中出现正确 kind、stable ID、版本、状态和 hash 前缀。页面不要求或允许手工输入 hash。 |
| CAT-M-08 | 用同样方法登记对象 B；随后对对象 A 再登记一次。 | 对象 B 成功；重复登记不会生成第二个相同精确引用，结果保持幂等或明确提示已存在。 |
| CAT-M-09 | 在引用注册中输入不存在的 stable ID 或错误版本后提交。 | 被拒绝，提示权威源对象不可用；列表不新增错误引用。 |
| CAT-M-10 | 在统一查看中对对象 A 点击“刷新状态”。 | 成功时显示刷新成功且引用仍是原精确版本；若测试 Adapter 未提供刷新能力，记录为环境阻塞，不允许将对象改写为其他版本。 |

### C. Pack 草稿、审批与发布

| 编号 | 操作步骤 | 预期结果 |
|---|---|---|
| CAT-M-11 | 以 U1 在 **Pack 管理**新建平台 Pack 草稿，层级选 `platform`，owner 角色填测试约定的 Pack owner，版本 `1.0.0`。 | 草稿出现在 Pack 列表，状态为 `draft`。 |
| CAT-M-12 | 向平台 Pack 加入对象 A；再加入对象 B。 | 两个已注册引用可选并加入；客户端不填写 hash。 |
| CAT-M-13 | 分别创建行业 Pack 和企业 Pack。行业 Pack 加入对象 A（用于验证相同精确引用可去重）；企业 Pack 至少加入对象 B。 | 三个草稿均可见；同一精确引用跨 Pack 可存在，后续组合由服务端处理。 |
| CAT-M-14 | U1 在平台 Pack 点击“提交发布申请”，输入清晰原因，例如“Catalog 人工验收发布”。 | 审批中心出现该申请，状态进入待审批；U1 不应能在没有审批的情况下直接把 Pack 变为 published。 |
| CAT-M-15 | 仍以 U1 尝试审批自己的申请。 | 被拒绝；不得因拥有多个角色或同一显示名绕过。记录错误提示。 |
| CAT-M-16 | 切换 U2，在审批中心批准 U1 的申请；按页面提示执行发布履约。对三个 Pack 分别完成。 | 每个 Pack 最终为 `published`；已发布 Pack 不再可原地编辑。若 U2 不是该 Pack owner 或没有审批权限，应被拒绝。 |
| CAT-M-17 | 已发布后尝试再次向平台 Pack 加条目，或用同一 ID/版本再建草稿。 | 被拒绝；不可变版本不被覆盖。 |

### D. Manifest 预览、签署与激活

| 编号 | 操作步骤 | 预期结果 |
|---|---|---|
| CAT-M-18 | 以 U3 打开 **Manifest 管理 → 生成 Manifest 预览**。填测试 Profile、Manifest ID、revision `1`，Pack 填三个已发布 Pack，格式为 `pack_id@version`，逗号分隔。 | 返回预览 JSON；可看到 Manifest hash、Pack lock 和有效 entries。对象 A 即使在两层 Pack 中出现，也只保留一个相同精确 pin。 |
| CAT-M-19 | 预览时故意输入未发布 Pack、错误版本或错误格式（例如漏掉 `@版本`）。 | 被拒绝并说明原因；不生成可激活 Manifest。 |
| CAT-M-20 | 使用测试负责人提供的、与 CAT-M-18 预览结果精确对应的有效 attestation，在“激活已签署 Manifest”中填写相同 Profile、Manifest、revision、Pack。首次激活的“当前 active revision”留空。 | 激活成功；Manifest 列表中出现 revision 1 和 `active` 标识。 |
| CAT-M-21 | 使用篡改过 `effective_from`、`manifest_hash` 或 `envelope_hash` 的 attestation 再尝试激活一个新 Manifest。 | 被拒绝；现有 active Manifest 不变。 |
| CAT-M-22 | 用 U4（只读）或 U1（无发布权限）尝试预览/激活 Manifest。 | 被拒绝；只有具备 `ecmc.catalog.manifest.publish` 的用户可执行。 |

### E. Resolver 与撤销（辅助 API 验证）

这些用例需要 U3 或 U4 的已登录授权。联调人员可在 Swagger 的 `POST /v1/catalog/resolve` 和 `POST /v1/catalog/validate` 执行。请求中的 `profile_id`、`data_domain_id`、kind、stable ID、版本必须使用本方案实际创建的数据。

| 编号 | 操作步骤 | 预期结果 |
|---|---|---|
| CAT-M-23 | 调用 `resolve`，引用对象 A，`expected_kind` 与对象 A 的 kind 一致。 | 返回同一个 kind、stable ID、版本、content hash 和数据域；不能返回 `latest` 或其他版本。 |
| CAT-M-24 | 调用 `validate`，一次传对象 A、对象 B。 | `resolved` 包含两个精确引用，`issues` 为空。 |
| CAT-M-25 | 在 `resolve` 中把 expected kind 改成错误值，或传一个 Manifest 中不存在的版本。 | 被拒绝或返回明确 issue；不得返回“最接近”的对象。 |
| CAT-M-26 | 以 U1 撤销对象 B，必须填写原因；再次调用 `resolve` 或 `validate` 查询对象 B。 | 撤销成功后对象 B 不再被正常解析；错误原因可追踪。对象 A 仍可正常解析。 |
| CAT-M-27 | 以 U6（租户 B）用相同 stable ID 查询对象 A。 | 不可获得租户 A 的对象或存在性信息；结果应为不可见/未找到，不能泄露对象内容。 |

### F. Manifest 撤销、回滚与审计（辅助 API 验证）

页面当前提供激活入口；撤销/回滚属于治理操作，使用 Swagger 执行并由 U3 操作。

| 编号 | 操作步骤 | 预期结果 |
|---|---|---|
| CAT-M-28 | 在 Swagger 调用 `POST /v1/catalog/manifests/revoke`，输入测试 Profile 和明确原因。 | 当前 active Manifest 被撤销；之后 CAT-M-23 的解析被拒绝。历史 revision 仍可在列表/审计中追溯。 |
| CAT-M-29 | 重新激活一个更高 revision 的 Manifest；再调用 `POST /v1/catalog/manifests/rollback`，指定历史 revision，并提供新的 Manifest ID、新 revision 与匹配的 attestation。 | 回滚产生更高的新 revision，而非改写旧 revision；新 revision 成为 active。 |
| CAT-M-30 | 在治理中心审批列表、平台 Audit 页面或由联调人员查询审计记录，检查本轮注册、Pack 发布、Manifest 激活/撤销/回滚记录。 | 每项记录至少能关联操作者、租户、时间、资源、动作结果和请求/correlation ID；不展示凭据或完整敏感签名材料。 |

---

## 5. 页面专项验收清单

在核心用例通过后，以 U1、U4 各快速走查一次。每项勾选“是/否”。

### 5.1 Catalog 治理

- [ ] 5 个 Tab 名称、顺序清晰：统一查看、引用注册、Pack 管理、Manifest 管理、审批中心。
- [ ] 引用注册只要求来源、kind、stable ID、版本，不暴露 hash 编辑框。
- [ ] Pack 条目只能从已注册引用中选择。
- [ ] 发布申请、审批、履约的状态变化可见，不能跳过。
- [ ] Manifest 预览和激活输入项明确区分；激活要求 attestation。
- [ ] 失败提示说明原因，不只显示“操作失败”。

### 5.2 项目配置

- [ ] Profile 显示 data domain 与角色数量。
- [ ] 一份 Profile 只填写一个 data domain；多数据域应建多个 Profile。
- [ ] roles JSON 格式错误时，页面有清晰提示，原数据不被写入。
- [ ] Profile 页面不出现指标、单位等业务语义编辑字段。

### 5.3 指标、基础配置、绑定模板

- [ ] 指标页能看到运行摘要、同步记录和运行时指标区域；无数据时不伪造指标列表。
- [ ] 基础配置明确说明单位、聚合、时间窗口、规则模式来自权威源。
- [ ] 绑定模板明确说明由独立源系统维护。
- [ ] 在真实源未接入时，空态/禁用态说明一致，并含有下一步信息。

---

## 6. 常见现象与处理方法

| 现象 | 通俗解释 | 处理方式 |
|---|---|---|
| 页面显示 readiness HOLD | 该页面所需真实源或列表 API 尚未接入 | 记录为生产接入待验证，不创建缺陷；确认未显示假数据 |
| 注册返回 503 / “source adapter is not ready” | 测试 Adapter 没有部署或名称填错 | 停止后续注册用例，联系部署人员核对数据卡 |
| 注册返回 404 | stable ID 或版本不在权威测试源中 | 核对数据卡，不要改用模糊版本 |
| 注册返回 422 / hash 校验失败 | 源对象内容和权威 hash 不一致，系统正在保护数据 | 记录缺陷/环境问题；不要手工改 hash 绕过 |
| 点击审批没有按钮 | 当前用户没有审批权限，或申请尚未到可审批状态 | 切到 U2，检查申请状态 |
| 自己审批被拒绝 | 职责分离生效 | 记为通过，不需要修复 |
| Manifest 激活失败 | Pack 未发布、Profile/Pack 不匹配、revision 不正确或 attestation 不匹配 | 先重新预览，再由签署材料负责人生成匹配材料 |
| Resolver 返回未找到/拒绝 | 引用不在 active Manifest、版本不精确、已撤销、跨数据域或跨租户 | 按用例核对 Profile、数据域、版本和状态；不要使用 `latest` |
| 指标/基础配置/绑定模板为空 | 真实源列表合同仍为 HOLD | 记为待生产接入验证，不新增本地语义 |

---

## 7. 缺陷分级、完成条件与交付物

### 7.1 缺陷分级

| 级别 | 判断标准 | 示例 |
|---|---|---|
| P0 阻塞 | 可绕过权限、跨租户读取、未签署 Manifest 激活、错误 hash 被接受、数据损坏 | 无权用户读取其他租户引用 |
| P1 重要 | 主闭环无法完成，或错误提示导致 FDE 无法继续 | 注册成功但无法加入 Pack；已审批 Pack 无法履约 |
| P2 建议 | 不影响结果，但文案、布局或记录体验需要改善 | 空态说明不够易懂 |
| HOLD | 外部真实源/签署/owner/调度条件未就绪 | 真实 webhook secret 未配置 |

### 7.2 本轮 Mock/Test 验收通过条件

1. CAT-M-01～CAT-M-25 中所有非 HOLD 用例通过；CAT-M-26～CAT-M-30 至少完成一次，或因环境限制记录明确阻塞和责任人。
2. 不存在 P0；P1 有修复计划和复测结论。
3. 全部失败、拒绝和空态都能说明原因，且没有通过 Fixture、手工 hash 或直接写库绕过。
4. 测试报告清楚写明：**“Mock/Test 人工验收通过，不代表生产 readiness 已关闭。”**

### 7.3 测试结束应提交的材料

- 已填写的用例记录表；
- 成功链路截图：Profile、引用、3 个已发布 Pack、Manifest 预览、active Manifest、Resolver 成功结果；
- 关键拒绝截图：无权限、自审批、错误源对象、篡改 attestation、跨租户或跨数据域；
- 每个缺陷的编号、复现步骤、截图、correlation ID 和环境信息；
- 未关闭 HOLD 清单及责任人：真实 Pack/hash、真实 owner、真实引用、真实 Source Adapter/webhook/调度/告警；
- 测试结论：通过 / 有条件通过 / 不通过，以及复测日期。

---

## 8. 生产接入后必须补做的验证

以下不是本轮 Mock/Test 验收的替代项。真实源系统准备好后，应单独开一轮“生产接入验证”，至少补测：

1. 真实源对象的注册、分页 pull、断点恢复、限流/超时/5xx 重试；
2. 真实 webhook 的签名、防重放、乱序处理和告警；
3. 单次同步缺失进入 `suspected_missing`，不能误下线；人工确认后才转 inactive；
4. 已签署 Manifest 在同步故障时仍按 LKG 服务，恢复后告警闭环；
5. 真实 Pack lock、真实 Manifest/attestation、10 个 kind owner 与 JQMK 初始引用；
6. RLS、审计留存/脱敏、监控告警、缓存失效、数据库迁移、撤销和回滚演练；
7. 以试点租户灰度运行后，再执行上线评审。

本方案的功能说明以 [FDE 使用说明](/Users/linkunpeng/work/EARP/arch/guides/earp-fde-user-guide.md) 和 [ECMC FDE 使用指南](/Users/linkunpeng/work/EARP/arch/guides/earp-ecmc-guide.md) 为准；实现状态与生产 HOLD 以 [Catalog Phase 1 实施任务书](/Users/linkunpeng/work/EARP/arch/design/2026-09-02-catalog-phase1-implementation-task-book.md) 和 [技术债清单](/Users/linkunpeng/work/EARP/arch/tech-debt.md) 为准。
