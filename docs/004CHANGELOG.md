## [2026-06-10-2] feat(phase2-6): wire wall-clock gantt + media-timeline + causal chain + ReplayClient regression [ISS-017]

### 改动

Phase 2.6 完整落地：工作台升级为「事件流 + 壁钟甘特图 + 媒体时间线」三视图共享 `selectedEventId` / `hoveredChainRoot` / events 数据；新增 ReplayClient 把历史 events.jsonl 反向当 IR 形状回归 fixture。四个第一性原理决策（详见 `decisions/009-phase2-6-replay-and-dual-axis.md`）替代 PLAN 原方案：

1. ReplayClient 用 schema 验证过滤队列代替新增 `emitter` 字段（避免 schema 迁移 + 实体事件全量改造）；
2. `_build_event` 始终落地 `ir_value`（让 ReplayClient 不依赖 ir_target 就能复原结构化输出）；
3. 中栏因果链走 inline `ChainAnchorPill` + 跨视图 hover sync 而非 SVG `<path>` overlay（垂直滚动列表上跨卡片虚线视觉噪音 > 信号）；
4. 甘特图 + 媒体时间线的聚合落客户端（`frontend/src/lib/aggregateEvents.ts`），不引入 backend `/gantt` + `/media-timeline` 端点——同一 SSE 流既给 store 写 IR 快照也给视图算聚合，单一真理源；同日二次核查时识别出原"backend 聚合 + live fetch"方案违反 D1 + 触发 N×N 重复请求，切回客户端 useMemo 增量计算。

二次核查（同日）顺手修了原方案里的几处 P0 / P1：(a) 甘特图横条本来按 `start = event.timestamp` 渲染，但 `event.timestamp` 是 chat_vision 调用结束时间——客户端口径改为 `start_ms = (timestamp_epoch - duration_ms) - origin` / `origin = min(timestamp - duration_ms)`，与 perf_counter 计时口径一致；(b) 媒体时间线的 `<rect>` scrub overlay 原放在 SVG 末尾（z-order 最上），把所有 marker 的 onClick 都吃掉了——改放第一位（z-order 最下），markers 在上拦截各自点击，空白处 fall-through 到 scrub；(c) 甘特图原 `yScale.range = [0, max(innerH, lanes×LH)]` 让超量 lane 渲染到 SVG 视口外但 SVG 不滚动 → 改 SVG height = totalSvgHeight、外层 `overflow-y-auto`；(d) `record_golden.py` 用 `template["ir_json"]` 但 `kb_store.get_template` 返回的字段名是 `ir`（pydantic 已经 round-trip 过）——KeyError 早晚会犯，按 KB 实际形状改 `template["ir"]`。

- backend/app/ir/vision_event.py: VisionEvent 增 `media_ts: float | None` 与 `media_ts_range: tuple[float, float] | None` 双时间轴字段；docstring 写明 frame_ts/wall-clock vs media_ts/视频媒体时间的语义边界
- backend/app/llm/client.py: 新增 `_media_ts_from_frames(frames)` helper（0 frames → 双 None；1 frame → media_ts；>1 frames → media_ts_range = (min, max)）；`_build_event` 与 `_fallback` 调用 helper 自动填两字段；`_build_event` 即使 `ir_target=None` 也写 `ir_value = parsed.model_dump(mode="json")`
- backend/app/llm/replay_client.py（新增）：`ReplayClient(LLMClient)` 用 `dict[stage, deque[VisionEvent]]` 索引；`chat_vision/chat_text` 走统一 `_serve()`：popleft 队首，schema 验证失败的事件直接丢弃（同 stage 但不同 schema 的实体事件），验证成功的事件作为返回；`ir_value=None + severity="warning"` 特殊处理为 `_construct_default(schema)`；`_republish` 用当前 task_id 把事件转发到活跃 bus；`ReplayExhaustedError` 携带 stage + 剩余队列长度
- backend/app/api/events.py: 经二次核查精简——保留原有 SSE 推送和历史回放端点，不新增聚合端点；删除原方案里的 `_RESOURCE_DIRS` / `_resolve_normalized_url` / `_video_duration_seconds` / `_short_event_payload` / `_STAGE_COLOR_TOKENS` / `_stage_color` 等聚合辅助（约 150 行），把工作台聚合让给前端（见 frontend/src/lib/aggregateEvents.ts）。模块 docstring 写明"events.py 仅做 SSE + history endpoint，聚合视图由前端从同一份事件流投影"
- backend/app/extract/{captions,stickers,masks,scenes,captions_anim,motion}.py: 实体级 / 跨段级事件构造时显式填 `media_ts`（单帧锚点）或 `media_ts_range`（如 caption 起止 / scene 起止 / zoom 曲线覆盖的 scene 区间）；CV 主路径 / VLM 兜底分支均同步
- scripts/record_golden.py（新增）：typer CLI `record_golden --sample SID`——用真实 LLM client 跑 `extract_template(SID)`，完成后把 events.jsonl + KB ir_json 写入 `tests/fixtures/golden_runs/{SID}/{events.jsonl, template.json}`；不自动 git add（强制人工 review，PLAN 1786）
- scripts/check_media_ts.py（新增）：CI 守卫——AST 扫描所有 `VisionEvent(...)` 构造调用，凡传 `frame_url=` 的必须同时传 `media_ts=` 或 `media_ts_range=`
- backend/tests/integration/test_golden_runs.py（新增）：parametrize over `tests/fixtures/golden_runs/{sid}/`；构造 `ReplayClient(events.jsonl)` → monkey-patch `app.llm.client.get_llm_client` → 跑 `extract_template(sid)` → 与 `template.json` 做深度 diff（jsonpatch 风格的字段路径 diff）；目录空时 parametrize 空集自然为 no-op
- backend/tests/unit/test_phase2_6.py（新增）：7 项单测覆盖 `_media_ts_from_frames`（0/1/many frames）/ VisionEvent 默认值 / ReplayClient（成功复原 / 跳过实体事件 → 队列耗尽 / fallback 事件返回默认 schema）；二次核查后聚合相关测试迁到前端 `aggregateEvents.test.ts`（聚合落客户端，单测随之迁移）
- tests/fixtures/golden_runs/README.md（新增）：录制 / review / commit 流程说明 + 何时需要重录（IR 字段语义变更 / prompt 改变结构化输出 / 新模型上线）+ CI 集成说明
- .github/workflows/ci.yml: python job 加 `media_ts guard`（Phase 2.6 dual-axis）+ `Golden-runs regression`（CPU-only pytest，0 API key 依赖）
- frontend/package.json: 加 `@visx/{group,responsive,scale,text,zoom}@^3.12.0`（visx 模块化按需引入）
- frontend/src/state/workbench.ts: 新增 `WorkbenchView = "list" | "gantt" | "media_timeline"`；store 增 `view`（默认 list）/ `currentMediaTs`（媒体时间线播放头）/ `hoveredChainRoot`（跨视图因果链高亮根）三态 + 对应 setter；`reset(taskId)` 不重置 `view`（URL 是真理源）
- frontend/src/lib/aggregateEvents.ts（新增）：`buildGantt(events)` + `buildMediaTimeline(events)` 两个纯函数 + `GanttEvent` / `GanttLane` / `GanttPayload` / `MediaTimelineMarker` / `MediaTimelinePayload` 类型；甘特图 bar 时间口径硬约束 `start = (timestamp_epoch - duration_ms) - origin` / `end = timestamp_epoch - origin`；stage 颜色复用 `EventBadge.badgeColor` phase-prefix 映射
- frontend/src/lib/aggregateEvents.test.ts（新增）：vitest 覆盖 buildGantt 时间口径正确（call END 不是 START）+ origin 对齐 + 0-duration tick + lane 排序 + 空输入；buildMediaTimeline 过滤无 media_ts* 事件 + 升序排序 + 颜色 token 注入
- frontend/src/types/workbench.ts: VisionEvent 镜像增 `media_ts: number | null` + `media_ts_range: [number, number] | null`
- frontend/src/pages/WorkbenchGantt.tsx（新增）：visx `ParentSize` + `scaleLinear`（X 轴 ms）+ `scaleBand`（Y 轴 stage lane）；`Zoom` 处理 X 轴滚轮缩放 / 拖拽平移 / Shift+滚轮横向滚动 / 模态键无修饰滚轮 fall-through 给外层 wrapper 做纵向滚动；事件读 `useWorkbenchStore.events` + `useMemo(buildGantt, ...)` 派生，不发 HTTP；duration_ms > 0 渲染为 `<rect>`，== 0 渲染为 `<line>`；父子事件用 quadratic Bezier `<path>` dashed 连接；选中 / 因果链 hover 时 stroke 切 accent；外层 wrapper `overflow-y-auto`，SVG height = lanes × LANE_HEIGHT，超长内容时纵向滚动看后续 lane（甘特图 bar 时间口径见 D40）
- frontend/src/pages/WorkbenchMediaTimeline.tsx（新增）：顶部嵌入 `<video src={videoUrl} controls>`（videoUrl 由 Workbench.tsx 从 `task.normalized_media_url` 透传，不另外 fetch），`onLoadedMetadata` 读视频时长，`onTimeUpdate` 推 `currentMediaTs`；按 stage 分 lane；`media_ts` marker 渲染为三角形 polygon，`media_ts_range` 渲染为半透明 rect；事件读 `useWorkbenchStore.events` + `useMemo(buildMediaTimeline, ...)` 派生；`currentMediaTs` 处画 accent 竖线（pointer-events:none 不挡 marker 点击），±0.5s 邻域内 marker 加 accent 描边；scrub 透明 `<rect>` 放 SVG 子节点首位（z-order 最下），markers 在它上面，markers 自身的 onClick 不被 scrub 拦截
- frontend/src/components/workbench/CausalChainOverlay.tsx（新增）：3 个公开导出——`useChainResolver()` 解析事件的 immediate parent + 子事件（最多 5 条 short label）；`useChainHighlight()` 计算 hoveredChainRoot 的祖先 + 后代闭包 set；`ChainAnchorPill` 渲染单个 inline anchor（hover 写 hoveredChainRoot，点击调 setSelected 跳转）；docstring 详细说明为什么不画 SVG overlay（决策详见 009 文档）
- frontend/src/components/workbench/WorkbenchEventStream.tsx: EventRow 从 `<button>` 改为 `<div role="button">`（避免嵌套 button HTML 警告，keyboard accessibility 由外层 ↑↓ 监听承担）；旧 `parentLabel` prop 替换为 `chain: ChainAnchorInfo` + `inChainHighlight: boolean`；卡片底部用 `ChainAnchorPill` 渲染 parent / children 锚点；`inChainHighlight` 时加 ring 高亮；rowRefs 类型从 HTMLButtonElement 改为 HTMLDivElement
- frontend/src/pages/{WorkbenchGantt,WorkbenchMediaTimeline}.tsx: 接入 `useChainHighlight()`；`onMouseEnter/Leave` 设置 hoveredChainRoot；inChain 时 stroke 切 accent，让中栏 hover 一条 anchor → 甘特图 / 媒体时间线对应横条 / marker 同步亮起
- frontend/src/pages/Workbench.tsx: 顶栏新增 3 选 1 segmented control（三栏列表 / 壁钟甘特图 / 媒体时间线）；新增 `useViewParam` hook 实现 URL `?view=` ↔ store.view 双向同步（URL 是真理源）；list 模式渲染原 3 栏布局，gantt / media_timeline 模式渲染对应全宽 page 组件；切换不重 fetch（events 数据走同一 store）；`videoUrl={task?.normalized_media_url}` 透传给媒体时间线复用同一份 task status

### 涉及文件

- backend/app/ir/vision_event.py：VisionEvent 双时间轴字段
- backend/app/llm/client.py：media_ts 自动填充 + ir_value 始终落地
- backend/app/llm/replay_client.py：ReplayClient + 验证型 FIFO 过滤
- backend/app/api/events.py：聚合端点删除 — 二次核查后只保留 SSE + history（聚合落前端）
- backend/app/extract/{captions,stickers,masks,scenes,captions_anim,motion}.py：实体事件 media_ts / media_ts_range
- scripts/record_golden.py：golden_runs 录制 CLI
- scripts/check_media_ts.py：媒体时间线字段守卫
- backend/tests/{integration/test_golden_runs,unit/test_phase2_6}.py：回归 + 单测
- tests/fixtures/golden_runs/README.md：种子文件规范
- .github/workflows/ci.yml：media_ts 守卫 + golden-runs job
- frontend/package.json：visx 5 个 sub-package
- frontend/src/state/workbench.ts：view / currentMediaTs / hoveredChainRoot
- frontend/src/lib/aggregateEvents.ts + .test.ts：客户端聚合纯函数 + vitest
- frontend/src/types/workbench.ts：双时间轴字段镜像
- frontend/src/pages/{WorkbenchGantt,WorkbenchMediaTimeline}.tsx：两个新视图页
- frontend/src/components/workbench/CausalChainOverlay.tsx：useChainResolver / useChainHighlight / ChainAnchorPill 三件套
- frontend/src/components/workbench/WorkbenchEventStream.tsx：div role=button + ChainAnchorPill 接入
- frontend/src/pages/Workbench.tsx：view 切换 + URL 双向同步

### 关联

-> ISS-017
-> decisions/009-phase2-6-replay-and-dual-axis.md

---

## [2026-06-10-1] docs: rewrite 002STRUCTURE.md for external readers + add 006API.md placeholder [ISS-016]

### 改动

按外部新工程师视角重写 `002STRUCTURE.md`，剔除内部进度标签与函数级细节，让"第一次接手"的人能在 1 分钟内定位代码（呼应 `000README.md` 的判断标准）。同时新增 `006API.md` 占位文档作为接口侧的"带场景导览"。本轮不动 `001ARCHITECTURE.md`（D1–D37 精简留待后续 issue）。

