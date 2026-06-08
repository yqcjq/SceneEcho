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
│  └─ gen_schema.py                         # Pydantic → shared/ir.schema.json 的薄入口
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
│  │  │  └─ pipeline/events_{task_id}.jsonl   # 项目应用事件流
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
│  │  ├─ tasks_store.py                     # SQLite tasks 表 CRUD（WAL）+ Phase 0.5 idempotent ALTER
│  │  ├─ event_bus.py                       # 进程内事件总线：subscribe_with_snapshot / await put 反压 / jsonl 持久化 / jsonl tail seq 真理源 / lookup callback 注入
│  │  ├─ api/
│  │  │  ├─ __init__.py
│  │  │  ├─ samples.py                      # POST /samples 上传归一化；POST /samples/{id}/render-demo
│  │  │  ├─ projects.py                     # POST /projects 上传占位
│  │  │  ├─ tasks.py                        # GET /tasks/{id}；POST /internal/task-progress
│  │  │  ├─ events.py                       # GET /tasks/{id}/events SSE + /events/history
│  │  │  └─ dev_workbench.py                # ENABLE_DEV_MOCK gated：mock-stream / scenarios 列表
│  │  ├─ ir/
│  │  │  ├─ __init__.py                     # 顶层 IR 类型聚合 export
│  │  │  ├─ ledger.py                       # TranscriptLedger / Unit
│  │  │  ├─ template.py                     # TemplateIR + Slot/StyleRule/CaptionStyle/...
│  │  │  ├─ project.py                      # ProjectIR + Section/PlacedSegment/Caption/Gap
│  │  │  ├─ patch.py                        # NL/面板/审核统一编辑 op
│  │  │  ├─ vision_event.py                 # VisionEvent / IRTarget（AI 决策事件 IR · D9/D10；ir_value: Any）
│  │  │  ├─ path_validator.py               # lodash 风路径校验器（CI 验证 mock JSON 命中真实 IR）
│  │  │  └─ export.py                       # pydantic → JSON Schema 聚合导出
│  │  ├─ llm/
│  │  │  ├─ __init__.py
│  │  │  ├─ client.py                       # LLMClient ABC + OpenAICompat/Anthropic 占位（chat_vision/chat_text）
│  │  │  └─ prompts/
│  │  │     ├─ __init__.py
│  │  │     └─ scenarios/                   # Phase 0.5 mock 事件脚本（dev_workbench 消费）
│  │  │        ├─ captions_demo.json
│  │  │        ├─ stickers_demo.json
│  │  │        └─ full_extract_demo.json
│  │  └─ render/
│  │     ├─ __init__.py
│  │     ├─ client.py                       # httpx 调 renderer /render；renderer_health 探活
│  │     └─ ffmpeg.py                       # ffmpeg/ffprobe wrapper：normalize / thumbnail / probe
│  └─ tests/
│     ├─ __init__.py
│     ├─ conftest.py                        # temp DATA_ROOT + fresh_event_bus + task_with_events fixtures
│     └─ unit/
│        ├─ __init__.py
│        ├─ test_ir_models.py               # ProjectIR 最小构造 + JSON round-trip
│        ├─ test_ir_schema.py               # IR JSON Schema 导出含期望 $defs
│        ├─ test_event_bus.py               # 多订阅 / replay / snapshot 切分 / jsonl tail 续起 / silent
│        └─ test_scenarios.py               # mock JSON 解析 + ir_target.path 命中真实 IR + parent 顺序
│
├─ renderer/                                 # Node Remotion 渲染服务
│  ├─ package.json                          # pnpm @sceneecho/renderer 依赖与脚本
│  ├─ tsconfig.json                         # 严格 TS + Bundler 模块解析
│  ├─ tsconfig.build.json                   # 编译出 dist（CI build 用）
│  ├─ scripts/
│  │  └─ gen-types.ts                       # 读 ir.schema.json 写 src/types/ir.ts
│  └─ src/
│     ├─ server.ts                          # Express :8001 入口；/health /render /render/queue
│     ├─ render.ts                          # bundle + selectComposition + renderMedia
│     ├─ queue.ts                           # p-queue({concurrency:1}) 单 worker 串行
│     ├─ progress.ts                        # POST 后端 /api/internal/task-progress
│     ├─ logger.ts                          # pino JSON + withTask child binding
│     ├─ paths.ts                           # DATA_ROOT 解析 + 渲染源目录定位（ESM 安全）
│     ├─ remotion.root.tsx                  # registerRoot 入口
│     ├─ types/
│     │  └─ ir.ts                           # 生成产物：zod schemas + 推导 TS 类型（gitignored）
│     └─ compositions/
│        ├─ Root.tsx                        # <Composition id="Project"> + calculateMetadata
│        ├─ Project.tsx                     # 顶层组合：OffthreadVideo 段落 + Caption overlay
│        ├─ Caption.tsx                     # 单条字幕的位置/动画/描边渲染
│        └─ projectMeta.ts                  # 从 IR 算 width/height/fps/durationInFrames（共用）
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
      ├─ main.tsx                           # 路由入口（Shell + /sample-extract / /workbench/dev / /workbench/:taskId）
      ├─ styles/
      │  ├─ tokens.css                      # Anthropic 风 design tokens（颜色/字体/间距/圆角/stage 染色）
      │  └─ global.css                      # @tailwind 注入 + 基础排版 + se-* 组件类（卡片/按钮/动画）
      ├─ api/
      │  ├─ index.ts                        # axios 封装：uploadSample / renderDemo / pollTask / dataUrl + 转出 events 模块
      │  └─ events.ts                       # subscribeEvents (EventSource) / fetchEventHistory / mock-stream / scenarios
      ├─ state/
      │  ├─ index.ts                        # Zustand store：currentTask
      │  └─ workbench.ts                    # 工作台 store：events / irSnapshot (immer + lodash.set) / childIndex / vetoedIds / autoFollow / 选中 / 过滤
      ├─ components/
      │  ├─ TaskProgress.tsx                # task_id 轮询 + 进度条 + 错误展示
      │  └─ workbench/
      │     ├─ WorkbenchVisionPane.tsx      # 左栏：选中事件帧 + bbox overlay
      │     ├─ WorkbenchEventStream.tsx     # 中栏：事件卡片倒序 + ↑↓/Enter/X 快捷键 + URL stage_filter/time_range + 否决线穿
      │     ├─ WorkbenchIRPane.tsx          # 右栏：react-arborist 渲染 IR 树（ResizeObserver 测父高度）+ 命中字段(含 field) 800ms 闪烁
      │     ├─ EventBadge.tsx               # stage 前缀染色徽章（badgeColor 导出）
      │     └─ BboxOverlay.tsx              # 0-999 → 像素的 SVG bbox + 标签气泡（bboxToRect 导出）
      ├─ pages/
      │  ├─ SampleExtract.tsx               # 阶段 0 上传 + 渲染 demo + 内嵌 <video> 播放
      │  ├─ Workbench.tsx                   # /workbench/:taskId 三栏页面：SSE 订阅 + history 预填
      │  └─ WorkbenchLauncher.tsx           # /workbench/dev：列出 mock scenarios + 启动按钮
      └─ types/
         ├─ ir.ts                           # 生成产物（gitignored）
         └─ workbench.ts                    # 本地 VisionEvent / IRTarget / ScenarioListItem 类型镜像
```
