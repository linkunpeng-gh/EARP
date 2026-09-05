# EARP 功能测试与演示指南（煤矿开采行业版）

> **版本**：v1.0  
> **日期**：2026-09-04  
> **适用对象**：测试人员、售前演示人员、实施工程师  
> **行业场景**：煤矿开采行业  
> **数据位置**：`example/` 目录

---

## 一、先搞懂：EARP 是什么？演示数据有哪些？

### 1.1 一句话理解 EARP

EARP（Enterprise AI Runtime Platform，企业级 AI 运行平台）就像一个**"企业大脑的操作系统"**——它把企业的知识、经验、数据和 AI 能力整合在一起，让 AI 能够像企业专家一样理解问题、查找资料、分析原因、给出答案。

打个比方：
- **知识中心** = 企业的"图书馆 + 档案室"，存放所有文档、设备台账、业务关系
- **模型中心（ECMC）** = 企业的"专家经验库"，把老师傅的诊断思路变成可审核、可追溯的 AI 模型
- **Catalog（语义目录）** = 企业的"标准化词典"，统一规定"产量""设备可用率"这些词到底是什么意思
- **能力中心** = 企业的"工具箱"，AI 可以调用的各种取数、执行能力

### 1.2 演示数据总览

所有演示数据都在 `example/` 目录下，按照功能模块组织：

```
example/
├── knowledge-center/          # 知识中心演示数据
│   ├── business-documents/    # 业务文档（5份，用于知识库上传）
│   ├── ontology/              # 实体关系数据（TBox + ABox）
│   └── file-dataset/          # 文件场景数据集（因果模型运行时取数）
├── model-center/              # 模型中心演示数据
│   └── causal-models/         # 因果模型定义（3号矿产量下降诊断）
├── catalog/                   # Catalog 语义目录数据
│   ├── metrics.json           # 指标定义（8个煤矿核心指标）
│   ├── units.json             # 单位定义（10种单位）
│   ├── aggregations.json      # 聚合方式（7种）
│   ├── time-windows.json      # 时间窗口（5种）
│   ├── binding-templates.json # 绑定模板（4种）
│   ├── capability-contracts.json # 能力合同（5个）
│   └── rule-schemas.json      # 规则Schema（4种）
└── test-guide/                # 测试指导（本文件）
```

### 1.3 贯穿演示场景：3号矿产量下降事件

所有演示数据围绕一个真实的业务场景设计：

> **背景**：某煤矿企业有3座矿井。2026年8月20日起，3号矿的日产量突然从正常的5000-5500吨下降到4000-4500吨，下降幅度约15-20%。
>
> **业务专家经验**：产量下降通常有三个主要原因——①运输周期变长（矿卡跑一趟花的时间多了）；②设备可用率下降（采煤机、液压支架等设备故障多了）；③排队时间增加（矿卡在装载点等的时间长了）。
>
> **演示目标**：用 EARP 把这套专家经验录入系统，让 AI 能够自动诊断产量下降的原因。

这个场景会贯穿知识中心、模型中心、Catalog 的所有功能测试。

---

## 二、知识中心功能测试指南

知识中心是 EARP 的基础，所有的文档、实体、关系、数据都在这里管理。

### 2.1 数据域管理

**功能入口**：知识中心 → 数据域（Data Domains）

**功能说明**：
数据域就像图书馆的"楼层分区"——生产数据在一楼，设备数据在二楼，安全数据在三楼。每个知识库、实体、文档都归属于一个数据域，权限和检索都按数据域隔离。

**测试数据**：`example/knowledge-center/ontology/data-domains.json`

**操作步骤**：
1. 进入数据域管理页面
2. 点击"新建数据域"
3. 参照 `data-domains.json` 中的定义，依次创建4个数据域：

| 数据域ID | 名称 | 说明 | 密级 |
|---------|------|------|------|
| production_data | 生产数据 | 原煤产量、掘进进尺、工作面推进度等 | internal |
| equipment_data | 设备数据 | 设备台账、可用率、故障率、维护记录 | internal |
| transport_data | 运输数据 | 矿卡运输周期、排队时间、运输量 | internal |
| safety_data | 安全数据 | 瓦斯浓度、通风量、安全事件 | confidential |

**验证要点**：
- 创建后数据域列表中能看到4个数据域
- 数据域的密级（classification）正确设置
- 后续创建知识库、实体时，数据域下拉框能看到这4个选项

**类比理解**：数据域就像超市的"商品分区"——食品区、日用品区、电器区。分区的好处是：你找食品不会跑到电器区去，权限管理也可以做到"食品区员工不能进电器区仓库"。

---

### 2.2 知识库管理（Knowledge Base）

**功能入口**：知识中心 → 知识库（Knowledge Base）

**功能说明**：
知识库就像图书馆里的"书架"——每个书架放一类书。你可以创建多个知识库，比如"安全生产知识库""设备维护知识库""生产指标知识库"。上传文档后，系统会自动把文档切分成小块（chunk），建立向量索引，之后就可以用自然语言搜索文档内容了。

**测试数据**：`example/knowledge-center/business-documents/` 目录下的5份文档

**操作步骤**：

#### 第一步：创建知识库

1. 进入知识库页面
2. 点击"+ New KB"（新建知识库）
3. 填写以下信息，创建3个知识库：

| 知识库名称 | 数据域 | 说明 | 分段大小 | 重叠 | 检索模式 |
|-----------|--------|------|---------|------|---------|
| 安全生产知识库 | safety_data | 煤矿安全规程、应急预案等 | 1000 | 200 | hybrid |
| 设备维护知识库 | equipment_data | 综采设备维护手册等 | 1000 | 200 | hybrid |
| 生产运营知识库 | production_data | 生产指标说明、运输规程等 | 1000 | 200 | hybrid |

#### 第二步：上传文档

选中对应知识库，上传以下文档：

**安全生产知识库**：
- `01-煤矿安全生产规程.md`
- `05-煤矿应急预案.md`

**设备维护知识库**：
- `02-综采设备维护手册.md`

**生产运营知识库**：
- `03-煤矿生产指标说明.md`
- `04-运输系统操作规程.md`

上传时注意：
- Title（标题）：自动从文件名提取，可修改
- Classification（密级）：根据文档内容选择，安全相关选 confidential，其他选 internal
- Data Domain：自动继承知识库的数据域，只读

#### 第三步：查看分段（Chunk）

上传完成后，文档列表中会显示每个文档的 chunk 数量。点击文档的"⚙️"按钮可以进入分段配置页面，查看系统是如何把文档切分成小块的。

**验证要点**：
- 5份文档全部上传成功
- 每个文档都有合理的 chunk 数量（通常每份文档10-30个chunk）
- 文档列表显示正确的文档数、chunk总数

**类比理解**：上传文档就像把一本厚书拆成一张张"知识卡片"——每张卡片讲一个小主题。搜索的时候，系统不是整本书翻，而是快速找到最相关的几张卡片，这样又快又准。

---

### 2.3 召回测试（Test Retrieval）

**功能入口**：知识库页面 → "Test Retrieval"按钮，或直接进入 `test-retrieval.html`

**功能说明**：
召回测试就是"搜索引擎的试金石"——你输入一个问题，系统从知识库中找出最相关的文档片段。这是检验文档上传和索引是否正常的关键功能。

**测试数据**：已上传的5份业务文档

**测试用例**：

| 序号 | 测试问题 | 期望命中的知识库 | 期望命中的关键词 |
|------|---------|----------------|----------------|
| 1 | 采煤工作面的安全出口有什么要求？ | 安全生产知识库 | 安全出口、回风巷、进风巷 |
| 2 | 瓦斯浓度达到多少必须停止工作？ | 安全生产知识库 | 瓦斯、1.5%、停止工作 |
| 3 | 采煤机日常检查需要检查哪些内容？ | 设备维护知识库 | 采煤机、日常检查、截齿 |
| 4 | 液压支架的乳化液浓度要求是多少？ | 设备维护知识库 | 乳化液、浓度、3%-5% |
| 5 | 原煤产量是怎么计算的？ | 生产运营知识库 | 原煤产量、计算方法、回采产量 |
| 6 | 矿卡运输周期包括哪些时间？ | 生产运营知识库 | 运输周期、装车、重车运行、卸车 |
| 7 | 发生瓦斯爆炸事故应该怎么应急处置？ | 安全生产知识库 | 瓦斯爆炸、应急处置、切断电源 |
| 8 | 设备完好率和可用率有什么区别？ | 设备维护知识库 | 完好率、可用率、区别 |

**操作步骤**：
1. 进入召回测试页面
2. Scope（范围）选择对应的知识库，或选择"全部"
3. 在 Query 输入框输入测试问题
4. 点击 Search（搜索）
5. 查看返回的结果列表，包括 Chunk ID、内容摘要、相似度得分（Score）

**验证要点**：
- 每个测试问题都能返回相关结果
- 结果的 Score（相似度）通常在0.7以上表示高度相关
- 结果内容确实包含问题的答案
- 可以点击结果查看完整的 chunk 内容

