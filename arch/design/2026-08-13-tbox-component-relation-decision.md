# TBox 部件级关系缺口 — 决策备忘

- 日期: 2026-08-13
- 状态: 待拍板（阻塞 QU 设计 v0.3 §17 relation 门槛 / §20 开放问题 1）
- 关联: `arch/design/2026-08-07-ontology-layer-design.md`（§3.2 关系类型）、`arch/design/query-understanding-query-plan-design-v0.3.md`（§6.2/§17/§20-1）、`arch/design/2026-08-07-ontology-layer-l3-design-v1.md`（§161）
- 决策点: 扩展 TBox vs 部件按 material 处理

---

## 1. 问题定义（精确缺口）

QU 设计 §6.2 写死「relation 必须来自 TBox（`relation_types` 的 12 类）」，但冻结的 12 类关系里有两类查询**无法输出合法 relation**：

| 查询 | 需要的 relation | TBox 现状 |
|---|---|---|
| "CNC-01 的主轴轴承由哪家供应商提供？" | `component → supplier` | ❌ `supplied_by` source 仅 `material`；`manufactured_by` source 仅 `equipment` |
| "CNC-01 装的主轴轴承是哪个？"（部件归属） | `component → equipment` | ❌ `belongs_to` source 仅 `equipment,sensor`、target 仅 `production_line` |

**为何现在必须拍板**：这两类查询正是 QU 评估集的典型用例（"CNC-01 主轴轴承由谁供应" 出现在 ontology 设计 §7.2、P2 任务书 verify_ontology 用例）。若 TBox 不补，QU 无法产出合法 relation → 直接打穿 §17「relation 准确率 ≥ 80%」门槛。

---

## 2. 代码实证（拍板前必须知道的 5 个事实）

1. **`tbox_service.py:30-44`（`SEED_RELATION_TYPES`）**：`supplied_by`=("由…供应","material","supplier")、`manufactured_by`=("由…制造","equipment","supplier")、`belongs_to`=("属于","equipment,sensor","production_line")。
2. **归属关系 de-facto 已在用 `belongs_to`**：`test_ontology.py:82` 与 `verify_knowledge.py:111` 均已把 `component → belongs_to → equipment` 作为事实落库——即「部件归属设备」在 ABox/测试里**已经用了 belongs_to**，只是 TBox 声明没跟上。
3. **`add_fact()` 不校验类型域**（`abox_service.py:122-153` 直接 INSERT facts，不比对 relation_types 的 source_type/target_type）——TBox 类型域当前是「文档级约束」，非运行时约束。
4. **seed 用 `ON CONFLICT DO NOTHING`**（`tbox_service.py:66`）：改 `SEED_RELATION_TYPES` **不会**更新已种子租户的既有行，需 migration UPDATE 或 seed 升级。
5. **`caused_by` target 已含 `component`**（`tbox_service.py:40`，下钻到部件级）——说明 `component` 是独立概念、有独立事实，不是 material 的别名。

---

## 3. 方案对比

### 方案 1：扩展 TBox（放宽类型域，不新增关系，推荐）

三处最小改动（均只放宽 source/target 类型域，关系清单仍是 12 类）：

| relation | 现状 source → target | 改为 |
|---|---|---|
| `supplied_by` | `material` → `supplier` | `material,component` → `supplier` |
| `manufactured_by` | `equipment` → `supplier` | `equipment,component` → `supplier` |
| `belongs_to` | `equipment,sensor` → `production_line` | `equipment,sensor,component` → `production_line,equipment` |

**影响**：
- 代码：`SEED_RELATION_TYPES` 三行 + 已种子租户 migration UPDATE（因 DO NOTHING 不覆盖）。
- 文档：ontology-layer-design §3.2 关系表 3 行；l3-design-v1 §161 的 12 类清单**不变**（只变域）。
- Phase 2a 导入映射：设备台账/供应商表导入时规则生成 `component→belongs_to→equipment`、`component→supplied_by→supplier`。
- §17 relation 门槛恢复可评估。