- docs/002STRUCTURE.md（重写）：结构由 ~250 行扁平树改为按主目录分组——每个目录段落先有 2–4 句平白导语介绍它的角色与解决的问题，再列文件一句话职责。删除全部 `Phase 0/1A/1B/2/2.5/5` / `D1`–`D37` / `ISS-NNN` / `★MVP` 等内部进度标签；删除 `_safe(label, field_key, coro)` / `SUBCAP_TO_IR_PATH` / `subscribe_with_snapshot` 等函数与常量级细节（可 grep 的不入文档）；`VisionEvent` / `Phase1AReport` / `Patch` / `StyleRule` 等内部类型在首次出现处用平白话解释（"AI 决策记录" / "识别结果聚合数据" / "一条编辑指令" 等）。占位状态精确化：真占位（`agent/aigc.py` + `agent/__init__.py` 中 AIGC 转发）显式标 `🚧 占位（计划中）`；dev-mode 闸门控制但已实现的（`api/dev_workbench.py` / `api/lab.py` / `frontend/src/pages/WorkbenchLauncher.tsx` / `frontend/src/pages/SubcapabilityLab.tsx`、两份 `types/ir.ts` 生成产物）纠正为非占位的平白说明；`extract/motion.py` 误标占位修复（实际为 VLM 缩放方向 + OpenCV 光流曲线已落地）。补回原文档遗漏项：`docs/proposals/`、`frontend/src/vite-env.d.ts`、`frontend/src/components/editor/ProjectHistoryStrip.tsx`、`frontend/src/components/editor/StepCard.tsx`。
- docs/006API.md（新增）：占位骨架 + 命名约定 + 六条典型用户流程导览（上传 / 提取 / 出片 / 编辑 / 实时回放 / 跨页导航）+ 开发模式专用接口区段 + 渲染器内部回调区段 + 待补充清单（请求示例、错误码、鉴权说明、`/openapi.json` 索引化）。详细字段统一指向 FastAPI 自动生成的 `/docs`，不复制 OpenAPI 已有内容。

### 涉及文件

- docs/002STRUCTURE.md：按目录分组重写，剔除内部进度标签 / 函数级细节，纠正占位判定
- docs/006API.md：新增"带场景的接口导览"占位文档

### 关联

-> ISS-016


---

## [2026-06-09-8] feat(phase2-5): wire NL edit + panel edit + undo + workbench event replay + history index [ISS-015]

### 改动

Phase 2.5 完整落地：编辑链路（NL / 参数面板 / Undo）+ 重渲染节流 + 工作台事件回放页 + 提取/编辑历史入口 + 面包屑。三个第一性原理决策（详见 `decisions/008-phase2-5-edit-storage.md`）替代 PLAN 原方案：用 snapshot 栈代替 per-op inverse undo（新增 op 不需要写 inverse）；用 events.jsonl 作为 patch 真理源（不再写并行的 patch_history.jsonl）；用 30 行 `render/throttle.py` 替代独立 `render_queue.py` 模块（dict + asyncio.Lock 串行化 supersede）。

- backend/app/agent/nl_edit.py（新增）：`nl_edit` 调 Text LLM 翻译 NL 指令为 Patch 列表 + 同时发 `stage="2.5.nl_edit"` VisionEvent；`panel_to_patches` 不调 LLM 翻译参数面板字段；`apply_patches` pure-function 调度器覆盖 8 个 PatchOp + 完整 pydantic re-validate；`push_snapshot` / `undo` 实现快照栈；`list_patch_history` 通过 `tasks_store.list_by_resource` + `event_bus.replay` 聚合 patch 流
- backend/app/api/edit.py（新增）：`POST /projects/{id}/edit` / `/panel-edit` / `/undo` / `GET /history` 四个端点；每条 edit 路径都创建对应 kind 的 task（nl_edit / panel_edit / undo）并把 patch 通过 VisionEvent 持久化到 events.jsonl；统一通过 `_maybe_kick_render` 经 `BackgroundTasks → trigger_render_supersede` 触发 supersede 重渲染
- backend/app/api/replay.py（新增）：`GET /projects/{id}/replay/events` / `/replay/tasks` / `POST /replay/snapshot`，对称的 sample 三端点；`POST /workbench/{tid}/reject-event/{eid}` 发 `stage="2.5.veto"` 事件保留原事件不修改；内置 lodash.set 重放器 `_lodash_set` 支持 dotted+integer 路径与 `set/append/remove` 三 op，复用前端语义重建 IR 快照
- backend/app/api/projects.py：新增 `GET /projects/{id}/tasks` 与 `GET /projects/{id}/lineage`（迁移链审计：模板骨架摘要 + 映射 + 缺口 + edit_count）
- backend/app/api/samples.py：新增 `GET /samples/{id}/tasks` 供 SampleExtract / TemplateLibrary 详情页 ExtractHistoryList 使用
- backend/app/tasks_store.py：新增 `list_by_resource(kind, id)`（按 created_at DESC）+ `idx_tasks_resource` 复合索引（`init_db` 幂等创建）
- backend/app/render/throttle.py（新增）：`trigger_render_supersede(project_id, task_id, ir)` 用 `defaultdict(asyncio.Lock)` + `dict[project_id → in_flight_task_id]` 串行化"取出旧 + 设置新"，旧任务存在时调 `cancel_render` → renderer DELETE，再 await `render_project`
- backend/app/render/client.py：新增 `cancel_render(task_id)`（httpx DELETE 5s 超时，best-effort 不 raise）
- backend/app/main.py：挂载 `edit.router` + `replay.router`
- backend/app/llm/prompts/2_5_nl_edit.md（新增）：NL → Patch system prompt；8 op 清单 + ValueObject 字段约束 + 中文颜色映射；用户消息含 ProjectIR 摘要 / 模板骨架 / 可用模板目录
- renderer/src/queue.ts：新增 RenderState 注册表（`registerRender` / `cancelRender` / `finalizeRender`）；`queueStatus` 暴露 tracked 字段
- renderer/src/server.ts：新增 `DELETE /render/:taskId` 路由；`POST /render` 处理 callback 内查 `state.cancelled` 实现 pre-start skip 与 mid-render mark-cancelled
- frontend/src/api/index.ts：新增 11 个端点客户端方法（nlEdit / panelEdit / undoEdit / listPatchHistory / listSampleTasks / listProjectTasks / fetchReplayEvents / fetchReplayEventsForSample / snapshotAtSequence / fetchProjectLineage / rejectEvent）与配套 TS 类型
- frontend/src/components/ExtractHistoryList.tsx（新增）：通用样例/项目历史列表，kind 中文映射 + 状态色 + 相对时间
- frontend/src/components/workbench/WorkbenchBreadcrumb.tsx（新增）：Workbench 顶栏面包屑「样例 > {name} > 提取任务 #{tid}」；拉取 task → resource 链；fallback 到 `任务 #{tid}`
- frontend/src/components/editor/{NLBar,ParamPanel,PatchHistoryList}.tsx（新增）：Editor 三件套，分别负责 NL 输入栏 / 参数面板（字幕颜色/字号/位置/动画/换行字符数/placeholder/节奏/画布/BGM）/ 编辑历史 + Undo 按钮 + 工作台链接
- frontend/src/pages/Editor.tsx：升级为 `[ParamPanel | Preview+NLBar | PatchHistoryList]` 三栏布局；每次编辑都通过 `handleEditApplied` 刷新 preview + 触发 editTick 让历史栏重读
- frontend/src/pages/Visualize.tsx（新增）：`/projects/:id/replay` 与 `/samples/:id/replay` 工作台事件回放页；时间线 scrub + 0.5×/1×/2×/4× 倍速 + MediaRecorder 60s 录屏导出（webm/vp9，Safari 提示不兼容）；复用三栏 Workbench panes
- frontend/src/pages/Workbench.tsx：顶栏插入 `<WorkbenchBreadcrumb taskId={taskId}>`
- frontend/src/pages/SampleExtract.tsx：`useSearchParams` 读 `?sample_id=`（供面包屑回跳）+ 详情区底部插入 `<ExtractHistoryList resourceKind="sample">`
- frontend/src/pages/TemplateLibrary.tsx：详情页底部新增「本样例其它提取记录」段，复用 ExtractHistoryList
- frontend/src/main.tsx：新增 `/projects/:projectId/replay` 与 `/samples/:sampleId/replay` 路由
- backend/tests/integration/test_nl_edit.py（新增）：覆盖 8 个 PatchOp 的 apply_patches 行为（含 set_emphasis 子串过滤 / adjust_rhythm 钳速 / set_canvas allow-list 防越界字段 / delete_segment timeline 重组 / set_bgm 清空）+ panel_to_patches 字段表 + 3 patch → 2 undo round-trip + _lodash_set 三 op 语义 + _snapshot_payload 端到端重建 + list_by_resource DESC 排序

### 涉及文件

- backend/app/agent/nl_edit.py：NL→Patch + 调度器 + snapshot 栈 + patch 历史聚合
- backend/app/api/edit.py：edit / panel-edit / undo / history HTTP 入口
- backend/app/api/replay.py：replay events / tasks / snapshot + veto 事件
- backend/app/api/projects.py：projects/{id}/tasks + lineage
- backend/app/api/samples.py：samples/{id}/tasks
- backend/app/tasks_store.py：list_by_resource + 复合索引
- backend/app/render/throttle.py：项目级 render supersede
- backend/app/render/client.py：cancel_render
- backend/app/main.py：edit + replay 路由挂载
- backend/app/llm/prompts/2_5_nl_edit.md：NL → Patch prompt
- renderer/src/queue.ts：RenderState 注册表
- renderer/src/server.ts：DELETE /render/:taskId
- frontend/src/api/index.ts：11 个 Phase 2.5 客户端方法
- frontend/src/components/ExtractHistoryList.tsx：通用历史列表
- frontend/src/components/workbench/WorkbenchBreadcrumb.tsx：工作台面包屑
- frontend/src/components/editor/{NLBar,ParamPanel,PatchHistoryList}.tsx：Editor 三件套
- frontend/src/pages/Editor.tsx：三栏布局
- frontend/src/pages/Visualize.tsx：工作台事件回放页
- frontend/src/pages/{Workbench,SampleExtract,TemplateLibrary}.tsx：分别挂载面包屑 + 历史列表
- frontend/src/main.tsx：replay 路由
- backend/tests/integration/test_nl_edit.py：集成测试覆盖
- docs/decisions/008-phase2-5-edit-storage.md：snapshot vs inverse / events.jsonl vs patch_history.jsonl / throttle.py vs render_queue.py 三决策

### 关联

-> ISS-015
-> decisions/008-phase2-5-edit-storage.md

---

## [2026-06-09-7] feat(phase2): make ASR backend configurable + co-locate HF cache with DATA_ROOT [ISS-014]

### 改动

阶段 2 端到端验证阻塞的第一性原理修复：`Settings` 接管 ASR 模型选择 + HuggingFace 缓存路径，把项目「single source of truth」与「重资产入 DATA_ROOT」两条范式贯彻到底。`asr.py` 的字面量 `"large-v3"` 提到 `Settings.asr_model`（PLAN 1593 默认值不变，dev `.env.local` 覆盖为 `small` 即可绕开 3GB 下载）；`get_settings()` lru_cache 内 `_apply_hf_env` 把 `HF_HOME` / `HUGGINGFACE_HUB_CACHE` 默认指向 `DATA_ROOT/.cache/huggingface`（系统盘 C: 不再被吃）；操作员显式 export `HF_HOME` 时 `setdefault` 不覆盖，`hf_cache_dir=""` 整段 opt-out。顺手修了两处：CI 守卫 `check_event_emission.py` 的 EXEMPT 从前缀改子串匹配（monorepo 化后 `backend/tests/` 与 repo-root `tests/` 一视同仁），`test_apply_phase2.py` 补 `from pathlib import Path`（之前漏写被 `_safe` 静默吞成 stage_failed）。

- backend/app/config.py: `Settings` 加 `asr_model` / `asr_device` / `asr_compute_type` / `hf_cache_dir` 四字段；新 helper `_apply_hf_env(settings)` 在 `get_settings()` 返回前注入 `HF_HOME` + `HUGGINGFACE_HUB_CACHE`；`os.environ.setdefault` 保留运维显式 export 的优先级；`hf_cache_dir=""` opt-out
- backend/app/understand/asr.py: `_whisperx_run` 内 `from app.config import get_settings` lazy 读三字段传给 `whisperx.load_model`；fallback 事件 reasoning 写明当前 ASR_MODEL / ASR_DEVICE / ASR_COMPUTE_TYPE / HF_HOME 实际值，磁盘紧张时引导改 .env.local；新 helper `_hf_home_hint()` 从 env 读出 HF 实际落点
- .env: 新增 `ASR_MODEL=large-v3` / `ASR_DEVICE=cpu` / `ASR_COMPUTE_TYPE=int8` / `HF_CACHE_DIR=.cache/huggingface` 四行模板，注释列出 tiny/base/small/medium/large-v3 各档磁盘占用
- .env.local（新增）：dev override `ASR_MODEL=small`（gitignored 走 `*.env` 规则）；注释解释「磁盘紧张时改 tiny 也行」
- scripts/check_event_emission.py: `EXEMPT_FILES` 从 `rel.startswith(d)` 改成 `d in rel` 子串匹配；新 helper `_is_exempt` 写明意图「AI-client 名字守卫不该套在 fixtures/dev tools/static data 上，与路径深度无关」
- backend/tests/unit/test_config.py（新增）：6 项单测覆盖 Settings ASR 默认 / env 覆盖 / `_apply_hf_env` 注入 / 已存在 env 不覆盖 / 空串 opt-out / `get_settings()` 端到端 wiring
- backend/tests/integration/test_apply_phase2.py: 顶部补 `from pathlib import Path`（`_fake_extract_audio` 之前 NameError 被 `_safe` 静默吞掉，伪装成 bgm_mix stage 失败）
- scripts/build_bgm_index.py（新增）：扫 `data/system/bgm_pool/*.{mp3,wav,m4a,aac,flac,ogg}` → librosa 提 BPM + ffprobe header 读真实 duration → 写 `bgm_index.json`（`schema_version=1`，对齐 fonts_index.json 范式）；幂等，保留已有 `mood_tag`；首次落地 3 首（Take me hand / 懒鬼小何 / 蜜桃物语，125-136 BPM 区间），PLAN 1578 推荐 ≥ 5 的提示走 stderr 不阻塞
- backend/data/system/bgm_pool/bgm_index.json（新增）：上述脚本产物，apply 的 `_bgm_features` nearest-neighbour 选择从此不再 fallback 为空
- package.json: `dev:backend` 脚本加 `--reload-dir app`；uvicorn `--reload` 默认监听整个 cwd，HF 模型下载到 `data/.cache/huggingface/` 时频繁写入触发重启 → ASR 进程被反复打断永远跑不完。限定到 `backend/app/` 源码目录后，dev 代码热重载语义不变，运行时数据目录变化不再参与 reload 循环（第一性原理：`data/` 是运行时资产，本就不该耦合到「改源码→热重载」回路）

### 涉及文件

- backend/app/config.py：Settings 加 ASR 四字段 + HF env 注入
- backend/app/understand/asr.py：去字面量 + fallback reasoning 写明运行时配置
- .env / .env.local：模板 + dev override
- scripts/check_event_emission.py：EXEMPT 改子串匹配
- backend/tests/unit/test_config.py：6 项单测固化语义
- backend/tests/integration/test_apply_phase2.py：补 Path import
- scripts/build_bgm_index.py：BGM 索引生成脚本（librosa BPM + 真实 duration）
- backend/data/system/bgm_pool/bgm_index.json：首次入库 3 首曲目索引

