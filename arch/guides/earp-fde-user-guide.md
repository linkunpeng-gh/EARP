# EARP 知识资产管理 — FDE 使用说明

- 版本: v1.1
- 日期: 2026-08-17
- 适用对象: FDE（一线部署/实施工程师）——负责为客户搭建和运营 EARP 知识资产
- 适用范围: 实体管理 / 批量导入 / 图谱探索 / 知识检索（含三层检索与引用溯源）/ 评估管理（跑分）
- 前置: 服务已启动（API :8000）、Ollama embedding 可达、已通过 `pages/login.html` 登录获取 token

---

## 0. 概念速览（30 秒看懂核心）

| 概念 | 一句话 | 类比 |
|---|---|---|
| **TBox**（类型层） | 实体/关系的"字典"——什么是设备、什么是供应商、什么关系合法 | 数据库的表结构 |
| **ABox**（实例层） | 实际的实体和事实——CNC-01 是设备、CNC-01 由上海某精机供应 | 表里的数据行 |
| **实体（entity）** | 一个业务对象实例（设备/供应商/工厂/员工…） | 一条主数据 |
| **事实（fact）** | 实体间的关系三元组（主语—关系→宾语） | 一条外键关联 |
| **图谱（graph）** | 从某实体出发，按事实多跳展开的关系网络 | 关系图 |
| **实体档案（profile）** | 某个实体的"事实摘要"（Compiled Truth，检索时快速命中） | 实体卡片 |
| **软路由** | 系统自动判断问题属于哪个数据域/知识库 | 查哪个书架 |
| **三层检索** | profile（实体档案）+ graph（图谱）+ chunk（文档原文）三路召回融合 | 实体卡 + 关系图 + 原文 |
| **Query Understanding**（理解层） | 先理解问题再检索——识别实体/关系/问题类型/时间/约束，产出结构化查询 | 先听懂问题再找答案 |
| **Structured Query** | 理解层输出的结构化表示（intent + entities + relations + constraints + confidence） | 问题的“结构化翻译” |
| **Knowledge Query Plan** | 按问题类型选策略（plan_fact/plan_relation/plan_aggregation）编排检索执行 | 根据问题类型选答题路线 |
| **Evidence**（证据） | 每次检索/执行的结果带来源、置信度、主/佐证角色——回答可溯源 | 答题时注明“依据” |
| **评估集（eval set）** | 一组「问题 + 期望答案」的标注用例，系统逐条跑分衡量检索/理解/规划质量 | 考卷 + 标准答案 |
| **跑分（eval run）** | 把评估集全部用例跑一遍，输出各指标通过率 + 逐条明细，对照门槛判 ✅/❌ | 交卷出分 |
| **中台对接**（M3） | 企业数据自动流入知识库：synced（拷贝主数据副本）/ virtual（指标实时直连）——见 §12 操作、§14 原理 | 自来水管 + 实时行情 |
| **Enrichment**（M3） | 夜间自动维护：档案重编 + 过期事实清理 + 时间线回填 + 热度报告——见 §13 | 夜间保洁员 |

**关键认知**：
1. **实体/事实与文档是两套知识**——实体图谱回答"谁、属于谁、由谁供应"（结构化）；文档（KB）回答"标准是什么、流程怎么走"（非结构化）。检索时两者融合。
2. **先有实体+事实，才有图谱和档案**——`KB 传文档不会生成实体`；实体必须通过「实体管理/导入」或**中台对接（§12）**录入。
3. **权限贯穿**——实体按数据域归属，你的角色看不到无权限域的实体/文档。
4. **中台对接不是强制**——没中台照常用 CSV 导入（§2）；中台来了只是多一条更自动的路。

---

## 1. 实体管理（页面：知识中心 → 实体管理）

### 1.1 查看实体列表

- 打开 `pages/entities.html`，默认展示当前租户全部活跃实体（分页，每页 20 条）
- 顶部过滤条：
  - **搜索**：按名称或业务编码（如输入 `CNC` 回车）
  - **全部类型**下拉：只看某类实体（设备/供应商/工厂…）
  - **全部数据域**下拉：只看某数据域（设备数据/财务数据…）

### 1.2 新建实体（示例：录入一台新设备）

1. 点右上角 **+ 新建实体**
2. 填写表单：
   ```
   实体类型:  设备 (equipment)          ← 下拉选择（来自 TBox）
   名称:      CNC-03
   业务编码:  CNC-03                     ← 建议唯一，facts 引用锚点
   数据域:    设备数据 (equipment_data)
   attributes: {"model":"XK-700","install_date":"2026-05-01"}   ← JSON 可选
   ```
3. 点**保存** → 列表出现 CNC-03

> 提示：`business_code` 是事实引用锚点（批量导入 facts 用它指路），同类型内建议唯一。

### 1.3 查看实体详情（档案 + 关系）

点列表中的实体名称，展开详情面板：

```
CNC-01   equipment · CNC-01 · equipment_data · extracted
📇 实体档案（profile v2）
   · 由…制造 → 上海某精机 (supplier)
   · 位于 → 华东一厂 (plant)
   · 属于 → A产线 (production_line)
🔗 关系（前向 3 · 反向 1）
   → manufactured_by → 上海某精机   [撤销]
   → located_in → 华东一厂          [撤销]
   ⇠ caused_by ← 高温报警           [撤销]
[+ 添加关系]
```

- **📇 实体档案**：该实体的活跃事实摘要（profile），检索时被快速命中
- **🔗 关系**：前向（此实体指向别人，绿色→）+ 反向（谁指向此实体，琥珀⇠）
- **[撤销]**：作废一条事实（软撤销，留痕）
- **[+ 添加关系]**：添加事实

### 1.4 添加关系（示例：CNC-03 由哪家供应商制造）

1. 详情面板点 **+ 添加关系**
2. 依次输入/选择：
   ```
   ① 输入关联实体（搜索）: 上海某精机        → 命中供应商
   ② 输入关系类型:        manufactured_by    ← 必须是 TBox 已有关系（可参考导入页 TBox 一览）
   ```
3. 确认后详情刷新，CNC-03 的关系列表出现 `→ manufactured_by → 上海某精机`

> 关系类型与实体类型的匹配由系统校验（如 `manufactured_by` 只允许 设备→供应商）；类型不匹配会被拒绝。

### 1.5 停用实体

- 列表行操作「停用」→ 确认。停用后实体不再出现在检索/列表，事实保留（可追溯）。
- 适用：错误录入、业务退役的实体。

---

## 2. 批量导入实体与事实（页面：知识中心 → 实体导入）

适用：一次导入大量主数据（设备台账、供应商表、组织架构）。

### 2.1 下载模板

页面点 **⬇ entities.csv** 和 **⬇ facts.csv**，模板含：
- 说明头注释（每列含义）
- 示例行（照抄格式改内容即可）
- Excel 直接打开（UTF-8 中文正常）

### 2.2 填写示例（设备台账 + 供应关系）

**entities.csv**（每行一个实体）：
```csv
# 列: entity_type_id, name, business_code, data_domain_id, attributes(JSON)
equipment,CNC-01,CNC-01,equipment_data,{"model":"XK-500"}
equipment,CNC-02,CNC-02,equipment_data,
plant,华东一厂,PLANT-1,equipment_data,
supplier,上海某精机,SUP-001,equipment_data,
```

**facts.csv**（每行一个关系，用 business_code 引用实体）：
```csv
# 列: source_code, relation_type_id, target_code, confidence
CNC-01,located_in,PLANT-1,1.0
CNC-01,manufactured_by,SUP-001,1.0
CNC-02,located_in,PLANT-1,1.0
```

