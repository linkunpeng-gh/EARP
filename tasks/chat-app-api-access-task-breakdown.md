# 任务清单 — Chat 应用对外 API 服务（Dify API Access 对标）

**状态：规划定稿，待开工**
**依据**：`arch/tech-debt.md` #18（2026-08-24 评估记录，含最小闭环预案）+ C 系列交付（可见范围前置就绪）+ Dify API Access 功能对照
**依赖**：C 系列 ✅（access_mode+app_role_access 可见范围已交付，migration 0032）+ 发布状态机 ✅ + audit 管线 ✅ + api_keys/service_accounts 表 ✅（0001 已建未用）
**日期**：2026-08-25

## 目标

1. **应用对外服务**：chat / chatflow 应用发布后，外部系统（企业微信/钉钉/网页/业务系统）可用 **API 密钥**调用——`Bearer app-<key>` 鉴权，非用户 JWT
2. **密钥管理**：应用详情「API 访问」页签——生成/吊销密钥（多把、生产/测试隔离）、明文仅显示一次、last_used_at 追踪
3. **复用现成链路**：`POST /api/v1/chat-apps/{id}/chat` 复用 flow_chat（flow）/ chat_sse（auto）——SSE/阻塞/挂起 202 语义与内部一致
4. **约束与审计**：仅已发布应用可开放；`earp.api.*` 审计事件（app_id/key_id/耗时/状态）；access_mode 可见范围语义衔接
5. 零回归：内部 JWT 路径零改动；verify_f6 80 绿

## 现状（已核实，2026-08-25）

- **api_keys 表**（0001 已建、0 行、无代码引用）：`api_key_id / tenant_id / name / key_hash / status(active) / created_at / last_used_at`——**缺 chat_app_id 列**（需 migration 0033 加 + 外键/索引）
- **service_accounts 表**（0001 已建、0 行）：`service_account_id / tenant_id / name / api_key_id / created_at`——可作服务账号语义（一期可不用，密钥即代表应用调用）
- **gateway**：`JWTMiddleware.dispatch` 全量 JWT——`Authorization: Bearer <token>` 走 `_decode`（HS256/RS256）失败即 401；**`Bearer app-xxx` 目前会走 JWT 解码失败 401**（API key 分支插入点清晰：token 以 `app-` 前缀走查表）
- **可见范围（C 系列已交付）**：`chat_apps.access_mode ∈ {open, restricted}` + `app_role_access` 授权行表（`access_mode='restricted'` 时按角色白名单过滤 GET /chat_apps 与对话查询）——**API 开放可衔接「已发布 + access_mode」语义**
- **发布状态机**：publish_chat_app（flow 模式重校验 flow_schema）——published 才可对外
- **chat 端点**：`POST /chat_apps/{id}/chat`（auto→SSE / flow→JSON，human_approval 挂起 202）现成；`flow_chat` / `chat_sse` 可直接复用
- **审计**：in-process EventBus → audit handler 落 audit_logs（earp.* 模式订阅现成）
- 最新 migration **0032_conversation_context**；下一次从 **0033** 起

## 既定决策（开工前置确认）

| # | 决策点 | 倾向方案 |
|:-:|:---|:---|
| D1 | 密钥形态 | `app-` 前缀 + 随机 32 位（`app-<hex>`）；**明文只显示一次**；落库 `key_hash = sha256(明文)`；多把密钥（每把独立 name/status/last_used_at），可吊销（status=revoked） |
| D2 | 鉴权分支 | gateway：`Bearer` token 以 `app-` 开头 → 走 **API key 查表**（tenant + key_hash 匹配 + status=active）→ 注入 `request.state.{tenant_id, chat_app_id, api_key_id}`；非 `app-` 前缀 → 原 JWT 路径。**JWT 路径零改动** |
| D3 | 端点 | `POST /api/v1/chat-apps/{chat_app_id}/chat`（body 同现 `/chat_apps/{id}/chat`：query/conversation_id）——内部转调 flow_chat/chat_sse；**仅已发布（status=published）应用可被密钥调用**（未发布 → 404/403） |
| D4 | 密钥绑定 | api_keys 增 `chat_app_id`——**密钥即授权**（一把密钥绑一个应用，不叠加角色白名单判断；access_mode 仍约束平台内可见性，API 层只看密钥+发布状态，简化一期语义） |
| D5 | 身份 | 服务调用无 user/role——flow 执行注入 `user_id=service:api:<key_id>`、`role_id` 取应用创建者角色或空（**命令审批仍生效**——API 调用遇 human_approval 挂起 202 语义不变，恢复依赖 conversation_id 续调） |
| D6 | 审计 | `earp.api.{chat.started,chat.completed,chat.failed}`（app_id/key_id/tenant/耗时/状态码）；复用 audit 管线 + api_keys.last_used_at 更新 |
| D7 | 边界 | 一期**不做**：SDK 包、webhook/消息平台绑定（企业微信/钉钉等接入层）、inputs 应用变量注入、密钥轮换/过期策略、按密钥限流（TokenBucket 可后接）——Dify 对比中这些是接入层/增值项 |
| D8 | 测试策略 | gateway 密钥分支单测（app-key 放行/JWT 不受影响/吊销 401/未发布 404）+ 端点集成（auto SSE / flow 挂起 202→恢复）+ verify_f6 回归 |

