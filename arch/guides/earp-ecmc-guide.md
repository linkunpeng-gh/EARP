# EARP 企业认知模型中心（ECMC）— FDE 使用指南

- 版本：v1.1
- 日期：2026-09-01
- 适用对象：FDE（一线部署/实施工程师）、交付测试、客户侧模型管理员
- 当前范围：因果模型管理、版本治理、校验、审核发布、编译、显式激活、目录扩展申请
- 不在当前范围：决策模型、任务模型、诊断结果 UI、真实 Provider/凭据/endpoint 配置
- 前置条件：EARP Admin 与 API 已启动，用户已登录，并已获得相应租户、数据域和 ECMC 权限

---

## 0. 30 秒理解 ECMC

ECMC（Enterprise Cognitive Model Center，企业认知模型中心）用于把业务人员掌握的“为什么会发生”转化为可版本化、可审核、可编译、可安全投产的因果模型。

它与知识中心的区别是：

| 模块 | 主要回答 | 管理内容 |
|---|---|---|
| 知识中心 | “企业知道什么？” | 文档、实体、关系、Ontology、静态语义资产 |
| ECMC | “系统如何解释、决策和执行？” | 因果模型，以及后续的决策模型、任务模型 |
| 能力中心 | “系统能调用什么？” | Capability Contract、连接器和执行能力 |
| 运行监控 | “一次运行发生了什么？” | Session、Trace、运行异常 |

当前 ECMC 只开放**因果模型**。决策模型和任务模型仅显示“规划中”，不能用因果模型 API 代替。

### 0.1 最重要的四个对象

| 对象 | 一句话解释 | 是否影响生产诊断 |
|---|---|---|
| Draft Version | 正在编辑的模型版本 | 否 |
| Snapshot | 审核发布后冻结的不可变业务语义 | 否 |
| Candidate Artifact | 从指定 Snapshot 编译出的候选 Blueprint | 否 |
| Active Version | 已显式激活、允许新诊断使用的版本 | 是 |

请记住：

```text
发布 ≠ 编译 ≠ 激活

发布：冻结业务语义，生成 Snapshot
编译：把 Snapshot 转成 Candidate Artifact
激活：物化指定 Artifact，并切换 active pointer
```

发布成功不会自动上线，编译成功也不会自动上线。只有“激活成功”才会改变新诊断使用的模型。

### 0.2 Last-known-good

新版本正在审核、编译中或编译失败时，旧的 Active Version 继续服务。这称为 **last-known-good**。

ECMC 不会因为新候选失败而自动清除旧模型，也不会自动选择另一个编译结果。FDE 不需要在候选失败时紧急回滚旧版本，因为旧版本本来就没有被替换。

### 0.3 用“写方案—打印—审批上线”理解整个过程

如果这些名词第一次看比较抽象，可以用下面的类比：

| ECMC 概念 | 通俗类比 |
|---|---|
| Draft Version | 正在修改的 Word 文档 |
| 提交审核 | 把文档发给负责人审阅，暂时锁定 |
| Snapshot | 审批通过后盖章存档的 PDF，不能再改 |
| Compile Attempt | 把盖章方案转换成系统能执行的配置 |
| Candidate Artifact | 转换成功、但还没上线的安装包 |
| Activation | 明确选择一个安装包上线 |
| Active Version | 当前生产环境正在使用的版本 |

所以，一个常见误解是：“已经发布，为什么诊断还在用旧模型？”

答案是：**发布只是盖章存档，还没有上线。还需要编译成功，并显式激活。**

### 0.4 本指南的贯穿案例

后文统一使用下面这个案例，方便把各步骤连起来理解。

某矿山发现 **3 号矿每天的产量下降**。业务专家认为可能有三类原因：

1. 运输周期变长；
2. 装载设备可用率下降；
3. 排队时间增加。

FDE 要把这套经验录入 ECMC，形成“3 号矿产量下降诊断”模型。

用一句话表示这张因果图：

```text
运输周期变长 ─┐
设备可用率下降 ├─→ 产量下降
排队时间增加 ─┘
```

其中：

- “产量下降”是入口/结果节点；
- 另外三个是原因节点；
- 每条箭头是一条因果边；
- 指标数据是 Evidence；
- 整张图审核发布后成为 Snapshot；
- 编译成功后成为 Candidate Artifact；
- 激活后，新诊断才开始使用它。

---

## 1. 页面入口与导航

登录 EARP Admin 后，点击顶部一级导航 **认知模型**，进入 ECMC。

左侧导航如下：

