# Query Understanding 评估集（Understanding Evaluation Set）

> Phase B 验收基线（QU 设计 v0.3 §17 Understanding 层）。
> 格式：`| # | query | intent | entities | relations | time | constraints | note |`
> - intent：FACT/RELATION/AGGREGATION（可靠子集，计分）| FALLBACK（回落即正确，7 类抽样不设门槛）
> - entities：`mention:semantic_type` 分号分隔（空 = 无期望；mention 为 seed 实体名）
> - relations：relation_type_id 分号分隔（空 = 无期望；必须 ∈ TBox）
> - time：期望 expression（空 = none）；constraints：期望 JSON（空 = 无）
> - note：备注；`ctx:` 前缀 = runner 传会话上下文（指代消解场景）
> CI（test_understanding_eval.py）机制层验证（规则层，不真调 LLM）；dev 用
> `scripts/verify_understanding.py` + 真 LLM 验证升级路径。门槛：intent ≥85%
> （可靠子集）/ 实体提及召回 ≥90% / relation ≥80% / schema 合规 100%。

| # | query | intent | entities | relations | time | constraints | note |
|---|---|---|---|---|---|---|---|
| 1 | 报销制度是什么 | FACT | | | | | 文档事实 |
| 2 | 财务报销标准是什么 | FACT | | | | | 文档事实 |
| 3 | 设备维护标准有哪些 | FACT | | | | | 文档列举 |
| 4 | 2024 年财务部的报销制度是什么 | FACT | | | | {"year":2024} | 约束+文档 |
| 5 | 2023 年的报销标准 | FACT | | | | {"year":2023} | 约束 |
| 6 | 设备报警阈值配置说明 | FACT | | | | | 文档 |
| 7 | 主轴轴承的更换规范 | FACT | 主轴轴承:component | | | | 实体+文档 |
| 8 | 高温报警的处理流程是什么 | FACT | 高温报警:alarm | | | | 实体+文档 |
| 9 | 设备维护手册的目录 | FACT | | | | | 文档 |
| 10 | 设备报警阈值是多少 | FALLBACK | | | | | ATTRIBUTE 回落（属性值） |
| 11 | 安全生产规范要求 | FACT | | | | | 文档 |
| 12 | 财务报销流程说明 | FACT | | | | | 文档 |
| 13 | 设备保养周期的规定 | FACT | | | | | 文档 |
| 14 | 质量检验标准 | FACT | | | | | 文档 |
| 15 | 产品出厂检验要求 | FACT | | | | | 文档 |
| 16 | 供应商准入制度 | FACT | | | | | 文档 |
| 17 | 员工休假政策 | FACT | | | | | 文档 |
| 18 | 2024 年差旅费用标准 | FACT | | | | {"year":2024} | 约束 |
| 19 | 设备台账是什么 | FACT | | | | | 文档 |
| 20 | 报警处理的注意事项 | FACT | | | | | 文档 |
| 21 | 什么是设备点检 | FACT | | | | | 定义 |
| 22 | 设备点检制度包含什么 | FACT | | | | | 定义列举 |
| 23 | 主轴轴承的作用是什么 | FACT | 主轴轴承:component | | | | 实体+文档 |
| 24 | 华东一厂的基本情况 | FACT | 华东一厂:plant | | | | 实体+文档 |
| 25 | 高温报警的定义是什么 | FACT | 高温报警:alarm | | | | 实体+文档 |
| 26 | 设备故障的分类标准 | FACT | | | | | 文档 |
| 27 | 维修工单的处理规范 | FACT | | | | | 文档 |
| 28 | 2024 年 3 月的报销政策 | FACT | | | | {"year":2024,"month":3} | 约束 |
| 91 | 差旅报销的标准是什么 | FACT | | | | | 文档 |
| 92 | 设备台账包括什么内容 | FACT | | | | | 列举 |
| 93 | 安全生产的制度要求 | FACT | | | | | 文档 |
| 94 | 2024 年度的设备预算说明 | FACT | | | | {"year":2024} | 约束 |
| 95 | 设备润滑保养的要求 | FACT | | | | | 文档 |
| 96 | 维修工单的填写规范 | FACT | | | | | 文档 |
| 97 | 物料入库的流程是什么 | FACT | | | | | 文档 |
| 98 | 产品质检的标准 | FACT | | | | | 文档 |
| 29 | CNC-01 由哪家供应商制造 | RELATION | CNC-01:equipment | manufactured_by | | | 单跳关系 |
| 30 | CNC-01 是由谁生产的 | RELATION | CNC-01:equipment | manufactured_by | | | 单跳关系 |
| 31 | CNC-01 的制造商是谁 | RELATION | CNC-01:equipment | manufactured_by | | | 制造→manufactured_by |
| 32 | 主轴轴承由谁供应 | RELATION | 主轴轴承:component | supplied_by | | | 供应关系 |
| 33 | 主轴轴承的供应商是哪家 | RELATION | 主轴轴承:component | supplied_by | | | 供应→supplied_by |
| 34 | CNC-01 位于哪个工厂 | RELATION | CNC-01:equipment | located_in | | | 位置关系 |
| 35 | CNC-01 属于哪条产线 | RELATION | CNC-01:equipment | belongs_to | | | 归属关系 |
| 36 | 主轴轴承属于哪个设备 | RELATION | 主轴轴承:component | belongs_to | | | 归属关系 |
| 37 | 高温报警由什么引起 | RELATION | 高温报警:alarm | caused_by | | | 因果关系 |
| 38 | 高温报警是什么引起的 | RELATION | 高温报警:alarm | caused_by | | | 因果关系 |
| 39 | 张工负责哪条产线 | RELATION | 张工:employee | responsible_for | | | 负责关系 |
| 40 | A产线的负责人是谁 | RELATION | A产线:production_line | | | | 主动疑问（subject 未知） |
| 42 | CNC-01 由谁维护 | RELATION | CNC-01:equipment | maintained_by | | | 维护关系 |
| 43 | 张工负责哪些设备 | FALLBACK | 张工:employee | | | | LIST 回落（“哪些”列举语义） |
| 44 | 高温报警是由什么设备引起的 | RELATION | 高温报警:alarm | caused_by | | | 因果+设备 |
| 46 | 华东一厂生产什么产品 | RELATION | 华东一厂:plant | produces | | | 生产关系 |
| 57 | 它是哪家供应商生产的 | RELATION | CNC-01:equipment | manufactured_by | | | ctx:CNC-01:equipment |
| 58 | 主轴轴承属于哪台设备 | RELATION | 主轴轴承:component | belongs_to | | | 归属关系 |
| 60 | CNC-01 在哪个工厂 | RELATION | CNC-01:equipment | located_in | | | 位置关系 |
| 99 | 华东一厂位于哪里 | RELATION | 华东一厂:plant | | | | 位置（plant 非 located_in 源） |
| 102 | 主轴轴承属于CNC-01吗 | RELATION | 主轴轴承:component; CNC-01:equipment | belongs_to | | | 确认式关系 |
| 105 | 设备维护由谁负责 | RELATION | | | | | 主动疑问（无实体 subject） |
| 106 | 高温报警由哪个设备引起 | RELATION | 高温报警:alarm | caused_by | | | 因果+设备 |
| 63 | 华东一厂有多少台设备 | AGGREGATION | 华东一厂:plant | | | | 计数 |
| 64 | 昨天华东一厂有多少次报警 | AGGREGATION | 华东一厂:plant | | yesterday | | 计数+时间 |
| 65 | 最近三个月有多少次高温报警 | AGGREGATION | 高温报警:alarm | | recent_三_months | | 计数+时间 |
| 66 | 设备总共有多少台 | AGGREGATION | | | | | 计数 |
| 67 | CNC-01 有多少次故障 | AGGREGATION | CNC-01:equipment | | | | 计数 |
| 68 | 平均故障率是多少 | AGGREGATION | | | | | 平均 |
| 69 | 设备数量统计 | AGGREGATION | | | | | 统计 |
| 70 | 报警次数最多的是哪个设备 | AGGREGATION | | | | | 最多（聚合消歧） |
| 71 | 哪个设备故障最多 | AGGREGATION | | | | | 最多（聚合消歧） |
| 72 | 设备故障率的平均值 | AGGREGATION | | | | | 平均 |
| 73 | 今年生产了多少个产品 | AGGREGATION | | | this_year | | 计数+时间 |
| 74 | 最近一周有多少次报警 | AGGREGATION | | | recent_1_weeks | | 计数+时间 |
| 75 | 有多少台设备在维修 | AGGREGATION | | | | | 计数 |
| 76 | 故障设备的占比是多少 | AGGREGATION | | | | | 占比 |
| 77 | 华东一厂设备数量 | AGGREGATION | 华东一厂:plant | | | | 数量 |
| 78 | 平均每台设备故障几次 | AGGREGATION | | | | | 平均+次数 |
| 79 | 2024 年有多少次设备报警 | AGGREGATION | | | | {"year":2024} | 计数+约束 |
| 80 | 设备维护工单的数量 | AGGREGATION | | | | | 数量 |
| 81 | 哪个班次产量最多 | AGGREGATION | | | | | 最多（聚合消歧） |
| 82 | 统计设备总数 | AGGREGATION | | | | | 统计 |
| 83 | 最近三个月设备故障合计 | AGGREGATION | | | recent_三_months | | 合计+时间 |
| 84 | 高温报警有多少条 | AGGREGATION | 高温报警:alarm | | | | 计数 |
| 85 | 主轴轴承更换了几次 | AGGREGATION | 主轴轴承:component | | | | 次数 |
| 86 | 最近一年有多少次维护 | AGGREGATION | | | recent_1_years | | 计数+时间 |
| 87 | 设备故障最多的是哪台 | AGGREGATION | | | | | 最多 |
| 88 | 统计各部门设备数量 | AGGREGATION | | | | | 统计+数量 |
| 89 | 报警总计 | AGGREGATION | | | | | 总计 |
| 90 | 设备数量占比 | AGGREGATION | | | | | 占比 |
| 41 | 上海某精机给哪些设备供货 | FALLBACK | 上海某精机:supplier | | | | LIST 回落 |
| 47 | A产线生产哪些产品 | FALLBACK | A产线:production_line | produces | | | LIST 回落（关系仍提取） |
| 48 | CNC-01 的供应商名单 | FALLBACK | CNC-01:equipment | | | | LIST 回落 |
| 49 | 比较 CNC-01 和 CNC-02 的故障率 | FALLBACK | | | | | COMPARISON 回落 |
| 50 | 为什么主轴轴承最近故障增加 | FALLBACK | 主轴轴承:component | | | | CAUSAL 回落 |
| 51 | 近一年设备故障的趋势如何 | FALLBACK | | | | | TREND 回落 |
| 52 | 设备故障率的变化趋势 | FALLBACK | | | | | TREND 回落 |
| 53 | 设备、物料、产品的供应商列表 | FALLBACK | | | | | LIST 回落 |
| 54 | 主轴轴承的规格参数 | FALLBACK | 主轴轴承:component | | | | ATTRIBUTE 回落 |
| 55 | 华东一厂和A产线的产能对比 | FALLBACK | 华东一厂:plant; A产线:production_line | | | | COMPARISON 回落 |
| 56 | 今年设备故障与去年的对比 | FALLBACK | | | this_year | | COMPARISON 回落+时间 |
| 59 | 高温报警的触发原因是什么 | FACT | 高温报警:alarm | | | | "原因是什么"→文档事实（CAUSAL 无可靠关键词） |
| 61 | 上海某精机供应哪些物料 | FALLBACK | 上海某精机:supplier | | | | LIST 回落 |
| 62 | 张工维护哪些设备 | FALLBACK | 张工:employee | | | | LIST 回落 |
| 100 | CNC-01 的供应商是上海某精机吗 | FALLBACK | CNC-01:equipment; 上海某精机:supplier | | | | 是非问回落 |
| 101 | A产线由张工负责吗 | FALLBACK | A产线:production_line; 张工:employee | responsible_for | | | 是非问回落（关系提取） |
| 103 | 上海某精机生产哪些产品 | FALLBACK | 上海某精机:supplier | | | | LIST 回落 |
| 104 | 张工的部门 | FALLBACK | 张工:employee | | | | ATTRIBUTE 回落 |
| 107 | 主轴轴承的供应商名单 | FALLBACK | 主轴轴承:component | supplied_by | | | LIST 回落（关系仍提取） |
| 108 | 主轴轴承的温度趋势 | FALLBACK | 主轴轴承:component | | | | TREND 回落 |
| 109 | 对比CNC-01和CNC-02的供应商 | FALLBACK | CNC-01:equipment | | | | COMPARISON 回落 |
| 110 | 设备故障的因果分析 | FALLBACK | | | | | CAUSAL 回落 |
| 111 | 设备清单 | FALLBACK | | | | | LIST 回落 |
| 112 | 张工负责什么 | FALLBACK | 张工:employee | | | | 开放问回落 |
