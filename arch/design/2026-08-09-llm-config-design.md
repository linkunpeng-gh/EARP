# LLM 模型配置中心设计（参考 Dify 模型配置体系）

- 日期: 2026-08-09
- 状态: draft
- 关联: `arch/L2/01-runtime/runtime-specification.md`（第十一章 Resource）、`connector.py`（LLMConnector）、`config.py`（当前全 env 配置）

## 1. 背景与现状

**现状**：LLM / Embedding 配置全部是环境变量（`Settings`：ollama_base_url / ollama_chat_model / embedding_provider 等），启动时固定。缺：
- 运行时动态配置（换模型要改 env 重启）
- 多模型管理（多个供应商、多个模型并存、按用途选择）
- 管理界面（Dify 的"模型供应商"页面）
- 租户级隔离（不同租户可用不同模型）

**参考 Dify 三层模型配置体系**（`core/model_runtime/`，映射度 70%）：

```
Layer 1: Model Provider（供应商目录）     —— OpenAI / Anthropic / Ollama / 通义 / 智谱…
         静态内置：name / icon / 支持类型 / 凭证字段 schema / 默认模型
Layer 2: Model Config（模型配置，租户级）  —— provider + model_type + model_name + credentials
         LLM / Text-Embedding / Rerank / STT / TTS / Moderation 六种类型
Layer 3: System Model Settings（默认设置） —— default_llm / default_embedding / default_rerank
         运行时各组件取默认模型（可被节点级覆盖）
```

## 2. EARP 设计（适配简化）

### 2.1 数据模型（migration 0009，2 张新表 + 复用加密）

```sql
-- Layer 1 供应商目录 = 代码内置常量（MODEL_PROVIDERS），不入库（变更频率极低，同 Dify builtin）

-- Layer 2 模型配置（租户级）
CREATE TABLE model_configs (
    config_id     VARCHAR(64) PRIMARY KEY,
    tenant_id     VARCHAR(64) NOT NULL,
    provider      VARCHAR(32) NOT NULL,          -- ollama | openai | anthropic | ...
    model_type    VARCHAR(16) NOT NULL           -- llm | embedding | rerank
                  CHECK (model_type IN ('llm','embedding','rerank')),
    model_name    VARCHAR(128) NOT NULL,         -- qwen3.6:35b / bge-m3:latest / gpt-4o
    credentials   JSONB NOT NULL DEFAULT '{}',   -- 加密存储（复用 encrypted_credentials 机制）
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    is_default    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, provider, model_type, model_name)
);
-- RLS + tenant_isolation policy（同既有模式）

-- Layer 3 默认模型设置（租户级，每类型一条）
CREATE TABLE system_model_settings (
    tenant_id      VARCHAR(64) NOT NULL,
    setting_type   VARCHAR(16) NOT NULL          -- llm | embedding | rerank
                   CHECK (setting_type IN ('llm','embedding','rerank')),
    model_config_id VARCHAR(64) NOT NULL REFERENCES model_configs(config_id),
    PRIMARY KEY (tenant_id, setting_type)
);
-- RLS + tenant_isolation policy
```

**凭证加密**：`model_configs.credentials` 用 `infra/ext/ext_logging` 已有的 `CredentialMaskingFilter` 同款 AES/环境密钥加密（或复用 `encrypted_credentials` 表——倾向 JSONB 内嵌 + 加密函数，减少 join）。

### 2.2 供应商目录（内置常量，`infra/model_registry.py`）

```python
MODEL_PROVIDERS = [
    {
        "provider": "ollama",
        "name": "Ollama",
        "model_types": ["llm", "embedding"],
        "credential_schema": [{"key": "base_url", "type": "string", "default": "http://localhost:11434"}],
        "default_models": {"llm": "qwen3.6:35b", "embedding": "bge-m3:latest"},
    },
    {
        "provider": "openai",
        "name": "OpenAI",
        "model_types": ["llm", "embedding"],
        "credential_schema": [{"key": "api_key", "type": "secret"}, {"key": "base_url", "type": "string", "optional": True}],
        "default_models": {"llm": "gpt-4o", "embedding": "text-embedding-3-small"},
    },
    # anthropic / qwen / zhipu … Phase 2 扩展（实现对应 connector）
]
```

### 2.3 运行时集成（关键：DB 优先、env 兜底）

