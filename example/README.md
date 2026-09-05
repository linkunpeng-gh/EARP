# EARP 煤矿开采行业演示数据集

> **版本**：v1.0  
> **日期**：2026-09-04  
> **行业**：煤矿开采  
> **适用**：功能测试、客户演示、实施交付

## 目录结构

```
example/
├── README.md                              # 本文件（总入口）
├── knowledge-center/                      # 知识中心演示数据
│   ├── business-documents/                # 业务文档（5份，用于知识库上传）
│   │   ├── 01-煤矿安全生产规程.md
│   │   ├── 02-综采设备维护手册.md
│   │   ├── 03-煤矿生产指标说明.md
│   │   ├── 04-运输系统操作规程.md
│   │   └── 05-煤矿应急预案.md
│   ├── ontology/                          # 实体关系数据（TBox + ABox）
│   │   ├── data-domains.json             # 4个数据域定义
│   │   ├── entity-types.json             # 14种实体类型（TBox）
│   │   ├── relation-types.json           # 13种关系类型（TBox）
│   │   ├── entities.csv                  # 43个实体实例（ABox，批量导入格式）
│   │   └── facts.csv                     # 38条关系事实（ABox，批量导入格式）
│   └── file-dataset/                      # 文件场景数据集（因果模型运行时取数）
│       ├── manifest.yaml                 # 数据集清单（3个Provider）
│       ├── production.csv                # 3号矿产量数据（62行，2026年8月）
│       ├── equipment.csv                 # 3号矿设备可用率数据（31行）
│       ├── haulage.csv                   # 3号矿运输周期+排队时间（31行）
│       ├── entities.csv                  # 数据集实体映射（3行）
│       └── relations.csv                 # 数据集关系映射（2行）
├── model-center/                          # 模型中心演示数据
│   └── causal-models/
│       └── mine3-production-drop-diagnosis.json  # 3号矿产量下降诊断因果模型
├── catalog/                               # Catalog 语义目录数据
│   ├── metrics.json                      # 8个煤矿核心指标定义
│   ├── units.json                        # 10种计量单位定义
│   ├── aggregations.json                 # 7种聚合方式定义
│   ├── time-windows.json                 # 5种时间窗口定义
│   ├── binding-templates.json            # 4种实体绑定模板定义
│   ├── capability-contracts.json         # 5个取数能力合同定义
│   └── rule-schemas.json                 # 4种规则Schema定义
└── test-guide/                            # 测试指导
    └── EARP功能测试与演示指南.md          # 完整的功能使用说明（含测试数据对应关系）
```

## 贯穿演示场景

所有演示数据围绕一个真实的煤矿业务场景设计：

> **3号矿产量下降事件**：2026年8月20日起，3号矿日产量从正常的5000-5500吨下降到4000-4500吨（下降约15-20%）。业务专家判断主要原因是：①运输周期变长（从20分钟增至30分钟以上）；②设备可用率下降（从95%降至80%）；③排队时间增加（从4分钟增至15分钟）。

这个场景贯穿知识中心（数据准备）、模型中心（因果模型构建）、Catalog（语义标准化）的所有功能测试。

## 快速开始

### 第一步：阅读测试指南

详细的功能使用说明和测试步骤请阅读：
**`example/test-guide/EARP功能测试与演示指南.md`**

该指南包含：
- 每个功能的通俗解释（含类比）
- 具体操作步骤
- 使用哪些测试数据
- 验证要点
- 常见问题排查
- 完整的端到端演示流程

### 第二步：知识中心数据准备

1. 创建数据域（参考 `ontology/data-domains.json`）
2. 创建知识库并上传文档（参考 `business-documents/`）
3. 创建TBox实体类型和关系类型（参考 `ontology/entity-types.json`、`relation-types.json`）
4. 批量导入实体和关系（使用 `ontology/entities.csv`、`facts.csv`）
5. 上传并发布文件场景数据集（使用 `file-dataset/` 目录）

### 第三步：模型中心模型构建

1. 注册Catalog引用（参考 `catalog/` 目录）
2. 新建因果模型（参考 `model-center/causal-models/mine3-production-drop-diagnosis.json`）
3. 编辑模型（节点、边、证据需求、规则）
4. 校验→提交审核→发布→编译→激活

### 第四步：端到端演示

发起因果诊断，验证完整链路：
- 输入："为什么3号矿8月下旬产量下降？"
- 传入 dataset_id: `mine3-production-demo`
- 预期：系统从文件数据集取数，执行因果诊断，给出"运输周期变长+设备可用率下降是主要原因"的结论

## 数据统计

| 数据类别 | 数量 | 位置 |
|---------|------|------|
| 数据域 | 4个 | ontology/data-domains.json |
| 业务文档 | 5份 | business-documents/ |
| 实体类型（TBox） | 14种 | ontology/entity-types.json |
| 关系类型（TBox） | 13种 | ontology/relation-types.json |
| 实体实例（ABox） | 42个 | ontology/entities.csv |
| 关系事实（ABox） | 35条 | ontology/facts.csv |
| 文件数据集Provider | 3个 | file-dataset/manifest.yaml |
| 产量数据行 | 62行 | file-dataset/production.csv |
| 设备数据行 | 31行 | file-dataset/equipment.csv |
| 运输数据行 | 31行 | file-dataset/haulage.csv |
| 因果模型 | 1个 | model-center/causal-models/ |
| 模型节点 | 6个 | 因果模型JSON |
| 模型边 | 5条 | 因果模型JSON |
| 证据需求 | 5个 | 因果模型JSON |
| 规则 | 5条 | 因果模型JSON |
| Catalog指标 | 8个 | catalog/metrics.json |
| Catalog单位 | 10种 | catalog/units.json |
| Catalog聚合方式 | 7种 | catalog/aggregations.json |
| Catalog时间窗口 | 5种 | catalog/time-windows.json |
| Catalog绑定模板 | 4种 | catalog/binding-templates.json |
| Catalog能力合同 | 5个 | catalog/capability-contracts.json |
| Catalog规则Schema | 4种 | catalog/rule-schemas.json |

## 数据来源与合理性说明

所有演示数据基于煤矿行业公开资料和行业常识设计：

- **产量数据**：参考大型现代化矿井日产量6000-10000吨、中型矿井3000-6000吨的行业范围，3号矿设计为中型矿井，正常日产量5000-5500吨
- **设备可用率**：参考行业要求设备完好率95%以上、可用率90%以上，正常状态设计为93-96%，异常状态下降至80-83%
- **运输周期**：参考煤矿生产能力核定标准中的运输周期公式 T=2L/v+t1+t2，中距离运输（1-3km）正常周期15-25分钟，异常状态增至30-35分钟
- **掘进进尺**：参考综掘工作面月进尺500-800米的行业数据
- **业务文档**：基于《煤矿安全规程》《煤矿生产能力核定标准》等公开法规和行业标准编写

数据为演示用途，不代表任何具体煤矿的真实数据。

## 参考文档

更多详细的官方使用说明请参考项目架构文档：

- `arch/guides/earp-fde-user-guide.md` — 知识中心FDE使用说明（v1.4）
- `arch/guides/earp-ecmc-guide.md` — ECMC企业认知模型中心使用指南（v1.2）
- `arch/guides/earp-file-dataset.md` — 文件场景数据集说明
- `arch/guides/earp-catalog-phase1-runbook.md` — Catalog Phase 1运维手册
- `arch/guides/earp-chatflow-guide.md` — Chatflow使用指南