```text
认知模型
├─ 概览
├─ 模型资产
│  ├─ 全部模型
│  ├─ 因果模型
│  ├─ 决策模型（规划中）
│  └─ 任务模型（规划中）
├─ 审核发布
│  ├─ 待审核
│  ├─ 发布记录
│  └─ 驳回记录
├─ 编译与激活
│  ├─ 最新编译状态
│  ├─ Candidate Artifacts
│  └─ Active Versions
├─ 模型依赖（规划中）
└─ 目录扩展申请
```

常用页面路由：

| 页面 | 路由 |
|---|---|
| ECMC 概览 | `pages/ecmc.html` |
| 模型资产 | `pages/ecmc-models.html?type=causal` |
| 因果模型编辑器 | `pages/ecmc-causal-edit.html?model_id=...&version_id=...` |
| 审核发布 | `pages/ecmc-reviews.html` |
| 编译与激活 | `pages/ecmc-compiles.html` |
| 目录扩展申请 | `pages/ecmc-catalog-requests.html` |

> 当前“待审核”展示用户可见的全部 `in_review` 版本。N01A 尚未提供审核任务分配接口，因此它不是严格意义上的“只分配给我”。“驳回记录”也依赖后续审核历史查询接口，页面不会伪造记录。

---

## 2. 权限准备

ECMC 不内置固定“建模者”“审核者”角色，而是使用既有 RBAC 权限。客户可以把权限组合到自己的角色中。

| 权限 | 用途 |
|---|---|
| `ecmc.causal_model.read` | 查看模型和版本 |
| `ecmc.causal_model.write_draft` | 创建、复制、编辑、校验、提交审核 |
| `ecmc.causal_model.review` | 驳回、治理发布、归档 |
| `ecmc.causal_model.compile` | 发起或重试编译 |
| `ecmc.causal_model.activate` | 激活指定 Candidate Artifact |
| `ecmc.catalog.read` | 浏览受控目录 |
| `ecmc.catalog.request` | 创建或取消目录扩展申请 |
| `ecmc.catalog.approve` | 批准、驳回申请或重试履约 |
| `ecmc.causal_model.audit.read` | 查看治理和 Artifact 信息 |

权限同时受以下边界约束：

- tenant（租户）；
- data domain（数据域）；
- 资源可见性；
- 当前 Version 状态。

常见权限响应：

| 现象 | 含义 | FDE 处理 |
|---|---|---|
| `403` | 资源可见，但没有执行该操作的权限 | 检查角色权限和数据域授权 |
| `404` | 资源不存在，或对当前用户不可见 | 检查 tenant、数据域和资源 ID，不要直接判断为数据丢失 |

生产环境建议保持职责分离：建模者提交，审核者发布，发布运维编译，业务负责人激活。

---

## 3. 当前 Catalog 前置条件

因果模型中的实体类型、关系类型、指标、单位、聚合、时间窗口、绑定模板、规则 Schema 和 Capability Contract 都是**可执行语义**，必须从受控 Catalog 选择。

禁止在模型中填写：

- SQL 或自由查询表达式；
- URL、endpoint；
- Provider 参数或物理 Provider ID；
- credential、token、密码；
- 任意 stable ID、`latest` 或 `*` 版本；
- 自由执行 DSL。

### 3.1 当前签署状态

当前 N01A 已实现 CatalogResolver interface、fake adapter、contract test 和 CatalogChangeRequest，但**生产 Catalog browse/search API 与 manifest owner 尚未签署**。

因此：

- 正式页面默认不伪造 Catalog 数据；
- 没有生产 adapter 时，依赖 Catalog 的创建操作会禁用并说明原因；
- 已保存的 CatalogRef 可以只读展示；
- FDE 不得在生产环境启用 Case A Fixture；
- 真实 Provider、endpoint 和凭据仍属于后续 N03。

### 3.2 test-only 演示模式

本地开发或集成测试可在 URL 上显式增加：

```text
?catalog=fake
```

例如：

```text
pages/ecmc-models.html?type=causal&catalog=fake
```

该模式只加载 Case A 的 test-only Catalog，用于界面合成和合同测试。它不是生产数据源，禁止用于客户生产建模、正式 HTTP composition、N02 Discovery 或 Provider 接入。

### 3.3 为什么煤矿和金融看到的 Catalog 不一样

Catalog 不是一份对所有客户都相同的“大字典”。它保存的是行业和企业的受控业务语义，因此通常分为四层：

| 层级 | 通俗解释 | 例子 |
|---|---|---|
| 平台基础包 | 多个行业真正通用的基础概念 | 吨、元、小时、日均 |
| 行业包 | 某个行业共同使用的业务概念 | 煤矿的原煤产量；金融的净息差 |
| 企业扩展包 | 某家企业自己的业务口径 | 某集团定义的有效生产时长 |
| 数据域授权 | 决定当前人员能看和使用哪些内容 | 生产域、安全域、财务域、风控域 |