### 关联

-> ISS-014
-> decisions/（无；本次修复只是把项目自己的 Settings + DATA_ROOT 范式贯彻到底，没有新方案分叉）

---

## [2026-06-09-6] refactor(phase2): unify output_span derivation, slot-local sticker time, auto BGM ducking [ISS-013]

### 改动

阶段 2 二核：三处第一性原理修复 + P2 冗余一次性清理。`PlacedSegment` 的 output_span 现在一处推算（`(src_end-src_start)/speed`）覆盖 mapping/fill/style/renderer 四个使用点，不再有 banding 漂移；模板 IR 的 sticker 时间彻底切换为 slot-local [0,1]，apply 阶段才映射成 segment-local 秒；apply 流水线新增 stage `bgm_mix`，自动跑 ffmpeg sidechain ducking 写出 `bgm_ducked.aac`；同时清掉 recommend 端点的 try/except 死代码、fill 死参、mapping 错位事件、normalize 单一 black-pad 模式四项 P2。

- backend/app/apply/mapping.py: 取消 `output_span = max(slot.min, min(slot.max, ...))` banding；speed 钳到 1.2 后 output 仍超 slot.max 则截短 `src_end = src_start + slot.max × speed`；timeline_cursor 累积值与渲染端读到的 `(end-start)/speed` 严格一致；`_slot_min` 不再被引用顺手删掉；gap_candidate 事件 `ir_target.path` 从 `sections.0.gaps` 改为 `sections.0.segments`（与 fill 后落点一致）
- backend/app/apply/style.py: 新增 `_segment_output_span(seg)` 与 `style_for_segment(slot, output_span)` 两个 helper，作为单一真理源给 mapping/fill/style/renderer 共用；segment-style copy 经过 helper 把 slot.style.stickers 的 [0,1] 映射成 segment-local 秒
- backend/app/apply/fill.py: `_wrap_segment_for` / `_reuse_segment_for` 接入 `style_for_segment`；timeline_cursor 推算改用 `_segment_output_span`；`_pivot_unit_for` 删除未使用的 `gap_idx` 形参；删除 `cur_gap.fill_result = ...` 的 in-place mutation（改由 pipeline 用 `outcome.gap_idx` 显式写回）
- backend/app/apply/pipeline.py: 在 style 后新增 stage `bgm_mix`，包在 `_safe` 中跑 `extract_audio + mix_bgm`，写出 `projects/{id}/bgm_ducked.aac` 并更新 `ProjectIR.bgm_track`；新增 `_mix_bgm_for_project` 异步包裹（asyncio.to_thread）；fill 阶段后用 `outcome.gap_idx → gaps[i].fill_result` 写回；`STAGE_TO_IR_PATH` 增 `bgm_mix` 键
- backend/app/extract/skeleton.py: `_stickers_in` 把 sticker.start/end 从样例绝对秒转换为 slot-local 归一化 [0,1]；docstring 写明 Phase 2 apply 端再映射回 segment-local 秒
- backend/app/render/ffmpeg.py: `normalize` 新增 `pad_mode: "black" | "blur"` 参数；blur 路径用 `split=2 + scale=increase + crop + boxblur=20 + scale=decrease + overlay`，PLAN 1657 的"模糊背景 letterbox"落地；black 路径保留原行为给 sample-extract 使用
- backend/app/api/projects.py: `upload_project` 用 `pad_mode="blur"`；`recommend_templates_endpoint` 删除 `transcribe()` 外层冗余 try/except（`transcribe` 设计为永不抛）+ 绝对路径 fallback（违反 D2）
- renderer/src/compositions/Project.tsx: sticker 直接用 segment-local 秒，删除 `stk.start - seg.timeline_start` 的坐标系混淆减法
- frontend/src/components/RemotionPlayer.tsx: sticker 比较时把 segment-local 秒投影回 timeline-global 秒后再与 timelineSec 比较
- backend/tests/integration/test_apply_phase2.py: 新增 5 项测试 — `test_canvas_mismatch_blur_pad_mode` / `test_mapping_timeline_is_contiguous_for_overlong_user` / `test_mapping_truncates_src_when_clamped_speed_overshoots_max` / `test_apply_style_remaps_stickers_to_segment_local_seconds` / `test_apply_pipeline_runs_bgm_mix_when_bgm_selected`
- backend/tests/unit/test_skeleton.py: 新增 `test_build_skeleton_normalizes_sticker_times_to_slot_local`

### 涉及文件

- backend/app/apply/mapping.py：取消 banding + 截短 src 兜底超长 / 修正 gap_candidate ir_target
- backend/app/apply/style.py：单一真理源 `_segment_output_span` + `style_for_segment` helper / sticker 段内重映射
- backend/app/apply/fill.py：复用 helper / 删死参 / 移除 in-place mutation
- backend/app/apply/pipeline.py：bgm_mix stage / outcomes → gaps 写回 / STAGE_TO_IR_PATH 扩展
- backend/app/extract/skeleton.py：sticker 时间 [0,1] 归一化
- backend/app/render/ffmpeg.py：normalize blur pad_mode
- backend/app/api/projects.py：upload_project blur / recommend 死代码清理
- renderer/src/compositions/Project.tsx：sticker 直接读 segment-local 秒
- frontend/src/components/RemotionPlayer.tsx：sticker timeline 投影修正
- backend/tests/integration/test_apply_phase2.py：5 项新测试
- backend/tests/unit/test_skeleton.py：sticker 归一化测试

### 关联

-> ISS-013
-> decisions/（无，沿用 ISS-010 的"补丁 → 重构"二核范式，无新方案分叉）

---

## [2026-06-09-5] feat(phase2): close MVP loop — ASR + recommend + apply + multi-segment render [ISS-012]

### 改动

Phase 2 ★MVP 端到端闭环落地：短素材（10–20s 一镜到底口播）+ KB 模板 → ASR 对齐 → 映射 → 缺口补全 → 套风格（含字幕 emphasis_words + zoom keyframes + 贴纸占位 + BGM features/original 选择）→ Remotion 多 PlacedSegment 渲染 → MP4。`apply/` 新包沿用 1B 的 `_safe(label, ir_path, coro)` 降级范式 + `STAGE_TO_IR_PATH` 翻译表，让 `ProjectIR.degraded` 与 `TemplateIR.degraded` 命名空间对称；前端 `/editor` 五步闭环页 + CSS-based `RemotionPlayer` 即时预览（不打包 Remotion bundle 到前端，避免重复源）。

- backend/app/ir/project.py: `ProjectIR` 新增 `degraded: dict[str, str]` 与 TemplateIR 对称
- backend/app/understand/asr.py（新增）: WhisperX large-v3 lazy import；缺包/CUDA OOM/空输出时 fallback 到 ffprobe duration + 等距 ~3s 分段，发 `severity=warning` 事件不阻塞 pipeline
- backend/app/kb/recommend.py（新增）: 一次 VLM call 看 ≤50 模板 + 3 帧 + ASR 摘要前 200 字，输出 top-k 推荐；每条推荐发 stage="2.recommend" 事件；VLM 返空 / template_id 越界时按 KB 目录顺序兜底
- backend/app/apply/__init__.py / mapping.py / gaps.py / fill.py / style.py / pipeline.py（新增）：mapping 按 Unit 时间顺序绑定 voice slot；speed 钳制 ±20%；溢出 / 不足分别一次性 warning；gaps 按 material_req 分类 text_fill / wrap_fill / reuse；fill 用 placeholder + length_constraint + semantic_purpose 作 LLM 文案锚点，wrap/reuse 段速度让 output_span = slot.nominal 保持 timeline 连续；style 逐 Unit 调 LLM 选 emphasis_words（≤3 个、必为 Unit.text 子串、D11 严守 Caption.text = Unit.text）；BGM 按 BGM_STRATEGY 走 features (bgm_index.json 最近邻) / original 双路径
- backend/app/render/ffmpeg.py: 新增 `extract_audio` / `mix_bgm`(sidechaincompress + ducking) / `compose_segments`(filter_complex trim+atempo+concat)
- backend/app/api/projects.py: `POST /projects` 已有；新增 `/recommend-templates` (sync VLM call + 帧采样事件流) / `/apply` (BackgroundTask 跑 apply_short) / `GET /projects/{id}` (返回 ProjectIR) / `GET .../preview-props` (精简 props 喂前端 player) / `POST .../render` / `POST .../mix-bgm` (dev hook)
- backend/app/llm/prompts/{2_recommend, 2_caption_emphasis, 2_fill_gap}.md（新增）：三组 Phase 2 prompt 模板，placeholder/length_constraint/semantic_purpose 作视觉锚点
- renderer/src/compositions/Project.tsx: 重写从"取 segments[0]"假设升级为多 Sequence 渲染——每段 ZoomLayer + per-seg Mask + per-seg Sticker；全局 ColorLayer 包 video stack；BGM `<Audio>` 走 inputProps.bgmUrl；OffthreadVideo 加 playbackRate 跟随 speed
- renderer/src/compositions/Caption.tsx: 新增 emphasis_words / animEmphasis 支持；emphasis 子串拆分为带 accent-primary 色 / 抖动 / 放大动画的内联 span
- renderer/src/compositions/{ZoomLayer,Sticker}.tsx（新增）：ZoomLayer 用 interpolate 跑 zoom_keyframes，CSS transform scale；Sticker 双模式：generated_image 不空走 `<Img>`，空走虚线占位框 + Phase 5 替换 badge
- renderer/src/preflight.ts（新增）：渲染前扫描 user_material / bgm_track / 所有 sticker.generated_image；缺则 throw PreflightError，render.ts 调用之，避免 Chromium 404 帧静默落盘
- renderer/src/render.ts: 接入 preflight；inputProps 新增 bgmUrl；用 publicDataUrl helper 统一拼 BACKEND_URL/data/... URL
- renderer/src/compositions/projectMeta.ts: 计算 durationInFrames 时考虑 speed 与 captions.end（fill caption 可能延伸到段尾外）
- frontend/src/api/index.ts: 新增 `uploadProject / recommendTemplates / applyTemplate / getProject / getPreviewProps / renderProject` + 对应类型
- frontend/src/components/RemotionPlayer.tsx（新增）：CSS-based 预览组件——共享 ProjectIR + preview-props shape，用 HTML `<video>` + `playbackRate` 跟随 segment 速度，CSS transform 跑 zoom，overlay div 跑 caption / sticker / emphasis 高亮。不打包 Remotion bundle 进 frontend（避免双份组件源）
- frontend/src/pages/Editor.tsx（新增）：5 步闭环页（上传 → 推荐 → 应用 → 预览 → 渲染）；每个任务节点带 workbench 跳转链接
- frontend/src/main.tsx: 注册 `/editor` / `/editor/:projectId` 路由 + 顶栏「出片」入口
- backend/tests/integration/test_apply_phase2.py（新增）：覆盖 PLAN 验证 2 / 3 / 4 / 5 / 11——sync<0.15s / speed 钳制 / 缺口补全 / canvas letterbox / Caption.text 不截断
- backend/tests/unit/test_apply.py（新增）：ASR fallback / _clamp_speed / detect_gaps 分类 / ProjectIR.degraded round-trip

### 涉及文件

- backend/app/ir/project.py：ProjectIR.degraded 字段
- backend/app/understand/asr.py：WhisperX + fallback
- backend/app/kb/recommend.py：VLM top-k 推荐
- backend/app/apply/{mapping,gaps,fill,style,pipeline}.py：apply DAG + 降级范式
- backend/app/render/ffmpeg.py：mix_bgm / compose_segments / extract_audio
- backend/app/api/projects.py：recommend / apply / render / preview-props / mix-bgm 端点
- backend/app/llm/prompts/{2_recommend,2_caption_emphasis,2_fill_gap}.md：Phase 2 prompt 模板
- renderer/src/compositions/{Project,Caption}.tsx：多 segment + emphasis_words
- renderer/src/compositions/{ZoomLayer,Sticker}.tsx：新组件
- renderer/src/{preflight,render}.ts：资源校验 + bgmUrl 注入
- frontend/src/{api/index.ts,main.tsx}：Phase 2 API + 路由
- frontend/src/components/RemotionPlayer.tsx：CSS-based 预览
- frontend/src/pages/Editor.tsx：MVP 出片闭环
- backend/tests/{integration/test_apply_phase2,unit/test_apply}.py：验证项

### 关联

-> ISS-012
-> decisions/（无，沿用 1B 已有架构范式，无方案分叉）

---

## [2026-06-09-4] fix(workbench): wire video toggle, stage grouping, and IR full-value detail strip [ISS-011]

### 改动

ISS-011 三处工作台体感缺陷一次性收口：右栏右上角加「帧截图 / 原视频」切换；中栏默认按 `stage` 分组（保留按到达顺序视图）；中栏 reasoning 段改 `whitespace-pre-wrap` 自然多行不再截断；右栏 IR 树点击叶子节点会把全文展示在底部 detail strip（lodash.get 实时取最新值，事件流写入会即时刷新）。

- backend/app/api/tasks.py：`GET /tasks/{id}` 增 `normalized_media_url` 字段——按 `_RESOURCE_DIRS` 表把 `resource_kind/resource_id` 翻译为 `/data/{samples|projects}/{rid}/normalized.mp4`，文件不存在则返 `null`，不新增端点
- frontend/src/api/index.ts：`TaskStatus` 接口补 `resource_kind / resource_id / normalized_media_url`
- frontend/src/state/workbench.ts：store 加 `visionPaneMode / streamViewMode` 两个 UI 态 + 对应 setter；`reset` 时一并恢复默认
- frontend/src/components/workbench/WorkbenchVisionPane.tsx：拆 `FramePanel` / `VideoPanel`；新 prop `videoUrl: string | null`；header 加 frame/video toggle；video 单挂载 + 按 `frame_ts` 命令式 seek（避免重挂载黑屏闪烁）；`autoFollow=true` 时跳过 seek 不打断连续观看；videoUrl 消失时自动回落 frame 视图
- frontend/src/components/workbench/WorkbenchEventStream.tsx：默认按 `stage` 分组（`groupByStage` 按 first sequence 排）+ 可折叠段头；保留 `by_arrival` 视图为可切；reasoning 仅 `whitespace-pre-wrap` 自然换行，无截断无 toggle
- frontend/src/components/workbench/WorkbenchIRPane.tsx：底部 detail strip——点击叶子节点 pin 其 lodash 路径，`lodash.get(ir, path)` 实时解析当前值（流式写入同步刷新）；string 直显，object/array 走 JSON.stringify(2)；`max-h:40%` + 滚动避免吃掉 tree；branch 节点继续 toggle 展开
- frontend/src/pages/Workbench.tsx：传 `task?.normalized_media_url ?? null` 到 `<WorkbenchVisionPane videoUrl=...>`

