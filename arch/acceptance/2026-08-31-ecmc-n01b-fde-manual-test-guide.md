# ECMC 因果模型页面 — FDE 手工测试指南（N01B）

**文档编号：** ACCEPT-ECMC-N01B-FDE
**日期：** 2026-08-31
**适用范围：** `apps/earp-admin` ECMC 前端（页面）全流程测试
**依据：** `arch/design/2026-08-30-ecmc-frontend-information-architecture-and-page-template.md`（§20.2 验收主路径）、`prd/PRD-2026-033-causal-model-management-n01a.md`、`api/2026-08-30-n01a-causal-model-management-api-contract.md`
**前置验证结论：** 服务端全链路已用 `apps/earp-server/scripts/verify_ecmc_n01b.py` 自动跑通（建模型→节点/边/证据/规则→校验→提交→发布→编译→激活→过期 CAS 409）。

---

## 0. 测试前必须知道的三件事（避免误判）

1. **生产 Catalog 合同未签署，服务端默认 fail-closed。**
   `main.py` 生产默认注册 `UnavailableCatalogResolver()`，所有涉及目录引用的写入都会被拒。
   要让页面能写，**必须**以 `EARP_ECMC_TEST_CATALOG=1` 启动服务端（仅 dev/test 生效，生产不受影响）：
   - 注册 dev fake 目录（条目与前端 `?catalog=fake` 完全一致，数据域 `production`/`equipment`）；
   - 幂等种入编译器需要的 StepType pin（`knowledge_query`/`output`）；
   - 挂载 dev 编译驱动路由 `POST /v1/ecmc/_dev/complete-compile/{compile_id}`。

2. **`?catalog=fake` 只作用于前端选择器（test-only 界面合成，§9.3）。**
   它让目录选择器出现 test-only 数据；服务端写入能否成功取决于第 1 点。正式生产页面在目录合同签署前会正确地禁用目录写入——那是预期行为，不是 bug。

3. **编译是异步 Attempt，页面点「编译」后会停在 running。**
   仓库暂无 outbox 消费进程，因此需要手工用 dev 路由把 Attempt 驱动到 success（见第 5 步），之后页面才会出现「激活」。

---

## 1. 环境准备

### 1.1 依赖服务（PostgreSQL 等）

```bash
cd apps/earp-server
make db-up        # docker compose up -d --wait（含 pgvector:5433 / valkey / minio / langfuse）
make migrate      # alembic upgrade head（含 0040_n01_causal_model_management）
```

> 已在跑则跳过；迁移状态确认：`.venv/bin/alembic current` 应显示 `0040_n01_causal_model_management (head)`。

### 1.2 启动服务端（关键：带 fake catalog 钩子）

```bash
cd apps/earp-server
EARP_ECMC_TEST_CATALOG=1 .venv/bin/python -m uvicorn earp_server.main:create_app --factory --port 8000
```

启动日志应出现一行：
```
EARP_ECMC_TEST_CATALOG=1: fake ECMC catalog enabled (dev/test only)
```
出现 `ECMC fake catalog init failed` 则说明钩子未生效，先排查再继续。

> 端口可换；文档后续以 8000 为例。

### 1.3 登录

浏览器打开 `http://localhost:8000/admin/pages/login.html`，填入：

| 字段 | 值 |
|---|---|
| Tenant ID | `tenant-demo` |
| User ID | `u1` |
| Role ID | `r1` |

逻辑：`r1` 是 `is_admin=True`，ECMC 的 `read/write_draft/review/compile/activate` 权限全部放行；登录接口会校验 tenant/user/role 存在（启动时 `seed_demo_tenant` 已幂等创建）。

登录后 localStorage 会存 `earp_token`（后续 dev 编译路由的 `Authorization: Bearer <token>` 用）。

### 1.4 进入被测页面（带 fake 模式）

```
http://localhost:8000/admin/pages/ecmc-models.html?catalog=fake
```

进入后应看到：一级导航含「认知模型」，左侧抽屉为 ECMC 结构（概览/模型资产/待审核/…/目录扩展申请）。`catalog=fake` 会贯穿 ECMC 全部内部导航（切 tab、进编辑器、返回列表均自动保留）。

---

## 2. 快速自检（可选，但建议先跑）

```bash
cd apps/earp-server
.venv/bin/python scripts/verify_ecmc_n01b.py http://127.0.0.1:8000
```