可以把它理解为给不同客户安装不同的“业务词典组合包”：

```text
煤矿 A 集团生产域
├─ 平台基础包
├─ 煤矿行业包
└─ A 集团扩展包

金融 B 银行风控域
├─ 平台基础包
├─ 金融行业包
└─ B 银行扩展包
```

两套组合需要分别生成 manifest、分别签署。煤矿中的“产量”不能因为名字相似就被金融模型使用；只有语义、schema 和 hash 都一致的基础条目才能跨行业复用。

企业扩展包也不能偷偷覆盖行业定义。如果同一个精确引用在组合包里出现两种语义，系统应拒绝加载，由 owner 发布新版本或新的 stable ID。FDE 在页面上只选择当前 tenant、行业和数据域已经授权的有效条目，不需要也不能通过手写 ID 切换到其他行业。

`CatalogRef` 本身仍只有 `kind + stable_id + version`。行业、企业和数据域范围由登录上下文和已签署 manifest 决定。例如：

```text
common.mass.tonne
coal.raw_coal_output
finance.net_interest_margin
enterprise_acme.effective_production_hours
```

未来 EARP 从煤矿扩展到金融时，不需要改变 ECMC 的模型发布、编译和激活流程；需要新增金融行业 Catalog Pack、指定 owner、生成金融范围的 manifest，并完成独立签署和合同测试。

---

## 4. 因果模型的业务结构

一个 Logical Causal Model 固定服务一个 Diagnostic Target。需要改变诊断目标时，应创建新模型，而不是修改已存在模型的目标签名。

### 4.1 Diagnostic Target

创建模型时需要确定：

- 数据域；
- 目标实体类型；
- 诊断方向，如 `up`、`down`、`change`；
- 入口节点 key；
- 时间窗口 Schema。

这些字段共同形成目标签名，创建后不可随 Version 修改。

贯穿案例可以填写为：

| 字段 | 示例值 | 通俗解释 |
|---|---|---|
| 数据域 | 生产数据 | 去哪个业务范围找数据和目录项 |
| 目标实体类型 | 矿山 | 诊断对象是什么 |
| 诊断方向 | `down` | 我们关注指标下降 |
| 入口节点 key | `production_output` | 从哪个结果开始倒推原因 |
| 时间窗口 | 日窗口 | 按一天的数据做判断 |

例如，“设备能耗上升”虽然也发生在 3 号矿，但目标、方向和入口都不同，应另建一个模型，不能塞进“产量下降诊断”。

### 4.2 Node

节点表示业务因果图中的一个因素或结果。

主要字段：

- `node_key`：模型内稳定唯一标识；
- 业务名称；
- EntityType CatalogRef；
- `observability`；
- 是否为入口节点；
- notes。

可观测性：

| 值 | 含义 |
|---|---|
| `observable` | 可由证据直接观测 |
| `indirectly_observable` | 通过其他因素间接判断 |
| `latent_hypothesis` | 潜在假设，可能没有直接证据 |

入口节点必须是 `observable`，且一个 Version 恰好有一个入口节点。

贯穿案例中的节点可以这样设计：

| node key | 业务名称 | observability | 为什么 |
|---|---|---|---|
| `production_output` | 产量 | `observable` | 有日产量指标，可以直接观测 |
| `haulage_cycle_time` | 运输周期 | `observable` | 有矿卡运输周期指标 |
| `equipment_availability` | 装载设备可用率 | `observable` | 有设备可用率指标 |
| `dispatch_congestion` | 调度拥堵 | `latent_hypothesis` | 可能无法直接测量，只能结合排队时间推断 |

错误示例：把 `production_output` 标成 `latent_hypothesis`，同时又设为入口节点。入口必须能被直接观测，因此校验会阻断。

### 4.3 Edge

边表示两个节点间的因果影响。

主要字段：

- source / target；
- RelationType CatalogRef；
- effect：`+` 或 `-`；
- strength、confidence；
- lag；
- rationale。

首版只支持 DAG：不能有自环、环路、悬空端点或无法通向入口目标的节点。

正确示例：

```text
运输周期变长 --(-)--> 产量
设备可用率下降 --(+)--> 产量
```

这里 `effect` 表示“源因素增加时，对目标的影响方向”。例如：

- 运输周期越长，产量通常越低，因此是 `-`；
- 设备可用率越高，产量通常越高，因此是 `+`。

错误示例：

```text
产量 → 运输周期 → 排队时间 → 产量
```

这形成了环。首版只支持 DAG，校验会阻断发布。

