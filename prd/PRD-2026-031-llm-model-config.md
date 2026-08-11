# PRD-2026-031 v1.0

## LLM 模型配置中心

| 字段 | 值 |
|------|-----|
| **PRD ID** | PRD-2026-031 |
| **Feature** | 模型配置中心：供应商目录（ollama/openai）+ 模型配置 CRUD（credentials 加密）+ 默认模型设置 + 测试连接 + 管理页面（右上角图标入口） |
| **优先级** | **P1** |
| **版本** | v1.0 |
| **上游设计** | `arch/design/2026-08-09-llm-config-design.md`（参考 Dify 三层模型配置体系） |
| **PRD 链** | ← 知识资产方向（M3/M4 之后或并行） |

---

## 1. 范围表

| # | 域 | 功能 |
|:--|:---|:-----|
| 1 | DDL | migration 0009：`model_configs`（provider/model_type/model_name/credentials 加密 JSONB/enabled/is_default）+ `system_model_settings`（tenant + setting_type → model_config_id）+ RLS + 索引 |
| 2 | 目录 | `infra/model_registry.py`：内置供应商常量——ollama（llm/embedding，base_url 凭证）、openai（llm/embedding，api_key+base_url 凭证）；model_type enum（llm/embedding/rerank，rerank 占位） |
| 3 | 加密 | `infra/credential_crypto.py`：AES-256 加解密（`EARP_CREDENTIALS_KEY` 32 字节 env；无 key 时 dev 用默认值 + 告警）；API 永不明文返回 credentials |
| 4 | Service | `admin/model_service.py`：model_config CRUD（唯一约束 provider+type+name；删除被默认引用时拒绝）+ system_model_settings GET/PUT + `load_runtime_models()`（启动时 DB 优先、env 兜底）+ 测试连接（真实调一次） |
| 5 | API | `GET /api/model-providers`（目录+已配置）、`POST/PUT/DELETE /api/model-configs`、`POST /api/model-configs/{id}/test`、`GET/PUT /api/system-model-settings` |
| 6 | 运行时 | LLMConnector 支持从 model_config 构造（DB 优先 env 兜底）；embedding init 优先 DB 默认；改默认惰性生效（下次读 map）+ 审计日志 |
| 7 | 页面 | `models.html`：默认模型下拉（llm/embedding/rerank）+ 测试连接 + 配置列表 + 添加模型表单（Provider/Type/Name/凭证）；**右上角齿轮图标入口（所有页面 header 统一）** |

---

## 2. US

| US | 描述 |
|:--:|:-----|
| US-01 | 管理员打开「模型」页 → 看到供应商目录（ollama/openai）+ 已配置模型列表 + 默认设置 |
| US-02 | 添加 ollama llm 模型（qwen3.6:35b，base_url）→ 保存 → 列表出现 → 设为默认 |
| US-03 | 添加 openai embedding 模型（api_key）→ 保存 → 列表出现 |
| US-04 | 测试连接 → 真实调用一次 → 成功/失败反馈 |
| US-05 | 设置默认 llm/embedding → 下次 Planner/知识库调用使用新模型（不重启） |
| US-06 | 删除被默认引用的模型 → 拒绝（提示先改默认） |
| US-07 | GET API 返回 credentials 永不明文（只返回 masked 标记） |
| US-08 | 无 DB 配置时 → 回退 env 现有行为（向后兼容，零迁移） |

---

## 3. AC

| AC | 内容 | 验证 |
|:--:|:-----|:----|
| AC-01 | migration 0009 后 2 表存在 + RLS FORCE（跨租户不可见） | pytest |
| AC-02 | 创建 model_config（唯一约束冲突 → 422） | pytest |
| AC-03 | credentials 加密落库（明文不在 DB）、API 返回 masked | pytest |
| AC-04 | system_model_settings PUT → GET 回读一致；非法 type → 422 | pytest |
| AC-05 | 删除被默认引用的 config → 拒绝；未被引用 → 删除成功 | pytest |
| AC-06 | load_runtime_models：有 DB 配置用 DB，无则回退 env | pytest |
| AC-07 | 测试连接：mock connector 成功/失败两种路径 | pytest |
| AC-08 | 改默认 embedding 后，embed_chunks 用新 provider（monkeypatch 验证） | pytest |
| AC-09 | 页面 CRUD 走通 + 右上角图标导航（全部页面 header） | 手工 |

---

## 4. 依赖

| 依赖 | 来源 | 引用 |
|:---|:---|:---|
| connector.py LLMConnector | 现有 | 从 model_config 构造 |
| ext_embedding | 现有 | init 优先 DB 默认 |
| encrypted_credentials 机制 / CredentialMaskingFilter | M0 | 加密模式参考 |
| RLS / tenant_session | M0 | 2 张新表 |
| JWT | M0 | 全部端点鉴权 |

---

## 5. 对齐检查

| 规范 | 条款 | 对齐 |
|:---|:---|:----|
| runtime-spec 第十一章 Resource | llm 资源类型 | ✅ |
| 设计文档 2026-08-09 | 三层体系（供应商/配置/默认） | ✅ |
| 决策记录 | ollama+openai / JSONB AES / 右上角导航 / rerank 占位 | ✅ |

---

## 6. Gate 检查

| # | 检查项 | 状态 |
|:--|:-----|:----:|
| 1 | 依赖明确 | ✅ 6 项 |
| 2 | AC 可测试 | ✅ 9 条（8 自动化 + 1 手工） |
| 3 | 与冻结规范无矛盾 | ✅ |
