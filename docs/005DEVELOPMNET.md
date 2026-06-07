# 005 · 首次构建与运行指引

> 目标读者：第一次 clone 这个仓库的开发者。读完照做能在本机跑通"上传 mp4 → 渲染叠字幕的 mp4 → 浏览器播放"全链路。
>
> 平台：以 Windows 11 + Git Bash 为主，其他平台命令同形（venv 激活脚本路径不同）。

---

## 0. 总览

三服务架构，本地全部跑起来：

| 服务 | 端口 | 进程 |
|------|------|------|
| Backend (FastAPI) | 18521 | Python venv |
| Renderer (Node Remotion) | 8001 | Node 进程 |
| Frontend (Vite) | 5173 | Vite dev server |

外加一条 IR codegen 管线：pydantic 模型 → `shared/ir.schema.json` → 两端 `src/types/ir.ts`。

---

## 1. 前置软件

| 工具 | 版本 | 安装 | 验证 |
|------|------|------|------|
| Python | 阶段 0 用 **3.13** 可；进阶段 1 前换 **3.11/3.12** | https://www.python.org/downloads/ | `python --version` |
| Node.js | ≥ 18（推荐 20 LTS） | https://nodejs.org/ | `node --version` |
| pnpm | ≥ 8（仓库锁定 10.x） | `npm install -g pnpm` | `pnpm --version` |
| FFmpeg + ffprobe | 6+ 且加入 PATH | `winget install Gyan.FFmpeg` | `ffmpeg -version` / `ffprobe -version` |
| Git | 任意 | https://git-scm.com/ | `git --version` |

**安装 FFmpeg 后必须新开终端**（让 PATH 生效），再做 `ffmpeg -version` 验证，否则后续后端 normalize 会报"找不到 ffmpeg"。

---

## 2. 拉代码

```bash
git clone https://github.com/yqcjq/SceneEcho.git
cd SceneEcho
```

仓库根绝对路径示例：`D:\Project\2026-6-SceneEcho\SceneEcho`。本文档所有相对路径基于此。

---

## 3. 环境变量

```bash
cp .env.example .env
```

`.env` 字段：

| 变量 | 阶段 0 是否必填 | 说明 |
|------|---------------|------|
| `DATA_ROOT` | 不填 = 默认 `backend/data` | 所有媒体落盘根 |
| `RENDERER_URL` | 不填 = `http://localhost:8001` | 后端调 renderer |
| `BACKEND_URL` | 不填 = `http://localhost:18521` | renderer 回调后端 |
| `LLM_*` / `MODEL_*` | **阶段 0 可空** | 阶段 1 起才真用 |
| `BGM_STRATEGY` | 默认 `features` | `original` 仅个人使用（版权风险） |
| `ENABLE_CLI_INGEST` | 推荐设 `true` | dev CLI 上传开关 |
| `LOG_LEVEL` | 默认 `INFO` | `DEBUG` 排障用 |

`.env` 不入 git（`.gitignore` 已忽略）。

---

## 4. 后端环境（Python）

```bash
cd backend
python -m venv .venv

# 激活（Windows Git Bash 用 source 也行）
source .venv/Scripts/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
# Windows cmd：    .venv\Scripts\activate.bat
# macOS / Linux：  source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"
```

验证（**仍在 `backend/` 目录、venv 已激活**）：
```bash
python -c "import app.main; print('backend importable')"
ruff check .
pytest tests/unit -v
# 单测路径是 backend/tests/unit/，跑出 test_ir_schema + test_ir_models 全绿即可。
# 注意：仓库根的 tests/ 只放 fixtures（测试视频），不放单测代码。
```

---

## 5. Node 工作区（renderer + frontend）

回到仓库根：
```bash
cd ..
pnpm install
```

`pnpm install` 会自动给 `renderer/` 和 `frontend/` 装依赖（pnpm-workspace.yaml 管理）。

---

## 6. 生成 IR 类型（关键步骤）

```bash
# 仍在仓库根，且 backend 的 venv 已激活
pnpm gen:types
```

这个命令会：
1. 跑 `python scripts/gen_schema.py` → 生成 `shared/ir.schema.json`
2. 跑 `renderer/scripts/gen-types.ts` → 生成 `renderer/src/types/ir.ts`
3. 跑 `frontend/scripts/gen-types.ts` → 生成 `frontend/src/types/ir.ts`

**这三个产物 gitignore，每次拉新代码 / 改 IR 都要重新生成**。