全链路自动跑通（建模型→画图→证据/规则→校验→提交→发布→编译→激活→过期 CAS 409），证明服务端可用。脚本结束后会清理自身数据，只留一份可继续手工测试的空库。

---

## 3. 手工测试主路径（Case A 语义：「3 号矿产量下降诊断」）

> 每步的「为什么」帮助理解契约逻辑；「预期」是判定通过的标准。

### 步骤 1 — 新建模型（向导）

- [ ] 操作：模型资产页右上角「+ 新建模型」→ 选「因果模型」→
  1. 数据域：选择 `生产数据`（production）
  2. 目标实体类型：`矿山`（entity.mine）
  3. 方向 `下降(down)`，入口节点 key `production_output`，时间窗口 `日窗口`（daily_window）
  4. 名称：`3 号矿产量下降诊断`，说明随意
  5. 确认 DiagnosticTarget 签名 → 创建
- [ ] 预期：进入全屏编辑器，命令栏显示模型名 / `draft` 徽章 / `revision 1` / 画布空态「此版本尚无节点」。
- 为什么：DiagnosticTarget 创建后不可修改，目标变更必须新建模型（§7.2）；所有可执行字段只能来自受控目录选择器（§9）。

### 步骤 2 — 新增节点（3 个）

- [ ] 操作：左侧「组件」Tab →「+ 新增节点」（**节点 key 创建后只读，创建时对话框可填**）：
  - 节点 A：勾选**入口节点**（勾选后 key 自动对齐诊断目标入口 `production_output`；业务名 `产量`、实体 `矿山`、observable）
  - 节点 B：key 可留默认（如 `n-1`）、实体 `运输系统`、`observable`、业务名 `运输周期`
  - 节点 C：key 默认、实体 `运输系统`、`indirectly_observable`、业务名 `排队时间`
- [ ] 预期：画布出现 3 张节点卡片；入口节点有「入口」标记且 key = `production_output`（否则校验会报 `CAUSAL_TARGET_MISMATCH`）；每保存一次命令栏 revision 递增、显示「已保存」。
- 为什么：入口必须唯一、observable，且其 node key 必须等于诊断目标入口；间接可观测节点不强制直接证据（§7.2 校验语义）。

### 步骤 3 — 新增边（DAG，指向入口）

- [ ] 操作：
  - 边 1：从 `运输周期` → 到 `产量`（关系 `影响`，负向 `-`，strength 0.80，confidence 0.90，lag PT0S）
  - 边 2：从 `排队时间` → 到 `运输周期`（**正向 `+`**，0.60/0.70——排队越久循环周期越长，同向）
  - 也可用画布端口拖拽建边（会弹出受控表单）
- [ ] 预期：画布出现带方向箭头的边，边标签显示 `- 0.80 · c0.90`。
- 为什么：边从因指向果、最终通向入口；任何节点到不了入口会阻断（§7.2）。

### 步骤 4 — 证据需求（required evidence）

- [ ] 操作：点击节点卡 → 右侧属性面板「+ 证据需求」：
  - `产量`：metric `production_output`、unit `吨`、聚合 `日累计`、窗口 `日窗口`、模板 `上下文实体`、primary `读取产量`、勾选 required
  - `运输周期`：metric `haulage_cycle_time`、unit `分钟`、聚合 `均值`、模板 `出向关系`（绑定参数按 schema 渲染：关系 `拥有子系统`、目标 `运输系统`）、primary `读取运输周期`、required
- [ ] 预期：节点卡底部出现「✓ 证据 1」；支持合同用「+ 添加」多选且排除 primary。
- 为什么：observable 节点必须有 required 证据；每个证据恰好一个 primary 合同（§6.3）；binding 参数只能含模板 schema 声明字段（§2.1）。

### 步骤 5 — 规则

- [ ] 操作：「+ 规则」→ RuleSchema `方向规则`，spec：`{"operator":"matches_direction","expected":"down"}`，rationale 随意。
- [ ] 预期：左侧大纲「规则」出现该条；属性面板可编辑。
- 为什么：规则结构由受控 rule_schema 校验，不是自由 DSL。

### 步骤 6 — 校验（先验证阻断，再验证通过）

