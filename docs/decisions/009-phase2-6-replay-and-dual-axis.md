# 009. Phase 2.6 工作台升级 — 双时间轴 + 验证型 ReplayClient + 中栏因果链不走 SVG overlay

**日期**：2026-06-10
**状态**：已决策
**关联 Issue**：ISS-017

## 背景

阶段 2.6（PLAN 1759-1870）把工作台从「事件列表 + 回放」升级到「壁钟甘特图 + 媒体时间线 + 因果链 + ReplayClient 回归」。落地时三处和已有抽象正面冲突，必须明确决定：

1. **`emitter` 字段**——PLAN 假设 `ReplayClient` "popleft 一条 event" 就能正确还原结构化结果，但 Phase 1A 的 `captions` / `stickers` / `masks` 子能力会在 chat_vision 调用之外**自行 publish 实体事件**到同一个 `stage` 队列。FIFO popleft 会拿到错误的事件类型。
2. **`patch_history.jsonl` / `child_event_ids` 双向索引等冗余字段**——同 ISS-015 一样，PLAN 在 IR 上还要继续加字段。
3. **中栏 SVG overlay**——PLAN 1818-1821 要求在中栏事件流上画 `<path>` 连父子卡片。但中栏是垂直滚动的卡片列表，跨卡片的虚线在视觉上比"父→子的位置关系"更难解读，跟 IDE / 文档型阅读模式相悖。

## 被否定的方案

### 方案 A：给 `VisionEvent` 加 `emitter: Literal["client", "subcap"]` 字段

ReplayClient 通过 `emitter == "client"` 过滤出 chat_vision 调用事件，跳过子能力直接 publish 的实体事件。

否定原因：

- 引入 schema 字段意味着 pydantic / zod / TS 三处同步、jsonl 旧文件迁移、所有发 entity event 的子能力代码（captions / stickers / masks 等）必须显式标注 `emitter="subcap"`，否则默认值会把它们误判为 chat_vision 事件。
- 信息冗余：`ir_value` 的形状已经能区分。chat_vision 事件携带 *call schema*（如 `CaptionsRawResult` 是 `{captions: list[_CaptionRaw]}`）；实体事件携带 *entity schema*（如 `Phase1ACaptionEvent` 是 `{style: ..., start: float, end: float, ...}`）。pydantic 的 `model_validate` 在两者间的判别已经是确定性的。
- 与 D11 / D13 的"事件即真理源"语义冲突：D11 强调事件流是 LLM 决策的可观测层，加 `emitter` 反而把生产侧元数据塞进可观测对象。

### 方案 B：在中栏事件流上加 SVG `<path>` overlay

PLAN 原文方案。`CausalChainOverlay` 监听每张卡片的 `DOMRect`（ResizeObserver + forwardRef），在中栏底部画 SVG `<path>` 把父子卡片连起来。

否定原因：

- 中栏是**纵向滚动列表**。当一个调用链跨度大（如 `1A.captions` 调用 → 多帧后才出现的 `verify_caption_anim`），dashed 路径会**穿越大量无关卡片**，视觉上看起来像噪音而不是信号。坐标映射型视图（甘特图：横轴是时间；媒体时间线：横轴是视频秒）天然适合 SVG dashed 路径——空间布局已经隐含因果方向。
- DOMRect-based overlay 必须订阅滚动 / resize / 字体加载等多源事件，并且每次 React reconcile 后要再 sync 一次。一旦中栏的事件分组 / 折叠 / 过滤模式发生变化（已有的 `streamViewMode: "by_stage" | "by_arrival"`），所有线段都要重算。复杂度 / 收益比明显倒挂。
- 本质上"父→子"的可解释性诉求是"我能从 A 跳到 B"+"hover A 时知道 B 在哪儿"。这两件事用 inline pill（"↳ parent: 1A.captions · ..." / "↱ N children"）+ 跨视图 `hoveredChainRoot` 高亮就完整覆盖了，且不依赖 DOM 几何。

## 最终决策

四个子决策一并落地（决策 4 是同日二次核查后追加的架构修订）：