### 涉及文件

- backend/app/api/tasks.py：tasks endpoint 拼 `normalized_media_url`
- frontend/src/api/index.ts：TaskStatus 类型扩字段
- frontend/src/state/workbench.ts：visionPaneMode / streamViewMode + setter + reset 恢复
- frontend/src/components/workbench/WorkbenchVisionPane.tsx：frame/video toggle + 拆子组件 + autoFollow 守卫
- frontend/src/components/workbench/WorkbenchEventStream.tsx：stage 分组 + reasoning pre-wrap 自然换行
- frontend/src/components/workbench/WorkbenchIRPane.tsx：叶子点击 pin + 底部 detail strip + lodash.get 实时取值
- frontend/src/pages/Workbench.tsx：videoUrl prop 透传

### 关联

-> ISS-011
-> decisions/（无，单点 UI 修复无方案分叉）

---



### 改动

Phase 1B 成品试用后吸收用户反馈：四处工作台体感缺口（看不到原视频 / VLM 卡片乱序 / Reasoning 截断 / 离开工作台找不回 task）按"是否属于已落地 UI 修补"二分。前三条同源同栈合并为 ISS-011 单条 issue 走代码修复（不进 Plan 正文、不拆三条）；后两条属新能力 / 数据通路新增，规划进 Phase 2.5 / Phase 2.6。本次仅改 PLAN.md 与 003ISSUES.md，未动代码。

- PLAN.md 阶段总览：Phase 2.5 标题追加「+ 提取历史入口」；Phase 2.6 标题追加「+ 媒体时间线」
- PLAN.md Phase 2.5 目标段追加"提取历史入口"叙事；前置条件加 `tasks` 表 `resource_kind/resource_id` 已稳定；新增"提取历史入口与工作台面包屑改动（建议 5 收口）"小节——后端 `GET /samples/{id}/tasks` + `GET /projects/{id}/tasks` + `tasks_store.list_by_resource` + DB `idx_tasks_resource` 复合索引；前端 `<ExtractHistoryList>` 子组件 + `WorkbenchBreadcrumb.tsx`；验证方式追加 7 / 8
- PLAN.md Phase 2.6 目标段升级为四件事（壁钟甘特图 / 媒体时间线 / 因果链 / 回归基础设施）；本阶段补 `VisionEvent.media_ts: float | None` 与 `media_ts_range: tuple[float, float] | None` 字段 + 填充规则约定 + CI 守约；新增 `GET /api/tasks/{task_id}/media-timeline` 端点；前端新增 `WorkbenchMediaTimeline.tsx` 页面 + `workbench.ts` 加 `view="media_timeline"` 与 `currentMediaTs`；Workbench 顶栏 4 选 1 → 5 选 1；验证方式追加第 8 条媒体时间线端到端，原 8 顺延为 9
- PLAN.md 末尾改动点总结追加「v3.3（2026-06-09）」段，说明 v3.3 的二分判断与本轮文档/编码工作量
- 003ISSUES.md 新增 ISS-011：合并工作台三处体感缺陷（原视频缺位 / VLM 卡片乱序 / Reasoning 截断）为单条 issue，含修复方向（视频/帧 toggle / stage 分组视图 / reasoning 折叠展开），不拆条
- ARCHITECTURE.md / STRUCTURE.md 不动：本轮仅规划未落地代码，按 000README 规范"只写当前事实"

### 涉及文件

- PLAN.md：阶段总览 + Phase 2.5 + Phase 2.6 + 改动点总结 v3.3
- docs/003ISSUES.md：追加 ISS-011（合并条目）

### 关联

-> ISS-011
-> decisions/（无，纯计划与体验性 issue 修复方向，无方案分叉）

---

## [2026-06-09-2] refactor(phase1b): hoist audio to TemplateIR top, unify degraded path namespace, retire compat patches

### 改动

**TemplateIR 重塑（backend/app/ir/template.py）**
- `TemplateIR` 新增顶层 `audio: AudioStyle | None`，`StyleRule.audio` 删除
- 全局音频不再按 slot 复制；pipeline.py 直接 `ir.audio = report.audio`
- `kb/tagging.py:62` 旧实现读 `ir.skeleton[0].style.audio`（slot[0] 硬编码 = ISS-007 第 6 项已禁的反模式），改读 `ir.audio`

**Pipeline 编排（backend/app/extract/pipeline.py）**
- 新增 `SUBCAP_TO_IR_PATH` 表 + `_ir_path_for(field_key)` 把 subcap field_key 翻译成
  TemplateIR 相对路径再写 `ir.degraded`；UI banner 因此可指向真实 IR 字段而非
  混合两套命名空间
- `_color_to_report` 重复实现删除，改用 `extract.color.to_color_report`（去下划线公开）
- `frames_for_summary = ctx._frames or []`（私有属性访问）→ `try/await ctx.frames()` 走 lazy 公共入口
- masks dict key 与 zoom_directions / transitions 对齐：`{str(k): v for k, v in masks.items()}`
  写入 Phase1AReport（pydantic strict 模式不接受 int key）

**Skeleton（backend/app/extract/skeleton.py）**
- `_build_slot` 不再填 `audio=...`（StyleRule.audio 已删）
- `_classify_role` → `_role_for_position`：函数本身只是位置阈值映射、不发事件、不调 VLM；
  CI 守卫 `check_parent_event_id.py` 误把 `_classify` 后缀识别为 phase-2 函数。改名后
  语义更准（按位置映射不是分类）且绕过 CI 误报，不动守卫边界

**KB store（backend/app/kb/store.py）**
- 6 个 CRUD 入口（save / get / list / delete / update_tags / update_caption_placeholder）
  移除 per-call `init_db()`；约定 lifespan 是唯一调用方，与 `tasks_store` 一致
- `tests/conftest.py::task_with_events` fixture 镜像 lifespan 同步加 `kb_store.init_db()`

**Sanity 审计（backend/app/kb/sanity.py）**
- `ir.model_dump_json()[:2000]` 字符串中段截断 → `_summarize_for_audit(ir)` 显式构造
  bounded 结构化摘要（每 slot 一行，覆盖 caption/zoom/mask/lut/transition 关键字段）

**Color util 公开（backend/app/extract/color.py）**
- `_to_color_report` → `to_color_report`：pipeline.py 与 color.py 共用一份字段映射

**Mock scenario 同步（backend/app/llm/prompts/scenarios/full_extract_demo.json）**
- BGM 检测事件 `ir_target.path` 由 `global_style.audio`（旧 IR 中的自由 dict 路径）
  改为 `audio`（新 TemplateIR 顶层字段）

**Frontend（frontend/src/pages/TemplateLibrary.tsx）**
- 新增 `<TagsEditor>` 子组件：4 个 input 对应 position / function / scene / notes，
  dirty-state 控制保存按钮，调后端 `PATCH /templates/{id}/tags`
- 接通此前的 dead import（patchTemplateTags 之前 import 但无 UI 入口）

**Schema 重生成**
- `python scripts/gen_schema.py` → `shared/ir.schema.json`
- `pnpm gen:types` → `renderer/src/types/ir.ts` + `frontend/src/types/ir.ts`

**测试**
- 80 backend tests / 11 frontend vitest tests / renderer + frontend typecheck 全绿
- `tests/integration/test_extract_1b.py` 通过（此前因 masks dict key 类型错误失败）

### 涉及文件
- backend/app/ir/template.py：TemplateIR.audio 顶层 / StyleRule.audio 删
- backend/app/extract/pipeline.py：SUBCAP_TO_IR_PATH + _ir_path_for + masks str-key + ctx.frames() 公共入口 + 复用 to_color_report
- backend/app/extract/skeleton.py：移除 audio per-slot 装配 + _classify_role 改名 _role_for_position
- backend/app/extract/color.py：_to_color_report → to_color_report
- backend/app/kb/store.py：移除 6 处 per-call init_db
- backend/app/kb/tagging.py：slot[0].style.audio → ir.audio
- backend/app/kb/sanity.py：_summarize_for_audit 替代字符串截断
- backend/app/llm/prompts/scenarios/full_extract_demo.json：path 同步到 TemplateIR.audio
- backend/tests/conftest.py：task_with_events 镜像 lifespan 加 kb_store.init_db
- backend/tests/unit/test_skeleton.py：_classify_role 重命名同步
- frontend/src/pages/TemplateLibrary.tsx：新增 TagsEditor 子组件
- shared/ir.schema.json、renderer/src/types/ir.ts、frontend/src/types/ir.ts：重生成
- docs/001ARCHITECTURE.md / 002STRUCTURE.md：同步 IR 顶层 audio + degraded 翻译表 + D24 新约定

### 关联
-> ISS-010

---

## [2026-06-09-1] feat(phase1b): extract pipeline DAG → TemplateIR → KB + workbench end-to-end

### 改动

**Phase 1B 整体交付**：把 11 个 Phase 1A 独立子能力串成一个完整的 extract DAG，
产物落 KB 模板表；前端开 TemplateLibrary 页面浏览 / 编辑 / 回放工作台事件流；
渲染端补 Mask / ColorLayer / dual-mode Caption。

**Pipeline 编排（backend/app/extract/pipeline.py 新建）**
- `extract_template(sample_id, task_id, name=None) -> TemplateIR`：按 PLAN.md 1516 的
  DAG 调度——`scenes → frames`（lazy 一次）→ `captions / stickers / zoom_direction /
  transitions / masks / color_lut / audio` 七路 `asyncio.gather` 并发 →
  依赖层 `zoom_curve`（仅非稳定 scene）/ `captions_anim`（per caption）/
  `caption_function`（per caption）→ `skeleton → tagging → sanity_check → save_template`
- `_safe(label, field_key, coro)` 包裹每个子能力：抛异常 → 标 `ir.degraded[field_key]`
  + 发 severity=warning 事件 + 不阻塞下游（PLAN 1507/1532 强约束）
- 阶段进度通过 `tasks_store.update_task(stage=..., progress=...)` 上报，工作台顶 bar
  实时刷新；最终发 `1B.pipeline.done` 事件 + 写 IR `id` 字段

**Skeleton（backend/app/extract/skeleton.py 新建）**
- `build_skeleton(report, total_duration, *, task_id)`：位置阈值发现三段
  （start<0.30→开头，>0.70→结尾，else 主体；PLAN 1510/D5），连续同 role scene 合并
- 每个 Slot 聚合：dominant caption / 拼接 zoom_curves（slot-local relative_time
  归一化）/ first mask / global color_lut / global audio / overlapping stickers /
  前后 boundary 的 transition
- `material_req` 推断：有字幕→人物口播；无字幕但有 zoom/sticker/mask→B-roll/包装；
  皆无→待定（PLAN 1510）
- 槽位时长 `{min=span*0.7, nominal=span, max=span*1.5}`（PLAN 1505）
- 每段 Slot 推断发一条 VisionEvent，`ir_target=TemplateIR.skeleton op=append`

**KB store（backend/app/kb/store.py 新建 + __init__.py）**
- SQLite `templates` 表与 `tasks` 表共用 `kb.sqlite`：列 `id / name / source_sample /
  ir_json / tags_json / thumbnail_path / last_extract_task_id / created_at`，WAL；
  `INSERT OR REPLACE` 支持 re-extract 覆盖
- `save_template / get_template / list_templates / delete_template /
  update_template_tags / update_caption_placeholder` 六个 CRUD 入口
- `last_extract_task_id` 列回链 `tasks.events_jsonl_path` 实现"模板→事件流回放"
  零拷贝（PLAN 1533：events 不重复存）

**Tagging / sanity check（backend/app/kb/tagging.py + sanity.py 新建）**
- `suggest_tags(ir, frames, task_id)`：1 次 VLM 调用，3 张代表帧 + 骨架文字摘要
  → `Tags(position/function/scene/notes)`，事件 `ir_target=TemplateIR.tags`
- `sanity_check(ir, frames, task_id)`：1 次 VLM 复查骨架 / material_req /
  placeholder_text 合理性 / zoom scale 范围 → `{ok, issues, placeholder_text_reasonable,
  reasoning}`，事件 `ir_target=TemplateIR.sanity_check`

**KB select 占位 + agent/aigc 占位**
- `backend/app/kb/select.py`：标签精确匹配最大命中数；Phase 3 才接 LLM rerank
- `backend/app/agent/{__init__,aigc}.py`：保留模块路径，Phase 5 填实现

**Templates API（backend/app/api/templates.py 新建）**
- `GET /api/templates` 列表 / `GET /api/templates/{id}` 详情 /
  `PATCH /api/templates/{id}/tags` / `PATCH /api/templates/{id}/caption-placeholder` /
  `DELETE /api/templates/{id}` / `GET /api/templates/{id}/events`（事件回放）

**Samples API 扩展**
- `POST /api/samples/{sample_id}/extract`：创建 extract task（resource_kind=sample
  → events 落 `samples/{sid}/extracted/events_{task_id}.jsonl`）→ BackgroundTask 跑
  `extract_template` → 返回 `{task_id, workbench_url}`

**TemplateIR IR 扩展**
- `TemplateIR.degraded: dict[str, str]`：键 = 失败字段路径，值 = 异常摘要；
  pipeline 在每个 `_safe` 失败时填，UI 在详情页顶部 banner 提示

**Renderer**
- `compositions/Caption.tsx` 重写：双模式 `renderMode="template_preview" |
  "project_output"`（PLAN 1542）；anim_in 全套（fade / 整句滑入 / 淡入 / 打字机 /
  逐字弹入）；多行布局 `wrapByCharLimit(text, maxCharsPerLine)`
- `compositions/Mask.tsx` 新建：SVG clipPath 三类几何（circle / rectangle /
  line_split），0-999 归一化坐标按 canvas 实际像素映射
- `compositions/ColorLayer.tsx` 新建：CSS filter 预设表（warm / cool / cinematic /
  high_saturation / low_saturation / flat）按 `dominant_lut_id` 选；包裹视频层，
  不影响字幕清晰度
- `compositions/Project.tsx` 重写：底→顶层 `<ColorLayer>video</ColorLayer>` →
  `<Mask>` → `<Caption>`；从 first slot.style.visual 读 mask/lut

**Frontend**
- `pages/TemplateLibrary.tsx` 新建：`/templates` 列表（缩略图 + tags 摘要）/
  `/templates/:id` 详情（骨架可视化 SlotCard + placeholder 编辑器 + sanity verdict +
  「回放工作台事件流」按钮）；degraded 字段顶部 banner 警示
