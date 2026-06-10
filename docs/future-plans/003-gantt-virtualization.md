# 003 — WorkbenchGantt 视图大数据虚拟化

**登记日期**：2026-06-10
**关联**：`decisions/009-phase2-6-replay-and-dual-axis.md` 不在本期范围 1

## 背景

Phase 2.6 的 `WorkbenchGantt.tsx` 用 visx + React reconciliation 增量渲染 `<rect>` / `<line>` / `<path>`。短素材抽取 Phase 2 的 ★MVP 闭环典型 ~30 个事件，长视频 Phase 3 的 9-step 流水线 + 多 Section 套模板会把事件量推到 500+ 甚至 1000+。

虽然 visx 的 React 自带最小重渲染，但 SVG `<rect>` 数量超过 ~1000 时浏览器渲染 / 命中测试都会变慢，体感 FPS 下降。本期没有 Phase 3 真实数据可以测，先不做虚拟化。

## 触发条件

满足以下任意一条时把这个规划提上议程：

- Phase 3 落地后实测 FPS < 30 且 CPU 占用 > 50%（用 Chrome devtools Performance tab 验证）。
- 单次 task 事件量稳定超过 1000（如 LLM 重试机制改变后频次提升）。
- 用户主观抱怨"甘特图卡顿"——主观信号也是触发条件，但需要先验证再上虚拟化（避免滥用）。

## 方案概述

两条互补的优化路径：

1. **基于视口的剔除**：当事件 `start_ms` < 当前视口左边或 > 视口右边时不渲染对应 `<rect>`。`@visx/zoom` 已经暴露当前的 `transformMatrix`，可以推算可见 X 范围。这是最便宜的优化，应该最先做。
2. **Lane 折叠**：默认折叠近 5 秒内没有事件的 lane（`<rect>` 数量按 lane 数线性减少）。鼠标点击展开按需。

两条路径都不需要换底层渲染库，只需要在 `lane.events.map` 之前加 filter。

## 风险与依赖

- 视口剔除会让"快速滚轮缩放"出现 pop-in 闪烁——需要外加少量 padding（如视口外 ±20%）做缓冲。
- Lane 折叠会改变默认视图的"信息密度感"，需要明确状态展示（如 lane header 加"折叠 N 项"角标）。

## 与当前实施的关系

当前实施：vertical scroll 已经让 lane 数不受视口高度限制；DOM 节点数仍随事件数线性增长。Followup 落地后 DOM 节点数对视口可见区线性，对总事件数次线性。