1. **`ReplayClient` 用 schema 验证过滤队列**。构造时按 `stage` 把每条事件入 FIFO；`chat_vision(schema=T)` 调用时 popleft 队首事件，尝试 `T.model_validate(ev.ir_value)`，验证失败的事件直接丢弃（它们必然是同 stage 但不同 schema 的实体事件）；验证成功的事件作为返回值的来源。`ir_value=None` + `severity="warning"` 的旧 fallback 事件特殊处理为返回 `_construct_default(schema)`，与真实客户端 fallback 行为一致。
2. **`_build_event` 始终写 `ir_value`**。即使 chat_vision 调用没有 `ir_target_template`（如 `1A.captions` / `1A.stickers`），也把 `parsed.model_dump()` 写进 `ir_value`。这让 ReplayClient 不依赖额外字段就能还原任何 chat_vision 事件的结构化输出。语义解读：`ir_value` 从"要写到 IR 的值"放宽为"AI 产生的结构化输出"，IR 写入由 `ir_target` 是否为空驱动。前端 `lodash.set` 路径已经守卫了 `ir_target` 为空的情况。
3. **中栏因果链走 inline pill + 跨视图 hover sync**。每张事件卡片上挂两类 `ChainAnchorPill`：父卡片 anchor（"↳ {parent stage · label}"）/ 子卡片 anchor（"↱ {child stage · label}"，最多展示 5 条）。点击 anchor → `setSelected(targetId)` 直接跳转；hover anchor → 写入 `hoveredChainRoot` Zustand state；甘特图 / 媒体时间线 / 中栏其他卡片用 `useChainHighlight` hook 计算被高亮事件的祖先 + 后代闭包，给对应横条 / marker / 卡片加 accent border。SVG `<path>` 因此只在两个坐标映射型视图（甘特图 + 媒体时间线）画——它们各自的 SVG 容器内就能完成，不需要额外的 overlay 层。
4. **甘特图 + 媒体时间线的聚合落在客户端**（同日二次核查修订 PLAN 1790-1791）。原方案是 backend 提供 `GET /api/tasks/{tid}/gantt` + `/media-timeline` 两个聚合端点，前端按事件流到达（`liveEventCount` 依赖）反复 fetch；二次核查发现：(a) `_RESOURCE_DIRS` 与 `tasks.py::_resolve_normalized_media_url` 重复定义、违反 D1 单一真理源；(b) SSE 已经把每条事件推到工作台 store，store 同时承载 IR 快照写入；后端再做一次按 stage / media_ts 聚合是把同一份数据在两端各算一次；(c) "live 期间每来一条事件就 fetch 一次"放大成 N 次 HTTP 往返聚合 N 个事件——长视频 Phase 3 的 500+ 事件即 500 次重复请求。这三条都是"在原方案上打补丁"才能解决（debounce / ETag / 移共享路径表），都不是第一性原理。
   第一性原理修复：聚合是数据形状的纯函数，应该在数据自然汇聚的地方算一次。SSE → workbench store 是数据自然汇聚处。聚合改为 `frontend/src/lib/aggregateEvents.ts` 的 `buildGantt(events)` / `buildMediaTimeline(events)` 纯函数，配 `React.useMemo` 在 store events 变化时增量重算。视频 URL 已由 `task.normalized_media_url`（D27）提供，视频时长由 `<video>` 的 `loadedmetadata` 给。后端 `events.py` 因此回到 Phase 2.6 之前的最小职责（SSE + history endpoint），删除 ~150 行重复逻辑。
   附带修了甘特图横条的"超前 1 秒"显示 bug——原服务端实现把 `start_ms = epoch - origin` 当作开始时间，但 `event.timestamp` 是 chat_vision 调用 *结束* 那一刻（`_build_event` 在调用返回后才构造事件）。客户端聚合明确写为 `start_ms = (timestamp_epoch - duration_ms) - origin`、`end_ms = timestamp_epoch - origin`，`origin = min(timestamp - duration_ms)`，与 perf_counter 计时口径一致。

## 已知代价

### 代价 1：`ReplayClient` 不能区分两类 chat_vision 事件如果它们 schema 完全相同
理论上若两个不同的 chat_vision 调用 stage 相同且 schema 相同（且都不带特征 `ir_target.path`），FIFO popleft 仍依赖事件持久化顺序保持稳定。当前 Phase 1A / 1B 没有这种 stage，但未来若新增需要刻意保证调用顺序与持久化顺序一致。
**Followup**: 暂不追踪 — 若未来确实出现，单测 `test_golden_runs.py` 的失败信号会精确指向该 stage，触发再设计的契机；现在不假想其存在性。

### 代价 2：`ir_value` 语义放宽，存量数据无 `ir_value` 的旧 jsonl 走 fallback 路径
存量 Phase 1A / 1B 跑的 events.jsonl 里 `1A.captions` / `1A.stickers` 的 chat_vision 事件 `ir_value=None`（旧 `_build_event` 行为）。`ReplayClient` 会把它们当 fallback 处理，返回 `_construct_default(schema)`——下游 captions 实体在 ReplayClient 模式下不会复现。
**Followup**: future-plans/002-replay-old-recordings.md — 仅当我们决定要回放 v3.3 之前录制的 events.jsonl 时再处理（届时写一个 schema migration 脚本即可，不进入 v1 范围）。

### 代价 3：中栏没有 SVG dashed 路径
跨卡片的因果链需要用户依靠 hover 时的全屏 accent border 串联。在卡片之间间隔很大（如长视频 9 step 流水线）时不如 dashed 路径直观。
**Followup**: 暂不追踪 — 媒体时间线 + 甘特图视图都包含 dashed 路径；用户对"全局因果图"的需求都能切到这两个视图满足。中栏定位为"线性卡片阅读"，不强求承载全局图谱。

## 不在本期范围

- **甘特图 lane 折叠 / 长视频 500+ 事件性能优化**——v1 用 visx React reconcile 渲染 + vertical scroll，长视频实测可能掉帧。先观察实际跑 Phase 3 时的体感。
**Followup**: future-plans/003-gantt-virtualization.md — 当 Phase 3 落地后若 FPS < 30 再处理。
- **golden_runs 自动 record + commit 流水线**——v1 是手动跑 `record_golden.py` + 人工 review + 手动 commit。
**Followup**: 暂不追踪 — 自动化反而会让 fixtures 静默漂移，违反 PLAN 1786 "review 强制"。