- [ ] 操作 A（造阻断）：删除 `排队时间` 的证据需求，或把一条边改成指向错误节点 → 命令栏「校验」→ 底部校验抽屉展开。
- [ ] 预期 A：出现「阻断发布」条目，每条有 code/message/资源定位/「定位」按钮；点「定位」画布会居中选中对应节点/边。
- [ ] 操作 B（修复）：恢复正确结构 → 再次「校验」。
- [ ] 预期 B：抽屉显示通过；命令栏「提交审核」可用（有阻断时该按钮禁用并自动展开校验面板，§8.5/§10）。
- 为什么：校验只回答「模型内容是否有效」；权限/并发错误走全局错误条，不进校验列表（§10）。

### 步骤 7 — 提交审核

- [ ] 操作：「提交审核」（**不是**「发布」——文案与权限分离）。
- [ ] 预期：页面切换为只读 `in_review`，编辑器所有可写控件消失/禁用；顶部出现「通过并发布」「驳回」。
- 为什么：提交后内容锁定；提交与发布是不同的治理动作（§8.1/§11.1）。

### 步骤 8 — 驳回 → 修改 → 重提（审核闭环）

- [ ] 操作：左侧「待审核」→ 打开该版本 →「驳回」→ 必须填写原因。
- [ ] 预期：版本回到 `draft`，revision 递增，可继续编辑（如改业务名）。
- [ ] 操作：修改后再次「提交审核」。
- [ ] 预期：回到 `in_review`。
- 为什么：驳回带原因、可追溯；内容保留（§11.2）。

### 步骤 9 — 治理发布

- [ ] 操作：「通过并发布」→ 确认对话框检查：模型/Version、DiagnosticTarget 签名、数据域、最新校验结果、Snapshot 不可变说明 → 确认。
- [ ] 预期：Toast 显示服务端返回的 `snapshot_id` 与 content hash；版本状态 `published + inactive`；命令栏出现「编译」「查看 Artifact」「复制为新草稿」。
- 为什么：前端不计算 canonical hash，只展示服务端结果；发布不切换 runtime active（§11.3）。

### 步骤 10 — 编译（含 dev 驱动）

- [ ] 操作：「编译」→ 命令栏状态变 running（页面不展示伪 Artifact）。页面会自动轮询 governance（每 2s，最长 ~30s），无需手动刷新。
- [ ] 操作（dev 驱动 success）：取 token 后执行：
  ```bash
  TOKEN=<earp_token>   # 页面 localStorage 或登录接口返回
  COMPILE_ID=<cr-xxx>  # 编译后 toast 会显示 compile_record_id
  curl -X POST "http://localhost:8000/v1/ecmc/_dev/complete-compile/$COMPILE_ID" \
       -H "Authorization: Bearer $TOKEN"
  ```
- [ ] 预期：curl 返回 `{"status":"success","compiled_artifact_hash":"<64hex>"}` 后，页面**自动**出现「激活」按钮（轮询已生效）；点「查看 Artifact」能看到只读 Artifact JSON。
- 为什么：CompileRecord 是 append-only Attempt；success 才冻结不可变 Artifact（§11.4）。dev 路由等价测试里的 `complete_attempt`，因为仓库暂无 outbox 消费进程——这是预期行为，不是卡死。

### 步骤 11 — 显式激活（双 CAS）

- [ ] 操作：「激活」→ 确认框核对：候选 Version+revision、CompileRecord/Artifact hash、当前 active pointer（首次应为「无」）→ 确认。
- [ ] 预期：Toast「激活成功」；右上/治理面板显示 `ACTIVE` 标记；「编译与激活 → Active Versions」页出现该模型，readiness=active。
- 为什么：激活携带候选 If-Match + active pointer CAS；只物化指定 Artifact，不重新编译（§11.5）。

### 步骤 12 — 并发 CAS 冲突（重点验证）

- [ ] 操作：再编译/激活一次（或另开一个浏览器窗口并发）——最简做法：构造**过期 expected pointer** 的激活（把当前 active pointer 换成 null 提交）。
  - 页面路径：编译成功后再次「激活」，但确认框中 expected pointer 与实际不符时提交。
- [ ] 预期：返回/提示 `409 ACTIVE_VERSION_CHANGED`；页面提示指针已被他人更新，**不会**自动重试，需刷新后重新确认；Active 不被覆盖。
- 为什么：active-pointer CAS 防止并发覆盖（§11.5/§15.2）。

### 步骤 13 — 归档 active 版本

- [ ] 操作：编辑页（published+active）→「更多」→ 归档（或治理面板）。
- [ ] 预期：版本变 `archived`；active pointer 清空（Active Versions 消失）；对应 Blueprint withdrawn。
- 为什么：归档 active 版本会原子清 pointer + withdraw 当前 Blueprint，不自动回退旧版本（§3.5）。