```
启动时 model_service.load_runtime_models(engine)：
  1. 读 system_model_settings → 找 model_configs → 构建运行时模型 map
  2. 无 DB 配置 → 回退 env（Settings 现有字段，向后兼容）
  3. 结果注入 app.state：llm_connector（default llm）/ embedding provider（default embedding）

LLMConnector 改造：
  - 支持按 model_config 动态构造（base_url/model_name/credentials 从 DB 读而非仅 settings）
  - 保留 env 兜底（现有构造路径不变）

embedding provider：
  - init 时优先用 default embedding config（DB），否则 env
  - 知识库上传/检索走该 provider
```

### 2.4 API

```
GET    /api/model-providers                     → 供应商目录 + 每供应商已配置模型
POST   /api/model-configs                       → 新增模型配置（provider/type/name/credentials）
PUT    /api/model-configs/{id}                  → 更新（credentials 可留空=不变）
DELETE /api/model-configs/{id}                  → 删除（若被默认引用则拒绝）
POST   /api/model-configs/{id}/test             → 测试连接（真实调用一次）
GET    /api/system-model-settings               → 当前默认（llm/embedding/rerank）
PUT    /api/system-model-settings               → 设置默认（{llm: config_id, embedding: ..., rerank: ...}）
```

### 2.5 管理页面（/admin/pages/models.html，新导航项「模型」）

```
┌─ 模型 ─────────────────────────────────────────────┐
│ 推理模型（默认）: [qwen3.6:35b ▾]  测试连接  保存    │
│ 嵌入模型（默认）: [bge-m3:latest ▾] 测试连接  保存   │
│ 重排序模型（默认）: [未配置]                          │
│                                                    │
│ ┌─ 模型配置列表 ──────────────────────────────┐    │
│ │ Provider │ Type │ Model │ 默认 │ 状态 │ 操作  │    │
│ │ ollama   │ llm  │ qwen3.6:35b │ ✓ │ ✓ │ ⚙️ 🗑 │    │
│ │ ollama   │ embed│ bge-m3      │ ✓ │ ✓ │ ⚙️ 🗑 │    │
│ └─────────────────────────────────────────────┘    │
│ [+ 添加模型]（Provider ▾ / Type ▾ / Name / 凭证）    │
└────────────────────────────────────────────────────┘
```

导航：顶层独立「模型」组（或并入「治理」——倾向独立，属于运行时配置）。

### 2.6 安全

- credentials 加密存储（复用 CredentialMaskingFilter 机制）
- API 响应**永不明文返回** credentials（仅返回 `credential_masked: bool`）
- 全部端点 JWT 鉴权 + tenant RLS

## 3. 与现有 env 配置的关系

| 场景 | 行为 |
|---|---|
| 无 DB 配置 | env 兜底（现有行为不变，零迁移成本） |
| 有 DB 配置 | DB 优先（启动时覆盖 env） |
| 运行时改默认模型 | 只改 system_model_settings，**不重启**（下次调用生效；LLMConnector 每次取当前 map） |

## 4. 影响分析

| 项 | 变更 |
|---|---|
| migration 0009 | model_configs + system_model_settings（2 表 + RLS + 加密函数） |
| 新模块 | `infra/model_registry.py`（供应商目录）+ `admin/model_service.py`（CRUD + 运行时加载） |
| connector.py | LLMConnector 支持从 model_config 构造（DB 优先 env 兜底） |
| config.py | 保留（作为兜底默认） |
| ext_embedding.py | init 时优先 DB 默认 embedding |
| 前端 | models.html 新页面 + 导航「模型」 |
| 不影响 | 知识库/本体层/执行链路（只换模型来源） |

## 5. 开放问题

> **2026-08-09 决策记录（已全部确认）**：
>
> 1. **供应商范围**：Phase 1 只做 `ollama` + `openai` 两个（anthropic/通义/智谱 Phase 2 扩展）
> 2. **凭证加密**：`model_configs.credentials` JSONB 内嵌 + 应用层 AES（`EARP_CREDENTIALS_KEY` env，32 字节；不引入 pgcrypto、不 join encrypted_credentials 表）
> 3. **导航**：「模型」为独立入口，放**右上角图标**（设置齿轮，所有页面 header 统一）——不进左侧主导航组
> 4. **rerank**：Phase 1 占位（model_type enum 含 rerank、页面可配；bge-reranker connector 实现 Phase 2）
>
> ---
> （以下为原开放问题，已由上述决策关闭）

1. ~~凭证加密实现~~ ✅ 已决策：JSONB 内嵌 AES（见上）
2. ~~供应商范围~~ ✅ 已决策：ollama + openai
3. ~~运行时热更新~~ ✅ 惰性生效 + 审计日志（`runtime.model.default_changed` 事件可选）
4. ~~rerank 类型~~ ✅ 占位（Phase 2 实现 connector）
