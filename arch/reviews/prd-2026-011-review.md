Permission allow rule (.claude/settings.local.json): Write(/Users/linkunpeng/work/adp2/**) is not matched by file permission checks — only Edit(path) rules are. Use Edit(/Users/linkunpeng/work/adp2/**) instead (Edit rules cover all file-editing tools).
## PRD-2026-011 审查报告

### P0（阻塞合并）

**1. 六大数据域划分与企业架构不对齐**
声明的六域为 Runtime / Capability / Governance / Workspace / Security / LLM，但 `enterprise-architecture.md` 中还存在独立的 **Knowledge**（KnowledgeBase、Document、Chunk，pgvector 承载）、**Conversation**（Conversation、Message、MessageAttachment）、**Integration**（Connector 配置、Adapter 健康状态）三个含数据实体的域。缺失会导致 ER 图不完整，数据架构视图与企业架构脱节。

**2. "LLM 数据域" 分类错误**
LLM 是能力类型而非数据域。LLM 相关数据（Prompt、Response、Token 用量）本质上是 Execution / CapabilityCall 的载荷数据 + 审计日志的横切关注点，不应独立成域。建议将 "LLM" 替换为 **Knowledge（向量/知识库）** 或 **Observability（指标/日志/链路）**，LLM 数据作为审计与运行时的横切主题处理。

---

### P1（合并前应修复）

**3. AC-01 "Audit ↔ 各域的关系" 边界模糊**
未定义 "关系" 的含义——是外键引用？事件订阅？数据流？按当前措辞，画一条无标注的连线即可满足 AC，无法保证审查质量。应明确最少的预期关系类型（至少：Audit 引用各域实体的 `entity_type + entity_id`；Audit 订阅各域事件总线的 `event_type`）。

**4. AC-04 "每类数据" 缺少对齐锚点**
没有定义数据分类清单。应显式引用已有规范中的 TTL/保留策略——
- Audit Spec v1.1: LLM Prompt+Response 保留 30 天
- Deployment Architecture v1: Prometheus 指标保留 30 天、WAL 保留 7 天、快照保留 30 天
- Tenant Spec v1.1: Session/Execution 存储配额

**5. 缺少 EventBus 规范依赖**
`audit-specification-v1.1.md` 明确声明事件类型唯一来源是 EventBus 规范第 3 章注册表。若数据架构涉及事件持久化、事件溯源或审计存储策略，EventBus 应列为依赖或显式排除。

**6. Knowledge/Vector 数据域未处理**
pgvector 出现在存储引擎列表中，企业架构中有完整的 Knowledge 领域实体，但六域中无此域。需明确：是将其归入 Capability 域，还是独立为 Knowledge 域。

---

### P2（可后续优化）

**7. §2.2 "不做" 范围缺少 L1 级关键排除项**
当前只排除了物理调优、向量索引参数、DDL 三类 L3 内容，但未说明以下 L1 级数据架构主题的取舍：数据一致性模型（强一致 vs 最终一致）、事件溯源模式、CQRS 考量。应补充声明。

**8. AC 缺少优先级标注**
六条 AC 平级列出，但 ER 图完整性（AC-01）和存储选型理由（AC-03）显然比迁移策略（AC-06）更基础。建议标注 P0/P1 分级。

**9. 产出物路径未经校验**
`arch/L1/data-architecture-v1.md` —— 需确认该路径不与现有文件冲突，且目录 `arch/L1/` 下已有两个文件，命名约定一致。

**10. 缺少变更记录**
v1.0 应有 Changelog 节，记录创建日期、作者、初版内容摘要。