**常见问题**：
- **搜不到结果**：检查文档是否上传成功、chunk是否生成、检索范围是否选对
- **结果不相关**：检查问题描述是否清晰，尝试用文档中的关键词搜索
- **Score很低**：可能是文档内容与问题确实不相关，或者分段不合理

**类比理解**：召回测试就像你在图书馆问管理员"采煤机怎么维护"，管理员从书架上找出最相关的几本书翻到对应页码。Score就是管理员认为这本书和你问题的相关程度——0.9分就是"非常相关"，0.5分就是"有点关系但不太确定"。

---

### 2.4 实体类型管理（TBox）

**功能入口**：知识中心 → 实体管理 → 类型管理（TBox）

**功能说明**：
TBox（Type Box，类型层）就像数据库的"表结构定义"——它定义了系统中有哪些类型的实体（比如"矿山""设备""员工"），以及这些实体之间可以有什么关系（比如"矿山拥有设备""员工操作设备"）。

打个比方：TBox 就是"企业的名词和动词词典"——名词是实体类型（矿山、设备、工作面），动词是关系类型（拥有、位于、操作）。

**测试数据**：
- `example/knowledge-center/ontology/entity-types.json`（14种实体类型）
- `example/knowledge-center/ontology/relation-types.json`（13种关系类型）

**操作步骤**：

#### 创建实体类型

参照 `entity-types.json`，在实体类型管理页面创建以下核心实体类型（可以先创建主要的，其余按需创建）：

| 实体类型ID | 名称 | 类型 | 数据域 | 说明 |
|-----------|------|------|--------|------|
| mine | 矿山 | object | production_data | 煤矿生产经营单位 |
| coal_face | 采煤工作面 | object | production_data | 采煤作业工作面 |
| heading_face | 掘进工作面 | object | production_data | 掘进作业工作面 |
| equipment_group | 设备组 | object | equipment_data | 按功能划分的设备集合 |
| shearer | 采煤机 | object | equipment_data | 综采核心设备 |
| roadheader | 掘进机 | object | equipment_data | 掘进核心设备 |
| hydraulic_support | 液压支架 | object | equipment_data | 顶板支护设备 |
| mining_truck | 矿用卡车 | object | transport_data | 煤炭运输车辆 |
| transport_system | 运输系统 | object | transport_data | 运输子系统 |
| ventilation_system | 通风系统 | object | safety_data | 矿井通风系统 |
| safety_monitor_system | 安全监测系统 | object | safety_data | 安全监测监控系统 |
| team | 班组 | actor | production_data | 生产作业班组 |
| employee | 员工 | actor | production_data | 从业人员 |

#### 创建关系类型

参照 `relation-types.json`，创建以下核心关系类型：

| 关系类型ID | 名称 | 源类型 | 目标类型 | 说明 |
|-----------|------|--------|--------|------|
| has_subsystem | 拥有子系统 | mine | transport_system | 矿山拥有运输/通风/安全系统 |
| has_equipment_group | 拥有设备组 | mine | equipment_group | 矿山拥有设备组 |
| has_coal_face | 拥有采煤工作面 | mine | coal_face | 矿山拥有采煤工作面 |
| has_heading_face | 拥有掘进工作面 | mine | heading_face | 矿山拥有掘进工作面 |
| equipped_with | 配备 | equipment_group | shearer | 设备组配备具体设备 |
| located_in | 位于 | coal_face | mine | 工作面位于矿山 |
| responsible_for | 负责 | team | coal_face | 班组负责工作面 |
| monitors | 监测 | safety_monitor_system | mine | 安全系统监测矿山 |
| operated_by | 由...操作 | shearer | employee | 设备由员工操作 |

**验证要点**：
- 实体类型列表中能看到创建的类型
- 关系类型创建时，源类型和目标类型必须从已有的实体类型中选择
- 关系类型的基数（cardinality）正确设置（1:1、1:N、N:1、N:M）

**类比理解**：TBox 就像你在搭积木之前先定义"有哪些形状的积木"（实体类型）和"积木之间怎么拼接"（关系类型）。定义好了之后，后面才能用这些积木搭出具体的东西（ABox实体实例）。

---

### 2.5 实体实例与关系管理（ABox）

**功能入口**：知识中心 → 实体管理

**功能说明**：
ABox（Assertion Box，实例层）就是"具体的数据行"——TBox 定义了"矿山"这种类型，ABox 里就是具体的"3号矿""1号矿""2号矿"。关系也是一样，TBox 定义了"矿山拥有设备组"，ABox 里就是"3号矿拥有综采设备组"这个具体事实。

**测试数据**：
- `example/knowledge-center/ontology/entities.csv`（43个实体实例）
- `example/knowledge-center/ontology/facts.csv`（38条关系事实）

**推荐方式：批量导入**

单个创建实体太慢，推荐使用批量导入功能：

1. 进入"实体导入"页面
2. 下载模板（entities.csv 和 facts.csv）
3. 用我们提供的 `entities.csv` 和 `facts.csv` 替换模板内容
4. 先上传 `entities.csv`，点击"🔍 干跑校验"（先验证不写库）
5. 检查校验结果，确认所有实体通过校验
6. 点击"✅ 确认导入"
7. 再上传 `facts.csv`，同样先干跑校验，再确认导入

**entities.csv 格式说明**：
```csv
entity_type_id, name, business_code, data_domain_id, attributes(JSON)
mine, 3号矿, MINE-003, production_data, {"design_capacity":300}
```

**facts.csv 格式说明**：
```csv
source_code, relation_type_id, target_code, confidence
MINE-003, has_subsystem, TS-301, 1.0
```

**实体数据概览**：

| 实体类型 | 数量 | 示例 |
|---------|------|------|
| 矿山（mine） | 3 | 3号矿、1号矿、2号矿 |
| 采煤工作面（coal_face） | 3 | 3号矿综采一队工作面等 |
| 掘进工作面（heading_face） | 3 | 3号矿掘进一队工作面等 |
| 运输系统（transport_system） | 3 | 3号矿矿卡运输系统等 |
| 设备组（equipment_group） | 4 | 3号矿综采设备组等 |
| 矿用卡车（mining_truck） | 5 | MT-301至MT-304、MT-101 |
| 采煤机（shearer） | 3 | SL-301、SL-302、SL-101 |
| 掘进机（roadheader） | 3 | RH-301、RH-302、RH-101 |
| 液压支架（hydraulic_support） | 2 | HS-301-A、HS-302-A |
| 装载机（loader） | 2 | LD-301、LD-302 |
| 通风系统（ventilation_system） | 2 | VS-301、VS-101 |
| 安全监测系统（safety_monitor_system） | 2 | SMS-301、SMS-101 |
| 班组（team） | 4 | 3号矿综采一队等 |
| 员工（employee） | 4 | 张建国、李卫东、王志强、赵明辉 |
| **合计** | **43** | |

**验证要点**：
- 干跑校验显示"实体 42/42 通过""事实 35/35 通过"
- 导入后实体管理页面能看到所有实体
- 点击某个实体（如"3号矿"），详情页能看到它的关系（拥有运输系统、拥有设备组等）
- 实体的 attributes（属性）正确显示

**常见导入错误**：
| 错误提示 | 原因 | 修正 |
|---------|------|------|
| 实体类型不存在: xxx | entity_type_id 拼写错误或未创建 | 先在TBox创建对应实体类型 |
| 数据域不存在: xxx | data_domain_id 拼写错误 | 先创建对应数据域 |
| attributes 不是合法 JSON | JSON格式错误 | 用双引号，如 `{"model":"XK-500"}` |
| business_code 重复 | 同类型下编码重复 | 修改为唯一编码 |
| 源实体类型不在关系的源类型集合 | 关系方向/类型不匹配 | 检查关系类型的源类型和目标类型定义 |

**类比理解**：ABox 就像你用 TBox 定义好的积木形状，实际搭出来的东西。TBox 说"有矿山这种积木，矿山可以和运输系统拼接"，ABox 就是"我拿了一块叫3号矿的矿山积木，拼上了一块叫3号矿运输系统的运输系统积木"。

---

### 2.6 图谱探索（Graph Exploration）

**功能入口**：知识中心 → 图谱探索

**功能说明**：
图谱探索就是"实体关系的可视化地图"——你输入一个实体，系统把它和相关实体之间的关系用图形展示出来，一眼就能看清"谁和谁有关系"。

**测试数据**：已导入的43个实体和38条关系

**操作步骤**：
1. 进入图谱探索页面
2. 在搜索框输入"3号矿"或"MINE-003"
3. 选择搜索结果中的"3号矿"实体
4. 系统展示以3号矿为中心的关系图谱
5. 可以点击图中的其他节点（如"3号矿运输系统"）展开更多关系
6. 可以调整展开深度（1跳、2跳）、关系方向（前向、反向、双向）

**推荐测试路径**：