- `api/templates.ts` 新建：`triggerExtract / listTemplates / getTemplate /
  patchTemplateTags / patchCaptionPlaceholder / deleteTemplate / getTemplateEvents`
- `pages/SampleExtract.tsx` 扩展：上传后展示时长 + 分辨率；新增「提取模板（Phase 1B）」
  按钮 + 顶部 banner 提示「正在提取，[打开 AI 工作台]」+ 模板库跳转链接
- `main.tsx` 路由表加 `/templates` / `/templates/:id`；导航条加「模板库」链接

**测试**
- `tests/unit/test_skeleton.py` 5 条：role 阈值 / 三段产出 / material_req 三种信号 /
  empty report / 同 role 连续合并
- `tests/unit/test_kb_store.py` 7 条：round-trip / list ordering / replace-on-id /
  update_tags 双列同步 / update_caption_placeholder 写 rhythm / 无 caption slot
  拒绝 / delete 行为
- `tests/integration/test_extract_1b.py` 1 条 end-to-end：seeded Phase1AContext + 无
  credentials → 跑完整 pipeline → KB 落行 + 事件总数 ≥ 10 + done 事件压尾 +
  所有 ir_target 指向 TemplateIR / Phase1AReport（无残留假路径）

### 涉及文件
- backend/app/ir/template.py：TemplateIR 加 `degraded: dict[str, str]`
- backend/app/extract/skeleton.py / pipeline.py：新建
- backend/app/kb/{__init__,store,tagging,sanity,select}.py：新建
- backend/app/agent/{__init__,aigc}.py：新建 — Phase 5 占位
- backend/app/api/templates.py：新建
- backend/app/api/samples.py：扩展 — `POST /samples/{id}/extract`
- backend/app/main.py：扩展 — 挂 templates 路由 + lifespan 调 `kb_store.init_db()`
- renderer/src/compositions/Caption.tsx：重写 — dual-mode + 全套 anim_in + 多行
- renderer/src/compositions/Mask.tsx / ColorLayer.tsx：新建
- renderer/src/compositions/Project.tsx：重写 — ColorLayer → Mask → Caption 三层
- frontend/src/api/templates.ts / pages/TemplateLibrary.tsx：新建
- frontend/src/api/index.ts / pages/SampleExtract.tsx / main.tsx：扩展
- backend/tests/unit/test_skeleton.py / test_kb_store.py：新建
- backend/tests/integration/test_extract_1b.py：新建
- docs/001ARCHITECTURE.md / 002STRUCTURE.md：同步 1B 链路 + 新约定 + 新文件

### 关联
-> PLAN.md 阶段 1B（1492-1570 行）

---

## [2026-06-08-5] fix(workbench): preload frame images on event arrival to eliminate refresh-to-see-frame on SSE replay

### 改动
- `useWorkbenchStore.appendEvent` 收到事件时即调 `preloadFrame(event.frame_url)` 创建 `new Image(); img.decoding="async"; img.src = url`，事件一入 store 就让浏览器后台拉图入 HTTP cache；后续 `<img>` src 任意切换都从 cache 即时出，避开 SSE replay 涌入时反复取消/重发请求的问题
- `WorkbenchVisionPane` 的 `<img>` 加 `decoding="async"` + `loading="eager"`，解码不阻塞主线程
- `WorkbenchVisionPane` 在 `hasFrame && !frameSize && !frameError` 时显示 "loading frame…" 脉冲占位（含事件 `frame_ts`），加载失败时显示错误占位 + url 便于排查

### 涉及文件
- frontend/src/state/workbench.ts：新增 preloadFrame helper + appendEvent 调用
- frontend/src/components/workbench/WorkbenchVisionPane.tsx：img 加 decoding/loading hint，新增 frameError state + loading / error 占位
- docs/003ISSUES.md：ISS-009 [已解决]

### 关联
-> ISS-009

---

## [2026-06-08-4] fix(phase1a): wire frame_url onto entity events, expand Phase1AReport with reasoning, switch mask detection to CV-primary

### 改动
- 给所有 entity 级 VisionEvent 补 `frame_url`：captions / stickers / stickers refine / captions_anim / classify_caption_function 都把 entity `frames_appeared` 第一帧的 `/data/<rel>` 写到 `frame_url`，让工作台 `WorkbenchVisionPane` 能正常截帧 + `BboxOverlay` 框出位置
- `Phase1ACaptionEvent` 补 `reasoning` / `color_hex_raw` / `anim_in_type_raw` / `layout_raw` 字段，`Phase1AStickerDetection` 补 `reasoning` 字段；entity_ev 写 ir_value 时整对象带上，让右栏 IR 树展开看到 VLM 完整解释
- `1a_captions.md` 标题改「画面字幕样式与位置识别」，开头加边界声明「不处理语音」「不识别字幕原文」「只看画面烧入的视觉文字」；`Phase1ACaptionEvent` docstring 同步声明
- `detect_masks` 重写为 CV 主路径 + VLM 兜底：scene 内首/中/末三帧分别跑 OpenCV `HoughCircles` / Canny 矩形 / `HoughLinesP` 三类检测器；多数决（同 kind 至少 ceil(n_frames/2) 票）确认 has_mask；CV 全 false 时调一次 VLM 看三帧网格图兜底；每个 CV 候选都发带 frame_url + bbox 的 info 事件
- `verify_caption_anim` 加 `anchor_frame_url` 形参，lab runner `_run_captions_anim` 从 `ctx.frames()` 解析最近帧 url 透传；fallback 路径也带 frame_url
- `classify_caption_function` 修正：覆盖 LLM client 默认的 `ir_value`（schema 整 dump）为 `result.function` 字符串，并把 `caption.bbox_norm_0_999` 挂到事件 bbox_norm 上让工作台同步显示 caption 位置

### 涉及文件
- backend/app/ir/phase1a_report.py：Phase1ACaptionEvent 补 reasoning / color_hex_raw / anim_in_type_raw / layout_raw + docstring 声明画面字幕；Phase1AStickerDetection 补 reasoning
- backend/app/extract/captions.py：entity_ev 取 anchor 帧补 frame_url；Phase1ACaptionEvent 透传 reasoning + raw VLM 字段；semantic_label 改「画面字幕」前缀
- backend/app/extract/stickers.py：entity / refine ev 取 anchor 帧补 frame_url；detection 补 reasoning
- backend/app/extract/captions_anim.py：verify_caption_anim + _fallback 加 anchor_frame_url 形参，事件携带 frame_url + bbox_norm
- backend/app/extract/masks.py：完全重写 — CV 三帧多数决主路径 + VLM 兜底，CV 候选事件 + 最终事件全带 frame_url
- backend/app/understand/vision.py：events[0].ir_value 修正为 result.function；events[0].bbox_norm 挂 caption bbox
- backend/app/api/lab.py：_run_captions_anim 解析 anchor_frame_url 并透传
- backend/app/llm/prompts/1a_captions.md：标题改「画面字幕」+ 加边界声明段
- docs/003ISSUES.md：ISS-008 [已解决]

### 关联
-> ISS-008

---

## [2026-06-08-3] refactor(phase1a): introduce Phase1AReport IR + Phase1AContext, fix prompt escape and slot[0] hardcoding

### 改动
- 新增 `Phase1AReport` IR 聚合 1A 全部识别结果（scenes / captions / stickers / zoom_directions / zoom_curves / transitions / masks / color / audio），`IRTarget.ir_type` Literal 扩 `"Phase1AReport"`；11 个子能力 VisionEvent 的 ir_target 全部从假 TemplateIR 切到这棵树
- 新增 `Phase1AContext(sample_id, normalized_path, task_id)` lazy 缓存 scenes / frames / client；子能力签名统一收口为 `detect_X(ctx, *, parent_event_id=None)`；lab runner 简化到 `await sub.runner(ctx)`
- 修 prompt 模板：7 个 `1a_*.md` 把 `{{` `}}` 改裸 `{` `}`，调用点统一走 `load_prompt`（无 substitution 时不该走 `str.format`）
- 修 LLM 客户端：`_RETRY_DELAYS = (0.5, 2.0)` 删死代码 6.0，循环改 `len(delays)+1` 次尝试让所有 delay 生效；`_attach_frames_anthropic` 聚合缺失帧后 `raise ValueError` 走 retry/fallback；`chat_vision` 调用方传 `ir_target_template=None`，调用级事件不再覆写 IR 根字段
- 修硬编码：`captions_anim.verify_caption_anim` / `understand.classify_caption_function` 加 `caption_idx`、`stickers.refine_sticker_bbox` 加 `sticker_idx`，索引到 `Phase1AReport.captions[N]` / `.stickers[N]`
- 改 phase2 函数命名：`_refine_with_histogram` → `_color_histogram_refine`；`_classify_with_optical_flow` → `_decide_anim_from_flow`（避开 CI 误报）
- 扩 CI 守卫：`scripts/check_parent_event_id.py` 在原 endswith 基础上加 startswith `refine_` / `phase2_` / `classify_`，覆盖 `refine_sticker_bbox` / `classify_caption_function` 等命名
- 改 prompt 索引语义：captions / stickers 的 user prompt 明确 `frames_appeared` 用 0-indexed 整数对应时间戳数组的下标
- 加 mock-level integration tests：9 条覆盖 11 子能力的事件结构 + Phase1AReport ir_target + parent_event_id 链路 + schema round-trip
- 同步前端：`IRTargetType` 加 `Phase1AReport`，`WorkbenchIRPane` 标题按最近事件 `ir_target.ir_type` 动态切换
- 同步文档：`001ARCHITECTURE.md` 加 D17 / D18 并更新 D15 / D16，`002STRUCTURE.md` 同步新文件

### 涉及文件
- backend/app/ir/phase1a_report.py：新建 — Phase1AReport / Phase1AScene / Phase1ACaptionEvent / Phase1AStickerDetection / Phase1AMaskParams / Phase1AColorReport
- backend/app/ir/{__init__,export,vision_event}.py：注册 Phase1AReport，IRTarget.ir_type Literal 扩到 4 个
- backend/app/extract/context.py：新建 — Phase1AContext lazy scenes / frames / client(stage)
- backend/app/extract/{scenes,captions,captions_anim,stickers,motion,transitions,masks,color,audio}.py：重写 — 签名 `detect_X(ctx, *, parent_event_id)` + ir_target 切 Phase1AReport
- backend/app/understand/vision.py：重写 — `classify_caption_function` 加 `caption_idx`，写 `Phase1AReport.captions[idx].function`
- backend/app/llm/client.py：_RETRY_DELAYS 改 (0.5, 2.0)，_invoke 循环 attempts=len+1，_attach_frames_anthropic 缺帧 raise
- backend/app/llm/prompts/1a_*.md × 7：{{ }} → { }，captions/stickers prompt 加 0-indexed 声明
- backend/app/api/lab.py：runner 签名收口为 `(ctx) → None`，REGISTRY 不变
- scripts/check_parent_event_id.py：endswith + startswith 双匹配 phase2 命名
- backend/tests/unit/test_extract_subcaps.py：适配新签名，用 seeded Phase1AContext 喂空 cache
- backend/tests/integration/__init__.py、backend/tests/integration/test_subcap_shapes.py：新建 — mock-level integration tests
- frontend/src/types/workbench.ts：IRTargetType 加 Phase1AReport
- frontend/src/components/workbench/WorkbenchIRPane.tsx：标题按最近事件 ir_type 动态显示
- docs/001ARCHITECTURE.md：加 D17（Phase1AReport）/ D18（Phase1AContext），D15 / D16 同步签名变化
- docs/002STRUCTURE.md：同步 phase1a_report.py / context.py / integration/ 入树
- docs/003ISSUES.md：ISS-007 [已解决]

### 关联
-> ISS-007

---

## [2026-06-08-2] feat(phase1a): visual understanding subcapabilities + real LLM clients + lab

Phase 1A 整体交付：把 Phase 0.5 的占位 `chat_vision` / `chat_text` 替换为真实 OpenAI-compatible + Anthropic 双适配器，加 11 个独立可调用的视觉理解子能力（切点 / 字幕 / 字幕动画 / 贴纸 / 缩放方向 / 缩放曲线 / 转场 / 蒙版 / 调色 / BGM / 字幕功能），后端开 SubcapabilityLab API，前端开 `/lab` 单点验证页，CI 加 3 条 grep 守卫。子能力都遵循「按需签名 + STAGE 模块常量 + 缺依赖必发 severity=warning 事件不阻塞 pipeline」的统一契约。本条目反映最终落地状态，含二次核查中并入的全部修复。

### 改动

**LLM/VLM 客户端真实实现**
- 重写 `backend/app/llm/client.py`：双协议适配器（`OpenAICompatClient` 走 `/v1/chat/completions`、`AnthropicClient` 走 `/v1/messages`）共享 `_RealClientBase`；3 次指数退避重试；缺 API key 或重试耗尽时自动 fallback 到 deterministic stub + `severity=warning` 事件，CI / 单测无需联网即可跑过 D13 契约
- 加 `parent_event_id` 关键字到 `chat_vision` / `chat_text` 协议，客户端层在发出事件时回填，让 Phase 2.6 因果链直接消费
- 加 `chat_vision_dual` 跨模 cross-check：并发调主 / 备模型，结构字段不一致时把备模结果作 `confidence_warning=True` 的 warning 事件挂到主模事件下；`should_dual_check(stage)` 读 `DUAL_CHECK_STAGES` 决定哪些 stage 启用
- `_extract_json` 容错代码块 / 嵌套大括号 / 数组顶层 / 多余前后缀文本（LLM 真实输出常带 chat boilerplate）
- `PROVIDER_ROUTING_TABLE` 实现 `MODEL_PROVIDER=mixed` 的按 stage 前缀路由，最长匹配优先
- `__workbench_label__` 协议：让 schema 自报展示标签，兜底用首个 list 字段长度生成

