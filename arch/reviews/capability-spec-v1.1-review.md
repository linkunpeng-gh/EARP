# Capability Center Spec 优化版评估

对 L2 Freeze v1.1 优化版逐项评估。

---

## 总体结论

**方向完全正确，进入工程实现的 L2 要求全部满足。**

相比 v1.0，优化版在三个关键点上做了正确收敛：

1. **Capability = Execution Description（不是 Execution）** — 解决了 Capability 与 Execution 边界模糊问题
2. **Resolution Engine** — 统一了 Capability 调用入口，填补了"Planner 直接检索 Registry"的设计空白
3. **Graph 增加执行约束** — 从纯语义升级为语义+执行约束，Graph 可直接用于决策

---

## 逐条评估

### 明确边界 — ✅ 完全同意，v1.0 没做好

v1.0 的边界只隐含在正文中，没有显式声明。你的做法"把不做什么写在前面"是更正确的 L2 规范写法。

### Capability 三层结构 — ✅ 关键收敛

| 层 | 职责 | 与 v1.0 对比 |
|---|------|-------------|
| Definition Layer | 语义 | ✅ v1.0 有 |
| Execution Contract | 调用契约 | ✅ **v1.0 没有独立成层** |
| Policy Layer | 治理 | ✅ v1.0 有 |

v1.0 把这三层混在 Metadata 中。拆开后每层的变更频率相互独立。

### Graph 增加执行约束 — ✅ v1.0 最大的缺失

你的 `parallel_allowed / sequence_required / transaction_boundary` 决定了 Execution Runtime 如何调度。没有这些，Planner 生成的 Plan 可能违反底层 Capability 的执行限制。**这个改动将 Graph 从"知识层"升级为"可执行层"**。

### Resolution Engine — ✅ 正确填补

v1.0 中 Planner 直接调 Registry Discovery，缺少中间层。Resolution Engine 的 `fallback_capabilities` 和 `composition_plan` 是 Planner 真正需要的——不只需要"选哪个"，还需要"不行怎么办、可以怎么组合"。

### Capability Invocation Flow — ⚡ Execution Contract Build 可简化

```
Resolution → Policy Check → Execution Contract Build → Dispatch → Result
```

Contract 是 Capability 声明时自带的静态信息，不需要运行时 Build。建议简化为：

```
Resolution → Policy Check → Dispatch → Result
```

### Lifecycle — ✅ 命名更准确

Removed → Retired，语义更好。建议补充一条：**Deprecated 应继续参与 Graph（提供备用方案），仅在 Discovery 排序时降低优先级。**

### 与 Runtime / Planner 边界 — ✅ 最重要的收敛点

| 模块 | 职责 |
|------|------|
| Capability Center | "有哪些能力" |
| Planner | "怎么组合能力" |
| Decision Engine | "是否执行" |
| Execution Runtime | "执行能力" |

四个职责互不重叠，一个改动不影响另外三个。这是整个优化中最有价值的变更。

---

## 差异总表

| 维度 | v1.0 | 优化版 v1.1 | 判断 |
|------|------|------------|------|
| Capability 结构 | Metadata 混合 | 三层独立 | ✅ 更好 |
| Graph | 纯语义（7 种关系） | 语义+执行约束 | ✅ **关键升级** |
| Resolution Engine | 无 | 新增 | ✅ **正确填补** |
| Planner 接入 | 直接搜 Registry | 通过 Resolution | ✅ 更好 |
| Fallback | 无 | fallback_capabilities | ✅ |
| Composition Plan | 无 | composition_plan | ✅ |
| 边界声明 | 隐式 | 显式 | ✅ 更好 |
| 可进 L3 | 带风险 | 风险显著降低 | ✅ |

---

## 建议合并的最终结构

```
Capability Center
│
├── Definition Layer（语义）
├── Execution Contract Layer（契约）
├── Policy Layer（治理）
│
├── Lifecycle Manager
├── Capability Graph（语义+执行约束）
├── Resolution Engine（检索+过滤+排序）
└── Registry（存+查）
```

Invocation Flow 简化为：`Resolution → Policy Check → Dispatch → Result`