**路径1：3号矿的生产全景**
- 中心节点：3号矿
- 展开后可以看到：
  - 3号矿 → 拥有采煤工作面 → 3号矿综采一队工作面
  - 3号矿 → 拥有掘进工作面 → 3号矿掘进一队工作面
  - 3号矿 → 拥有设备组 → 3号矿综采设备组
  - 3号矿 → 拥有子系统 → 3号矿矿卡运输系统、3号矿通风系统、3号矿安全监测系统

**路径2：设备的完整关系链**
- 中心节点：3号矿综采设备组（EG-301）
- 展开后可以看到：
  - 3号矿综采设备组 → 配备 → 采煤机SL-301
  - 采煤机SL-301 → 由...操作 → 员工张建国
  - 3号矿综采设备组 → 属于 → 3号矿

**路径3：工作面的责任链**
- 中心节点：3号矿综采一队工作面（CF-301）
- 展开后可以看到：
  - 3号矿综采一队工作面 → 位于 → 3号矿
  - 3号矿综采一队工作面 ← 负责 ← 3号矿综采一队（班组）
  - 3号矿综采一队工作面 ← 支护 ← 液压支架HS-301-A

**验证要点**：
- 图谱能正常渲染，节点和边清晰可见
- 节点显示实体名称，边显示关系名称
- 点击节点能展开更多关系
- 图谱中实体之间的关系与 facts.csv 中定义的一致

**类比理解**：图谱探索就像你在百度地图上搜索"3号矿"，地图不仅显示3号矿的位置，还显示它周围的"运输系统""设备组""工作面"等相关地点，以及它们之间的"道路"（关系）。你可以点击任意地点继续探索周边。

---

### 2.7 知识检索（三层融合检索）

**功能入口**：知识中心 → 知识检索，或通过 Chat 对话

**功能说明**：
知识检索是 EARP 的核心能力——它不是简单的关键词搜索，而是**三层融合检索**：

1. **Profile层（实体档案）**：先查实体的"档案卡"——比如问"3号矿的设备情况"，系统先找到3号矿的实体档案，里面有它的设备组、关键设备等摘要信息
2. **Graph层（图谱关系）**：再查实体之间的关系——比如"3号矿的运输系统是什么"，系统通过图谱关系找到3号矿 → 拥有子系统 → 3号矿运输系统
3. **Chunk层（文档原文）**：最后查文档原文——比如"煤矿安全规程对瓦斯浓度的规定"，系统从上传的文档中找到最相关的段落

三层结果通过 RRF（Reciprocal Rank Fusion）算法融合，给出最终答案，并且每个答案都带来源引用（可以追溯到具体的实体或文档）。

**测试数据**：已导入的实体关系 + 已上传的文档

**测试用例**：

| 序号 | 测试问题 | 主要检索层 | 期望答案要点 |
|------|---------|-----------|------------|
| 1 | 3号矿有哪些运输系统？ | Graph层 | 3号矿矿卡运输系统、3号矿皮带运输系统 |
| 2 | 3号矿综采设备组配备了哪些设备？ | Graph层 | 采煤机SL-301、采煤机SL-302 |
| 3 | 谁在操作采煤机SL-301？ | Graph层 | 张建国（采煤机司机） |
| 4 | 3号矿综采一队工作面由哪个班组负责？ | Graph层 | 3号矿综采一队（TM-301） |
| 5 | 煤矿安全规程对采煤工作面安全出口有什么要求？ | Chunk层 | 至少两个畅通的安全出口，一个通回风巷一个通进风巷 |
| 6 | 瓦斯浓度达到多少必须停止工作撤出人员？ | Chunk层 | 1.5%，必须停止工作、撤出人员、切断电源 |
| 7 | 液压支架乳化液浓度要求是多少？ | Chunk层 | 3%-5%，每班用折光仪检查 |
| 8 | 原煤产量包括哪几部分？ | Chunk层 | 回采产量、掘进煤量、其他产量 |
| 9 | 3号矿的设计生产能力是多少？ | Profile层 | 300万吨/年（从实体属性中获取） |
| 10 | 矿卡运输周期包括哪几部分时间？ | Chunk层 | 装车时间、重车运行时间、卸车时间、空车返回时间 |

**验证要点**：
- 每个问题都能返回答案
- 答案带有引用来源（citations），可以点击查看来源
- 引用来源正确：关系类问题引用实体/关系，文档类问题引用文档chunk
- 答案内容准确，与测试数据一致

**类比理解**：三层检索就像你问一个博学的企业顾问一个问题：
- 他先翻翻"企业组织架构手册"（Profile层），看看有没有直接的档案记录
- 再看看"企业关系图谱"（Graph层），找找各个部门之间的关系
- 最后翻翻"规章制度汇编"（Chunk层），查找具体的条文规定
- 然后把三个来源的信息整合起来，给你一个完整的答案，并且告诉你"这个答案来自哪本书哪一页"（引用溯源）

---

### 2.8 评估管理（Evaluation）

**功能入口**：知识中心 → 探索验证 → 评估管理

**功能说明**：
评估管理就是"AI 的考试系统"——你准备一套"考试题"（评估集，包含问题和标准答案），让 AI 逐条答题，然后系统自动打分，看看 AI 的理解能力和检索能力怎么样。

评估分为两层：
1. **理解层评估（QU Evaluation）**：考 AI"听懂问题没有"——能不能正确识别问题类型、实体、关系
2. **Plan层评估（Planning Evaluation）**：考 AI"选对答题路线没有"——根据问题类型选择正确的检索策略

**测试数据**：可以使用系统内置的评估集，也可以基于我们的演示数据自定义评估集

**操作步骤**：
1. 进入评估管理页面
2. 查看系统内置的评估集（通常有 understanding 和 planning 两套）
3. 选择一个评估集，点击"运行评估"（触发跑分）
4. 等待评估完成（后台任务，需要worker进程运行）
5. 查看评估结果：总体通过率、各维度得分、逐条明细

**自定义评估集（可选）**：
基于煤矿演示数据，可以创建以下测试用例：

| 问题 | 期望意图 | 期望实体 | 期望关系 | 期望策略 |
|------|---------|---------|---------|---------|
| 3号矿有哪些运输系统？ | RELATION | 3号矿:mine | has_subsystem | plan_relation |
| 3号矿有多少台采煤机？ | AGGREGATION | 3号矿:mine | equipped_with | plan_aggregation |
| 煤矿安全规程对瓦斯有什么规定？ | FACT | 无 | 无 | plan_fact |
| 采煤机SL-301由谁操作？ | RELATION | SL-301:shearer | operated_by | plan_relation |
| 3号矿综采设备组的设备可用率是多少？ | AGGREGATION | EG-301:equipment_group | 无 | plan_aggregation |

**验证要点**：
- 评估集能正常创建和运行
- 评估结果显示各维度得分（intent准确率、实体召回率、关系准确率等）
- 逐条明细能看到每个用例的期望结果和实际结果
- 失败用例有明确的失败原因

**注意事项**：
- 评估跑分需要 worker 进程在后台运行，如果一直显示 running，检查 worker 是否启动
- 规则层（rules）跑分是确定性的，结果稳定；LLM 跑分可能有波动
- 评估结果可以作为系统优化的依据

**类比理解**：评估管理就像学校的"模拟考试"——老师出一套卷子（评估集），学生（AI）答题，老师批改打分（评估算法），最后出成绩单（评估结果），看看学生哪些知识点掌握了、哪些还需要加强。

---

### 2.9 文件场景数据集（File Dataset）

**功能入口**：知识中心 → 中台对接 → 文件场景数据集

**功能说明**：
文件场景数据集是"没有真实业务系统时的模拟数据源"——它把一个 manifest.yaml（清单文件）和多个 CSV（数据文件）打包在一起，作为因果模型运行时的取数来源。

打个比方：因果模型就像一个"医生"，它需要给病人"化验"（取数）才能诊断。文件场景数据集就是一个"模拟化验室"——里面准备好了各种化验结果（CSV数据），医生可以直接拿来用，不需要真的去医院化验。

**测试数据**：`example/knowledge-center/file-dataset/` 目录

**文件清单**：

| 文件名 | 说明 | 行数 |
|--------|------|------|
| manifest.yaml | 数据集清单，定义Provider和数据映射 | - |
| production.csv | 3号矿产量数据（2026年8月，按班次） | 62行 |
| equipment.csv | 3号矿设备可用率数据（2026年8月，按日） | 31行 |
| haulage.csv | 3号矿运输周期和排队时间数据（2026年8月，按日） | 31行 |
| entities.csv | 实体映射（发布时可导入ABox） | 3行 |
| relations.csv | 关系映射（发布时可导入ABox） | 2行 |

**数据场景设计**：

数据覆盖2026年8月1日至8月31日，设计了一个完整的"产量下降事件"：

| 时间段 | 产量 | 设备可用率 | 运输周期 | 排队时间 | 状态 |
|--------|------|-----------|---------|---------|------|
| 8月1日-19日 | 5000-5500吨/日 | 93-96% | 19-22分钟 | 3-5分钟 | 正常 |
| 8月20日-31日 | 4000-4500吨/日 | 80-83% | 30-35分钟 | 14-17分钟 | 异常下降 |

