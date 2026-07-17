# EARP 时序图

## L1 — 核心交互流

**文档编号：L1-SEQUENCE**  
**版本：v1.0**  
**定位：L1 — 系统架构。6 条核心交互链的时序图，覆盖 EARP 主要运行时行为。**  
**依赖：L1/deployment-architecture-v1.md, L1/data-architecture-v1.md, L2-01-RUNTIME v1.2, L2-06-SECURITY v1.1, L2-05-AUDIT v1.1, L2-07-TENANT v1.1**

---

# 图 1：核心执行流

```
User    Gateway    Runtime     Planner    Policy    Capability   Connector   External    Audit
 │         │          │           │          │          │            │           │         │
 │─POST──▶│          │           │          │          │            │           │         │
 │ JWT     │          │           │          │          │            │           │         │
 │         │─验证JWT─▶│           │          │          │            │           │         │
 │         │ extract  │           │          │          │            │           │         │
 │         │ tenant_id│           │          │          │            │           │         │
 │         │          │           │          │          │            │           │         │
 │         │          │─create───▶│          │          │            │           │         │
 │         │          │ Session   │          │          │            │           │         │
 │         │          │           │          │          │            │           │  ╔══════╗
 │         │          │           │          │          │            │           │  ║Audit ║
 │         │          │           │          │          │            │           │  ║Sess. ║
 │         │          │           │          │          │            │           │  ║created║
 │         │          │           │          │          │            │           │  ╚══════╝
 │         │          │           │          │          │            │           │         │
 │         │          │─plan─────▶│          │          │            │           │         │
 │         │          │  intent   │          │          │            │           │         │
 │         │          │           │─LLM─────▶│          │            │           │         │
 │         │          │           │  (Plan)  │          │            │           │         │
 │         │          │           │◀─Plan────│          │            │           │         │
 │         │          │◀─DAG──────│          │          │            │           │         │
 │         │          │           │          │          │            │           │         │
 │         │          │           │──eval───▶│          │            │           │         │
 │         │          │           │  Policy  │          │            │           │         │
 │         │          │           │◀─ok/deny─│          │            │           │         │
 │         │          │           │          │          │            │           │         │
 │         │          │─────────────────────────invoke──────────────▶│           │         │
 │         │          │           │          │   cap_id, params      │           │         │
 │         │          │           │          │          │            │──call────▶│         │
 │         │          │           │          │          │            │  API Key  │         │
 │         │          │           │          │          │            │◀─result───│         │
 │         │          │◀────────────────────────result────────────────           │         │
 │         │          │           │          │          │            │           │  ╔══════╗
 │         │          │           │          │          │            │           │  ║Exec  ║
 │         │          │           │          │          │            │           │  ║done  ║
 │◀─200────│          │           │          │          │            │           │  ╚══════╝
 │ result  │          │           │          │          │            │           │         │
```

**步骤说明：**
1. User 携带 JWT 发起请求 → Gateway 验证 JWT，提取 `tenant_id`
2. Gateway → Runtime：创建 Session（Session.tenant_id = JWT.tenant_id）
3. Runtime → Planner：传入 intent，Planner 调用 LLM 生成执行计划 (DAG)
4. Runtime → Policy Center：对每个 Capability 调用做策略评估
5. Runtime → Capability → Connector → External System：执行能力调用
6. Audit Service 订阅 EventBus，记录 Session.created + Execution.completed

---

# 图 2：Session 生命周期

```
User      Gateway     Runtime                   PG                 Audit
 │          │           │                        │                   │
 │─POST────▶│           │                        │                   │
 │ /sessions│           │                        │                   │
 │          │─create───▶│                        │                   │
 │          │ session   │──INSERT───────────────▶│                   │
 │          │           │  (tenant_id,user_id)    │                   │
 │          │◀─session──│◀───────────────────────│                   │
 │◀─201────│  _id      │                        │                   │
 │ {id:"s1"}           │                        │──▶AuditEvent──────▶│
 │          │           │                        │   SESSION_CREATED  │
 │          │           │                        │                   │
 │─POST────▶│           │                        │                   │
 │ /exec   │─invoke───▶│                        │                   │
 │          │           │──INSERT───────────────▶│                   │
 │          │           │  (exec_id, session=s1)  │                   │
 │          │◀─result──│◀───────────────────────│                   │
 │◀─200────│           │                        │                   │
 │          │           │                        │                   │
 │─PATCH───▶│           │                        │                   │
 │ /sess/s1│─close────▶│                        │                   │
 │          │           │──UPDATE status=done────▶│                   │
 │          │           │                        │──▶AuditEvent──────▶│
 │          │◀─200─────│                        │   SESSION_CLOSED   │
```

