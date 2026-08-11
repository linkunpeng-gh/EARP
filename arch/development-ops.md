# EARP 开发运维备忘录（Dev Ops Cheat Sheet）

> 本地服务启停、排查、日志的速查手册。遇到"服务起没起/怎么重启/为什么 404"先看这里。

## 1. 常用命令（均在 `apps/earp-server/` 下）

| 命令 | 作用 |
|---|---|
| `make db-up` | 启动基础设施（PG:5433 / valkey:6380 / minio / langfuse） |
| `make migrate` | 应用 Alembic 迁移到 head（含 procrastinate schema） |
| `make api` | 启动 API（`python -m earp_server.entrypoints.api`，**无热重载**） |
| `make dev` | 启动 API（uvicorn `--reload`，**改代码自动生效**，推荐开发用） |
| `make test` | 全量 pytest（testcontainers 起临时 PG，无需本地服务） |
| `make lint` | ruff check + format + pyright |

## 2. 判断当前服务类型（make api vs make dev）

```bash
lsof -i :8000 | grep LISTEN
ps aux | grep -E "uvicorn|entrypoints.api" | grep -v grep
```

| 命令行特征 | 类型 | 改代码是否生效 |
|---|---|---|
| `python -m earp_server.entrypoints.api` | `make api` | ❌ 需重启 |
| `uvicorn earp_server.main:create_app --factory --reload`（有 reloader 子进程） | `make dev` | ✅ 自动 |

## 3. 重启服务

```bash
# 通用：杀端口再起（make api 模式改代码后必须重启）
lsof -ti :8000 | xargs kill
make api            # 或 make dev

# 后台运行 + 日志（本会话实践过的可靠方式）
cd apps/earp-server
nohup make dev > /tmp/earp-dev.log 2>&1 &    # 日志: /tmp/earp-dev.log
tail -f /tmp/earp-dev.log

# 停掉后台服务
lsof -ti :8000 | xargs kill
```

## 4. 验证 API 是否正常

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health   # 期望 200

# 路由是否注册（401 = 存在但需认证；404 = 路由缺失 → 服务是旧代码没重启）
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/knowledge/routing/debug \
  -H 'Content-Type: application/json' -d '{"query":"报销制度"}'
```

## 5. 前端页面（静态文件，改完刷新即生效，无需重启）

- admin：`apps/earp-admin/pages/`（knowledge.html / test-retrieval.html / data-domains.html …）
- JS 语法自检：`node -e "const fs=require('fs');const h=fs.readFileSync('pages/xxx.html','utf8');const s=[...h.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');new Function(s);console.log('OK')"`

## 6. 环境（2026-08-09/10 会话现状）

- **Ollama 远程**：`http://10.188.2.230:11434`（bge-m3:latest 嵌入），本地 11434 无服务
- **数据库**：docker PG `localhost:5433`（app 角色 `earp_app`，migration 角色 `postgres`）
- **后台服务现状**：`make dev` 模式，日志 `/tmp/earp-dev.log`
- **企业级精准召回**：验证指南见 `arch/design/2026-08-09-enterprise-retrieval-design.md` §0.1（四层验证）

### 6.1 模型配置（DB 优先，env 兜底）

- 机制：`model_configs` 表存模型（provider/model_name/base_url/api_key），`system_model_settings` 表存**默认指向**；运行时 `load_runtime_models` 读默认 → DB 优先，无则 env 兜底
- **检索描述生成（suggest-description / suggest-summary）走「默认 LLM」**——配置了模型但没设默认 = 不生效
- 切换默认：admin「模型配置」页（models.html）→ LLM 列表 → **设为默认**（写 system_model_settings）；或直接改 DB：
  ```sql
  UPDATE system_model_settings SET model_config_id='mc-xxx' WHERE tenant_id='tenant-demo' AND setting_type='llm';
  ```
- 生效：DB 实时读取，**无需重启**
- **当前默认（2026-08-10/11 起）**：LLM = DeepSeek（openai / `deepseek-v4-flash` / `https://api.deepseek.com`）；**embedding = 硅基流动 BAAI/bge-m3**（openai 兼容，`https://api.siliconflow.cn/v1`，1024 维，key 仅用于 embedding）；env 兜底 `ollama_chat_model=qwen3.6:27b`
- **注意**：远端共享 Ollama（10.188.2.230）embedding 服务不稳定（2026-08-10 实测 /api/embed 无响应），已弃用；本地 Docker 无 ollama 镜像（下载受网络限制）
- 注意：LLM 默认影响所有 LLM 调用（planner 意图规划等），不只是检索描述

## 7. 常见坑速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 前端调新端点 404 | 服务是旧代码（make api 未重启） | 重启服务，或切 make dev |
| 路由调试一直"路由中" | （已修复：psycopg async 惰性游标嵌套查询挂起） | 确认代码含 fetchall 物化修复 |
| `ReferenceError: esc is not defined` | JS 回调作用域（已修复：esc 提升到函数顶部） | 刷新页面 |
| `data_domains` 主键冲突 | 单列主键跨租户冲突（既有债务 #7） | 测试/脚本用迁移角色清理后重建 |