### 4.4 Evidence Requirement

Evidence Requirement 定义“系统需要什么证据验证这个节点”。

每项包括：

- metric；
- unit；
- aggregation；
- time window；
- binding template；
- binding params；
- required / optional；
- 恰好一个 primary Capability Contract；
- 零到多个 supporting Capability Contract；
- 业务说明。

`binding_params` 只能填写 BindingTemplate schema 声明的字段。primary Contract 失败时系统不会自动改用 supporting Contract；自动 failover 属于后续能力解析策略。

贯穿案例中，“运输周期”节点的证据可以这样理解：

| 字段 | 示例 | 通俗解释 |
|---|---|---|
| metric | 运输周期 | 要看什么指标 |
| unit | 分钟 | 指标用什么单位 |
| aggregation | 平均值 | 多条记录如何汇总 |
| time window | 日窗口 | 看哪段时间 |
| binding template | 出向关系 | 如何找到当前矿山关联的运输系统 |
| binding params | 关系=`拥有运输系统`，目标类型=`运输系统` | 模板允许填写的固定参数 |
| required | 是 | 缺少该证据时是否阻断当前模型要求 |
| primary contract | 读取运输周期 | 首选的逻辑取数能力 |
| supporting contract | 读取运输质量 | 补充证据，不是自动备用线路 |

不要在 Evidence 中填写类似下面的内容：

```text
SELECT avg(cycle_time) FROM truck_events
http://provider.example/api
token=abc123
```

这些属于 Provider 和物理连接配置，不属于认知模型。

### 4.5 Rule

规则必须引用受控 RuleSchema，目前只支持：

- `predicate`；
- `threshold`；
- `direction_rule`。

规则不能包含脚本、Provider 配置或自由执行表达式。

规则示例：

```text
当运输周期相对基线增加超过 15%，标记为异常方向证据。
```

业务人员表达的是规则语义；具体字段必须由受控 RuleSchema 决定，不能直接粘贴 Python、JavaScript 或 SQL。

---

## 5. 新建因果模型

> 需要 `ecmc.causal_model.write_draft`，并且需要可用的 Catalog adapter。

1. 进入 **认知模型 → 模型资产 → 因果模型**。
2. 点击右上角 **+ 新建模型**。
3. 模型类型选择 **因果模型**。决策模型和任务模型当前不可选。
4. 选择数据域。
5. 选择目标实体类型。
6. 填写诊断方向、入口节点 key，并选择时间窗口 Schema。
7. 填写模型名称和业务说明。
8. 检查 Diagnostic Target 摘要，确认后创建。

创建成功后，系统建立 Logical Model 和首个 Draft Version，并进入编辑器。

建议命名：

```text
<业务对象> + <异常/变化> + 诊断

示例：3 号矿产量下降诊断
```

不要把多个诊断目标塞进同一个模型。例如“产量下降诊断”和“设备能耗上升诊断”应是两个 Logical Model。

### 5.1 完整填写示例

```text
模型类型：因果模型
数据域：生产数据
目标实体类型：矿山
诊断方向：下降（down）
入口节点 key：production_output
时间窗口：日窗口
模型名称：3 号矿产量下降诊断
业务说明：用于解释日产量低于计划时的主要业务原因
```

FDE 可以这样向客户解释：

> 这一步只是在定义“我们要诊断谁、诊断什么变化、从哪个结果开始追原因”。还没有录入原因图，也没有上线。

---

## 6. 编辑 Draft

编辑器分为四个区域：

```text
顶部：模型名、Version、状态、revision、治理操作
左侧：节点、边、证据和规则结构
中央：因果 DAG
右侧：当前资源属性
底部：校验结果抽屉
```

### 6.1 推荐建模顺序

1. 创建入口节点。
2. 创建原因节点。
3. 添加从原因通向结果的边。
4. 为可观测节点添加 Evidence Requirement。
5. 添加必要规则。
6. 运行全量校验。

贯穿案例的实际顺序：

```text
第 1 步：创建 production_output（产量）入口节点
第 2 步：创建 haulage_cycle_time（运输周期）原因节点
第 3 步：创建 equipment_availability（设备可用率）原因节点
第 4 步：添加 原因 → 产量 的边
第 5 步：分别为节点选择指标、单位、聚合、时间窗口和能力合同
第 6 步：运行校验
```

如果不确定先画什么，先问客户两个问题：

1. “最终要解释的结果指标是什么？”——它通常是入口节点。
2. “业务上最常见的前三个原因是什么？”——它们通常是第一层原因节点。

### 6.2 保存与并发

页面保存时自动携带当前 Version revision。每次成功写入后 revision 递增。

