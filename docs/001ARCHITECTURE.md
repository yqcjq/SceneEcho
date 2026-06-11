# SceneEcho 整体架构

> 风格约束（依 `000README.md`）：陈述句描述当前事实，不写历史、不写优缺点、不写"未来可以考虑"、不写被否定的方案、不放目录树。详细推理见 `decisions/`，目录树见 `002STRUCTURE.md`。

---

## 1. 系统拓扑

```
┌──────────────────────────┐   HTTP /api/*    ┌────────────────────────────┐
│  Frontend (Vite, :5173)   │ ───────────────▶ │  Backend (FastAPI, :18521)  │
│  React + Remotion Player  │ ◀── /data/* ──── │  app/{api, ir, render,      │
│  + Workbench (/workbench) │ ◀══ SSE  /api/   │       event_bus, llm}       │
│                          │     tasks/{id}/   └────────────┬───────────────┘
│                          │     events ══════              │ HTTP /render
└──────────────────────────┘                                ▼
                                              ┌────────────────────────────┐
                                              │ Renderer (Express, :8001)  │
                                              │ Remotion + Chromium → mp4  │
                                              └────────────────────────────┘
                                                           │
                                                共享卷 DATA_ROOT (本地 backend/data/)
```

三服务通过 HTTP + JSON 通信，共享 `DATA_ROOT` 文件系统读写媒体。前端不直渲染像素，调用后端 API 触发渲染，渲染产物经后端 `/data/*` 静态路由回放。AI 决策事件（VLM / Text LLM / ASR / audio / CV）经后端进程内 `event_bus` 广播，浏览器走 SSE 长连接订阅 `/api/tasks/{id}/events`。

---

## 2. 分层结构

```
┌──────────────────────────────────────────────┐
│ UI 层（frontend/src/{pages, components})      │
│ 仅通过 api/index.ts 与后端通信，状态走 Zustand │
└──────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────┐
│ 编排层（backend/app/api）                     │
│ HTTP 路由，触发任务，组装 IR                  │
│ events.py / dev_workbench.py 出 SSE 事件流   │
└──────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────┐
│ 事件总线（backend/app/event_bus）             │
│ 进程内 asyncio 广播 + jsonl 持久化（方案 B）  │
└──────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────┐
│ 能力层（backend/app/{render, ir, llm,         │
│        extract, understand}）                 │
│ FFmpeg 归一化 / IR 校验 / 渲染客户端 /        │
│ LLMClient（OpenAI-compat + Anthropic 双适配  │
│ 器，缺凭据 fallback）+ Phase 1A 11 个视觉子 │
│ 能力（Phase1AContext 入参 + STAGE 模块常量  │
│ + lazy ML import + Phase1AReport ir_target） │
└──────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────┐
│ 渲染层（renderer/src）                        │
│ Remotion 组件 + bundle + renderMedia          │
└──────────────────────────────────────────────┘
```

IR（pydantic 模型）位于 `backend/app/ir/`，作为「人 / AI / 渲染器」共同语言。前端与渲染器的 zod schema + TS 类型由 `scripts/gen_schema.py` + `{renderer,frontend}/scripts/gen-types.ts` 从 pydantic 模型自动生成到 `shared/ir.schema.json` → `*/src/types/ir.ts`。

---

## 3. 调用方向约束

- 前端只调 `/api/*`；不直连 renderer。
- 后端 `api/` 只 import `app/{ir,render,tasks_store,config,logging,event_bus,llm,extract,understand,kb,apply}`；不反向依赖 frontend / renderer 进程。
- renderer 不调后端业务 API，仅通过 `POST /api/internal/task-progress` 上报进度，并通过 `GET {BACKEND_URL}/data/*` 拉取用户素材字节。
- IR 类型方向：pydantic（唯一真相源）→ JSON Schema → 两端 zod/TS；CI 的 `type-sync` job 阻塞反向修改。
- 跨服务文件传递只用相对 `DATA_ROOT` 的 POSIX 路径字符串，禁止绝对路径。
- AI 客户端（`app.llm.client`）只通过 `event_bus.publish` 广播事件；调用方不得绕过客户端层直接发事件。
- `event_bus` 不依赖 `tasks_store`：`main.py` lifespan 注入 `tasks_store.get_task` 作为 lookup callback；`tasks_store.create_task` 仅静态调用 `EventBus.resolve_events_path` 计算路径，不引入运行时反向依赖。
- `extract/*` 子能力模块只 import `app/{ir,event_bus,llm,extract,logging,config,render}`；不反向依赖 `api/` 或 `understand/`，调度 / 编排在 `api/lab.py`（dev）以及 `extract/pipeline.py`（1B 完整 DAG）里。
- `kb/*` 只 import `app/{ir,event_bus,llm,extract,frame_sampler,config,logging}`；`api/templates.py` 调 `kb.store`，`extract/pipeline.py` 调 `kb.store` 落库。`kb` 不反向依赖 `api/`。
- `apply/*` 只 import `app/{ir,event_bus,llm,kb,understand,render,config,logging,tasks_store}`；不反向依赖 `api/` 或 `extract/`。编排在 `apply/pipeline.py`，HTTP 入口在 `api/projects.py`。Phase 2 ★MVP 闭环全部走这条链。
- `agent/*` 只 import `app/{ir,event_bus,llm,tasks_store,config,logging,kb,render}`；不反向依赖 `api/` / `apply/` / `extract/`。`agent/nl_edit.py` 是 Phase 2.5 Patch 调度核心，被 `api/edit.py` 调用。`agent/aigc.py` 是 Phase 5 AIGC 生成层调度核心（hash 缓存 + 事件 + provider 工厂 + ffmpeg 把 provider 的图像字节循环成 mp4），被 `apply/fill.py` 调用——它对 `app/render/ffmpeg.py::image_to_video` 的依赖是单向的工具复用（与 `apply/` / `api/` 复用 `render/ffmpeg.py` 同性质）；`agent/aigc_providers/{name}.py` 子包是纯 HTTP 适配层，只 import `httpx` + `app/{config,logging}` + `agent/aigc.py` 的 typed exceptions（lazy import 避免循环），**绝不调 event_bus.publish**——事件统一在 `agent/aigc.py` 上层发，确保 D13 守卫只校验一处。`render/throttle.py` 由 `api/edit.py` 与 `api/projects.py` 直接 import 用于 BackgroundTask（不属于 agent/，因为渲染节流是 render 模块自身的能力扩展，不是 LLM 决策）。
- `understand/vision.py` 是语义层，依赖 `extract/captions.py` 的 `CaptionEvent` dataclass + `llm/client.py` 的 `chat_vision`；caption_function 之类的"phase2 分类"由调用方在拿到 `extract` 输出后再调，并通过 `parent_event_id` 把事件挂到对应的 caption 实体事件下。
- 重 ML 依赖（PySceneDetect / opencv-python-headless / librosa / Demucs / torch）放在 `pip install -e ".[extract]"` 可选 extras；每个 `extract/*` 模块在用前 `try: import ... except ImportError`，缺包时返回 fallback 形状 + 发 `severity="warning"` VisionEvent，不阻塞 pipeline。

