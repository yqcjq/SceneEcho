# 目录结构

> 约定：每新增或删除文件/目录后更新本文件。每个文件/目录一句话说明职责，不写模块间关系（关系在 `001ARCHITECTURE.md`）。

```
SceneEcho/
├─ PLAN.md                                  # 当前执行路径（阶段 0..7）
├─ README-PLAN.md                           # Plan 文档写作规范
├─ README.md                                # 项目顶层简介（占位）
├─ taskRequirements.md                      # 任务原始需求
├─ package.json                             # 根 workspace 脚本：dev / gen:types / build / lint
├─ pnpm-workspace.yaml                      # 工作区声明，包含 renderer + frontend
├─ .env.example                             # 环境变量样板，复制为 .env 使用
├─ .gitignore                               # 含 backend venv / data / 生成产物的忽略规则
│
├─ .github/
│  └─ workflows/
│     └─ ci.yml                             # CI：type-sync / python / renderer / frontend 四 job
│
├─ docs/
│  ├─ 000README.md                          # 文档体系规范（必须先读）
│  ├─ 001ARCHITECTURE.md                    # 系统拓扑、分层、调用约束、运行时链路
│  ├─ 002STRUCTURE.md                       # 本文件：目录与文件职责
│  ├─ 003ISSUES.md                          # 问题追踪
│  ├─ 004CHANGELOG.md                       # 改动记录（commit 级）
│  ├─ 005DEVELOPMENT.md                     # 首次构建与运行指引
│  ├─ decisions/                            # 拍板决策的 ADR
│  └─ future-plans/                         # 远期演进规划
│
├─ shared/
│  └─ ir.schema.json                        # 生成产物：pydantic IR 导出的 JSON Schema（gitignored）
│
├─ scripts/
│  ├─ gen_schema.py                         # Pydantic → shared/ir.schema.json 的薄入口
│  ├─ check_stage_naming.py                 # CI 守卫：VisionEvent 的 stage 字面量必匹配 PLAN.md 命名表
│  ├─ check_event_emission.py               # CI 守卫（D13）：标记的 AI 客户端方法必发 event_bus.publish
│  └─ check_parent_event_id.py              # CI 守卫：*_refine / *_phase2 / *_classify 函数必传 parent_event_id=
│
├─ tests/
│  └─ fixtures/                             # 用户手动放置的测试视频（不入 backend/data）
│     ├─ sample_basic_15s/source.mp4        # 5-20s 样例素材（Phase 0/1 测）
│     └─ short_15s/source.mp4               # 10-20s 短口播（Phase 0/2 测）
│
├─ backend/                                  # Python FastAPI 服务
│  ├─ pyproject.toml                        # 依赖与打包配置（pip install -e ".[dev]"）
│  ├─ ruff.toml                             # lint + format 规则
│  ├─ .venv/                                # 本地虚拟环境（gitignored）
│  ├─ data/                                  # DATA_ROOT 默认根（gitignored）
│  │  ├─ samples/{id}/                      # 样例：source/normalized/thumbnail/extracted
│  │  │  └─ extracted/events_{task_id}.jsonl  # AI 决策事件流（路径方案 B）
│  │  ├─ projects/{id}/                     # 项目：user_material/normalized/project.json/outputs
│  │  │  ├─ pipeline/events_{task_id}.jsonl   # 项目应用 / 编辑事件流
│  │  │  └─ snapshots/v{N}.json              # Phase 2.5 编辑前 ProjectIR 快照栈（D35 undo 用）
│  │  ├─ system/                            # 字体 / BGM 池 / 模型缓存 / 贴纸参考
│  │  │  └─ dev_events/                     # 开发态事件流兜底（template/未知 kind）
│  │  ├─ aigc/                              # AIGC 缓存（贴纸 / B-roll）
│  │  ├─ kb.sqlite                          # tasks 表（含 resource_kind/id + events_jsonl_path）+ 后续 KB 表
│  │  └─ logs/                              # JSON 结构化日志按天落盘
│  ├─ app/
│  │  ├─ __init__.py
│  │  ├─ main.py                            # FastAPI 入口：CORS + lifespan + 路由挂载 + /data 静态 + 工作台路由（dev gated）
│  │  ├─ config.py                          # pydantic-settings 读 .env，含 model_provider / dual_check_stages / enable_dev_mock
│  │  ├─ logging.py                         # structlog JSON 配置 + task_id contextvar 绑定
│  │  ├─ cli.py                             # typer：ingest-sample / ingest-project（dev 闸门）
│  │  ├─ tasks_store.py                     # SQLite tasks 表 CRUD（WAL）+ Phase 0.5 idempotent ALTER + Phase 2.5 list_by_resource + idx_tasks_resource 索引
│  │  ├─ event_bus.py                       # 进程内事件总线：subscribe_with_snapshot / await put 反压 / jsonl 持久化 / jsonl tail seq 真理源 / lookup callback 注入
│  │  ├─ api/
│  │  │  ├─ __init__.py
│  │  │  ├─ samples.py                      # POST /samples 上传归一化；POST /samples/{id}/render-demo；POST /samples/{id}/extract (1B)；GET /samples/{id}/tasks (2.5)
│  │  │  ├─ projects.py                     # POST /projects 上传；/recommend-templates / /apply / GET /projects/{id} / /preview-props / /render / /mix-bgm (Phase 2) / GET /projects/{id}/tasks + /lineage (2.5)
│  │  │  ├─ tasks.py                        # GET /tasks/{id}（含 normalized_media_url · D27）；POST /internal/task-progress
│  │  │  ├─ events.py                       # GET /tasks/{id}/events SSE + /events/history
│  │  │  ├─ templates.py                    # 1B KB CRUD: GET/PATCH/DELETE /templates(/{id}) + /events 回放
│  │  │  ├─ edit.py                         # Phase 2.5 编辑 HTTP 入口: POST /edit / /panel-edit / /undo + GET /history（events.jsonl 作 Patch 真理源 · D36）
│  │  │  ├─ replay.py                       # Phase 2.5 回放: GET /projects/{id}/replay/events + /tasks; POST /replay/snapshot + /workbench/{tid}/reject-event/{eid} 否决；对称 /samples/* (D35-37)
│  │  │  ├─ dev_workbench.py                # ENABLE_DEV_MOCK gated：mock-stream / scenarios 列表
│  │  │  └─ lab.py                          # ENABLE_DEV_MOCK gated：SubcapabilityLab 子能力 registry / run / baselines
│  │  ├─ ir/
│  │  │  ├─ __init__.py                     # 顶层 IR 类型聚合 export
│  │  │  ├─ ledger.py                       # TranscriptLedger / Unit
│  │  │  ├─ template.py                     # TemplateIR（含顶层 audio · D24）+ Slot/StyleRule/CaptionStyle/...
│  │  │  ├─ project.py                      # ProjectIR + Section/PlacedSegment/Caption/Gap
│  │  │  ├─ phase1a_report.py               # Phase1AReport：1A 识别结果聚合 IR（D17，子能力 VisionEvent 写入这棵树）
│  │  │  ├─ patch.py                        # NL/面板/审核统一编辑 op
│  │  │  ├─ vision_event.py                 # VisionEvent / IRTarget（AI 决策事件 IR · D9/D10；ir_type 含 Phase1AReport；ir_value: Any）
│  │  │  ├─ path_validator.py               # lodash 风路径校验器（CI 验证 mock JSON 命中真实 IR）
│  │  │  └─ export.py                       # pydantic → JSON Schema 聚合导出
│  │  ├─ llm/
│  │  │  ├─ __init__.py
│  │  │  ├─ client.py                       # 真实双适配器：OpenAI-compat + Anthropic native + retry + dual-check + parent_event_id + 缺凭据 fallback
│  │  │  └─ prompts/
│  │  │     ├─ __init__.py                  # load_prompt / render_prompt（lru_cache）
│  │  │     ├─ 1a_captions.md               # Phase 1A 字幕样式 + 位置 + placeholder 三件套 prompt
│  │  │     ├─ 1a_stickers.md               # Phase 1A 贴纸网格抽帧 + semantic_category prompt
│  │  │     ├─ 1a_zoom_direction.md         # Phase 1A 缩放方向粗判 prompt（首/中/末三帧）
│  │  │     ├─ 1a_transitions.md            # Phase 1A 转场分类（硬切/叠化/滑入/推拉）prompt
│  │  │     ├─ 1a_masks.md                  # Phase 1A 几何蒙版有无 + 参数 prompt
│  │  │     ├─ 1a_color_lut.md              # Phase 1A 调色语义标签 + dominant_lut_id prompt
│  │  │     ├─ 1a_caption_function.md       # Phase 1A 字幕功能分类 prompt（标题/强调/卖点/CTA/regular/过渡）
│  │  │     ├─ 2_recommend.md               # Phase 2 模板智能推荐 prompt（top-k VLM 排序 + 中文 reason）
│  │  │     ├─ 2_caption_emphasis.md        # Phase 2 字幕 emphasis_words 选取（必为 unit_text 子串）
│  │  │     ├─ 2_fill_gap.md                # Phase 2 缺口字幕文案补全（受 length_constraint 约束）
│  │  │     ├─ 2_5_nl_edit.md               # Phase 2.5 NL 指令 → Patch 列表（8 op 清单 + ValueObject 约束 + 中文颜色映射）
│  │  │     └─ scenarios/                   # Phase 0.5 mock 事件脚本（dev_workbench 消费）
│  │  │        ├─ captions_demo.json
│  │  │        ├─ stickers_demo.json
│  │  │        └─ full_extract_demo.json
│  │  ├─ extract/                           # Phase 1A 视觉理解子能力（统一 ctx 签名 + STAGE 模块常量 + lazy import 缺包降级）
│  │  │  ├─ __init__.py
│  │  │  ├─ context.py                      # Phase1AContext：sample 路径 + scenes/frames lazy 缓存 + client(stage)
│  │  │  ├─ scenes.py                       # 1A-T1 切点检测（PySceneDetect），写 Phase1AReport.scenes[]
│  │  │  ├─ frame_sampler.py                # 1A-T2 关键帧抽样器（1fps + scene 边界 ±0.2s + 中点）
│  │  │  ├─ captions.py                     # 1A-V1 字幕样式 + 位置（VLM，跨帧 IoU 合并），写 Phase1AReport.captions[]
│  │  │  ├─ captions_anim.py                # 1A-V2 字幕动画细节验证（OpenCV 5fps 帧差 + 光流），写 Phase1AReport.captions[idx].verified_anim_in
│  │  │  ├─ stickers.py                     # 1A-V3 贴纸两阶段（VLM 网格 → CV refine bbox 至 ±5px），写 Phase1AReport.stickers[]
│  │  │  ├─ motion.py                       # 1A-V4 缩放方向粗判（VLM）+ 1A-V5 缩放曲线（CV 光流），写 Phase1AReport.zoom_directions/.zoom_curves
│  │  │  ├─ transitions.py                  # 1A-V6 转场分类（VLM），写 Phase1AReport.transitions
│  │  │  ├─ masks.py                        # 1A-V7 几何蒙版（CV HoughCircles/Canny/HoughLines 三帧多数决主路径 + VLM 兜底），写 Phase1AReport.masks
│  │  │  ├─ color.py                        # 1A-V8 调色语义（VLM 标签 + OpenCV HSV 直方图微调），写 Phase1AReport.color
│  │  │  ├─ audio.py                        # 1A-A1 BGM（Demucs htdemucs 分离 + librosa BPM/能量/情绪），写 Phase1AReport.audio.{has_bgm,bpm,mood_tag}
│  │  │  ├─ skeleton.py                     # 1B 骨架推断（位置阈值发现 + StyleRule 聚合 + sticker 时间转 slot-local [0,1] · D32），读 Phase1AReport 写 TemplateIR.skeleton
│  │  │  └─ pipeline.py                     # 1B extract DAG 编排（asyncio.gather + _safe 降级 + SUBCAP_TO_IR_PATH 翻译 + KB save）
│  │  ├─ kb/                                # 1B 知识库
│  │  │  ├─ __init__.py
│  │  │  ├─ store.py                        # SQLite templates 表 CRUD（与 tasks 表共用 kb.sqlite WAL；init_db 只在 lifespan 调用 D26）
│  │  │  ├─ tagging.py                      # 1B Tags 推断（VLM 综合骨架摘要 + 3 帧）
│  │  │  ├─ sanity.py                       # 1B 整体复查（VLM 验骨架/material_req/placeholder/zoom）
│  │  │  ├─ recommend.py                    # Phase 2 VLM 模板智能推荐 top-k（catalog + ASR 摘要 + 3 帧）
│  │  │  └─ select.py                       # Phase 1B 占位：标签精确匹配；Phase 3 接 LLM rerank
│  │  ├─ apply/                             # Phase 2 应用层（user material + template → ProjectIR）
│  │  │  ├─ __init__.py
│  │  │  ├─ mapping.py                      # 2.map — Unit → voice slot 时间顺序绑定 + ±20% speed 钳制 + 超 max 截短 src_timerange（D31）
│  │  │  ├─ gaps.py                         # 2.gaps — slot 未覆盖检测，按 material_req 分类 fill_strategy
│  │  │  ├─ fill.py                         # 2.fill — text_fill (LLM) / wrap_fill / reuse 三策略；output_span = slot.nominal；通过 outcomes 返回 fill 结果（不 mutate 原 gaps）
│  │  │  ├─ style.py                        # 2.style — 套 StyleRule 到 PlacedSegment + LLM 选 emphasis_words + BGM 选曲；导出 `_segment_output_span` / `style_for_segment`（D31/D32 单一真理源）
│  │  │  └─ pipeline.py                     # 2.pipeline — apply_short DAG 编排（_safe 降级 + STAGE_TO_IR_PATH 翻译 + bgm_mix 自动 ducking · D33 + project.json 落盘）
│  │  ├─ agent/                             # Phase 2.5 + 5 编辑/AIGC 模块
│  │  │  ├─ __init__.py                     # Phase 5 占位（aigc / narrative / sfx_preset 等）
│  │  │  ├─ aigc.py                         # 贴纸生图 / B-roll 占位（Phase 5 填）
│  │  │  └─ nl_edit.py                      # Phase 2.5 核心：nl_edit(LLM NL→Patch) + panel_to_patches + apply_patches(pure dispatcher) + push_snapshot/undo(D35) + list_patch_history(via events.jsonl D36)
│  │  ├─ understand/                        # Phase 1A 语义层分类器 + Phase 2 ASR
│  │  │  ├─ __init__.py
│  │  │  ├─ vision.py                       # classify_caption_function（caption_idx 入参，写 Phase1AReport.captions[idx].function；命名匹配 CI classify_ 前缀）
│  │  │  └─ asr.py                          # Phase 2 WhisperX large-v3 + forced align；缺包 fallback 等距 ~3s 分段
│  │  └─ render/
│  │     ├─ __init__.py
│  │     ├─ client.py                       # httpx 调 renderer /render；renderer_health 探活；Phase 2.5 cancel_render(taskId)（D37 supersede）
│  │     ├─ throttle.py                     # Phase 2.5 项目级 supersede：dict[project_id→in_flight_task_id] + asyncio.Lock + trigger_render_supersede（D37）
│  │     └─ ffmpeg.py                       # ffmpeg/ffprobe wrapper：normalize（pad_mode=black|blur · D34）/ thumbnail / probe / extract_audio / mix_bgm（sidechaincompress）/ compose_segments
│  └─ tests/
│     ├─ __init__.py
│     ├─ conftest.py                        # temp DATA_ROOT + fresh_event_bus + task_with_events fixtures
│     └─ unit/
│        ├─ __init__.py
│        ├─ test_ir_models.py               # ProjectIR 最小构造 + JSON round-trip
│        ├─ test_ir_schema.py               # IR JSON Schema 导出含期望 $defs
│        ├─ test_event_bus.py               # 多订阅 / replay / snapshot 切分 / jsonl tail 续起 / silent
│        ├─ test_scenarios.py               # mock JSON 解析 + ir_target.path 命中真实 IR + parent 顺序
│        ├─ test_llm_client.py              # _extract_json / 双 provider fallback / silent / dual-check / 路由
│        ├─ test_extract_subcaps.py         # 1A 子能力 fallback 形状（缺包 / 空输入 / 缺帧；用 Phase1AContext 直接喂 [] cache）
│        ├─ test_lab_api.py                 # SubcapabilityLab API 行为（registry / 403 / 404 / dry_run）
│        ├─ test_check_scripts.py           # 三脚本 grep 守卫在仓库自有代码上跑过
│        ├─ test_skeleton.py                # 1B 骨架推断（role 阈值 / material_req / 同 role 合并）
│        ├─ test_kb_store.py                # 1B KB store CRUD + IR round-trip + tags 双列同步
│        └─ test_apply.py                   # Phase 2 ASR fallback / _clamp_speed / detect_gaps 分类 / ProjectIR.degraded round-trip
│     └─ integration/
│        ├─ __init__.py
│        ├─ test_subcap_shapes.py           # 1A mock-level integration：seeded ctx 跑全部 subcap，断言事件结构 + Phase1AReport ir_target + parent 链路 + schema round-trip
│        ├─ test_extract_1b.py              # 1B end-to-end pipeline：seeded ctx + 无 credentials → KB 落行 + 事件 ≥ 10 + done 事件压尾
│        ├─ test_apply_phase2.py            # Phase 2 验证 2/3/4/5/11：字幕同步 / speed 钳制 / 缺口补全 / canvas letterbox / Caption.text 不截断
│        └─ test_nl_edit.py                 # Phase 2.5 验证：8 个 PatchOp apply_patches + panel_to_patches + snapshot 栈 round-trip + lodash.set 三 op + _snapshot_payload 端到端重建 + list_by_resource DESC 排序
│
├─ renderer/                                 # Node Remotion 渲染服务
│  ├─ package.json                          # pnpm @sceneecho/renderer 依赖与脚本
│  ├─ tsconfig.json                         # 严格 TS + Bundler 模块解析
│  ├─ tsconfig.build.json                   # 编译出 dist（CI build 用）
│  ├─ scripts/
│  │  └─ gen-types.ts                       # 读 ir.schema.json 写 src/types/ir.ts
│  └─ src/
│     ├─ server.ts                          # Express :8001 入口；/health /render /render/queue + Phase 2.5 DELETE /render/:taskId (D37)
│     ├─ render.ts                          # bundle + selectComposition + renderMedia
│     ├─ queue.ts                           # p-queue({concurrency:1}) 单 worker 串行 + Phase 2.5 RenderState 注册表 (registerRender / cancelRender / finalizeRender) 支持 supersede
│     ├─ progress.ts                        # POST 后端 /api/internal/task-progress
│     ├─ logger.ts                          # pino JSON + withTask child binding
│     ├─ paths.ts                           # DATA_ROOT 解析 + 渲染源目录定位（ESM 安全）
│     ├─ remotion.root.tsx                  # registerRoot 入口
│     ├─ types/
│     │  └─ ir.ts                           # 生成产物：zod schemas + 推导 TS 类型（gitignored）
│     └─ compositions/
│        ├─ Root.tsx                        # <Composition id="Project"> + calculateMetadata
│        ├─ Project.tsx                     # 顶层组合：多 Sequence × per-seg ZoomLayer/Mask/Sticker + 全局 ColorLayer + Caption overlay + BGM Audio (Phase 2)
│        ├─ Caption.tsx                     # 单条字幕的位置/动画/描边渲染（1B 双模式 + anim_in 全套 + 多行 + Phase 2 emphasis_words 高亮）
│        ├─ Mask.tsx                        # 1B 几何蒙版（SVG clipPath circle/rectangle/line_split）
│        ├─ ColorLayer.tsx                  # 1B 调色层（CSS filter 预设按 dominant_lut_id）
│        ├─ ZoomLayer.tsx                   # Phase 2 缩放层（interpolate zoom_keyframes + CSS transform scale）
│        ├─ Sticker.tsx                     # Phase 2 贴纸层（generated_image 双模式：Img / 虚线占位 + Phase 5 替换 badge）
│        └─ projectMeta.ts                  # 从 IR 算 width/height/fps/durationInFrames（含 speed + caption.end 修正）
│     └─ preflight.ts                       # Phase 2 渲染前资源校验（user_material / bgm_track / sticker.generated_image 缺则 throw）
│
└─ frontend/                                 # React + Vite 前端
   ├─ package.json                          # pnpm @sceneecho/frontend 依赖与脚本（含 tailwind / radix / lucide / react-arborist / immer / lodash / vitest）
   ├─ tsconfig.json
   ├─ vite.config.ts                        # :5173 + /api /data 代理到后端 :18521
   ├─ tailwind.config.ts                    # Tailwind theme 桥接 tokens.css 的 CSS 变量
   ├─ postcss.config.js                     # postcss + tailwindcss + autoprefixer
   ├─ vitest.config.ts                      # vitest + jsdom + react 插件
   ├─ test-setup.ts                         # 引入 @testing-library/jest-dom matchers
   ├─ index.html
   ├─ scripts/
   │  └─ gen-types.ts                       # 读 ir.schema.json 写 src/types/ir.ts
   └─ src/
      ├─ main.tsx                           # 路由入口（Shell + /sample-extract / /workbench/dev / /workbench/:taskId / /projects/:id/replay / /samples/:id/replay）
      ├─ styles/
      │  ├─ tokens.css                      # Anthropic 风 design tokens（颜色/字体/间距/圆角/stage 染色）
      │  └─ global.css                      # @tailwind 注入 + 基础排版 + se-* 组件类（卡片/按钮/动画）
      ├─ api/
      │  ├─ index.ts                        # axios 封装：uploadSample / renderDemo / pollTask / dataUrl + Phase 2 projects + Phase 2.5 edit/panelEdit/undoEdit/listPatchHistory/listSampleTasks/listProjectTasks/fetchReplayEvents/snapshotAtSequence/fetchProjectLineage/rejectEvent
      │  ├─ events.ts                       # subscribeEvents (EventSource) / fetchEventHistory / mock-stream / scenarios
      │  ├─ templates.ts                    # 1B KB API: triggerExtract / list / get / patchTags / patchPlaceholder / delete / getEvents
      │  └─ lab.ts                          # SubcapabilityLab API：listSubcaps / runSubcap / getBaseline
      ├─ state/
      │  ├─ index.ts                        # Zustand store：currentTask
      │  └─ workbench.ts                    # 工作台 store：events / irSnapshot (immer + lodash.set) / childIndex / vetoedIds / autoFollow / 选中 / 过滤 / visionPaneMode / streamViewMode
      ├─ components/
      │  ├─ TaskProgress.tsx                # task_id 轮询 + 进度条 + 错误展示
      │  ├─ RemotionPlayer.tsx              # Phase 2 CSS-based 预览（<video> + playbackRate + CSS zoom/caption/sticker 叠层，不打包 Remotion bundle）
      │  ├─ ExtractHistoryList.tsx          # Phase 2.5 通用样例/项目历史列表（任务 kind 中文映射 + 状态色 + 相对时间）
      │  ├─ editor/
      │  │  ├─ NLBar.tsx                    # Phase 2.5 Editor 底部 NL 输入栏 → POST /projects/{id}/edit
      │  │  ├─ ParamPanel.tsx               # Phase 2.5 Editor 左侧参数面板（字幕颜色/字号/位置/动画/换行/placeholder/节奏/画布/BGM） → POST /panel-edit
      │  │  └─ PatchHistoryList.tsx         # Phase 2.5 Editor 右侧编辑历史（GET /history） + Undo 按钮（POST /undo）
      │  └─ workbench/
      │     ├─ WorkbenchVisionPane.tsx      # 左栏：选中事件帧 + bbox overlay + 「帧/原视频」toggle（video 单挂载，按 frame_ts 命令式 seek，autoFollow 时不打断连续观看）
      │     ├─ WorkbenchEventStream.tsx     # 中栏：默认按 stage 分组（可切按到达顺序）+ ↑↓/Enter/X 快捷键 + URL stage_filter/time_range + 否决线穿 + reasoning pre-wrap 自然多行
      │     ├─ WorkbenchIRPane.tsx          # 右栏：react-arborist 渲染 IR 树 + 命中字段 800ms 高亮 + 点击叶子 pin 到底部 detail strip（lodash.get 实时取值显示全文）
      │     ├─ WorkbenchBreadcrumb.tsx      # Phase 2.5 工作台顶栏面包屑「样例|项目 > {resource} > {kind 中文} #{tid 前 8}」
      │     ├─ EventBadge.tsx               # stage 前缀染色徽章（badgeColor 导出）
      │     └─ BboxOverlay.tsx              # 0-999 → 像素的 SVG bbox + 标签气泡（bboxToRect 导出）
      ├─ pages/
      │  ├─ SampleExtract.tsx               # 阶段 0/1B 上传 + 渲染 demo + 「提取模板（1B）」按钮 + 工作台跳转 + Phase 2.5 ExtractHistoryList + ?sample_id= 反向回跳
      │  ├─ TemplateLibrary.tsx             # 1B `/templates` 列表 + `/templates/:id` 详情（骨架/sanity/placeholder 编辑/事件回放）+ Phase 2.5 详情页底部「本样例其它提取记录」
      │  ├─ Editor.tsx                      # Phase 2 出片闭环：上传 → 推荐 → 应用 → 预览 → 渲染 + Phase 2.5 三栏 [ParamPanel | Preview+NLBar | PatchHistoryList]
      │  ├─ Visualize.tsx                   # Phase 2.5 `/projects/:id/replay` 与 `/samples/:id/replay` 事件回放器（时间线 scrub + 倍速 + MediaRecorder 60s 录屏导出）
      │  ├─ Workbench.tsx                   # /workbench/:taskId 三栏页面：SSE 订阅 + history 预填 + Phase 2.5 顶栏 WorkbenchBreadcrumb
      │  ├─ WorkbenchLauncher.tsx           # /workbench/dev：列出 mock scenarios + 启动按钮
      │  └─ SubcapabilityLab.tsx            # /lab：DEV-only Phase 1A 子能力 × fixture 单点验证
      ├─ vite-env.d.ts                      # /// <reference types="vite/client" /> 让 import.meta.env 可解析
      └─ types/
         ├─ ir.ts                           # 生成产物（gitignored）
         └─ workbench.ts                    # 本地 VisionEvent / IRTarget / ScenarioListItem 类型镜像
```