如果其他用户先修改了同一 Version，当前写入会得到：

```text
409 VERSION_CONFLICT
```

此时：

1. 停止继续编辑；
2. 重新加载最新版本；
3. 对照自己的修改重新处理；
4. 不要尝试覆盖服务器版本。

这不是模型校验错误，不会出现在底部 ValidationResult 中。

### 6.3 删除资源

节点存在边、规则或证据依赖时，不能直接删除。应先显式删除依赖，再删除节点。

系统不会为了方便而隐式级联删除业务语义。遇到 `RESOURCE_HAS_DEPENDENTS` 时，按错误详情清理依赖。

### 6.4 非 Draft 版本

只有 Draft 可编辑。`in_review`、`published`、`superseded`、`archived` 都应只读。

需要修改历史版本时，点击 **复制草稿**，基于该版本创建新的 Draft。Snapshot、审核和编译记录不会被复制。

---

## 7. 校验模型

点击顶部 **校验**，运行 full validation。校验结果进入底部抽屉。

### 7.1 Error 与 Warning

| 类型 | 是否阻断提交/发布 | 示例 |
|---|---|---|
| Error / 阻断 | 是 | DAG 有环、入口缺失、CatalogRef 无效、required evidence 缺失 |
| Warning / 警告 | 否 | 置信度偏低、lag 过长、适用范围过窄 |

每条问题应包含：

- 稳定 code；
- message；
- severity；
- 节点、边、规则或证据的定位信息；
- 建议处理动作。

点击问题后，编辑器应定位到对应资源。

### 7.2 校验示例

假设 FDE 创建了以下错误边：

```text
产量 → 运输周期
运输周期 → 产量
```

系统会发现环路，并给出阻断问题。处理方式不是“忽略警告”，而是根据真实业务方向删除错误边。

另一个例子：

```text
问题：运输周期节点标记 required evidence，但没有选择 primary Capability Contract
结果：阻断提交审核
修复：为该 Evidence 选择“读取运输周期”逻辑能力合同
```

Warning 示例：某条边的 confidence 只有 `0.55`。这表示业务把握不高，但不一定阻止发布；审核者需要判断该风险是否可接受。

### 7.3 哪些错误不属于模型校验

以下问题使用全局错误条，不应混入 ValidationResult：

- 权限不足：`403`；
- 资源不可见：`404`；
- Version 并发冲突：`VERSION_CONFLICT`；
- 状态不允许：`INVALID_STATE_TRANSITION`；
- Active pointer 冲突：`ACTIVE_VERSION_CHANGED`；
- 幂等键误用：`IDEMPOTENCY_KEY_REUSE`。

---

## 8. 提交审核、驳回与治理发布

### 8.1 提交审核

1. 在 Draft 中点击 **提交审核**。
2. 页面先运行 full validation。
3. 有阻断项时保持 Draft，并打开校验面板。
4. 无阻断项时，Version 进入 `in_review`，内容锁定。

提交审核不等于发布，更不等于上线。

### 8.2 审核与驳回

审核者进入 **审核发布 → 待审核**，打开只读版本。

审核者应检查：

- Diagnostic Target 是否正确；
- 节点和边是否表达真实业务因果关系；
- required Evidence 是否充分；
- CatalogRef 是否属于正确数据域；
- primary Capability Contract 是否合理；
- 警告是否可以接受。

需要修改时点击 **驳回**，必须填写原因。驳回后 Version 回到 `draft`，revision 递增，内容保留。

### 8.3 治理发布

审核通过后点击 **通过并发布**，确认以下信息：

- 模型与 Version ID；
- revision；
- Diagnostic Target；
- 数据域；
- 校验结果。

发布成功后：

- Version 进入 `published + inactive`；
- 生成不可变 Snapshot；
- 返回 Snapshot ID 和 canonical content hash；
- 内容变为只读；
- 当前 Active Version 不变；
- 不自动编译、不自动激活。

不要把“发布成功”对客户解释为“已经上线”。

### 8.4 用案例区分提交、发布和上线

```text
建模者画完“3 号矿产量下降诊断”
    ↓ 提交审核
审核者发现运输周期方向画反了
    ↓ 驳回并说明原因
建模者修正后再次提交
    ↓ 审核通过并发布
系统生成 Snapshot，但生产诊断仍使用旧模型
```

FDE 可直接使用下面的话术：

> “现在模型已经盖章冻结，可以追溯，但还没有进入生产。下一步需要把这个 Snapshot 编译成系统能运行的 Artifact，再由有激活权限的人明确上线。”

---

## 9. 编译 Candidate Artifact

> 需要 `ecmc.causal_model.compile`。只有 `published` Version 可以编译。