---

## 4. 状态持久化分类

| 数据类型 | 存储位置 | 说明 |
|---------|---------|------|
| 任务态（progress / stage / result + resource_kind/id + events_jsonl_path） | `DATA_ROOT/kb.sqlite` 的 `tasks` 表 | WAL 模式；后端写、前端读 |
| 模板库（TemplateIR + tags + thumbnail + last_extract_task_id） | `DATA_ROOT/kb.sqlite` 的 `templates` 表 | WAL；`api/templates` 读写 / `extract/pipeline` 写 |
| 上传媒体 / 归一化产物 / 渲染输出 | `DATA_ROOT/{samples,projects}/...` | 文件系统，相对路径在 IR 内引用 |
| AIGC 生成产物（B-roll mp4 / sticker png） | `DATA_ROOT/aigc/{broll,stickers}/{hash}.{mp4,png}` | 永久缓存，按 `(prompt, style_hint, duration)` 的 sha256 命名；同一请求不重复支付 API 费。`PlacedSegment.aigc_broll_path` 指向此目录 |
| ProjectIR / TemplateIR / TranscriptLedger | `projects/{id}/project.json`、`projects/{id}/transcript.json` 等 | JSON 落盘，供回放、调试；`transcript.json` 由 `recommend` 写、`apply` 读，跨阶段复用同一份 ledger |
| AI 决策事件流（VisionEvent jsonl） | `samples/{sid}/extracted/events_{task_id}.jsonl`、`projects/{pid}/pipeline/events_{task_id}.jsonl` | 路径方案 B：随资源走、task_id 作后缀；event_bus.publish 写入、SSE replay 与 history 端点读；同时承担 EventBus 的 sequence high-water mark 真理源（重启后 lazy 读最后一行恢复计数） |
| Remotion bundle | renderer 进程内存 + headless Chromium 缓存 | 启动后首次渲染缓存一次 |
| 前端 UI 态（工作台事件 / IR 快照 / 选中事件） | 浏览器内存（Zustand `useWorkbenchStore`） | 刷新走 SSE replay 重建，不持久化 |

---

## 5. 核心运行时链路

**链路 A：上传样例并渲染 Demo**
```
浏览器选文件
  → POST /api/samples (multipart)
     → backend.api.samples.upload_sample
       → 拷贝到 DATA_ROOT/samples/{sid}/source.mp4
       → render.ffmpeg.normalize（force_original_aspect_ratio=decrease + pad）
       → 写 normalized.mp4 + thumbnail.jpg
       → 返回 {sample_id, info}
  ← 前端拿到 sample_id
浏览器点"渲染 demo"
  → POST /api/samples/{sid}/render-demo
     → 构造最小 ProjectIR（1 PlacedSegment + 1 Caption "Hello SceneEcho"）
     → 落 projects/{pid}/project.json
     → tasks_store.create_task("render") → task_id
     → BackgroundTask: render.client.render_project(ir, task_id)
        → httpx.post {RENDERER_URL}/render {project_ir, task_id}
           ↓
     renderer.server.POST /render
        → renderQueue.add(job)
        → render.renderProjectIR(projectIR, task_id)
           → 把 projectIR.user_material 拼成 `{BACKEND_URL}/data/<rel>`，作为 inputProps.userMaterialUrl
           → 首次：bundle(remotion.root.tsx) 缓存
           → selectComposition({serveUrl, id:"Project", inputProps})
              （触发 Composition.calculateMetadata 从 IR 推导 width/height/fps/duration）
           → renderMedia 期间 headless Chromium GET {BACKEND_URL}/data/... 取字节
           → renderMedia onProgress → POST /api/internal/task-progress
           → 写 DATA_ROOT/projects/{pid}/outputs/render_{ts}.mp4
        ← {output_path, duration_sec}
     ← 后端 _run_render: tasks_store.update_task(status=completed, result)
  ← 前端 TaskProgress 轮询 /api/tasks/{id} 看到 status=completed
浏览器播放 /data/projects/{pid}/outputs/render_{ts}.mp4
```

**链路 B：CLI ingest（开发路径，`ENABLE_CLI_INGEST=true` 时启用）**
```
python -m app.cli ingest-sample /local/path.mp4
  → _require_enabled 校验 .env 开关
  → 拷贝到 samples/{generated_id}/source.mp4
  → render.ffmpeg.normalize → normalized.mp4 + thumbnail.jpg
```

**链路 D：Phase 1A SubcapabilityLab 单点验证（`ENABLE_DEV_MOCK=true` 时启用）**
```
浏览器 /lab
  → GET /api/lab/subcaps → 列出 10 个子能力（每条 {name, label, stage, baseline_key}）
  → GET /api/lab/samples → 运行时扫 data/samples/*/ 列出可跑样例 [{id, has_normalized, has_source, thumbnail_url}]
  → 用户选 subcap × sample（任意自由组合，无 fixture 兼容性约束），点「跑此子能力」
  ↳ 用户也可点「＋ 上传新样例」→ <input type="file"> → uploadSample() 调既有 POST /samples ingest
       → 上传完自动 refreshSamples + setFixture(new_id) 刷新 dropdown
浏览器 → POST /api/lab/run-subcap/{name} {fixture_id, dry_run:false}
  → backend.api.lab.run_subcap：
     → tasks_store.create_task("lab_<name>", resource_kind="sample", resource_id=fixture_id)
        路径方案 B → events_jsonl_path = samples/{fixture_id}/extracted/events_{task_id}.jsonl
     → BackgroundTask: REGISTRY[name].runner(Phase1AContext)
        runner 是 extract/* 子能力的薄编排（先 detect_scenes → frame_sampler → 该 subcap）
        每一步 chat_vision/chat_text 由 llm.client 自动 publish 事件 + 缺依赖时 fallback warning
     → 完成后 tasks_store.update_task(status=...) + bus.close_task → SSE done
  ← 返回 {task_id, workbench_url}
浏览器 navigate 到 /workbench/{task_id}
  → SSE 订阅同链路 C，看到该 subcap 的事件流（含 parent_event_id 因果链）
```

