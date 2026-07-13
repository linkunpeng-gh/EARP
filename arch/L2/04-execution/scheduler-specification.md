# Scheduler Specification

## EARP 调度器规范

**文档编号：L2-04-SCHEDULER**
**版本：v1.0**
**定位：L2 — 平台规范。Scheduler 负责管理触发方式和定时任务调度，是 Coordination Runtime 的一部分。**

---

# 第一章：概述

## 1.1 定位

Scheduler 管理所有触发方式和定时任务调度，属于 Coordination Runtime。负责将外部事件转化为 Runtime Request。

### 边界

**负责：**
- Trigger 注册与生命周期
- 触发条件评估
- 生成 Request 提交给 Runtime

**不负责：**
- ❌ 执行（Execution Runtime 负责）
- ❌ 规划（Planner 负责）

---

# 第二章：Trigger 类型

## 2.1 内建 Trigger

| 类型 | 说明 | 配置 |
|------|------|------|
| cron | 定时触发 | cron 表达式、时区 |
| event | 事件触发 | 事件类型、过滤条件 |
| webhook | HTTP 回调 | endpoint、签名验证 |
| message | 消息触发 | 队列类型、Topic |
| condition | 条件触发 | 条件表达式、评估频率 |

## 2.2 CronTrigger

```
MUST: 标准 5 字段 Cron 表达式
SHOULD: 支持时区配置（默认 UTC+8）
示例： "0 8 * * 1-5" → 工作日上午 8:00
```

## 2.3 EventTrigger

```
MUST: 指定监听事件类型
SHOULD: 支持事件属性过滤
示例： event_filter: "runtime.execution.failed AND error_code == 'CONNECTOR_ERROR'"
```

## 2.4 WebhookTrigger

```
MUST: 提供唯一 endpoint
MUST: 支持 HMAC-SHA256 签名验证
SHOULD: 支持 IP 白名单
```

## 2.5 MessageTrigger

```
MUST: 指定队列类型和 Topic
```

## 2.6 ConditionTrigger

```
MUST: 定义条件表达式和评估频率
示例： condition: "temperature > 50 AND status == 'running'"
```

---

# 第三章：生命周期

```
Registered → Active → Paused ↔ Active → Expired → Removed
```

```
MUST: Active 状态才被评估
SHOULD: 支持暂停/恢复
SHOULD: 支持过期自动 Deactivate
MUST: trigger_log 保留 30 天
```

---

# 第四章：执行

```
Trigger Fired → Scheduler → Request → Runtime(Planner → Execution → Result)
```

```
MUST: 每个触发生成一个 Runtime Request
MUST: Request 含 trigger 来源信息
SHOULD: 支持并发控制（同一 Trigger 不重叠执行）
MUST: 触发后 5 秒内生成 Request
SHOULD: 支持去重
```

---

# 附录：规范依赖

| 规范 | 关系 |
|------|------|
| Runtime Spec | Trigger 生成 Request |
| Coordination Runtime | Scheduler 是 Coordination 一部分 |
