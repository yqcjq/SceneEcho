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
- 新建后端骨架：FastAPI 入口 + lifespan + CORS + /data 静态挂载；`config.py` pydantic-settings + REPO_ROOT 解析；`logging.py` structlog JSON；SQLite tasks 表 CRUD（WAL）；typer CLI ingest（gated by ENABLE_CLI_INGEST）
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