### 2.3 干跑校验（先验证，不写库）

1. 选择两个 CSV → 点 **🔍 干跑校验**
2. 结果：统计卡（实体 4/4 通过 · 事实 3/3 通过）+ 错误表格（如有）

**常见错误示例**：
| 错误提示 | 原因 | 修正 |
|---|---|---|
| `实体类型不存在: badtype` | entity_type_id 不在 TBox | 改为 equipment/supplier 等（看 TBox 一览） |
| `数据域不存在: xxx` | data_domain_id 拼错 | 改为已有数据域 |
| `attributes 不是合法 JSON` | JSON 格式错 | 用双引号：`{"model":"XK-500"}` |
| `business_code 重复（同类型内）` | 同一类型下编码重复 | 改唯一编码 |
| `源实体类型 equipment 不在关系 caused_by 的源类型集合` | 关系方向/类型不匹配 | caused_by 是 报警→设备，改为 `高温报警,caused_by,CNC-01` |
| `confidence 不是 0-1 数字` | 置信度越界 | 用 0~1 的小数 |

### 2.4 确认导入

- 干跑全通过 → 出现「③ 确认导入」区 → 点 **✅ 确认导入**
- 导入特性：
  - **幂等**：business_code 已存在的实体按 (类型,编码) 合并更新，不会重复
  - **profile 联动**：导入后自动重编涉及实体的档案（key_facts 立即反映新事实）
- 完成后到「实体管理」页验证：实体出现、详情档案含新关系

---

## 3. 图谱探索（页面：知识中心 → 图谱探索）

适用：直观查看某实体的关系网络、排查数据关系、向客户演示。

### 3.1 基本使用

1. 输入实体名或编码（如 `CNC-01`）→ **🔍 探索**
2. 图形展示：
   - **中心圆**：CNC-01（点击邻居节点可"以它为中心"重新展开）
   - **绿色 →**：前向关系（CNC-01 指向谁：manufactured_by → 上海某精机 / located_in → 华东一厂 / belongs_to → A产线）
   - **琥珀 ⇠**：反向关系（谁指向 CNC-01：caused_by ← 高温报警）
   - 关系标签在连线上（如 `manufactured_by`）
3. 勾选/取消「含反向关系」可控制是否展示反向

### 3.2 多跳场景示例

**"华东一厂有哪些设备？"**（反向遍历）
1. 输入 `华东一厂` → 探索
2. 琥珀 ⇠ 边显示：`located_in ← CNC-01`、`located_in ← CNC-02`——即该厂的设备

**"CNC-01 的供应商是谁？"**（前向一跳）
1. 输入 `CNC-01` → 探索
2. 绿色 → 边显示：`manufactured_by → 上海某精机`

### 3.3 从实体管理进入

实体管理页每行有「图谱」链接 → 直接跳到该实体的图谱视图。

---

## 4. 知识检索（三层融合 + 软路由）

### 4.1 召回测试（页面：知识中心 → 召回测试）

- **Scope 选「全局」**：不指定 KB/数据域 → 系统自动软路由 + 三层检索
- 输入问题（如 `CNC-01 位于哪个工厂`）→ **Search**
- 结果卡三种徽标：
  - **📇 实体档案**：命中实体档案（结构化事实）
  - **🕸 图谱**：命中图谱关系（如 `图谱：located_in → 华东一厂`）
  - **📄 文档**：命中 KB 文档片段（原文证据）
- 点「🛰 路由调试」可看三层漏斗：问题 → 候选数据域/知识库 → 每层得分（哪层命中一眼可见）

**示例查询集**（验证三层是否生效）：
| 问题 | 期望命中 |
|---|---|
| CNC-01 位于哪个工厂 | 📇/🕸（图谱：located_in → 华东一厂） |
| 设备报警阈值是多少 | 📄（报警阈值 KB 文档） |
| 报销标准是什么 | 📄（财务 KB 文档） |

### 4.2 智能体问答（页面：工作台 → Chat / 应用中心）

- 问自然语言问题，回答带**引用溯源**：
  - 文档引用：「依据」卡（如《报销制度v1》）
  - **📇 实体 / 🕸 图谱**引用卡：回答涉及实体档案/图谱关系时出现
  - **📊 聚合**引用卡：回答涉及统计聚合（多少台/多少次）时出现，卡上显示聚合值
- 示例：问 `CNC-01 的供应商是谁` → 回答 + 引用卡 `🕸 图谱：manufactured_by → 上海某精机`

### 4.3 检索的完整链条（理解"为什么能答对"）

```
你的问题
  ↓ 软路由（自动判断数据域/知识库，权限过滤）
  ↓ 三层检索
     Layer 1 📇 实体档案（谁是什么）
     Layer 2 🕸 图谱多跳（谁关联谁）
     Layer 3 📄 文档原文（标准/流程）
  ↓ 融合排序 → 带引用的回答
```

### 4.4 QU 调试（页面：知识中心 → 探索验证 → QU 调试）

> 回答是「黑盒」？这个页面把系统**怎么理解你的问题、按什么策略回答**拆开给你看。
> 与「召回测试」（看检索到没有）互补：QU 调试看**理解对不对、证据怎么组织**。

#### ① 「🧠 理解」按钮 — Query Understanding 分层结果

输入问题，系统展示如何理解它：

| 字段 | 含义 | 示例（`CNC-01 由哪家供应商制造`） |
|---|---|---|
| **intent** | 问题类型（一期可靠分类） | `RELATION`（关系查询） |
| **entities** | 识别到的实体提及 + 类型 | `CNC-01 · equipment` |
| **relations** | 识别到的关系（必须来自 TBox） | `CNC-01 → manufactured_by → supplier` |
| **time / constraints** | 时间表达 / 元数据过滤 | `2024 年` → constraints.year=2024 |
| **confidence** | 规则命中覆盖率 − 歧义惩罚（≥0.7 直接出结果，<0.7 走 LLM 升级） | `0.8` |
| **rule_fields** | 每个字段命中/未命中（未命中显示原因） | intent=hit / entities=hit |
| **derive_needs** | 回答这个问题需要哪些检索通道 | relation_reasoning=true |

**徽标解读**：
- **🧠 LLM 升级**：低置信度时系统自动用 LLM 补齐未命中字段（只补缺失，不重做已命中）——通常出现在问法模糊/口语化的问题上
- **显式回落**：问题类型属于一期未可靠分类的 7 类（比较/因果/趋势等）时，不静默当作普通文档问题，标注原因供你判断

#### ② 「🗺 运行策略」按钮 — Knowledge Query Plan + 执行过程

点击后在上方结果基础上继续展示：

| 区块 | 含义 |
|---|---|
| **select_plan** | 按问题类型选的策略：`plan_fact`（文档事实）/ `plan_relation`（实体关系）/ `plan_aggregation`（统计聚合） |
| **Execution Trace** | 每一步执行（如 `RESOLVE_ENTITY → GRAPH_QUERY`）的输入/输出/耗时——回答是**可重放**的 |
| **Evidence Set** | 检索/执行到的证据，每条带：通道图标（📄文档 / 📇实体 / 🕸图谱 / 📊聚合）+ **主证据/佐证**徽标 + 置信度 + ⚠冲突标记 |

**主证据/佐证规则**（回答以什么为主）：
- `FACT`（文档事实）→ 📄 文档为主，📇/🕸 佐证
- `RELATION`（关系）→ 🕸 图谱为主，📄 佐证
- `AGGREGATION`（统计）→ 📊 聚合为主（能力执行结果）

