# EARP 文件场景数据集

文件数据集用于在不连接业务系统时验证因果模型。它实现的是标准的运行时 Provider：

```text
Evidence Requirement → Capability Contract → File Provider → EvidenceObservation
```

模型仍然声明逻辑 Capability Contract；每次运行通过 `dataset_id` 选择数据集。CSV 中的
测试数据不写入因果模型、Blueprint 或其版本快照。面向实施的操作步骤见
[FDE 使用说明 §12.4](/Users/linkunpeng/work/EARP/arch/guides/earp-fde-user-guide.md)。

## 生命周期与审计

1. 上传或从受控目录登记场景包，生成 `staged` revision 和内容哈希。
2. 校验通过后由 Admin 发布，变为该数据集的最新 `published` revision。
3. 因果规划传入 `dataset_id`，系统解析当时的最新发布内容，并将实际 `content_hash`、
   manifest 快照固定在 execution profile 中。
4. 后续上传或发布同一 `dataset_id` 的新内容不会改变已经开始的运行、审计 trace 或 replay 输入。

数据集元数据、revision、清单与校验报告按租户隔离；写操作仅 Admin。完整包保存于
`EARP_FILE_DATA_ROOT` 下的租户隔离、内容哈希寻址目录，服务不会读取该根目录以外的文件。

## 最小 manifest

```yaml
schema_version: earp-file-dataset/v1
dataset:
  id: mine-production-demo
  name: 3 号矿产量演示
  description: 文件 Provider 演示数据

providers:
  - provider_key: file-production-v1
    capability_contract_ref: production_metric_query
    file: production.csv
    entity_column: entity_id
    time_column: observed_at
    requirements:
      production_actual_and_baseline:
        value_column: value
        baseline_column: baseline
        unit: t
```

`production.csv`：

```csv
entity_id,observed_at,value,baseline
mine-3,2026-08-28T01:00:00+08:00,4200,5000
mine-3,2026-08-28T13:00:00+08:00,4000,5000
```

时间必须是带时区的 ISO-8601。运行时按目标实体和 `[start,end)` 窗口筛选，再使用模型
Evidence Requirement 中声明的 `sum` / `mean` / `min` / `max` / `latest` 聚合 value 和 baseline。

`requirement_key` 必须是目标模型已声明的 Evidence Requirement；`capability_contract_ref`
必须是它解析所需的 Capability Contract。baseline 是 CSV 的显式列，一期不会根据历史值自动推导。

## 字段与文件规则

- `schema_version` 固定为 `earp-file-dataset/v1`；`dataset.id` 在当前租户内作为 `dataset_id` 使用。
- 每个 Provider 的 `provider_key` 唯一；`file` 指向同次上传的 CSV；`entity_column` 和
  `time_column` 必须存在于该文件表头。
- 每个 requirement 至少配置 `value_column`、`baseline_column` 和 `unit`，并且列名必须存在。
- CSV 仅接受 UTF-8 或 UTF-8-BOM；不支持 Excel、Parquet、公式、跨文件 join 或自动 baseline 推导。
- 文件名只可为包内相对文件名。绝对路径、目录穿越、符号链接、超出数量/大小上限的文件会被拒绝。

坏行（无效时间、数值或缺少必填列值）会被跳过，并在校验报告中记录文件名、行号和原因。
若某 Provider 仍有可用数据，可带 warning 发布；manifest 结构错误、文件缺失、没有可用 Provider
或安全校验失败则不能发布。

## 完整场景包

manifest 可内联声明 `data_domains`、`entity_types` 和 `relation_types`，并通过下列映射导入
ABox：

```yaml
entities:
  file: entities.csv
  columns:
    entity_id: entity_id
    entity_type: entity_type
    name: name
    business_code: business_code
    data_domain_id: data_domain_id

relations:
  file: relations.csv
  columns:
    source_code: source_code
    source_type: source_type
    relation_type: relation_type
    target_code: target_code
    target_type: target_type
    confidence: confidence
```

发布时按“实体类型 + business_code”复用已有实体，不覆盖已有业务数据。坏行会跳过并
出现在 validation warnings 中。关系目标无法解析和类型冲突同样只跳过并告警。导入记录带有
`dataset_id + content_hash` 来源；不会随数据集升级自动删除或回滚共享 ABox 中已有的数据。

## 操作

- 管理页“中台对接 → 文件场景数据集”可同时选择 manifest 和多个 CSV。
- `POST /v1/file-datasets` 暂存并校验；`POST /v1/file-datasets/{dataset_id}/publish` 发布。
- 开发环境也可把目录放在 `EARP_FILE_DATA_ROOT` 下，调用
  `POST /v1/file-datasets/from-directory` 并传入相对路径。
- 调用 `/v1/ecmc/planning/entry` 时传 `dataset_id`。返回的 `execution_profile.file_dataset`
  含实际发布内容哈希，后续 Prepare 必须传递该 pin。

## 运行结果语义

- 找不到目标实体或时间窗内的行、或全部匹配行无效：返回 `DATA_UNAVAILABLE`，由既有
  Evidence Requirement 的 required/optional 语义决定后续 Evaluate 行为。
- 有效行：按 requirement 的聚合方式分别产出 value 与 baseline；provenance 记录数据集、
  文件和内容哈希。
- 文件丢失、文件哈希与发布版本不一致、解析过程失败：视为基础设施失败，不能用 fixture 或
  默认值伪造结果。
