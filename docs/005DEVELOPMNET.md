# 005 · 首次构建与运行指引

> 目标读者：想把 SceneEcho 跑起来、看看它能做什么的人。照着做完能在本机跑通完整功能——上传样例视频 → 提取风格模板 → 上传口播素材 → 套用风格 → 渲染成品 mp4 → 用自然语言修改字幕颜色。不需要提前了解项目架构。
>
> 平台：以 Windows 11 + Git Bash 为主，其他平台命令同形（venv 激活脚本路径不同）。

---

## 0. 总览

本地需要同时跑三个服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| Backend (FastAPI) | 18521 | Python，处理上传、AI 分析、渲染调度 |
| Renderer (Node Remotion) | 8001 | Node，负责把模板渲染成 mp4 |
| Frontend (Vite) | **5177** | 浏览器界面 |

外部依赖：需要一个 OpenAI-compatible LLM 网关账号（项目默认用 PPIO）。没有账号时大部分功能会降级到占位输出，但服务能启动。

---

## 1. 前置软件

| 工具 | 版本要求 | 安装 | 验证 |
|------|---------|------|------|
| Python | **3.11 或 3.12**（3.13 不兼容部分 ML 库） | https://www.python.org/downloads/ | `python --version` |
| Node.js | ≥ 18（推荐 20 LTS） | https://nodejs.org/ | `node --version` |
| pnpm | 10.x | `npm install -g pnpm@10` | `pnpm --version` |
| FFmpeg + ffprobe | 6+，必须加入 PATH | `winget install Gyan.FFmpeg` | `ffmpeg -version` |
| Git | 任意 | https://git-scm.com/ | `git --version` |

**装好 FFmpeg 后必须新开终端**（让 PATH 生效），再验证 `ffmpeg -version`，否则视频处理会报「找不到 ffmpeg」。

**磁盘**：建议预留 ≥ 15 GB（Python 依赖含 torch/demucs 约 3 GB，AI 模型权重约 4 GB，渲染产物按需增长）。

**网络**：首次运行时会自动下载几 GB AI 模型权重，国内网络可能需要 HuggingFace 镜像或代理。

---

## 2. 拉代码

```bash
git clone https://github.com/yqcjq/SceneEcho.git
cd SceneEcho
```

---

## 3. 配置环境变量

```bash
cp .env.example .env
```

用任意编辑器打开 `.env`，按需填写以下字段。标注「必填」的不填对应功能会降级。

### LLM / VLM（AI 分析功能）

| 变量 | 是否必填 | 说明 |
|------|---------|------|
| `LLM_BASE_URL` | 必填 | OpenAI-compatible 接口地址，默认已指向 PPIO |
| `LLM_API_KEY` | 必填 | 你的 API Key；缺则模板推荐 / 字幕分析全走占位符输出 |
| `MODEL_VLM` | 必填 | 视觉模型 id（如 PPIO 上的 Qwen-VL 系列） |
| `MODEL_TEXT` | 必填 | 文本推理模型 id（如 DeepSeek） |
| `MODEL_TEXT_CHEAP` | 必填 | 高频调用文本模型 id（如 Qwen-Plus） |

### 存储路径（默认值够用，通常不需要改）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATA_ROOT` | `backend/data` | 所有上传文件 / 渲染产物的存放目录 |
| `RENDERER_URL` | `http://localhost:8001` | 后端调 renderer 的地址 |
| `BACKEND_URL` | `http://localhost:18521` | renderer 回调后端的地址 |

### ASR 语音转写

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ASR_PROVIDER` | `glm` | `glm` 用 PPIO GLM-ASR 网络转写（推荐）；`whisperx` 用本地模型 |
| `ASR_BASE_URL` | `https://api.ppio.com/v3/glm-asr` | GLM-ASR 接口地址 |
| `MODEL_ASR` | `glm-asr-2512` | GLM-ASR 模型 id |

> `glm` 模式复用 `LLM_API_KEY`，不需要额外申请。`whisperx` 模式在本机离线运行，但首次会下载约 3 GB 模型。

### 其他（可不改，保持默认即可）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BGM_STRATEGY` | `features` | BGM 匹配策略，保持默认 |
| `ENABLE_DEV_MOCK` | `true` | 开启子能力调试页（开发时保持 true） |
| `LOG_LEVEL` | `INFO` | 日志级别 |

`.env` 不入 git，凭据自行管理。

---

## 4. 安装 Python 依赖

```bash
cd backend
python -m venv .venv

# 激活虚拟环境
source .venv/Scripts/activate        # Windows Git Bash
# .venv\Scripts\Activate.ps1         # Windows PowerShell
# source .venv/bin/activate           # macOS / Linux

pip install --upgrade pip
pip install -e ".[dev,extract]"
```

