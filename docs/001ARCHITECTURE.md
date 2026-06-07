# SceneEcho 整体架构

> 风格约束（依 `000README.md`）：陈述句描述当前事实，不写历史、不写优缺点、不写"未来可以考虑"、不写被否定的方案、不放目录树。详细推理见 `decisions/`，目录树见 `002STRUCTURE.md`。

---

## 1. 系统拓扑

```
┌──────────────────────────┐   HTTP /api/*    ┌────────────────────────────┐
│  Frontend (Vite, :5173)   │ ───────────────▶ │  Backend (FastAPI, :18521)  │
│  React + Remotion Player  │ ◀── /data/* ──── │  app/{api, ir, render, … } │
└──────────────────────────┘                  └────────────┬───────────────┘
                                                           │ HTTP /render
                                                           ▼
                                              ┌────────────────────────────┐
                                              │ Renderer (Express, :8001)  │
                                              │ Remotion + Chromium → mp4  │
                                              └────────────────────────────┘
                                                           │
                                                共享卷 DATA_ROOT (本地 backend/data/)
```

三服务通过 HTTP + JSON 通信，共享 `DATA_ROOT` 文件系统读写媒体。前端不直渲染像素，调用后端 API 触发渲染，渲染产物经后端 `/data/*` 静态路由回放。

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
└──────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────┐
│ 能力层（backend/app/{render, ir}）            │
│ FFmpeg 归一化 / IR 校验 / 渲染客户端          │
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
- 后端 `api/` 只 import `app/{ir,render,tasks_store,config,logging}`；不反向依赖 frontend / renderer 进程。
- renderer 不调后端业务 API，仅通过 `POST /api/internal/task-progress` 上报进度，并通过 `GET {BACKEND_URL}/data/*` 拉取用户素材字节。
- IR 类型方向：pydantic（唯一真相源）→ JSON Schema → 两端 zod/TS；CI 的 `type-sync` job 阻塞反向修改。
- 跨服务文件传递只用相对 `DATA_ROOT` 的 POSIX 路径字符串，禁止绝对路径。

---

## 4. 状态持久化分类

| 数据类型 | 存储位置 | 说明 |
|---------|---------|------|
| 任务态（progress / stage / result） | `DATA_ROOT/kb.sqlite` 的 `tasks` 表 | WAL 模式；后端写、前端读 |
| 上传媒体 / 归一化产物 / 渲染输出 | `DATA_ROOT/{samples,projects}/...` | 文件系统，相对路径在 IR 内引用 |
| ProjectIR / TemplateIR / TranscriptLedger | `projects/{id}/project.json` 等 | JSON 落盘，供回放、调试 |
| Remotion bundle | renderer 进程内存 + headless Chromium 缓存 | 启动后首次渲染缓存一次 |
| 前端 UI 态（上传 ID、当前任务） | 浏览器内存（Zustand） | 刷新即失，不持久化 |

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