**业务逻辑**：
- 8月20日起，3号矿关键设备组出现批量故障，设备可用率从95%下降到80%
- 同时，运输系统因为装载机不足和道路维护，运输周期从20分钟增加到30分钟以上
- 排队时间从4分钟增加到15分钟，进一步加剧了运输瓶颈
- 综合导致日产量从5200吨下降到4200吨，下降幅度约19%

**操作步骤**：

#### 第一步：上传并校验
1. 进入"文件场景数据集"页面
2. 选择 manifest.yaml 文件
3. 同时选择所有被引用的 CSV 文件（production.csv、equipment.csv、haulage.csv、entities.csv、relations.csv）
4. 点击"上传并校验"
5. 系统创建 staged（暂存）版本，显示校验报告

#### 第二步：检查校验报告
- 检查数据集ID：`mine3-production-demo`
- 检查Provider数量：3个（production、equipment、haulage）
- 检查每个CSV的行数和有效行数
- 检查是否有 warning（坏行、格式错误等）
- 我们的数据应该全部通过，无错误

#### 第三步：发布
1. 确认校验通过后，点击"发布最新暂存版本"
2. 发布后，数据集中的实体和关系会自动导入共享ABox（按business_code复用，不覆盖已有数据）
3. 发布后的数据集可以被因果模型引用

#### 第四步：在因果规划中使用
调用因果模型规划入口时，传入 dataset_id：
```json
POST /v1/ecmc/planning/entry
{
  "text": "为什么3号矿产量下降？",
  "dataset_id": "mine3-production-demo"
}
```

系统会从文件场景数据集中取数，作为因果诊断的证据。

**验证要点**：
- 上传后校验通过，无致命错误
- 发布成功，数据集状态为 published
- 数据集中的实体（mine-3、critical-equipment-group-mine-3、haulage-system-mine-3）在ABox中可见
- 因果规划时传入 dataset_id 能正常取数
- 取数结果与CSV中的数据一致

**manifest.yaml 关键字段说明**：

```yaml
providers:
  - provider_key: file-production-metric-v1      # Provider唯一标识
    capability_contract_ref: production_metric_query  # 绑定的能力合同
    file: production.csv                           # 数据文件名
    entity_column: entity_id                       # 实体列名
    time_column: observed_at                       # 时间列名
    requirements:
      production_actual_and_baseline:              # 需求key（必须与因果模型中的Evidence Requirement对应）
        value_column: value                         # 实际值列名
        baseline_column: baseline                   # 基线值列名
        unit: t                                     # 单位
```

**类比理解**：文件场景数据集就像一个"数据剧本"——manifest.yaml 是剧本的"角色表和场景说明"，CSV是每一场戏的"具体台词和动作"。因果模型这个"演员"按照剧本的要求，在对应的场景（时间窗口）里取对应的台词（数据），然后完成表演（诊断分析）。

---

### 2.10 Catalog 语义目录

**功能入口**：知识中心 → 目录管理 → Catalog 治理

**功能说明**：
Catalog（语义目录）是企业的"标准化业务词典"——它统一定义了"产量""设备可用率""运输周期"这些业务术语的精确含义、单位、计算方式，确保全企业（以及AI模型）对同一个词的理解一致。

打个比方：如果没有Catalog，A部门说的"产量"可能是"原煤产量"，B部门说的"产量"可能是"精煤产量"，C部门说的"产量"可能是"商品煤产量"——大家鸡同鸭讲。Catalog 就是强制规定"以后说'产量'，统一指原煤产量，单位吨，按日求和"。

**测试数据**：`example/catalog/` 目录下的7个JSON文件

**Catalog 支持的10种对象（Kind）**：

| Kind | 说明 | 演示数据数量 | 文件 |
|------|------|------------|------|
| data_domain | 数据域 | 4个 | data-domains.json（在ontology目录） |
| entity_type | 实体类型 | 14种 | entity-types.json（在ontology目录） |
| relation_type | 关系类型 | 13种 | relation-types.json（在ontology目录） |
| metric | 指标 | 8个 | metrics.json |
| unit | 单位 | 10种 | units.json |
| aggregation | 聚合方式 | 7种 | aggregations.json |
| time_window_schema | 时间窗口 | 5种 | time-windows.json |
| binding_template | 绑定模板 | 4种 | binding-templates.json |
| capability_contract | 能力合同 | 5个 | capability-contracts.json |
| rule_schema | 规则Schema | 4种 | rule-schemas.json |

**核心指标定义（metrics.json）**：

| 指标ID | 名称 | 单位 | 聚合 | 时间窗口 | 说明 |
|--------|------|------|------|---------|------|
| raw_coal_output | 原煤产量 | 吨(t) | sum | 日窗口 | 回采产量+掘进煤量+其他产量 |
| equipment_availability | 设备可用率 | 比率(%) | avg | 日窗口 | 可用时间/制度工作时间 |
| haulage_cycle_time | 矿卡运输周期 | 分钟(min) | avg | 日窗口 | 装车+重车运行+卸车+空车返回 |
| haulage_queue_time | 装载点排队时间 | 分钟(min) | avg | 日窗口 | 到达装载点到开始装载的等待时间 |
| ore_quality_index | 原矿品位指数 | 无量纲 | avg | 日窗口 | 灰分+发热量+硫分的加权评分 |
| heading_advance | 掘进进尺 | 米(m) | sum | 日窗口 | 掘进工作面实际掘进长度 |
| gas_concentration | 瓦斯浓度 | 比率(%) | max | 日窗口 | 甲烷体积百分比，取日最大值 |
| air_volume | 风量 | 立方米(m³) | avg | 日窗口 | 单位时间通过巷道断面的空气体积 |

**操作步骤**：

#### 第一步：注册引用（Registration）
Catalog 不直接编辑业务语义，而是"注册"已经在权威源系统发布的精确引用：
1. 进入 Catalog 治理页面
2. 点击"引用注册"
3. 输入：来源系统（如"煤矿生产管理系统"）、kind（如 metric）、stable_id（如 coal.raw_coal_output）、version（如 1.0.0）
4. 系统自动读取 canonical input 并计算 content_hash
5. 注册成功后，该引用可以被Pack和模型引用

> **注意**：当前Phase 1使用Mock/Test Adapter，可以在测试环境验证注册流程。生产环境需要真实源系统接入。

#### 第二步：创建Pack
Pack是"引用的组合包"，分为三层：
- 平台基础包（platform）：跨行业通用的基础概念（吨、分钟、平均值等）
- 行业包（industry）：煤矿行业特有的业务概念（原煤产量、设备可用率等）
- 企业扩展包（enterprise）：某家企业自己的业务口径

操作：
1. 进入 Pack 管理
2. 创建 Pack 草稿，选择层级（如 industry）
3. 把已注册的引用加入Pack（如煤矿行业的8个指标）
4. 提交发布申请，由Pack owner审批并履约发布

#### 第三步：创建Profile
Profile是"项目级配置"，定义行业范围、企业范围、数据域和治理角色：
1. 进入项目配置（Profile）页面
2. 创建Profile，填写：
   - industry_scope: coal_mining（煤矿行业）
   - enterprise_scope: 某煤矿集团
   - data_domain: production（生产数据域）
   - 治理角色：产品负责人、平台架构师、数据域负责人等
3. 可以参考 `example/catalog/../arch/catalog/profiles/jqmk-coal-production-v2.yaml` 的格式

#### 第四步：生成Manifest并激活
Manifest是"当前生效的引用组合清单"：
1. 进入 Manifest 管理
2. 选择已发布的Pack（平台基础包+煤矿行业包+企业扩展包）
3. 生成 Manifest 预览，检查条目、层级组合和hash
4. 获得外部签署的 attestation 后，激活 Manifest
5. 激活后，Resolver 才能向 ECMC 等调用方返回该 Profile 中的精确引用

#### 第五步：在因果模型中使用
在ECMC创建因果模型时，所有可执行字段（指标、单位、聚合、时间窗口、绑定模板、能力合同、规则Schema）都必须从Catalog中选择，不能手填。

**验证要点**：
- 引用注册成功，系统自动计算hash
- Pack创建、提交审批、发布流程正常
- Profile创建成功，角色配置正确
- Manifest生成预览、激活流程正常
- 激活后，ECMC模型编辑器中能从Catalog选择器中看到这些引用
- 未注册、已撤销、hash漂移或不在当前Manifest中的引用会被拒绝

**Catalog的5个页面**：
1. **Catalog 治理**：核心操作（引用注册、Pack管理、Manifest管理）
2. **项目配置**：Profile管理
3. **指标管理**：Catalog运行摘要、同步记录
4. **基础配置**：单位、聚合、时间窗口、规则模式的接入状态
5. **绑定模板**：绑定模板接入状态