`[extract]` 包含视频分析所需的重型依赖（torch / demucs / opencv 等），不装的话视频分析功能会全部降级。安装时间较长，耐心等待。

验证（仍在 `backend/` 目录、venv 已激活）：

```bash
python -c "import app.main; print('backend ok')"
```

---

## 5. 安装 Node 依赖

回到仓库根目录：

```bash
cd ..
pnpm install
```

会自动给 renderer 和 frontend 两个子项目装好依赖。

---

## 6. 生成类型文件（必做）

```bash
# 仓库根，且 backend 的 venv 已激活
pnpm gen:types
```

验证：

```bash
ls shared/ir.schema.json renderer/src/types/ir.ts frontend/src/types/ir.ts
# 三个文件都应存在
```

这步生成的文件被 gitignore 忽略，每次拉新代码后都需要重新执行。

---

## 7. 系统资源确认

仓库内 `data/system/` 已包含渲染所需的字体和调色预设：

```
data/system/
├─ fonts/          # 思源黑体 / 宋体 + Source Han Sans SC
└─ luts/           # 调色 LUT 预设
```

这两个目录随仓库一起 clone 下来，不需要手动操作。

---

## 8. 启动服务

**方式 A：一键起（推荐）**

```bash
# 仓库根，backend venv 已激活
pnpm dev
```

控制台会用颜色区分三个服务（蓝 = backend，紫 = renderer，绿 = frontend）。

**方式 B：分三个终端（便于单独查看日志）**

终端 1（backend）：
```bash
cd backend
source .venv/Scripts/activate
python -m uvicorn app.main:app --reload --reload-dir app --port 18521
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

## 9. 验证服务正常

### 9.1 探活

```bash
curl http://localhost:18521/health    # 应返回 {"status":"ok","service":"backend"}
curl http://localhost:8001/health     # 应返回 {"status":"ok","service":"renderer",...}
curl http://localhost:5177            # 应返回 HTML
```

### 9.2 上传样例，提取风格模板

1. 打开 http://localhost:5177，会跳到样例上传页
2. 上传 `tests/fixtures/sample_basic_15s/source.mp4`
3. 上传成功后点「提取模板」
4. 顶部出现 banner，点「打开 AI 工作台」可看到实时分析事件流
5. 分析完成后，进 `/templates` 能看到刚入库的模板卡片

### 9.3 上传口播素材，套用模板渲染出片

1. 进 `/editor`，上传一段 10–20 秒的口播视频
2. 上传完成后下方自动出现智能推荐的模板卡片
3. 选一张模板，点「应用」
4. 等待处理完成，中央播放器出现实时预览
5. 点「渲染出片」，等进度条跑完，下载 mp4

### 9.4 自然语言编辑

在 Editor 页底部输入框输入「字幕换成黄色」，播放器字幕实时变黄。

---

## 10. 排障

| 现象 | 排查 |
|------|------|
| 浏览器输入 `localhost:5173` 一直打不开 | 端口是 `5177`，不是 5173 |
| `ffmpeg: command not found` 或上传报 normalize 失败 | 装 FFmpeg 后**重开终端**；`where ffmpeg` 确认路径 |
| 视频分析事件全是 degraded / fallback | backend venv 没装 `[extract]`，重跑 `pip install -e ".[dev,extract]"` |
| 字幕显示 `[语音 0]` / `[语音 1]` 占位 | `LLM_API_KEY` 未填或 PPIO 网络不通，先用 `curl` 测试接口连通性 |
| 模板推荐返回空 | `LLM_API_KEY` 缺失或 `MODEL_VLM` 在 PPIO 上不存在，进控制台确认模型可用 |
| `pnpm gen:types` 报 `ModuleNotFoundError: app` | backend venv 未激活，或没跑 `pip install -e .` |
| renderer 首次渲染慢 30 秒以上 | 首次下载 headless Chromium（约 150 MB），等待即可 |
| ASR / 视频分析首次跑很慢 | 在下载 AI 模型权重，终端有 `Downloading` 字样即正常，等待即可 |
| `/sublab` 路由 404 | `ENABLE_DEV_MOCK=true` 没设置，或 backend 没重启 |
| 上传 mp4 报 CORS | 检查 backend 是否在 18521 端口，`vite.config.ts` 的代理只走这个端口 |
| `pytest` 报 `app` 找不到 | 必须在 `backend/` 目录下跑，且 venv 已激活 |

排障时优先看 backend 终端输出（结构化 JSON 日志，每条带 `task_id` / `stage`）和浏览器 DevTools → Network → SSE 事件流。