验证：
```bash
ls shared/ir.schema.json renderer/src/types/ir.ts frontend/src/types/ir.ts
# 三个文件都应存在
```

---

## 7. 准备测试 fixtures

按 `tests/fixtures/README.md` 放两段 mp4：

```
tests/fixtures/sample_basic_15s/source.mp4   # 5–20s
tests/fixtures/short_15s/source.mp4          # 10–20s
```

这两个文件**不入 git**。没有它们可以跳过 CLI ingest 验证，但 UI 上传链路仍可用任意 mp4 测。

---

## 8. 启动三服务

**方式 A：一键起（推荐）**

```bash
# 仓库根，backend venv 已激活
pnpm dev
```

会用 concurrently 同时起 backend / renderer / frontend，控制台带颜色前缀区分。

**方式 B：分三个终端**

终端 1（backend）：
```bash
cd backend
source .venv/Scripts/activate
python -m uvicorn app.main:app --reload --port 18521
```

终端 2（renderer）：
```bash
pnpm dev:renderer
```

终端 3（frontend）：
```bash
pnpm dev:frontend
```

---

## 9. 验证全链路

### 9.1 服务探活

```bash
curl http://localhost:18521/health    # {"status":"ok","service":"backend"}
curl http://localhost:8001/health    # {"status":"ok","service":"renderer",...}
curl http://localhost:5173           # HTML 入口
```

### 9.2 浏览器端到端

1. 打开 http://localhost:5173 自动跳转到 `/sample-extract`
2. 选一段 mp4 上传（任意短视频，几秒到几十秒）
3. 上传成功显示 `sample_id`
4. 点"渲染 demo"
5. 看到进度条 0% → 100%（阶段 `bundling` → `rendering` → `done`）
6. 页面下方 `<video>` 播放产物，画面中央偏下叠加 "Hello SceneEcho" 字幕

### 9.3 CLI ingest（可选）

确认 `.env` 里 `ENABLE_CLI_INGEST=true`，然后：
```bash
cd backend
source .venv/Scripts/activate
python -m app.cli ingest-sample ../tests/fixtures/sample_basic_15s/source.mp4
```

检查 `backend/data/samples/smp_*/` 下出现 `source.mp4`、`normalized.mp4`、`thumbnail.jpg`。

---

## 10. 排障

| 现象 | 排查 |
|------|------|
| `ffmpeg: command not found` / 上传 500 报 normalize failed | 装 FFmpeg 后**重开终端**；`where ffmpeg` 看路径 |
| `pnpm gen:types` 报 `ModuleNotFoundError: app` | backend venv 未激活，或没跑过 `pip install -e .` |
| `pnpm gen:types` 报 `json-schema-to-zod` 缺失 | `pnpm install` 没跑完，重跑 |
| renderer 首次 `/render` 慢 30s+ | 首次会下载 headless Chromium（~150MB），缓存到 `~/.cache/remotion/` |
| 上传 mp4 浏览器报 CORS | 检查 backend 启动端口是不是 18521；vite.config.ts 代理只走 18521 |
| 渲染进度卡在 `bundling` | 看 renderer 终端日志，可能是 bundle 编译报错（IR 类型未生成？） |
| pytest 报 `app` 找不到 | 必须在 `backend/` 目录下跑 pytest，且 venv 激活 |
| Windows 路径反斜杠出问题 | IR 内引用一律用 POSIX 风格（`projects/x/normalized.mp4`），后端 / renderer 内部自动解析 |

排障时优先打开 backend 终端 + renderer 终端的 stdout 看 JSON 结构化日志，每条带 `task_id`。

---

## 11. 日常开发循环

```bash
# 改了 IR（backend/app/ir/*.py）
pnpm gen:types     # 重生成两端 types
# 改了 backend Python 代码：uvicorn --reload 自动热更
# 改了 renderer/frontend：tsx watch / Vite HMR 自动热更
```

**改 IR 后必须 commit 前先 `pnpm gen:types`**：CI 的 `type-sync` job 会校验 schema 与 ir.ts 是否一致，不一致直接红。

---

## 12. 进阶

- 集成测试 / 端到端测试：阶段 0 暂无，Phase 1+ 引入。
- 部署：阶段 0 不部署，三服务全本地。
- 长视频管线、AIGC、NL 编辑：后续阶段功能，见 `../PLAN.md`。

下一步阅读：`001ARCHITECTURE.md`（系统协作）→ `002STRUCTURE.md`（代码在哪）→ `../PLAN.md`（接下来做什么）。
