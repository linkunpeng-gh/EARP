# PRD-2026-023 v1.0

## M3 — Reasoning 最小版

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-023 |
| **Feature** | Rule Intent Planner + Simple Task Planner + LLMConnector 接口定稿 + Plan Validation |
| **里程碑** | M3（依赖 M1 invoke 链 + M2 PolicyLayer 鉴权） |
| **上游设计** | L1/architecture-v6.md §8（推理管道）；LLMConnector 五挂点（langchain §2.4） |
| **PRD 链** | ← PRD-2026-022(M2) ← PRD-2026-021(M1) |

---

## 1. 范围表

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | Planner | Rule Intent Planner：Business Dictionary 精确匹配，intent="query users" → 查 dictionary → 构造 Step |
| 2 | Planner | Simple Task Planner：单步 Plan（1 Step）或顺序 Plan（Steps[]，M1 invoke 单步执行） |
| 3 | Planner | Plan Validation：Schema 校验（Step 必填 capability_id+input）、权限校验（PolicyCenter 参与）、深度限制（max_depth=5 硬上限） |
| 4 | Connector | LLMConnector 接口定稿——五挂点一次定义：rate_limiter / cache / bind_tools / with_structured_output / 流式开关。M3 仅实现 rate_limiter（Redis 已有）和 structured_output 约束 Plan schema；其余挂点留 Phase 2/3 |
| 5 | Connector | Plan 产出用 Pydantic schema 约束（`Plan = list[Step]`），LLM 返回非法 JSON → ERR-PL-VALIDATION-001 |
| 6 | Connector | LLM 不可用降级路径：Rule Planner 兜底（Business Dictionary 匹配 + template Step） |

---

## 2. US

| US | 描述 | 类型 |
|:--:|:-----|:----:|
| US-01 | 用户发送 intent="query users" → Rule Planner 查 Business Dictionary → 匹配到 capability → 构造 Plan(1 Step) → invoke 执行 | 正常 |
| US-02 | 用户发送 intent 不在 Dictionary → 规则匹配失败 → `intent_not_found` error + audit | 错误 |
| US-03 | Simple Task Planner 接收 Prompt → 构造顺序 Plan（Step[]，当前 M1 单步执行第一步） | 正常 |
| US-04 | Plan 产出含非法字段（无 capability_id）→ Plan Validation 拒绝 → ERR-PL-VALIDATION-001 + audit | 校验 |
| US-05 | Plan 深度超过 max_depth=5 → Plan Validation 拒绝 | 深度 |
| US-06 | LLMConnector.plan(prompt) → 调用 LLM → 解析 Pydantic Plan → 校验 → 返回 Plan | 正常 |

---

## 3. AC

| AC | 内容 | 验证方式 |
|:--:|:-----|:--------|
| AC-01 | Rule Planner: "query users" → 匹配规则 → Plan 含 1 Step(capability_id) | pytest |
| AC-02 | Rule Planner: unknown intent → error response | pytest |
| AC-03 | Simple Task Planner: prompt → Plan(Steps[]) | pytest |
| AC-04 | Plan Validation: 缺少 capability_id → reject | pytest |
| AC-05 | Plan depth > 5 → reject | pytest |
| AC-06 | LLMConnector.plan() 返回合法 Plan schema | pytest |

---

## 4. 对齐检查

| 规范 | 关键条款 | 对齐 |
|:-----|:---------|:----:|
| L1 §8 | 推理管道：Intent→Plan→Validate→Execute | ✅ |
| L1 §8.2 | ERR-PL-VALIDATION-001 | ✅ |
| L1 §8.5 | LLM 不可用降级路径 | ✅ |
| Capability v1.4 | required_permissions | ✅ (M2 已落地) |
| M1 StepRunner | invoke(Step) 接口 | ✅ (产出 Plan=Step[]) |

---

## 5. Gate 检查

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确（M1 invoke 链 + M2 PolicyLayer） | ✅ |
| 2 | AC 可测试 | ✅ 6 条 |
| 3 | M0/M1/M2 遗留 0 | ✅ |
| 4 | 与冻结规范无矛盾 | ✅ |