**链路 C：AI 透明工作台 mock 流（`ENABLE_DEV_MOCK=true` 时启用）**
```
浏览器打开 /workbench/dev
  → GET /api/dev/workbench/scenarios → 列出 captions_demo / stickers_demo / full_extract_demo
浏览器点 scenario 卡片
  → POST /api/dev/workbench/mock-stream {scenario}
     → 创建 dummy sample + 任务 (resource_kind="sample")，路径方案 B 写 events_jsonl_path
     → BackgroundTask: _replay_scenario(task_id, scenario)
        → 读 backend/app/llm/prompts/scenarios/{scenario}.json
        → 按 delay_ms 顺序: VisionEvent.model_validate → event_bus.publish
           → lock 内分配 sequence + append jsonl → lock 外 await q.put 广播
     → 返回 {task_id, workbench_url}
  ← 前端 navigate(workbench_url)
浏览器进入 /workbench/{task_id}
  → useEffect: subscribeEvents(task_id) 建 EventSource 订阅 /api/tasks/{task_id}/events
     → 后端 _stream: subscribe_with_snapshot 原子拿 (queue, snapshot) → replay(until_seq=snapshot) 推历史 → 队列推 live (>snapshot)；两段无重叠，前端无须 dedup
     → SSE: 每条 event 三行 (id / event:vision / data:json) + 心跳每 15s
     → useWorkbenchStore.appendEvent(event)
        → immer produce + lodash.set(draftIr, ir_target.path + field, ir_value) 写入 IR 快照
        → childIndex 反向索引 parent_event_id → child ids
        → autoFollow=true 时自动选中最新事件；用户首次主动选中后切为 false
  ← 三栏渲染：左帧+bbox / 中事件流卡片 (↑↓/Enter/X) / 右 IR 树（含 field 的命中字段闪烁）
任务完成 → close_task → SSE event: done → 浏览器 EventSource 关闭
```

**链路 E：Phase 1B 模板提取 → KB**
```
浏览器 /sample-extract
  → POST /api/samples (multipart)         # 已有，沿用链路 A 的上传
  → POST /api/samples/{sid}/extract       # 1B 新增
     → tasks_store.create_task("extract_template", resource_kind="sample", resource_id=sid)
        路径方案 B → events_jsonl_path = samples/{sid}/extracted/events_{task_id}.jsonl
     → BackgroundTask: extract_template(sid, task_id)
        → Phase1AContext(sid, normalized.mp4, task_id)
        → ffprobe duration → 发 1B.pipeline start event
        → _run_phase1a (asyncio.gather 七路并发):
             captions / stickers / zoom_direction / transitions / masks / color_lut / audio
             每个子能力包在 _safe(label, field_key, coro): 抛异常→ degraded[_ir_path_for(field_key)]=str(e)
             + 发 severity=warning 事件 + 不阻塞其他 branch（D21）
          ↓
        → 依赖层串行 fan-out:
             zoom_curve（仅 direction != 稳定 的 scene）
             caption_function（per caption，承担功能 + 动画类型）→ Phase1AReport.caption_functions
        → assemble Phase1AReport
        → build_skeleton(report, duration, task_id): 位置阈值发现三段
                                                    + caption_style_palette 聚类
                                                    （每个 Slot.style.caption_palette_idx 引用 idx）
                                                     → list[Slot] + per-slot 事件
        → tagging.suggest_tags(ir, frames, task_id):  1 次 VLM → Tags
        → sanity.sanity_check(ir, frames, task_id):    1 次 VLM → {ok, issues, ...}
        → kb_store.save_template(ir, thumbnail_path, last_extract_task_id=task_id)
           INSERT OR REPLACE INTO templates  (kb.sqlite WAL)
        → 发 1B.pipeline.done 事件 + tasks_store.update_task(status=completed)
        → bus.close_task(task_id)
  ← 浏览器 navigate /workbench/{task_id} 看 ≥ 10 条事件 + degraded 字段实时填充
  ← 完成后 /templates 列表出现新模板
  ← /templates/{id} 详情：骨架可视化 + sanity verdict + placeholder 编辑 +
     「回放工作台事件流」按钮 → /workbench/{last_extract_task_id} 重读 jsonl
```

**链路 F：Phase 2 ★MVP 应用闭环 — 短素材 + 模板 → MP4**
```
浏览器 /editor 上传用户素材
  → POST /api/projects (multipart)
     → 拷贝到 projects/{pid}/user_material.mp4
     → render.ffmpeg.normalize → normalized.mp4
     → 返回 {project_id}
浏览器点「VLM 推荐 top-3」
  → POST /api/projects/{pid}/recommend-templates
     → tasks_store.create_task("recommend_templates", resource_kind="project")
        路径方案 B → events_jsonl_path = projects/{pid}/pipeline/events_{task_id}.jsonl
     → 同步跑：understand.asr.transcribe（三层降级 glm/whisperx/uniform；GLM 路径 = PPIO GLM-ASR-2512 取文本 + WhisperX wav2vec2 forced alignment 给字级时间戳；Unit 切分按 gap+max_chars+min_chars+标点四因素）→ 写 projects/{pid}/transcript.json 给 apply 复用 → frame_sampler.sample_frames（首/中/末）
            → kb.recommend.recommend_templates（一次 VLM call 看 ≤50 模板 + ASR 摘要 + 3 帧）
            → 每条推荐发 stage="2.recommend" VisionEvent
     → 返回 {recommendations:[{template_id,score,reason,...}], workbench_url}
浏览器选模板，可选勾选「允许 AI 补画面」(D10 用户主动触发)，点「应用」
  → POST /api/projects/{pid}/apply {template_id, allow_aigc_broll}
     → tasks_store.create_task("apply_short", resource_kind="project")
     → BackgroundTask: apply.pipeline.apply_short(pid, tid, task_id, allow_aigc_broll)
        → kb_store.get_template → TemplateIR
        → _safe("probe_duration") → ffprobe duration
        → _safe("asr") → 优先读 projects/{pid}/transcript.json 复用推荐阶段的 ledger（命中则发 stage="2.pipeline.asr_reuse" 事件并跳过 transcribe），未命中则 understand.asr.transcribe → TranscriptLedger
        → _safe("mapping") → apply.mapping.map_short_to_template
                              (Unit → voice slot 顺序绑定 + ±20% speed 钳制)
        → _safe("gaps") → apply.gaps.detect_gaps
                          (按 material_req 分类 aigc_broll / text_fill / wrap_fill / reuse；
                           AI生成画面 slot → aigc_broll 策略，gaps.py 只标 intent，
                           是否真调 provider 由 fill.py 看 allow_aigc_broll 决定)
        → _safe("fill") → apply.fill.fill_gaps(project_id, allow_aigc_broll)
                          (text_fill: text LLM 受 placeholder/length_constraint/semantic_purpose 锚定；
                           aigc_broll + 勾选: chat_text 用 5_aigc_broll.md 把 ASR ±2 Unit + tags
                           合成英文 image prompt → agent.aigc.generate_broll(hash 缓存 + PPIO
                           OpenAI-compat /v1/images/generations 文本生图 → render.ffmpeg.image_to_video
                           把静图循环成 duration 秒 mp4 落到 data/aigc/broll/{hash}.mp4) →
                           写 PlacedSegment.aigc_broll_path + use_aigc_broll=True；
                           运动由模板 zoom_keyframes 在渲染时附加，生成 API 只产出静态画面；
                           AIGCProviderError 任一子类 → fallback _reuse_segment_for + 把
                           degraded_msg 装到 FillOutcome 让 pipeline 写 ProjectIR.degraded
                           [sections.0.segments.{i}.aigc_broll]，永不阻塞 pipeline；
                           aigc_broll + 未勾选: 静默走 reuse，不调 LLM 也不调 provider；
                           wrap/reuse 段速度让 output_span = slot.nominal 保持 timeline 连续)
        → _safe("style") → apply.style.apply_style
                          (per-PlacedSegment 深拷贝 slot.style；per-Unit Caption（D11
                           严守 text = Unit.text）；text LLM 选 ≤3 个 emphasis_words
                           且必为 Unit.text 子串；BGM 按 BGM_STRATEGY 选 features /
                           original 两路径)
        → 装配 ProjectIR + degraded 写 projects/{pid}/project.json
        → 发 2.pipeline.done 事件
浏览器看 RemotionPlayer 实时预览（CSS-based — <video src=normalized.mp4>
            + playbackRate 跟随 seg.speed + CSS transform zoom + overlay div
            for captions / stickers / emphasis）
浏览器点「渲染出片」
  → POST /api/projects/{pid}/render → BackgroundTask: render.client.render_project(ir, task_id)
     → renderer.server.POST /render
        → render.ts: preflight 扫所有资源（user_material / bgm_track /
                     sticker.generated_image）；缺则 throw PreflightError
        → inputProps = {projectIR, userMaterialUrl, bgmUrl}
        → selectComposition + renderMedia
        → compositions/Project.tsx:
             <ColorLayer>
               for each PlacedSegment:
                 <Sequence>
                   <ZoomLayer><OffthreadVideo playbackRate=speed/></ZoomLayer>
                   <Mask if mask /><Sticker per applied_style.stickers/>
                 </Sequence>
             </ColorLayer>
             <Caption per captions[]>  (emphasis_words 高亮)
             <Audio src=bgmUrl if bgm_track />
        → 写 projects/{pid}/outputs/render_{ts}.mp4
浏览器 TaskProgress 看到 completed → 渲染 mp4 下载链接
浏览器从 ProjectHistoryStrip 重进 /editor/{pid}（或 URL 直接打开）
  → useEffect [projectId] 并行 Promise.allSettled:
     - getProject(pid) → project.json → applyDone + chosenTemplate（取 sections[0].template_id）
       + aigc_cost_summary（GET /projects/{id} 内反查最新 apply_short 的 events.jsonl，
         聚合 stage="5.aigc.broll" 事件计数 + ProjectIR.degraded 中 *.aigc_broll 键计数；
         无 AIGC 活动返 null）
     - getRecommendations(pid) → tasks_store.list_by_resource("project", pid) 取最新
       kind="recommend_templates" → event_bus.replay 过滤 stage="2.recommend"
       且 ir_value 为字符串 → 按 template_id 反查 kb_store.get_template 拼 name/thumbnail
       → 恢复 step-2 卡片
     - listProjectTasks(pid) → tasks 表取最新 kind="apply_short" → 恢复 step-3
       「apply 全链路 #...」工作台链接
  ← Editor 渲染：step-2 卡片高亮 chosenTemplate；step-3 显示 apply 全链路 #...
     + 成本面板（已调 / 缓存命中 / 失败降级 / 累计秒）；
     PatchHistoryList 顶部「打开工作台看 apply 全链路 →」一并恢复
```