**示例（与 4.1/4.2 同租户）**：

| 输入 | 理解结果 | 策略 | Evidence |
|---|---|---|---|
| `CNC-01 由哪家供应商制造` | RELATION + CNC-01 → manufactured_by | plan_relation | 🕸 图谱主证据（manufactured_by → 上海某精机） |
| `2024 年财务部的报销制度是什么` | FACT + constraints.year=2024 | plan_fact | 📄 文档主证据 |
| `CNC-01 有多少次故障` | AGGREGATION + COUNT | plan_aggregation | 📊 聚合主证据（count） |
| `A产线和B产线的设备故障率对比` | 比较类 → **显式回落**（不静默） | plan_fact（回落标注） | 标注原因 |

**一句话**：召回测试看“检索到没有”，QU 调试看“系统理解对不对、按什么策略组织证据”。

---

## 5. 评估管理（页面：知识中心 → 探索验证 → 评估管理）

> 目的：把「检索 / 理解 / 规划」的质量变成**可量化的分数**。系统内置三套评估集（与 CI 同口径），一键跑分看门槛是否通过、哪些用例挂了、挂在哪一步——评估从“脚本验证”变成平台能力。

### 5.1 三套内置评估集

页面顶部是集合卡片区，每张卡显示：类型徽标 / 用例数 / **最近一次跑分**（✅ 通过 或 ❌ 未达标 + 各指标率）。

| 评估集 | 用例数 | 衡量什么 | 门槛（gates） |
|---|---|---|---|
| 路由评估集（routing） | 5 | 问题能否路由到正确的数据域（DD） | DD 命中率 ≥ 90%（KB 命中为报告项） |
| 理解层评估集（understanding） | 111 | QU 是否正确识别 intent/实体/关系、不产生 schema 违规 | intent ≥ 85% / 实体召回 ≥ 90% / 关系 ≥ 80% / schema 违规 = 0 |
| Plan 层评估集（planning） | 111 | select_plan 是否按问题类型选中正确策略 | 策略命中率 ≥ 95% |

> **理解层 vs Plan 层评估怎么区分**（两者用同一批 111 条 query，表面相似）：
> - 理解层测「系统**认不认识**问题」——六维提取（intent/实体/关系/时间/约束）逐字段精确匹配；失败 = 实体没认出/关系没提取/类型判错
> - Plan 层测「系统**怎么执行**」——按问题类型选策略（plan_fact 文档检索 / plan_relation 关系查询 / plan_aggregation 聚合），只复用 intent 标注做映射判定；失败 = 选了错误路线
> - 理解层是上游（产出 StructuredQuery），Plan 层是下游（拿理解结果决定执行路线）——分开评分才能定位问题在「认错」还是「选错」
> - 例：「华东一厂有多少台设备」→ 理解层期望 intent=AGGREGATION+entities=[华东一厂:plant]+operation=COUNT；Plan 层期望 plan_aggregation（由 AGGREGATION 映射）
> - 注意：Plan 层 rules 跑分稳定 100% 是正常的——映射表是纯函数（确定性）；真正有区分度的是 **LLM 跑分**（真实理解→真实策略执行）与策略执行质量（trace 合法性/延迟/回落）
> - 类比：理解层 = 医生诊断对不对（识别）；Plan 层 = 诊断后开什么治疗方案（决策）

每张卡两个跑分按钮：
- **规则层跑分**：几秒出结果，与 CI 同口径（确定性，可复现）——日常回归用这个
- **LLM 跑分**：走真 LLM 升级路径（较慢），评估「低置信度由 LLM 补齐」后的实际效果——需要 Ollama 可达

**跑分进度**（T3）：跑分历史里 running 行显示**进度条**（已完成 N/总数，页面 2s 轮询自动刷新）——LLM 长跑分不用盲等，取消后进度冻结（不回落）。

### 5.1b 集合治理（T3：模板同步 / 门槛编辑 / 导出导入，仅 Admin）

- **同步内置模板**：内置评估集升级（题量/内容变化）后，老集合卡片出现「↻ 同步内置模板」按钮——一键重建内置用例（custom 自定义用例保留），版本更新。注意：同步会**覆盖内置题**（含之前手工改过的内置题），确认弹窗会提示。
- **门槛编辑**：`PUT /sets/{id}`（或按需的集合配置入口）可改每个指标及格线——部分覆盖自动合并默认（不会因为只改一个指标导致其他 gates 缺指标）；非法指标名/数值越界会被拒绝。改门槛后**下次跑分立即按新门槛判定**。
- **导出/导入**：集合卡「导出」下载 JSON（题面+期望+门槛，无租户/敏感字段）；「导入评估集」卡选择 JSON 文件 → 在本租户建 custom 集合（可跨租户复制标准评估）。

### 5.2 跑分过程与判定

1. 点「规则层跑分」或「LLM 跑分」→ 系统后台逐条执行，状态 ⏳ running（页面约 2 秒自动轮询刷新，running 行带进度条 N/总数）
2. 完成后集合卡 / 跑分历史自动更新 ✅/❌
3. 每个指标对照门槛判定通过/不通过，**全部通过 → 集合卡显示 ✅ 通过**；任一不达标 → ❌ 并标红对应指标（门槛可在集合治理处调整，见 5.1b）

> **跑分由独立 worker 进程执行**（与 API 同队列，T1 起）：点跑分后任务入队，由后台 worker 进程消费逐条评分。若 dev 环境没有启动 worker 进程，跑分会一直停在 ⏳ running——先确认 `python -m earp_server.entrypoints.worker` 在跑（需与 API 同 env：`EARP_OLLAMA_BASE_URL` 等）。
> **进程中断恢复**：worker 中途被杀死（或重启）后，遗留的 running 任务会在 worker 下次启动时自动标记「失败（interrupted）」——不会永久卡在 running；心跳新鲜的在跑任务不受影响（不误杀）。

**停止跑分**：跑分历史里 running 行有「停止」按钮——LLM 跑分（111 例 × 真模型升级）可能很慢，卡住或不想等可直接停止：已执行的用例结果保留，状态标记「已取消」，不再继续。

> **跑分是「诚实报告」**：租户里没有评估用例引用的数据（如期望的数据域、实体不存在）时，对应指标**如实偏低**并显示失败原因——这提示你补数据，或按客户数据加自定义用例（见 5.4）。不是系统坏了。

### 5.3 查看跑分明细（失败原因一眼可见）

点「跑分历史」某一行 → 展开明细：逐用例 ✅/❌ + 实际输出 + **失败原因**。

| 失败原因示例 | 含义 | 排查方向 |
|---|---|---|
| `DD 未命中: finance_data` | 该问题没路由到期望数据域 | 数据域描述质量（知识库页填好描述）、权限（角色无该域访问） |
| `KB 未命中: 费用报销流程手册` | 路由到域但 KB 摘要没匹配上 | KB 名称/摘要与问题用词差异大 |
| `实体未命中` | 期望实体在租户里不存在或名称不匹配 | 补建/导入实体；对齐名称 |
| `关系未命中` | 期望关系没提取出来 | TBox 关系方向与问法不匹配（如 `manufactured_by` 只允许 设备→供应商） |
| `策略不符: plan_fact ≠ plan_relation` | select_plan 选了别的策略 | 通常是理解层 intent 判错——先用 QU 调试看理解结果 |
| `schema 违规: xxx` | 输出了 TBox 之外的关系 | 联系开发（正常不应发生） |

