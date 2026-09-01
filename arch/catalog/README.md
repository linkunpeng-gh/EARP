# EARP Catalog 治理目录（arch/catalog）

本目录承载"模板 + Profile + 决策输入 → 签署实例"四层结构的 Catalog 治理资产，用于将 N01A 生产 Catalog 签署记录做成**跨项目可复用**。

## 目录结构

```
arch/catalog/
├─ templates/     # 签署模板（FROZEN 契约语义层，跨项目复用，不可含项目数据）
│  └─ n01a-catalog-phase0-signoff-template.md
├─ schemas/       # Profile JSON Schema（严格模式，additionalProperties:false 防危险语义开关）
│  └─ catalog-profile.schema.json
├─ profiles/      # 项目级配置（值层：scope/owner 绑定/编号/变更单/pack_lock）
│  └─ jqmk-coal-production.yaml
├─ decisions/     # 决策/证据输入（Profile 之外的审批记录、门禁证据、RBAC/audit 选择）
│  └─ jqmk-coal-production-20260901-r1.json
├─ signoffs/      # 已签署实例（模板 + Profile + 决策渲染 + 签署结果）
│  └─ jqmk-coal-production-20260901-r1.md
├─ attestations/  # 签署 attestation（绑定基线 commit + 各文件 blob hash，不可变证据）
│  └─ jqmk-coal-production-20260901-r1.json
└─ scripts/       # 确定性渲染 + 机械校验
   ├─ render_signoff.py
   └─ validate_catalog.py
```

## 输入模型与职责边界

签署实例由 **模板 + Profile + 决策输入** 三个输入确定性渲染，缺一不可：

| 输入 | 内容 | 是否可配置 | 换项目是否改 |
|---|---|---|---|
| **模板** | FROZEN 契约语义、填写规则、四类标签、所有"[FROZEN-CONFIRM]"条款 | 否（语义冻结） | 不改 |
| **Profile** | tenant/industry/data_domain/enterprise scope、角色→人员绑定、pack_lock、变更单、保管人 | 是（仅值） | 新建一份 |
| **决策输入** | 审批记录、manifest/门禁证据、RBAC/audit 选择、global scope 决定等**非 Profile 值** | 是（签署结论） | 每项目/每修订一份 |
| **签署实例** | 三输入渲染结果 + APPROVE/HOLD 决定 + 签名记录 | 签署结论 | 每项目/每修订一份 |

> 注意：manifest hash、运营决策、门禁证据等**不来自 Profile**。Profile 只承载项目静态配置；决策/证据必须进入 decisions 文件，渲染器才能产出完整实例。不要声称"仅凭 Profile 即可复现签署实例"。

## 硬边界（不可破坏）

1. **Profile 只承载值，不承载语义。** `catalog-profile.schema.json` 使用 `additionalProperties:false`，未列出的字段一律拒绝——`allow_inactive`、`disable_fail_closed` 等危险语义开关无法通过 schema（校验器含负向测试）。
2. **模板语义冻结。** FROZEN 条款（fail closed、exact ref、非 active 拒绝新操作、approve 不进 fulfilled、callback 幂等/对账）只存在于模板，Profile/决策无法覆盖。**禁止仅凭 `template_contract_version` 判断模板未变**——须校验模板 blob hash 与 FROZEN 锚点。
3. **签署实例必须绑定不可变证据。** 每个实例头部记录 `template_contract_version + profile_hash(SHA-256) + profile 路径 + manifest hash + resolver contract version`；manifest 未生成时 hash 为 HOLD，不得声明生效。
4. **签署基线用 annotated tag + attestation。** 基线 commit（含模板/Profile/签署实例/脚本）由 `git tag -a` 冻结；attestation 独立提交，绑定基线 commit 与各文件 blob hash。签署实例头部**只引用 tag，不写具体 commit 自引用**。

## 换新项目（如银行）的流程

1. 复制 `profiles/jqmk-coal-production.yaml` 为 `profiles/<bank>-<env>.yaml`，改写 scope / 角色绑定 / 变更单 / pack_lock。
2. 复制 `decisions/...json` 为 `<bank>-<env>-<date>-r<n>.json`，改写审批记录、门禁证据、RBAC/audit 选择等决策值。
3. 用渲染器生成签署实例基线（FROZEN 块自动从模板带入，不可手工改写）：
   ```bash
   .venv/bin/python arch/catalog/scripts/render_signoff.py \
     --template arch/catalog/templates/n01a-catalog-phase0-signoff-template.md \
     --profile arch/catalog/profiles/<bank>-<env>.yaml \
     --decisions arch/catalog/decisions/<bank>-<env>-<date>-r<n>.json \
     --out arch/catalog/signoffs/<bank>-<env>-<date>-r<n>.md
   ```
4. 补充签署结论（APPROVE/HOLD、责任人、签名记录）到渲染出的实例。
5. 运行校验器，全部通过后提交基线并打 annotated tag；随后写 attestation。
6. 模板、schema 不做任何改动；FROZEN 语义随模板跨项目保持一致。

## 校验（脚本化，勿用手工）

```bash
# 机械校验：schema 正负向、profile_hash、残留占位符、FROZEN 锚点、attestation blob hash
.venv/bin/python arch/catalog/scripts/validate_catalog.py

# 计算 profile_hash（渲染器与校验器内部自动处理，此处仅核对）
shasum -a 256 arch/catalog/profiles/jqmk-coal-production.yaml
```

校验器退出码 0 = 全部通过；非 0 = 存在失败项（详见输出）。

## 下一次修订 backlog（非阻塞，已记录）

1. **渲染器逐字复现签署实例**：当前渲染产物的标题、签署勾选（☑/□）、少量展示格式仍来自人工编辑。下一次修订应把签署结论纳入 decisions 输入，或明确"渲染产物 + 人工签署附录"的边界，并在校验器中增加"仅允许修改附录区域"的检查。
2. **联系方式补全**：当前所有角色 contact 为 TBD，§9.1 RACI entry gate 保持 HOLD；补全后 readiness 检查应通过。
3. **pack_lock 填实**：3 个 pack 的 version/hash 为 null（D-13），填实后需重算 profile_hash 并重签实例。

## 签署证据链（如何证明这份签署不可变）

1. `git tag -a catalog-phase0-jqmk-coal-r1` 冻结基线 commit（含全部被签署资产）。
2. `arch/catalog/attestations/jqmk-coal-production-20260901-r1.json` 记录：
   - `baseline_commit`：基线 commit hash；
   - `blob_hashes`：signoff / profile / template / schema 四文件的 SHA-256；
   - `verification`：FROZEN 锚点一致、无占位符、schema 合法、危险开关被拒。
3. `validate_catalog.py` 每次校验 attestation 声明的 blob hash 与磁盘文件一致——任何改动立即被检测。
4. 校验命令：
   ```bash
   git show catalog-phase0-jqmk-coal-r1           # 查看基线
   git cat-file -t catalog-phase0-jqmk-coal-r1     # 确认 annotated tag
   .venv/bin/python arch/catalog/scripts/validate_catalog.py
   ```