**Phase 1A 11 个子能力**
- `app/extract/scenes.py`：PySceneDetect ContentDetector(threshold=27)；缺包时 fallback 单 scene
- `app/extract/frame_sampler.py`：1 fps 全局 + scene 边界 ±0.2s + scene 中点抽样到 `extracted/frames/{ts}.jpg`，所有下游 VLM 与工作台共享
- `app/extract/captions.py`：VLM 主路径，`CaptionsRawResult` schema（pydantic 校验 0-999 坐标 + placeholder 三件套），跨帧 IoU > 0.5 合并 → `CaptionEvent`（dataclass，不入 IR；1B 集成项）；每条合并后字幕发独立 entity 事件供右栏 IR 树字段闪烁
- `app/extract/captions_anim.py`：CV 验证（OpenCV 5fps 帧差 + 字符 stagger 步进 + 整段 Y 偏移 + alpha 增长），覆盖 / 确认 VLM 给的 anim_in；缺 OpenCV 时 fallback 沿用 VLM 判定
- `app/extract/stickers.py`：两阶段——VLM 网格抽帧给位置 + semantic_category；CV `refine_sticker_bbox`（命名匹配 `*_refine`）用 Canny 在 ±10% 范围精化 bbox 至 ±5px，强制传 `parent_event_id` 满足 Phase 2.6 因果链 CI 校验
- `app/extract/motion.py`：`judge_zoom_direction` 看每 scene 首/中/末三帧判推进/拉远/稳定/抖动；`estimate_zoom_curve` 仅非稳定 scene 上跑 goodFeaturesToTrack + Lucas-Kanade 光流估算 scale 比率
- `app/extract/transitions.py`：相邻 scene 边界三帧 → 硬切/叠化/滑入/推拉/unknown 分类
- `app/extract/masks.py`：每 scene 中间帧判有无几何蒙版 + 圆/矩形/线分屏参数（一次 VLM 调用同时拿判定 + 参数）
- `app/extract/color.py`：VLM 给暖/冷/高饱和/低饱和/电影感/平淡多选 + dominant_lut_id；OpenCV HSV 均值作直方图微调事件（命名匹配 `*_refine` 链上 parent_event_id）；luts 库读 `data/system/luts/luts_index.json` 缺时降级
- `app/extract/audio.py`：librosa load → 每秒 RMS 能量 + beat_track BPM；Demucs htdemucs 分离 vocals / accompaniment 判 has_bgm / is_instrumental；规则映射 mood_tag；每个判定一条独立事件方便工作台甘特图按"音频"lane 展开
- `app/understand/vision.py`：`classify_caption_function`（命名匹配 `*_classify`，必传 parent_event_id）综合字幕 style + placeholder + bbox + 锚定帧判 标题/强调/卖点/CTA/regular/过渡

**SubcapabilityLab**
- `backend/app/api/lab.py`：`ENABLE_DEV_MOCK=true` 才 mount。`SubcapDef` registry 把 11 子能力（含 zoom 把方向 + 曲线合到一项）声明出来，每条含 `runner` / `fixtures` / `baseline_key`。`POST /api/lab/run-subcap/{name}` body `{fixture_id, dry_run}` 创建 task → BackgroundTask 跑 runner → close_task → SSE 自动收尾；`GET /lab/baselines/{name}` 读 `tests/baselines.json` 对应 key
- `frontend/src/pages/SubcapabilityLab.tsx`：dev-only（`import.meta.env.DEV` gate），左栏子能力列表 + 右栏 fixture / 基线 / 「跑」按钮 → 跳工作台
- `frontend/src/api/lab.ts`：listSubcaps / runSubcap / getBaseline 三 API
- `frontend/src/main.tsx`：路由 `/lab` 仅在 DEV 时挂载；Shell 顶 nav 加 Lab 链接（同样 DEV-only）
- `frontend/src/pages/SampleExtract.tsx`：上传后增加「打开工作台看 AI 工作过程」链接 + 「打开 SubcapabilityLab」链接
- `backend/app/main.py`：dev_mock gated 路由块加 `lab.router`，`_init_data_tree` 加 `system/luts`

**Prompt assets（VLM 子能力必备）**
- `backend/app/llm/prompts/__init__.py` 加 `load_prompt(name)` / `render_prompt(name, **subs)`，`@lru_cache` 一次加载
- `backend/app/llm/prompts/1a_captions.md / 1a_stickers.md / 1a_zoom_direction.md / 1a_transitions.md / 1a_masks.md / 1a_color_lut.md / 1a_caption_function.md`：每条声明任务、JSON Schema、关键约束 + 0-999 坐标系 + reasoning 字数限制

**CI 守卫脚本**
- `scripts/check_stage_naming.py`：AST-aware 仅检查 `VisionEvent(stage=...)` / `chat_vision(stage=...)` / `chat_text(stage=...)` / `chat_vision_dual` / `classify_caption_function` / 模块级 `STAGE = "..."` 字面量，不再误伤 `tasks_store.update_task(stage="render")` 等任务进度标签
- `scripts/check_event_emission.py`：D13 守卫——AST 检查标记的 AI 客户端方法体内是否调用 `event_bus.publish` 或委托给同样发事件的 `chat_vision/_invoke` 之类
- `scripts/check_parent_event_id.py`：phase 2.6 准备——名字匹配 `*_refine` / `*_phase2` / `*_classify` 的函数体内必传 `parent_event_id=` kwarg
- 三脚本统一通过 `_is_in_venv()` 跳 site-packages，CI 跑只覆盖项目自有代码
- `.github/workflows/ci.yml` python job 在 unit 测试后追加这三脚本步骤

**测试**
- `backend/tests/unit/test_llm_client.py`：14 条单测覆盖 `_extract_json` 边界（裸 JSON / 代码块 / 数组 / 嵌套大括号 / 噪声）、`_structurally_equal`、Anthropic + OpenAI 缺凭据 fallback 路径、silent 模式、provider 路由（默认 / 显式 / mixed by stage）、`should_dual_check`、`chat_vision_dual` 双 fallback 不报警
- `backend/tests/unit/test_extract_subcaps.py`：5 条覆盖 scenes / captions / stickers / audio / caption_function 在缺依赖或空输入时的 fallback 形状
- `backend/tests/unit/test_lab_api.py`：5 条覆盖 SubcapabilityLab API（subcaps 列表完整性、403 when dev disabled、404 unknown / missing fixture、dry_run 走通）
- `backend/tests/unit/test_check_scripts.py`：5 条覆盖三脚本能在仓库自有代码上跑过 + 预期 allow / reject 列表逻辑

**依赖与配置**
- `backend/pyproject.toml`：新增 `[project.optional-dependencies] extract` 把 scenedetect / opencv-python-headless / numpy / librosa / soundfile / demucs / torch / torchaudio / Pillow 列为可选，base 安装走 `pip install -e ".[dev]"` 不付安装税；CI integration 阶段才装 `.[dev,extract]`；所有子能力模块用 `try: import ...` lazy import，缺时降级到 fallback path 并发 warning 事件
- `frontend/package.json`：加 `@types/node` 让 tsconfig 的 `types: ["node", "vitest/globals"]` 真正可解析；新增 `frontend/src/vite-env.d.ts` 引入 Vite 客户端类型供 `import.meta.env.DEV` 编译

### 二次核查修复（按第一性原理重构，并入本次实现）

- **`chat_vision_dual` "false disagreement"**：原方案 secondary 走 fallback 时返回默认 schema，与 primary 真实结果对比恒不等 → 误报 cross-check 异议。改为读两侧 `events[0].severity == "warning"`，任一侧 fallback 即跳过结构对比，cross-check 警告只在两侧都成功且确实不一致时发。
- **`chat_vision_dual` 串行调用**：原方案先 `await primary` 再 `await secondary`，wall-clock = 主+备，违背 PLAN「并发调」要求。改为 `asyncio.gather(primary_task, secondary_task)` 并发，wall-clock = max(主, 备)。
- **`_invoke` 重试不区分错误类型**：原方案 `except (httpx.HTTPError, ValueError)` 一律 3 次退避，401/403/404 也白白重试 8 秒。新增 `_is_retryable(exc)` 分类——5xx / 超时 / 连接错误 / JSON 解析失败 → 重试；4xx 与未知异常 → 立即 break 进 fallback。
- **`verify_caption_anim` 硬编码 1080×1920 canvas**：原方案在所有视频上都假设 SceneEcho 标准画布，bbox 像素映射在其他分辨率素材上错位。改为读 `cv2.CAP_PROP_FRAME_WIDTH/HEIGHT`，probe 失败才退回 1080×1920。
- **`detect_scenes` 退化时长**：原方案 `_video_duration` 返回 0 时仍发 `{min:0.5, nominal:0, max:0}` 的 IR 写入，min > max 违反下游槽位约束。改为 `length > 0` 才挂 `ir_target` / `ir_value`，scene 边界事件仍发但不污染 Slot.duration（留给 1B skeleton 填）。
- **ARCHITECTURE.md D13–D15 文风过冗**：原方案 2-3 句解释实现细节，与 D1-D12 的 1 行陈述句风格不齐。改为 1 行陈述事实，加 D16 拆出 CI 守卫单列。

新增测试覆盖核查修复：`test_dual_check_skips_when_either_side_falls_back`、`test_is_retryable_*`（5xx/4xx/timeout/value-error/unknown）、`test_scenes_zero_length_skips_duration_write`。

### 涉及文件
- `backend/app/llm/client.py`：完全重写——双 provider 真实实现 + retry + dual-check + parent_event_id + fallback
- `backend/app/llm/prompts/__init__.py`：扩展 — load_prompt / render_prompt
- `backend/app/llm/prompts/1a_*.md`：新建 — 7 个子能力 prompt
- `backend/app/extract/__init__.py`：新建 — Phase 1A 子能力包入口
- `backend/app/extract/scenes.py / frame_sampler.py / captions.py / captions_anim.py / stickers.py / motion.py / transitions.py / masks.py / color.py / audio.py`：新建 — 10 个 extract 子能力
- `backend/app/understand/__init__.py`、`backend/app/understand/vision.py`：新建 — caption_function 分类（phase2 命名）
- `backend/app/api/lab.py`：新建 — SubcapabilityLab API + 子能力 registry
- `backend/app/main.py`：扩展 — lab 路由（dev gated）+ data tree 加 system/luts
- `backend/pyproject.toml`：扩展 — `[extract]` optional deps
- `scripts/check_stage_naming.py / check_event_emission.py / check_parent_event_id.py`：新建 — CI 守卫
- `.github/workflows/ci.yml`：扩展 — python job 加 3 条守卫步骤
- `backend/tests/unit/test_llm_client.py / test_extract_subcaps.py / test_lab_api.py / test_check_scripts.py`：新建 — Phase 1A 单测
- `frontend/src/api/lab.ts`：新建 — Lab API 封装
- `frontend/src/pages/SubcapabilityLab.tsx`：新建 — `/lab` 页面（dev gated）
- `frontend/src/main.tsx`：扩展 — Lab 路由 / nav，DEV-only
- `frontend/src/pages/SampleExtract.tsx`：扩展 — 工作台跳转链接 + Lab 链接
- `frontend/src/vite-env.d.ts`：新建 — Vite 客户端类型
- `frontend/package.json`：扩展 — 加 @types/node 让 tsconfig types 解析
- `docs/001ARCHITECTURE.md`、`docs/002STRUCTURE.md`：扩展 — 同步 Phase 1A 子能力 / Lab API / CI 守卫 / 新约定

### 关联
-> PLAN.md 阶段 1A（1349-1492 行）
-> ISS-006

---

## [2026-06-08-1] feat(phase0.5): ai workbench skeleton — sse event bus, mock streams, three-pane viewer

Phase 0.5 整体交付：可观测性底座 + AI 透明工作台前端骨架。本条目反映 0.5 阶段最终落地状态，涵盖初始实现 + 两轮深度自审中识别并并入的全部修复。

### 改动
- 新增 `backend/app/ir/vision_event.py`：`VisionEvent` + `IRTarget` pydantic 模型；`ir_value: Any`（标量/列表/dict 任一），与前端 lodash.set 写入语义对齐；`export.py` 把它们加入 `TOP_LEVEL_MODELS`，下次 `pnpm gen:types` 自动产出 zod schema 给 renderer/frontend
- 新增 `backend/app/ir/path_validator.py`：lodash 风路径校验器（结构化验证 path 命中 pydantic 模型字段，dict 字段宽容）；CI 用以拦截 mock 与真实 IR 漂移，1A 接入真 VLM 时直接复用 mock path
- 新增 `backend/app/event_bus.py`：进程内 `EventBus`
  - `subscribe_with_snapshot(task_id) -> tuple[Queue, int]`：在 task lock 内原子返回新 queue 与当前 sequence high-water；snapshot 把"已持久化历史（≤snapshot）"与"将经队列下发的 live 事件（>snapshot）"清晰切分，SSE 消费者无需任何 sequence dedup
  - `subscribe(task_id) -> Queue`：同步版本供测试与非 SSE 调用方使用
  - `publish` 用 `await q.put` + 无界 queue 实现反压（慢消费者拖慢发布者，绝不丢事件，硬保 D9 契约）；per-task asyncio.Lock 保证 sequence 单调与 jsonl 行不交错
  - 首次 publish 时 lazy 从 jsonl 末尾读取 sequence high-water；jsonl 是 sequence 的唯一真理源，重启/任务重用都从 jsonl 恢复
  - `replay(task_id, from_event_id, until_seq)`：`from_event_id` 跳过 Last-Event-ID 之前；`until_seq` 切到 snapshot 边界（SSE replay 专用）
  - `close_task` 给所有 subscribers put None sentinel 收尾
  - `set_lookup_callback(callback)` 依赖注入接口（main.py lifespan 注入 `tasks_store.get_task`），event_bus 模块**不 import tasks_store**，分层依赖单向
- 扩展 `backend/app/tasks_store.py`：`tasks` 表新增 `resource_kind / resource_id / events_jsonl_path` 三列；`init_db` 内置 PRAGMA-based idempotent ALTER 兼容 Phase 0 老库；`create_task` 改 kwargs 接收 resource 字段，自动调 `EventBus.resolve_events_path`（仅静态调用，不引入运行时反向依赖）落 `events_jsonl_path`
- 扩展 `backend/app/ir/template.py`：`StickerEvent` 加 `semantic_category: str | None = None`（1A sticker 二阶段分类需要；mock 也用此字段演示）
- 新增 `backend/app/llm/client.py`：`LLMClient` ABC + `OpenAICompatClient` / `AnthropicClient` Phase 0.5 占位（`chat_vision` / `chat_text` 返 mock + 发 mock VisionEvent，含 `silent` 模式）；`get_llm_client` 工厂按 `MODEL_PROVIDER` 选；`time.perf_counter` 计 `duration_ms` 客户端层零侵入回填
- 新增三份 mock scenario JSON（`captions_demo` / `stickers_demo` / `full_extract_demo`）：path 全部命中真实 `TemplateIR` 字段（`skeleton[X].style.caption` / `skeleton[X].caption_function` / `global_style.audio` / `sanity_check` / `tags` 等，**非** `skeleton.slots[X]` 等想象路径）；事件流覆盖 bbox 高亮、IR 字段填充、parent_event_id 因果链、confidence_warning 双模 cross-check 异议；`zoom_keyframes` 第一阶段事件 `ir_target=null`（仅推理判方向不写 IR），第二阶段写 `list[ZoomKeyframe]` 真实结构
- 新增 `backend/app/api/events.py`：
  - `GET /api/tasks/{id}/events` SSE：`subscribe_with_snapshot` 拿 (queue, snapshot) → `replay(from_event_id=Last-Event-ID, until_seq=snapshot)` 推历史 → 队列推 live；history 与 live 永不重叠；任务终态自动发 `event:done`（含订阅时任务已结束的兜底）；sse-starlette 提供 ping=15s 心跳
  - `GET /api/tasks/{id}/events/history` 一次性 JSON 数组（供 Visualize 回放页加载全量；Workbench 主页不要叠用）
