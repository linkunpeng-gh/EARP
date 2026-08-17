# EARP 知识资产管理 — FDE 使用说明

- 版本: v1.0
- 日期: 2026-08-15
- 适用对象: FDE（一线部署/实施工程师）——负责为客户搭建和运营 EARP 知识资产
- 适用范围: 实体管理 / 批量导入 / 图谱探索 / 知识检索（含三层检索与引用溯源）
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

**关键认知**：
1. **实体/事实与文档是两套知识**——实体图谱回答"谁、属于谁、由谁供应"（结构化）；文档（KB）回答"标准是什么、流程怎么走"（非结构化）。检索时两者融合。
2. **先有实体+事实，才有图谱和档案**——`KB 传文档不会生成实体`；实体必须通过「实体管理/导入」录入。
3. **权限贯穿**——实体按数据域归属，你的角色看不到无权限域的实体/文档。

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

## 5. 数据准备最佳实践（FDE 标准流程）

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

## 6. 常见问题排查（FAQ）

| 现象 | 可能原因 | 排查/解决 |
|---|---|---|
| 检索搜不到刚导入的实体 | ① 实体未 active（被停用）② 检索的查询没触发该实体所在数据域的路由 ③ 实体名称与查询差异大 | ① 实体管理查状态 ② 召回测试看路由调试的候选 DD ③ 用实体名精确词 |
| 图谱没有关系 | 该实体没有活跃事实（facts 未建或已撤销） | 实体管理详情看关系数；facts.csv 补导入 |
| 实体档案（profile）显示旧事实 | profile 无写时失效（已知 tech-debt #11） | 导入/建关系后档案自动重编；如仍旧，删除 entity_profiles 行后重新检索触发重编 |
| 导入报"关系类型不存在" | relation_type_id 拼写错或不在 TBox | 打开实体导入页 TBox 一览核对 |
| chat 回答没有引用 | 检索没命中（问题在知识外）或回答没用到资料 | 用召回测试确认能命中；拒答是正常行为（知识外不编造） |
| 纯中文实体名搜不到 | 实体识别分词局限（已知，Phase B 解决） | 用完整实体名或带英文/数字的编码搜索 |

---

## 7. 附：常用验证命令（进阶，可选）

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
```

## 8. QU 调试会话上下文（指代消解，可选）

QU 调试页的「会话上下文」输入框支持多轮指代消解：上文提到的实体填进去，`它/该设备` 等指代词会映射到它：

- 输入框格式：`mention:type`，逗号分隔，如 `CNC-01:equipment`
- 示例：第一轮问 `CNC-01 的供应商是谁`，第二轮问 `它是哪家供应商生产的` 并在上下文填 `CNC-01:equipment` → 理解结果 entities 仍识别 CNC-01