> **注意**：当前Phase 1，指标管理、基础配置、绑定模板页面在真实源列表API未接入时会显示空态或readiness HOLD，这是预期的保护行为，不是功能缺失。

**类比理解**：Catalog 就像企业的"标准化管理委员会"：
- **引用注册** = 把国家标准、行业标准登记在册
- **Pack** = 把相关标准打包成"煤矿行业标准汇编"
- **Profile** = 某个具体项目"采用哪些标准、谁负责管理"
- **Manifest** = 当前生效的标准清单（有版本、有签字、可追溯）
- **Resolver** = 标准查询窗口，业务系统问"'产量'是什么标准？"，Resolver从当前Manifest中找到精确答案

这样做的好处是：业务语义变更必须走标准发布流程，不能谁都能改；AI模型使用的都是经过审核的标准定义，不会出现"各说各话"的情况。

---

## 三、模型中心（ECMC）功能测试指南

ECMC（Enterprise Cognitive Model Center，企业认知模型中心）是 EARP 的"专家经验固化系统"——它把业务人员头脑中的"为什么会发生"的因果经验，转化为可版本化、可审核、可编译、可安全投产的因果模型。

### 3.1 ECMC 核心概念（30秒搞懂）

| 概念 | 一句话解释 | 类比 |
|------|-----------|------|
| Draft Version | 正在编辑的模型版本 | 正在修改的Word文档 |
| 提交审核 | 把文档发给负责人审阅 | 把方案发给领导审批 |
| Snapshot | 审核通过后盖章存档的PDF | 审批通过的正式文件 |
| Compile | 把盖章方案转成系统能执行的配置 | 把设计图转成施工方案 |
| Candidate Artifact | 编译成功但还没上线的安装包 | 生产好但还没安装的软件包 |
| Activation | 明确选择一个安装包上线 | 点击"安装并启用" |
| Active Version | 当前生产环境正在使用的版本 | 当前正在运行的软件版本 |

**最重要的一句话**：发布 ≠ 编译 ≠ 激活
- 发布只是"盖章存档"，还没有上线
- 编译是"转成可执行格式"，还没有上线
- 激活才是"正式上线"，新诊断才开始使用新模型

这是 ECMC 的安全设计——一个新模型即使有问题，也不会直接替换当前生产模型，必须经过三道关卡（审核发布→编译→显式激活）才能上线。

### 3.2 新建因果模型

**功能入口**：认知模型 → 模型资产 → 因果模型 → "+ 新建模型"

**测试数据**：`example/model-center/causal-models/mine3-production-drop-diagnosis.json`

**操作步骤**：
1. 进入因果模型列表页面
2. 点击"+ 新建模型"
3. 填写模型基本信息（参照 JSON 文件中的 model_info）：

| 字段 | 填写值 | 说明 |
|------|--------|------|
| 模型类型 | 因果模型 | 当前只支持因果模型，决策模型和任务模型规划中 |
| 数据域 | production_data（生产数据） | 去哪个业务范围找数据和目录项 |
| 目标实体类型 | mine（矿山） | 诊断对象是什么 |
| 诊断方向 | down（下降） | 我们关注指标下降 |
| 入口节点key | production_output | 从哪个结果开始倒推原因 |
| 时间窗口 | daily（日窗口） | 按一天的数据做判断 |
| 模型名称 | 3号矿产量下降诊断 | 建议命名：业务对象+异常/变化+诊断 |
| 业务说明 | 用于诊断3号矿日产量低于计划时的主要业务原因 | 模型的用途说明 |

4. 检查 Diagnostic Target 摘要，确认后创建
5. 创建成功后，系统建立 Logical Model 和首个 Draft Version，进入编辑器

**验证要点**：
- 模型创建成功，进入编辑器
- 模型列表中能看到"3号矿产量下降诊断"
- Diagnostic Target（数据域、目标实体类型、诊断方向、入口节点、时间窗口）创建后不可修改

**类比理解**：新建因果模型就像医生"建立病历"——先确定"看什么病"（诊断目标：3号矿产量下降），然后才能开始"分析病因"（添加原因节点和因果关系）。

---

### 3.3 编辑因果模型（节点、边、证据、规则）

**功能入口**：因果模型编辑器

**编辑器布局**：
- 顶部：模型名、Version、状态、revision、治理操作
- 左侧：节点、边、证据和规则结构树
- 中央：因果DAG（有向无环图）可视化
- 右侧：当前选中资源的属性面板
- 底部：校验结果抽屉

**测试数据**：`mine3-production-drop-diagnosis.json` 中的 nodes、edges、evidence_requirements、rules

#### 第一步：创建节点

参照 JSON 文件中的 nodes 定义，创建以下6个节点：

| node_key | 业务名称 | 可观测性 | 是否入口 | 说明 |
|----------|---------|---------|---------|------|
| production_output | 原煤产量 | observable | ✅ 是 | 入口节点，诊断目标 |
| effective_production_capacity | 有效生产能力 | indirectly_observable | 否 | 中间节点，综合因素后的实际产能 |
| equipment_availability | 关键设备可用率 | observable | 否 | 原因节点，设备故障影响产能 |
| haulage_cycle_time | 矿卡运输周期 | observable | 否 | 原因节点，运输效率影响产能 |
| haulage_queue_time | 装载点排队时间 | observable | 否 | 原因节点，运输拥堵的佐证 |
| ore_quality | 原矿品位 | observable | 否 | 原因节点，质量因素（影响较小） |

**节点创建要点**：
- 入口节点必须是 observable（可直接观测），且一个版本恰好有一个入口节点
- observability 三种值：
  - `observable`：可由证据直接观测（有指标数据）
  - `indirectly_observable`：通过其他因素间接判断（如"有效生产能力"无法直接测量）
  - `latent_hypothesis`：潜在假设，可能没有直接证据

#### 第二步：添加边（因果关系）

参照 JSON 文件中的 edges 定义，创建以下5条边：

| 边 | 源节点 → 目标节点 | effect | strength | confidence | 说明 |
|----|------------------|--------|----------|------------|------|
| 1 | equipment_availability → effective_production_capacity | + | 0.85 | 0.95 | 设备可用率越高，产能越强 |
| 2 | haulage_cycle_time → effective_production_capacity | - | 0.90 | 0.95 | 运输周期越长，产能越低 |
| 3 | haulage_queue_time → effective_production_capacity | - | 0.80 | 0.90 | 排队时间越长，产能越低 |
| 4 | effective_production_capacity → production_output | + | 0.95 | 0.98 | 产能直接决定产量 |
| 5 | ore_quality → production_output | + | 0.55 | 0.85 | 品位对产量有一定影响（较小） |

**effect（影响方向）说明**：
- `+`：源因素增加时，目标也增加（正相关）。如"设备可用率越高，产量越高"
- `-`：源因素增加时，目标减少（负相关）。如"运输周期越长，产量越低"

**DAG约束**：
- 必须是有向无环图（DAG），不能有环路
- 不能有悬空端点（节点没有边连接）
- 所有节点必须能通向入口目标

**错误示例（会被校验阻断）**：
```
产量 → 运输周期 → 排队时间 → 产量  （形成了环，校验阻断）
```

#### 第三步：添加 Evidence Requirement（证据需求）

参照 JSON 文件中的 evidence_requirements，为每个可观测节点添加证据需求。证据需求定义了"系统需要什么数据来验证这个节点"。

以"原煤产量"节点为例：

| 字段 | 填写值 | 说明 |
|------|--------|------|
| requirement_id | er-production-actual-and-baseline | 需求唯一标识 |
| node_key | production_output | 关联的节点 |
| required | true（必填） | 缺少该证据时是否阻断诊断 |
| metric | 原煤产量（从Catalog选择） | 要看什么指标 |
| unit | 吨（从Catalog选择） | 指标用什么单位 |
| aggregation | sum（求和，从Catalog选择） | 多条记录如何汇总 |
| time_window | daily（日窗口，从Catalog选择） | 看哪段时间 |
| binding_template | 上下文实体绑定（从Catalog选择） | 如何找到目标实体 |
| binding_params | {"expected_entity_type": "mine"} | 模板参数 |
| primary_capability_contract | 产量指标查询（从Catalog选择） | 首选的取数能力 |
| business_description | 获取目标矿山的日原煤产量实际值和基线值 | 业务说明 |

**5个证据需求清单**：
1. **原煤产量**（required）：metric=原煤产量, unit=吨, aggregation=sum, binding=上下文实体
2. **设备可用率**（required）：metric=设备可用率, unit=比率, aggregation=avg, binding=出向关系(has_equipment_group→equipment_group)
3. **运输周期**（required）：metric=矿卡运输周期, unit=分钟, aggregation=avg, binding=出向关系(has_subsystem→haulage_system)
4. **排队时间**（optional）：metric=装载点排队时间, unit=分钟, aggregation=avg, binding=出向关系(has_subsystem→haulage_system)
5. **原矿品位**（optional）：metric=原矿品位指数, unit=无量纲, aggregation=avg, binding=上下文实体

