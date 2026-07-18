# Conversation Specification v1.0

## EARP 对话管理规范

**文档编号：L2-09-CONVERSATION**  
**版本：v1.0**  
**定位：L2 — 平台规范。定义 EARP 的对话管理——Conversation/Message 结构、多轮上下文管理、对话生命周期。**  
**依赖：L1/enterprise-architecture.md (Conversation 领域模型), L2-01-RUNTIME v1.3, L2-07-TENANT v1.1**

---

# 第一章：概述

## 1.1 定位

Conversation 管理用户与 AI Agent 之间的多轮对话。每轮对话生成一条 Message，多条 Message 组成一个 Conversation。

**负责：**
- Conversation 创建/管理
- Message 结构定义
- 多轮上下文窗口管理

**不负责：**
- ❌ Agent 执行（Runtime Spec）
- ❌ 对话存储引擎选择（部署视图已有）
- ❌ 前端 UI 渲染

---

# 第二章：数据模型

## 2.1 Conversation

```
MUST: Conversation 包含以下字段
  - conversation_id:  string        — 全局唯一（UUID）
  - tenant_id:        string        — 租户隔离（Multi-Tenant Spec MUST）
  - user_id:          string        — 对话发起者
  - title:            string        — 对话标题（SHOULD，可从首条 Message 自动生成）
  - status:           "active" | "archived" | "deleted"（MUST）
  - message_count:    int           — 消息数量
  - created_at:       string        — ISO 8601
  - updated_at:       string        — ISO 8601
```

## 2.2 Message

```
MUST: Message 包含以下字段
  - message_id:       string        — 全局唯一
  - conversation_id:  string        — 所属对话
  - role:             "user" | "assistant" | "system" | "tool"（MUST）
  - content:          string        — 消息内容（MUST）
  - seq:              int           — 对话内序号（自动递增）
  - metadata:         dict          — 扩展元数据（SHOULD）
    ├── model:        string        — 使用的 LLM 模型名
    ├── tokens:       int           — Token 消耗（prompt + completion）
    ├── latency_ms:   int           — 响应延迟
    └── execution_id: string | null — 关联的 Execution ID
  - created_at:       string        — ISO 8601（MUST）
```

## 2.3 MessageAttachment（可选）

```
SHOULD: Message 可包含附件引用
  - attachment_id:    string
  - message_id:       string
  - type:             "image" | "file" | "link"
  - url:              string        — 文件存储路径（S3）
  - filename:         string
```

---

# 第三章：多轮上下文管理

## 3.1 上下文窗口

```
MUST: 每次 LLM 调用时自动构建上下文窗口
  - 默认包含最近 20 条 Message（可配置）
  - 总 Token 数不超过模型上下文窗口的 80%（预留响应空间）
  - 溢出时从最早的消息开始裁剪（truncate_head）

SHOULD: 支持以下上下文策略
  - sliding_window:  固定条数（最近 N 条）
  - token_aware:     按 Token 总数裁剪
  - summarized:      对历史消息做摘要后保留（Phase 2）
```

## 3.2 System Prompt 注入

```
MUST: 每次对话的 system prompt 由 Conversation 级配置决定
MUST: system prompt 不作为 Message 存储——注入在 LLM 调用前
SHOULD: system prompt 可包含以下动态变量
  - {{user_name}}    — 当前用户名
  - {{tenant_name}}  — 当前租户名
  - {{current_time}} — 当前时间
```

---

# 第四章：对话生命周期

```
MUST: Conversation 生命周期状态
  active → 正常对话中
  archived → 用户或系统归档（不再活跃，但可查询）
  deleted → 软删除（30 天后物理删除）

SHOULD: 自动归档策略
  - 30 天无新消息 → 自动转为 archived
  - archived Conversation 不可新增 Message
```

---

# 第五章：多租户隔离

```
MUST: Conversation 和 Message 按 tenant_id 隔离
MUST: 查询时自动注入 WHERE tenant_id = current_tenant()
MUST: 不可跨租户访问对话
```

---

# 第六章：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec v1.3 | Message.metadata.execution_id 关联 Execution |
| Multi-Tenant Spec v1.1 | tenant_id 隔离 |
| Audit Spec v1.1 | Conversation 创建/归档 → 审计事件 |
| LLM 安全（Security Spec §4） | 用户输入经过 InputGuard 后存储为 Message |
