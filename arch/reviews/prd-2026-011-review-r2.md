Permission allow rule (.claude/settings.local.json): Write(/Users/linkunpeng/work/adp2/**) is not matched by file permission checks — only Edit(path) rules are. Use Edit(/Users/linkunpeng/work/adp2/**) instead (Edit rules cover all file-editing tools).
## PRD-2026-011 v1.1 快速复查

**P0 剩余：无。** P0-1/P0-2 已修复，八大域（Runtime/Capability/Governance/Workspace/Security/Knowledge/Conversation/Integration）覆盖完整。三个 P0 AC 范围合理，无新增 P0 缺口。

**一个值得注意的遗漏：** 数据架构文档缺少备份/容灾策略——只覆盖了 TTL/归档生命周期（AC-04），未提及 PostgreSQL/S3 等存储的备份方案和 RPO/RTO 目标。这通常属于 L1 数据视图的基础关切。

**P1 计数：6 个** — 验收条件 3 个（AC-04/05/06），修复记录 4 个（P1-3/4/5/6），但 P1-3 实质已合并进 AC-01 的修复。

**小瑕疵：** 修复记录编号从 P2-7 跳到 P2-8 再到 P2-10，缺少 P2-9（编号跳跃，无功能影响）。