**关键约束**：
- 所有可执行字段（metric、unit、aggregation、time_window、binding_template、capability_contract）必须从Catalog选择器中选择，**不能手填**
- required evidence 必须选择 primary Capability Contract，否则校验阻断
- binding_params 只能填写 BindingTemplate schema 声明的字段
- primary Contract 失败时系统不会自动改用 supporting Contract（自动failover属于后续能力）

#### 第四步：添加规则（Rules）

参照 JSON 文件中的 rules，为节点添加异常判定规则：

| rule_key | 节点 | 规则类型 | 参数 | 业务含义 |
|----------|------|---------|------|---------|
| rule-production-drop-detection | production_output | direction_rule | relative_change_lte, threshold=-0.10, direction=down | 产量相对基线下降超过10%，标记为异常 |
| rule-equipment-low-availability | equipment_availability | threshold | absolute_lte, threshold=0.90 | 设备可用率低于90%，标记为异常 |
| rule-cycle-time-increase | haulage_cycle_time | direction_rule | relative_change_gte, threshold=0.20, direction=up | 运输周期相对基线增加超过20%，标记为异常 |
| rule-queue-time-increase | haulage_queue_time | direction_rule | relative_change_gte, threshold=0.50, direction=up | 排队时间相对基线增加超过50%，标记为异常 |
| rule-quality-stable | ore_quality | predicate | absolute_relative_change_lt, threshold=0.05 | 品位变化小于5%，认为稳定可排除 |

**规则类型**：
- `threshold`：基于绝对值的阈值判定（如"可用率低于90%"）
- `direction_rule`：基于相对基线变化率的方向判定（如"产量下降超过10%"）
- `predicate`：通用布尔谓词规则

**验证要点**：
- 6个节点全部创建，入口节点正确设置
- 5条边全部创建，DAG无环、无悬空节点
- 5个证据需求全部添加，required证据有primary contract
- 所有可执行字段都从Catalog选择，无手填
- 5条规则全部添加，参数正确
- 中央DAG可视化正常，节点和边清晰可见

**类比理解**：编辑因果模型就像医生"画诊断流程图"：
- **节点** = 症状和病因（"产量下降"是症状，"设备故障""运输慢"是病因）
- **边** = 因果关系箭头（"设备故障→产量下降"）
- **证据需求** = 需要做什么化验来验证每个症状/病因（"查产量记录""查设备运行日志"）
- **规则** = 化验结果的判读标准（"产量下降超过10%算异常""可用率低于90%算异常"）

画好这张图，AI 就能按照这个流程自动诊断了。

---

### 3.4 校验模型

**功能入口**：编辑器顶部 → "校验"按钮

**功能说明**：
校验就是"模型的体检"——系统检查模型是否符合所有约束条件，有问题就列出来，阻断提交审核。

**操作步骤**：
1. 在编辑器中点击顶部"校验"按钮
2. 系统运行 full validation（全量校验）
3. 校验结果显示在底部抽屉中
4. 每条问题包含：稳定code、message、severity、定位信息、建议处理动作
5. 点击问题可以定位到对应资源

**Error（阻断）vs Warning（警告）**：

| 类型 | 是否阻断提交/发布 | 示例 |
|------|------------------|------|
| Error / 阻断 | 是 | DAG有环、入口缺失、CatalogRef无效、required evidence缺失 |
| Warning / 警告 | 否 | 置信度偏低、lag过长、适用范围过窄 |

**推荐测试：故意制造错误再修复**

为了测试校验功能，可以故意制造以下错误，观察校验是否能检测到：

1. **环路错误**：添加一条 production_output → equipment_availability 的边，形成环路 → 校验应报"DAG有环"
2. **入口缺失**：把 production_output 的 is_entry_node 改为 false → 校验应报"入口节点缺失"
3. **required evidence缺失**：删除 production_output 的证据需求 → 校验应报"required evidence缺失"
4. **CatalogRef无效**：（如果支持手填的话）输入一个不存在的metric → 校验应报"CatalogRef无效"
5. **入口节点observability错误**：把入口节点的observability改为 latent_hypothesis → 校验应报"入口节点必须observable"

修复后再次校验，确认所有Error都已解决。

**验证要点**：
- 校验功能正常运行，结果显示在底部抽屉
- Error类型的问题能正确检测并阻断
- Warning类型的问题能检测但不阻断
- 点击问题能定位到对应资源
- 修复后重新校验，问题消失
- 全量校验通过后，才能提交审核

**类比理解**：模型校验就像"论文查重+格式审查"——提交审核之前，系统自动检查你的模型有没有"逻辑硬伤"（比如因果关系形成了环）、有没有"缺项漏项"（比如必填证据没填）、有没有"引用错误"（比如Catalog里没有这个指标）。有硬伤就不让你提交，必须改好了才能送审。

---

### 3.5 提交审核与驳回

**功能入口**：编辑器顶部 → "提交审核"按钮；审核发布 → 待审核

**功能说明**：
提交审核就是"把方案发给领导审批"——建模者完成模型编辑后，提交给审核者审查。审核者可以通过（发布）或驳回（要求修改）。

**操作步骤**：

#### 建模者：提交审核
1. 在 Draft 编辑器中，确认校验通过（无Error）
2. 点击顶部"提交审核"
3. 系统先运行 full validation，有阻断项时保持Draft并打开校验面板
4. 无阻断项时，Version 进入 `in_review` 状态，内容锁定（不可编辑）

#### 审核者：审核与驳回
1. 进入"审核发布 → 待审核"页面
2. 打开待审核的模型版本（只读）
3. 审核者应检查：
   - Diagnostic Target 是否正确
   - 节点和边是否表达真实业务因果关系
   - required Evidence 是否充分
   - CatalogRef 是否属于正确数据域
   - primary Capability Contract 是否合理
   - 警告是否可以接受
4. **驳回**：需要修改时点击"驳回"，必须填写原因。驳回后 Version 回到 `draft` 状态，revision 递增，内容保留
5. **通过并发布**：审核通过后点击"通过并发布"，确认模型信息后发布

**推荐测试：完整的驳回-修改-再提交流程**

1. 建模者提交审核
2. 审核者驳回，填写原因："运输周期节点的证据需求缺少supporting contract，请补充设备故障记录查询作为佐证"
3. 建模者收到驳回通知，Version回到draft
4. 建模者修改：为运输周期节点添加 supporting Capability Contract
5. 建模者再次提交审核
6. 审核者通过并发布

**验证要点**：
- 提交审核前自动运行校验，有Error时不允许提交
- 提交后Version状态变为 in_review，内容锁定不可编辑
- 驳回必须填写原因，驳回后Version回到draft，内容保留
- 驳回后revision递增
- 发布后Version状态变为 published + inactive，生成Snapshot ID和hash
- 发布后内容变为只读
- **发布不会改变Active Version**（当前生产诊断仍使用旧模型）

**重要提醒**：
> "发布成功"不等于"已经上线"！发布只是盖章存档，还需要编译成功并显式激活，新模型才会真正用于生产诊断。

**类比理解**：提交审核就像"员工写好方案发给经理审批"：
- 提交审核 = 把方案发出去，自己不能再改了
- 审核者驳回 = 经理说"这里不行，改改再给我"，方案退回来，你可以继续改
- 审核通过发布 = 经理签字盖章，方案正式生效（但还没执行）
- 注意：签字盖章的方案不会自动变成执行动作，还需要后续的"编译"和"激活"

---

### 3.6 编译（Compile）

**功能入口**：已发布Version详情 → "编译"按钮；或 编译与激活 → 最新编译状态

**功能说明**：
编译就是"把盖章的方案转成系统能执行的配置"——发布后的Snapshot是业务语义（人能看懂的因果图），编译把它转成 Candidate Artifact（系统能执行的Blueprint）。

**操作步骤**：
1. 打开已发布的Version（状态必须是 published）
2. 点击"编译"按钮
3. 系统创建新的 Compile Attempt，初始状态为 `running`
4. 刷新治理状态，等待编译完成（success 或 failed）
5. 编译成功后，生成 Candidate Artifact JSON、Artifact hash、Artifact schema version
6. 编译失败时，失败Attempt保留，不能原地修改，重试必须创建新的Attempt

**编译状态机**：
```
running → success
        → failed
```

**推荐测试：编译失败与重试**

（如果环境支持模拟编译失败）
1. 发布v1版本，编译成功
2. 发布v2版本（故意引入一些问题），编译失败
3. 观察：v1继续作为Active Version服务（last-known-good）
4. 修复v2的问题，重新发布v2.1
5. 对v2.1发起编译，创建新的Compile Attempt（retry_of指向之前的失败Attempt）
6. 编译成功

**验证要点**：
- 只有 published 状态的Version可以编译，draft/in_review不可以
- 编译创建Compile Attempt，状态从running开始
- 成功Attempt有不可变的Artifact JSON、hash、schema version
- 失败Attempt保留，重试创建新Attempt并记录 retry_of_compile_id
- 编译只读取发布时生成的immutable Snapshot，不读取后来创建的Draft
- 编译失败不影响旧Active Version（last-known-good）
- 编译成功不会自动激活，还需要显式激活

