# Resource Specification

## EARP 资源规范

**文档编号：L2-04-RESOURCE**
**版本：v1.0**
**定位：L2 — 平台规范。Resource Manager 管理 Runtime 执行所需的底层资源。Resource 不属于业务能力——Capability 表达"做什么"，Resource 表达"用什么做"。**

---

# 第一章：概述

## 1.1 定位

Resource Manager 管理 Execution 使用的底层执行资源。Resource 不属于业务能力。

### 边界

**负责：** 资源注册、分配/释放、配额管理、资源池化
**不负责：** ❌ 执行业务逻辑、❌ 调用 Capability

---

# 第二章：资源类型

## 2.1 内建资源

| 类型 | 说明 | Phase |
|------|------|-------|
| llm | 大语言模型 | Phase 1 |
| python | Python 代码执行引擎 | Phase 1 |
| sandbox | 安全沙箱 | Phase 1 |
| docker | Docker 容器 | Phase 2 |
| browser | 浏览器实例 | Phase 2 |
| gpu | GPU 资源 | Phase 3 |
| remote_worker | 远程执行节点 | Phase 3 |

## 2.2 LLM

```
MUST: 包含 provider、model、max_tokens、temperature
MUST: api_key_ref 引用密钥（不存明文）
SHOULD: 支持多 Provider 负载均衡
SHOULD: 支持模型 Fallback
```

## 2.3 Sandbox

```
MUST: 文件系统隔离 / 网络白名单 / CPU/Memory 限制 / 超时
SHOULD: 支持 Python 和 JavaScript
MUST: 执行完成后清理临时文件
```

## 2.4 Browser（Phase 2+）

```
SHOULD: 支持浏览器池化
MUST: 实例独立 Cookie 和 Storage
```

---

# 第三章：生命周期

```
Available → Allocated → Released → Available
```

```
MUST: 使用前申请，使用后释放
SHOULD: 支持资源池化
SHOULD: 支持租户级配额
```

---

# 第四章：调度

```
SHOULD: 支持 FIFO / 优先级 / 公平调度
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec — Execution | 执行时申请资源 |
| Runtime Spec — Resource | 资源状态映射 Runtime Lifecycle |