**链路 G：Phase 2.5 NL 编辑 / 参数面板编辑 → ProjectIR Patch → 自动重渲染**
```
浏览器 /editor/{pid}
  → 用户在右下 NLBar 输入 "字幕改黄色描边黑色" 回车
  → POST /api/projects/{pid}/edit body={instruction}
     → tasks_store.create_task("nl_edit", resource_kind="project", resource_id=pid)
        路径方案 B → events_jsonl_path = projects/{pid}/pipeline/events_{task_id}.jsonl
     → load project.json → ProjectIR
     → 拉当前模板 + KB 目录 (kb.store.get_template + list_templates) 喂给 prompt
     → agent.nl_edit.nl_edit(ir, instruction, task_id, current_template, catalog):
        → llm.client.chat_text(2_5_nl_edit prompt + ProjectIR 摘要) → _NLEditResult{patches[], reasoning}
        → 每条 patch 发一条 stage="2.5.nl_edit" VisionEvent (ir_value=patch.model_dump)
        → 未知 op / 空 patches → 发 stage="2.5.nl_edit.unknown_op" 或 .no_patch warning 事件
     → push_snapshot(pid, ir) 写 projects/{pid}/snapshots/v{ir.version}.json
     → apply_patches(ir, patches) → pure-function 走 _OP_HANDLERS 调度 → ProjectIR (version+1)
        PatchApplyError → HTTP 400 + task 标 failed
     → write project.json
     → 发 stage="2.5.nl_edit.apply_done" VisionEvent
     → background_tasks.add_task(render.throttle.trigger_render_supersede, pid, render_task_id, ir):
        → 锁 _locks[pid]
           if _in_flight[pid] 已有 prior_task_id → POST renderer DELETE /render/{prior}
                                                  → tasks_store.update_task(prior, status="superseded")
           _in_flight[pid] = render_task_id
        → 锁外 await render.client.render_project(ir, task_id=render_task_id):
           renderer POST /render：
             RenderState.cancelled? → pre-start skip + 进度报 "cancelled"
             否则正常 render → 完成时 RenderState.cancelled? → 报 "cancelled" 否则 "completed"
        → 锁内 _in_flight[pid] = None
     → HTTP 200 返回 {task_id, patches_applied, ir, render_task_id, workbench_url}
  ← Editor 收到 → 更新 preview-props + editTick++ 让 PatchHistoryList 重读
浏览器 PatchHistoryList 调 GET /api/projects/{pid}/history:
  → agent.nl_edit.list_patch_history(pid):
     → tasks_store.list_by_resource("project", pid) WHERE kind IN nl_edit/panel_edit/undo
     → 每 task event_bus.replay 过滤 stage="2.5.nl_edit" 抽 ir_value 即 Patch
  ← Editor 用户点 "↺ 撤销 (N)"：
  → POST /api/projects/{pid}/undo
     → undo(pid) → 读 latest snapshots/v{N}.json 写回 project.json + 删快照
     → 创建 kind="undo" task → 发 stage="2.5.nl_edit" 撤销事件
     → trigger_render_supersede 与上面同路径触发重渲染
```