**类比理解**：编译就像"把建筑设计图转成施工方案"：
- 设计图（Snapshot） = 人能看懂的图纸，画了"这里要建一栋楼"
- 施工方案（Candidate Artifact） = 施工队能执行的详细方案，包括"先挖地基、再搭钢筋、然后浇混凝土"的具体步骤
- 编译 = 设计院把设计图转成施工方案的过程
- 编译失败 = 设计图有问题，转不成可执行的施工方案，需要改设计图重新来
- 注意：施工方案做好了不等于已经开工了，还需要"激活"（下达开工令）

---

### 3.7 显式激活（Activation）

**功能入口**：已发布Version详情 → "激活"按钮；或 编译与激活 → Active Versions

**功能说明**：
激活是"正式上线"的最后一道关卡——只有显式选择一个编译成功的Candidate Artifact并点击激活，新模型才会真正用于生产诊断。这是ECMC最重要的安全设计：**系统永远不会自动上线新模型**。

**操作步骤**：
1. 打开已发布Version的治理信息
2. 确认有编译成功的Compile Attempt（status=success）
3. 点击"激活"按钮
4. 在确认框中检查：
   - Candidate Version（要上线的版本号）
   - Compile Attempt ID
   - Artifact hash
   - 当前 active pointer（当前正在使用的版本）
   - expected active pointer（激活后将使用的版本）
5. 确认无误后点击"确认激活"
6. 激活成功后：
   - 新Version成为 Active
   - 旧Active Version进入 superseded（被取代）状态
   - 新诊断开始使用新模型

**激活前后状态变化示例**：
```
激活前：
  v1 = Active（当前生产使用）
  v2 = Published + Compile success + inactive（已编译但未上线）

激活v2后：
  v1 = superseded（被取代，不再用于新诊断）
  v2 = Active（新诊断开始使用v2）
```

**并发冲突测试（ACTIVE_VERSION_CHANGED）**：

如果环境支持多用户并发，可以测试：
1. 用户A和用户B同时打开v2的激活确认框
2. 用户A先点击确认激活，v2成为Active
3. 用户B再点击确认激活，系统返回 `409 ACTIVE_VERSION_CHANGED`
4. 用户B的激活操作零业务写入：不产生Blueprint、不改变Version状态、不改变active pointer
5. 用户B需要刷新当前active pointer，重新核对后由用户明确确认，不能自动重试

**验证要点**：
- 激活必须选择一个 success 状态的Compile Attempt，不能激活failed的
- 激活确认框显示完整的版本信息和hash
- 激活成功后，新Version成为Active，旧Version进入superseded
- 激活只物化用户明确选择的Artifact，不重新编译、不自动挑选其他成功Attempt
- ACTIVE_VERSION_CHANGED冲突时零业务写入，要求重新确认
- 归档当前Active Version会原子清空active pointer并withdraw对应Blueprint
- **没有激活的模型，即使发布和编译都成功，也不会用于生产诊断**

**类比理解**：激活就像"软件的正式安装启用"：
- 你下载了一个软件安装包（Candidate Artifact）
- 但安装包放在硬盘上不会自动运行
- 你必须双击安装、确认协议、选择安装路径，然后点击"完成"（显式激活）
- 软件才会真正安装并运行
- EARP的设计更严格：即使安装包准备好了，系统也不会自动安装，必须有人明确点击"激活"才行
- 这样做的好处是：新版本有问题也不会偷偷替换掉正在稳定运行的旧版本

---

### 3.8 ECMC 完整演示流程（推荐）

给客户演示时，建议按照以下完整流程展示 ECMC 的治理闭环：

| 步骤 | 操作 | 演示重点 |
|------|------|---------|
| 1 | 新建"3号矿产量下降诊断"模型 | 定义诊断目标（谁、什么变化、从哪开始追原因） |
| 2 | 创建入口节点和原因节点 | 业务因果图的构建过程 |
| 3 | 添加因果边 | 因果关系的方向（+/-）和强度 |
| 4 | 添加Evidence Requirement | 展示metric/unit/aggregation/binding/contract都来自受控Catalog（不能手填） |
| 5 | 添加规则 | 异常判定标准（产量降10%算异常、可用率低于90%算异常） |
| 6 | 故意制造一个阻断错误（如环路） | 展示校验功能的问题定位 |
| 7 | 运行校验，展示问题定位 | 校验能精准找到错误位置 |
| 8 | 修复后提交审核 | 提交前自动校验，有Error不允许提交 |
| 9 | 使用审核权限驳回一次 | 展示驳回原因和返回Draft的流程 |
| 10 | 再次提交并治理发布 | 展示Snapshot ID和hash，强调"发布≠上线" |
| 11 | 发起编译，展示running→success | 展示Candidate Artifact hash，强调"编译≠上线" |
| 12 | 激活指定Artifact | 展示Active Version更新，这才是真正上线 |
| 13 | 说明旧active在编译期间一直正常服务 | last-known-good安全设计 |

**FDE可直接照读的客户话术**：

> 介绍ECMC：
> "知识中心保存企业已有的资料和事实，ECMC保存企业如何解释问题的模型。这里不是直接写程序，而是把业务专家的因果经验做成可审核、可追溯的资产。"

> 介绍受控目录：
> "模型里选择的是'运输周期'这个业务指标，而不是某个数据库字段或接口地址。将来数据源变化时，模型语义不需要跟着改。"

> 介绍发布与激活：
> "发布相当于审批盖章，激活才是正式上线。中间还有一次编译检查，因此一个新模型即使有问题，也不会直接替换当前生产模型。"

> 介绍last-known-good：
> "新版本编译失败时，旧版本照常服务。系统不会为了追新版本而牺牲当前稳定运行。"

---

## 四、完整演示流程（端到端）

以下是一个完整的端到端演示流程，从数据准备到因果诊断，展示 EARP 的核心能力：

### 阶段一：知识准备（知识中心）

| 序号 | 操作 | 使用的数据 | 预期结果 |
|------|------|-----------|---------|
| 1 | 创建4个数据域 | data-domains.json | 生产/设备/运输/安全数据域创建成功 |
| 2 | 创建3个知识库并上传5份文档 | business-documents/ | 文档上传成功，生成chunk |
| 3 | 创建14种实体类型和13种关系类型 | entity-types.json, relation-types.json | TBox创建成功 |
| 4 | 批量导入43个实体和38条关系 | entities.csv, facts.csv | ABox导入成功，干跑校验全通过 |
| 5 | 图谱探索查看3号矿的关系网络 | 已导入的ABox | 3号矿→运输系统/设备组/工作面的关系清晰可见 |
| 6 | 召回测试验证文档检索 | 已上传的文档 | 8个测试问题都能返回相关结果 |
| 7 | 上传并发布文件场景数据集 | file-dataset/ | mine3-production-demo发布成功，3个Provider可用 |

### 阶段二：模型构建（模型中心）