**TTL 行为：** Session 创建后 24h 自动过期（Redis TTL + PG 定时清理）。

---

# 图 3：认证与授权流

```
User      Gateway            Runtime         Policy Center        Audit
 │          │                   │                 │                  │
 │─POST────▶│                   │                 │                  │
 │ JWT      │                   │                 │                  │
 │          │─验证签名 (RS256 pub key, Gateway 本地)│                 │                  │
 │          │◀─payload (本地解析)──│                 │                  │
 │          │  {user_id,         │                 │                  │
 │          │   tenant_id,       │                 │                  │
 │          │   permissions}     │                 │                  │
 │          │                   │                 │                  │
 │          │─extract tenant_id─▶│                 │                  │
 │          │  (X-EARP-Tenant)   │                 │                  │
 │          │                   │                 │                  │
 │          │                   │─RBAC eval──────▶│                  │
 │          │                   │  (user, cap,     │                  │
 │          │                   │   tenant)        │                  │
 │          │                   │◀─allow/deny─────│                  │
 │          │                   │                 │                  │
 │          │          ┌────────┴────────┐        │                  │
 │          │          │  deny?           │        │                  │
 │          │          │  → 403           │        │                  │
 │          │          │  + Audit         │──────────────────────────▶│
 │          │          │    PERM_DENIED   │        │   AUDIT          │
 │          │          └─────────────────┘        │                  │
```

**Security Spec 对齐：** JWT 验证每请求执行（§5.1 MUST），permissions 传递给 Policy Center 做 RBAC（§5.1）。

---

# 图 4：LLM 安全流

```
User     Gateway/InputGuard    LLM Provider    OutputFilter    Capability    Audit
 │              │                   │               │              │          │
 │─POST────────▶│                   │               │              │          │
 │ user input   │                   │               │              │          │
 │              │─check(input)──────│               │              │          │
 │              │  扫描 7 种注入模式  │               │              │          │
 │              │                  │               │              │          │
 │              │    ┌──blocked?───┐│               │              │          │
 │              │    │  → 403      ││               │              │          │
 │              │    │  + Audit ─────────────────────────────────────────────▶│
 │              │    │    INJECTION ││               │              │  AUDIT   │
 │              │    └─────────────┘│               │              │          │
 │              │                   │               │              │          │
 │              │─sanitize(input)───│               │              │          │
 │              │  包裹分隔符        │               │              │          │
 │              │                   │               │              │          │
 │              │─LLM call─────────────────────────▶│              │          │
 │              │  (sanitized prompt)               │              │          │
 │              │◀────────response─────────────────│              │          │
 │              │                   │               │              │          │
 │              │─check(output)──────────────────────────────────▶│          │
 │              │  PII/泄露/代码检测 │               │              │          │
 │              │                   │               │              │          │
 │              │                   │    ┌──blocked?─┐│              │          │
 │              │                   │    │  → Audit ─────────────────────────▶│
 │              │                   │    │    LEAK/   ││              │  AUDIT   │
 │              │                   │    │    CODE    ││              │          │
 │              │                   │    └───────────┘│              │          │
 │              │                   │               │              │          │
 │              │                   │──filtered─────▶│              │          │
 │              │                   │  (安全输出)     │─execute─────▶│          │
```

---

# 图 5：Plugin 沙箱执行流

