# EARP 中台对接数据契约规范 v1.0

> 给数据中台 / 数据团队看的对接约定（M3 交付物）。EARP 不强制中台按固定模板建表，
> 而是「映射驱动」：中台保持原生态表/API，EARP 注册数据源时用 `field_mapping`
> 把中台字段翻译成 EARP 实体模型。本规范定义**最小契约**（必须满足的底线）+
> **推荐模板**（照抄即用）+ **校验规则**（注册时怎么验）。
>
> 关联：`tasks/m3-ontology-import-enrichment-task-breakdown.md`（A3/B1）、
> `arch/design/2026-08-07-ontology-layer-design.md` §4.6（ABox 数据源模式）

---

## 1. 对接模式速览

| 模式 | EARP 是否存数据 | 适用场景 | 中台侧交付物 |
|:---|:---|:---|:---|
| **synced（同步）** | 存副本（定期拷贝） | 主数据（设备台账/供应商/组织架构）——不常变 | 一张表/视图 或 全量拉取 API |
| **virtual（直连）** | 不存，实时取 | 指标/状态（OEE/销售额/温度）——随时变 | 按编码单查的 REST API |

> 决策指南：主数据走 synced；状态/指标走 virtual；源系统无稳定 API 时用同步；
> 无中台场景用 CSV 兜底（不受本规范约束）。

## 2. 最小契约（必须满足，缺一项就无法对接）

### 2.1 synced（数据表/视图）

| # | 契约项 | 要求 | 说明 |
|:--:|:---|:---|:---|
| 1 | **一个数据源 = 一类实体** | 一张表/视图对应一种实体类型 | EARP 按类型取数建实体 |
| 2 | **业务编码列** ⭐必填 | 唯一、稳定、跨行不重复 | 幂等同步的锚点（二次同步按它合并，不重复插行） |
| 3 | **名称列** ⭐必填 | 展示名 | 实体显示用 |
| 4 | 更新时间戳列 | 建议有 | 增量同步（`WHERE 更新时间 > 上次同步`）；没有则每次全量拉 |
| 5 | 软删标记 | 建议有 | 中台删了记录，EARP 侧标 deprecated 而非留幽灵数据 |
| 6 | 关系列 | 可选 | 表里带外键语义的列可映射成关系（见 §4.3） |

### 2.2 virtual（REST API）

| # | 契约项 | 要求 |
|:--:|:---|:---|
| 1 | GET 端点 + 稳定路径 | 如 `/api/v1/metrics/oee` |
| 2 | 查询参数 | 支持按业务编码单查（`?equip_code=CNC-01`） |
| 3 | 响应格式 | JSON：裸数组 或 `{data: [...]}` 包装均可（EARP 兼容） |
| 4 | 健康检查 | `/health` 类端点（连接测试用，可选但推荐） |
| 5 | 响应超时 | 约定 ≤30s；超时 EARP 侧兜底，**不假造值** |

## 3. field_mapping 结构（EARP 注册时填写）

EARP 侧注册数据源时提交的映射（存 `import_rules.field_mapping`）：

```json
{
  "name_field": "equip_name",            // 名称 ← 中台列
  "business_code_field": "equip_code",   // 业务编码 ← 中台列（必填）
  "attr_fields": {                       // 属性 ← 中台列（对应实体类型的 attributes）
    "model": "model",
    "install_date": "install_date"
  },
  "relations": [                         // 关系 ← 中台列（值 = 目标实体业务编码）
    { "relation_type": "belongs_to",      "target_field": "line_code" },
    { "relation_type": "manufactured_by", "target_field": "supplier_code" }
  ]
}
```

**关系字段语义**：`target_field` 的值是**目标实体的业务编码**（不是名称）——EARP 同步时
用该编码反查/创建目标实体后建立关系（与 CSV 导入的 facts 引用方式一致）。

## 4. 推荐模板（照抄即用）

### 4.1 synced：设备台账 DM 表

```sql
CREATE TABLE dm_equipment (
    equip_code    VARCHAR(32) PRIMARY KEY,  -- 业务编码 → business_code
    equip_name    VARCHAR(128),             -- 名称 → name
    model         VARCHAR(64),              -- 型号 → attributes.model
    install_date  DATE,                     -- 安装日期 → attributes.install_date
    line_code     VARCHAR(32),              -- 所属产线编码 → belongs_to 关系
    supplier_code VARCHAR(32),              -- 供应商编码 → manufactured_by 关系
    update_time   TIMESTAMP,                -- 更新时间 → 增量同步
    is_deleted    SMALLINT                  -- 软删标记
);
```

对应 field_mapping 见 §3（注册时照抄）。

### 4.2 virtual：指标 API

```
GET /api/v1/metrics/oee?equip_code=CNC-01
→ 200 OK
{
  "code": 0,
  "data": [
    { "equip_code": "CNC-01", "oee": 0.87, "time": "2026-08-19T10:00:00Z" }
  ]
}
```

EARP 侧注册：`entity_type` = 一个 `kind=metric` 的类型（如 `oee`），`source_mode=virtual`，
field_mapping 的 `business_code_field` 指向 `equip_code`。

### 4.3 关系与目标实体

关系列（如 `supplier_code`）引用的目标实体（`supplier`）可以是：
- 同一批导入（同表内另一行 / 另一张已注册的表）
- 已存在于 EARP（手工建/CSV 导入/上次同步）
- 不存在 → EARP 按该编码自动创建目标实体（名称=编码，来源标记 import）

## 5. 校验规则（注册/同步时 EARP 自动执行）

| # | 校验 | 失败行为 |
|:--:|:---|:---|
| 1 | 映射字段存在性（name/business_code/attr 列在数据源中存在） | 注册 400，逐项报错 |
| 2 | `business_code` 非空且行内唯一 | 该行跳过，记入错误列表 |
| 3 | 属性值类型合法（对照实体类型 attributes 定义） | 该行跳过 |
| 4 | 关系方向合法（relation_type 的源类型 = 当前实体类型） | 该行跳过 |
| 5 | 重复同步幂等（同 business_code 二次同步 → 合并更新不重复插行） | 正常行为，非错误 |
| 6 | 取数失败（超时/HTTP 错误/连接失败） | 整个同步失败，状态标记 failed，不半途写库 |

> 校验可先 dry-run（只验不写），与 CSV 导入的 dry_run 模式一致。

## 6. 对接流程（中台侧视角）

```
1. 中台按 §2 最小契约准备表/API（推荐按 §4 模板）
2. 提供数据字典：表/接口文档 + 字段说明（列名、类型、含义）
3. EARP 注册 connector（连接配置：URL/认证/超时）→ 注册数据源（entity_type + field_mapping）
4. EARP dry-run 校验（§5）→ 通过后正式同步
5. synced：定时/手动触发同步（business_code 幂等）；virtual：查询时实时取数
6. 数据变更通知 EARP（可选）：中台更新后 EARP 触发一轮同步即可刷新
```

---

**版本记录**：v1.0（2026-08-19，M3 讨论定稿；field_mapping 结构与 `import_rules` schema 同源）