> **Plan 层跑分的「执行结果」**：每条用例的「实际」列会显示策略函数**真实执行**的记录——Execution Trace（如 `DD_ROUTING → KB_ROUTING → VECTOR_SEARCH → FUSION_RERANK`）、evidence 通道与数量、耗时。规则层跑分也执行（用标注 intent 构造输入，验证策略执行质量）；执行失败（如 embedding 不可达）不拉低策略命中率，trace 为空并在明细标注。真实理解→执行链路看 LLM 跑分。

### 5.4 管理用例（增 / 启停 / 删 + 自定义集合）

**改内置评估集**：点集合卡进入详情 → 用例表（query / 期望 / 备注 / 停用·删除）→「新增用例」：

| 集合类型 | 新增用例要填的期望字段 |
|---|---|
| 路由 | query + 期望数据域 DD + 期望知识库（可空） |
| 理解 | query + intent（下拉）+ 实体（`mention:type;…`）+ 关系（`relation;…`，必须 ∈ TBox） |
| Plan | query + intent 标注（FACT/RELATION/AGGREGATION/…） |

**新建自定义评估集**：集合区末尾「＋ 新建自定义评估集」→ 选类型 + 命名 → 从 0 用例开始，按客户数据建用例。

**理解层「期望」字段说明**（新增用例时的下拉/输入框含义）：

| 字段 | 含义 | 合法值来源 |
|---|---|---|
| intent | 问题类型 | 10 类枚举 + FALLBACK（见下表）；下拉选项与系统校验同一来源 |
| 实体 mention:type | 期望识别的实体（`CNC-01:equipment`，分号分隔多个） | type 必须 ∈ TBox 实体类型（设备/供应商/工厂…） |
| 关系 relation;… | 期望识别的关系（分号分隔多个） | **只允许 TBox 已有 12 类**（manufactured_by/located_in/belongs_to/supplied_by/caused_by…） |

| intent 值 | 含义 | 计分规则 |
|---|---|---|
| FACT / RELATION / AGGREGATION | 文档事实 / 实体关系 / 统计聚合 | **可靠子集**：跑分必须精确命中才计通过 |
| FALLBACK | 期望系统「显式回落」而非硬分类（如比较/趋势/因果类） | 回落即正确 |
| ATTRIBUTE / LIST / MULTI_HOP / COMPARISON / TREND / CAUSAL / MIXED | 属性值 / 列举 / 多跳 / 对比 / 趋势 / 因果 / 混合 | 一期不设门槛（系统回落，不静默当普通问题） |

> intent 类型定义在 QU 设计 v0.3 §6.2（代码 `understanding.py::Intent`）；实体/关系类型来自 **TBox**（类型管理页可查，12 类冻结关系 + 13 种种子实体类型）。

> 停用用例不参与跑分；删除不可恢复（建议先停用观察再删）。

### 5.5 FDE 标准流程（评估驱动迭代）

```
① 基线：三套内置评估集跑分（规则层）→ 记录当前通过率
② 调优：按明细失败原因补数据 / 改描述 / 建关系 → 重跑看分数变化
③ 覆盖：为客户建 custom 评估集（收集客户高频问题 → 标注期望 DD/KB/实体）
④ 交付：Chat 演示前跑一遍全绿再交付；上线后定期回归
```

---

## 6. 数据准备最佳实践（FDE 标准流程）

推荐顺序（每步验证再往下）：

```
① 建数据域（DD）→ 知识中心 → 数据域
② 建知识库（KB）→ 知识中心 → 知识库（传文档，填元数据）
③ 建/导实体 → 知识中心 → 实体管理 / 实体导入
④ 建关系 → 实体管理添加 / facts.csv 导入
⑤ 验证 → 图谱探索看关系、召回测试看检索命中
⑥ 交付 → Chat 问答演示（带引用溯源）
```

**命名与规范建议**：
- `business_code`：同类型内唯一、有业务含义（设备编码/供应商代码）
- 实体名称：用客户熟悉的业务名（"CNC-01" 而非内部缩写）
- 事实 `confidence`：主数据导入 = 1.0；人工不确定的用 0.8 以下（检索时低置信度靠后）
- 关系类型：只用 TBox 已有 12 类（manufactured_by / located_in / belongs_to / supplied_by / caused_by / responsible_for…），不要发明

---

## 7. 常见问题排查（FAQ）

| 现象 | 可能原因 | 排查/解决 |
|---|---|---|
| 检索搜不到刚导入的实体 | ① 实体未 active（被停用）② 检索的查询没触发该实体所在数据域的路由 ③ 实体名称与查询差异大 | ① 实体管理查状态 ② 召回测试看路由调试的候选 DD ③ 用实体名精确词 |
| 图谱没有关系 | 该实体没有活跃事实（facts 未建或已撤销） | 实体管理详情看关系数；facts.csv 补导入 |
| 实体档案（profile）显示旧事实 | profile 无写时失效（已知 tech-debt #11） | 导入/建关系后档案自动重编；如仍旧，删除 entity_profiles 行后重新检索触发重编 |
| 导入报"关系类型不存在" | relation_type_id 拼写错或不在 TBox | 打开实体导入页 TBox 一览核对 |
| chat 回答没有引用 | 检索没命中（问题在知识外）或回答没用到资料 | 用召回测试确认能命中；拒答是正常行为（知识外不编造） |
| 纯中文实体名搜不到 | 实体识别分词局限（已知，Phase B 解决） | 用完整实体名或带英文/数字的编码搜索 |
| 评估跑分 ❌ 不达标 | ① 评估数据不在本租户（期望 DD/实体不存在）② 数据质量（描述/关系）问题 | ① 看明细失败原因——多是数据缺失，按 5.5 补数据或加 custom 用例 ② 数据域描述 / TBox 关系方向 |
| 跑分一直 ⏳ running 不动 | worker 进程未启动（跑分由独立 worker 消费，API 只入队） | 启动 `python -m earp_server.entrypoints.worker`（同 env）；worker 重启后遗留 running 自动标 failed（interrupted），不会永久卡住 |
| 规则层与 LLM 跑分结果不同 | 规则层=确定性基线（CI 同口径）；LLM=真模型升级理解层，模糊问法可能不同 | 验收/回归以规则层为基线；LLM 跑分评估升级效果 |
| 想给客户建专属评估 | 内置评估集是标准种子数据，客户数据不同 | 新建 custom 评估集：收集客户高频问题 → 标注期望 DD/KB/实体（5.4） |
| 回答/跑分不对，怀疑理解或 Plan 层 | 见下「7.1 判断理解 vs Plan 问题」 | 分层定位（先理解、后 Plan、再下游） |

### 7.1 判断理解 vs Plan 问题（分层定位）

**口诀：先理解层（输入），再 Plan 层（决策），最后下游（检索/聚合）**。Plan 层是「忠实执行者」，吃理解层的输出（StructuredQuery）——输入错了下游全错，Plan 层无责。

**Step 1 — 看理解层对不对**（QU 调试页「🧠 理解」/ `understanding/debug`）：输入同一句话看 StructuredQuery——intent 判对了吗？实体/关系提取到了吗？**输出错 → 问题在理解层**，不用再往下查。

**Step 2 — 理解对，再看策略选对没有**（QU 调试页「🗺 运行策略」/ `plan-debug`）：plan_name ≠ 期望策略 → **Plan 层映射问题**；plan_name 对但证据空/检索失败 → **策略执行/更下游**（软路由、三层检索）。

| 理解层输出 | select_plan 策略 | 问题归属 |
|---|---|---|
| ❌ 错 | （策略基于错输入） | **理解层**（源头错） |
| ✅ 对 | ❌ 错 | **Plan 层映射** |
| ✅ 对 | ✅ 对 | 策略执行 / 更下游 |