| 序号 | 操作 | 使用的数据 | 预期结果 |
|------|------|-----------|---------|
| 8 | 注册Catalog引用（指标/单位/聚合等） | catalog/*.json | 煤矿行业的8个指标等引用注册成功 |
| 9 | 新建"3号矿产量下降诊断"因果模型 | mine3-production-drop-diagnosis.json | 模型创建成功，进入编辑器 |
| 10 | 编辑模型：6节点+5边+5证据需求+5规则 | 同上JSON | 模型内容完整，DAG可视化正常 |
| 11 | 校验模型 | - | 全量校验通过，无Error |
| 12 | 提交审核→审核通过并发布 | - | Snapshot生成，Version状态published |
| 13 | 编译模型 | - | Compile Attempt success，Candidate Artifact生成 |
| 14 | 激活模型 | - | Version状态变为Active，新诊断使用该模型 |

### 阶段三：运行诊断（端到端验证）

| 序号 | 操作 | 使用的数据 | 预期结果 |
|------|------|-----------|---------|
| 15 | 发起因果诊断："为什么3号矿8月下旬产量下降？" | dataset_id=mine3-production-demo | 系统从文件数据集取数，执行因果诊断 |
| 16 | 查看诊断结果 | - | 诊断结论：运输周期变长(+50%)和设备可用率下降(至80%)是主要原因，排队时间增加(+200%)加剧运输瓶颈，原矿品位稳定可排除 |
| 17 | 查看证据溯源 | - | 每个结论都有对应的指标数据作为证据，可追溯到具体CSV行 |
| 18 | 知识检索验证："3号矿的运输系统有哪些？" | 已导入的ABox | 返回3号矿矿卡运输系统和皮带运输系统，带实体引用 |
| 19 | 文档问答验证："煤矿安全规程对瓦斯浓度有什么规定？" | 已上传的文档 | 返回安全规程中的具体条款，带文档引用溯源 |

---

## 五、常见问题排查（FAQ）

### 5.1 知识中心常见问题

| 现象 | 可能原因 | 排查/解决 |
|------|---------|----------|
| 检索搜不到刚导入的实体 | ①实体未active ②查询没触发该数据域路由 ③实体名称与查询差异大 | ①实体管理查状态 ②召回测试看路由调试 ③用实体名精确词 |
| 图谱没有关系 | 该实体没有活跃事实（facts未建或已撤销） | 实体管理详情看关系数；facts.csv补导入 |
| 实体档案显示旧事实 | profile无写时失效（已知tech-debt） | 导入/建关系后档案自动重编；如仍旧，删除entity_profiles行后重新检索触发重编 |
| 导入报"关系类型不存在" | relation_type_id拼写错或不在TBox | 打开实体导入页TBox一览核对 |
| chat回答没有引用 | 检索没命中（问题在知识外）或回答没用到资料 | 用召回测试确认能命中；拒答是正常行为（知识外不编造） |
| 纯中文实体名搜不到 | 实体识别分词局限 | 用完整实体名或带英文/数字的编码搜索 |
| 评估跑分一直running | worker进程未启动 | 启动 `python -m earp_server.entrypoints.worker`；worker重启后遗留running自动标failed |

### 5.2 ECMC 常见问题

| 现象 | 可能原因 | 排查/解决 |
|------|---------|----------|
| HTTP_401 | 未登录、token过期 | 重新登录，再刷新ECMC |
| 403 | 缺少对应操作权限或数据域授权 | 检查RBAC和data-domain scope |
| 404 | ID错误、跨租户或资源不可见 | 核对登录租户和资源来源 |
| MODEL_VALIDATION_FAILED | 模型存在阻断项 | 打开底部校验面板逐项修复 |
| VERSION_CONFLICT | 当前revision已过期 | 重新加载Version，不要静默覆盖 |
| INVALID_STATE_TRANSITION | 在错误状态执行操作 | 核对Draft/in_review/published等状态 |
| RESOURCE_HAS_DEPENDENTS | 删除对象仍被其他资源引用 | 先显式删除依赖 |
| 发布后诊断仍使用旧模型 | 尚未激活 | 编译成功后显式激活指定Artifact |
| 编译失败后旧模型仍在运行 | 正常的last-known-good行为 | 修复候选后创建新的Compile Attempt |
| Catalog页面显示readiness HOLD或新建按钮不可用 | 真实源列表API、真实Adapter或生产配置尚未接入 | 在Mock/Test环境按人工测试方案验证核心闭环；生产环境等待真实源接入 |

### 5.3 文件场景数据集常见问题

| 现象 | 可能原因 | 排查/解决 |
|------|---------|----------|
| 上传被拒绝，提示缺文件/列映射/未知requirement | manifest与实际CSV不一致 | 核对每个file、表头、Capability Contract和模型Evidence Requirement |
| 只有warning，能否发布 | 可以，前提是还有可用Provider数据 | 先查看行号和原因，确认不会影响本次演示的实体和时间窗 |
| 规划报"数据集未发布或不可见" | 用Admin完成发布；确认dataset_id拼写正确且在当前租户 | 检查发布状态和dataset_id |
| 运行得到DATA_UNAVAILABLE | 核对target entity ID、带时区时间、[start,end)边界、数值列和baseline列 | 检查CSV中是否有匹配实体和时间范围的数据 |
| 运行报基础设施失败 | 检查发布后的文件是否仍在受控根目录，且内容未被人工修改 | 重新上传并发布以生成新哈希 |

---

## 六、数据文件索引（快速查找）

### 知识中心数据

| 数据类型 | 文件路径 | 用途 |
|---------|---------|------|
| 数据域定义 | `example/knowledge-center/ontology/data-domains.json` | 创建4个数据域 |
| 实体类型定义 | `example/knowledge-center/ontology/entity-types.json` | 创建14种TBox实体类型 |
| 关系类型定义 | `example/knowledge-center/ontology/relation-types.json` | 创建13种TBox关系类型 |
| 实体实例CSV | `example/knowledge-center/ontology/entities.csv` | 批量导入43个ABox实体 |
| 关系事实CSV | `example/knowledge-center/ontology/facts.csv` | 批量导入38条ABox关系 |
| 安全生产规程 | `example/knowledge-center/business-documents/01-煤矿安全生产规程.md` | 上传到安全生产知识库 |
| 综采设备维护手册 | `example/knowledge-center/business-documents/02-综采设备维护手册.md` | 上传到设备维护知识库 |
| 生产指标说明 | `example/knowledge-center/business-documents/03-煤矿生产指标说明.md` | 上传到生产运营知识库 |
| 运输系统操作规程 | `example/knowledge-center/business-documents/04-运输系统操作规程.md` | 上传到生产运营知识库 |
| 煤矿应急预案 | `example/knowledge-center/business-documents/05-煤矿应急预案.md` | 上传到安全生产知识库 |
| 文件数据集清单 | `example/knowledge-center/file-dataset/manifest.yaml` | 文件场景数据集上传 |
| 产量数据CSV | `example/knowledge-center/file-dataset/production.csv` | 3号矿产量数据（62行） |
| 设备数据CSV | `example/knowledge-center/file-dataset/equipment.csv` | 3号矿设备可用率数据（31行） |
| 运输数据CSV | `example/knowledge-center/file-dataset/haulage.csv` | 3号矿运输周期+排队时间（31行） |
| 数据集实体CSV | `example/knowledge-center/file-dataset/entities.csv` | 数据集发布时导入ABox |
| 数据集关系CSV | `example/knowledge-center/file-dataset/relations.csv` | 数据集发布时导入ABox |

### 模型中心数据

| 数据类型 | 文件路径 | 用途 |
|---------|---------|------|
| 因果模型定义 | `example/model-center/causal-models/mine3-production-drop-diagnosis.json` | ECMC新建3号矿产量下降诊断模型 |

### Catalog 数据

| 数据类型 | 文件路径 | 用途 |
|---------|---------|------|
| 指标定义 | `example/catalog/metrics.json` | 注册8个煤矿核心指标 |
| 单位定义 | `example/catalog/units.json` | 注册10种计量单位 |
| 聚合方式 | `example/catalog/aggregations.json` | 注册7种聚合方式 |
| 时间窗口 | `example/catalog/time-windows.json` | 注册5种时间窗口 |
| 绑定模板 | `example/catalog/binding-templates.json` | 注册4种实体绑定模板 |
| 能力合同 | `example/catalog/capability-contracts.json` | 注册5个取数能力合同 |
| 规则Schema | `example/catalog/rule-schemas.json` | 注册4种规则Schema |

---

## 七、验证清单（交付前自检）

### 知识中心验证

- [ ] 4个数据域全部创建成功
- [ ] 3个知识库创建成功，5份文档全部上传
- [ ] 文档生成合理数量的chunk（每份10-30个）
- [ ] 14种实体类型、13种关系类型创建成功
- [ ] entities.csv 干跑校验 42/42 通过
- [ ] facts.csv 干跑校验 35/35 通过
- [ ] 实体导入后，实体管理页面可见所有实体
- [ ] 3号矿详情页能看到所有关联关系
- [ ] 图谱探索能正常渲染3号矿的关系网络
- [ ] 召回测试8个用例都能返回相关结果
- [ ] 文件场景数据集上传校验通过
- [ ] 文件场景数据集发布成功，3个Provider可用
- [ ] 数据集中的实体导入ABox成功

### 模型中心验证

- [ ] Catalog引用注册成功（指标/单位/聚合等）
- [ ] 因果模型创建成功，Diagnostic Target正确
- [ ] 6个节点全部创建，入口节点正确
- [ ] 5条边全部创建，DAG无环无悬空
- [ ] 5个证据需求全部添加，required证据有primary contract
- [ ] 所有可执行字段从Catalog选择，无手填
- [ ] 5条规则全部添加，参数正确
- [ ] 全量校验通过，无Error
- [ ] 提交审核→驳回→修改→再提交→发布流程正常
- [ ] 发布生成Snapshot ID和hash
- [ ] 编译成功，生成Candidate Artifact
- [ ] 激活成功，Version状态变为Active
- [ ] 旧Version进入superseded状态

### 端到端验证

- [ ] 因果诊断能正常发起，传入dataset_id能取数
- [ ] 诊断结论与数据场景一致（运输+设备是主要原因）
- [ ] 诊断结果带证据溯源
- [ ] 知识检索能正确返回实体关系和文档内容
- [ ] 所有答案带引用来源，可追溯

---

> **文档结束**  
> 如有疑问，请参考 `arch/guides/` 目录下的官方用户指南：
> - `earp-fde-user-guide.md` — 知识中心FDE使用说明
> - `earp-ecmc-guide.md` — ECMC企业认知模型中心使用指南
> - `earp-file-dataset.md` — 文件场景数据集说明
> - `earp-catalog-phase1-runbook.md` — Catalog Phase 1运维手册