1. 打开已发布 Version，或进入 **编译与激活 → 最新编译状态**。
2. 点击 **编译**。
3. 系统创建新的 Compile Attempt，初始状态为 `running`。
4. 刷新治理状态，等待 `success` 或 `failed`。

状态机严格为：

```text
running → success
        → failed
```

成功 Attempt 冻结：

- Candidate Artifact JSON；
- Artifact hash；
- Artifact schema version。

编译只读取发布时生成的 immutable Snapshot，不读取后来创建的 Draft。

### 9.1 编译失败与重试

编译失败时：

- 旧 Active Version 继续服务；
- 失败 Attempt 保留，不能原地改成 running；
- 重试必须创建新的 Attempt；
- 新 Attempt 记录 `retry_of_compile_id`。

不要通过修改数据库把 failed Attempt 改成 success，也不要伪造 Artifact。

> 当前前端展示的是每个 Version 的“最新编译状态”，不是完整 Compile Attempts 历史。完整历史需要后续列表 API。

### 9.2 编译失败示例

假设当前生产使用 v1，新发布的 v2 编译失败：

```text
v1：Active，继续服务
v2：Published，Compile Attempt #1 = failed
```

修复问题后重试：

```text
v2：Compile Attempt #1 = failed（保留）
v2：Compile Attempt #2 = running，retry_of = Attempt #1
v2：Compile Attempt #2 = success
```

Attempt #1 不会被覆盖或改成 success，这样审计人员能看清每一次真实尝试。

---

## 10. 显式激活

> 需要 `ecmc.causal_model.activate`，且必须选择一个 `success` Compile Attempt。

1. 打开已发布 Version 的治理信息。
2. 确认 Compile Attempt ID 和 Artifact hash。
3. 点击 **激活**。
4. 在确认框中检查：
   - Candidate Version；
   - Compile Attempt；
   - Artifact hash；
   - 当前 active pointer；
   - expected active pointer。
5. 点击 **确认激活**。

激活只会物化用户明确选择的 Artifact：

- 不重新编译；
- 不自动挑选其他成功 Attempt；
- 不读取可变 Draft；
- 不允许绕过 active gate。

激活成功后，新 Version 成为 Active，旧 Active Version 才进入 `superseded`。

### 10.1 ACTIVE_VERSION_CHANGED

如果确认期间另一个用户已经切换了 Active Version，系统返回：

```text
409 ACTIVE_VERSION_CHANGED
```

该冲突保证零业务写入：

- 不产生 Blueprint；
- 不改变 Version 状态；
- 不改变 active pointer；
- 不写 activation audit/outbox；
- 不消费 Artifact。

页面会刷新当前 active pointer，并重新打开确认。FDE 必须重新核对后由用户明确确认，不能自动重试激活。

### 10.2 激活前后示例

激活前：

```text
v1 = Active
v2 = Published + Compile success + inactive
```

明确选择 v2 的成功 Artifact 并激活后：

```text
v1 = superseded
v2 = Active
```

如果 v2 只是发布或编译成功，没有点击激活，v1 仍然是 Active。这是系统刻意设计的安全门，不是延迟或故障。

---

## 11. 归档

审核者可以归档不再使用的 Version。

普通 Version 归档后进入只读 `archived`。

归档当前 Active Version 是一个原子治理操作：

1. 清空该模型的 active pointer；
2. 归档源 Version；
3. withdraw 精确 source pin 对应的 current Blueprint。

归档不会修改历史 Snapshot、Artifact 或 Trace。历史诊断仍按自己的 pin 重放。

归档 Active Version 后，如果没有新的 Active Version，新诊断应得到明确的“尚未投产”状态，而不是自动选择其他 Published Version。

---

## 12. 目录扩展申请

当受控 Catalog 中缺少所需实体类型、关系、指标、单位、聚合、时间窗口、绑定模板、能力合同或规则 Schema 时，不能在模型里临时手填。

进入 **目录扩展申请** 创建申请。

### 12.1 申请内容

- `request_type`；
- 目标数据域；
- 业务名称；
- 语义定义；
- 与类型对应的 typed contract；
- 申请理由。

不同类型的 contract 不同。例如 Metric 需要：

- value type；
- time semantics；
- allowed units；
- allowed aggregations。

申请不允许包含 raw JSON Schema、SQL、URL、Provider 参数或执行代码。

### 12.2 状态流转

```text
draft → submitted → approved_pending_fulfillment → fulfilled
                  ↘ rejected
draft/submitted → cancelled
approved_pending_fulfillment → fulfillment_failed → retry → approved_pending_fulfillment
```

重点：