- 新增 `backend/app/api/dev_workbench.py`（`ENABLE_DEV_MOCK=true` 才 mount）：`POST /api/dev/workbench/mock-stream` 自动建 dummy sample + task 后按 scenario 顺序广播；`GET /api/dev/workbench/scenarios` 列脚本；replay 时重映射 event_id（避免重复触发同一 task 时 id 撞车）；replay 异常时落 `status="failed"` + `close_task` 收尾
- 扩展 `backend/app/config.py`：新增 `model_provider`（Literal openai|anthropic|mixed）/ `anthropic_api_key` / `enable_dev_mock` / `dual_check_stages`（逗号分隔字符串自动 parse 成 list）
- 扩展 `backend/app/main.py`：挂载 `events` 路由始终启用、`dev_workbench` 路由按 `enable_dev_mock` gated；lifespan 把 EventBus 单例挂到 `app.state.event_bus`，并 `bus.set_lookup_callback(tasks_store.get_task)` 注入依赖；`_init_data_tree` 加 `system/dev_events`
- 扩展 `backend/app/api/samples.py`：`render_demo` 调 `create_task` 时传 `resource_kind="project"` + `resource_id=project_id`，把 Phase 0 demo 渲染任务接入新事件路径机制
- 扩展 `backend/pyproject.toml`：新增 `sse-starlette>=2.1.0` 依赖
- 新增 `backend/tests/unit/test_event_bus.py` 9 个用例（多订阅广播 / replay from_event_id / replay until_seq 切片 / jsonl 解析 / 并发 sequence / `subscribe_with_snapshot` 不重不丢 / counter 重启从 jsonl tail 恢复 / 路径解析 / silent 模式 / unsubscribe）；扩 `conftest.py` 加 `fresh_event_bus` + `task_with_events` fixture
- 新增 `backend/tests/unit/test_scenarios.py`：参数化遍历所有 scenario JSON，验证 ① 每条 event 能 `VisionEvent.model_validate` ② 每条 `ir_target.path + field` 通过 `path_validator` 命中真实 IR ③ `parent_event_id` 都向前引用
- 扩展 `.env.example`：加 `MODEL_PROVIDER` / `ANTHROPIC_API_KEY` / `DUAL_CHECK_STAGES` / `ENABLE_DEV_MOCK`
- 新增 frontend Anthropic 风 design tokens：`tokens.css`（颜色/字体/间距/圆角/stage 染色 + bbox 脉冲、IR 字段闪烁、事件卡片入场三套动画）+ `global.css`（@tailwind 注入 + se-* 组件类）；`tailwind.config.ts` 把 token CSS 变量桥接到 Tailwind theme；`postcss.config.js` 启用 tailwindcss + autoprefixer
- 新增 frontend Workbench 三栏页面：
  - `Workbench.tsx`：仅订阅 SSE（不叠 fetchEventHistory）+ `useTaskStatus` hook 1.5s 轮询 `/api/tasks/{id}` 显示 `status · progress% · stage`（终态自动停轮询）；顶 bar 含累计事件/tokens/耗时 + 暂停按钮
  - `WorkbenchVisionPane.tsx` 左栏：根据 `selectedEventId` 显示帧 + bbox overlay；动态读取 `<img onLoad>` 的 `naturalWidth/Height`，避免 1A+ 真实帧分辨率不同时 bbox 错位
  - `WorkbenchEventStream.tsx` 中栏：事件卡片倒序 + URL `?stage_filter=&time_range=` 双维过滤 + parent 因果链气泡 + 否决线穿；键盘快捷键 ↑↓ 切换 / Enter 滚动卡片到视图（左栏帧已自动联动）/ X 切换否决态；INPUT/TEXTAREA focus 时跳过；listener 用 ref 单次绑定（不随事件流重装）
  - `WorkbenchIRPane.tsx` 右栏：react-arborist 渲染 IR 树，宽高用 `ResizeObserver` 测父容器（响应式）；`flashPath = field ? path + "." + field : path` 与 store `writeIr` 落地路径一致，最近写入字段 800ms 闪烁
  - `EventBadge.tsx` stage 前缀染色；`BboxOverlay.tsx` 0-999 → 像素映射的 SVG overlay
- 新增 frontend `WorkbenchLauncher.tsx`（`/workbench/dev` 入口）：列出 mock scenarios + 启动按钮 → 调 `mock-stream` → navigate 到 `/workbench/{task_id}`
- 新增 frontend `api/events.ts`：`subscribeEvents` 封装 EventSource（vision/done 事件分发 + URL encode + teardown）/ `fetchEventHistory` / `startMockStream` / `listScenarios`
- 新增 frontend `state/workbench.ts`：Zustand store
  - `irSnapshot`：immer + `lodash.set/get/unset` 增量写入；按 op 分支处理（set/append/remove），append 走 `lodash.get` + `Array.push`（缺失时初始化为单元素数组）；append 不再被误当 set 处理
  - 反向 `childIndex` 支持因果链查找
  - `vetoedIds: Set<string>` + `toggleVetoed(id)` action
  - `autoFollow: boolean`：默认 true 时 `appendEvent` 自动选中最新事件；`setSelected` 切为 false（用户主动选中后停止自动跟随）；`reset` 复位为 true
- 新增 frontend 本地类型镜像 `types/workbench.ts`：`VisionEvent` / `IRTarget` / `ScenarioListItem` 与 pydantic 字段精确对齐（`ir_value: unknown`，与后端 Any 对齐），避免依赖 `pnpm gen:types` 才能编译
- 新增 frontend vitest 配置（jsdom + globals + setup 引入 jest-dom）+ 关键测试：`api/events.test.ts`（FakeEventSource 验证 onEvent / onDone / teardown / URL encode）/ `EventBadge.test.tsx`（stage 前缀染色映射 + 渲染断言）/ `BboxOverlay.test.tsx`（0-999 → 像素映射 + SVG rect 属性断言）
- 扩展 frontend `package.json`：依赖加 tailwindcss 3.x / postcss / autoprefixer / @radix-ui/{dialog,tabs,tooltip} / lucide-react / react-arborist / immer / lodash + @types/lodash；devDeps 加 vitest 2.x / jsdom / @testing-library/{react,jest-dom}；`test` 脚本改 `vitest run`
- 扩展 frontend `tsconfig.json`：`types` 加 `vitest/globals`，`include` 覆盖 vitest/tailwind/postcss 配置文件
- 扩展 frontend `main.tsx`：导入 `styles/global.css`；加 Shell 顶部导航条；新增路由 `/workbench/dev` 与 `/workbench/:taskId`
- 扩展 `.github/workflows/ci.yml` frontend job：在 typecheck 后追加 `pnpm -F @sceneecho/frontend test` 步骤

### 自我审计修复（深度审计后并入本次实现）
本阶段实现过程中两轮深度审计识别的设计/正确性问题，全部已并入上面的"改动"列表。这里仅留作记录，供后续阶段参考思路：

**架构性（按第一性原理重构，非打补丁）：**
- **EventBus 队列丢事件**：原方案 `q.put_nowait` + `maxsize=1024` 在突发流下 `QueueFull` 静默丢，破坏 D9 "AI 调用必发 VisionEvent" 契约。最终用 `await q.put` + 无界 queue 反压发布者
- **sequence high-water mark race**：原方案靠 SQL `tasks.last_event_sequence` 维护，与 jsonl 真实状态有 race（write-then-crash 时 SQL 落后 jsonl）。最终改为 lazy 从 jsonl 最后一行读，jsonl 是唯一真理源；删除 SQL `last_event_sequence` 列与 `bump_event_sequence` 函数
- **event_bus ↔ tasks_store 循环依赖**：原方案靠函数体内 local import 解。最终用 `set_lookup_callback` 依赖注入彻底解开，event_bus 模块不再 import tasks_store，分层依赖单向
- **mock scenarios IR path 与真实 TemplateIR 不齐**：原方案用 `skeleton.slots[X]`、`zoom_keyframes={direction:推进}` 等想象路径，1A 接入真 VLM 必须再改一次。最终改为真实路径（`skeleton[X].style.caption`、`zoom_keyframes` 第一阶段不写、第二阶段写 list 等），删除 1A 才扩展的字段（`placeholder_text` / `length_constraint` / `semantic_purpose` / `verified_stagger_ms` / `alt_proposed`）；新增 `path_validator.py` + `test_scenarios.py` 把漂移卡死在 CI
- **SSE history-vs-live race**：原 "先 replay 再 subscribe" 在 window 内的 publish 永久丢失。最终改为 `subscribe_with_snapshot` 在 lock 内原子拿 (queue, snapshot)，`replay(until_seq=snapshot)` 切分，从根本消除重叠（也连带删除原"在 live 流中 dedup-by-sequence"补丁式逻辑）

**正确性 / UX：**
- **WorkbenchIRPane flashPath 丢 field**：原 `flashPath` 仅取 `ir_target.path`，命中不到子字段写入。最终 `flashPath = field ? path + "." + field : path`，与 store `writeIr` 落地路径一致
- **WorkbenchIRPane 高度硬编码 600px**：父容器尺寸变化时 tree 内部滚动而非容器滚动。改为 `ResizeObserver` 测父高度
- **Workbench 顶 bar 缺 stage / progress**：补 `useTaskStatus` hook 1.5s 轮询 `/api/tasks/{id}`，渲染 `status · progress% · stage`（终态自动停轮询），补齐 PLAN.md 1314 要求
- **EventStream 缺 PLAN 1317 要求的 Enter / X 快捷键**：补齐
- **`selectedEventId` 自动跟随跳屏**：原实现一律自动选中最新事件，用户用 ↑↓ 选定后视图被新事件强行拽走。加 `autoFollow` 开关，用户主动选中后停止跟随
- **VisionPane bbox overlay 硬编码 1080×1920**：1A+ 真实帧分辨率不同会错位。改为读取 `<img onLoad>` 的 `naturalWidth/Height`，frame_url 切换时重置
- **EventStream 键盘监听重装**：`useEffect` deps 含 `events / selectedId`，每条事件都拆装 window listener。改为 ref 暂存最新值，listener 只装一次
- **op="append" 当 set 处理**（state/workbench.ts）：原实现忽略 op 类型一律 set，下次同路径 append 会覆盖整个数组。改为按 op 分支：append 走 `lodash.get` + `Array.push`（缺失时初始化为单元素数组），remove 用 `lodash.unset`
- **Workbench.tsx 双拉历史**：原本同时调 `fetchEventHistory` + `subscribeEvents`，前者 resolve 后 `setHistory` 会覆盖期间已 append 的 SSE 事件。SSE 端点已自带 history replay，去掉前者；连带删除已死代码 `setHistory` action 与 `seenIds` 集合
- **完成态空流不关闭**（events.py）：任务标完成但订阅时机晚于 close_task → SSE 永远 wait_for 超时。在 history replay 完成后立即检查任务状态；timeout 分支也复查
- **scenario replay 异常使任务卡 running**（dev_workbench.py）：循环里 publish 抛错让 BackgroundTask 直接退出，task 永停在 `running`、SSE 永等不到 done。整段循环 try/except，失败时落 `status="failed"` + `close_task` 收尾
- **subscribeEvents `ping` 监听器死代码**：sse-starlette 心跳是 SSE 注释行，浏览器不触发 named event。删除
- **`ir_value` 类型 `dict | None`**：dict 限制太严，无法表达标量值（如 `CaptionStyle.anim_in: str`）。改为 `Any`（前端 `unknown`），与 lodash.set 写入语义一致
- **render-demo 任务未升级到新 `create_task` kwargs**：补传 `resource_kind="project" + resource_id=project_id`，Phase 0 demo 任务也走方案 B 路径
- **dead code 与吞错日志**：删除 `EventBus.publish_many_sync`（无调用方）；`_lookup_path` 等位置的 bare `except: pass` 改为 log warning 便于排障

