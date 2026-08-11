# Chat 智能体设计评审 — r2 复核

- 日期: 2026-08-11
- 对象: `arch/design/2026-08-11-chat-agent-design.md`（v2，r1 后修订）
- r1 报告: `arch/reviews/2026-08-11-chat-agent-design-review.md`（8.0/10，12 项问题：1 P0 + 3 P1 + 8 P2）
- 结论: **通过（可进入实施）** —— r1 12/12 全部闭环；r2 新发现 2 个 P2 细节，实施中顺手落实即可

## r1 问题逐项复核（12/12 RESOLVED）

| # | 问题 | r1 级别 | 修订位置 | 状态 |
|---|------|:---:|---------|:---:|
| I2 | migration 编号 0013 已占用 | P0 | §4.1 标题改为 **0014**，注明被 kb_summary_text 占用 | ✅ RESOLVED |
| CP1 | conversations 无 chat_app_id 归属 | P1 | §4.1 加 `ALTER TABLE conversations ADD COLUMN chat_app_id`（NULL, FK→chat_apps）；§4.3 ② 新建会话写入归属；§6/§10.2 标注一期就位、二期直接可用 | ✅ RESOLVED |
| CP2 | 系统默认模型解析链未定义 | P1 | §4.4 三级解析链：`chat_apps.model_config_id → system_model_settings(llm)（PRD-031 Layer 3）→ env` | ✅ RESOLVED |
| I1 | 元数据问题评估 vs 链路无 metadata_filters | P1 | §8.2 明确口径：一期不暴露 metadata_filters 配置（文档管理层属性过滤）；「2024 年的报销标准」按**纯语义命中**验收（期望文档在 citations 即可）；d.metadata 随 chunk 返回供引用展示 | ✅ RESOLVED |
| CP3 | 引用编号规则未定义 | P2 | §4.3 新增编号规则：检索结果按 `[1]..[N]` 编号（与返回顺序一致），citations 数组顺序 = 编号顺序（citations[0] ↔ [1]），写死在结构尾巴 | ✅ RESOLVED |
| CP4 | 单事务与流式长连接冲突 | P2 | §4.3 标题改「单编排：无独立外部 API 调用，非 DB 长事务」；③ 用户消息先 commit（SSE 前可见）、⑧ done 后 commit | ✅ RESOLVED |
| CP5 | retrieval 无默认值 | P2 | §4.1 `DEFAULT '{"mode": "hybrid", "top_k": 5, "threshold": 0.0}'`（标注 CP5） | ✅ RESOLVED |
| S1 | 多轮历史 role 交替风险 | P2 | §4.3 ④ 按 (user, assistant) 配对取最近 N 对，孤立 user 消息跳过 | ✅ RESOLVED |
| F1 | apps.html 实为新建非升级 | P2 | §5.3 改「新建页」，注明 nav.js 现指向 planned.html?section=apps | ✅ RESOLVED |
| F2 | 审计事件类型/订阅未指定 | P2 | §4.6 明确类型 `earp.chat_app.created/updated/deleted/published` + 增加订阅（见下方 N2 位置修正） | ✅ RESOLVED |
| Q1 | GET /conversations 未标新端点 | P2 | §4.2 标注「新增端点（Q1）」，响应补 chat_app_id | ✅ RESOLVED |
| Q2 | conversations.html 承接关系未点明 | P2 | §4.2 注释说明 GET /conversations 是对话日志（现静态页）第一真实数据源，UI 升级留二期；§10.3 开放项同步 | ✅ RESOLVED |

## r2 新发现（2 个 P2，实施中落实）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| N1 | `conversations.chat_app_id` FK 未定 ON DELETE 行为：chat_apps 是**硬删**（§4.2），默认 NO ACTION 会阻止删除有会话的 app（§8.1「删除」用例会踩到） | 中（删除路径阻塞） | `REFERENCES chat_apps(chat_app_id) ON DELETE SET NULL`（保留对话日志）；或明确「有会话的 app 禁止删除」并返回 409 |
| N2 | §4.6「main.py 增加 earp.chat_app.* 订阅」位置不实：审计订阅实际在 **entrypoints/audit.py:32**（`bus.subscribe("earp.execution.*", audit_handler_factory(engine))`），RedisStreamsEventBus.subscribe 转发 fallback、consumer 循环在 audit 进程 | 低（表述错，实施会自然找对） | 改文案为「entrypoints/audit.py 增加 earp.chat_app.* 订阅（audit handler 通用，写 audit_logs）」 |

**可选 N3（P3）**：kb_scope 绑定 KB 的存在性/租户校验未提——绑定不存在的 kb_id 检索为空（静默）。一期可接受，无需处理。

## 评分更新

| 维度 | r1 | r2 |
|------|:---:|:---:|
| 一致性 | 8/10 | 9.5/10 |
| 完整性 | 7/10 | 9/10 |
| 合理性 | 8/10 | 9/10 |
| 可行性&演进性 | 8/10 | 9/10 |
| 规范质量 | 8/10 | 9/10 |
| 评审延续性 | 9/10 | 10/10 |
| **总分** | **8.0/10** | **9.2/10** |

## 总体结论

**通过。** r1 全部 12 项问题（含 P0 事实错误与 3 个 P1 决策缺口）均已闭环且修订质量高——每处修改都标注了对应评审编号（CP1/CP2/CP3/CP4/CP5/S1/F1/F2/Q1/Q2），可追溯性符合仓库惯例。剩余 2 个 P2 为实施细节（FK 删除行为、订阅文件位置），不阻塞开工。建议实施时：① migration 中 chat_app_id 加 ON DELETE SET NULL；② audit 订阅加在 entrypoints/audit.py；③ §8.1 补一条「chat_app_id 归属写入 + 删除含会话 app」用例。