**链路 H：Phase 2.5 工作台事件回放器 → Visualize 页录屏导出**
```
浏览器 /projects/{pid}/replay 或 /samples/{sid}/replay
  → GET /api/projects/{pid}/replay/events?task_id=<可选>
     → _resolve_task("project", pid, task_id?) 默认取该资源最新 task
     → event_bus.replay(target_task) 读 jsonl 全量事件
  ← 返回 {task_id, task: {...}, events: [...]}
  Visualize.useEffect → reset(task_id) → cursor=0
浏览器点 "▶ 播放" → 每 ~600/speed ms 取 events[cursor]
  → useWorkbenchStore.appendEvent → 与实时 Workbench 走完全相同的 IR 写入逻辑
浏览器拖拽 timeline → scrubTo(newCursor):
  → reset(task_id) + 重放 events[0..newCursor]
浏览器点 "● 导出录屏":
  → navigator.mediaDevices.getDisplayMedia 让用户选 tab
  → MediaRecorder(stream, "video/webm;codecs=vp9").start
  → 60s 后自动 stop → URL.createObjectURL(blob) + a.download="workbench_replay_{ts}.webm"
  Safari 不支持 webm → 主动 alert 提示用户改用 Chrome/Edge/Firefox
  → snapshot 预览：POST /api/projects/{pid}/replay/snapshot {task_id, sequence}
     → _snapshot_payload 复用 _lodash_set 重放 events[0..sequence] 的 ir_target → 返回 snapshot dict
浏览器 ExtractHistoryList / WorkbenchBreadcrumb 同源：
  → GET /api/samples/{sid}/tasks 或 /api/projects/{pid}/tasks
     → tasks_store.list_by_resource("sample"|"project", id)（按 idx_tasks_resource 索引 + created_at DESC）
  ← 列表点 task → navigate("/workbench/" + tid)
浏览器进入 /workbench/{tid} → 顶栏 WorkbenchBreadcrumb:
  → pollTask(tid) → resource_kind + resource_id
  → 渲染「样例|项目 > {name} > {kind 中文} #{tid 前 8}」
  → resource 拉失败 → fallback "任务 #{tid 前 8}"
```

---

## 6. 关键约定