**例 1**：「CNC-01 有多少次故障」回答做了文档检索而非聚合 → 先看 intent：`AGGREGATION` 则 **Plan 层**（映射问题）；`FACT` 则 **理解层**（聚合关键词没触发）。

**例 2**：「A产线由谁负责」回答空 → entities 对但 relations 空 → **理解层**关系提取失败（主动疑问方向校验不过，Phase C 已知边界），plan_relation 选得没错但没东西可查。

**平台化定位**：理解层评估集指标低 → 理解层问题；理解层全绿但 Plan 层（LLM 跑分）失败 → Plan 层问题——两套评估集分开跑就是为了切一刀定位（§5.1）。

---

## 8. 附：常用验证命令（进阶，可选）

```bash
# token（以 verify-ontology 租户为例）
TOKEN=$(cd apps/earp-server && .venv/bin/python -c "
import jwt; print(jwt.encode({'sub':'u1','tenant_id':'verify-ontology','role_id':'verify-role','exp':9999999999},'earp-dev-secret-change-in-production',algorithm='HS256'))")

# 无 scope 三层检索（看 source=profile/graph/chunk 混合）
curl -X POST localhost:8000/knowledge/search -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 位于哪个工厂","top_k":5}'

# 实体图谱（前向/反向）
curl -s "localhost:8000/v1/ontology/entities/lookup?q=CNC-01" -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/v1/ontology/entities/<entity_id>/graph?direction=backward" -H "Authorization: Bearer $TOKEN"

# 路由调试（看 DD/KB 命中与新鲜度）
curl -X POST localhost:8000/knowledge/routing/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"设备报警"}'

# QU 理解调试（Structured Query + 字段命中 + derive_needs + LLM 升级标记）
curl -X POST localhost:8000/v1/ontology/understanding/debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 由哪家供应商制造"}'

# QU 完整链路调试（select_plan + Execution Trace + Evidence 角色层）
curl -X POST localhost:8000/v1/ontology/understanding/plan-debug -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"CNC-01 有多少次故障"}'

# 评估跑分：列表 / 触发（后台任务）/ 查结果（轮询到 completed）
curl -s localhost:8000/v1/evaluations/sets -H "Authorization: Bearer $TOKEN"
curl -s -X POST "localhost:8000/v1/evaluations/sets/evs-<tenant>-planning/runs?mode=rules" -H "Authorization: Bearer $TOKEN"
curl -s localhost:8000/v1/evaluations/runs/<run_id> -H "Authorization: Bearer $TOKEN"
```

## 9. QU 调试会话上下文（指代消解，可选）

QU 调试页的「会话上下文」输入框支持多轮指代消解：上文提到的实体填进去，`它/该设备` 等指代词会映射到它：

- 输入框格式：`mention:type`，逗号分隔，如 `CNC-01:equipment`
- 示例：第一轮问 `CNC-01 的供应商是谁`，第二轮问 `它是哪家供应商生产的` 并在上下文填 `CNC-01:equipment` → 理解结果 entities 仍识别 CNC-01

---

## 10. 附：理解层（Query Understanding）实现原理（技术参考）

> 给 FDE 的「为什么系统这样理解问题」参考。核心代码：`earp_server/ontology/understanding.py`。
> 使用入口见 §4.4 QU 调试页（把原理可视化）；验收门槛见 §5 评估管理的理解层评估集。

### 10.1 一句话原理

**双引擎**：规则层（快、确定性、与 CI 同口径）优先，低置信度时 LLM 升级补齐。把一句自然语言拆成**六维结构化表示**（Structured Query，QU v0.3 §6.2 冻结 schema），交给 Plan 层编排检索。

### 10.2 六维拆解

| 维度 | 提取什么 | 例：「2024 年华东一厂有多少台设备」 |
|---|---|---|
| intent | 问题类型（10 类枚举） | AGGREGATION（聚合） |
| entities | 实体提及 + 类型 | 华东一厂:plant |
| relations | 关系（必须来自 TBox） | 无 |
| time | 相对时间表达 | 无 |
| constraints | 元数据过滤维度 | {"year": 2024} |
| operation | 聚合操作 | COUNT |

### 10.3 规则层各维机制

**① intent — 关键词表 + 消歧顺序**
- 每个类型一张关键词表（FACT：「是什么/定义/制度/流程…」；RELATION：「谁/哪家/由谁/属于…」；AGGREGATION：「有多少/数量/统计/最多/平均…」）
- 多类同时命中 → 固定消歧顺序：**AGGREGATION > RELATION > FACT**（「哪个设备故障最多」聚合语义强于疑问词）
- 10 类只有 3 类可靠（FACT/RELATION/AGGREGATION）；其余 7 类关键词表不设，命中不了**显式回落**（§4.4「显式回落」徽标）

**② entities — 双向子串匹配 + 指代消解**
- 双向子串：实体名包含查询词（name ILIKE %查询%）+ 查询包含实体名（查询 LIKE %name%）——「主变压器是哪个公司生产的」能命中实体「主变压器」
- 指代消解：query 含「它/该设备」且无实体命中 → 用上文上下文实体顶上（§9 会话上下文）
- 产出 mention + semantic_type，不解析具体 entity_id（Plan 层职责）

**③ relations — 动词词典 + TBox 候选 + 方向校验**
- 动词表：「制造→manufactured_by」「供应→supplied_by」「属于→belongs_to」…
- 候选关系**动态从 TBox 拉取**（查 relation_types 表，不硬编码）——所以类型管理页改 TBox 会影响关系识别
- 只做「实体作主语」的被动提取，且校验主语类型 ∈ 关系源类型（manufactured_by 只允许 设备→供应商；方向错直接跳过，不强行提取）

**④ time / constraints — 正则**：「昨天/最近三个月」→ time；「2024 年」→ constraints.year（绝对年份走元数据过滤维度，分开建模）

**⑤ operation — 聚合词**：「有多少→COUNT / 平均→AVG / 最多→MAX」…（裸「多少」不算，要「有多少/多少台」复合量词，避免「更换周期是多少」误判为聚合）

### 10.4 置信度（机械计算，可解释）

```
① relevant_fields：判定哪些维度与问题相关（未涉及的维度不拉低分）
   例：「2024 年华东一厂有多少台设备」→ 相关 = {intent, entities, constraints, operation}
② rule_coverage = 命中相关维度数 / 相关维度总数
③ 歧义惩罚：intent 多候选扣 0.2
④ confidence = coverage − 惩罚（0~1）
```

≥ 阈值（0.7）→ 直接产出（零 LLM）；< 0.7 → 触发 LLM 升级。QU 调试页展示 confidence 与各字段命中明细。

### 10.5 LLM 升级（低置信度时）

- **只补未命中字段**（省 token，不重做已命中）
- prompt 给出 TBox 关系候选集，**禁止发明关系**（intent ∈ 10 类枚举、relation ∈ TBox 是硬校验）
- LLM 不可达/输出非法 → 保持规则结果（schema 合规率 100% 不破）

### 10.6 完整链路（例子）

```
「2024 年华东一厂有多少台设备」
  ↓ understand() 六维提取
  intent=AGGREGATION · entities=[华东一厂:plant] · operation=COUNT · constraints={year:2024}
  confidence = 4/4 − 0 = 1.0 → 不需 LLM
  ↓ StructuredQuery → select_plan → plan_aggregation（聚合策略）
  ↓ resolve_with_entities → 聚合执行器 → 带证据的回答
```

### 10.7 验收门槛（为什么评估集这样判定）

