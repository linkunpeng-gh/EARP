# EARP Catalog 治理目录（arch/catalog）

本目录承载"模板 + Profile + 签署实例"三层结构的 Catalog 治理资产，用于将 N01A 生产 Catalog 签署记录做成**跨项目可复用**。

## 目录结构

```
arch/catalog/
├─ templates/    # 签署模板（FROZEN 契约语义层，跨项目复用，不可含项目数据）
│  └─ n01a-catalog-phase0-signoff-template.md
├─ schemas/      # Profile JSON Schema（严格模式，防危险语义开关）
│  └─ catalog-profile.schema.json
├─ profiles/     # 项目级配置（值层：scope/owner 绑定/编号/变更单）
│  └─ jqmk-coal-production.yaml
└─ signoffs/     # 已签署实例（模板 + Profile 渲染 + 签署结果）
   └─ jqmk-coal-production-20260901-r1.md
```

## 三层职责与边界

| 层 | 内容 | 是否可配置 | 换项目是否改 |
|---|---|---|---|
| **模板** | FROZEN 契约语义、填写规则、四类标签、所有"[FROZEN-CONFIRM]"条款 | 否（语义冻结） | 不改 |
| **Profile** | tenant/industry/data_domain/enterprise scope、角色→人员绑定、pack_lock、变更单、保管人 | 是（仅值） | 新建一份 |
| **签署实例** | 模板+Profile 渲染结果 + APPROVE/HOLD 决定 + 签名记录 | 签署结论 | 每项目/每修订一份 |

## 硬边界（不可破坏）

1. **Profile 只承载值，不承载语义。** `catalog-profile.schema.json` 使用 `additionalProperties:false`，未列出的字段一律拒绝——`allow_inactive`、`disable_fail_closed` 等危险语义开关无法通过 schema。
2. **模板语义冻结。** FROZEN 条款（fail closed、exact ref、非 active 拒绝新操作、approve 不进 fulfilled、callback 幂等/对账）只存在于模板，Profile 无法覆盖。
3. **签署实例必须绑定不可变证据。** 每个实例头部记录 `template_contract_version + profile_hash(SHA-256) + profile 路径 + manifest hash + resolver contract version`；manifest 未生成时 hash 为 HOLD，不得声明生效。

## 换新项目（如银行）的流程

1. 复制 `profiles/jqmk-coal-production.yaml` 为 `profiles/<bank>-<env>.yaml`，改写 scope / 角色绑定 / 变更单。
2. 用 `schemas/catalog-profile.schema.json` 校验新 Profile（必须通过；可加 `allow_inactive` 等字段验证被拒）。
3. 计算新 Profile 的 SHA-256 作为 `profile_hash`。
4. 复制模板到 `signoffs/<bank>-<env>-<date>-r1.md`，填入新 Profile 值与 `profile_hash`，完成 APPROVE/HOLD 签署。
5. 模板、schema 不做任何改动；FROZEN 语义随模板跨项目保持一致。

## 校验命令

```bash
# 校验 Profile 是否通过 Schema（含负向：危险开关应被拒绝）
.venv/bin/python - <<'PY'
import json, yaml
from jsonschema import validate
schema = json.load(open("arch/catalog/schemas/catalog-profile.schema.json"))
prof = yaml.safe_load(open("arch/catalog/profiles/jqmk-coal-production.yaml"))
validate(instance=prof, schema=schema)
print("profile valid")
PY

# 计算 profile_hash
shasum -a 256 arch/catalog/profiles/jqmk-coal-production.yaml
```