---

## 4. 边界与负向用例（建议按需抽查）

| # | 场景 | 操作 | 预期 |
|---|---|---|---|
| N1 | 制造环 | 再加一条反向边（产量→运输周期）后校验 | 出现 `CAUSAL_DAG_CYCLE` 阻断，可定位 |
| N2 | 悬空引用 | 删除某节点但保留其边（页面会先弹依赖清单） | 页面不直接发删除请求，先展示依赖；服务端 409 兜底 |
| N3 | 缺失 required 证据 | 删掉 `产量` 的证据后校验 | `CAUSAL_REQUIRED_EVIDENCE_MISSING` 阻断 |
| N4 | 已发布只读 | 打开 published/archived 版本 | 无任何可写控件；「复制为新草稿」才能继续编辑 |
| N5 | 无目录模式 | 用**不带** `catalog=fake` 的 URL 打开模型页，点新建/新增节点 | 显示「受控目录不可用」引导，不出现自由 stable ID 输入框（§9.3） |
| N6 | 跨数据域 | 在 `production` 域模型里给节点选 `设备组`（equipment） | 选择器按数据域过滤，选不到；即使绕过也会被服务端 `CATALOG_REF_DOMAIN_FORBIDDEN` 拒绝 |
| N7 | 版本冲突 | 两个窗口同时编辑同版本并保存 | 后保存者收到 `409 VERSION_CONFLICT`，弹出「版本已被其他用户更新」+ 重新加载，无静默覆盖 |
| N8 | 目录申请类型 | 目录申请页新建不同类型（如 relation_type/unit/capability_contract） | 表单按 kind 渲染对应 contract 字段；无目录时「创建申请」禁用并说明 |
| N9 | 引导导航 | 在 `?catalog=fake` 下走：编辑器→待审核→编辑器→返回模型页 | 全程 URL 保留 `catalog=fake`，Catalog 选择器始终可用 |

---

## 5. 数据清理

手工测试会产生模型数据。清空测试数据（仅测试租户/命名模型，超管连接，会话级跳过 draft guard 触发器）：

```bash
cd apps/earp-server
EARP_MIGRATION_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/earp' \
  .venv/bin/python scripts/cleanup_ecmc_test_data.py "你的测试模型名"
```

> 注意：
> - **必须显式传模型名**，无参数调用是 no-op（2026-08-31 误删已发布模型事故后加固），生产数据库不要执行；
> - 误删已发布模型可恢复：不可变 Snapshot 不随模型删除，用 `scripts/restore_ecmc_model_from_snapshot.py`（按 snapshot 重建 model/version 并回填图内容）恢复；
> - 脚本会跳过 draft-only guard 触发器（仅超管会话有效）。

---

## 6. 通过标准（勾选全部后视为通过）

- [ ] 主路径 13 步全部符合「预期」列
- [ ] N1–N3 阻断可定位并修复
- [ ] N4 已发布内容无写入口
- [ ] N5 无目录时无自由输入、有明确引导
- [ ] N6 数据域过滤生效（前端 + 服务端双重）
- [ ] N7 并发 409 且不静默覆盖
- [ ] N9 fake 模式贯穿导航
- [ ] `apps/earp-admin` 四组 smoke 全绿（`test-nav/ecmc-api/ecmc-catalog-picker/ecmc-dom`）
- [ ] `git diff --check` 干净

## 7. 相关文件速查

| 用途 | 路径 |
|---|---|
| 服务端 fake catalog / StepType / dev 编译钩子 | `apps/earp-server/src/earp_server/main.py`（`EARP_ECMC_TEST_CATALOG=1`） |
| FDE 自动全链路脚本 | `apps/earp-server/scripts/verify_ecmc_n01b.py` |
| 测试数据清理脚本 | `apps/earp-server/scripts/cleanup_ecmc_test_data.py` |
| 前端 fake 目录适配器 | `apps/earp-admin/js/ecmc-catalog-picker.js` |
| 页面 | `apps/earp-admin/pages/ecmc*.html` |
| 前端 smoke | `apps/earp-admin/test-{nav,ecmc-api,ecmc-catalog-picker,ecmc-dom}-smoke.cjs` |
| 设计文档 | `arch/design/2026-08-30-ecmc-frontend-information-architecture-and-page-template.md` |