理解层正确性由评估集量化（QU v0.3 §17）：**intent ≥ 85% / 实体召回 ≥ 90% / 关系 ≥ 80% / schema 违规 = 0**。规则层是 CI 同口径（确定性可复现）；LLM 跑分评估低置信度升级路径的实际效果。

---

## 11. 附：Plan 层（Knowledge Query Plan）实现原理（技术参考）

> 给 FDE 的「系统按什么路线回答」参考。核心代码：`earp_server/ontology/planning.py`。
> 使用入口见 §4.4 QU 调试「运行策略」（select_plan + Execution Trace + Evidence）；验收见 §5 评估管理的 Plan 层评估集。

### 11.1 一句话原理

理解层产出 StructuredQuery 后，**select_plan 按问题类型从 3 种固定策略中选一条执行路线**（一期固定策略，非 LLM 自由规划；Phase F 才评估通用 DAG）。映射是**纯函数、确定性**——同样的 intent 永远选同样的策略。

### 11.2 三种策略

| 策略 | 干什么 | 执行链路 |
|---|---|---|
| plan_fact | 文档事实检索 | 软路由 → 三层检索（profile/graph/chunk RRF）→ 证据 |
| plan_relation | 实体关系查询 | 实体解析 → 图遍历（graph_query）→ 无事实则文档补证 |
| plan_aggregation | 统计聚合 | 实体解析 → 聚合执行器（COUNT/group_by 等） |

### 11.3 10 类 intent → 策略映射表（§11.2）

| intent | 策略 | 备注 |
|---|---|---|
| FACT | plan_fact | 文档事实 |
| RELATION / ATTRIBUTE / LIST | plan_relation | 解析失败回落 plan_fact |
| MULTI_HOP | plan_relation | 多跳：max_hops=2 |
| AGGREGATION / COMPARISON / TREND | plan_aggregation | 无 capability → plan_fact |
| CAUSAL / MIXED | plan_fact | **显式回落**（标注原因，不硬做因果分析） |
| （兜底） | plan_fact | 理论不可达（intent 必填枚举），防未定义落点 |

### 11.4 两级回落（策略层也不空手而归）

- **策略选择级**：CAUSAL/MIXED 不硬做 → 显式回落 plan_fact（QU 调试可见 fallback_reason）
- **策略执行级**：plan_relation 解析不到实体 → plan_fact；plan_aggregation 无 capability 候选 → plan_fact

### 11.5 与评估的关系

Plan 层评估集「策略命中率 ≥ 95%」测的就是：**标注 intent → 映射表 → 选中的策略 == 期望策略**（如 AGGREGATION 期望 plan_aggregation，FALLBACK 回落即正确）。rules 跑分稳定 100% 属正常（纯函数）；LLM 跑分才有区分度（真实理解 → 真实策略执行）与策略执行质量（trace 合法性/延迟/回落）。

## 12. 中台数据对接（connector + 数据源同步，M3）

> 中台通道（PRD-2026-030 M3）：让企业数据自动流入知识库，替代手工 CSV。
> 两种模式：**synced**（定期拷贝主数据副本）/ **virtual**（指标实时直连，不存数据）。
> 操作页面：知识中心 → **中台对接**（连接管理 / 数据源注册 / 触发同步 / virtual 实时取数测试）；
> 对接约定见《中台对接数据契约规范》（`arch/guides/earp-data-contract.md`）。

### 12.0 先理解：数据存哪、主数据是什么

**两种模式的数据归宿（最关键的一个区别）：**

| 模式 | 数据保存在哪 | 类比 |
|:---|:---|:---|
| **synced（同步）** | ✅ **存 EARP 本地**（PostgreSQL 副本）——中台数据拷一份进来 | 手机通讯录"同步云端联系人" |
| **virtual（直连）** | ❌ **不存数据**——本地只存"怎么取数"的配置，每次查询实时去中台要 | App"实时查股票行情" |

**主数据是什么（synced 主要服务的目标）：**

主数据 = 企业核心业务对象的"权威档案"——被多个系统共享、相对稳定、不常变的基础数据，对应 EARP 里大部分 `object` 类型实体：

| 主数据 | 例子 |
|:---|:---|
| 设备 | CNC-01、型号 XK-500、所属产线 |
| 供应商 | SUP-001「上海某精机」 |
| 组织架构 | 华东一厂、A 产线、张工 |
| 物料/客户 | 轴承、CNC-01 的客户 |

**主数据 vs 流水数据**：报警记录、工单、设备实时状态这类高频发生的是"流水/事件"，不是主数据——主数据是"事实的锚点"（"CNC-01 由 SUP-001 制造"引用的就是主数据），所以必须稳定存本地随时可查。

**"存副本"意味着什么（中台挂了还能用吗？）——能，但有边界：**

| 情形 | 结果 |
|:---|:---|
| 中台宕机/断网 | ✅ 本地副本照常可用——检索、问答、图谱都不依赖中台在线 |
| 副本是"快照" | ⚠️ 是**上次同步时刻**的数据（页面 `last_synced_at` 可查），不是实时 |
| 前提 | ⚠️ 至少成功同步过一次才有副本；从没同步过的数据源没有本地数据 |
| 中台恢复后 | 🔄 再点同步刷新副本（幂等合并，不重复） |
| virtual 中台挂了 | ❌ 取数返回 503（不假造值）——它本来就不存数据 |

> **一句话**：主数据（设备/供应商/组织/物料）走 synced 存本地副本——中台挂了本地照常用（旧版本）；指标/状态走 virtual 实时取——中台挂了就没有（但本来也不该缓存）。检索/问答永远走本地，中台只是"定期往 EARP 灌新数据"的角色。

### 12.1 三步接入（以中台设备台账为例）

> 以下 API 均可通过「中台对接」页面完成（表单填写即等价请求体）；此处给 API 形状便于对照/脚本化。

1. **注册连接**（Admin，写端点需 admin 权限）：

   ```
   POST /v1/ontology/connectors
   { "connector_id": "cn-mid-rest", "adapter_type": "rest",
     "config": { "base_url": "http://中台地址", "path": "/equip" } }
   ```

   配置加密存储（列表/详情只回 `credential_masked` 标记，不泄露凭据/URL）。

2. **注册数据源**（选实体类型 + 字段映射）：

   ```
   POST /v1/ontology/import/connector
   { "connector_id": "cn-mid-rest", "entity_type_id": "equipment",
     "source_mode": "synced",
     "field_mapping": {
       "name_field": "equip_name", "business_code_field": "equip_code",
       "attr_fields": { "model": "model" },
       "relations": [ { "relation_type": "manufactured_by", "target_field": "supplier_code" } ] } }
   ```

   - `business_code_field`/`name_field` 必填（幂等同步锚点 + 显示名）
   - 关系字段的值 = **目标实体业务编码**（供应商表/已存在实体自动关联，不存在自动创建）
   - `source_mode=virtual` 仅支持 `kind=metric` 的实体类型（object 实时事实二期）

3. **触发同步**：注册后自动入队（worker 进程消费）；或随时 `POST /v1/ontology/data-sources/{id}/sync`。
   同步按 business_code 幂等合并（二次同步不重复行/不重复事实）；running 中重复触发 → 409。

### 12.2 查看数据源状态

```
GET /v1/ontology/data-sources            # 列表（含 last_synced_at / last_sync_status）
GET /v1/ontology/data-sources/{id}       # 详情
```

`last_sync_status`：queued → running → completed / failed / interrupted（进程中断后下次触发自动恢复标记）。

### 12.3 virtual 指标实时取数（不存数据）

