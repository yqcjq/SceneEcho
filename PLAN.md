# SceneEcho — 口播视频「结构 + 风格」迁移引擎 · 分阶段实施计划

## 项目一句话愿景

> 让创作者从一段 5–20s 优质口播样例中**学到剪辑风格**，自动复用到自己的口播素材上**直接出片**，告别手工 1:1 模仿样例的字幕动画、缩放卡点、贴纸、BGM。

## 术语表

| 术语 | 含义 |
|------|------|
| **口播视频** | 创作者面对镜头讲话为主的短视频（说话人占画面主体） |
| **一镜到底** | 用户的原始素材是一次连续拍摄、单一机位的口播录制（不换镜头） |
| **样例（Sample）** | 用户上传的 5–20s 已剪辑好的"模板来源"视频，系统从中提取风格 |
| **用户素材（User Material）** | 用户自己录制的待应用模板的原始口播视频（短=10–20s 或 长=~3min） |
| **模板（Template）** | KB 中存储的可复用风格配方 = 结构骨架 + 风格规则 + 标签 |
| **骨架（Skeleton）** | 一个 Template 的时间结构 = `Slot` 列表 |
| **Slot（槽位）** | 骨架中的一段，含角色（开头/主体/结尾/…）、时长区间、material_req、风格规则 |
| **Section（主题段）** | 长视频被主题分段后的一段；每个 Section 套一个 Template |
| **IR（Intermediate Representation）** | 中间表示，模板/项目/账本都用 pydantic 结构化表达 |
| **TemplateIR / ProjectIR / TranscriptLedger** | 三大 IR：模板配方 / 实例化时间线 / ASR 时间戳账本 |
| **账本（Ledger）** | WhisperX 词级时间戳的不可变 ASR 单元列表，LLM 操作的唯一真相源（D11） |
| **Tier A / B / C** | 风格保真度分层：A=结构+字幕+缩放+BGM 特征+贴纸（MVP）/ B=蒙版+调色+标题条/ C=任意特效 1:1（不做） |
| **D2 / D3** | 保真度同 Tier A / Tier B 的代号（阶段 1 做 D2，阶段 4 做 D3） |
| **保序** | 时间线上的片段顺序不被打乱（D3 默认约定；Phase 7 是唯一例外） |
| **Patch** | 对 ProjectIR 的结构化编辑操作（NL / 参数面板 / 时间轴 / 重排都产出 Patch） |
| **分步审核（Staged Review）** | 长视频管线在关键决策点暂停等待用户 Accept / Edit / Rerun（D12） |
| **VLM** | Vision-Language Model，视觉大模型（贴纸描述 / 字幕功能 / 标签）|
| **Text LLM** | 纯文本大模型（去重 / 分段 / NL→Patch） |
| **AIGC** | AI 生成内容（贴纸图 / B-roll 视频 / 封面，Phase 5） |

## Context

SceneEcho 解决一个真实痛点：**一镜到底口播视频枯燥，需要字幕动画、缩放推进、贴纸、BGM 卡点、转场这些复杂特效才能留住观众**；创作者能感受到"这条视频的剪辑风格更出效果"却很难把这种风格抽象、复用到自己的素材上。本项目从 5–20s 优质口播样例中提取「**结构骨架 + 视听风格**」模板入知识库；MVP 阶段实现"用户传 10–20s 短口播素材 + 指定一个模板 → 自动套风格出片"；后续阶段扩展到长视频自动拼接、AIGC 补画面、时间轴手动微调。

**自闭环出片，不经过剪映**：Python 后端做分析（ASR / OCR / Demucs / CV / LLM 编排），Node 服务跑 Remotion 渲染叠加层，FFmpeg 处理音视频剪接，最终输出 MP4。

**硬约束**：输入是导出后的 MP4 成片（非剪映工程文件），模板只能靠 CV / ASR / 多模态推断。

---

## 阶段总览

| 阶段 | 名称 | 状态 | 一句话说明 |
|------|------|------|-----------|
| 阶段 0 | 地基与渲染骨架 | 📋 待开始 | 三服务脚手架 + IR codegen + CI；mp4 → Remotion+FFmpeg → 叠字幕的 mp4 跑通 |
| 阶段 1 | 模板提取（D2 范围） | 📋 待开始 | 5–20s 样例 → TemplateIR（切点/字幕/缩放/BGM/贴纸/骨架/标签）→ KB |
| **阶段 2** | **★MVP 应用闭环（短素材+指定模板）** | 📋 待开始 | **10–20s 口播 + 选模板 → ASR + 套风格 → MP4** |
| 阶段 2.5 | NL 编辑 + 参数面板 + 迁移可视化 | 📋 待开始 | 一句话改 IR 重渲染；前端展示抽取→映射→缺口→补全全链路 |
| 阶段 3 | 长视频分步审核闭环 | 📋 待开始 | ~3min 长口播 → 9 step 流水线（含 5 个用户审核暂停点）→ 多 Section 拼接 |
| 阶段 4 | 保真度升级到 D3（Tier B） | 📝 略写 | 转场分类 + 几何蒙版 + 调色匹配 + 标题条 + 音效预设注入 |
| 阶段 5 | AIGC 扩展（生图 + 视频 + 封面） | 📝 略写 | 贴纸生图 + B-roll 视频生成 + 封面生成，均用户主动触发 |
| 阶段 7 | 结构重排与内容优化 | 📝 略写 | 叙事角色识别 + 多版本重排建议 + 代词依赖检测 + 双时间轴对照 + 用户编辑确认 |

> **依赖链**：0 → 1 → 2（★MVP）→ 2.5 → 3 → 7 → 4 → 5。阶段 7 强依赖阶段 3 的分步审核基础设施；初版只依赖阶段 3，但充分体验需要阶段 4（过渡处理）/ 阶段 5（AIGC 补缺口）协同。
> **时间轴拖拽编辑器**已从主路线移出 → `docs/future-plans/001-timeline-editor.md`（保留为远期演进项，触发条件见该文档）。

---

## 架构概览

### 核心原则
- **IR 是地基**：所有模板与剪辑决策落在结构化中间表示（IR）上——IR 是"人 / AI / 渲染器"的共同语言，可解释、可调整、可对话式编辑。NL 编辑、迁移可视化、AIGC 补全都是在同一份 IR 上做读写。
- **闭环优先**：先打通"学样例 → 选模板 → 出片"的最短路径（短素材+指定模板），再叠加长视频自动化、保真升级、AIGC、时间轴。
- **渲染自闭环**：渲染由 Remotion（视频/字幕/贴纸/转场等动画合成）+ FFmpeg（剪接 / 音轨混缩 / 编码）联合完成，输出 MP4；剪映不参与任何环节。

### 全局约定（各阶段必守）
- **D1 输入是 MP4 ⇒ 提取靠推断**：成片是像素、无剪辑元数据；所有模板信息必须从像素/音频/语音转写中重建。
- **D2 模板 ≠ 产物**：模板是 KB 里的可复用配方；产物 = 模板 + 用户素材实例化后的 MP4。
- **D3 默认保序 = 不改时间线顺序**：短素材场景下天然保序；长视频默认 ASR/去重/分段保序。**结构重排是 D3 的唯一例外，仅在 Phase 7 经用户多步审核确认后允许**（见 D12）。
- **D4 保真度分层**：D2（Phase 1：切点/字幕样式含多行/缩放/BGM 特征/贴纸位置+描述）→ D3（Phase 4：转场分类 / 几何蒙版 / 调色匹配 / 标题条 / 音效预设注入）。**字幕多行布局放 D2**（长中文字幕天然需多行）。音效识别 / 高潮位置 / 变速识别 / 画面缩放出框 在 v2.3 砍掉，详见 Phase 4 "已砍项"。
- **D5 骨架"发现"非"预设"**：基础三段（开头/主体/结尾）按位置阈值发现，所有口播必有；其余角色按样例实际出现、开放可扩展；不预设固定清单。
- **D6 选模板用标签 + LLM 重排**：≤50 模板用标签匹配 + LLM 评分足够、可解释；向量检索 = Future。
- **D7 渲染锁 Remotion + FFmpeg**：输出 MP4 自闭环，不依赖任何外部 GUI 编辑器。
- **D8 模板是「可伸缩风格规则集」**：模板编码风格 + 节奏规则，套用时按用户素材实际长度自适应铺开（槽位时长 = {min, nominal, max} 区间）。
- **D9 长视频 = 多主题段 × 模板**：长素材先按主题分段（保序），每个主题段各选一个模板，多段套完按原序拼接。
- **D10 AIGC 用户主动触发**：AI 生图（贴纸）和 AI 生视频（B-roll）**绝不自动启用**；用户通过项目级开关或段级勾选明确授权，且在产物上披露 AI 内容。
- **D11 LLM 决策 ≠ 文本改写**：所有 LLM/VLM 决策（去重/分段/选模板/打标签/NL→patch）都返回**对结构化 id 的指令**，绝不改写 `Unit.text` 或像素内容。**但用户可在审核界面手动校正 `Unit.text`**（修正 WhisperX 误识的品牌名/方言/专有名词），校正后系统自动重跑该 Unit 后续依赖的 step（字幕渲染、强调词识别等）。
- **D12 分步用户审核**：长视频（Phase 3）/ 结构重排（Phase 7）等多步流水线在关键决策点（去静音 / 去重 / 主题分段 / 选模板 / 重排方案）**暂停等待用户 Accept / Edit / Rerun**；中间产物全部持久化到 `projects/{id}/pipeline/`，便于"打回任意 step"而无需从头跑。短素材场景（Phase 2）不走分步审核（一步出活，成本不值）。

### 视频理解技术选型（第一性原理）

**核心判断**：不同提取任务对"时间精度 / 像素精度 / 语义理解深度"需求差异巨大，单一技术统治所有任务是次优的。**hybrid 是唯一合理选择**。

| 任务 | 主技术 | 是否调 VLM | 理由 |
|------|--------|-----------|------|
| 切点检测 | PySceneDetect | ❌ | 帧级精度（±0.04s），VLM 做不到 |
| 字幕 OCR（文本/位置/颜色） | PaddleOCR (`ch_PP-OCRv4`) | ❌ | 像素级 bbox，中文最优 |
| 字幕入场动画类型 | 帧位移启发式 | 模糊时 VLM 兜底 | 滑入/淡入/逐字 用 Y/X 位移和 alpha 曲线判 |
| 字幕功能分类（标题/强调/卖点/CTA） | VLM + ASR 上下文 | ✅ | 纯语义判断 |
| 缩放方向粗判 | VLM 看首/中/末三帧 | ✅ | 推进/拉远/稳定/抖动语义判断 |
| 缩放关键帧曲线（仅非稳定 scene） | OpenCV `goodFeaturesToTrack` + Lucas-Kanade 光流 | ❌ | 时间序列上的 scale 值 |
| BGM 有/无 + BPM + 能量曲线 | Demucs (`htdemucs`) + librosa | ❌ | 信号处理直出 |
| BGM 情绪标签 | librosa 特征 + 规则映射 | 可选 VLM 验证 | 规则可用，需要时 VLM 强化 |
| 贴纸**检测**（位置 + 时机） | VLM 网格抽帧（每 4–6 帧一组） | ✅ | 口播脸部高显著性会污染纯 CV 方案 |
| 贴纸 bbox 精细化 | CV 帧差 + Canny edge（在 VLM 给的区域内） | ❌ | VLM 给粗位置，CV 精化 ±10% |
| 贴纸视觉描述 | VLM on cropped region | ✅ | 纯语义，区域裁图 |
| 骨架三段划分 | 位置阈值（rule） | ❌ | D5 约定 |
| 标签建议（function/scene/notes） | VLM + Text LLM | ✅ | 整体样例采样帧 + ASR → 综合判 |
| 整体提取 sanity check | VLM | ✅ | "这模板和样例一致吗？" 防错 |
| 语音转写（词级时间戳） | WhisperX (`large-v3` zh) + forced align | ❌ | 词级精度 |
| 静音检测 | silero-VAD | ❌ | 信号处理 |
| 重复/口误识别 | Text LLM（id 决策） | ✅（text only） | 文本语义 |
| 主题分段 | Text LLM（id 决策） | ✅（text only） | 文本语义 |
| 转场分类（D3） | 帧序列 pattern + VLM 兜底 | 兜底 ✅ | 大多 classical 能判 |
| 几何蒙版（D3） | OpenCV 分割（或 SAM2）+ VLM 先判有无 | 先判 ✅ | 无蒙版样例直接跳过精分割 |
| 调色 LUT（D3） | 颜色直方图 + 预设库匹配 | ❌ | 不做 1:1，匹配 5–10 个预设 |
| 标题条（D3） | OCR 长矩形检测 + 颜色提取 | ❌ | 口播包装高频元素 |
| 音效预设注入（D3，**非识别**） | 模板手工标注 + FFmpeg 混入 | ❌ | 不从样例学，用户主动配 |

**VLM 调用成本预估**：每个模板提取约 5–8 次 VLM 调用（贴纸描述 N 次 + 字幕功能 N 次 + 标签建议 1 次 + sanity check 1 次），按 Qwen-VL-Max 估算约 ¥0.5–2/模板。可控。

**为什么不"VLM 一把梭"**：
1. 时间戳精度差（VLM 给"大约第几秒"）。
2. 像素位置模糊（"屏幕底部偏右"非归一化坐标）。
3. 同次调用结果可变，KB 一致性差。
4. 完整 video input 成本约 ¥5+/30s，规模化不经济。
5. 失败定位困难，黑盒。

**为什么不"Classical 一把梭"**：贴纸描述、标签语义、字幕功能这些纯语义任务，规则化做不出来。

### 技术栈

| 组件 | 选型 | 引入阶段 |
|------|------|----------|
| Python 后端 | FastAPI + uvicorn + BackgroundTasks | 阶段 0 |
| Node 渲染服务 | Node 18+ / TypeScript / Remotion 4.x / Express | 阶段 0 |
| 前端 | React 18 + TypeScript + Vite + @remotion/player | 阶段 0 |
| 服务通信 | HTTP + JSON IR（pydantic ↔ JSON Schema ↔ zod 三向校验） | 阶段 0 |
| 媒体处理 | FFmpeg 6+ / ffprobe / OpenCV-Python 4.x | 阶段 0 / 1 |
| 分镜切点 | PySceneDetect 0.6+ (`ContentDetector`) | 阶段 1 |
| 字幕识别 | PaddleOCR 2.7+ (`ch_PP-OCRv4_det/rec`) | 阶段 1 |
| BGM 分离 | Demucs 4.x (`htdemucs`) | 阶段 1 |
| 音频特征 | librosa 0.10+ (BPM/RMS/Spectral) | 阶段 1 |
| 贴纸检测 | VLM 网格抽帧 + CV 精化 bbox | 阶段 1 |
| 语音转写 | WhisperX 3.x (`large-v3`, zh) | 阶段 2 |
| 静音检测 | silero-VAD 4.x | 阶段 3 |
| LLM/VLM 客户端 | OpenAI-compatible（统一 endpoint） | 阶段 1 |
| Text LLM 默认 | `claude-opus-4-7`（推理）/ `qwen-plus`（高频） | 阶段 1 / 2 |
| VLM 默认 | `qwen-vl-max-latest`（中文视觉）| 阶段 1 |
| 任务/状态存储 | SQLite + WAL 模式 | 阶段 0 |
| 渲染队列 | p-queue（Node side） | 阶段 0 |
| 日志 | structlog（Python）+ pino（Node） | 阶段 0 |
| IR 类型生成 | datamodel-code-generator + json-schema-to-zod | 阶段 0 |
| Phase 4 蒙版分割（可选） | SAM2 / OpenCV 分割 | 阶段 4 |
| 生图 API | 第三方（接 OpenAI 兼容 image endpoint） | 阶段 5 |
| 视频生成 API | 第三方（Runway/Sora/Kling/即梦，阶段 5 选型） | 阶段 5 |

### 部署架构

- **开发模式**：三服务全跑本地（Python 18521 / Node 8001 / Vite 5173）。`docs/dev-setup.md` 给一键启动脚本（`pnpm dev` 用 concurrently 起三服务 + watch IR codegen）。
- **演示/生产模式**：Python 后端 + Node 渲染服务部署到云 GPU 机器；前端可本地连云后端，也可一并部署。Python ↔ Node 通过内网 HTTP 通信，前端走对外端口；**共享存储用同机器卷或 MinIO**。
- **环境变量**（`.env`）：`RENDERER_URL`、`LLM_BASE_URL`、`LLM_API_KEY`、`MODEL_VLM`、`MODEL_TEXT`、`MODEL_TEXT_CHEAP`、`DATA_ROOT`、`BGM_STRATEGY`(features|original)、`ENABLE_CLI_INGEST`(dev only)。