## Task 拆解（建议执行序 1 → 2 → 3 → 4 → 5）

### Task 1 — migration 0033 api_keys 扩展 + 密钥 service（0.5-1 天）
**文件**：`migrations/versions/0033_api_keys_chat_app.py`（新）、`src/earp_server/gateway/api_keys.py`（新，或并入现有 service）
- `api_keys` 增 `chat_app_id VARCHAR(64)` + 索引（tenant, chat_app_id）；显式 GRANT；`test_migrations`/`test_rls` 更新
- 密钥 service：`create_api_key(tenant, chat_app_id, name) → {plaintext}`（明文仅返回一次）、`revoke_api_key`、`verify_api_key(tenant, key) → {chat_app_id, api_key_id}`（sha256 比对 + status 检查 + last_used_at 更新）
- 验证：生成/吊销/校验单测 + 明文不可复得（仅 key_hash 落库）

### Task 2 — gateway 密钥鉴权分支（0.5 天）
**文件**：`src/earp_server/gateway/auth.py`
- `JWTMiddleware.dispatch`：token 以 `app-` 开头 → `verify_api_key` → 注入 `request.state.{tenant_id, chat_app_id, api_key_id}`（`user_id=service:api:<key_id>`）；失败 401；非 `app-` → 原路径
- `/api/v1/` 前缀端点（API 面）与内部端点在 middleware 上无差异（同一分支按 token 前缀判定）
- 验证：app-key 放行注入 / 吊销 401 / 非法前缀回 JWT 路径 / JWT 零回归

### Task 3 — API 端点 + 复用执行链路（1 天）
**文件**：`src/earp_server/main.py`（/api/v1 路由）、`src/earp_server/conversation/chat_service.py`（如需薄封装）
- `POST /api/v1/chat-apps/{chat_app_id}/chat`：校验密钥绑定 == 路径 app + 应用已发布 → 转调 flow_chat（orchestration=flow）/ chat_sse（auto）——响应语义与内部一致（SSE / JSON / 挂起 202）
- 未发布 → 404（不暴露存在性）；密钥与应用不匹配 → 403
- 验证：auto SSE 流、flow 全链、挂起 202→恢复（conversation_id 续调）、未发布 404

### Task 4 — 审计 + last_used_at（0.5 天）
**文件**：`src/earp_server/gateway/api_keys.py`、`src/earp_server/main.py`、`src/earp_server/audit/`
- `earp.api.*` 事件（含 execution_id 关联）；audit handler 订阅 `earp.api.*`
- `verify_api_key` 更新 last_used_at（或端点完成时更新，防热路径写放大——倾向端点完成时）
- 验证：审计单测 + 集成（API 调用后能查到事件 + last_used_at 已更新）

### Task 5 — 前端「API 访问」页签 + FDE 指南（0.5-1 天）
**文件**：`apps/earp-admin/...`（chat/chatflow 应用详情）、`arch/guides/earp-fde-user-guide.md`、`arch/guides/earp-chatflow-guide.md`
- 应用详情加「API 访问」：创建密钥（明文一次性展示+复制）/吊销/列表（name/状态/最后使用）
- 指南补：curl 调用示例（SSE 流式 + 阻塞 + flow 挂起 202 两步）+ 「仅已发布应用可开放」+ 生产密钥管理须知
- 验证：前端冒烟 + 指南可照着 curl 通

## 依赖关系

```
Task 1（migration+service）→ Task 2（gateway）→ Task 3（端点）→ Task 4（审计）
Task 5（前端+指南）依赖 1-3 的端点/密钥可用
```

**建议执行序**：`1 → 2 → 3 → 4 → 5`，合计 3-5 天

## 验收标准

1. `POST /api/v1/chat-apps/{id}/chat` 用 `Bearer app-xxx` 可调用 auto（SSE）与 flow（JSON/挂起 202）应用；JWT 内部路径零回归
2. 密钥生成明文仅一次、吊销后 401、未发布应用 404
3. 挂起 202 → conversation_id 续调恢复——**命令审批语义在 API 调用下不变**（D5）
4. `earp.api.*` 审计事件 + last_used_at 更新
5. verify_f6.py 80 绿 + 全量 pytest 绿 + ruff/pyright 零新增 + OpenAPI 同步（新增端点入 openapi.yaml）

## 风险提示

1. **密钥泄露面**：明文仅显示一次——日志/请求体不得回显；key_hash 用 sha256（加盐可选）；吊销即时生效
2. **last_used_at 写放大**：高频调用逐次 UPDATE——倾向端点完成时更新一次/或节流（D4 已定）
3. **命令审批在 API 场景**：挂起 202 依赖外部系统携带 conversation_id 续调——指南要写清两步调用模式
4. **app- 前缀冲突**：若未来引入其他 `app-` token（如微信 appsecret），前缀判定需预留命名空间（D2 判定只认 `app-` + api_keys 命中）
5. **未发布 404 vs 403**：404 不暴露存在性（对齐 capability 详情先例）；密钥绑定不匹配 403

---
**规划定稿，确认后开工。**
