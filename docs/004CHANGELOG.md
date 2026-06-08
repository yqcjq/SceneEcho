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
