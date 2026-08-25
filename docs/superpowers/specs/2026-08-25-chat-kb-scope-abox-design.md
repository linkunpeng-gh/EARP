# Chat/Flow 智能体绑定知识库时 ABox（实体/图谱）照常生效 — 设计

日期：2026-08-25
状态：已批准（方案 1：复用三层检索 `knowledge_search`，kb_scope 只约束文档层）

## 背景与问题

chat 智能体（auto 模式）配置「知识库绑定」（`kb_scope`）后，问答只走纯文档检索
（`search_chunks`），实体档案/图谱（ABox：profile/graph/capability）被整体跳过：

```python
# conversation/chat_service.py::_retrieve（现状）
kb_scope = app.get("kb_scope") or []
if kb_scope:
    chunks = await search_chunks(...)   # ← 只查 KB 文档，不碰 ABox
else:
    # 走 planner（understand → execute_plan）→ 才有 profile/graph（ABox）
```

代码注释即现状设计：*"kb_scope 非空 → 限定 KB（search_chunks，一期不接 planner）"*。

**实况复现**（本地库 tenant-demo，agent `设备维护` app-757243ba49e4，绑 3 个 KB）：

| 场景 | 「主变压器的供应商是谁？」citations |
|---|---|
| 绑定 3 个 KB（现状） | 仅 5 条文档 chunk（交接班制度.md 等），无 ABox |
| 清空绑定 | 3 条图谱事实：manufactured_by → 特变电工、maintained_by → 李维修、located_in → 阳光光伏发电厂 |

flow 模式 Knowledge 节点（`connector._execute_knowledge_search`）绑定 `kb_ids` 时同款问题。

## 目标（行为变更）

- **chat 智能体（auto）绑定 kb_scope 后**：文档（chunk）检索仍严格限定在绑定 KB；
  **实体档案/图谱（profile/graph，ABox）按角色域权限照常生效**，不再被整体禁用。
- **flow Knowledge 节点绑定 kb_ids 后**：同款行为，两条链路一致。

权限模型不变：profile/graph 由角色 `data_domain_access` 门禁（`_role_scope_domains`），
绑定 KB 不改变实体层权限；chunk 层仍叠加角色域过滤。

## 实现

### 1. `conversation/chat_service.py::_retrieve`（kb_scope 分支）

`search_chunks(...)` 替换为 `knowledge_search(...)`（三层检索）：

```python
from earp_server.ontology.search import knowledge_search  # 函数内 import

chunks = await knowledge_search(
    engine, tenant_id, query,
    embedding=q_emb, role_id=role_id,
    knowledge_base_ids=kb_scope,   # L3 chunk 层限定绑定 KB
    top_k=top_k, embedding_dim=embedding_dim,
    query_text=query, mode=mode, threshold=threshold,
    eventbus=None,
)
```

- L1/L2（profile/graph = ABox）由角色域权限决定，与 kb_scope 无关（方案 A 语义）。
- L3（chunk）限定在绑定 KB（`knowledge_base_ids`），行为与现状一致。
- 现有 citations 转换循环已支持 profile/graph 源，展示层零改动。
- 更新 `_retrieve` docstring（去掉「一期不接 planner」表述，改为三层语义）。

import-linter 已存在 ignore：`earp_server.conversation.chat_service -> earp_server.ontology.search`。

### 2. `connector.py::_execute_knowledge_search`（flow Knowledge 节点）

`search_chunks(...)` 替换为 `knowledge_search(...)`：

```python
chunks = await knowledge_search(
    self._engine, ctx.tenant_id, query,
    embedding=q_emb, role_id=ctx.role_id,
    knowledge_base_ids=input_.get("kb_ids"),
    data_domain_ids=input_.get("data_domain_ids"),
    top_k=max(1, min(20, int(input_.get("top_k", 5) or 5))),
    query_text=query,
)
```

citations 组装支持三源（与 chat_service 对齐）：

```python
src = c.get("source")
if src == "profile":
    citations.append({"source": "profile", "entity_id": c.get("entity_id"),
                      "title": c.get("title")})
elif src == "graph":
    citations.append({"source": "graph", "entity_id": c.get("entity_id"),
                      "title": c.get("title")})
else:
    citations.append({"chunk_id": ..., "document_id": ..., "title": ..., "content": ...})
```

### 3. `pyproject.toml` import-linter

新增 ignore（带注释说明）：

```
# flow Knowledge 节点与 chat 检索同源——复用 ontology 三层检索（ABox 层）
"earp_server.connector -> earp_server.ontology.search",
```

### 4. `apps/earp-admin/pages/chat-edit.html`（文案）

知识库绑定 tooltip 补一句：绑定仅限定文档检索范围，实体/图谱（ABox）按角色权限仍生效。

## 测试

- `test_chat_kb_scope_limits_search`：断言改为「有 kb_id 的 citations 全部在绑定 KB 内」
  （允许出现无 kb_id 的 profile/graph 源）。
- 新增 `test_chat_kb_scope_keeps_abox`：绑定 KB（kb-alarm，equipment_data 域）+ 实体问题
  （CNC-01 供应商）→ citations 含 profile 或 graph 源。
- `test_flow_executor.py::TestConnector::test_knowledge_search`：mock 层改为
  `ontology.search.knowledge_search`；断言三源 citations 形状（含 source）。
- 回归：`test_chat.py` / `test_flow_executor.py` / `test_ontology_search.py` / import-linter。

## 验证

本地真实库复现脚本：绑定 agent 问「主变压器的供应商是谁」→ citations 出现 graph 源
（与未绑定时一致），chunk 仍限绑定 KB。

## 明确不做（YAGNI）

- 不改 `/knowledge/search` 端点的显式 scope 语义（调试面，文档声明 chunk-only）。
- 不做绑定场景的 intent planner / capability 聚合（方案 2 内容，后续单独立项）。
- 不改 copilot 链路。
