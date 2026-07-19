# Server M1 — 架构影响分析

## PRD-2026-021 v1.1

| 字段 | 值 |
|------|-----|
| **影响范围** | apps/earp-server（Gateway/JWT/StepRunner/Orchestrator/Checkpoint/EventBus/Audit/Capability/Connector 9 个新/改模块）；libs/earp-sdk-core-py（F1 版本号 + F3 utcnow + F4 新增导出）；libs/earp-sdk-runtime-py（F3）；CI（F2 capability 进 matrix + AC-09 runtime-py 集成测试联动） |
| **架构决策** | 无新增 ADR——M1 所有架构性决定（Step Runner 三形态/Layer 链/Checkpoint 最小落盘）已在 plan v1.4 和 PRD 中声明 |
| **Breaking Change** | **F1 是 breaking**——earp-sdk-core 版本从 0.1.0.dev0 升到 0.1.0，下游 >=0.1.0 约束自动满足（dev 序变化，非 API 断裂） |
| **新增依赖** | PyJWT / python-jose（JWT 签发校验） |
| **分析人** | Arch Agent |
| **日期** | 2026-07-19 |

---

## 1. 影响范围

### 1.1 服务端新增模块

| 模块 | 文件数(估) | 说明 |
|:-----|:--------:|:-----|
| gateway/auth.py | 1 | JWT 中间件 + 租户/角色上下文注入 |
| gateway/input_guard.py | 1 | 注入攻击模式黑名单 |
| runtime/session_service.py | 1 | Session CRUD（create/get/close） |
| runtime/invoke.py | 1 | POST /v1/sessions/{id}/invoke 路由 + Orchestrator 集成 |
| orchestrator/step_runner.py | 1 | Step 接口三形态（invoke/stream/batch）+ 同步执行器 |
| orchestrator/layers.py | 1 | AuditLayer + Layer 基类 |
| checkpoint.py | 1 | CheckpointStore（写 checkpoints+blobs） |
| infra/eventbus.py | 1 | 进程内 EventBus（发布/订阅） |
| audit/consumer.py | 1 | EventBus 订阅 → audit_logs DB 写入 |
| capability/registry.py | 1 | Capability 注册+精确发现 |

### 1.2 SDK 修改

| 包 | 文件 | 变更 | 影响 |
|:---|:-----|:-----|:-----|
| earp-sdk-core-py | pyproject.toml | version 0.1.0.dev0 → 0.1.0（F1） | downstream >=0.1.0 约束自然满足；dev 序 → 正式版序，uv/pip 解析不再报版本冲突 |
| earp-sdk-core-py | conversation.py | `datetime.utcnow()` → `datetime.now(datetime.UTC)`（F3） | M0 既有警告消除 |
| earp-sdk-runtime-py | session.py | 同上 utcnow 修复 | 同上 |
| earp-sdk-core-py | `__init__.py` | 导出 `EnqueueInSessionProtocol`（F4） | 新增协议接口，不改变既有 API |
| earp-sdk-runtime-py | client.py | `enqueue_in_session()` 方法（F4） | 新增方法，不改变既有 API |

### 1.3 CI 变更

| 文件 | 变更 | 影响 |
|:-----|:-----|:-----|
| .github/workflows/test.yml | matrix 新增 `earp-sdk-capability-py`（F2） | +90 测试进 CI；job 数 4→5 |
| .github/workflows/test.yml | server job 增加 `earp-sdk-runtime-py` 集成测试步骤（AC-09） | server job 内建 runtime-py 依赖并运行其 37 测试打真实服务端 |

### 1.4 PRD AC → 交付物映射

| AC | 交付物 | 层 |
|:--:|:-------|:---|
| AC-01~04 | gateway/auth + runtime/session_service + invoke_endpoint | 代码 |
| AC-05 | checkpoint.py | 代码 |
| AC-06 | orchestrator/step_runner.py | 代码 |
| AC-07 | connector（增强重试）+ audit/consumer | 代码 |
| AC-08 | runtime/session_service.close() | 代码 |
| AC-09 | CI server job + testcontainers runtime-py 集成 | 工程 |
| AC-10 | capability/registry.py | 代码 |
| AC-11 | gateway/input_guard.py | 代码 |
| AC-12 | F1-F5 改动（SDK 版本+CI+utcnow+enqueue_in_session+RLS 矩阵） | SDK/CI/测试 |

## 2. 跨域依赖与风险

| # | 风险 | 缓解 |
|:-:|:-----|:-----|
| 1 | **F1 版本升号导致现有 SDK 安装路径变化** | 下游全部 `>=0.1.0`，dev 号仅排序差异不改变 API 兼容性；CI 全量 SDK 回归兜底（AC-09+AC-12） |
| 2 | **JWT 中间件开发环境密钥管理** | dev 硬编码 HS256 secret（documented limitation）；prod RS256 密钥环境变量注入，误用 dev secret→startup 日志 warn |
| 3 | **AC-09 runtime-py 37 测试打真实服务端——MockRuntime 未覆盖的路径** | 当前 37 测试含 mock_runtime + security 两个集，invoker_http 12 测试可能涉及尚未实现的流式/批处理；M1 集成目标为全部**可执行**测试 PASS（流式相关 skip） |
| 4 | **Step Runner 接口锁定后 M5/M6 返工** | plan v1.4 已声明为架构性决定一次到位；接口层提供 Protocol/ABC + NotImplemented 保护，实现层可扩展 |

## 3. L2 规范影响

M1 不需要版本升级任何 L2 规范——plan v1.4 里程碑-规范映射表中 M1 行仅需 Runtime Spec v1.3→v1.4（Checkpoint 创建点补"invoke 完成即落盘"语义 + Step Runner 三形态调用契约），但那属于**L3 设计的规范实施**（M1 L3 设计阶段在 Runtime Spec 升级声明的约束下写接口签名），**不是 M1 PRD 阶段的要求**。本影响分析仅声明 L3 设计会引用该升级项。

## 4. 结论

绿灯进入 Phase 2（L3 设计）。F1 是唯一的 breaking change 但影响限于版本号排序语义（无 API 断裂），SDK 全量回归兜底。服务端 10 个新文件均在已建立的骨架内，无新增进程角色或基础设施。