- 注册 `kind=metric` 实体类型 → 注册 virtual 数据源（`source_mode=virtual`）→ 用实体管理建 metric 实体（`source_mode=virtual` + `source_ref=connector_id`）：
  ```
  GET /v1/ontology/entities/{entity_id}/live
  → { "entity_id": "...", "business_code": "CNC-01", "data": { "oee": 0.87, ... }, "fetched_at": "..." }
  ```
- 取数实时经 connector 调用中台 API（查询参数 `business_code`）；失败返回 503（不假造值）。
- 中台侧最小契约：GET 端点 + 按业务编码查询 + JSON 响应（裸数组或 `{data:[...]}`）+ 响应 ≤30s。

## 13. Enrichment 夜间任务（自动维护，M3）

知识库的"夜间保洁"——scheduler 进程每 `EARP_ENRICHMENT_INTERVAL_SECONDS`（默认 3600s）自动执行，也可手动：

```
POST /v1/ontology/enrichment/run     # 手动触发（Admin），返回分项统计
```

| 步骤 | 干什么 | 用户可见效果 |
|:---|:---|:---|
| ④ | 档案（Compiled Truth）批量重编 | 实体详情/检索的 profile 保持新鲜 |
| ③ | 失效事实清理（valid_to 过期 → revoked） | AI 检索不再引用过期信息 |
| ① | 时间线回填（从执行记录提取实体引用） | 实体「最近动态」自动补全 |
| ② | 热度报告（top-N 实体引用频次，不落库） | 提示下一步优先补充哪些知识 |

> 排障：`/enrichment/run` 手动触发即可验证；scheduler 未启动时夜间任务不跑（起 scheduler 进程）。

## 14. 附：中台对接实现原理（技术参考）

> 给 FDE 深度理解"为什么能对接、怎么对接、出问题看哪里"——对应 §12 操作篇的原理篇。
> 对接契约细节见《中台对接数据契约规范》（`arch/guides/earp-data-contract.md`，给中台团队）。

### 14.1 一句话原理

**EARP 的实体知识库（ABox）是"统一访问层"，但不统一存储**——中台的数据可以放在中台（EARP 实时去取），也可以拷一份放 EARP（定期同步），EARP 对上层（检索/AI 回答）统一提供实体视图。**格式不强制**：中台保持自己的表/API 格式，EARP 注册时用字段映射"翻译"成自己的实体模型。

### 14.2 三种来源模式（为什么这么设计）

| 模式 | EARP 是否存数据 | 原理 | 典型场景 |
|:---|:---|:---|:---|
| **virtual（直连）** | 不存，只存元数据 | 查询时经 connector 实时向中台 API 取数（`GET /entities/{id}/live`） | 指标/状态（OEE、温度）——随时变，拷了也过期 |
| **synced（同步）** | 存副本 | 定时/手动触发，全量拉取 + 按业务编码幂等合并 | 主数据（设备台账、供应商、组织）——不常变，拷一份放心 |
| **extracted（抽取）** | 物理存储 | 文件/报表 → LLM 抽取 + 人工审核（已有 CSV/导入路径） | 文档知识、无中台兜底 |

> 通俗版理解（数据存哪/主数据是什么/中台挂了能否用）见 §12.0。

**选择口诀**：主数据用 synced、状态/指标用 virtual、源系统没稳定 API 用同步、没中台用 CSV（extracted）。

### 14.3 同步的数据流（synced 全链路时序）

```
中台表/API ──(adapter 取数)──▶ 行数据
                                 │ field_mapping 翻译
                                 ▼
    upsert_entity（按 business_code 幂等合并：有则更新、无则新建）
                                 │ relations 映射
                                 ▼
    add_fact（关系三元组：源实体 —关系→ 目标实体，confidence=1.0）
                                 │
                                 ▼
    profile 联动重编（档案刷新） + runtime.knowledge.synced 事件（审计）
```

- **取数适配器**：REST（httpx 直连中台 API，支持 Basic/Bearer 认证、超时 30s）
  或 DB（SQLAlchemy 直连外部库，表/列名白名单防注入，值全部绑定参数）
- **worker 进程消费**：同步是队列任务（API 只负责入队，worker 负责执行）——API 重启不丢任务

### 14.4 字段映射与关系映射原理

注册数据源时填 `field_mapping`（存在 `import_rules` 表，可复用）：

```json
{
  "name_field": "equip_name",            // 名称 ← 中台列（必填）
  "business_code_field": "equip_code",   // 业务编码 ← 中台列（必填，幂等锚点）
  "attr_fields": { "model": "model" },   // 属性 ← 中台列（对照实体类型 attributes）
  "relations": [ { "relation_type": "manufactured_by", "target_field": "supplier_code" } ]
}
```

**关键概念——business_code（业务编码）**：
- 中台行的唯一标识（如设备编码 CNC-01）→ EARP 幂等合并的"锚点"：同一编码二次同步 = 更新而非重复插行
- **关系字段的值 = 目标实体的业务编码**（不是名称）：同步时用该编码反查目标实体；
  不存在则**自动创建**（名称=编码），存在则直接关联——所以"供应商表"不用提前导入，
  设备台账里的 `supplier_code` 会自动带出供应商实体

### 14.5 幂等与增量

| 机制 | 原理 |
|:---|:---|
| 实体幂等 | upsert 按 (tenant, entity_type, business_code) 合并——二次同步 created=0 / merged=N |
| 事实去重 | 同 (源, 关系, 目标) 的活跃事实已存在则跳过——二次同步不重复建关系 |
| 增量同步 | connector 配置 `since_field` 后，取数带 `since=上次同步时间`（REST 透传参数 / DB WHERE 绑定）——只拉新增/变更行；不配则每次全量 |

### 14.6 可靠性设计

| 环节 | 机制 |
|:---|:---|
| 取数失败 | 超时/HTTP 错误/连接失败 → 整个同步标 failed，**不半途写库**（不产生半截数据） |
| 单行错误 | 某行字段缺失/关系非法 → 该行跳过 + 记入 errors 列表，**不中断整批** |
| 卡死恢复 | 同步中进程被杀 → 状态停留 running；下次触发时心跳超时（默认 30 分钟）→ 自动标 interrupted 再重新开始 |
| 并发保护 | 同步进行中（心跳新鲜）再触发 → 409 拒绝，防止重复消费 |
| 实时取数失败 | virtual live → 503 + 日志，**不假造值**（宁可报错也不编数据） |

### 14.7 权限与安全

| 项 | 机制 |
|:---|:---|
| 连接配置 | connector 配置 AES-256-GCM 加密落库（config_payload），列表/详情只回 `credential_masked` 标记——**凭据/URL 不泄露** |
| 管理门禁 | connector 注册/数据源注册/触发同步/手动 enrichment 均为 **Admin 角色**（403 封堵） |
| 租户隔离 | 全部表 RLS FORCE（跨租户不可见），同步任务逐租户执行 |
| virtual 权限 | 取数在外部系统（不经 EARP RLS）——结果按实体所属数据域的 classification 继承声明（管理员需知晓此边界） |
| 防注入 | DB 取数表/列名白名单校验（仅字母数字下划线），值全部绑定参数 |

### 14.8 排障速查表