- approve 只代表同意申请；
- `approved_pending_fulfillment` 仍不能被模型引用；
- 只有 Resolver 返回 active stable ref 后才进入 `fulfilled`；
- 履约失败可以重试，但每次重试建立新 attempt；
- reject 必须填写原因；
- 申请人只能取消自己的 draft/submitted 申请。

当前生产 Catalog browse 合同未签署时，页面会禁用提交并明确提示。FDE 不应通过自由 ID 或 Fixture 绕过该限制。

### 12.3 目录申请示例

场景：模型需要“矿卡排队时间”指标，但 Catalog 中没有。

申请可以这样填写：

```text
request_type：metric
目标数据域：生产数据
业务名称：矿卡排队时间
语义定义：矿卡到达装载点后，从进入队列到开始装载的等待时长
value_type：decimal
time_semantics：event_duration
允许单位：分钟
允许聚合：平均值、P95
申请理由：用于判断运输拥堵是否导致日产量下降
```

错误申请示例：

```text
业务名称：排队时间
语义定义：查 truck_queue 表
contract：http://10.0.0.8/query?sql=...
```

错误原因：它描述了物理实现和 endpoint，没有清晰定义业务语义。目录申请应回答“这个指标是什么”，而不是“去哪里执行 SQL”。

---

## 13. 常见问题排查

| 错误/现象 | 常见原因 | 处理方法 |
|---|---|---|
| `HTTP_401` | 未登录、token 过期 | 重新登录，再刷新 ECMC |
| `403` | 缺少对应操作权限或数据域授权 | 检查 RBAC 和 data-domain scope |
| `404` | ID 错误、跨租户或资源不可见 | 核对登录租户和资源来源 |
| `MODEL_VALIDATION_FAILED` | 模型存在阻断项 | 打开底部校验面板逐项修复 |
| `VERSION_CONFLICT` | 当前 revision 已过期 | 重新加载 Version，不要静默覆盖 |
| `INVALID_STATE_TRANSITION` | 在错误状态执行操作 | 核对 Draft/in_review/published 等状态 |
| `RESOURCE_HAS_DEPENDENTS` | 删除对象仍被其他资源引用 | 先显式删除依赖 |
| `INVALID_RETRY_PARENT` | retry 指向其他 Version 或非 failed Attempt | 使用同一 Version 的精确 failed Attempt ID |
| `ACTIVE_VERSION_CHANGED` | active pointer 被其他用户更新 | 刷新指针，重新人工确认 |
| `IDEMPOTENCY_KEY_REUSE` | 同一 key 被用于不同业务请求 | 重新发起一次新的业务操作 |
| 新建按钮不可用 | 生产 Catalog browse API 未签署 | 等待 Catalog 合同/adapter；仅本地可用 fake |
| 编译失败后旧模型仍在运行 | 正常的 last-known-good 行为 | 修复候选后创建新的 Compile Attempt |
| 发布后诊断仍使用旧模型 | 尚未激活 | 编译成功后显式激活指定 Artifact |

### 13.1 错误定位原则

先判断错误属于哪一层：

```text
模型内容错误 → ValidationResult
权限/可见性 → 403 / 404
Version 并发 → VERSION_CONFLICT
治理状态 → INVALID_STATE_TRANSITION
Active 并发 → ACTIVE_VERSION_CHANGED
编译过程 → CompileRecord failed
目录履约 → fulfillment_failed
```

不要把权限、并发或状态错误解释成“模型画错了”。

---

## 14. FDE 推荐演示脚本

### 14.1 演示前说明

明确告诉参与者：

- 当前演示使用 test-only Catalog；
- 演示不连接真实 Provider；
- 演示重点是治理闭环，不是诊断结果 UI；
- 发布和激活是两个独立审批点。

### 14.2 演示步骤

本地或集成环境打开：

```text
pages/ecmc-models.html?type=causal&catalog=fake
```

然后依次演示：

1. 新建“3 号矿产量下降诊断”。
2. 选择生产数据域、目标实体类型和时间窗口。
3. 创建入口节点和两个原因节点。
4. 添加因果边。
5. 添加 Evidence Requirement，并展示 metric/unit/aggregation/binding/contract 都来自受控目录。
6. 故意制造一个阻断错误，例如环路或缺失 required evidence。
7. 运行校验，展示问题定位。
8. 修复后提交审核。
9. 使用审核权限驳回一次，展示驳回原因和返回 Draft。
10. 再次提交并治理发布，展示 Snapshot ID/hash。
11. 强调当前仍未 Active。
12. 发起编译，展示 running → success 和 Candidate Artifact hash。
13. 激活指定 Artifact，展示 Active Version 更新。
14. 说明旧 active 在步骤 12 期间一直正常服务。

