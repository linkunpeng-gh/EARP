Permission allow rule (.claude/settings.local.json): Write(/Users/linkunpeng/work/adp2/**) is not matched by file permission checks — only Edit(path) rules are. Use Edit(/Users/linkunpeng/work/adp2/**) instead (Edit rules cover all file-editing tools).
## 审查结论：无 P0 问题

**AC-01 ✅** ER 图覆盖完整：Tenant→Session→Execution→CapabilityCall 主链路、Capability↔Connector（通过 ConnectorBinding）、Policy↔Capability（PolicyBinding）、Audit 通过 `entity_type+entity_id` 引用各域实体——引用方式在 ER 图注释和 2.2 关系表中均已标注。

**AC-02 ✅** 八大域每域的 (a) 核心实体、(b) 存储引擎、(c) 关键索引策略，在 1.1 表格中逐域列出。

**AC-03 ✅** 3.1 给出了每个引擎 vs 替代方案的理由（PG vs MySQL、pgvector vs Milvus/Qdrant、Redis vs KeyDB、Prometheus vs InfluxDB 等），3.2 补充了排除多模型数据库的理由。

**AC-04 ✅** 4.1 生命周期表逐条对齐已有规范：LLM 30d 对齐 Audit Spec §LLM、Prometheus/WAL/快照对齐 Deployment Arch §4.3、Session 对齐 Tenant Spec 存储配额。

**AC-05 ✅** 第五章逐存储列出隔离方式，并引用 Tenant Spec 对应章节。

**AC-06 ✅** 第六章覆盖 Alembic 版本管理、多环境同步流程、大表迁移策略。

---

**小建议（非 P0）**：Security 域存储引擎写的是 `PostgreSQL (密文) + Vault`，但第三章存储选型分析中没有覆盖 Vault（如 HashiCorp Vault）的选型理由和替代方案对比。如果 Vault 定位为外部密钥管理服务而非存储引擎，建议在 3.1 中补充一句说明，或在 Security 域表格中加注。