### 跨服务契约

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Browser (Frontend, React+Vite)                  │
│                  pages/{SampleExtract, Library, Editor, ...}        │
│                  RemotionPlayer ◀──── 实时预览（不渲染像素）           │
└──────────────────┬────────────────────────────────────┬─────────────┘
                   │ HTTP /api/*                        │ Static files
                   │ JSON (ProjectIR/TemplateIR/Patch)  │ (rendered mp4)
                   ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Python Backend (FastAPI, :18521)                    │
│   api/{samples, templates, projects, edit, pipeline, reorder, tasks}│
│   extract/   understand/   apply/   kb/   agent/   llm/             │
│   render/client.py ──HTTP /render──┐                                │
│                                    │           │ ffmpeg local       │
│                                    │           ▼ (normalize/mix)    │
│                                    │     ┌────────────────┐         │
│                                    │     │  FFmpeg CLI    │         │
│                                    │     └────────────────┘         │
└────────────────────────────────────┼────────────────────────────────┘
                                     │ HTTP POST /render
                                     │ JSON (ProjectIR)
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Node Renderer Service (Express+Remotion, :8001)        │
│   server.ts → p-queue(1) → render.ts → Headless Chromium → mp4      │
│   onProgress ──webhook──▶ Python /internal/task-progress            │
└─────────────────────────────────────────────────────────────────────┘

外部依赖（按需调）：
- LLM/VLM API（OpenAI-compatible endpoint）
- 生图 API / 视频生成 API（Phase 5）

共享存储：所有服务读写 DATA_ROOT（本地共享卷 / 云上 MinIO bucket）
```

**文件路径约定**
- 所有服务以 `DATA_ROOT` 作为根（默认 `backend/data/`）。
- 跨服务传文件用**相对 `DATA_ROOT` 的路径**（如 `projects/p001/normalized.mp4`），不传绝对路径。
- 部署时两服务共享同一物理卷或挂载同一 MinIO bucket。
- 输出文件命名 `{project_id}/outputs/render_{ts}.mp4`，便于回溯。

**IR 类型三向同步**
- pydantic 模型为唯一真相源（`backend/app/ir/`）。
- 通过 `scripts/gen_schema.py` 导出 JSON Schema → `shared/ir.schema.json`。
- `renderer/scripts/gen-types.ts` 和 `frontend/scripts/gen-types.ts` 用 `json-schema-to-zod` 生成 `types/ir.ts`（zod schema + 推导 TS 类型）。
- Node 在 `/render` 处用 zod 校验请求体；Frontend 在 API 调用边界用 TS 类型。
- **CI 检查**：每次 PR 跑 `pnpm run gen:types && git diff --exit-code`，schema 与生成文件不一致则红。

**异步任务与进度上报**
- 长任务（extract/apply/render/aigc）走 FastAPI `BackgroundTasks`；任务态写 `data/kb.sqlite` 的 `tasks` 表（`id, kind, status, progress, stage, result_json, error, created_at, updated_at`）。
- 前端 `GET /tasks/{id}` 轮询（阶段 0 选轮询，简单）；阶段 4 后如需要实时升级到 SSE。
- 渲染端收到 `/render` 后用 Remotion 的 `onProgress` callback，每 5% 回调 Python `POST /internal/task-progress` 更新 `tasks.progress`。

**错误处理与降级**
- Python ↔ Node：HTTP 错误返 JSON `{code, message, retry_safe: bool}`；Python 按 `retry_safe=true` 自动重试一次。
- LLM/VLM/AIGC 限流/超时：指数退避 3 次；最终失败标 Gap 为"待补全"而非 crash。
- ASR 低置信（WhisperX 平均 logprob < -0.6）：标记该段，UI 提示"需校对"。
- OCR 无字幕识别但骨架推断有字幕：标记并 fallback 到无字幕骨架。
- 渲染失败：保留 ProjectIR 与中间产物（`projects/{id}/outputs/intermediates/`），日志写明失败 step；前端展示"渲染失败，点击重试"。
- 渲染服务不可达：Python 启动时 `GET {RENDERER_URL}/health` 探活；挂掉则首页 banner 提示。

**渲染队列与并发**
- MVP 单 worker：Node 用 `p-queue({concurrency:1})` 串行处理 `/render`，避免 Headless Chromium 多实例打架。
- 队列态 `GET /render/queue` 返回 `{pending, running_task}`；前端 Editor 显示"前面有 N 个任务"。
- 多 worker 并发 = Phase 3 后再考虑（需要资源隔离）。

**编解码与格式归一化**
- 入：接受任意 mp4/mov/webm；FFmpeg 首步统一转 H.264 baseline + AAC + 30fps + yuv420p + 1080×1920（默认 9:16）→ 存 `{kind}/{id}/normalized.mp4`，后续处理基于归一化版。
- 出：H.264 + AAC + 30fps + yuv420p + faststart（兼容剪映/抖音/微信视频号）。
- canvas 不匹配处理：模板 9:16、用户素材 16:9 → "contain" 策略 letterbox + 模糊背景（FFmpeg `pad` + `boxblur`）。模板/素材都用 16:9 则直接渲染。

### 素材目录结构与生命周期

```
data/                              # 由 DATA_ROOT 指向，gitignore
├─ system/                         # 系统资源（仓库 fixtures 或一次性准备）
│  ├─ bgm_pool/                    # 免版权 BGM 库
│  │  ├─ {track_id}.mp3
│  │  └─ bgm_index.json            # {id, bpm, energy, mood, duration, license}
│  ├─ fonts/                       # 中文字体
│  │  ├─ NotoSansSC-{weight}.otf
│  │  ├─ SourceHanSans-{weight}.otf
│  │  └─ fonts_index.json          # family → file 映射
│  ├─ stickers_reference/          # 用户提供的贴纸参考图（可选）
│  └─ models/                      # ML 模型缓存
│     ├─ whisperx/
│     ├─ paddleocr/
│     └─ demucs/
├─ samples/                        # 提取模板的样例（输入）
│  └─ {sample_id}/
│     ├─ source.mp4                # 原始上传
│     ├─ normalized.mp4            # FFmpeg 归一化版
│     ├─ thumbnail.jpg             # 首帧
│     └─ extracted/                # 中间产物
│        ├─ scenes.json
│        ├─ captions.json
│        ├─ stickers_crops/        # 贴纸区域裁图
│        ├─ bgm_stem.wav           # Demucs 分离的 BGM
│        └─ extract.log
├─ projects/                       # 用户项目（输入+输出）
│  └─ {project_id}/
│     ├─ user_material.mp4
│     ├─ normalized.mp4
│     ├─ project.json              # 当前 ProjectIR
│     ├─ patch_history.jsonl       # NL 编辑 + 分步审核 + 重排 编辑历史
│     ├─ pipeline/                 # 长视频分步审核中间产物（Phase 3+）
│     │  ├─ 01_ledger.json
│     │  ├─ 02_vad.json
│     │  ├─ 03_dedup.json
│     │  ├─ 04_sections.json
│     │  ├─ 05_template_assignments.json
│     │  ├─ 06_reorder_plans.json  # Phase 7 启用时填，否则 identity
│     │  ├─ 07_project_ir.json
│     │  ├─ 08_quality.json        # Quality scoring 结果
│     │  └─ pipeline_state.json
│     └─ outputs/
│        ├─ render_{ts}.mp4
│        └─ intermediates/         # 渲染失败时保留
├─ aigc/                           # AIGC 产物（全局复用）
│  ├─ stickers/                    # 按 description hash 缓存
│  │  └─ {hash}.png
│  └─ broll/                       # 按 prompt+style hash 缓存
│     └─ {hash}.mp4
├─ kb.sqlite                       # 知识库 + tasks 表
└─ logs/                           # JSON 日志
```

**素材生命周期**
- `samples/{id}/source.mp4`：保留 90 天（用户可在 UI 删）。
- `samples/{id}/extracted/`：保留 30 天，可重跑。
- `projects/{id}/`：保留 90 天。
- `projects/{id}/outputs/intermediates/`：渲染成功即删；失败保留 7 天供调试。
- `aigc/`：永久（生成成本高）。
- 后台 cron（FastAPI 启动时 `apscheduler` schedule）每天扫一次。

**素材入口（上传方式）**
- **UI 上传**（生产/演示主路径）：`POST /samples` / `POST /projects` 接收 multipart → 写 `{kind}/{id}/source.mp4`。
- **CLI ingest**（开发/测试路径，`ENABLE_CLI_INGEST=true` 时启用）：
  ```bash
  python -m app.cli ingest-sample /local/path.mp4 [--name xxx]
  python -m app.cli ingest-project /local/path.mp4 [--name xxx]
  ```
  内部走"拷贝到 `{kind}/{generated_id}/source.mp4`"的相同流程，避免直接接受任意路径的安全风险。

**用户提供的资源放置约定**
- **5–20s 样例视频**（3–5 条）：用 CLI `ingest-sample` 入 `samples/`，或 UI 上传。
- **10–20s 用户口播短素材**（2–3 条）：用 CLI `ingest-project` 入 `projects/`，或 UI 上传。
- **~3min 长口播**（1–2 条）：阶段 3 才用，先放 `system/test_fixtures/long/`。
- **贴纸/字幕参考图**：放 `system/stickers_reference/`，命名 `{category}_{n}.png`（如 `arrow_red_01.png`）。VLM 描述时可参考此库做匹配增强。
- **BGM 音源**：放 `system/bgm_pool/`，命名 `{mood}_{bpm}_{id}.mp3`（如 `energetic_128_01.mp3`）。同时维护 `bgm_index.json`。

### 项目结构

```
SceneEcho/
├─ docs/{PLAN.md, dev-setup.md, decisions/, future-plans/, 003ISSUES.md}
├─ .github/workflows/{ci.yml, release.yml}
├─ shared/
│  └─ ir.schema.json                # pydantic 导出的 JSON Schema
├─ scripts/
│  └─ gen_schema.py                 # pydantic → JSON Schema
├─ backend/                         # Python FastAPI
│  ├─ pyproject.toml
│  ├─ ruff.toml
│  ├─ .venv/                        # gitignore
│  └─ app/
│     ├─ main.py                    # FastAPI 入口
│     ├─ config.py                  # 环境变量加载
│     ├─ cli.py                     # ingest 命令（dev only）
│     ├─ api/{samples, templates, projects, edit, tasks, pipeline, reorder}.py
│     ├─ ir/{template.py, project.py, ledger.py, patch.py, pipeline.py, narrative.py, export.py}
│     ├─ extract/{scenes, motion, captions, audio, stickers, skeleton, normalize, pipeline}.py
│     │                              # Phase 4 增: title_bar.py, color.py, masks.py
│     ├─ understand/{asr, vad, dedup, segment, vision}.py
│     ├─ apply/{mapping, gaps, fill, style, pipeline, long_pipeline, pipeline_state, quality}.py
│     ├─ render/{client.py, ffmpeg.py}
│     ├─ kb/{store, tagging, select, recommend}.py
│     ├─ agent/{tools, orchestrator, nl_edit, aigc, narrative, render_queue}.py
│     │                              # Phase 4 增: sfx_preset.py
│     ├─ llm/{client.py, prompts/}  # OpenAI-compatible 统一客户端
│     └─ logging.py                 # structlog 配置
│  └─ tests/{unit/, integration/, fixtures/, conftest.py}
├─ renderer/                        # Node Remotion 服务
│  ├─ package.json
│  ├─ tsconfig.json
│  ├─ scripts/gen-types.ts
│  └─ src/
│     ├─ server.ts                  # Express HTTP 入口
│     ├─ render.ts                  # bundle + renderMedia
│     ├─ queue.ts                   # p-queue
│     ├─ progress.ts                # 回调 Python
│     ├─ logger.ts                  # pino
│     ├─ types/ir.ts                # generated from JSON Schema
│     └─ compositions/
│        ├─ Project.tsx
│        ├─ Caption.tsx
│        ├─ ZoomLayer.tsx
│        ├─ Sticker.tsx
│        ├─ TitleBar.tsx            # Phase 4
│        ├─ Transition.tsx          # Phase 4
│        ├─ ColorLayer.tsx          # Phase 4
│        └─ Mask.tsx                # Phase 4
├─ frontend/                        # React + Vite
│  ├─ package.json
│  ├─ vite.config.ts
│  ├─ scripts/gen-types.ts
│  └─ src/
│     ├─ api/index.ts
│     ├─ types/ir.ts                # generated from JSON Schema
│     ├─ pages/{SampleExtract, TemplateLibrary, Editor, LongVideoEditor, Visualize}.tsx
│     ├─ components/{RemotionPlayer, ParamPanel, NLBar, TaskProgress}.tsx
│     │                              # Phase 3 增: StepVADReview, StepDedupReview, StepSegmentReview,
│     │                              # StepSelectReview, StepReorderReview, StepFinalReview
│     └─ state/                     # Zustand stores
├─ pnpm-workspace.yaml              # 管理 renderer + frontend
├─ .gitignore
├─ .env.example
└─ README.md
```

### 总体数据流
```
[样例 mp4] ──extract──▶ TemplateIR ──▶ 知识库 KB（带标签）
                                              │ 用户指定 template_id（阶段 2）
                                              │ 自动 select（阶段 3）
[用户口播素材] ──understand──▶ 账本 ──┐         │
                                     ▼         ▼
            apply: 映射 + 缺口识别 + 缺口补全 + 套风格
                                              ▼
                       ProjectIR（保序 EDL + Caption 列表）
                                              │ render.client
                                              ▼
                              Node Remotion 服务 + FFmpeg
                                              ▼
                                          MP4 产物
   [自然语言指令 / 参数面板修改] ──agent.nl_edit──▶ Patch ──▶ 重渲染
   [用户勾选 AI 补画面] ──agent.aigc──▶ 调外部 API ──▶ 替换素材
```

### 关键机制

#### 账本机制（项目最 novel 的设计）

**核心**：用 WhisperX 词级强制对齐生成不可变的 `TranscriptLedger`（账本），每个 `Unit` 带稳定 id 和精确 `start/end`。所有 LLM/VLM 决策（去重 / 分段 / NL 编辑）**只返回对 id 的指令**，绝不改写 text。

**为什么这么设计**——用一个反例说明：

如果让 LLM 直接"重写转写文本"（常规做法），会发生：
1. LLM 把"嗯啊那个"删了 → 但删除位置无法映回原视频时间戳 → 字幕错位
2. LLM 把"我们的产品很好"改成"产品超棒" → 文本变了但音频没变 → 字幕和语音对不上
3. NL 编辑"删第二段"→ LLM 返回新文本 → 系统不知道这对应原始视频的哪段时间
4. 多轮编辑后，文本和原音频的对应关系彻底丢失，无法回滚

**账本机制下**：
- LLM 输入：`[{id:1,text:"...",start:0.0,end:1.2},{id:2,...}]`
- LLM 输出：`{"keep":[1,3,5],"drop":[{"id":2,"dup_of":1},{"id":4,"reason":"口误"}]}`
- 系统按 id 映回时间戳 → 知道精确从哪一秒切到哪一秒
- 字幕直接复用 `Unit.text`，永远和音频对齐
- 回滚 = 撤销对 id 的决策，文本本体永不变

这个设计一次解决三件事：**字幕帧级同步、切点落词句边界、NL 编辑精确定位**。

（人工校正入口：D11 允许用户在审核界面手动改 `Unit.text` 修正 WhisperX 误识，但 AI 不行。）

#### 提取流水线（Phase 1，D2 范围）

```
FFmpeg 归一化
  → 切点（PySceneDetect）
  → 缩放（VLM 粗判方向 + CV 在有缩放镜头里算 scale 曲线）
  → 字幕样式/时机/动画（PaddleOCR + 跨帧追踪 + anim_in 推断 + 多行检测）
  → BGM（Demucs 分离 → BPM/energy/mood，可选保留 BGM stem）
  → 贴纸（VLM 网格抽帧识别 + CV 精细化 bbox + 跨帧追踪）
  → 骨架发现（位置阈值 0–30%/30–70%/70–100%）
  → 字幕功能分类（VLM）
  → 标签建议（VLM + Text LLM）
  → sanity check（VLM）
  → 入 KB
```

#### 应用流水线

**短素材（Phase 2 MVP）**：
```
FFmpeg 归一化 → WhisperX → 账本
  → 映射到模板槽位（保序 + 时长自适应）
  → 缺口识别 → 缺口补全（文案/包装/素材复用三法不重排）
  → 套风格 → ProjectIR → 渲染
```

**长视频（Phase 3，分步审核）**：
```
FFmpeg 归一化 → WhisperX → 账本
  → [Step02] VAD 去静音 + 用户标记删除（审核）
  → [Step03] LLM 去重（审核）
  → [Step04] LLM 主题分段（审核，保序）
  → [Step05] 逐 Section 选模板（审核）
  → [Step06] 重排建议（Phase 7，opt-in 时启用）
  → [Step07] 逐 Section 映射 + 缺口 + 补全 + 套风格 → ProjectIR
  → [Step08] Quality scoring 检查点
  → [Step09] 渲染
```

#### 时长自适应（D8）

槽位时长 `{min, nominal, max}`。
- 用户段比槽位长 → 裁切 / 轻微变速（≤±20%）/ 拆成多片填多个槽
- 比槽位短 → 在区间内拉伸 / 素材复用兜底
- 无用户片段满足 → 走缺口补全

**注**：变速主要用于应用端的素材填充自适应，不用于提取端学样例的变速规则（已从 Phase 4 砍掉）。

#### 缺口识别与补全

槽位 `material_req` 无用户片段满足 = 缺口。MVP 三法（均不改顺序）：
1. **文案补全**：LLM 生成补充字幕，标 `is_fill=true`
2. **包装补全**：标题条 / 卖点卡片 / 贴纸占位
3. **素材复用**：裁取相邻片段局部放大 / 重复

AIGC 补 B-roll 走 Phase 5，**仅在用户授权时**触发（D10）；结构重排走 Phase 7（D12）。

#### NL 编辑（NL → Patch）

Text LLM 把指令翻成对 IR 的结构化 Patch 列表（具体 op 见数据结构 Patch 定义）→ 应用 → 重渲染；维护 patch 历史（`patch_history.jsonl`）支持回滚。

**参数面板修改与 NL 编辑产出同样的 Patch**，二者经同一路径落入 ProjectIR，前端 Player 实时反映。Phase 3 分步审核每 step 的 Edit 操作也产出 Patch，三者共用 history。

#### AIGC 触发（D10）

| 类型 | 触发点 | UX |
|------|--------|-----|
| **贴纸生图** | TemplateLibrary 模板详情页"为该模板生成所有贴纸"按钮 | 批量调 `generate_sticker(description)`，按 hash 缓存到 `data/aigc/stickers/` |
| **B-roll 项目级** | Editor 页 apply 前勾选"允许 AI 补画面" | 写 `ProjectIR.allow_aigc_broll`；apply 时缺口走 AIGC 补全（`fill_strategy="aigc_broll"`） |
| **B-roll 段级** | apply 后某 PlacedSegment 右键"AI 生成画面" | prompt 从 Unit.text + 模板风格生成 → 写 `aigc_broll_path` → 重渲染 |
| **封面生成** | 项目完成后"生成封面"按钮 | LLM 生成文案 + 生图 API 出封面图（Phase 5） |

所有路径都需用户显式确认；产物 mp4 元数据标注 AIGC 段时长占比。

#### BGM 策略（可配置）

| 策略 | 行为 | 适用场景 |
|------|------|---------|
| `BGM_STRATEGY=features`（默认） | 提取 BPM/能量/情绪 → 套用时按 `bgm_index.json` 选近似曲 | 安全可发布 |
| `BGM_STRATEGY=original` | 保留 Demucs 分离的 BGM stem，套用时 FFmpeg 拼回 | 仅个人使用，UI 红字提示版权风险 |

**纯音乐 BGM 判定**：vocals stem RMS < 阈值 → `is_instrumental=true`，渲染时无需 ducking。

#### Agent 工具协议

每个能力注册为 tool，IO schema 即工具协议（写入交付文档）：

```
extract_template(media_path)       → TemplateIR
transcribe(media_path)             → TranscriptLedger
dedup(ledger)                      → {keep_ids, drop_pairs}
segment_topics(ledger)             → list[Section]
select_template(section, kb)       → {top1, candidates}
recommend_templates(material, kb)  → list[{template_id, reason}]   # B1 新增
detect_gaps(section, template)     → list[Gap]
fill_gap(gap, strategy)            → fill_result
apply_short(media, template_id)    → ProjectIR
apply_long(media, kb)              → PipelineState
render_project(project_ir)         → mp4_path
nl_edit(project_ir, instruction)   → list[Patch]
narrative_analyze(sections, ledger) → {scores, deps, plans}
quality_score(project_ir)          → list[QualityIssue]            # C3 新增
generate_sticker(description)      → image_path
generate_broll(prompt, duration)   → video_path
generate_cover(project_ir, ledger, style_hint) → image_path        # C1 新增
```

#### 鲁棒性边界

| 失败场景 | 降级策略 |
|---------|---------|
| 无标签匹配 | fallback 最通用模板或标记待人工选 |
| ASR 低置信 | 标记段，提供人工校正入口（D11） |
| 素材几乎全废 | 明确提示而非硬生成 |
| 渲染服务不可达 | 后端报错并保留 IR 供下次重试 |
| AIGC API 失败 | 降级到占位符并提示用户 |
| VLM 返回非 JSON | 重试 + Pydantic 校验失败则记日志、走 fallback |
| 重排打破强依赖 | Phase 7 自动 fallback 到 baseline |

### 分步审核管线（Staged Review Pipeline）

长视频与结构重排涉及多个 LLM 决策点，每点都可能出错。一次性跑完整管线、问题暴露在最终成片才被发现，回退代价巨大。本架构把管线拆成显式 step，每 step 在关键决策处暂停等待用户审核。

**核心机制**
- 每 step 输出持久化到 `projects/{id}/pipeline/{step_no:02d}_{name}.json`（两位补零，如 `01_ledger.json`、`08_quality.json`）；唯独 Step 09 render 产物落 `projects/{id}/outputs/render_{ts}.mp4` 与 `pipeline_state.json` 中 `output_path` 字段挂钩。
- `pipeline_states` 表（SQLite）记录每个 step 状态：`pending / running / awaiting_review / approved / rejected / replaying`。
- 后端按 step 顺序推进；遇到 `awaiting_review` 暂停并返回"等待用户决策"。
- 前端 Stepper UI 展示步骤进度条；每 step 对应专属 review 组件；用户决策后 POST 推进。

**Step 流（Phase 3 长视频 + Phase 7 重排，共 9 step）**

| Step | 名称 | 自动/审核 | 用户可做的操作 |
|------|------|----------|-------------|
| 01 | ASR → 账本 | 自动 | （不暂停） |
| 02 | VAD 去静音 | 审核 | 看去掉的静音段，可恢复个别段 + **手动标记跳过段（C2）** |
| 03 | LLM 去重 | 审核 | 看 drop 列表，可保留个别"重复"段 |
| 04 | LLM 主题分段 | 审核 | 看 Section 边界，可合并 / 拆分 / 重命名 |
| 05 | 选模板 per Section | 审核 | 看每段选用的模板；NL 改"第 3 段换模板 B"或表单替换；支持句级覆盖（用户特例） |
| 06 | 重排建议（Phase 7） | 审核（**仅项目初始化勾选启用时执行**） | 看 N 个版本，选一个或自定义；**保序也是合法选择**；可直接 skip |
| 07 | 应用模板 + 缺口补全 + 套风格 | 自动 | （不暂停，可在 Player 预览） |
| 08 | Quality scoring | 条件审核（仅有 error 时暂停） | 看节奏/字幕密度/BGM-人声比/总时长/缺口数 warning |
| 09 | 最终渲染 | 自动 | 出 MP4 |

**Step 流（Phase 2 短素材）**：不走分步审核，直接 apply → Player 预览 → NL 编辑 → 渲染（沿用现有设计）。

**操作语义**
- **Accept**：保存当前 step 输出 → 推进下一 step
- **Edit**：在该 step 的 review UI 内修改产出（如调 Section 边界 / 替换模板）→ 保存 → 推进
- **Rerun**：触发该 step 重跑（可换 seed / 换 prompt / 换模型）→ 重新等待审核
- **Rollback to Step N**：废弃 N 之后的所有产出 → 从 N 重新开始

**前端 Stepper UI**
- 顶部：step 进度条（已完成 / 当前 / 待执行）
- 中央：动态 review 区，根据 step 渲染专属 UI（去静音列表 / dedup 列表 / Section 时间轴 / 模板分配表 / 重排版本对比 / Player 预览）
- 底部：Accept / Edit / Rerun 三按钮 + 累计 LLM 成本
- 侧边：step 历史，可点击跳回任意 step（确认后会重跑其后所有 step）

**性能与成本**
- 每 step 产物缓存复用：rerun step N 只重跑 N，已通过的 N-1 不动。
- LLM/VLM 调用 token 数累计到 `pipeline_states.llm_cost`，UI 显示成本。
- Phase 3 完整跑（无 rerun）预计 LLM 调用 5–8 次；Phase 7 额外 2–3 次。

**与 NL 编辑（Phase 2.5）的关系**
- Phase 2.5 NL 编辑作用于已生成的 ProjectIR（产物后微调）
- 分步审核作用于 pipeline 中间产物（决策点修正）
- 二者共用 Patch 数据结构与 history，编辑产生的 patch 可统一回放

### 测试 / 可观测性 / CI 策略

**测试分层**
- 单测（`backend/tests/unit/`、`renderer/tests/unit/`）：纯函数、IR 转换、LLM/VLM prompt 输出结构（mock）。
- 集测（`backend/tests/integration/`）：真实模型跑 fixture 视频；指标退步 > 5% 阻塞合并。
- 端到端（`tests/e2e/`，Playwright）：浏览器走完上传 → 提取 → 应用 → 渲染 → 下载全流程。Phase 2 后引入。

**指标基线**（写入 `tests/baselines.json`，CI 比对）
- 阶段 1：切点 F1 / 字幕首现时刻误差 / 字幕位置 IoU / 骨架三段命中率 / BGM 有无判定。
- 阶段 2：字幕同步误差 median / 渲染耗时 / 时长自适应正确率。
- 阶段 4：D3 各项指标。

**日志与可观测性**
- Python：`structlog` JSON 输出，每条带 `task_id, stage, kind`；本地 stdout、prod 落 `data/logs/{date}.jsonl`。
- Node：`pino` JSON 同结构。
- 性能：每个 stage 耗时记 `tasks` 表的 `stage_timings` JSON 字段，可统计 P50/P99。
- 错误：未捕获异常落 `data/logs/errors.jsonl` 并写 task.error。

**CI 流水线**（`.github/workflows/ci.yml`）
```yaml
on: [pull_request, push to main]
jobs:
  type-sync:
    - python scripts/gen_schema.py
    - pnpm -F renderer gen:types
    - pnpm -F frontend gen:types
    - git diff --exit-code  # 三处类型必须保持同步，否则红
  python:
    - ruff check backend/
    - ruff format --check backend/
    - pytest backend/tests/unit/ -v
  node-renderer:
    - pnpm -F renderer typecheck
    - pnpm -F renderer test
  frontend:
    - pnpm -F frontend typecheck
    - pnpm -F frontend build
    - pnpm -F frontend test
  integration:
    runs-on: self-hosted  # 需 GPU；MVP 可用 CPU but slow
    - pytest backend/tests/integration/ --baseline tests/baselines.json
```

**Fixtures 清单**（按阶段准备，用户提供）
- `samples/sample_basic_15s/`：含字幕 + BGM + 1 处缩放（必备）
- `samples/sample_with_sticker_12s/`：含 1 个明显贴纸（阶段 1 测）
- `samples/sample_fast_pace_8s/`：3+ 切点的快节奏（阶段 1 测节奏）
- `samples/sample_no_bgm_10s/`：无 BGM（阶段 1 测判定）
- `projects/test_short_15s/`：10–20s 一镜到底口播（阶段 2 测）
- `projects/test_short_complex_18s/`：含多句 + 1 处口误（阶段 2 测）
- `system/test_fixtures/long_3min/`：~3min 多主题 + 口误（阶段 3 测）
- `system/bgm_pool/*.mp3`：5+ 首不同 BPM/mood 免版权曲（阶段 2 用）
- `system/stickers_reference/`：参考贴纸（可选，阶段 1 增强 VLM 描述）

---

## 核心数据结构

### TranscriptLedger（账本——时间戳唯一真相源）
```python
class Unit(BaseModel):
    id: int            # 稳定不变，不可复用
    text: str          # 不可被 LLM 改写
    start: float       # 秒，WhisperX 词级强制对齐
    end: float
    avg_logprob: float = 0.0   # ASR 置信度，< -0.6 视为低置信

class TranscriptLedger(BaseModel):
    units: list[Unit]
    language: str = "zh"   # WhisperX 检测/指定
    media_path: str        # 相对 DATA_ROOT
```

### TemplateIR（模板 = 结构骨架 + 风格规则 + 标签）
```python
SlotRole = str   # 开放枚举，从样例发现；基础三段: 开头|主体|结尾

class CaptionStyle(BaseModel):
    font_family: str               # 字体 family 名（映射到 data/system/fonts/）
    size: int                      # 像素
    color: str                     # #RRGGBB
    stroke_color: str | None = None
    stroke_width: int = 0
    position: tuple[float, float]  # 归一化坐标 (0~1)
    layout: str = "single"         # single | multi（D2 支持多行）
    max_chars_per_line: int = 12   # D2 多行布局参数
    anim_in: str                   # 逐字弹入|整句滑入|淡入|打字机|unknown
    anim_emphasis: str | None      # 关键词高亮|抖动|放大|None
    emphasis_words: list[str] = [] # VLM 识别出的强调词

class ZoomKeyframe(BaseModel):
    relative_time: float   # 0~1 相对槽位时长
    scale: float           # >1 推进，<1 拉远

class VisualStyle(BaseModel):
    zoom_keyframes: list[ZoomKeyframe] = []
    mask: str | None = None          # D3 (Phase 4)
    color_lut: str | None = None     # D3 (Phase 4 - 预设库 ID，不做 1:1 LUT 提取)
    title_bar: bool = False          # D3 (Phase 4)
    # speed_curve 提取端不填（变速识别在 v2.3 砍掉）；应用端 D8 时长自适应直接写 PlacedSegment.speed

class AudioStyle(BaseModel):
    has_bgm: bool = False
    is_instrumental: bool = True     # vocals stem 静默 → 纯音乐
    bpm: float | None = None
    energy_curve: list[float] = []   # 每秒能量值
    mood_tag: str | None = None      # 欢快|紧张|舒缓|严肃|...
    bgm_path: str | None = None      # original 策略时填，相对 DATA_ROOT
    bgm_features: dict | None = None # features 策略时填，用于库匹配

class StickerEvent(BaseModel):
    description: str                 # VLM 描述（"红色感叹号图标"）
    position: tuple[float, float]    # 归一化坐标
    size: tuple[float, float]
    start: float; end: float         # 相对槽位时长 0~1
    generated_image: str | None = None  # Phase 5 生图后填

class StyleRule(BaseModel):
    caption: CaptionStyle | None
    visual: VisualStyle
    audio: AudioStyle
    stickers: list[StickerEvent] = []
    rhythm: dict          # {cut_interval_mean, cut_interval_std, beat_align}
    transition_in: str | None = None    # D3
    transition_out: str | None = None

class Slot(BaseModel):
    role: SlotRole
    duration: dict        # {min, nominal, max}（秒，D8）
    material_req: str     # 人物口播|B-roll|文字卡|...
    style: StyleRule
    caption_function: str = "regular"  # Slot 内主流字幕功能（按出现频率投票自 vision.classify_caption_function 的多个 CaptionEvent 结果）：标题|强调|卖点|CTA|regular。简化为单值；样例内一个 Slot 多字幕功能并存的情况按主流取，剩余只走 StyleRule.caption 的通用样式。

class Tags(BaseModel):
    position: str    # 开头|中间|结尾
    function: str    # 开头引入|逻辑讲述|关键词强调|过渡|结尾收束|罗列要点|细节强调
    scene: str       # 纯口播|讲解|产品展示|...
    notes: str       # 一句人话，人工可覆盖

class TemplateIR(BaseModel):
    id: str; name: str; source_sample: str   # source_sample 相对 DATA_ROOT
    skeleton: list[Slot]
    global_style: dict   # canvas {width, height, fps} / 全局 BGM 策略 / 默认调色
    tags: Tags
    sanity_check: dict | None = None  # VLM 输出 {pass: bool, notes: str}
    created_at: str
```

### ProjectIR / EDL（实例化时间线）
```python
class PlacedSegment(BaseModel):
    slot_role: SlotRole
    source_unit_ids: list[int]          # 引用账本（保序依据）
    src_timerange: tuple[float, float]  # 取用户素材的哪段（秒）
    timeline_start: float               # 在输出时间轴的位置
    speed: float = 1.0                  # 时长自适应的变速系数
    applied_style: StyleRule
    is_fill: bool = False               # True = 缺口补全
    use_aigc_broll: bool = False        # 用户已勾选 AI 补画面
    aigc_broll_path: str | None = None  # Phase 5 调 API 后填

class Caption(BaseModel):
    text: str
    start: float; end: float            # 来自账本，精确
    style: CaptionStyle

class Gap(BaseModel):
    slot_role: SlotRole
    reason: str
    fill_strategy: str    # 文案|包装|素材复用|aigc_broll
    fill_result: str

class Section(BaseModel):
    topic: str
    template_id: str
    segments: list[PlacedSegment]     # 段内保序
    gaps: list[Gap]

class ProjectIR(BaseModel):
    project_id: str
    user_material: str                # 相对 DATA_ROOT
    sections: list[Section]           # 按原时间线顺序；MVP len=1
    captions: list[Caption]
    canvas: dict                      # {width, height, fps}
    allow_aigc_broll: bool = False    # 项目级 AIGC 开关
    bgm_track: str | None = None      # 最终选用的 BGM 路径
    version: int = 1                  # 用于 NL 编辑乐观锁
```

### Patch（NL 编辑 / 参数面板的统一操作）
```python
class Patch(BaseModel):
    op: Literal[
        # 字幕/视觉/节奏（Phase 2.5）
        "set_caption_style",      # 改字幕样式（颜色/字体/位置/动画）
        "set_visual_style",       # 改缩放幅度/调色
        "adjust_rhythm",          # 整体节奏快慢
        "set_emphasis",           # 改强调词
        # 段/模板（Phase 2.5 / Phase 3）
        "swap_template",          # 替换某 Section 模板
        "delete_segment",         # 删段（短素材场景）
        "set_canvas",             # 改输出比例
        "set_bgm",                # 改 BGM
        # AIGC（Phase 5）
        "mark_aigc",              # 标记某段允许 AIGC（不立即执行）
        # 分步审核（Phase 3）
        "manual_drop",            # C2 用户标记跳过 Unit（Step 02 review 产出）
        "restore_vad_segment",    # Step 02 恢复静音段
        "keep_dup",               # Step 03 保留某重复段
        "merge_sections",         # Step 04 合并 Section
        "split_section",          # Step 04 拆分 Section
        "rename_section",         # Step 04 重命名 Section
        "override_unit_text",     # D11 用户手工校正 Unit.text
        # 重排（Phase 7）
        "reorder_sections",       # 重排（value={new_order: [section_id...]}）
    ]
    target: dict      # {section_idx, segment_idx, unit_id, step_no, ...} 视 op 而定
    value: dict       # op 对应的参数
    source: str       # "nl" | "panel" | "review" | "timeline"（来源追踪）
    timestamp: str
    pipeline_step: int | None = None  # 来自哪个 step（来自分步审核时填）
```

---

## 阶段 0: 地基与渲染骨架 📋

### 前置条件
1. **Python 版本**：阶段 0 可暂用 3.13（仅 FastAPI/pydantic）；**进阶段 1 前必须新建 3.11 或 3.12 venv**（ML 库对 3.13 适配滞后）。
2. **Node 版本**：18+（Remotion 4.x 要求）。
3. **pnpm**：8+（管理 renderer + frontend 工作区）。
4. **FFmpeg**：6+ 系统级安装+加入 PATH，`ffprobe -version` 可运行。
5. **测试素材**：至少准备 `tests/fixtures/sample_basic_15s/source.mp4`（5–20s 任意视频）和 `tests/fixtures/short_15s/source.mp4`（10–20s 任意视频）；其他 fixtures 按需补。
6. **LLM Provider**：OpenAI-compatible endpoint + key → `.env`，阶段 1 真正引入。
7. **环境变量** `.env.example` 提交仓库，实际 `.env` 不提交。
8. **GitHub 仓库**：阶段 0 完成时推首版，CI 跑起来。

### 目标
一段 mp4 走完 Python→Node→FFmpeg 全链路出一段叠加固定字幕的 mp4；三服务脚手架就绪；IR 类型三向同步管线（pydantic ↔ JSON Schema ↔ zod ↔ TS）工作；CI 流水线绿灯；前后端上传/下载链路打通。

### 后端改动（backend/）
- **新增** `backend/pyproject.toml`：依赖 fastapi、uvicorn、httpx、pydantic、python-dotenv、structlog、apscheduler、typer（CLI）、imageio-ffmpeg。
- **新增** `backend/ruff.toml`：lint + format 配置。
- **新增** `backend/app/config.py`：从 `.env` 读 `DATA_ROOT`、`RENDERER_URL`、`LLM_BASE_URL`、`LLM_API_KEY`、`MODEL_VLM`、`MODEL_TEXT`、`MODEL_TEXT_CHEAP`、`BGM_STRATEGY`、`ENABLE_CLI_INGEST` 等；提供 `Settings` pydantic 模型校验。
- **新增** `backend/app/logging.py`：structlog 配置（JSON 输出 + task_id context binding）。
- **新增** `backend/app/ir/project.py`、`ir/template.py`、`ir/ledger.py`、`ir/patch.py`：v0 最小版（前三个含一个 PlacedSegment + 一个 Caption；其余类型骨架就位）。
- **新增** `backend/app/ir/export.py`：`export_json_schema(out_path)`，pydantic v2 `model_json_schema()` 聚合所有顶层 IR 类型 → 写 `shared/ir.schema.json`。
- **新增** `scripts/gen_schema.py`：调 `app.ir.export.export_json_schema()` 的薄入口。
- **新增** `backend/app/render/client.py`：`render_project(ir: ProjectIR) -> str`，`httpx.post(f"{RENDERER_URL}/render", json=ir.model_dump(), timeout=600)` → 返回 mp4 相对路径。
- **新增** `backend/app/render/ffmpeg.py`：`get_media_info(path) -> dict`（调 ffprobe）；`normalize(src_path, dst_path) -> dict`（统一 1080×1920 / 30fps / H.264 / AAC，返回归一化信息）。
- **新增** `backend/app/main.py`：FastAPI 入口；挂 `api/samples.py`、`api/projects.py`、`api/tasks.py`；CORS allow `http://localhost:5173`；启动时 init `DATA_ROOT` 目录树 + 启动 cleanup cron。
- **新增** `backend/app/api/samples.py`：`POST /samples` 上传 mp4 → 存 `data/samples/{generated_id}/source.mp4` → FFmpeg normalize → 返回 `{sample_id, info}`；`POST /samples/{id}/render-demo` 构造最小 ProjectIR（1 PlacedSegment 引归一化视频 + 1 Caption 文本"Hello SceneEcho"）→ 触发 BackgroundTask 调 `render_project()` → 返回 `task_id`。
- **新增** `backend/app/api/projects.py`：v0 仅占位 `POST /projects` 上传。
- **新增** `backend/app/api/tasks.py`：`GET /tasks/{id}` 返回任务状态；`POST /internal/task-progress` 接 renderer 进度回调。
- **新增** `backend/app/cli.py`：typer CLI；`ingest-sample` 和 `ingest-project` 子命令，行为同 UI 上传但接受本地文件路径（仅 `ENABLE_CLI_INGEST=true` 时启用）。
- **新增** `backend/tests/conftest.py`：fixture loader（拷贝 fixtures 到临时 DATA_ROOT）。
- **新增** `.env.example`、`.gitignore`（补 `backend/.venv/`、`backend/data/`、`renderer/node_modules/`、`frontend/node_modules/`、`*.env`、`__pycache__/`、`dist/`、`shared/ir.schema.json` 是否提交=**否，CI 重新生成**）。

### 渲染服务改动（renderer/）
- **新增** `renderer/package.json`：依赖 remotion、@remotion/cli、@remotion/bundler、@remotion/renderer、express、zod、pino、p-queue、tsx、json-schema-to-zod（dev）。
- **新增** `renderer/tsconfig.json`：strict TS。
- **新增** `renderer/scripts/gen-types.ts`：读 `shared/ir.schema.json` → `json-schema-to-zod` → 写 `src/types/ir.ts`（zod schema + 推导 TS 类型）。
- **新增** `renderer/src/types/ir.ts`：generated，不手动编辑（顶部加注释）。
- **新增** `renderer/src/logger.ts`：pino JSON 输出，task_id binding。
- **新增** `renderer/src/queue.ts`：`p-queue({concurrency: 1})` 单实例。
- **新增** `renderer/src/progress.ts`：`reportProgress(taskId, progress)` 调 Python `POST /internal/task-progress`。
- **新增** `renderer/src/compositions/Project.tsx`：顶层 Remotion composition，props = `{ projectIR }`；阶段 0 实现：渲染第一个 PlacedSegment 引用的源视频 + 第一个 Caption 作叠加层。
- **新增** `renderer/src/compositions/Caption.tsx`：阶段 0 简单淡入字幕（接 text + start + end + style）。
- **新增** `renderer/src/render.ts`：`renderProjectIR(ir, taskId) -> outputPath`，调 `@remotion/bundler` 打包 + `renderMedia({onProgress})` 出 mp4 到 `projects/{id}/outputs/render_{ts}.mp4`。
- **新增** `renderer/src/server.ts`：Express，`POST /render` 用 zod 校验 IR → 入 `p-queue` → 返回 `{task_id, queued_position}`；`GET /health` 探活；`GET /render/queue` 队列态。

### 前端改动（frontend/）
- **新增** Vite + React + TS 脚手架（`pnpm create vite frontend -- --template react-ts`）。
- **新增** `frontend/package.json`：依赖 react、react-router-dom、@remotion/player、zustand、axios、json-schema-to-zod（dev）。
- **新增** `frontend/scripts/gen-types.ts`：同 renderer 的方式生成 `src/types/ir.ts`。
- **新增** `frontend/src/api/index.ts`：封装 `uploadSample(file)`、`renderDemo(sampleId)`、`pollTask(taskId)`。
- **新增** `frontend/src/state/`：Zustand store（task 进度、当前 ProjectIR）。
- **新增** `frontend/src/components/TaskProgress.tsx`：根据 task_id 轮询并显示进度条 + stage。
- **新增** `frontend/src/pages/SampleExtract.tsx`：阶段 0 最简 UI——上传 mp4 → 点"渲染 demo" → 拿 task_id → 显示进度 → 完成后 `<video>` 播放下载。
- **新增** `frontend/vite.config.ts`：proxy `/api` 到 `http://localhost:18521`。

### 工作区与 CI 改动
- **新增** `pnpm-workspace.yaml`：包含 `renderer/` 和 `frontend/`。
- **新增** 根 `package.json`：scripts `dev`（concurrently 起三服务 + watch schema）、`gen:types`（递归调 renderer/frontend 的 gen:types）、`build`、`lint`。
- **新增** `.github/workflows/ci.yml`：按"测试 / 可观测性 / CI 策略"章节定义；type-sync job 阻塞合并。
- **新增** `docs/dev-setup.md`：开发环境搭建指引（Python venv、Node 安装、FFmpeg、`.env` 配置、`pnpm install && pnpm dev`）。

### 验证方式
1. `pytest backend/tests/unit/test_min_render.py`：构造最小 ProjectIR → 调 `render_project()` → 输出 mp4 存在 → ffprobe 时长与源一致（±100ms）、fps=30、yuv420p。
2. CLI 验证：`python -m app.cli ingest-sample tests/fixtures/sample_basic_15s/source.mp4` → 在 `data/samples/` 下生成新条目（含 normalized.mp4 + thumbnail.jpg）。
3. 手动验收：浏览器（`pnpm dev` 起三服务）上传 mp4 → 点渲染 → 看到任务进度从 0→100% → 页面 `<video>` 播放原画面叠加 "Hello SceneEcho" 字幕。
4. 服务通信：`curl POST $RENDERER_URL/render -d @tests/fixtures/min_ir.json` → 返回 task_id → 几秒后 mp4 文件出现。
5. **IR 同步**：手动改 `ir/template.py` 加一个字段 → 跑 `pnpm gen:types` → renderer/frontend 的 `types/ir.ts` 同步更新。
6. **CI 绿灯**：push 到 GitHub → Actions 全 job 通过；故意改一个 pydantic 字段不跑 codegen → CI type-sync job 红。

---

## 阶段 1: 模板提取（D2 范围） 📋

### 前置条件
- 阶段 0 的 `render_project()` 可将最小 ProjectIR 渲成 mp4（阶段 0 验证 1+3 通过）。
- Python venv 已切 3.11/3.12，可装 PaddleOCR / Demucs / PySceneDetect / opencv-python / librosa / whisperx。
- `.env` 已配 `LLM_BASE_URL`、`LLM_API_KEY`、`MODEL_VLM`、`MODEL_TEXT`。
- `data/system/fonts/` 已放入至少 2 个中文字体；`data/system/bgm_pool/` 已放入至少 5 首免版权曲（fixture 阶段 2 才用，阶段 1 不强求）。
- 测试 fixtures：`sample_basic_15s` / `sample_with_sticker_12s` / `sample_fast_pace_8s` / `sample_no_bgm_10s` 已 ingest（至少 3 个）。

### 目标
5–20s 样例 → 完整 `TemplateIR`（D2 范围：切点 + 字幕样式含多行 + 缩放 + BGM 特征 + 贴纸位置+描述 + 骨架三段 + 字幕功能分类 + 标签 + VLM sanity check）→ 存入 KB，可在前端列表查看。

### 设计约束（本阶段必守）
- 只提"怎么剪"，不判断样例说了什么内容本身（D2）。
- 骨架按位置阈值发现（D5）；其余角色按字幕有无标 material_req。
- 保真度只做 D2；D3 字段留空（VisualStyle.mask 等）（D4）。
- 槽位时长输出为 `{min, nominal, max}` 可伸缩区间（D8）。
- 贴纸只识别位置 + 时机 + 描述；图形生成留 Phase 5（D10）。
- VLM/LLM 调用都返回 id 决策或结构化 JSON，绝不改写源文本（D11）。
- 每次 extract 调用 VLM ≤ 8 次（成本控制）。

### 后端改动
- **新增** `backend/app/llm/client.py`：OpenAI-compatible 统一客户端；`chat_text(messages, model=cheap|reasoning) -> str`、`chat_vision(messages_with_images, model) -> str`、`structured_output(prompt, schema) -> dict`（自动 JSON mode + pydantic 校验 + 重试）。
- **新增** `backend/app/llm/prompts/`：`sticker_describe.md`、`caption_function.md`、`tag_suggest.md`、`sanity_check.md`、`dedup.md`、`segment.md`、`nl_edit.md`。
- **新增** `backend/app/extract/normalize.py`：复用 `render/ffmpeg.py::normalize()` 包装为 extract pipeline 的第一步。
- **新增** `backend/app/extract/scenes.py`：`detect_scenes(normalized_path) -> list[Scene]`，PySceneDetect `ContentDetector(threshold=27)`；输出 `{start, end, duration}` + 整体节奏 `{mean, std, count}`。
- **新增** `backend/app/extract/motion.py`：`estimate_zoom(normalized_path, scenes) -> list[ZoomKeyframe]`，**VLM 粗判 + CV 精细化两阶段**（替代原 ORB+RANSAC 重型方案）：
  - 阶段 1（粗判）：对每个 scene 取首 / 中 / 末三帧合成 1×3 网格 → VLM 判断 `direction ∈ {推进, 拉远, 稳定, 抖动}`；稳定的 scene 直接跳过阶段 2
  - 阶段 2（精细化，仅非稳定 scene）：在该 scene 内采样 5fps，用 OpenCV `goodFeaturesToTrack` + Lucas-Kanade 光流跟踪中心点周围特征 → scale 曲线 → 取 5 个 ZoomKeyframe
  - scale > 1.1 推进、< 0.9 拉远、其余稳定；scale 变化 > 3.0 视为抖动（不入关键帧）
- **新增** `backend/app/extract/captions.py`：`extract_captions(normalized_path) -> list[CaptionEvent]`，PaddleOCR (`ch_PP-OCRv4`) 抽帧（1fps）；跨帧追踪同一文字块（IoU > 0.5）→ 合并 `{text, position, size, color, stroke, anim_in, start, end}`；`anim_in` 由帧间位移/alpha 曲线判（Y 上升=滑入、alpha 0→1=淡入、bbox 宽度逐字增=逐字弹入、其余=unknown）；**多行布局**：bbox 高度 > 1.5 * 行高 → `layout=multi`，估算 `max_chars_per_line`。
- **新增** `backend/app/extract/audio.py`：`extract_bgm(normalized_path, save_stem: bool) -> AudioStyle`，Demucs `htdemucs` 分离 → 检查 vocals stem RMS 判 `is_instrumental` → librosa 算 BPM（tempogram）+ 每秒能量（RMS）+ mood（规则映射：BPM>120 高能/<80 舒缓 + 能量方差大=动态/小=平稳）→ 若 `BGM_STRATEGY=original` 保存 `bgm_stem.wav` 并填 `bgm_path`。
- **新增** `backend/app/extract/stickers.py`：`extract_stickers(normalized_path, scenes, captions) -> list[StickerEvent]`，**VLM-first 采样策略**（替代原 OpenCV 显著性方案，因后者在口播脸部高显著性区域产生大量假阳性）：
  - 步骤 1：采样 1fps + 在 PySceneDetect 给的 scene cut 前后额外抽 1 帧（贴纸常在切点出现/消失）→ 帧序列
  - 步骤 2：每 4–6 帧合成 2×2 或 2×3 网格图（带帧号水印）→ 一次 VLM 调用，prompt `prompts/sticker_detect.md` 要求结构化 JSON：`[{description, frames_appeared:[i,j,k], position_normalized:[x,y], size_normalized:[w,h], confidence}]`
  - 步骤 3：对 VLM 返回的每个贴纸候选，在指定帧的位置 ±10% 范围内做帧差 + Canny edge → 精确化 bbox 边界
  - 步骤 4：跨帧合并同一贴纸（IoU > 0.5 或描述余弦相似度 > 0.8）→ 输出 `{description, position, size, start, end, crop_frames}`，裁图存 `extracted/stickers_crops/{n}/`
  - 步骤 5：参考 `system/stickers_reference/` 时让 VLM 在描述里附"是否近似已知贴纸 ID"
  - 降级：VLM 返回非 JSON / 不可解析 → fallback 到空贴纸列表（不阻塞 pipeline）
- **新增** `backend/app/extract/skeleton.py`：`build_skeleton(scenes, captions, stickers, duration) -> list[Slot]`；位置阈值 `start/duration < 0.30` → 开头、`> 0.70` → 结尾、其余 → 主体；槽位时长 `{min=slot_duration*0.7, nominal=slot_duration, max=slot_duration*1.5}`；`material_req`：有字幕=人物口播，无字幕但有缩放/贴纸=B-roll/包装，二者皆无=待定。
- **新增** `backend/app/understand/vision.py`：`classify_caption_function(caption_event, frame) -> str`，VLM 送字幕区域裁图 + 文本 → 返回 `regular|标题|强调|卖点|CTA`；调用时按 caption 个数批量。
- **新增** `backend/app/extract/pipeline.py`：`extract_template(sample_id) -> TemplateIR`，串联 normalize → scenes → motion → captions → audio → stickers → skeleton → vision.classify_caption_function → kb.tagging.suggest_tags → sanity check；每 step 写 `tasks.stage_timings` 和 `extracted/extract.log`；返回完整 TemplateIR。
- **新增** `backend/app/kb/store.py`：SQLite `templates` 表（`id, name, source_sample, ir_json, tags_json, thumbnail_path, created_at`）+ `tasks` 表；`save_template(ir)`、`get_template(id)`、`list_templates()`、`init_db()` 启动时建表 WAL 模式。
- **新增** `backend/app/kb/tagging.py`：`suggest_tags(ir, sample_frames) -> Tags`，VLM 送 3 张采样帧 + 骨架概要 + ASR 文本（如有）+ 字幕样式摘要 → prompts/tag_suggest.md → 返回 `{position, function, scene, notes}`。
- **新增** `backend/app/kb/select.py`：`select_template(query_tags, kb) -> template_id`，标签精确匹配 + LLM 重排；阶段 1 占位（阶段 3 完整）。
- **新增** `backend/app/agent/aigc.py`：v0 占位空函数（Phase 5 填）。
- **扩展** `backend/app/api/samples.py`：`POST /samples/{id}/extract` 触发 `extract_template()` BackgroundTask → 入 KB → 返回 task_id；`GET /samples/{id}/thumbnail` 已在阶段 0 处理。批量：同批次多个 sample_id 各自独立 extract。
- **新增** `backend/app/api/templates.py`：`GET /templates`、`GET /templates/{id}`、`PATCH /templates/{id}/tags`、`DELETE /templates/{id}`。

### 渲染服务改动
- **扩展** `renderer/src/types/ir.ts`：跑 `pnpm gen:types` 重生成（含 TemplateIR / StyleRule / CaptionStyle 等完整 schema）。
- **扩展** `renderer/src/compositions/Caption.tsx`：实现完整 CaptionStyle：
  - 多行布局（按 `max_chars_per_line` 切行）
  - anim_in 全套：逐字弹入（中文按字符 stagger，英文按词）/ 整句滑入 / 淡入 / 打字机
  - anim_emphasis：关键词高亮（emphasis_words 数组的字符给特殊颜色）/ 抖动 / 放大
  - 字体加载：从 `data/system/fonts/` 解析 `font_family` → CSS @font-face
- **扩展** `renderer/src/compositions/Project.tsx`：消费 ProjectIR 的 Caption 列表（多个时段），渲染时按 `start/end` 决定显隐。

### 前端改动
- **扩展** `frontend/src/pages/SampleExtract.tsx`：上传后展示样例基础信息（时长、镜头数、BGM 有无、字幕数预览、**封面缩略图**、骨架三段标注）；**支持一次上传 2–3 条样例**，各自独立提取；"提取模板"按钮触发 extract → TaskProgress 显示 stage（"切点检测中..."、"OCR..."、"BGM 分离..."、"VLM 标签..."）→ 完成后展示提取出的骨架/风格摘要。
- **新增** `frontend/src/pages/TemplateLibrary.tsx`：列表展示 KB 所有模板（名称/标签/来源缩略图）；点击查看详情页（骨架可视化 + StyleRule 详情 + sanity check 结果 + 人工改 Tags）。

### 验证方式
1. **测试集**：3 个 fixtures 样例（`sample_basic_15s` / `sample_with_sticker_12s` / `sample_fast_pace_8s` / `sample_no_bgm_10s` 中至少 3 个），事先人工标注（切点数 ±1、字幕首现时刻、归一化位置、BGM 有无、骨架三段、贴纸 bbox）。
2. **指标基线**（`pytest backend/tests/integration/test_extract.py --baseline`，写入 `tests/baselines.json`）：
   - 切点 F1 ≥ 0.80（容差 ±0.2s）
   - 字幕首现时刻 median 误差 < 0.3s
   - 字幕位置 median 误差 < 5%（归一化坐标）
   - 字幕多行判定：测试样本中至少 1 个多行 case 被正确识别
   - 骨架三段：3/3 与人工一致
   - BGM 有/无：3/3 正确
   - 贴纸位置 IoU ≥ 0.5（如样例有贴纸）；描述与人工标注 LLM 评 ≥ 3/5
   - VLM sanity check：3/3 返回 `pass=true`（如不通过应有可读 notes）
3. **IR round-trip**：`save_template(ir)` → `get_template(id)` 各字段一致（`pytest backend/tests/unit/test_kb.py`）。
4. **VLM 调用预算**：单次 extract 调 VLM ≤ 8 次（pytest 监控 `llm.client` call counter）。
5. **端到端**：UI 上传 `sample_basic_15s/source.mp4` → extract → 模板库看到该模板的标签 + 骨架 + 缩略图 + sanity check 状态。
6. **失败降级**：故意删 `LLM_API_KEY` → extract 应在 VLM 步骤 fallback 到 "unknown" 描述/默认标签 → 仍能产出可入库的 TemplateIR（标 `degraded=true`）。

---

## 阶段 2: ★MVP 应用闭环（短素材 + 指定模板） 📋

### 前置条件
- 阶段 1 的 `extract_template()` 可产出完整 TemplateIR 入 KB（阶段 1 验证 2+3+5 通过）。
- KB 中至少存在 2 个带 Tags 的模板（fixtures 提前 extract 准备）。
- `render_project()` 已能处理多 PlacedSegment + Caption 列表 + 缩放层（阶段 0 基础上 + 本阶段渲染端扩展）。
- `data/system/bgm_pool/` 已放至少 5 首免版权曲 + `bgm_index.json`。

### 目标
用户传 10–20s 一镜到底口播短素材 + 从 KB 指定一个模板 → ASR 对齐 → 映射到模板骨架 → 套字幕风格（含多行）+ 缩放 + BGM（features 或 original）+ 贴纸（占位）→ 渲染 MP4 返回。**MVP 闭环在此完成。**

### 设计约束（本阶段必守）
- 短素材场景下天然保序（D3）；账本仍要建，为 Caption 精确时间戳服务。
- 时长自适应（D8）：用户素材时长 vs 模板骨架总时长，按各槽位 `{min,max}` 缩放或裁切；变速幅度 ≤ ±20%。
- 缺口补全只用 MVP 三法（D10：不引入 AIGC）。
- 渲染走 Remotion + FFmpeg，输出 MP4（D7）。
- 用户素材若 canvas 与模板不匹配，走 letterbox + 模糊背景，**不裁切用户脸**。

### 后端改动
- **新增** `backend/app/understand/asr.py`：`transcribe(normalized_path) -> TranscriptLedger`，WhisperX `large-v3` + language=zh + word_timestamps + forced alignment；按停顿（>0.3s gap）合并 Unit 到句级；`avg_logprob` 写入 Unit。
- **新增** `backend/app/kb/recommend.py`：`recommend_templates(material_path, ledger, kb, k=3) -> list[{template_id, score, reason}]`，**模板智能推荐**（B1）：
  - 从 user material 取 3 帧采样（首 / 中 / 末）+ ASR 摘要（前 200 字）
  - VLM 接收：采样帧 + ASR 摘要 + KB 中所有模板的 Tags 概要
  - prompt 要求 VLM 输出 top-k 推荐及理由（中文）
  - 前端 Editor 在上传素材后立即调，预填模板下拉；用户可采纳推荐或手动浏览全库
- **新增** `backend/app/apply/mapping.py`：`map_short_to_template(ledger, template) -> list[PlacedSegment]`；策略：按 Unit 时间顺序对应到模板骨架槽位（10–20s 短素材通常对应 1–3 个槽）；时长不足时按比例拉伸槽位 nominal（速度调整 ≤ ±20%）；时长超出时裁切尾部或顺延到下一槽（保序）；记录 `src_timerange` 和 `timeline_start`；**用户素材槽位是否完全等于模板骨架**：MVP 假设是（用户被引导上传与模板长度相近的素材），不等时打 warning。
- **新增** `backend/app/apply/gaps.py`：`detect_gaps(segments, template) -> list[Gap]`，槽位 `material_req` 无对应用户片段 → Gap；MVP 通常 Gap 数 ≤ 1（用户口播覆盖人物口播槽，B-roll/包装槽可能 Gap）。
- **新增** `backend/app/apply/fill.py`：`fill_gap(gap, ledger, style, allow_aigc=False) -> str`，三法：① 文案补全（Text LLM 按上下文生成字幕文案，标 `is_fill=True`）；② 包装补全（生成标题条/卖点卡片占位文字 + StyleRule 填色）；③ 素材复用（裁取相邻片段 zoom-in 0.5–1s 重复）；`allow_aigc=True` 时增加 AIGC 占位（Phase 5 实现）。
- **新增** `backend/app/apply/style.py`：`apply_style(segments, template, ledger) -> tuple[list[PlacedSegment], list[Caption], str|None]`；
  - 按 `StyleRule.caption` 生成 Caption 列表（text/start/end 来自账本，style 来自模板，emphasis_words 用 Text LLM 从 Unit.text 选取 1–3 个）
  - 按 `StyleRule.visual.zoom_keyframes` 写入 PlacedSegment.applied_style
  - 按 `StyleRule.stickers` 复制到 PlacedSegment.applied_style（generated_image=None 走占位渲染）
  - BGM 选择：`features` 策略 → 从 `bgm_index.json` 找 BPM/mood 最近的曲（欧氏距离）；`original` 策略 → 直接用 `template.audio.bgm_path`
- **新增** `backend/app/apply/pipeline.py`：`apply_short(project_id, template_id) -> ProjectIR`，串联 normalize → asr → map → gaps → fill → style → 写 `projects/{id}/project.json`；返回单 Section 的 ProjectIR；每 step 更新 task.stage 和 progress。
- **扩展** `backend/app/render/ffmpeg.py`：
  - `mix_bgm(voice_track, bgm_path, output, duck_db=-12, is_instrumental=True) -> str`：用 `sidechaincompress` 滤波器 ducking（人声 > -25dB 时 BGM 衰减 12dB）；`is_instrumental=False` 时 ducking 更激进
  - `compose_segments(segments, output) -> str`：按 PlacedSegment 列表 cut + concat（不含字幕/贴纸/缩放，留 Remotion 处理）
- **新增** `backend/app/api/projects.py`（扩展阶段 0 占位）：
  - `POST /projects` 上传用户短素材 → 存 `data/projects/{generated_id}/source.mp4` → normalize → 返回 `project_id`
  - `POST /projects/{id}/recommend-templates` → 调 `recommend_templates()` 返回 top-3 推荐
  - `POST /projects/{id}/apply` body `{template_id, allow_aigc_broll: false}` 触发 `apply_short()` BackgroundTask → 存 ProjectIR → 返回 task_id
  - `GET /projects/{id}` 返回 ProjectIR + 任务状态
  - `POST /projects/{id}/render` 调 `render_project()` → 返回 task_id
  - `GET /projects/{id}/preview-props` 返回前端 Remotion Player 实时预览所需的精简 props

### 渲染服务改动
- **扩展** `renderer/src/compositions/Project.tsx`：渲染完整 ProjectIR：
  - 多 PlacedSegment 串联（用 Remotion 的 `<Series>` 或 `<Sequence>`）
  - Caption 列表按 start/end 显隐
  - 缩放层应用 zoom_keyframes（CSS transform interpolate）
  - 贴纸层应用 StickerEvent 列表
  - BGM 层 `<Audio>`（音频已在后端预混 ducking，直接播放）
- **扩展** `renderer/src/compositions/Caption.tsx`：完整 anim_in（逐字/滑入/淡入/打字机）+ anim_emphasis（关键词高亮/抖动/放大）+ 多行布局（按 max_chars_per_line 换行）。
- **新增** `renderer/src/compositions/ZoomLayer.tsx`：消费 `zoom_keyframes`，`interpolate` 在槽位时间内插值 scale，CSS `transform: scale()` 应用；中心点固定（face-aware 留 Phase 4）。
- **新增** `renderer/src/compositions/Sticker.tsx`：渲染策略
  - `generated_image != null`：`<Img>` 渲染该图
  - `generated_image == null`：渲染占位 div（半透明色块 + description 文字 + 虚线边框 + "Phase 5 替换"标签）
- **新增** `renderer/src/preflight.ts`：渲染前检查所有资源（fonts、bgm_path、stickers/generated_image、source mp4 路径都可读）→ 缺资源直接报错而非渲染半成品。

### 前端改动
- **新增** `frontend/src/pages/Editor.tsx`：
  - 顶部：上传短素材 → 显示视频信息
  - **智能推荐区**（B1）：上传完成后自动调 `/recommend-templates` → 显示 top-3 模板卡片（含 VLM 推荐理由）→ 用户可一键选用，也可点"浏览全库"打开下拉
  - 模板下拉选（从 `/templates`）→ 显示选中模板的骨架/标签摘要
  - "应用"按钮触发 `/projects/{id}/apply` → TaskProgress 显示 stage（"ASR..."、"映射..."、"套风格..."）→ 完成
  - 中间 `<RemotionPlayer>` 实时预览（接收 ProjectIR + 资源 URL）
  - 右侧 ProjectIR 概览（slot 列表 / 缺口数 / 总时长 / Caption 摘要）
  - 底部"渲染出片"按钮触发 `/projects/{id}/render` → TaskProgress → mp4 URL 后 `<video>` 播放 + 下载链接
- **新增** `frontend/src/components/RemotionPlayer.tsx`：
  - 嵌入 `@remotion/player`
  - 接收 ProjectIR 作 inputProps
  - 通过本地 Remotion bundle（构建时打包 compositions 到 frontend 静态资源）
  - ProjectIR 切换时即时重绘
  - 加载态 + 资源缺失态 UI
- **扩展** `frontend/src/api/index.ts`：`uploadProject`、`applyTemplate`、`renderProject`、`getProject`、`listTemplates`、`getTemplate`。

### 验证方式
1. **测试数据**：`projects/test_short_15s/source.mp4`（一段 15s 一镜到底口播，3–4 句话）+ KB 内 2 个已 extract 模板（含完整 StyleRule）。
2. **字幕同步**（`pytest backend/tests/integration/test_sync.py`）：抽 5–10 条输出 Caption → `median |caption.start - Unit.start| < 0.15s`。
3. **时长自适应**（`pytest backend/tests/integration/test_mapping.py`）：构造比模板骨架总时长长 150% 和短 50% 的用户素材 → 输出 PlacedSegment 的实际时长落在各 `slot.duration.{min,max}` 内；变速系数 ≤ ±20%。
4. **缺口补全**（`pytest backend/tests/integration/test_gaps.py`）：人为构造无法被用户片段满足的槽位 → 输出 Gap 列表非空、每个 Gap 有非空 fill_result。
5. **canvas 不匹配**（`pytest backend/tests/integration/test_canvas.py`）：用户素材 16:9 + 模板 9:16 → 输出 mp4 是 9:16、用户画面 letterbox 居中、背景模糊。
6. **BGM 策略切换**：`BGM_STRATEGY=features` 应选 `bgm_index.json` 中 BPM 最近的；`original` 应直接用 template 中的 bgm_path。
7. **渲染验收**（手动）：播放输出 mp4 → 字幕颜色/字体/位置/入场动画/多行布局与模板一致；缩放推进/拉远幅度与模板一致；BGM 节奏与模板特征一致；贴纸占位块出现在模板指定位置和时间；ducking 时人声清晰。
8. **失败重试**：渲染中途 kill renderer 进程 → 任务标 error → 前端显示"点击重试" → 重试成功。
9. **端到端**：浏览器（`pnpm dev`）上传 `test_short_15s/source.mp4` → 选模板 → Player 实时预览（看到字幕动画、缩放）→ 点渲染 → 进度 100% → 拿 mp4 → 播放确认。

---

## 阶段 2.5: NL 编辑 + 参数面板 + 迁移可视化 📋

### 前置条件
- 阶段 2 的 `apply_short()` 可产出 ProjectIR 并渲染出 mp4（阶段 2 验证 7+9 通过）。

### 目标
用户用自然语言或参数面板改 ProjectIR → 重渲染拿新 mp4；前端 Visualize 页清晰展示"抽取→映射→缺口→补全→风格套用"全链路。

### 设计约束（本阶段必守）
- NL 编辑/参数面板修改都只改 IR 结构，不改像素；patch 可回滚（D3 / 核心原则）。
- 参数面板 = NL 的等价表单入口，二者都经统一 patch 路径（D11）。
- 高频编辑节流：300ms debounce 后再 trigger 重渲染；用户连续编辑时取消正在排队的旧渲染任务。

### 后端改动
- **新增** `backend/app/agent/nl_edit.py`：
  - `nl_edit(project_ir, instruction, context) -> list[Patch]`：Text LLM 把自然语言指令翻成 Patch 列表（按 Patch op 枚举约束 JSON 输出）；prompt 提供当前 ProjectIR 摘要 + 模板骨架 + 可用 op 清单
  - `apply_patches(project_ir, patches) -> ProjectIR`：按 op 调度处理函数；版本号 +1 用于乐观锁
  - `panel_to_patches(field, old_value, new_value) -> list[Patch]`：参数面板改字段 → 生成等价 Patch
  - 维护 `patch_history.jsonl` 追加写
  - `undo(project_id) -> ProjectIR`：读最后一条 patch 反操作
- **新增** `backend/app/api/edit.py`：
  - `POST /projects/{id}/edit` body `{instruction}` → 调 `nl_edit` → `apply_patches` → 重渲染（带 debounce/cancel）→ 返回 `{new_ir, patches_applied, render_task_id}`
  - `POST /projects/{id}/panel-edit` body `{field, old, new}` → 等价路径
  - `POST /projects/{id}/undo` 回滚
  - `GET /projects/{id}/history` 返回 patch 列表
- **扩展** `backend/app/api/projects.py`：`GET /projects/{id}/lineage` 返回迁移可视化数据（template 骨架 + 用户 Unit → Slot 映射表 + Gap 列表 + 各 Gap 的 fill_result + 当前 ProjectIR vs 初始 ProjectIR 的差异摘要）。
- **新增** `backend/app/agent/render_queue.py`：项目级渲染节流（同 project_id 的新渲染请求 cancel 之前未完成的）。

### 渲染服务改动
- **新增** `renderer/src/server.ts` 接口 `DELETE /render/{task_id}`：取消队列中未开始的任务；已在跑的任务标 cancelled 但不强 kill。

### 前端改动
- **扩展** `frontend/src/pages/Editor.tsx`：
  - 增加底部 `NLBar.tsx`（发送 instruction → 调 `/edit`）
  - 增加左侧 `ParamPanel.tsx`：字幕颜色 / 字号 / 位置 / 入场动画下拉、缩放强度滑块、节奏快慢滑块、BGM 选择 dropdown、模板替换 dropdown、强调词输入；改任何参数都生成对应 patch 调 `/panel-edit`；参数面板**双向 sync**：每次 ProjectIR 更新后回填表单当前值
  - 增加右侧 patch 历史 + Undo 按钮
  - 编辑后 Player 实时反映新 ProjectIR；渲染按钮触发完整出片
- **新增** `frontend/src/pages/Visualize.tsx`：四步链路
  1. **抽取**：模板 slot 列表 + StyleRule 摘要 + sanity check 状态
  2. **映射**：用户 Unit → 模板 Slot 的表格 + 时间轴对照（横轴=时间，上轴=用户段，下轴=Slot 占位，连线展示对应关系）
  3. **缺口**：高亮标记被识别为 Gap 的 Slot（红框 + 原因）
  4. **补全**：per Gap 展示 fill_strategy + fill_result（文案/包装/素材复用）
  - 整体作为可滚动长页，便于截图作课题展示材料

### 验证方式
1. `pytest backend/tests/integration/test_nl_edit.py`：固定 ProjectIR 测典型指令：
   - `"字幕改黄色描边黑色"` → patches 含 `{"op":"set_caption_style","value":{"color":"#FFD400","stroke_color":"#000000"}}`
   - `"节奏加快一点"` → patches 含 `{"op":"adjust_rhythm","value":{"scale":0.8}}`
   - `"换成模板 B 风格"` → patches 含 `{"op":"swap_template","value":{"template_id":"B"}}`
   - `"开头第一句强调'独家'"` → patches 含 `{"op":"set_emphasis","value":{"words":["独家"],"section_idx":0}}`
   - 非法指令 `"把视频翻转"` → 返回可读报错，ProjectIR 不变
2. `pytest backend/tests/integration/test_undo.py`：apply 3 patch → undo 2 次 → ProjectIR 回到第 1 patch 后状态、版本号正确。
3. 参数面板 ↔ NL 等价性：在 Editor 用面板改字幕色 → 看到 Player 更新；NL "字幕改红色" → 应得到相同 ProjectIR；二者 patch_history 内容等价。
4. 重渲染 cancel：连续 3 次 NL 编辑（每次间隔 100ms）→ 后台应只完成最后一次渲染。
5. 可视化人工走查：四步链路全部有内容展示，无空白面板。
6. 端到端：浏览器在 Editor 输入"字幕换成黄色"→ 看到预览字幕变色 → 点渲染 → mp4 字幕变色。

---

## 阶段 3: 长视频分步审核闭环 📋

### 前置条件
- 阶段 2 的 `apply_short()` 稳定，复用其 mapping/gaps/fill/style 子模块（阶段 2 验证 7+9 通过）。
- 阶段 2.5 NL edit 已实现，Patch 数据结构稳定。
- KB 至少 3 个不同 Tags 的模板（覆盖开头/中间/结尾）。
- 测试 fixture `system/test_fixtures/long_3min/source.mp4` 已 ingest，含 ≥3 处口误重录 + ≥5 处 >1s 静音 + ≥3 个明确主题段（人工标注 ground truth）。
- `data/system/bgm_pool/` 至少 10 首曲覆盖不同 BPM/mood。

### 目标
~3min 长口播 mp4 → **9 step 流水线（含 5 个用户审核暂停点 + 1 个条件审核点）** → 输出多 Section ProjectIR → 渲染 MP4。Step 06（重排建议）在本阶段为占位（默认 baseline 保序），Phase 7 才完整实现。**MVP 长视频闭环 + 分步审核基础设施在此完成。**

```
[upload long.mp4]
    │
    ▼
┌── Step 01: ASR → 账本 ──────────────────────────────────┐  自动
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 02: VAD 去静音 + 用户标记跳过 ────────────────────┐  审核 ◀── Accept / Edit / Rerun
│   review UI: 静音段表 + 主动删除标记                       │
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 03: LLM 去重 ────────────────────────────────────┐  审核 ◀── Accept / Edit / Rerun
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 04: LLM 主题分段（保序）────────────────────────────┐  审核 ◀── Accept / Edit / Rerun
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 05: 选模板 per Section ──────────────────────────┐  审核 ◀── Accept / Edit / Rerun
│   review UI: 表格 + top-3 候选 + NL 输入                  │
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 06: 重排建议 ────────────────────────────────────┐  审核 (opt-in)
│   未启用 = baseline 保序占位                              │
│   Phase 7 启用 = 多版本卡片 + 双时间轴对照                  │
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 07: 映射 + 缺口 + 补全 + 套风格 ────────────────────┐  自动
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 08: Quality scoring ────────────────────────────┐  审核（仅有 issue 时暂停）
│   节奏 / 字幕密度 / BGM-人声比 / 总时长 超阈值则 warning   │
└────────────────────────────────────────────────────────┘
    │
    ▼
┌── Step 09: 渲染 → MP4 ─────────────────────────────────┐  自动
└────────────────────────────────────────────────────────┘

任意 step 可 Rollback to N，废弃 N 之后所有产物从 N 重跑。
```

### 设计约束（本阶段必守）
- D11：账本不可变；所有 LLM 操作返回对 id 的决策。
- D12：每个关键 step 暂停等待用户审核；中间产物持久化。
- D3：默认保序（Step 06 保序占位，重排归 Phase 7）。
- D6：自动选模板用标签匹配 + LLM 重排，提供 top-3 候选。
- 每 step 失败可单独重跑，不影响其他 step 已产出。

### 后端改动

**Pipeline 状态管理基础设施**
- **新增** `backend/app/ir/pipeline.py`：
  ```python
  class StepState(BaseModel):
      step_no: int             # 1..9
      name: str                # "asr"|"vad"|"dedup"|"segment"|"select"|"reorder"|"apply"|"quality"|"render"
      status: str              # pending|running|awaiting_review|approved|rejected|replaying|skipped
      started_at: str | None
      completed_at: str | None
      output_path: str | None  # 相对 DATA_ROOT，指向 projects/{id}/pipeline/{step_no:02d}_{name}.json
      error: str | None
      llm_cost_tokens: int = 0
      llm_cost_usd: float = 0.0

  class PipelineState(BaseModel):
      project_id: str
      current_step: int        # 1..9
      steps: list[StepState]   # 长度恒为 9
      enable_reorder: bool = False  # Phase 7 opt-in 开关（项目初始化时设定）
      created_at: str
      updated_at: str
  ```
- **新增** `backend/app/apply/pipeline_state.py`：
  - `init_pipeline(project_id, enable_reorder: bool = False) -> PipelineState`：建 9 step 全 pending；`enable_reorder=false` 时 Step 06 创建即标 skipped
  - `start_step(pid, step_no)`：标 running
  - `mark_awaiting_review(pid, step_no, output_path)`：暂停
  - `approve(pid, step_no)`：推进到 next；若 next 是审核 step → 触发后又暂停；若是自动 step → 自动跑完
  - `submit_edit(pid, step_no, edited_output)`：保存编辑后产物 → approve
  - `rerun(pid, step_no, params)`：清当前 step 产物 → 重跑
  - `rollback_to(pid, step_no)`：废弃 step_no+1 之后所有产物 → 从 step_no 重新开始
  - SQLite 表 `pipeline_states`（`project_id PK, state_json, updated_at`）

**Step 实现（按编号）**
- **新增** `backend/app/understand/vad.py`：silero-VAD 标记静音 → 输出 `{kept_unit_ids, removed_segments: [{start, end, duration, reason}]}`；阈值 `min_silence_dur=1.0s`。**C2 用户标记跳过**：Step 02 的 review UI 除恢复静音段外，额外暴露"手动标记删除"操作——用户勾选不感兴趣的 Unit（非重复、非静音）→ 加入 `user_dropped_ids` → 不进入后续 step。这部分编辑产出 `manual_drop` patch，独立于 dedup。
- **新增** `backend/app/understand/dedup.py`：Text LLM (`MODEL_TEXT_CHEAP`) 输入带 id 的 Unit 列表 → 严格 JSON 输出 `{keep: [ids], drop_pairs: [{id, dup_of, reason: "重录"|"口误"|"重复表达"}]}`；prompt 强调"只判断重复、不评价内容"；同句重录取 logprob 最高一遍。
- **新增** `backend/app/understand/segment.py`：Text LLM 主题分段 → 输出 `{topics: [{name, unit_ids: [...]}]}`；断言 unit_ids 全局严格递增 + 每段时长 ≥20s；输出还含 `boundary_confidence` 数组供 UI 染色（低置信边界标黄）。
- **扩展** `backend/app/kb/select.py`：完整版 `select_template(section, kb) -> {top1, candidates: list[{id, score, reasoning}]}`；按 Section Unit 文本 + 时长调 Text LLM 判功能标签 → KB 精确匹配 + LLM 重排 → 返回 top-3 + 解释。
- **新增** `backend/app/apply/long_pipeline.py`：`apply_long(project_id) -> PipelineState`，按 step 推进；遇到审核 step 写 `awaiting_review` 后返回；用户调 `/approve` 后继续：
  - Step 01: normalize → asr → 写 `pipeline/01_ledger.json`（自动）
  - Step 02: vad → 写 `pipeline/02_vad.json`（**审核**）
  - Step 03: dedup → 写 `pipeline/03_dedup.json`（**审核**）
  - Step 04: segment → 写 `pipeline/04_sections.json`（**审核**）
  - Step 05: 逐 section select_template → 写 `pipeline/05_template_assignments.json`（**审核**）
  - Step 06: 重排（`enable_reorder=false` 时 status=skipped 写 identity；`true` 时调 narrative 全套）→ 写 `pipeline/06_reorder_plans.json`（**审核 if enable_reorder**）
  - Step 07: 逐 Section mapping → gaps → fill → style → 拼接 → 写 `pipeline/07_project_ir.json`（自动，同时同步 `project.json`）
  - Step 08: quality_score（C3）→ 写 `pipeline/08_quality.json`（**仅有 error 级 issue 时暂停**）
  - Step 09: render → 写 `outputs/render_{ts}.mp4`（自动）
- **新增** `backend/app/apply/quality.py`：`quality_score(project_ir) -> list[QualityIssue]`，按规则评估：
  - **节奏**：cuts/min < 5 = "节奏偏慢"；> 30 = "节奏过快"
  - **字幕密度**：字符数/秒 > 8 = "字幕过密阅读困难"；< 1 = "字幕过少"
  - **BGM-人声比**：BGM 段 ducking 后能量 > 人声 50% = "BGM 盖人声"
  - **总时长**：< 30s 或 > 5min = 异常告警
  - **缺口数**：> 总槽位 30% = "缺口过多"
  - 每条 QualityIssue 含 `{severity: warn|error, kind, message, suggestion}`
  - 全部 warn 且无 error → 自动通过；有 error → 暂停 review

**API**
- **新增** `backend/app/api/pipeline.py`：
  - `POST /projects/{id}/apply-long` 启动 → 返回 `task_id`
  - `GET /projects/{id}/pipeline` 返回 PipelineState（前端轮询）
  - `GET /projects/{id}/pipeline/steps/{n}/output` 返回 step n 产物
  - `POST /projects/{id}/pipeline/steps/{n}/approve` 推进
  - `POST /projects/{id}/pipeline/steps/{n}/edit` body 不同 step 不同 schema → 保存 → approve
  - `POST /projects/{id}/pipeline/steps/{n}/rerun` body `{params}` 重跑
  - `POST /projects/{id}/pipeline/rollback/{n}` 回退

### 渲染服务改动
- 无新增 step 接口；阶段 2 已能渲染 multi-Section ProjectIR。
- 扩展 `Project.tsx` 处理 Section 间过渡（按 `transition_in/transition_out` 决定 cut/fade；本阶段仅 cut/fade 二选一，复杂过渡归 Phase 4）。

### 前端改动
- **新增** `frontend/src/pages/LongVideoEditor.tsx`：长视频版 Editor，承担分步审核 UI：
  - 顶部 Stepper（9 个 step 状态图标）
  - 中央动态 review 区（per step UI 见下）
  - 底部：Accept / Edit / Rerun 按钮 + 累计成本
  - 侧边：step 历史，可点击跳回（弹确认框警告会清后续）
- **新增 review 组件**：
  - `StepVADReview.tsx`：去静音段表格（start/end/duration/原因），每行复选框"恢复此段"
  - `StepDedupReview.tsx`：drop 列表，每行展示原文 + dup_of 的引用文本对比，复选框"保留"
  - `StepSegmentReview.tsx`：Gantt 风格时间轴，每段一个色块；可拖边界、点击合并/拆分、双击改名；低置信边界标黄
  - `StepSelectReview.tsx`：表格 `Section | 当前模板 | top-3 候选 | NL 输入框`；NL 调 `/edit` 替换模板；表单 dropdown 等价
  - `StepReorderReview.tsx`：本阶段简化版（只显示 "保序 baseline → Accept"）；Phase 7 升级
  - `StepQualityReview.tsx`：QualityIssue 列表（severity 染色）+ 建议；warn 级可直接 Accept，error 级强制处理
  - `StepFinalReview.tsx`：Step 07 后的 RemotionPlayer 预览 + Step 09 渲染按钮

### 验证方式
1. **测试数据**：`long_3min/source.mp4`，人工标注（重复 unit_ids、静音段、主题段边界、每段期望模板）。
2. **各 step 自动通过率**（无用户介入）：
   - Step 02 去静音：召回 ≥ 0.85（误删少）
   - Step 03 去重：召回 ≥ 0.80、精度 ≥ 0.90（误删代价高）
   - Step 04 主题分段：边界与标注一致 ±1 句、段数一致
   - Step 05 选模板：top-1 候选与人工偏好一致 ≥ 0.60；top-3 命中 ≥ 0.85
3. `pytest backend/tests/integration/test_pipeline_state.py`：
   - 状态机：approve → next；rerun 不影响其他 step 产物；rollback to N 清 N+1 之后
   - 持久化：服务重启后 PipelineState 可恢复
4. `pytest backend/tests/integration/test_long.py`：完整跑通（全部 Accept），最终 ProjectIR 各 Section unit_ids 严格递增（保序断言）。
5. **审核操作端到端**：浏览器走完 9 step：
   - Step 02 恢复 1 个静音段 + 手动标记跳过 1 个 Unit → 后续 Section 反映两种操作
   - Step 03 保留 1 个 dup → 字幕含该重复句
   - Step 04 合并 2 段 → Section 数减 1
   - Step 05 NL "第 2 段换模板 B" → 第 2 段模板真改
   - Step 06 默认 Accept（保序）
   - Step 07 自动产 ProjectIR
   - Step 08 quality 无 error → 自动通过
   - Step 09 渲染 → mp4 体现以上修改
6. **回退**：走完 Step 05 → Rollback to Step 03 → Step 04/05 状态重置，重跑生效。

### 课题对齐
- 任务 2 结构拆解（段落 + 节奏 + 包装）→ Step 02-04 直接产出
- 任务 7 迁移过程可视化 → 分步审核每 step 暴露中间产物（评审能"看见"AI 决策）
- 任务 12 人工可调（hook/包装/节奏/结尾）→ 分步审核 + NL 编辑覆盖全部

---

## 阶段 4: 保真度升级到 D3（Tier B） 📝

### 目标
在 D2 已稳定基础上，**有选择地**扩展到 D3：转场分类 + 几何蒙版 + 调色 LUT + 标题条 + **音效预设注入（新增功能，非识别）**。砍掉：音效识别 / 高潮位置 / 画面缩放出框 / 变速识别（详见"已砍项"）。

### 前置条件
- 阶段 1 的 D2 提取稳定（验证 2 指标稳定通过 ≥ 1 个月，或测试集覆盖 5+ 样例）。

### 设计约束
- 每个子模块单独可启停（feature flag），不破坏 D2 基线。
- D2 baseline 指标不退步。
- 音效**只做注入**，不做识别（口播样例里基本没有可学的音效）。

### 初步构想（按价值/工作量排序，由高到低）

**核心 3 项（建议必做）**：
1. `extract/title_bar.py`（新增）：标题条/卖点卡片识别——屏幕顶/底带文字彩色长条 → 位置 + 颜色 + 文字 + 出现时段。这是口播视频里出现频率最高、价值最大的视觉包装元素。
2. `extract/scenes.py` 扩展：转场分类（硬切 / 叠化 / 滑入 / 推拉），基于相邻帧相似度 + 像素位移；模糊时 VLM 兜底。Phase 7 重排断点需要它做平滑。
3. `extract/color.py`（新增）：调色风格识别——颜色直方图 + 帧间色调一致性 → 匹配预设 LUT 库（暖色 / 冷色 / 高饱和 / 低饱和 / 电影感）+ 微调参数（不做 1:1 LUT 提取）。

**音效预设（用户手工配，新增功能）**：
4. `agent/sfx_preset.py`（新增）：模板编辑界面允许用户在 Slot 上手工标注"在此时机触发 X 类音效"，X 来自 `data/system/sfx_pool/`（whoosh / ding / pop / 打字音 …）。**不识别样例音效**——用户主动选。渲染时 FFmpeg 在指定时间混入对应音效。

**保留但可选（用户已表态保留几何蒙版）**：
5. `extract/masks.py`（新增）：帧级几何蒙版识别（圆 / 线性分屏 / 矩形）→ 归一化参数。复杂场景调 SAM2。**实施建议**：先 VLM 看采样帧判"有无蒙版"，无 → 跳过整步；有 → 详细分析。

### 已砍项（不在 D3 范围）

| 项 | 砍掉原因 |
|----|---------|
| 音效**识别**（从样例提取） | 口播视频里基本没用音效，识别准确率 < 50%；改为"预设注入"（条目 4） |
| 高潮位置 | 我之前定义为"BPM+能量+切点频率"——这是音乐视频的高潮。口播视频是**语义高潮**（讲到 climax 的内容），已合并到 Phase 7 `narrative.score.energy` 维度。 |
| 画面缩放出框 | 横屏→竖屏的格式适配，不是风格；用户素材直接走 canvas 归一化处理。 |
| 变速**识别**（从样例提取） | 变速识别准确率 < 70%；口播变速会扭曲语音。**应用端的主动变速**保留（D8 时长自适应 ≤±20%）。 |

### 渲染服务改动
- 对应 Remotion 组件：`Transition.tsx`、`TitleBar.tsx`、`ColorLayer.tsx`、`Mask.tsx`
- FFmpeg 端：`mix_sfx(timeline, sfx_events, output)` 在时间点叠加音效（与 BGM ducking 合并）

### 验证方式
1. `pytest backend/tests/integration/test_extract_tierB.py`：
   - 标题条识别：3 个含标题条样例的 IoU ≥ 0.7 + 文字正确率 ≥ 0.9
   - 转场分类：3 个不同转场类型样例的分类正确率 ≥ 0.8
   - 调色匹配：预设 5 个色调样例 → top-1 命中 ≥ 0.6
   - 蒙版识别（如有蒙版样例）：IoU ≥ 0.5
2. D2 基线回归：跑 Phase 1 测试集，指标退步 ≤ 5%。
3. 端到端：1 个含标题条 + 1 个转场分类的样例 → 应用到用户素材 → mp4 体现标题条 + 转场。

### 待讨论的问题
- 调色 LUT 的预设库怎么建（5–10 个手工标注 LUT 起步？）
- 蒙版羽化参数与 CSS mask 精度映射
- 音效池规模与音效 ID schema

---

## 阶段 5: AIGC 扩展（生图 + 视频生成 + 封面） 📝

### 目标
接入第三方生图 API（生成**贴纸图形** + **封面**）+ 视频生成 API（生成 B-roll 画面），由用户主动触发；产物明确披露 AI 内容；强缓存避免重复成本。

### 前置条件
- 阶段 1 已稳定输出 StickerEvent.description；阶段 2 已稳定运行单段闭环；阶段 2.5 NL 编辑已支持 `mark_aigc` patch。

### 设计约束
- D10：绝不自动启用 AIGC；所有调用都有用户显式确认。
- 失败降级：API 不可用时 fallback 到占位符 + 提示用户。
- 缓存：按内容 hash 全局复用，避免重复支付。
- 安全：prompt 注入防御 + 内容审查（API 自带或调 moderation endpoint）。
- 成本追踪：每次调用记 `tasks.aigc_cost` 字段；UI 显示项目总成本。

### 初步构想
- `agent/aigc.py`：
  - `generate_sticker(description) -> image_path`：调生图 API（先抽象 `StickerProvider` interface，实现 1 个具体 provider）。按 description hash 缓存到 `data/aigc/stickers/{hash}.png`。
  - `generate_broll(text_prompt, duration, style) -> video_path`：调视频生成 API。按 prompt+style hash 缓存到 `data/aigc/broll/{hash}.mp4`。
  - `generate_cover(project_ir, ledger, style_hint) -> image_path`：**封面生成（C1）**——LLM 先从 ASR + 项目 metadata 抽取"封面文案候选"3 个 → 用户选 1 个 → 生图 API 根据封面文案 + 模板风格 + 用户首帧 → 输出 1080×1920 封面 PNG，缓存到 `data/aigc/covers/{project_id}.png`。
  - `safe_prompt(user_text) -> str`：清洗用户文本注入风险（调 moderation + 关键词过滤）。
- 触发入口：
  - **贴纸**：TemplateLibrary 模板详情页"为该模板生成所有贴纸"按钮 → 批量调 `generate_sticker` → 写回 `TemplateIR.skeleton[*].style.stickers[*].generated_image`
  - **B-roll 项目级**：Editor 页 apply 前勾选"允许 AI 补画面"checkbox → 写到 `ProjectIR.allow_aigc_broll`；apply 时缺口走 AIGC 补全（`fill_strategy="aigc_broll"`）
  - **B-roll 段级**：Editor 页 apply 后，每个 PlacedSegment 右键菜单"AI 生成画面" → 触发 `generate_broll`，prompt 从 Unit.text + 模板风格生成 → 写 `PlacedSegment.aigc_broll_path` → 重渲染
  - **封面**：Editor 页项目完成后右上角"生成封面"按钮 → 弹文案候选 3 选 1 → 调 `generate_cover` → 返回封面 + 下载链接；多次生成可不同 seed 出多版本。
- 渲染端：`Project.tsx` 中 PlacedSegment 渲染优先 `aigc_broll_path`，否则用用户原素材；Sticker 优先 `generated_image`，否则占位。封面独立产物，不入视频时间线。
- 产物披露：渲染完成的 mp4 元数据写 AIGC 段时长占比；UI 显示 AIGC 标记 + 总成本（含封面成本单列）。

### 待讨论的问题
- 具体 API 选型（Runway / Sora / Kling / 即梦 / 自部署 SD-Video）。
- 视频生成的时长上限（多数 API ≤ 6s）vs 模板槽位时长。
- 生成内容的版权策略与披露形式。
- 单段重生成的成本控制（cooldown / 余额警告）。

---

## 阶段 7: 结构重排与内容优化 📝

### 目标
基于 Phase 3 长视频分步审核管线，把 Step 06（重排建议）从占位升级为完整能力：**叙事角色识别 + 代词依赖检测 + 多版本重排建议 + 用户双时间轴对照编辑确认** → 让最终输出从"按原序"升级到"按叙事范式优化"。

### 前置条件
- Phase 3 长视频分步审核管线稳定（除 Step 06 之外的 8 个 step 均能跑通，Phase 3 6 项验证全过）。
- Phase 2.5 NL 编辑稳定，Patch 数据结构稳定（含 `reorder_sections` op）。
- Phase 3 的 `pipeline_state` 基础设施可复用（本阶段不新建管线）。
- （强化项，非阻塞）Phase 4 提供过渡分类用于重排断点平滑；Phase 5 提供 AIGC 补缺口能力。

### 设计约束（本阶段必守）
- **D3 例外**：仅本阶段允许破坏保序，且必须经 Step 06 用户审核（D12）。
- **D11**：LLM 只返回 id 序列（重排方案 = section_id 数组），绝不生成新文本、不改写 Unit.text。
- **opt-in 必须前置**：长视频项目创建时勾选"是否允许 AI 优化叙事结构"，未勾选 → Step 06 自动 Accept baseline 跳过；勾选 → Step 06 进入完整 review。**默认不勾选**（保守路径）。
- **多版本不强制 N**：勾选启用时默认 3 版本（保序 / Hook 优先 / CTA 优先）；用户可一键选保序 baseline 跳过整个 Phase 7。
- 每个版本 = 一个原子 ReorderPlan = 一个 mega-Patch，可一键回退。
- 代词/指代依赖打破时优先告警而非强行重排（保守策略）。

### 后端改动

**新数据结构**
- **新增** `backend/app/ir/narrative.py`：
  ```python
  class NarrativeScore(BaseModel):
      section_id: str
      hook_score: int          # 0-5  开头钩子能力
      sale_point_score: int    # 0-5  卖点强度
      cta_score: int           # 0-5  结尾 CTA 倾向
      transition_score: int    # 0-5  过渡价值
      energy: float            # 0-1  叙述能量
      reasoning: str           # LLM 解释（中文）

  class Dependency(BaseModel):
      source_section: str      # 含"刚刚说的"的 section
      target_section: str      # 被指代的 section
      kind: str                # 代词|话题|时间引用
      surface: str             # 触发词（"刚刚"、"上面提到"…）
      can_break: bool          # 重排后是否能容忍打破

  class ReorderPlan(BaseModel):
      version_id: str          # baseline | hook_first | cta_first | high_pace | custom
      label: str               # 显示名（"保序" / "Hook 优先" / "CTA 优先"…）
      new_order: list[str]     # section_id 数组（长度 = 原 sections 数）
      rationale: str           # LLM 给的整体逻辑说明
      warnings: list[str]      # 来自 detect_dependencies 的打破告警
      role_assignments: dict   # {section_id: assigned_role} 给 UI 染色
  ```

**叙事分析模块**
- **新增** `backend/app/agent/narrative.py`：
  - `score_sections(sections, ledger) -> list[NarrativeScore]`：Text LLM（推理模型 `MODEL_TEXT`）输入 = 每 section 的 unit_ids 对应 ASR 文本 + 时长 + 模板标签；prompt 要求按 hook/卖点/CTA/过渡四维打分并给中文 reasoning；JSON mode 输出。
  - `detect_dependencies(sections, ledger) -> list[Dependency]`：Text LLM 检测代词/指代（"刚刚说的"、"这个"、"上面提到的"、"前面"），输出依赖图；标 `can_break=false` 表示打破后语义无法理解。
  - `generate_reorder_plans(scored, deps, n=3) -> list[ReorderPlan]`：固定策略集生成：
    - `baseline`：原序恒等映射
    - `hook_first`：hook_score 最高 → 位置 0；cta_score 最高 → 最后；中间按 energy 降序
    - `cta_first`：cta_score 最高 → 位置 0（变形为引子）；hook 最强 → 位置 1；其余按原序
    - （可选）`high_pace`：短 section 集中前 1/3
    - **依赖约束**：can_break=false 的依赖在 new_order 中保持相对顺序，否则该方案标 invalid 不返回
  - `apply_reorder(project_ir, plan) -> ProjectIR`：按 new_order 重排 sections、重算每段 timeline_start、产出 mega-Patch（多个 `swap_sections` 操作的复合）→ 写 `patch_history.jsonl`。

**API**（与 Phase 3 通用 pipeline API 互补，不重复——`reorder/*` 是 Step 06 内部的特化操作集，`accept` 内部会调通用 `pipeline/steps/06/approve` 推进状态机）：
- **新增** `backend/app/api/reorder.py`：
  - `POST /projects/{id}/narrative/analyze` 触发 score + deps + plans → 返回 `{scores, deps, plans}` 写 `pipeline/06_reorder_plans.json`
  - `POST /projects/{id}/reorder/preview` body `{plan_id | custom_order}` 应用到临时副本 → 返回预览 ProjectIR（不持久化）
  - `POST /projects/{id}/reorder/accept` body `{plan_id | custom_order}` 应用到正式 ProjectIR → 内部调 `pipeline_state.approve(step_no=6)` 推进
  - `POST /projects/{id}/reorder/undo` 回退 reorder mega-Patch
- **扩展** `backend/app/agent/nl_edit.py`：新增 op `reorder_sections`（target=全局, value=`{new_order: [section_id...]}`）；NL 例如"把第 3 段放最前"翻成该 op，与 reorder/accept 殊途同归。
- **扩展** `backend/app/apply/long_pipeline.py`：Step 06 从占位升级为完整 `narrative.analyze` + 等待用户确认；自动 fallback：所有 plans 都打破强依赖 → 默认 baseline。

### 渲染服务改动
- 无新增；ProjectIR.sections 顺序变化已能按 timeline_start 正确渲染。
- （Phase 4 配套）Section 间过渡若用户接受重排版本，自动强制 fade（≥0.3s）以缓解口气突变；可在 review UI 调整。

### 前端改动
- **升级** `LongVideoEditor.tsx` 的 Step 06 review UI `StepReorderReview.tsx`：
  - **顶部 N 个版本卡片**：每卡片标 `label` + `rationale` 摘要 + warnings 数量；点击切换预览
  - **中央双时间轴**：
    - 左：原序 Sections（按 timeline_start 排，色块标 hook/卖点/CTA/过渡角色）
    - 右：新序 Sections（同上）
    - 中间：连线 + 移动方向箭头
    - 鼠标 hover 一段 → 两边联动高亮
  - **警告条**：每条 Dependency 一行（"⚠️ 第 3 段提到'前面说的'，重排后失去上下文" + can_break/can_keep 标记）
  - **自定义编辑区**：拖动右侧 Sections 调整顺序（dnd-kit）；或 NL 输入框（"把第 5 段放第 1 位"）触发 `nl_edit`
  - **三按钮**：`Accept this version` / `Customize from this version` / `Keep original (skip Phase 7)`
  - **成本显示**：本步累计 LLM token 数
- 接受后 Stepper 推进到 Step 07，沿用 Phase 3 应用模板与渲染。

### 验证方式
1. `pytest backend/tests/integration/test_narrative.py`：
   - 固定 5-Section ledger → `score_sections` 每段评分非空、reasoning 非空、各维度 0-5 范围
   - `generate_reorder_plans` 返回 ≥ 2 版本（含 baseline）；invalid 方案不返回
   - `detect_dependencies` 在已知"刚刚说的"指代场景下召回 ≥ 0.70
2. `pytest backend/tests/integration/test_reorder.py`：
   - 应用 ReorderPlan → ProjectIR.sections 顺序与 new_order 一致
   - timeline_start 重新计算正确（每段 = 上一段 end）
   - Undo 后顺序回到 reorder 前；patch history 含 reorder mega-Patch
   - 强依赖打破时 plan 不出现在返回列表
3. **端到端**：长视频 fixture → 走完 Phase 3 到 Step 06 → 看到 3 版本卡片 → 选 "Hook 优先" → 双时间轴对照 → 接受 → 渲染出 mp4 → 用户主观对比"原序版"与"Hook 优先版"，hook 强度提升明显。
4. **多版本并存**：同一 project 可以分别接受不同版本各渲一次 → outputs/ 下有多个 render_*.mp4，命名含 version_id。
5. **课题对齐**：演示视频包含一个完整的"原序 vs Hook 优先 vs CTA 优先"三版对比 case，作为"结构迁移可解释性 + 多版本生成"双亮点。

### 待讨论的问题
- 代词依赖检测的精度阈值，与"宁可不重排"保守策略的边界（误检 vs 漏检）
- 重排后段间口气突变是否需要强制 ≥0.3s fade（用户可关闭？）
- 多版本同时渲染的成本控制（建议默认只渲染选中的 1 个）
- 是否允许"混搭多个版本片段"（如 v1 的 Section 1 + v2 的 Section 2-3）
- 与 Phase 5 联动：重排后产生的新缺口能否自动触发 AIGC 补 B-roll 提示（仍需用户授权 D10）

### 课题对齐
- 任务 6 缺口补全方式 1（结构重排）：本阶段直接对应
- 任务 10 多版本生成：默认产出 ≥ 3 版本，"高点击 / 高转化 / 高节奏 / 高质感"可映射到 hook_first / cta_first / high_pace / baseline 四个 plan
- 任务 7 迁移过程可视化：双时间轴 + 角色染色 + 警告链路完整可视化

---

## 交付物

- **代码仓库**（GitHub）：backend/ + renderer/ + frontend/ 三服务，含：
  - 完整 README（项目定位 + 快速启动）
  - `docs/dev-setup.md`（详细开发环境指引）
  - `.github/workflows/ci.yml`（CI 流水线）
  - `.env.example`（环境变量模板）
  - 一键启动脚本 `pnpm dev`
- **演示视频**：2–3 个完整 case（样例 mp4 → 模板提取 → 短素材应用 → MP4 产物对比）。
- **视频产物 case**：覆盖不同模板风格 × 不同用户素材的组合结果（建议 ≥ 6 对）。
- **OpenAPI spec**：从 FastAPI 自动生成 `docs/openapi.json`，前端 / 测试可消费。
- **项目说明文档**，须含：
  - 整体 AI 架构图（含 Python/Node/前端 三服务关系 + 数据流）
  - 工具协议 IO schema（Agent 工具协议章节列举的所有 tool 的 JSON schema）
  - **AI 工具使用披露**（课题要求）：① 使用了哪些 AI 工具（WhisperX / PaddleOCR / Demucs / Text LLM / VLM / 生图 API / 视频生成 API …）；② 各工具用于哪个环节；③ 哪些部分属于自主设计与实现（IR schema、账本机制、骨架发现算法、apply/render 管线、NL 编辑 patch 协议、AIGC 触发协议、渲染队列、跨服务 IR 同步管线）
  - **安全边界**：AIGC 内容审查 + 披露；BGM features vs original 双策略 + 版权说明；用户上传内容合规审核；prompt 注入防御；ASR 错误降级；服务故障降级；数据生命周期与清理。
  - **第一性原理：视频理解技术选型**（本 plan "视频理解技术选型" 章节的精简版）：解释为何 hybrid 而非全 VLM / 全 classical。

---

## 改动点总结

### v2.4（2026-06-06）：一致性核查修复

二次核查修复了 v2.3 之前留下的 20+ 处前后矛盾、过时引用与含糊点：

**矛盾修复**：
1. **D4 描述更新**：删除已砍的"音效/高潮/变速/缩放出框"。
2. **视频理解技术选型表**：贴纸改"VLM 网格抽帧 + CV 精化"；缩放改"VLM 粗判 + CV 精化"；与 Phase 1 实际方案对齐。
3. **技术栈表**：贴纸区域改 VLM；删除已不用的 CLIP / 卡点节拍 / 视觉分类（D3）行；加 Phase 4 蒙版分割 SAM2。
4. **PipelineState 长度**：从恒为 8 改为恒为 9（加 Step 08 quality）；StepState.name 枚举加 `quality`；增加 `enable_reorder` 字段反映 Phase 7 opt-in。
5. **Step 07.5 → Step 08**：quality scoring 升级为正式 step；render 顺移至 Step 09；流程图、长 pipeline 实现、各审核组件均同步。
6. **Patch op 列表补全**：新增 `reorder_sections` / `manual_drop` / `restore_vad_segment` / `keep_dup` / `merge_sections` / `split_section` / `rename_section` / `override_unit_text`；并加 `pipeline_step` 字段标识来源 step。
7. **Phase 5 `generate_cover` 签名一致**：Agent 工具协议与实现签名同步为 `(project_ir, ledger, style_hint)`。
8. **"已明确不做"**：移除已实现的"结构重排"条；加"时间轴拖拽编辑器"、"样例端音效/高潮/变速识别"、"句级任意重排"三条明确边界。

**项目结构同步**：
9. **api/** 加 `pipeline.py`、`reorder.py`。
10. **ir/** 加 `pipeline.py`、`narrative.py`。
11. **apply/** 加 `long_pipeline.py`、`pipeline_state.py`、`quality.py`。
12. **kb/** 加 `recommend.py`。
13. **agent/** 加 `narrative.py`、`render_queue.py`；Phase 4 备注 `sfx_preset.py`。
14. **frontend pages** 加 `LongVideoEditor.tsx`；Phase 3 review 组件备注。
15. **renderer compositions** Phase 4 备注加 `ColorLayer.tsx`、`Mask.tsx`。
16. **素材目录** `projects/{id}/pipeline/` 子目录加上，列出 9 个 step 产物路径。

**数据结构澄清**：
17. **VisualStyle.speed_curve** 注释为"提取端不填"（变速识别砍掉），应用端 `PlacedSegment.speed` 才是真正的变速来源。
18. **Slot.caption_function** 注释为"Slot 内主流字幕功能（投票自多个 CaptionEvent）"，澄清单值的简化策略。

**Fixtures 一致性**：
19. **Phase 1 prereqs fixtures** 与验证 1 fixtures 一致（加 `sample_fast_pace_8s`）。

**Phase 间引用更新**：
20. **Phase 7 前置**改为"除 Step 06 之外的 8 个 step 均能跑通"。
21. **Phase 3 端到端验证**改为"走完 9 step"，包含手动标记跳过 + quality 检查的具体操作。

### v2.3（2026-06-05）：第一性原理 audit + 精简补全 + 可读性提升

**砍掉/降级（不再做的事）**：
1. **Phase 4 音效识别**砍掉。改为 **Phase 4 音效预设注入**——用户在模板上手工标注"在 X 时机加 Y 类音效"，渲染时 FFmpeg 注入。
2. **Phase 4 高潮位置**砍掉。原方案"BPM+能量+切点频率"是音乐视频高潮的定义，与口播视频的"语义高潮"概念错位；语义高潮合并到 **Phase 7 narrative.score.energy** 维度。
3. **Phase 4 画面缩放出框**砍掉。本质是横屏→竖屏的格式适配，不是风格，由 canvas 归一化处理。
4. **Phase 4 变速识别**砍掉。识别准确率 < 70%；**应用端的主动变速保留**（D8 时长自适应）。
5. **Phase 6 时间轴拖拽编辑器**移到 `docs/future-plans/001-timeline-editor.md`。前端工程量过大、与"模板自动套用"价值有张力、分步审核 + NL 编辑已覆盖 90% 微调需求。

**简化（实现路径优化）**：
6. **Phase 1 贴纸提取**：从"OpenCV 显著性 + 形态学"改为"VLM 网格抽帧 + CV 精细化 bbox"。口播脸部高显著性会污染原方案。
7. **Phase 1 缩放估计**：从"ORB+RANSAC 重型特征点"改为"VLM 粗判方向 + CV 在非稳定 scene 算 scale 曲线"。

**新增（提升项目价值）**：
8. **Phase 2 模板智能推荐（B1）**：上传素材后 VLM 看 3 采样帧 + ASR 摘要 → top-3 模板推荐 + 推荐理由。
9. **Phase 3 Step 02 用户手动标记跳过（C2）**：除去重/去静音外允许用户主动删段。
10. **Phase 3 Step 07.5 Quality scoring（C3）**：渲染前自动评估节奏/字幕密度/BGM-人声比/总时长/缺口数，超阈值时暂停 review。
11. **Phase 4 音效预设注入**：用户在模板编辑界面手工标音效触发点（新功能）。
12. **Phase 5 封面生成（C1）**：LLM 抽 3 文案候选 → 用户选 → 生图 API 出封面。
13. **Phase 7 opt-in 必须前置**：项目初始化时勾选是否允许 AI 重排（默认不勾选）。

**可读性优化（D 类）**：
14. **顶部加项目愿景 + 术语表**：陌生人 30s 看懂"我们造什么 + 关键词什么意思"。
15. **关键机制章节拆子标题**：账本机制独立子章节 + 反例说明（B3）；其余机制按类目拆开。
16. **跨服务契约加 ASCII 数据流图**。
17. **Phase 3 加 stepper 流程图**：8 step 状态可视化。

**澄清（D11 等约定）**：
18. **D11 加用户校正字幕入口**：LLM 不可改写 Unit.text，**用户可手动校正**，校正触发后续 step 重跑。

**对应课题项**（v2.3 之后真正补齐）：
- 任务 9 画面包装能力：标题条（Phase 4）+ 转场（Phase 4）+ 字幕样式（Phase 1）+ 封面（Phase 5）→ 4 项
- 任务 11 真实素材适配：模板智能推荐（Phase 2）+ Phase 7 narrative score 的"适合开头/结尾"判定
- 任务 6 补全策略：文案/包装/素材复用（Phase 2）+ 结构重排（Phase 7）+ AIGC（Phase 5）→ 4/5 项（缺重排已补）

### v2.2（2026-06-05）：补回内容优化层 + 分步审核

**新增**：
1. **D12 分步用户审核**：长视频（Phase 3）/ 结构重排（Phase 7）pipeline 在关键决策点暂停等待用户 Accept / Edit / Rerun；中间产物全部持久化到 `projects/{id}/pipeline/`，可"打回任意 step"。
2. **分步审核管线架构**章节：8 step 表 + 状态机 + Stepper UI 设计 + 与 Phase 2.5 NL 编辑的关系。
3. **Phase 3 升详写**：从原"略写"升级为完整 8 step pipeline（5 个用户审核暂停点 + Pipeline 状态持久化基础设施 + 长视频版前端 Editor）。
4. **新增 Phase 7：结构重排与内容优化**：
   - 叙事角色识别（hook/卖点/CTA/过渡 四维评分）
   - 代词依赖检测（"刚刚说的""这个"等触发词识别）
   - 多版本重排建议（默认 baseline / hook_first / cta_first 三版）
   - 双时间轴对照 review UI + dnd-kit 自定义编辑 + NL 重排指令
5. **D3 修订**：保序仍是默认，结构重排作为**唯一例外**（仅 Phase 7 经用户审核后允许）。
6. **NL 编辑扩展**：Patch 新增 `reorder_sections` op，覆盖句级模板覆盖等场景。

**对应课题项**（这次明确补齐）：
- 任务 6 缺口补全方式 1（结构重排）→ Phase 7 直接对应
- 任务 10 多版本生成（高点击 / 高转化 / 高节奏 / 高质感）→ Phase 7 默认产出 3+ 版本
- 任务 12 人工可调（hook 方式 / 卖点顺序 / 包装风格 / 视频节奏 / 结尾表达）→ Phase 3 分步审核 + Phase 2.5 NL 编辑覆盖全部
- 任务 7 迁移过程可视化 → 分步审核每 step 暴露中间产物 + Phase 7 双时间轴对照

### v2.1（2026-06-05）：细节补全 + CI/契约规范

**新增**：
1. **跨服务契约**章节：文件路径约定、IR 类型三向同步、异步进度上报、错误处理与降级、渲染队列、编解码归一化。
2. **视频理解技术选型（第一性原理）**章节：13 类提取任务的 hybrid 分配 + 调用预算。
3. **素材目录结构与生命周期**章节：4 大目录隔离 + CLI/UI 双入口 + 用户资源放置约定 + cleanup 策略。
4. **测试 / 可观测性 / CI 策略**章节：3 层测试 + 基线指标 + 日志方案 + 完整 CI workflow。
5. **Patch** 数据结构：NL/参数面板/时间轴 三个入口统一产出格式。
6. **D11 约定**：LLM 决策返回 id 而非改写文本（提级到全局约定）。
7. **BGM 双策略**：`BGM_STRATEGY=features|original`，纯音乐自动检测，原版本含版权提示。
8. **CLI ingest** 入口：dev 模式接受本地路径。

**修复**：
- 字幕多行布局从 D3 移到 D2（中文字幕天然需多行）。
- 字体策略明确：family 映射 + 本地 fonts 目录 + Remotion 加载。
- 贴纸提取方法细化（4 步 pipeline + VLM 描述）。
- WhisperX/PaddleOCR/Demucs 中文模型版本明确。
- canvas 不匹配处理（letterbox + 模糊背景）。
- BGM ducking 用 sidechaincompress 参数明确。
- 渲染并发用 p-queue 单 worker。
- 参数面板与 NL 双向 sync（避免漂移）。
- 渲染节流（300ms debounce + 取消旧任务）。

### v2（2026-06-05）：剪映退场，Remotion 上位

**核心架构变更**：
1. 剪映彻底移出主路径，改用 Remotion + FFmpeg 自闭环出 MP4。
2. MVP 收窄为"10–20s 短素材 + 用户指定模板 → 出片"；长视频自动闭环延后到 Phase 3。
3. 新增 Phase 5 AIGC 扩展（贴纸生图 + B-roll 视频生成，用户主动触发）。
4. 新增 Phase 6 时间轴拖拽编辑器（可选未来）。
5. 保真度分层重排：D2 = 切点 + 字幕（含多行）+ 缩放 + BGM 特征 + 贴纸；D3 = 转场 + 蒙版 + 调色 + 标题条 + 音效 + 高潮 + 变速 + 缩放出框。
6. 新增 D10（AIGC 用户主动触发）。

**v1 保留的关键设计**：
- IR 三层（TranscriptLedger / TemplateIR / ProjectIR）整体保留，渲染目标从 draft 换成 Remotion props + FFmpeg 指令。
- 账本机制（LLM 只返回 id 决策）保留。
- 骨架按位置阈值发现保留。
- 标签匹配 + LLM 重排选模板保留。
- 保序原则 / 时长自适应 / 缺口三法保留。

### 已明确不做（Future / 排除）

- **剪映 draft 导出**：阶段 5 后如有强需求可考虑加 ProjectIR → JianYing draft 适配器，但不在主路径。
- **时间轴拖拽编辑器**：v2.3 起从主路线移出 → `docs/future-plans/001-timeline-editor.md`，触发条件见该文档。
- **向量检索（FAISS/embedding）**：≤50 模板用标签匹配 + LLM 重排足够；上百模板后再引入。
- **Tier C 特效**（任意特效 1:1 还原）：研究级，只做白名单近似。
- **精确 BGM 曲目识别**：Demucs 特征 + 情绪标签够用；曲目指纹识别 = Future。
- **多样例融合建模**：MVP 单样例学习；多样例聚类 / 风格 averaging = Future。
- **VLM 一把梭视频理解**：放弃，原因见"视频理解技术选型"章节。
- **样例端音效/高潮/变速/缩放出框识别**：v2.3 砍掉（详见 Phase 4 已砍项）。
- **句级任意重排**：Phase 7 重排粒度恒为主题段级，不做句级（拼贴感、逻辑断裂）。

### 关键设计决策（后人重新提出方向时先查 docs/decisions/）

- **D1 输入 MP4 而非工程文件** —— 与实际使用场景吻合，无需逆向解析。
- **D7 渲染走 Remotion + FFmpeg** —— 见 v2 重构，剪映退场原因详见 `docs/decisions/001-jianying-out.md`（待写）。
- **D8 模板为可伸缩规则集** —— 样例 5–20s、产出 10s–3min，定长无法自适应。
- **D11 LLM 决策 ≠ 文本改写** —— 保证时间戳不丢、字幕同步精确、NL 编辑精确定位。
- **Python + Node 双服务** —— Python 占 ML 生态优势，Node 占 Remotion 生态唯一性，混合最务实。
- **D10 AIGC 用户主动触发** —— 避免"AI 决定一切"导致的版权/可控性问题。
- **Hybrid CV + VLM** —— 见"视频理解技术选型"章节，第一性原理推导。
- **BGM 双策略** —— 满足"个人 demo"vs"公开发布"两种使用场景。
