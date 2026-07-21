 # PRD-2026-028 评审报告：Web Admin Dashboard

 **评审对象**: `prd/PRD-2026-028-admin-dashboard.md` v1.0
 **评审日期**: 2026-07-21
 **评审人**: Codex
 **基线依据**: `apps/earp-server/src/earp_server/main.py`（实际 API 端点）、各 domain service 实现

 ---

 ## 一、评审总评

 PRD 范围克制、定位清晰，Jinja2+htmx 选型务实。发现 **1 个 P0**（阻塞）、**7 个 P1**（应修后合）、**6 个 P2**（建议改进）。核心问题：Sessions 页面引用了不存在的列表端点、缺少 CSRF 保护、Admin 认证机制未定义、遗漏了 Knowledge/Conversation 等已有 API 的管理页面、Dashboard 计数查询绕过租户隔离。

 ---

 ## 二、P0 — 阻塞性问题（1 项）

 ### P0-1：Sessions 页面引用的列表端点 `GET /v1/sessions/{id}` 不能用于列表展示

 **问题**
 页面清单 #2 Sessions 页标注数据来源为 `GET /v1/sessions/{id}` → 列表+详情。但该端点接收的是单个 `session_id` 路径参数，返回单个 SessionResponse。后端 **不存在** `GET /v1/sessions` 列表端点，`session_service.py` 中也 **没有** `list_sessions()` / `get_all_sessions()` 方法。Sessions 列表页无法实现。

 **影响**
 Sessions 是整个 dashboard 的核心页面之一。无列表端点意味着该页面从第一行代码就无法工作。

 **修复建议**
 1）PRD 页面清单 #2 数据来源改为 "新增 GET /v1/sessions"（列出新建端点），并在 §4 API 映射中新增一行。
 2）实现 `session_service.list_sessions(engine, tenant_id, limit, offset)` → 带分页。
 3）`main.py` 新增 `@app.get("/v1/sessions")` 端点，按 `tenant_id` 过滤（复刻现有 RLS 模式）。

 ---

 ## 三、P1 — 重要问题（7 项）

 ### P1-1：缺少 Knowledge Base Management 页面

 **问题**
 M4 已实现完整知识库 API 栈（`POST /knowledge/documents`、`POST /knowledge/search`、`chunk_service`、`document_service`、`embedding_service`），但 PRD 页面清单未包含知识库管理入口。Admin 用户无法查看已索引的文档、执行搜索测试、删除文档或查看 chunk 状态。

 **修复建议**
 新增页面 #8 Knowledge Base：`/admin/knowledge`，数据来源 `GET /v1/knowledge/documents`（需新增列表端点）和 `POST /knowledge/search`（已有）。至少提供：文档列表、搜索测试框、文档删除操作。

 ### P1-2：缺少 Conversation Management 页面

 **问题**
 后端已有完整对话 API（`POST /conversations`、`POST /conversations/{id}/messages`、`GET /conversations/{id}/messages`），但 PRD 未设计对应的管理页面。Admin 无法查看或检查对话历史。

 **修复建议**
 新增页面 #9 Conversations：`/admin/conversations`，数据来源 `GET /v1/conversations`（需新增列表端点）。至少提供：对话列表、消息时序浏览。

 ### P1-3：Dashboard Home 直查 count(*) 绕过租户隔离

 **问题**
 PRD §4 API 映射标注 Dashboard "engine 直查 count(*)"。由于 EARP 多租户架构通过 RLS + JWT tenant_id 隔离数据，直接 `SELECT count(*) FROM sessions` 将返回 **所有租户** 的数据，导致跨租户信息泄露。即使绕过中间件直查，也必须按 `tenant_id` 过滤。

 **修复建议**
 不要直查数据库。改为新增 `GET /v1/stats` 端点（或 `GET /admin/api/stats`），统一走中间件栈获取 `tenant_id`。或者确保直查 SQL 中显式附加 `WHERE tenant_id = :tid`。

 ### P1-4：缺少 CSRF 保护

 **问题**
 PRD 非功能需求未提及 CSRF。htmx 通过 `hx-post` 发起 POST 请求修改服务端状态（Plan & Invoke、Streaming、Capabilities 注册），**任何未防护的 POST 端点都可能被跨站请求伪造利用**。FastAPI 原生不内置 CSRF 中间件。

 **修复建议**
 非功能需求 → 安全中增加 CSRF 保护要求。建议方案：FastAPI 集成 `starlette-csrf` 中间件（检查 `X-CSRF-Token` header），或自行实现 `csrf_token` cookie + htmx header 验证模式。注意 `/admin/*` 路由都需要豁免 JWT 后补充 CSRF 防护。

 ### P1-5：Admin 路由认证机制未定义

 **问题**
 非功能需求描述 "admin 路由复用 JWT 中间件（EARP_APP_ENV=dev 时可跳过）"，存在三个未回答的问题：
 1）dev 以外环境（staging/prod）的认证流程是什么？没有 `/admin/login` 页面或 token 获取入口。
 2）JWTMiddleware 当前 `EXEMPT_PATHS = ("/health", "/ready")`，`/admin/*` 不在免检列表中——开发者在 dev 模式下也需要提供有效 token。
 3）admin 用户与 API 调用者是同一个身份体系吗？如果是，admin 登录流程是什么？

 **修复建议**
 PRD §6 安全中明确 admin 认证方案。建议：
 - dev 环境：将 `/admin/*` 加入 `EXEMPT_PATHS`
 - staging/prod：自建 `/admin/login` 表单，通过 username+password 换取 JWT（复用现有 JWTMiddleware 解码逻辑）
 - 或 langfuse 的 iframe 内嵌认证模式同理，admin 不做独立认证

 ### P1-6：Audit 日志新端点命名不一致

 **问题**
 所有现有数据端点都使用 `/v1/*` 前缀（如 `/v1/sessions/{id}`、`/v1/sessions/{id}/invoke`），但 Audit 新增端点计划命名为 `GET /admin/api/audit`。两种命名风格共存会造成不一致，也增加了 future phase 中迁移 /v2 的工作量。

 **修复建议**
 改为 `GET /v1/audit/logs`（restful 风格），admin 模板通过 `hx-get="/v1/audit/logs?event_type=...&page=1"` 调用。实现上复用 audit consumer 或 audit service 中的 DB 查询逻辑。

 ### P1-7：Sessions 页面原型缺少分页和过滤控件

 **问题**
 PRD §5 页面设计中 Sessions 页没有草图或描述。实际使用中 sessions 列表必然需要分页（时间/状态过滤），但 PRD 未讨论任何交互模式。结合 P0-1（无列表端点），该页面的 UX 设计不完整。

 **修复建议**
 在 §5 中补充 Sessions 页草图，至少包含：搜索框（session_id / user_id）、状态过滤（active/closed）、时间范围、分页控件。hx-get 配合 `hx-trigger="change"` 实现实时过滤。

 ---

 ## 四、P2 — 改进建议（6 项）

 ### P2-1：添加 Executions 详情页面

 **建议**
 Dashboard 首页展示了 "Executions: 47" 计数卡片，但没有对应的执行详情页面。对于一个管理面板，查看各次执行的输入/输出/耗时/状态是很自然的需求。

 **可选方案**
 新增 `/admin/executions` 页面，展示最近执行记录，每行可展开查看详情。数据来源需新增 `GET /v1/executions` 端点（已有 `executions` 表）。

 ### P2-2：添加 Policies / Tenants 管理页面（Phase 2 可考虑）

 **建议**
 `policy_service.py` 和 `tenant_service.py` 提供了 policies 和 tenant_account_joins 的 CRUD 能力。若 dashboard 的目标是"让平台从能用变成可用"，那么 admin 不能直接管理策略和租户会是一个明显的缺口。建议 Phase 2 补充，当前记入 backlog。

 ### P2-3："内联CSS" 表述应明确

 **建议**
 "内联CSS" 有歧义。若指 `<style>` 块（每个模板一个 CSS block），是合理的起步方案；若指 `style="..."` HTML 属性内联，将导致维护噩梦。建议将 §2 表格中的 "内联 CSS (system font stack)" 改为 "独立 `<style>` 块（无额外构建工具链，system font stack）"。

 ### P2-4：建议引入极简 CSS 框架改善视觉效果

 **建议**
 纯内联 CSS 在没有设计师的单人项目中很快会变成"凑合能用但难看"。引入如 [Pico.css](https://picocss.com) 或 [Simple.css](https://simplecss.org) 等无 JS、单文件、~10KB 的框架，一次性导入即可获得一致的表格/表单/按钮样式。不增加 npm/tailwind 依赖链。

 ### P2-5：语言/编译工具没有指定

 **建议**
 PRD 未提及 Jinja2 模板的目录位置和 FastAPI 集成方式。建议在 §2 中说明在 `apps/earp-server/` 下新增 `templates/` 和 `static/` 目录，以及如何集成到 FastAPI app（`Jinja2Templates` + `StaticFiles` mount）。

 ### P2-6：Audit Logs 页面需要分页和性能关注

 **建议**
 Audit logs 是典型的增长型数据表，不设分页会导致页面越来越慢。htmx 的 infinite scroll 或传统页码模式应当在此页面明确选择。建议 PRD 在 §5 Audit Logs 草图中标出分页区域。

 ---

 ## 五、PASS 项

 | 项目 | 判定 | 说明 |
 |:---|:---:|:---|
 | 定位与范围 | PASS | "pure API → usable" 的定位清晰，7 页范围克制，适合 Phase 0 |
 | 技术栈：Jinja2 | PASS | 与 FastAPI 天然集成，零构建工具链，单人团队最佳选择 |
 | 技术栈：htmx 2.0 | PASS | htmx 的 hx-get/hx-post/hx-target/hx-swap 四属性覆盖 admin CRUD 全部需求，学习曲线低 |
 | 无前端测试策略 | PASS | Phase 3 人工验收 + curl 脚本覆盖关键路径，对 7 页应用足够 |
 | Langfuse 内嵌设计 | PASS | iframe 内嵌 Langfuse 是零开发成本的 observability 集成方式 |
 | Streaming 页面 | PASS | 与已有 `POST /stream/invoke` SSE 端点完全对齐，是一个实用的测试工具 |
 | Capabilities 页面 | PASS | `GET /capabilities` 已有完整发现搜索能力 |

 ---

 ## 六、汇总

 | 类型 | 数量 |
 |:---|:---:|
 | P0 — 阻塞 | 1 |
 | P1 — 重要 | 7 |
 | P2 — 建议 | 6 |
 | PASS | 7 |
 | **合计** | **21** |

 ### 优先级建议

 **必须先修后合并（P0+P1）**:
 1. P0-1: Sessions 缺少列表端点 → 新增 `GET /v1/sessions`
 2. P1-3: Dashboard 计数跨租户 → 改为 tenant-scoped 查询
 3. P1-5: Admin 认证未定义 → 明确 dev/prod 认证方案
 4. P1-4: 缺少 CSRF 保护 → 补充 CSRF 防护
 5. P1-1/2: 补充 Knowledge Base + Conversation 页面
 6. P1-6: Audit 端点命名统一

 **建议 Phase 1 合并前修完**:
 - P2-3: 明确内联CSS定义
 - P2-5: 说明模板/静态文件目录结构
 - P2-6: Audit 分页方案明确
 - P2-1: 考虑 Executions 详情页是否纳入 Phase 1