- **D1 IR 是地基**：所有跨进程契约用 pydantic 模型 → JSON Schema → zod 表达；改 IR 必跑 `pnpm gen:types`，CI 的 `type-sync` job 强制三方一致。
- **D2 路径都相对 DATA_ROOT**：API 返回 / IR 内引用 / 渲染输出全部使用 POSIX 风格相对路径（`projects/p001/normalized.mp4`），由后端 / renderer 的 `paths` 模块统一解析为绝对。
- **D3 IR 文本永不被改写**：所有 LLM/VLM 决策返回对 id 的指令，绝不重写 `Unit.text`（阶段 0 暂未引入 LLM，约定提前生效以约束后续）。
- **D4 渲染元数据由 IR 推导**：Remotion `<Composition>` 的 `calculateMetadata` 从 `projectIR.canvas` + `sections[].segments[].timeline_start/src_timerange` 算出 width/height/fps/durationInFrames，调用方不在 selectComposition 之后覆盖元数据。
- **D5 任务进度统一上报**：renderer `onProgress` → `POST /api/internal/task-progress` → SQLite `tasks` 表；前端 1s 轮询 `GET /api/tasks/{id}`。错误同样落任务表（`status=failed, error=...`），前端统一处理。
- **D6 媒体归一化用标准 ffmpeg 惯用法**：`scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2:color=black,fps=F`；不使用 ffmpeg 表达式语法以避免跨平台单引号转义问题。
- **D7 渲染队列单 worker**：renderer 端 `p-queue({concurrency:1})` 串行，避免多 Chromium 实例资源竞争；多 worker 推后到 Phase 3+。
- **D8 渲染端用户素材走 HTTP**：renderer 把 IR 里的 `user_material` 相对路径拼成 `{BACKEND_URL}/data/<rel>` 后传入 Remotion `<OffthreadVideo>`，不使用 `file://`。`BACKEND_URL` 由 env 注入，本地默认 `http://localhost:18521`。
- **D9 AI 调用必发 VisionEvent**：所有 AI 客户端方法（`llm.client.chat_vision` / `chat_text` 等）返回 `tuple[BaseModel, list[VisionEvent]]`；事件由客户端层 `event_bus.publish` 广播。`silent=True` 跳过广播但仍 log。`ir_value` 是 Any 类型，与前端 lodash.set 写入路径（含 ir_target.field）的语义对齐。
- **D10 事件持久化按资源 kind 路由**：`event_bus.publish` 按 `tasks.resource_kind + resource_id` 落 jsonl 文件——sample → `samples/{sid}/extracted/events_{task_id}.jsonl`，project → `projects/{pid}/pipeline/events_{task_id}.jsonl`，未知或 template 在 KB 接入前回退到 `system/dev_events/`。jsonl 同时是 EventBus 的 sequence high-water mark 真理源。
- **D11 SSE 流通过 snapshot 切分**：浏览器 `EventSource` 自动维护 `Last-Event-ID`；后端 `/api/tasks/{id}/events` 在 `event_bus` 的 task lock 内原子拿 (queue, snapshot)，调 `replay(from_event_id=..., until_seq=snapshot)` 推历史，再从队列推 live 事件（sequence > snapshot）。两段集合不重叠，无须客户端 dedup。每条 SSE 三行格式（`id` / `event` / `data`），`id` 字段不可省略。
- **D12 任务表含资源回链**：`tasks` 表自 Phase 0.5 起新增 `resource_kind` / `resource_id` / `events_jsonl_path` 三列；老库通过 `init_db` 内置 idempotent ALTER 自动迁移。`last_event_sequence` 列在 0.5 二核审计后被移除（jsonl 已是真理源），老库残留该列不影响读写。
- **D13 LLM 客户端真实双适配器**：`OpenAICompatClient` 走 `/v1/chat/completions`，`AnthropicClient` 走 `/v1/messages`，共享 `_RealClientBase` 的重试 + 缺凭据 / 4xx / 重试耗尽时回退 stub + `severity="warning"` 事件。重试只在 5xx / 超时 / 连接错误 / JSON 解析失败时发生；4xx 立即回退。
- **D14 dual-check 并发 + 跳过 fallback**：`chat_vision_dual` 通过 `asyncio.gather` 并发调主备模型；任一侧返回 `severity=warning` 事件（fallback）时跳过结构对比，避免「真结果 vs 默认 schema」误报为 cross-check 异议。
- **D15 子能力统一上下文签名 + STAGE 常量**：`extract/*` 与 `understand/*` 子能力函数签名为 `async def detect_X(ctx: Phase1AContext, *, parent_event_id=None) -> tuple[Result, list[VisionEvent]]`；`captions_anim` / `caption_function` 多一个 `caption_idx` 形参、`stickers.refine_sticker_bbox` 多一个 `sticker_idx` 形参索引到 `Phase1AReport`。stage 在模块顶部硬编码常量。重 ML 依赖在 `[extract]` extras 内 lazy import，缺包返默认形状 + `severity="warning"` VisionEvent。
- **D16 Phase 1A CI 守卫**：`scripts/check_stage_naming.py` AST 检查 VisionEvent / chat_vision / chat_text / chat_vision_dual / `STAGE` 常量字面量；`check_event_emission.py` 检查 AI 客户端方法体调用 `event_bus.publish` 或 chat_vision 系列；`check_parent_event_id.py` 检查名字以 `_refine` / `_phase2` / `_classify` 结尾或以 `refine_` / `phase2_` / `classify_` 开头的函数体内任一调用传 `parent_event_id=` kwarg。三脚本跳 site-packages，CI python job 在单测后串行执行。
- **D17 Phase 1A 识别报告 IR**：1A 子能力 VisionEvent 写入 `Phase1AReport`（`backend/app/ir/phase1a_report.py`），不写 `TemplateIR`。`IRTarget.ir_type` Literal 取 `{TemplateIR, ProjectIR, TranscriptLedger, Phase1AReport}` 之一。Phase1AReport 字段 = `scenes[]` / `captions[]` / `caption_style_palette[]` / `caption_functions[]` / `stickers[]` / `zoom_directions{}` / `zoom_curves{}` / `transitions{}` / `masks{}` / `color` / `audio` / `b_roll_segments[]`。列表型字段以 `op="append"` 增量写入；字典型字段以 `str(scene_idx)` 作 key、路径形如 `zoom_directions.0`；单值型字段整对象写或带 `field` 子字段写。1B `skeleton.py` 读 `Phase1AReport` 映射到 `TemplateIR.skeleton[N].style.{...}` + `TemplateIR.caption_style_palette[]`，并据 `b_roll_segments` 把含非「人物主导」段的 Slot.material_req 标为 `AI生成画面`。工作台右栏头部按最近事件 `ir_target.ir_type` 动态显示 IR 类型。
- **D18 Phase 1A 共享上下文**：`backend/app/extract/context.py` 暴露 `Phase1AContext(sample_id, normalized_path, task_id)`，`await ctx.scenes()` / `await ctx.frames()` / `ctx.client(stage)` 三个 lazy 入口在首次调用时计算并缓存。lab runner、1B pipeline、集成测试都以 `ctx` 为入参；多子能力同 fixture 时 `detect_scenes` / `sample_frames` 只执行一次。
- **D19 Phase 1A 实体事件可视化字段**：每个子能力的实体级 VisionEvent（每条字幕、每枚贴纸、每个 mask 检出）必须填 `frame_url`（指向 entity 首次出现的采样帧 `/data/<rel>`）+ `bbox_norm`（0-999 → 0-1 归一化），工作台左栏 `WorkbenchVisionPane` + `BboxOverlay` 在两个字段同时存在时才渲染帧底图 + 框。`Phase1ACaptionEvent` / `Phase1AStickerDetection` 同时携带 `reasoning` 字段，右栏 IR 展开可见 VLM 中文解释（decisions/010 落地后 raw 审计字段如 `color_hex_raw / anim_in_type_raw / layout_raw` 已删除——视觉信息直接收口在 `style: CaptionStyle`，行为信息收口在 `Phase1ACaptionFunctionEvent`）。
- **D20 几何 mask CV 主路径**：`extract/masks.py::detect_masks` 在每个 scene 首/中/末三帧只跑 `HoughCircles` 圆形检测器，多数决（同 kind 至少 ceil(n_frames/2) 票）确认 `has_mask`；CV 全 false 时调一次 VLM 看三帧网格，由 VLM 判断矩形 / 分屏等其他形状（VLM prompt 显式排除字幕 / 标题条 / 水印 / UI / letterbox 等非蒙版元素）。决策详见 decisions/010 决策 4：原 `Canny 矩形` / `HoughLinesP` 两类 CV 检测器在口播视频里几乎全是字幕带 / 标题条边缘的误报，已删除。CV 候选与最终判定事件都带 frame_url + bbox。
- **D21 1B pipeline 单点降级**：`extract/pipeline.py::_safe(label, field_key, coro)` 包裹每个子能力调用；任一抛异常 → `TemplateIR.degraded[_ir_path_for(field_key)] = str(e)` + 发 `severity="warning"` 事件 + 不阻塞下游。pipeline 自身永不 raise（顶层 `try/except` 仅防御非 `_safe` 路径的 programmer error）；最坏情况是一个 degraded 字段全标的 TemplateIR 仍可入 KB。`_ir_path_for` 翻译规则见 D25。
- **D22 模板 = KB 主键 + events 路径回链**：`kb.sqlite` 的 `templates` 表只存 `ir_json + tags + thumbnail + last_extract_task_id`，**绝不复制 events.jsonl**。事件流通过 `tasks.events_jsonl_path`（按 `last_extract_task_id` 反查）就地读取，工作台「回放」一键打开 `/workbench/{last_extract_task_id}`。
- **D23 Renderer Caption 双模式 + 单 prop 契约**：`compositions/Caption.tsx` 由调用方传 `renderMode: "template_preview" | "project_output"` props 区分；前者渲染 `style.placeholder_text[0]` 作为示例字幕（TemplateLibrary 详情 / 0.5 dev_workbench 预览），后者渲染 ProjectIR 的 `Caption.text`（Phase 2+ 用户素材产物）。组件内**绝不**根据 `text` 是否为空自动切换模式——隐式 fallback 在用户合法传空字符串时会无声跑错。组件接收 `{text, startSec, endSec, style: CaptionStyleShape, renderMode}` 五个 prop（decisions/010 P5）；CaptionStyleShape 镜像 `backend/app/ir/template.py::CaptionStyle`，IR 加视觉字段渲染端零改动。`bbox_norm` 非 0 时优先于 `position` 中心点作锚点，前端 RemotionPlayer CSS 预览同步该 fallback 顺序；frontend 与 renderer 共用一份 placement / shadow / padding 约定但不共用代码（PLAN L1644-1647 RemotionPlayer 注释说明为何不打包 Remotion 到 frontend）。
- **D24 全局信号挂 TemplateIR 顶层，per-slot 信号挂 StyleRule**：`audio` / `tags` / `sanity_check` / `degraded` / `caption_style_palette` 这类整模板共享的字段直接挂在 TemplateIR；`StyleRule` 只放真正按 slot 变化的事物（caption_palette_idx / visual.zoom_keyframes / mask / color_lut / stickers / transition_in/out）。decisions/010 落地后 caption 视觉样式由模板级 `caption_style_palette` 集中存放，Slot.style 通过 `caption_palette_idx: int | None` 引用——多个 Slot 共享同一种字幕样式时无须值拷贝。1A 的 `extract_bgm` 单全局 `AudioStyle` 直接装配到 `TemplateIR.audio`，不再被 skeleton.py 复制到每个 slot。Phase 2+ 若出现 per-slot BGM 切换需求，再单独引入 `StyleRule.audio_override: AudioStyle | None`，不复用此前的 per-slot 默认字段。
- **D25 degraded 路径统一翻译**：`TemplateIR.degraded` 的键一律是 TemplateIR 相对路径。`pipeline.py` 顶部的 `SUBCAP_TO_IR_PATH` 表是单一真理源——subcap 自带的 field_key（含 Phase1AReport 路径，如 `zoom_curves.3` / `captions.5.function`）在写入 `ir.degraded` 前由 `_ir_path_for(field_key)` 翻译为 TemplateIR 路径（如 `skeleton.*.style.visual.zoom_keyframes` / `caption_style_palette` / `caption_functions`）。`*` 是 slot glob，UI banner 据此展示 + 跳转，不需要再认识 Phase1AReport 字段名。
- **D26 SQLite 表初始化只在 lifespan**：`tasks_store.init_db` / `kb_store.init_db` 只由 `main.py` 的 lifespan 调用一次，CRUD 入口绝不 per-call init；测试用 `tests/conftest.py::task_with_events` fixture 镜像 lifespan，把两个 init 都跑一遍。两个 store 共用 `data/kb.sqlite` 的 WAL 连接，schema 全 `CREATE IF NOT EXISTS` 幂等，重复 init 不报错也不损失数据但会让单元 CRUD 跑出无谓的 DDL。
- **D27 task 端点对外暴露 normalized 媒体 URL**：`GET /api/tasks/{id}` 按 `_RESOURCE_DIRS = {sample → samples, project → projects}` 把 `resource_kind/resource_id` 翻译为 `/data/{subdir}/{rid}/normalized.mp4` 字符串，文件不存在或资源 kind 未登记则返 `null`。前端 Workbench 据此挂载 `<video controls>` 实现「帧 / 原视频」切换；不新增独立媒体端点，复用已有 `/data/*` 静态路由。新增资源 kind 仅改这张表。
- **D28 apply 流水线沿用 _safe 降级范式**：`backend/app/apply/pipeline.py::_safe(label, ir_path, coro)` 与 `extract/pipeline.py::_safe` 同构——每个 stage 抛异常 → 写 `ProjectIR.degraded[<ir_path>]` + 发 `severity="warning"` 事件 + 不阻塞下游。pipeline 顶层不 raise（除 `kb_store.get_template` 找不到模板这种程序错误外），最坏情况是 ProjectIR 多字段 degraded 仍可入磁盘。`STAGE_TO_IR_PATH` 是 ProjectIR.degraded 键的单一真理源（与 TemplateIR 的 `SUBCAP_TO_IR_PATH` 对称），翻译规则按 stage 首段查表 + 子路径折叠，UI banner 据此跳转。
- **D29 D11 字幕硬约束扩展到 emphasis_words**：Caption.text 永远等于 Unit.text（D11 原约束）；Phase 2 `apply/style.py` 调 LLM 选 `emphasis_words` 时，prompt 显式要求 ≤3 个、必为 unit_text 的连续子串；调用方 `_emphasis_for_unit` 用 `[w for w in result.emphasis_words if w and w in unit.text]` 兜底过滤 LLM 越界产物。用户 Unit text 长于 `length_constraint.max_chars` 时不截断（违反 D11），改走 `layout="multi" + max_chars_per_line` 自然换行；超长情况 log warning。
- **D30 RemotionPlayer 选 CSS-based 预览不打包 Remotion bundle 到 frontend**：`frontend/src/components/RemotionPlayer.tsx` 用 HTML `<video>` + `playbackRate` 跟随 segment.speed + CSS `transform: scale()` 跑 zoom_keyframes + overlay div 跑 caption / sticker / emphasis 高亮，共享 `/api/projects/{id}/preview-props` 的精简 props shape。理由：把 `renderer/src/compositions/*` 重新打包进 `frontend/` 会形成"compositions 双份源"——任何对 Project.tsx / Caption.tsx 的改动都要同步两份，第一性原理上违反单一真理源（D1 IR）。CSS-based 预览的视觉精度对 caption timing / zoom 曲线 / sticker 位置完全足够；最终 MP4 仍由 renderer 用真实 Remotion 渲染，二者在 IR 层对齐。
- **D31 PlacedSegment 的 output_span 是推算量、不是字段**：`output_span = (src_end - src_start) / speed` 作为唯一表达式由 `apply.style._segment_output_span(seg)` 暴露；mapping 累积 timeline_cursor、fill 重建 timeline、style 重映射 sticker、renderer (`projectMeta.ts` / `Project.tsx` / `RemotionPlayer.tsx`) 计算 durationInFrames 全部经它读，禁止任何使用方对结果做 min/max banding 后再写回 cursor。当 mapping 的速度钳到 ±20% 后 output 仍超 `slot.duration.max`，**截短** `src_end = src_start + slot.max × speed`（PLAN 1599 "裁切尾部"），而不是把 banded 值写到 IR——后者会让 IR 与渲染端口径不一致。
- **D32 sticker 时间在 IR 层间换坐标系**：Phase1AReport.stickers[i].sticker.start/end = 样例视频绝对秒；TemplateIR.skeleton[N].style.stickers[i].start/end = **slot-local 归一化 [0,1]**（由 `extract/skeleton.py:_stickers_in` 写入）；ProjectIR.sections[\*].segments[\*].applied_style.stickers[i].start/end = **segment-local 秒**（由 `apply/style.style_for_segment(slot, output_span)` 在装配 PlacedSegment.applied_style 时把 [0,1] × output_span 算出）。renderer 与 frontend 的 RemotionPlayer 一律按"segment-local 秒"读，自己再投影到 timeline-global 秒做命中检测。
- **D33 apply 流水线含 bgm_mix stage**：style 选完 `bgm_track` 后 `apply/pipeline.py` 自动跑 stage `bgm_mix`（`_safe` 包裹）—— `ffmpeg.extract_audio` 取出用户素材的人声 → `ffmpeg.mix_bgm`（sidechaincompress + voice 触发的 ducking）→ 写 `projects/{id}/bgm_ducked.aac` → `ProjectIR.bgm_track` 更新为这条 ducked 路径。renderer 的 `<Audio src={bgmUrl}/>` 直接播 ducked 文件，与 user material 视频本身的人声轨叠加；不再有"渲染端听到原始 BGM 盖人声"。失败降级为保留原 bgm_track + warning 事件。
- **D34 normalize 有两套 letterbox**：`render/ffmpeg.py:normalize(pad_mode="black"|"blur")`。`black` 用于 sample 上传（PLAN 1A 识别期不能用模糊背景污染原视频）；`blur` 用于 Phase 2 用户素材上传（`api/projects.py:upload_project`），符合 PLAN 1657 "letterbox 居中、背景模糊"——`split=2[bg][fg]; [bg]scale=increase,crop,boxblur=20; [fg]scale=decrease; [bg][fg]overlay`。两路径共享 `force_original_aspect_ratio=decrease` 的几何不变量，避免拉伸。
- **D35 Phase 2.5 编辑链路统一走 Patch + Snapshot 栈**：`agent/nl_edit.py` 暴露 `nl_edit / panel_to_patches / apply_patches / push_snapshot / undo / list_patch_history` 六个函数；NL 与参数面板编辑都经 `Patch` op 枚举（`set_caption_style` / `set_visual_style` / `adjust_rhythm` / `set_emphasis` / `swap_template` / `delete_segment` / `set_canvas` / `set_bgm`）翻译。`apply_patches` 是 pure-function 调度器：`ProjectIR × list[Patch] → ProjectIR`，end 处 `model_validate` 兜底；**不写盘**。落盘由 `api/edit.py` 在 push_snapshot 之后做。Undo 用快照栈而非 per-op inverse——`push_snapshot` 把 apply 前的 `project.json` 拷贝到 `projects/{id}/snapshots/v{ir.version}.json`，`undo()` 弹栈写回 + 删快照。新增 PatchOp 不需要触动 undo（与 ISS-015 决策 008 对应）。
- **D36 Patch 真理源 = events.jsonl**：Phase 2.5 NL / panel 编辑每生成一条 Patch 都发一条 `stage="2.5.nl_edit"` VisionEvent，`ir_value` 字段挂 Patch 的 `model_dump`；`GET /projects/{id}/history` 查 `tasks WHERE kind IN ('nl_edit','panel_edit','undo') AND resource_id={id}` 再聚合各 task events.jsonl 中 `stage="2.5.nl_edit"` 的事件即可还原 Patch 流。**绝不引入 `patch_history.jsonl`**——避免和 events.jsonl 两份真理源同步成本（与 ISS-015 决策 008 对应）。工作台事件否决（`POST /workbench/{tid}/reject-event/{eid}`）发 `stage="2.5.veto"` 事件而非 Patch（不修改原 events.jsonl 数据）。
- **D37 项目级渲染节流走 supersede dict**：Phase 2.5 NL/panel 编辑频繁触发重渲染，`backend/app/render/throttle.py::trigger_render_supersede(project_id, task_id, ir)` 用 `defaultdict(asyncio.Lock)` + `dict[project_id → in_flight_task_id]` 串行化"取出旧 + 设置新"；旧任务存在时调 `cancel_render` → renderer `DELETE /render/{tid}`（renderer 端 `queue.ts` 的 RenderState 注册表：pending 任务的 wrapper 顶部 `state.cancelled` 检查直接 skip，running 任务的 onProgress 在完成时报 `cancelled`）。**不引入独立 `agent/render_queue.py` 模块**——~30 行 dict + lock 已满足 supersede 需求；当未来真的需要队列优先级 / 多 worker / 跨项目限速时再单独抽（与 ISS-015 决策 008 对应）。
- **D38 VisionEvent 双时间轴**：Phase 2.6 在 `VisionEvent` 加 `media_ts: float | None` 与 `media_ts_range: tuple[float, float] | None`。`frame_ts` / wall-clock 表达"AI 何时跑"（甘特图横轴），`media_ts*` 表达"事件指向视频的哪一刻"（媒体时间线横轴）。两轴互补不重叠。`llm.client._build_event` 自动按 frames 数填（0 → 双 None；1 → media_ts；>1 → range = (min, max)）；实体事件 / 跨段事件由发射方显式填值（如 caption entity → media_ts = anchor.ts；scene cut → media_ts_range = (start_sec, end_sec)）；system / progress 事件两者皆 null。CI `scripts/check_media_ts.py` AST 守住"`VisionEvent(frame_url=...)` 必带 `media_ts=` 或 `media_ts_range=`"。
- **D39 ir_value 始终落地 + ReplayClient 验证型过滤**：`llm.client._build_event` 即使 `ir_target_template=None` 也写 `ir_value = parsed.model_dump(mode="json")`——`ir_value` 语义放宽为"AI 产生的结构化输出"，IR 写入仍由 `ir_target` 是否为空驱动。这让 `app.llm.replay_client.ReplayClient` 不依赖额外字段就能从历史 events.jsonl 还原任意 chat_vision 调用。ReplayClient 用 `dict[stage, deque[VisionEvent]]` 索引；调用 `chat_vision(schema=T)` 时 popleft 队首并 `T.model_validate(ev.ir_value)`，验证失败的事件直接丢弃（同 stage 但不同 schema 的实体事件，如 captions 子能力自行 publish 的 entity event），验证成功的事件作为返回；`ir_value=None + severity="warning"` 特殊处理为 `_construct_default(schema)`，与真实客户端 fallback 路径一致。**不新增 `emitter` 字段**（与 ISS-017 决策 009 对应）。
- **D40 工作台双时间轴聚合落客户端**：甘特图 + 媒体时间线共享同一份 events.jsonl，聚合在 `frontend/src/lib/aggregateEvents.ts` 的 `buildGantt(events)` / `buildMediaTimeline(events)` 两个纯函数完成；`React.useMemo` 在 workbench store 的 `events` 变化时增量重算。**不引入后端 `/api/tasks/{tid}/gantt` 或 `/media-timeline` 端点**——SSE 已经把每条事件推到 store（同时承载 IR 快照写入），后端再投影一次会让"live 期间每条新事件触发一次 fetch + 服务端聚合"，长视频 Phase 3 的 500+ 事件即 500 次重复 HTTP 往返。两个聚合视图共享 stage 颜色：复用 `EventBadge.badgeColor(stage)` 的 phase-prefix → `var(--stage-*)` 映射（tokens.css 单一真理源）。甘特图横条时间口径硬约束 `start_ms = (timestamp_epoch - duration_ms) - origin` / `end_ms = timestamp_epoch - origin` / `origin = min(timestamp - duration_ms)`——`event.timestamp` 是 chat_vision 调用返回那一刻（`_build_event` 在结果到手后才构造事件），所以 `timestamp - duration_ms` 才是调用真实开始时间，与 perf_counter 计时口径一致。媒体时间线视频 URL 仍走 `task.normalized_media_url`（D27），视频时长由前端 `<video>` 的 `loadedmetadata` 事件读取（与 D40 决策 4 对应）。
- **D41 工作台三视图切换 URL 真理源**：`/workbench/:tid` 由 `?view=` query param 驱动 list / gantt / media_timeline 三种全宽布局；`useViewParam` 实现 URL ↔ store.view 双向同步（URL 是真理源，浏览器后退 / 分享链接均尊重 `?view=`）。`reset(taskId)` 切任务时不重置 `view`——保留用户当前布局选择。`selectedEventId` / `hoveredChainRoot` / events 数据三视图共享一份 store，切换不重 fetch。
- **D42 因果链中栏走 inline pill + 跨视图 hover sync**：中栏事件流卡片底部用 `ChainAnchorPill`（"↳ parent" / "↱ children"，最多 5 条 children）替代旧 parentLabel 字符串。点击 anchor 直接 `setSelected(targetId)`；hover anchor 设 `hoveredChainRoot`，`useChainHighlight()` 计算其祖先 + 后代闭包 set，三视图（中栏 / 甘特图 / 媒体时间线）同步加 accent border 高亮。**坐标映射型视图（甘特图 + 媒体时间线）继续画 SVG `<path>` dashed 贝塞尔**——它们各自的 SVG 容器内就能完成，不需要额外的 overlay 层。中栏纵向滚动列表上不画 SVG `<path>`：跨卡片虚线视觉噪音 > 信号（与 ISS-017 决策 009 对应）。`EventRow` 容器从 `<button>` 改为 `<div role="button">` 以承载嵌套的 anchor `<button>`。工作台 store 维护 `eventsById: Map<event_id, VisionEvent>` 与 `childIndex: Map<parentId, eventId[]>` 两张派生索引（都从 events 数组在 `appendEvent` 时增量更新），所有"按 id 查事件"的消费方（chain 锚点解析 / chain 高亮闭包 / 视觉栏选中事件 lookup）都走 O(1) Map.get；不重复在组件内 `events.find` 或临时构造 byId Map。