如果环境支持并发演示，可用两个窗口制造 active pointer 冲突，展示 `ACTIVE_VERSION_CHANGED` 和重新确认流程。

### 14.3 FDE 可直接照读的客户话术

介绍 ECMC：

> “知识中心保存企业已有的资料和事实，ECMC 保存企业如何解释问题的模型。这里不是直接写程序，而是把业务专家的因果经验做成可审核、可追溯的资产。”

介绍受控目录：

> “模型里选择的是‘运输周期’这个业务指标，而不是某个数据库字段或接口地址。将来数据源变化时，模型语义不需要跟着改。”

介绍发布与激活：

> “发布相当于审批盖章，激活才是正式上线。中间还有一次编译检查，因此一个新模型即使有问题，也不会直接替换当前生产模型。”

介绍 last-known-good：

> “新版本编译失败时，旧版本照常服务。系统不会为了追新版本而牺牲当前稳定运行。”

介绍并发冲突：

> “如果两个人同时上线不同版本，后提交的人会被拦住并看到最新状态，系统不会静默覆盖。”

---

## 15. 人工验收清单

### 15.1 基础与权限

- [ ] 未登录进入 ECMC 明确显示 401，不出现伪造数据。
- [ ] 无 read 权限无法读取模型。
- [ ] 跨租户/无数据域授权资源不可见。
- [ ] 无 write/review/compile/activate 权限时对应操作不可成功。

### 15.2 Draft 与校验

- [ ] 可创建模型和首个 Draft。
- [ ] Diagnostic Target 创建后不能通过 Version 修改。
- [ ] 节点、边、Evidence、Rule 可保存并重新打开。
- [ ] 环路、悬空引用、入口错误和 required evidence 缺失能够阻断。
- [ ] Warning 不阻断提交。
- [ ] `VERSION_CONFLICT` 不会静默覆盖。

### 15.3 审核与发布

- [ ] 提交审核后内容只读。
- [ ] 驳回必须填写原因，并回到 Draft。
- [ ] 发布生成 Snapshot ID/hash。
- [ ] Published Version 不可修改。
- [ ] 发布不会改变 Active Version。

### 15.4 编译与激活

- [ ] 编译只允许 Published Version。
- [ ] success Attempt 有不可变 Artifact/hash/schema version。
- [ ] failed retry 创建新 Attempt，并保留 `retry_of_compile_id`。
- [ ] 编译失败不影响旧 Active Version。
- [ ] 激活只物化指定 success Artifact。
- [ ] `ACTIVE_VERSION_CHANGED` 时零业务写入并要求重新确认。
- [ ] Active 归档会原子清 pointer 并 withdraw 精确 Blueprint。

### 15.5 Catalog

- [ ] 所有可执行字段只能通过 Catalog picker 选择。
- [ ] 不存在自由 stable ID、SQL、endpoint、Provider、credential 或自由 DSL 输入。
- [ ] 未履约申请不能进入模型选择器。
- [ ] 生产无 Catalog adapter 时不回退 Case A Fixture。

---

## 16. 当前范围与后续能力

当前已覆盖：

```text
Draft → Validate → Review → Publish Snapshot
      → Compile Candidate Artifact → Explicit Activate
```

当前不覆盖：

- N02 诊断发起、执行进度、诊断结果和 Trace UI；
- N03 真实 Provider、连接参数、凭据和物理 Capability Binding；
- 决策模型与任务模型的元模型/API/编辑器；
- 自动因果发现或 LLM 自动建模；
- 循环因果图；
- 自动激活、自动候选选择、自动回退；
- 完整 Compile Attempts 历史列表；
- 审核任务分配和完整审核历史查询。

后续能力未冻结前，FDE 不应使用自由字段、假数据或其他模块 API 模拟这些功能。

---

## 17. 权威文档索引

发生产品口径或接口争议时，以以下文件为准：

1. `prd/PRD-2026-033-causal-model-management-n01a.md`
2. `arch/design/2026-08-30-causal-model-management-n01-detailed-design.md`
3. `arch/design/2026-08-30-planning-blueprint-l3-implementation-erratum-n01a.md`
4. `api/2026-08-30-n01a-causal-model-management-api-contract.md`
5. `arch/design/2026-08-30-n01a-canonicalization-and-hash-contract.md`
6. `arch/design/2026-08-30-n01a-catalog-resolver-and-fixture-boundary.md`
7. `arch/design/2026-08-30-ecmc-frontend-information-architecture-and-page-template.md`

本指南用于帮助 FDE 理解和操作功能，不替代冻结的产品、架构和 API 合同。