### 涉及文件
- `backend/app/ir/vision_event.py`：新建 — VisionEvent / IRTarget pydantic 模型（`ir_value: Any`）
- `backend/app/ir/path_validator.py`：新建 — lodash 风路径校验器（CI 验证 mock JSON 命中真实 IR）
- `backend/app/ir/template.py`：扩展 — StickerEvent.semantic_category
- `backend/app/ir/export.py`：扩展 — TOP_LEVEL_MODELS 加入 IRTarget / VisionEvent
- `backend/app/event_bus.py`：新建 — 事件总线（subscribe_with_snapshot / await put 反压 / jsonl tail seq 真理源 / lookup callback 注入 / replay until_seq）
- `backend/app/tasks_store.py`：扩展 — schema 加 3 列 + idempotent migration + create_task 扩参；不含 last_event_sequence / bump_event_sequence
- `backend/app/config.py`：扩展 — model_provider / anthropic_api_key / enable_dev_mock / dual_check_stages
- `backend/app/main.py`：扩展 — events / dev_workbench 路由挂载 + lifespan 挂 event_bus + 注入 lookup callback + system/dev_events 目录
- `backend/app/api/samples.py`：扩展 — render_demo 接入 resource_kind=project 路径
- `backend/app/api/events.py`：新建 — SSE（subscribe_with_snapshot 切分 history/live + 完成态自动关流）+ history 端点
- `backend/app/api/dev_workbench.py`：新建 — mock-stream / scenarios 列表（dev gated）+ 失败兜底
- `backend/app/llm/__init__.py`、`backend/app/llm/client.py`：新建 — LLMClient ABC + 占位实现
- `backend/app/llm/prompts/__init__.py`、`backend/app/llm/prompts/scenarios/{captions_demo,stickers_demo,full_extract_demo}.json`：新建 — Phase 0.5 mock 事件脚本（path 命中真实 TemplateIR）
- `backend/pyproject.toml`：扩展 — 加 sse-starlette
- `backend/tests/conftest.py`：扩展 — fresh_event_bus / task_with_events fixtures
- `backend/tests/unit/test_event_bus.py`：新建 — 9 个事件总线单测
- `backend/tests/unit/test_scenarios.py`：新建 — mock JSON 静态校验（parse / path / parent 顺序）
- `.env.example`：扩展 — Phase 0.5 新增 4 个 env 变量
- `.github/workflows/ci.yml`：扩展 — frontend job 加 vitest 步骤
- `frontend/package.json`：扩展 — 依赖 + test 脚本
- `frontend/tsconfig.json`：扩展 — types + include
- `frontend/postcss.config.js`、`frontend/tailwind.config.ts`：新建 — Tailwind 工具链
- `frontend/vitest.config.ts`、`frontend/test-setup.ts`：新建 — 测试运行器
- `frontend/src/styles/{tokens.css,global.css}`：新建 — design tokens + 全局样式
- `frontend/src/main.tsx`：扩展 — Shell + 工作台路由
- `frontend/src/api/events.ts`、`frontend/src/api/index.ts`：新建/扩展 — SSE 订阅（无 ping 死代码）+ 子模块导出
- `frontend/src/state/workbench.ts`：新建 — Zustand store（按 op 分支增量写 IR / vetoedIds / autoFollow）
- `frontend/src/types/workbench.ts`：新建 — 本地类型镜像（ir_value: unknown）
- `frontend/src/pages/Workbench.tsx`：新建 — /workbench/:taskId 三栏（仅订阅 SSE + useTaskStatus 顶 bar 显示 status/progress/stage）
- `frontend/src/pages/WorkbenchLauncher.tsx`：新建 — dev 入口
- `frontend/src/components/workbench/{WorkbenchVisionPane,WorkbenchEventStream,WorkbenchIRPane,EventBadge,BboxOverlay}.tsx`：新建 — 三栏 + badge + bbox overlay；VisionPane 动态读取帧 naturalWidth/Height；EventStream 键盘 ↑↓/Enter/X 单次绑定 + 否决视觉；IRPane flashPath 含 field + ResizeObserver 高度
- `frontend/src/api/events.test.ts`、`frontend/src/components/workbench/{EventBadge,BboxOverlay}.test.tsx`：新建 — 关键单测
- `docs/001ARCHITECTURE.md`：扩展 — 拓扑图加 SSE 通道、分层加事件总线、状态分类增 jsonl 行（jsonl 是 sequence 真理源）、加链路 C、追加 D9-D12 约定（含 ir_value: Any、event_bus 不依赖 tasks_store、SSE 用 snapshot 切分、tasks 表三列）
- `docs/002STRUCTURE.md`：扩展 — 同步 backend/app/{event_bus,llm,api/events,api/dev_workbench,ir/vision_event,ir/path_validator} + tests/unit/test_scenarios.py + frontend 全部新增文件

### 关联
-> PLAN.md 阶段 0.5（1246-1344 行）

---

## [2026-06-07-2] feat(plan): add v3.2 workbench v4 upgrade — gantt + causal chain + regression fixture

### 改动
- `PLAN.md` 新增 **Phase 2.6 AI 决策工作台 v4 升级** 阶段（位于 Phase 2.5 之后、Phase 3 之前），打包 `docs/proposals/001-ai-decision-workbench-v4.md` 的 3 条 🟢 P1 提案：
  - **O11 甘特图视图**：用 `@visx/scale + @visx/zoom + @visx/group` 实现 SVG 甘特图；lane × 时间轴 × 横条/竖线 × 因果连线；与中栏 EventStream 共享 `selectedEventId` 双向联动
  - **O3 因果链可视化**：parent_event_id 强约束 + 工作台 SVG dashed line 连父子事件 + hover 联动；不加 child_event_ids 双向链（前端 O(1) 反向构建索引足够）
  - **O2 events.jsonl 作 regression fixture**：`ReplayClient(LLMClient)` 重放 golden events → CI 跑 `test_golden_runs.py` 比对 IR 一致性；模型升级/子能力代码改动时 IR 字段语义漂移立即被发现
- **技术栈第一性原理选型**：visx（airbnb 出品的 d3 + React 融合库）而非 TapFlow 借鉴的命令式 D3.js——后者与实时 SSE 增量场景不匹配、与现有 React 心智模型冲突；visx 是 React 友好的 D3 包装（d3-scale/d3-zoom 的 hooks），bundle ~50KB gzipped，天然支持增量渲染
- **前期阶段零成本"埋点"**（无新工程，只是约束声明）：
  - Phase 0.5 `VisionEvent` IR 加 `duration_ms: int = 0` 字段；`chat_vision()` 客户端层用 `time.perf_counter()` 自动回填——子能力代码零侵入
  - Phase 1A 设计约束追加"两阶段 VLM 调用必填 `parent_event_id`"强约束 + CI `scripts/check_parent_event_id.py` 校验脚本
  - Phase 1B 验证方式追加第 8 条 "Golden runs 种子录制"——完工 close-out 时把 ≥ 3 个 fixture 的 events.jsonl + TemplateIR 复制到 `tests/fixtures/golden_runs/` git-commit
- **其他章节同步**：阶段总览表加 Phase 2.6 行 + 依赖链改为 0 → 0.5 → 1A → 1B → 2 → 2.5 → 2.6 → 3 → 7 → 4 → 5；技术栈表加 visx 行；末尾追加 v3.2 修订说明

### 涉及文件
- `PLAN.md`：新增 Phase 2.6 完整章节（前置条件 / 目标 / 设计约束 / 后端 / 前端 / CI / 验证方式 / 课题对齐 / 已明确不做）+ 4 处其他章节小改（阶段总览 / 依赖链 / 技术栈 / VisionEvent IR / Phase 1A 约束 / Phase 1B 验证 / CI 脚本约定 / v3.2 修订说明）
- `docs/proposals/001-ai-decision-workbench-v4.md`：本次新增功能的提案文档（用户认可 O11/O3/O2 三条 P1）

### 关联
-> docs/proposals/001-ai-decision-workbench-v4.md

---

## [2026-06-07-1] docs(plan): fix v3.1 consistency issues [N1-N21]

### 改动
- `PLAN.md` 修复 v3.1 修订后通读核查发现的 21 处内部不一致（详见 `docs/proposals/002-v3p1-consistency-fixes.md`），分三类：
  - **P0 schema bug**（N1）：`VisionEvent.source` Literal 补 `text_llm`，与 D13 拓宽对齐；不修则 Phase 3 Step 03 Text LLM 去重的事件会 pydantic 校验 fail
  - **P1 路径方案 B 残留**（N2-N3）：关键机制"事件持久化"段 + Phase 3 D13 强化段把旧的 `pipeline/events.jsonl` 改为 v3.1 方案 B 的 `events_{task_id}.jsonl` + `event_bus.publish` 按 `tasks.resource_kind` 路由的描述；Phase 3 stage 列表补 `3.step01.asr` / `3.step09.render`
  - **P1 D13 拓宽未同步**（N4-N14）：把 10 处"VLM 调用必发事件"统改为"AI 调用必发事件"（含视频理解技术选型表尾段、工作台事件流章节、AI 调用协议章节标题、VisionEvent 章节首句、`model_used` / `cost_tokens` 字段注释、Phase 0.5 D13 + `chat_vision` 强约定、Phase 1A 验证 5、关键设计决策 D13、"已明确不做"VLM 静默调用、Phase 3 累计 token 数描述）
  - **P2 数量描述**（N15-N16）：`Patch` op 数量 5→4（移除已被替换为 Workbench API 的 `replay_vision_event`）、Phase 7 前置条件 6 项→7 项验证
  - **P3 结构/格式**（N17-N19）：`backend/app/api/lab.py` 从 Phase 1A 前端改动段移到后端段；fixtures 表格前补空行；stage 命名规范表 Phase 3 行补 `3.step01.asr` / `3.step09.render`
  - **CI 脚本约定 + 历史标注**（N20-N21）：CI yaml 后追加 `scripts/check_stage_naming.py` / `scripts/check_event_emission.py` 约定；v3 改动总结里 source 5 个枚举 / D13 VLM 描述两条原文末尾追加 v3.1 修订标注，原文保留作为历史快照

### 涉及文件
- `PLAN.md`：21 处修订点（详见提案文档锚定字符串）
- `docs/proposals/002-v3p1-consistency-fixes.md`：本次修复的执行清单（含验收 grep 11 条全部通过）

### 关联
-> docs/proposals/002-v3p1-consistency-fixes.md

---

## [2026-06-06-2] fix(renderer): Serve user material over HTTP /data instead of file:// URLs [ISS-005]

### 改动
- `renderer/src/render.ts` 移除 `pathToFileURL` 导入；新增 `BACKEND_URL` 常量（env `BACKEND_URL`，默认 `http://localhost:18521`）
- `renderer/src/render.ts` 将 `inputProps.userMaterialUrl` 从 `file:///...` 改为 `${BACKEND_URL}/data/<rel>`，路径每段 `encodeURIComponent`
- `docs/001ARCHITECTURE.md` 调用方向约束补 renderer → backend `/data` GET；运行时链路 A 标注 Chromium 通过 HTTP 取字节；新增约定 D8

### 涉及文件
- `renderer/src/render.ts`：把用户素材 URL 切到后端静态路由
- `docs/001ARCHITECTURE.md`：同步约束 + 链路 A + D8

### 关联
-> ISS-005

---

## [2026-06-06-1] feat(phase0): Scaffold three-service skeleton with IR codegen and render demo [ISS-001] [ISS-002] [ISS-003] [ISS-004]

### 改动
- 新建根 workspace：`pnpm-workspace.yaml`、`package.json`（dev / gen:types / build / lint）、`.env.example`，扩展 `.gitignore` 加入 node_modules / data / 生成产物 / venv
- 新建后端骨架：FastAPI 入口 + lifespan + CORS + /data 静态挂载；`config.py` pydantic-settings + REPO_ROOT 解析;`logging.py` structlog JSON;SQLite tasks 表 CRUD（WAL）;typer CLI ingest（gated by ENABLE_CLI_INGEST）
- 新建后端 IR 包：`ledger / template / project / patch` pydantic 模型 + `export.py` 聚合导出 JSON Schema
- 新建后端 API：`POST /samples` 上传 + ffmpeg normalize；`POST /samples/{id}/render-demo` 构造最小 ProjectIR + 触发 BackgroundTask；`POST /projects` 占位；`GET /tasks/{id}` + `POST /internal/task-progress`
- 新建 render 客户端：httpx 调 renderer `/render`；`ffmpeg.py` normalize / probe / thumbnail wrapper
- 新建后端测试：`conftest.py` temp DATA_ROOT + fixtures 拷贝；IR schema 导出与最小 ProjectIR round-trip 单测
- 新建 IR codegen：`scripts/gen_schema.py` 调 `app.ir.export.export_json_schema`；`renderer/scripts/gen-types.ts` 与 `frontend/scripts/gen-types.ts` 用 json-schema-to-zod 生成 zod schema + TS 类型
- 新建 renderer 服务：Express :8001 + p-queue 单 worker；`bundle + selectComposition + renderMedia` 渲染链；pino logger；`POST /api/internal/task-progress` 回调；`paths.ts` ESM-safe 路径解析
- 新建 Remotion compositions：`Root.tsx` 含 `calculateMetadata`；`Project.tsx` Sequence+OffthreadVideo+Caption；`Caption.tsx` 字幕渲染；`projectMeta.ts` 共享元数据计算
- 新建前端：Vite + React + zustand + axios；`SampleExtract.tsx` 上传/渲染/预览；`TaskProgress.tsx` 1s 轮询进度
- 新建 CI：`.github/workflows/ci.yml` 四 job（type-sync / python / renderer / frontend）；type-sync 阻塞合并
- 新建 dev 文档：`docs/dev-setup.md`
- 二次核查修复（已写入 003ISSUES.md，本次实现的组成部分）：
  - ISS-001：`gen-types.ts` 弃用 `name+module:"none"` 组合，改用裸表达式 + 手动 `export const ... Schema` 包装
  - ISS-002：`ffmpeg.normalize` vf 改为 `force_original_aspect_ratio=decrease + pad` 标准惯用法，移除不稳定的表达式语法
  - ISS-003：抽 `projectMeta.ts` 共享元数据；`Composition` 加 `calculateMetadata`；`render.ts` 移除 `targetComposition` 覆盖
  - ISS-004：CLI `_require_enabled` 在 raise 前 stderr 输出明确提示

### 涉及文件
- `package.json`、`pnpm-workspace.yaml`、`.env.example`、`.gitignore`：新建/扩展 — 工作区与环境模板
- `.github/workflows/ci.yml`：新建 — 四 job CI
- `scripts/gen_schema.py`：新建 — pydantic → JSON Schema 入口
- `backend/pyproject.toml`、`backend/ruff.toml`：新建 — 依赖与 lint 配置
- `backend/app/{main,config,logging,cli,tasks_store}.py`：新建 — 应用入口与基础设施
- `backend/app/ir/{__init__,ledger,template,project,patch,export}.py`：新建 — IR pydantic 模型与导出
- `backend/app/api/{__init__,samples,projects,tasks}.py`：新建 — HTTP 路由
- `backend/app/render/{__init__,client,ffmpeg}.py`：新建 — 渲染客户端与 ffmpeg wrapper；`ffmpeg.py` 修复 ISS-002
- `backend/tests/{conftest,unit/test_ir_models,unit/test_ir_schema}.py`：新建 — fixture loader + 单测
- `renderer/{package.json,tsconfig.json,tsconfig.build.json}`：新建 — Node 工程配置
- `renderer/scripts/gen-types.ts`：新建 — IR codegen（修复 ISS-001）
- `renderer/src/{server,render,queue,progress,logger,paths,remotion.root}.ts(x)`：新建 — 服务/渲染/队列/日志/路径；`render.ts` 修复 ISS-003
- `renderer/src/compositions/{Root,Project,Caption}.tsx`、`projectMeta.ts`：新建 — Remotion 组件；`Root.tsx` + `projectMeta.ts` 修复 ISS-003
- `frontend/{package.json,tsconfig.json,vite.config.ts,index.html}`：新建 — Vite 工程配置
- `frontend/scripts/gen-types.ts`：新建 — IR codegen（修复 ISS-001）
- `frontend/src/{main.tsx,api/index.ts,state/index.ts,components/TaskProgress.tsx,pages/SampleExtract.tsx}`：新建 — 路由/API 封装/状态/进度组件/上传页
- `docs/{001ARCHITECTURE,002STRUCTURE,003ISSUES,004CHANGELOG}.md`、`docs/dev-setup.md`：新建/重写 — 体系文档同步

### 关联
-> ISS-001
-> ISS-002
-> ISS-003
-> ISS-004
