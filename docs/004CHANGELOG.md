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