| 现象 | 可能原因 | 排查 |
|:---|:---|:---|
| 同步一直 queued/running | **worker 进程未启动**（最常见） | 起 worker（`make worker`）；`GET /data-sources` 看状态 |
| 同步 failed | 取数失败（中台不可达/超时/HTTP 错） | 看 API 日志的 ConnectorFetchError；先测中台接口通不通 |
| 同步 interrupted | 上次进程被杀，心跳超时自动标记 | 属正常恢复——重新触发即可 |
| 触发同步 409 | 同步进行中（心跳新鲜） | 等它完成再触发；超过 30 分钟仍 409 检查心跳 |
| live 返回 503 | connector 配置不可用 / 中台超时 / 响应格式不支持 | 检查 connector 配置、中台响应是否裸数组或 `{data:[...]}` |
| live 返回 400「仅 metric」 | 实体类型不是 metric，或实体不是 virtual | virtual 只支持 metric 类型（object 实时事实二期） |
| 重复触发同步 409「已存在」 | 同 (connector, entity_type, source_mode) 已注册 | 用 `GET /data-sources` 找已有数据源复用 |
| 删除 connector 409「被引用」 | 有数据源在用该连接 | 先删数据源或停用 connector |

### 14.9 边界与二期

- **object 类型 virtual（设备实时事实进图谱）**：二期——一期 virtual 仅 metric 实时取数（消费语义已明确）
- **facts 生命周期**（关系变化自动 supersede/revoke）：二期——一期同步只建新事实、不更新旧关系
- **DB adapter 真实数仓对接**：代码就绪，需真实环境验证（dev 冒烟用 REST stub）
- **无中台场景**：CSV 兜底路径（§2 批量导入）保持可用，与中台对接并存

## 15. Chatflow flow 模式节点（F3：QU / Capability / Tool）

> 📘 **面向 FDE 的操作教程（从哪进 / 节点怎么写 / 怎么调试 / 场景示例 / FAQ）**
> 见 `earp-chatflow-guide.md`。本节是技术参考（节点 JSON 形状 / 权限审计边界 / 实现原理）。

> flow 模式（`orchestration=flow`）：开发者把「做事」画成 DAG（start → 节点 → end），
> 对话时逐节点执行。F2 已有 LLM/Knowledge/Chat History/Condition 节点；F3 增加三个
> **能做事**的节点：QU（自动理解子问题）、Capability（真实能力执行 + 权限/审计）、
> Tool（经中台连接体系取数）。节点用 JSON 声明（F5a 前端画布前的过渡形态）。

### 15.1 节点 JSON 形状（flow_schema）

```jsonc
// QU 节点：理解 → 选策略 → 执行（输出 selection/evidence/citations/chunks）
{ "id": "q1", "type": "qu", "data": { "query": "{{query}}", "context_turns": 2 } }

// Capability 节点：注册表校验 + 权限门禁 + 审计（capability_id 必填）
// 两种形状兼容——step 别名（capability_call）或新形状（input）
{ "id": "c1", "type": "capability",
  "data": { "capability_call": { "capability_id": "cap-demo-echo", "input": { "msg": "hi" } } } }

// Tool 节点：复用 M3 中台连接（connector_id 必填，params 支持模板）
{ "id": "t1", "type": "tool",
  "data": { "connector_id": "cn-xxx", "params": { "region": "{{query}}" } } }

// Human Approval 节点（F4）：执行到此处挂起，等人在会话里答复后继续
{ "id": "h1", "type": "human_approval",
  "data": { "question": "确认给 CNC-01 派维修单？" } }
```

### 15.2 三个节点做了什么

| 节点 | 执行链路 | 输出 | 备注 |
|:---|:---|:---|:---|
| **QU** | understand（规则层，可 LLM 升级）→ select_plan → execute_plan（plan_fact/relation/aggregation） | `{selection, evidence, citations, chunks}` | 输出 citations 供下游 `{{#q1.output.citations#}}`（或简写 `{{#q1.citations#}}`）引用——flow 里放 QU = 自动理解子问题 |
| **Capability** | business_capabilities 注册表校验（存在 + active）→ required_permissions 门禁 → 执行 | 适配器结果（如 demo.echo → `{"echo": {...}}`） | 无权限：PolicyLayer 403（角色缺 required_permissions）；审计事件 `earp.capability.call.*` 落 audit_logs；capability_id 需在注册表声明 |
| **Tool** | decrypt_config（AES 解密）→ data_adapter.fetch（REST/DB） | `{rows, count, domain_filtered: false}` | 取数在外部系统（不经 EARP RLS）——raw rows 一期标注 `domain_filtered: false`，需上层/后续做角色域过滤（M3 review 教训 B） |
| **Human Approval**（F4） | 执行到挂起点 → 抛挂起信号 → flow_runs 持久化 → 202 等人工答复 | 挂起 202 `{status: waiting_human, pending_node_id, question}`；恢复后答复经 `{{#h1.output.reply#}}` 供下游 | 用户下一句消息即答复（复用对话）；等待超时（默认 3600s）→ timeout 终态 |

### 15.3 权限与审计边界（FDE 需知）

- **Capability 权限**：与 orchestrator invoke 同构——角色 permissions 必须包含
  business_capabilities.required_permissions 全部项，否则 403（flow 端点透传，非 500）。
- **Capability 审计**：capability 节点执行发 `earp.capability.call.started/completed/failed`
  事件（entity_type=capability），audit worker / 进程内 handler 落 audit_logs——查询审计可按
  `event_type LIKE 'earp.capability.call%'` 过滤。
- **Tool 数据域边界**：tool 取数是「admin 配置的连接、按租户隔离」，但**结果行不自动按
  角色 data_scope 过滤**——涉及实体数据时请让上层 knowledge/QU 节点做域过滤，或接受一期
  `domain_filtered: false` 标注。
- **human_approval 节点**（F4）：执行到挂起点 → **202 等待确认**（不失败不阻塞）→ 用户在**同一会话**发下一句消息即答复 → 流程自动继续；答复可用 `{{#节点id.output.reply#}}` 引用。多个人工确认节点按顺序逐个等待。等待超时（默认 1 小时，`EARP_APPROVAL_TTL`）→ 流程终态 timeout + 消息「⏰ 等待超时」；恢复时的超时惰性检查 + scheduler 定期扫描双保险。
- **mcp 节点**：F4 仍编译报「未实现（后续）」——flow 图请勿放置。

### 15.4 变量引用（节点间传值）

- `{{query}}` → 当前用户问题（图输入）
- `{{#node_id.output.path#}}` → 前序节点输出（如 `{{#q1.output.citations#}}`）；F3 起支持
  简写 `{{#node_id.path#}}`（省略 `.output.` 段）
- 缺失引用原样保留（不静默吞掉）——适配器/LLM 端兜底

### 15.5 编排 Chatflow 应用（F5b，画布编辑器 + 独立标签）

> **Chatflow 是独立于 Chat 的应用类型**：管理端「工作台」左抽屉 **chatflow**（与 chat 并列），
> 进流程应用列表 → 新建/点击进入 **Dify 式三栏画布编辑器**（左节点面板 / 中画布 / 右属性）。
> chat 列表只显示聊天助手；flow 全在 chatflow 页（互不混杂）。

**操作三步**：
1. **拖节点 / 连边**：从左边拖 10 种节点到画布（或双击快速添加），连线「右圆点 → 左圆点」；
   条件节点 2 个输出 = ✓是 / ✗否
2. **配参数**：点选中节点 → 右侧属性面板改字段（能力 ID / 连接 ID / 提示词 / 确认问题…）
3. **保存 / 运行**：保存时图校验（缺开始/结束、有环、condition 分支不全会提示）；
   「▶ 运行」输入问题 → 弹结果 + 每个节点输出；人工确认处输答复继续

**调试**：运行结果弹层逐节点输出；遇 human_approval 弹「⏸ 等待确认」→ 输答复提交 → 流程继续。