```
PluginMgr   PermissionEnforcer   SandboxMgr    subprocess   Plugin.gRPC   Audit
    │              │                 │              │            │           │
    │─load(plugin)▶│                 │              │            │           │
    │              │─ensure_all()────│              │            │           │
    │              │  检查 permissions│              │            │           │
    │              │                 │              │            │           │
    │              │   ┌──denied?───┐│              │            │           │
    │              │   │  → raise   ││              │            │           │
    │              │   │  Permission││              │            │           │
    │              │   │  DeniedError│             │            │           │
    │              │   └────────────┘│              │            │           │
    │              │                 │              │            │           │
    │              │                 │─run(plugin)─▶│            │           │
    │              │                 │  Popen        │            │           │
    │              │                 │  start_new_   │            │           │
    │              │                 │  session=True │            │           │
    │              │                 │              │            │           │
    │              │                 │  stdin: JSON  │            │           │
    │              │                 │  (kwargs)     │            │           │
    │              │                 │              │─gRPC call─▶│           │
    │              │                 │              │◀─result────│           │
    │              │                 │◀─stdout: JSON─│            │           │
    │              │                 │  (result)     │            │           │
    │              │                 │              │            │           │
    │              │                 │   ┌──timeout?┐│            │           │
    │              │                 │   │ killpg()  │            │           │
    │              │                 │   │ TimeoutErr│            │──▶AUDIT──▶│
    │              │                 │   └──────────┘│            │  PLUGIN_   │
    │              │                 │              │            │  TIMEOUT   │
    │              │                 │              │            │           │
    │─on_load──▶─────────────────────────────────────────────────────────────▶│
    │  ok                                                                 AUDIT│
    │                                                                   LOADED │
```

---

# 图 6：审计事件流

```
各域组件         EventBus        Audit Service       PostgreSQL         S3
   │               │                  │                  │               │
   │               │                  │                  │               │
 Runtime ──publish─▶│                  │                  │               │
   │  session       │─dispatch────────▶│                  │               │
   │  .created      │  (订阅匹配)       │──INSERT────────▶│               │
   │               │                  │  (热数据)         │               │
   │               │                  │                  │               │
 Planner ──publish─▶│                  │                  │               │
   │  plan          │─dispatch────────▶│                  │               │
   │  .generated    │                  │──INSERT────────▶│               │
   │               │                  │                  │               │
 Capability───────▶│                  │                  │               │
   │  call            │─dispatch────────▶│                  │               │
   │  .completed      │                  │──INSERT────────▶│               │
   │               │                  │                  │               │
 Security ────────▶│                  │                  │               │
   │  AUTH_EXPIRED   │─dispatch────────▶│                  │               │
   │  PROMPT_INJECT  │                  │──INSERT────────▶│               │
   │  SYSTEM_LEAK    │                  │                  │               │
   │               │                  │                  │               │
   │               │                  │   ╔════════════╗  │               │
   │               │                  │   ║ 定时归档    ║  │               │
   │               │                  │   ║ (每日02:00) ║──▶  S3 冷存储   │
   │               │                  │   ║ 90d→归档    ║  │               │
   │               │                  │   ╚════════════╝  │               │
   │               │                  │                  │               │
   │               │                  │──▶ 哈希链保护 ──────────────────────▶│
   │               │                  │    (Audit Spec §5)                   │
```

**事件类型来源：** EventBus Spec v1.1 第 3 章注册表。Audit Service 自动订阅全部匹配事件。LLM Prompt+Response 作为 `detail` 字段存储，独立保留 30 天（Audit Spec §LLM）。

---

# AC 自检

| AC | 要求 | 覆盖 |
|:--:|:-----|:----:|
| AC-01 | 6 张图覆盖全部交互链 | ✅ 图1-6 |
| AC-02 | 核心执行流：JWT→Session→Plan→Capability→Connector→External→返回 | ✅ 图1 |
| AC-03 | 每张图 ≥1 审计点 | ✅ 图1(2点), 图2(2点), 图3(1点), 图4(2点), 图5(2点), 图6(全图) |
| AC-04 | 与 Security/Tenant/Audit/Runtime Spec 一致 | ✅ 图3 对齐 Security §5.1, 图4 对齐 Security §4, 图5 对齐 Security §7, 图6 对齐 Audit §6 |
