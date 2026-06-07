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
│  │  ├─ projects/{id}/                     # 项目：user_material/normalized/project.json/outputs
│  │  ├─ system/                            # 字体 / BGM 池 / 模型缓存 / 贴纸参考
│  │  ├─ aigc/                              # AIGC 缓存（贴纸 / B-roll）
│  │  ├─ kb.sqlite                          # tasks 表 + 后续 KB 表
│  │  └─ logs/                              # JSON 结构化日志按天落盘
│  ├─ app/
│  │  ├─ __init__.py
│  │  ├─ main.py                            # FastAPI 入口：CORS + lifespan + 路由挂载 + /data 静态
│  │  ├─ config.py                          # pydantic-settings 读 .env，提供 resolve() 路径解析
│  │  ├─ logging.py                         # structlog JSON 配置 + task_id contextvar 绑定
│  │  ├─ cli.py                             # typer：ingest-sample / ingest-project（dev 闸门）
│  │  ├─ tasks_store.py                     # SQLite tasks 表 CRUD（WAL 模式）
│  │  ├─ api/
│  │  │  ├─ __init__.py
│  │  │  ├─ samples.py                      # POST /samples 上传归一化；POST /samples/{id}/render-demo
│  │  │  ├─ projects.py                     # POST /projects 上传占位
│  │  │  └─ tasks.py                        # GET /tasks/{id}；POST /internal/task-progress
│  │  ├─ ir/
│  │  │  ├─ __init__.py                     # 顶层 IR 类型聚合 export
│  │  │  ├─ ledger.py                       # TranscriptLedger / Unit
│  │  │  ├─ template.py                     # TemplateIR + Slot/StyleRule/CaptionStyle/...
│  │  │  ├─ project.py                      # ProjectIR + Section/PlacedSegment/Caption/Gap
│  │  │  ├─ patch.py                        # NL/面板/审核统一编辑 op
│  │  │  └─ export.py                       # pydantic → JSON Schema 聚合导出
│  │  └─ render/
│  │     ├─ __init__.py
│  │     ├─ client.py                       # httpx 调 renderer /render；renderer_health 探活
│  │     └─ ffmpeg.py                       # ffmpeg/ffprobe wrapper：normalize / thumbnail / probe
│  └─ tests/
│     ├─ __init__.py
│     ├─ conftest.py                        # temp DATA_ROOT + 复制 tests/fixtures
│     └─ unit/
│        ├─ __init__.py
│        ├─ test_ir_models.py               # ProjectIR 最小构造 + JSON round-trip
│        └─ test_ir_schema.py               # IR JSON Schema 导出含期望 $defs
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
   ├─ package.json                          # pnpm @sceneecho/frontend 依赖与脚本
   ├─ tsconfig.json
   ├─ vite.config.ts                        # :5173 + /api /data 代理到后端 :18521
   ├─ index.html
   ├─ scripts/
   │  └─ gen-types.ts                       # 读 ir.schema.json 写 src/types/ir.ts
   └─ src/
      ├─ main.tsx                           # 路由入口 (BrowserRouter)
      ├─ api/
      │  └─ index.ts                        # axios 封装：uploadSample / renderDemo / pollTask / dataUrl
      ├─ state/
      │  └─ index.ts                        # Zustand store：currentTask
      ├─ components/
      │  └─ TaskProgress.tsx                # task_id 轮询 + 进度条 + 错误展示
      ├─ pages/
      │  └─ SampleExtract.tsx               # 阶段 0 上传 + 渲染 demo + 内嵌 <video> 播放
      └─ types/
         └─ ir.ts                           # 生成产物：同 renderer（gitignored）
```
