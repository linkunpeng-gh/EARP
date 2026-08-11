# 路由评估集（Routing Evaluation Set）

> 企业级精准召回验收基线（arch/design/2026-08-09-enterprise-retrieval-design.md §7）。
> 格式：`| # | query | 期望 DD | 期望 KB | 备注 |`
> CI（test_routing.py）用字符 bigram 伪向量验证**机制**（期望 DD ∈ 候选 top-N）；
> dev 用 `scripts/verify_routing.py` + 真实 bge-m3 验证**语义准确率**（≥90%）。

| # | query | 期望 DD | 期望 KB | 备注 |
|---|---|---|---|---|
| 1 | 报销制度是什么 | finance_data | 费用报销流程手册 | 语义路由（DD 描述向量） |
| 2 | 2024 年的报销标准 | finance_data | 费用报销流程手册 | 元数据过滤（year=2024） |
| 3 | 设备报警阈值是多少 | equipment_data | 报警阈值配置 | 语义路由 |
| 4 | 员工休假政策 | hr_data | 公司政策 | 语义路由 |
| 5 | 主轴轴承更换周期 | equipment_data | 设备手册 | 三层检索（DD→KB→chunk） |

## 验收指标

- 路由准确率（期望 DD ∈ 候选 top-N）≥ 90%
- 召回 P@5 不低于现有基线（vector 全库搜索）