**代价**：一个语义瑕疵——`belongs_to` 放宽后 `sensor → equipment` 理论上也可表达（source 含 sensor、target 含 equipment），而 sensor→equipment 的正确关系应是 `monitored_by` 反向。**当前 add_fact 不校验，故仅是文档级瑕疵**；若在意，见 §5 子决策点 B。

### 方案 2：部件按 material 处理（改建模，不推荐）

把「主轴轴承」等部件不建 `component` 实例、按 `material` 建模，复用 `supplied_by`(material→supplier)。

**四个硬伤**：
1. **语义降级**：material（原材料/半成品/成品，有库存、可消耗）≠ component（设备关键部件，有生命周期、可下钻到报警）。`caused_by` 已下钻到 component 级（事实 5），按 material 处理会断掉「报警→部件」下钻链路。
2. **归属仍无法表达**：`consumes` 是 `equipment → material`（消耗），方向反、语义错；反向问「哪个设备装了这个部件」又撞反向遍历缺口（Phase D2）。
3. **推翻已决策 + 已有数据**：2026-08-07 已决策「新增 component 一级部件类型」；`test_ontology.py` / `verify_knowledge.py` 已把 component 当独立类型落事实。方案 2 要改决策 + 改测试 + 改导入映射。
4. **表面零 TBox 变更，实则改更多**：实体类型、caused_by target、已有 ABox/测试数据、Phase 2a 导入映射全要动。

---

## 4. 推荐

**采纳方案 1（扩展 TBox 类型域）。** 理由：component 已是独立概念（有 caused_by 下钻、有独立测试事实），把它降级为 material 是语义倒退且改动更大；放宽三个关系类型域是最小、最贴近现有代码事实（belongs_to 已 de-facto 用于 component→equipment）的修法。

---

## 5. 两个子决策点（随方案 1 一并拍板）

- **子决策 A（供应关系用几个）**：`supplied_by` 与 `manufactured_by` **都**加 component source（覆盖「由谁供应」+「谁生产」两类自然问法），还是只加 `supplied_by`（最小，覆盖最高频的「供应商」问法）。**建议都加**——两者语义本就是对 equipment/component 同构的「供应/制造」关系，代价仅是 source 字符串各加一个词。
- **子决策 B（归属关系复用还是新增）**：
  - B1（推荐，最小）复用 `belongs_to`，放宽 source/target 域（如上表），接受 sensor→equipment 的文档级瑕疵；
  - B2（语义最精确）新增 `installed_in`（`component → equipment`，N:1），并把 `test_ontology.py` / `verify_knowledge.py` 里已用的 `belongs_to` 改为 `installed_in`（两处数据改动），关系清单 12 → 13 类（触发 TBox 审批）。
  - **默认 B1**；若项目组在意「关系贴近业务动词、不通用化」（ontology 设计 P2），改选 B2。

---

## 6. 拍板后改动清单

| # | 文件 | 改动 |
|:-:|---|---|
| 1 | `apps/earp-server/src/earp_server/ontology/tbox_service.py` | `SEED_RELATION_TYPES` 3 行（或 +`installed_in`） |
| 2 | migrations 新版本 | UPDATE 已种子租户的 `relation_types.source_type/target_type`（DO NOTHING 不覆盖） |
| 3 | `arch/design/2026-08-07-ontology-layer-design.md` §3.2 | 关系表 3 行（+ 若 B2 则加 installed_in） |
| 4 | `arch/design/2026-08-07-ontology-layer-l3-design-v1.md` §161 | 同步 12/13 类关系说明 |
| 5 | `arch/design/query-understanding-query-plan-design-v0.3.md` §20 问题 1 | 关闭开放问题，标注已决策 |
| 6 | `arch/session-record.md` | 决策记录 + 解除 Phase B 阻塞 |
| 7 | （若 B2）`test_ontology.py` / `verify_knowledge.py` | belongs_to → installed_in |

**前置依赖提醒**：本文档不自行拍板，仅备选；请项目组就「方案 1/2 + 子决策 A/B」给出结论后，按上表落地，随后 Phase B（QU 评估集）解除阻塞。
