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
| **Tier B** | 标题条 + 音效预设注入（蒙版/调色/转场已纳入 Phase 1A）；Tier C=任意特效 1:1 仍不做 |
| **D2-core / D2-extended / D3** | D2-core=切点/字幕样式含 placeholder/缩放/BGM/贴纸（Phase 1B 集成）；D2-extended=转场/几何蒙版/调色语义（Phase 1A 单点+1B 集成）；D3=标题条+音效预设（Phase 4） |
| **保序** | 时间线上的片段顺序不被打乱（D3 默认约定；Phase 7 是唯一例外） |
| **Patch** | 对 ProjectIR 的结构化编辑操作（NL / 参数面板 / 时间轴 / 重排都产出 Patch） |
| **分步审核（Staged Review）** | 长视频管线在关键决策点暂停等待用户 Accept / Edit / Rerun（D12） |
| **VLM** | Vision-Language Model，视觉大模型；本项目视觉理解的主路径 |
| **Text LLM** | 纯文本大模型（去重 / 分段 / NL→Patch） |
| **AIGC** | AI 生成内容（贴纸图 / B-roll 视频 / 封面，Phase 5） |
| **VisionEvent** | AI 决策事件的结构化记录，每次 VLM/CV/ASR/audio/LLM 决策都发一条，含 `frame_url + bbox_norm + reasoning + ir_target` 等字段；由 event_bus 广播到 SSE + 持久化 jsonl |
| **IRTarget** | 指向 IR 树的某个节点，让工作台第三栏 IR Pane 知道事件写入了哪个字段，触发对应填充动画 |
| **AI 透明工作台 / Workbench** | 前端 `/workbench/{task_id}` 三栏页面（VLM 看到什么 / 怎么想 / 决定了什么），项目第一产品页 |
| **0-999 归一化坐标系** | VLM 输出 bbox 统一用 0-999 整数区间，客户端层 `/1000 * width` 映射到实际像素；参考 Open-AutoGLM 在生产中跑通的方案 |
| **placeholder_text / length_constraint / semantic_purpose** | VLM 在判断字幕样式时同步给出的语义占位、字符数约束、字幕功能标签；用作应用阶段 LLM 填用户字幕的视觉锚点 |
| **stage 前缀** | VisionEvent.stage 字段的命名规范，决定工作台事件染色与过滤；完整列表见"AI 调用协议·stage 命名规范"小节 |
| **SubcapabilityLab** | 前端 `/lab` 单点验证页，列出 Phase 1A 所有视觉理解子能力供独立调试 |

## Context

SceneEcho 解决一个真实痛点：**一镜到底口播视频枯燥，需要字幕动画、缩放推进、贴纸、BGM 卡点、转场这些复杂特效才能留住观众**；创作者能感受到"这条视频的剪辑风格更出效果"却很难把这种风格抽象、复用到自己的素材上。本项目从 5–20s 优质口播样例中提取「**结构骨架 + 视听风格**」模板入知识库；MVP 阶段实现"用户传 10–20s 短口播素材 + 指定一个模板 → 自动套风格出片"；后续阶段扩展到长视频自动拼接、AIGC 补画面、时间轴手动微调。

**自闭环出片，不经过剪映**：Python 后端做分析（ASR / VLM / Demucs / CV / LLM 编排），Node 服务跑 Remotion 渲染叠加层，FFmpeg 处理音视频剪接，最终输出 MP4。

**硬约束**：输入是导出后的 MP4 成片（非剪映工程文件），模板只能靠 CV / ASR / 多模态推断。

**定位补充**：本项目处于 demo / 答辩准备阶段，API 调用成本与延迟在合理范围内（单样例提取 ≤ 5 分钟）不构成约束。

**前端设计语言**：整套 UI 参照 Anthropic 官网风格（米白底 + 衬线无衬线对比排版 + 温暖橙强调色 + 细线条卡片 + 大量留白），具体 design tokens 见"跨服务契约"章节后的"前端设计语言"小节。

---

## 阶段总览

| 阶段 | 名称 | 状态 | 一句话说明 |
|------|------|------|-----------|
| 阶段 0 | 地基与渲染骨架 | ✅ 已完成 | 三服务脚手架 + IR codegen + CI；mp4 → Remotion+FFmpeg → 叠字幕的 mp4 跑通 |
| **阶段 0.5** | **AI 透明工作台骨架** | ✅ 已完成 | **SSE 事件总线 + VisionEvent IR + 前端 `/workbench` 三栏页面骨架，用 mock 事件验证渲染** |
| 阶段 1A | 视觉理解能力单点验证 | ✅ 已完成 | 字幕样式/贴纸/缩放方向/转场/调色/蒙版/动画细节，每个独立 fixture + 指标基线，VLM 调用同步发射 VisionEvent |
| 阶段 1B | 模板提取集成 | ✅ 已完成 | 串联 1A 各能力 → 完整 TemplateIR（含 D2 + Tier B 部分项）→ KB，工作台展示全链路 |
| **阶段 2** | **★MVP 应用闭环（短素材+指定模板）** | 📋 待开始 | **10–20s 口播 + 选模板 → ASR + 套风格 → MP4；模板推荐与套风格全程在工作台可见** |
| 阶段 2.5 | NL 编辑 + 参数面板 + 工作台事件回放 + 提取历史入口 | 📋 待开始 | 一句话改 IR 重渲染；Visualize 页改为对历史 VisionEvent 的可回放回顾；样例/项目详情页补"提取历史"区块与工作台面包屑 |
| **阶段 2.6** | **AI 决策工作台 v4 升级（甘特图 + 媒体时间线 + 因果链 + 回归基础设施）** | 📋 待开始 | **events 流的四种新用法：visx 壁钟甘特图 / 媒体时间线（视频时间轴 + 事件 marker + 播放头联动）/ parent_event_id 因果链可视化 / events.jsonl 反向作 ReplayClient 回归测试** |
| 阶段 3 | 长视频分步审核闭环 | 📋 待开始 | ~3min 长口播 → 9 step 流水线（含 5 个用户审核暂停点）→ 多 Section 拼接；每 step 独立事件流 |
| 阶段 4 | 标题条 + 音效预设注入 | 📝 略写 | 蒙版/调色/转场已纳入 1A 后，本阶段只剩标题条识别 + 用户手工配置的音效注入 |
| 阶段 5 | AIGC 扩展（生图 + 视频 + 封面） | 📝 略写 | 贴纸生图 + B-roll 视频生成 + 封面生成，均用户主动触发 |
| 阶段 7 | 结构重排与内容优化 | 📝 略写 | 叙事角色识别 + 多版本重排建议 + 代词依赖检测 + 双时间轴对照 + 用户编辑确认 |

> **依赖链**：0 → 0.5 → 1A → 1B → 2（★MVP）→ 2.5 → 2.6 → 3 → 7 → 4 → 5。0.5 是后续所有 VLM 调用的发射目标，必须在 1A 之前完工；1A 各能力子模块独立验证、1B 才允许集成。**Phase 2.6 放在 ★MVP 与 Phase 2.5 完工后**——理由：Phase 2 完成时工作台已有真实事件流可被甘特图消费、Phase 1B 完成时已 commit golden_runs 种子供 ReplayClient 回放；放在 Phase 3 之前则长视频 9 step 调度天然受益于甘特图视图。阶段 7 强依赖阶段 3 的分步审核基础设施；初版只依赖阶段 3，但充分体验需要阶段 5（AIGC 补缺口）协同。
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
- **D4 保真度分层**：D2-core（Phase 1B：切点/字幕样式含多行/缩放/BGM 特征/贴纸位置+描述）→ D2-extended（Phase 1A 单点验证后随 1B 一起进 KB：转场分类 / 几何蒙版语义参数 / 调色风格语义）→ D3（Phase 4：标题条 / 音效预设注入）。**字幕多行布局放 D2**（长中文字幕天然需多行）。音效识别 / 高潮位置 / 变速识别 / 画面缩放出框 不做（详见 Phase 4 "已砍项"）。
- **D5 骨架"发现"非"预设"**：基础三段（开头/主体/结尾）按位置阈值发现，所有口播必有；其余角色按样例实际出现、开放可扩展；不预设固定清单。
- **D6 选模板用标签 + LLM 重排**：≤50 模板用标签匹配 + LLM 评分足够、可解释；向量检索 = Future。
- **D7 渲染锁 Remotion + FFmpeg**：输出 MP4 自闭环，不依赖任何外部 GUI 编辑器。
- **D8 模板是「可伸缩风格规则集」**：模板编码风格 + 节奏规则，套用时按用户素材实际长度自适应铺开（槽位时长 = {min, nominal, max} 区间）。
- **D9 长视频 = 多主题段 × 模板**：长素材先按主题分段（保序），每个主题段各选一个模板，多段套完按原序拼接。
- **D10 AIGC 用户主动触发**：AI 生图（贴纸）和 AI 生视频（B-roll）**绝不自动启用**；用户通过项目级开关或段级勾选明确授权，且在产物上披露 AI 内容。
- **D11 LLM 决策 ≠ 文本改写**：所有 LLM/VLM 决策（去重/分段/选模板/打标签/NL→patch）都返回**对结构化 id 的指令**，绝不改写 `Unit.text` 或像素内容。**但用户可在审核界面手动校正 `Unit.text`**（修正 WhisperX 误识的品牌名/方言/专有名词），校正后系统自动重跑该 Unit 后续依赖的 step（字幕渲染、强调词识别等）。注意 `CaptionStyle.placeholder_text` 不属于"改写文本"——它是 VLM 看样例字幕后给出的语义占位描述（如"4-6 字 CTA 短语示例：立即抢购"），用途是给应用阶段 LLM 填用户字幕时的视觉锚点与长度约束，不是从样例 OCR 出的原文。
- **D12 分步用户审核**：长视频（Phase 3）/ 结构重排（Phase 7）等多步流水线在关键决策点（去静音 / 去重 / 主题分段 / 选模板 / 重排方案）**暂停等待用户 Accept / Edit / Rerun**；中间产物全部持久化到 `projects/{id}/pipeline/`，便于"打回任意 step"而无需从头跑。短素材场景（Phase 2）不走分步审核（一步出活，成本不值）。
- **D13 所有 AI 决策必发射 Event（强约束）**：不仅 VLM 调用，**Text LLM / ASR / VAD / Demucs / 任何 AI 决策**都通过统一的 `event_bus.publish(task_id, event)` 发射 `VisionEvent`（命名沿用，含 `source ∈ {vlm, cv, asr, audio, text_llm, system}`）。任何 AI 客户端方法返回 `(structured_result, list[VisionEvent])` 元组；未发射事件的调用视为 bug，CI 通过 grep 扫源码强制校验。这是 AI 透明工作台的可观测性底座——账本机制管"LLM 文本决策的可回滚"，事件流机制管"所有 AI 决策的可观测"，二者共同覆盖项目所有 AI 黑盒环节。

### 视频理解技术选型（第一性原理）

**核心判断**：在不计 API 成本的前提下，视觉理解任务统一交给 VLM 做主路径，CV 与专用模型只在 VLM 物理上限做不到的地方把守（帧级时间精度、音频信号处理、动画微观位移精度）。理由：①VLM 的语义化输出可直接驱动「AI 透明工作台」对用户的可解释展示，是 CV 给不了的产品价值；②VLM 的归一化坐标（参考 Open-AutoGLM 在生产中跑通的 0-999 方案，`x = coord / 1000 * width`）足够 ±5–10% 精度，覆盖字幕/贴纸/标题条/几何蒙版的"识别 + 复用"需求；③单一技术栈减少 hybrid 切换成本；④demo 阶段无规模化经济约束。

| 任务 | 主技术 | 是否调 VLM | 理由 |
|------|--------|-----------|------|
| 切点检测 | PySceneDetect | ❌ | 帧级精度（±0.04s）是 VLM 物理上限做不到的事 |
| 字幕**文本**识别 | **不做（模板提取不需要原文）** | — | 模板提取不需要原文，只需要"长什么样、怎么动"。用户素材的字幕来自用户自己的录音，模板复用的是字幕样式而非文字本身。OCR 因此整体退场 |
| 字幕位置 + 样式（颜色/字体推测/描边/字号） | **VLM 直接给归一化 bbox + 样式 JSON** | ✅ | 一次 vision call 同时返回 bbox + 视觉属性，比 OCR det + 启发式色彩分析更连贯 |
| 字幕入场/强调动画（语义类型） | **VLM 看 3 帧（出现前/中/后）判断"逐字弹入/整句滑入/淡入/打字机"** | ✅ | 语义判断 VLM 天然擅长，给出 placeholder 配合 CV 验证细节 |
| 字幕动画**微观细节**（逐帧位移曲线） | OpenCV 5fps 帧差 + 光流 | ❌ | "逐字出现的字符 stagger 时长"等 ±5px 精度细节 VLM 抽样太稀疏 |
| 字幕功能分类（标题/强调/卖点/CTA） | VLM | ✅ | 纯语义判断 |
| 字幕 `placeholder_text` 与 `length_constraint` | **VLM 在判断字幕样式时同步输出** | ✅ | 给应用阶段 LLM 填字幕的视觉锚点："这里应该填 4-6 字 CTA 短语" |
| 缩放方向粗判（推进/拉远/稳定/抖动） | VLM 看首/中/末三帧 | ✅ | 单次三帧足够 |
| 缩放关键帧曲线（仅非稳定 scene） | OpenCV `goodFeaturesToTrack` + Lucas-Kanade 光流 | ❌ | 时间序列上的 scale 值是数值任务，CV 精度高于 VLM |
| BGM 有/无 + BPM + 能量曲线 | Demucs (`htdemucs`) + librosa | ❌ | 信号处理直出，VLM 不处理音频 |
| BGM 情绪标签 | librosa 特征 + 规则映射 | ❌ | 规则可靠且零延迟 |
| 贴纸**检测**（位置 + 类型 + 时机） | **VLM 网格抽帧（每 4–6 帧一组）** | ✅ | 归一化坐标系覆盖位置精度 |
| 贴纸 bbox 精细化（±5px 边界） | CV 帧差 + Canny edge（在 VLM 给的区域内） | ❌ | VLM 给粗位置，CV 精化到像素 |
| 贴纸视觉描述 + `semantic_category` | VLM on cropped region | ✅ | 输出"强调提示/装饰/信息标签/情绪表达"分类 |
| 骨架三段划分 | 位置阈值（rule） | ❌ | D5 约定 |
| 标签建议（function/scene/notes） | VLM + Text LLM | ✅ | 综合骨架+style+音频判定 |
| 整体提取 sanity check | VLM | ✅ | 整体复查 |
| 语音转写（词级时间戳） | WhisperX (`large-v3` zh) + forced align | ❌ | 词级精度，物理上限 |
| 静音检测 | silero-VAD | ❌ | 信号处理 |
| 重复/口误识别 | Text LLM（id 决策） | ✅（text only） | 文本语义 |
| 主题分段 | Text LLM（id 决策） | ✅（text only） | 文本语义 |
| 转场分类（D2 范围） | **VLM 主判 + CV 验证** | ✅ | VLM 看相邻 scene 边界 3 帧直接判"硬切/叠化/滑入/推拉" |
| 几何蒙版（D2 范围） | **VLM 直接给几何参数（圆/线分屏/矩形 + 归一化坐标）** | ✅ | VLM 先判有无，有则一次性给参数；复杂场景 fallback SAM2 |
| 调色 LUT 语义（D2 范围） | **VLM 给"暖色/冷色/高饱和/低饱和/电影感"语义 + 直方图微调** | ✅ | 不做 1:1 LUT 提取，5–10 预设库 + VLM 语义匹配 |
| 标题条（D3 保留） | OCR 长矩形检测 + 颜色提取 | ❌ | 待评估是否也升级为 VLM；保留原方案到 Phase 4 |
| 音效预设注入（D3，**非识别**） | 模板手工标注 + FFmpeg 混入 | ❌ | 不从样例学，用户主动配 |

**所有 AI 调用必发射 VisionEvent**：见"关键机制·AI 透明工作台事件流"章节。强约束——任何 `llm.client.chat_vision()` / `chat_text()` / ASR / VAD / Demucs 等 AI 客户端方法不发事件视为 bug，CI 通过 `scripts/check_event_emission.py` 扫源码强制校验。

**VLM 调用延迟预估**（成本已不是约束）：每个模板提取约 15–30 次 VLM 调用：字幕样式 N 次 + 字幕动画 N 次 + 字幕功能 N 次 + 贴纸 N 次 + 缩放方向 N 次 + 转场 N 次 + 蒙版/调色判断 + 标签 + sanity check。单次调用 2–10s，总提取时延 ≤ 5 分钟（可接受，因为有工作台让用户清楚看到进度）。

**为什么不"VLM 一把梭"**：
1. **帧级时间精度**：切点 ±0.04s、字幕词级对齐 ±0.05s 是 VLM 物理上限做不到的，必须 PySceneDetect / WhisperX 把守。
2. **音频信号处理**：VLM 不消费音频，BGM 分离 / BPM / 能量 / VAD 必须 Demucs / librosa / silero-VAD。
3. **动画微观位移**：±5px 的逐字 stagger / 滑入轨迹需要 5fps 密集采样的帧差与光流，VLM 抽样稀疏达不到。
4. **延迟权衡**：完整 30s 视频 input 单次调用 8–15s，30 次 = 4–8 分钟。比拆解后并发的 1–3 分钟慢，且失败定位困难——拆解的子调用每个都对应工作台的一条 VisionEvent，黑盒退化为白盒。

**为什么不"Classical 一把梭"**：贴纸描述、标签语义、字幕功能分类、几何蒙版有无判断、调色情绪、转场识别这些纯语义任务，规则化做不出来，也无法给前端工作台提供可读解释。

### 技术栈

| 组件 | 选型 | 引入阶段 |
|------|------|----------|
| Python 后端 | FastAPI + uvicorn + BackgroundTasks + sse-starlette | 阶段 0 / 0.5（SSE）|
| Node 渲染服务 | Node 18+ / TypeScript / Remotion 4.x / Express | 阶段 0 |
| 前端 | React 18 + TypeScript + Vite + @remotion/player + EventSource | 阶段 0 |
| 前端 UI 组件库 | Tailwind CSS + Radix UI primitives（Anthropic 风格 design tokens 自定） | 阶段 0.5 |
| 服务通信 | HTTP + JSON IR（pydantic ↔ JSON Schema ↔ zod 三向校验） | 阶段 0 |
| 媒体处理 | FFmpeg 6+ / ffprobe / OpenCV-Python 4.x | 阶段 0 / 1A |
| 分镜切点 | PySceneDetect 0.6+ (`ContentDetector`) | 阶段 1A |
| ~~字幕字符识别~~ | ~~PaddleOCR~~（**不做**：模板提取不需要文本字符识别） | — |
| 字幕样式/动画/位置 | **VLM（归一化 0-999 坐标系）+ OpenCV 5fps 帧差/光流验证动画细节** | 阶段 1A |
| 贴纸检测 | VLM 网格抽帧 + CV 精化 bbox | 阶段 1A |
| 缩放方向 / 几何蒙版 / 调色语义 / 转场分类 | VLM 直接给参数 | 阶段 1A |
| 缩放关键帧曲线 | OpenCV `goodFeaturesToTrack` + Lucas-Kanade | 阶段 1A |
| BGM 分离 | Demucs 4.x (`htdemucs`) | 阶段 1A |
| 音频特征 | librosa 0.10+ (BPM/RMS/Spectral) | 阶段 1A |
| 语音转写 | WhisperX 3.x (`large-v3`, zh) | 阶段 2 |
| 静音检测 | silero-VAD 4.x | 阶段 3 |
| **LLM/VLM 客户端（双协议适配器）** | OpenAI-compatible + Anthropic-native 双适配器，运行时按 `MODEL_PROVIDER` env 选 | 阶段 0.5 / 1A |
| Text LLM 默认 | `claude-opus-4-7`（推理）/ `qwen-plus`（高频） | 阶段 1A / 2 |
| VLM 默认（可切换） | `qwen-vl-max-latest`（中文视觉） / `claude-sonnet-4-6`（推理+视觉）/ `gpt-4o`（cross-check 备用） | 阶段 1A |
| **VisionEvent SSE 事件总线** | sse-starlette + asyncio 内存广播 + 可选 SQLite 持久化（回放用） | 阶段 0.5 |
| **工作台甘特图可视化** | `@visx/scale` + `@visx/zoom` + `@visx/group` + `@visx/responsive`（React 友好的 D3 包装，支持 SSE 增量更新；不用命令式 D3，避免与 React 心智模型冲突） | 阶段 2.6 |
| 任务/状态存储 | SQLite + WAL 模式 | 阶段 0 |
| 渲染队列 | p-queue（Node side） | 阶段 0 |
| 日志 | structlog（Python）+ pino（Node） | 阶段 0 |
| IR 类型生成 | datamodel-code-generator + json-schema-to-zod | 阶段 0 |
| Phase 4 蒙版分割（可选 fallback） | SAM2（仅复杂场景，主路径已是 VLM） | 阶段 4 |
| 生图 API | 第三方（接 OpenAI 兼容 image endpoint） | 阶段 5 |
| 视频生成 API | 第三方（Runway/Sora/Kling/即梦，阶段 5 选型） | 阶段 5 |

### 部署架构

- **开发模式**：三服务全跑本地（Python 18521 / Node 8001 / Vite 5173）。`docs/dev-setup.md` 给一键启动脚本（`pnpm dev` 用 concurrently 起三服务 + watch IR codegen）。
- **演示/生产模式**：Python 后端 + Node 渲染服务部署到云 GPU 机器；前端可本地连云后端，也可一并部署。Python ↔ Node 通过内网 HTTP 通信，前端走对外端口；**共享存储用同机器卷或 MinIO**。
- **环境变量**（`.env`）：`RENDERER_URL`、`BACKEND_URL`、`LLM_BASE_URL`、`LLM_API_KEY`、`MODEL_PROVIDER`(openai|anthropic|mixed)、`ANTHROPIC_API_KEY`、`MODEL_VLM`、`MODEL_TEXT`、`MODEL_TEXT_CHEAP`、`DATA_ROOT`、`BGM_STRATEGY`(features|original)、`ENABLE_CLI_INGEST`(dev only)、`ENABLE_DEV_MOCK`(dev only, 工作台 mock 流)、`DUAL_CHECK_STAGES`(逗号分隔 stage 列表，启用双模型 cross-check)。

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

**异步任务与进度上报（SSE 主路径）**
- 长任务（extract/apply/render/aigc）走 FastAPI `BackgroundTasks`；任务态写 `data/kb.sqlite` 的 `tasks` 表（schema：`id, kind, status, progress, stage, resource_kind, resource_id, events_jsonl_path, last_event_sequence, result_json, error, created_at, updated_at`，含 `resource_kind ∈ {sample, project, template}` / `resource_id` / `events_jsonl_path` / `last_event_sequence` 四列定位事件流）。
- **任务进度与 AI 决策事件统一走 SSE**：前端订阅 `GET /api/tasks/{id}/events`（sse-starlette + 浏览器 EventSource）。事件类型：`progress`（任务进度）/ `vision`（AI 决策事件，含 VLM/CV/ASR/audio/text_llm 各 source）/ `stage`（pipeline step 推进）。Phase 0 阶段已部署轮询作为兜底，Phase 0.5 起 SSE 为主路径。
- 渲染端 Remotion `onProgress` callback 每 5% 回调 Python `POST /internal/task-progress` 更新 `tasks.progress`，后端继续以 `progress` event 推 SSE。

**错误处理与降级**
- Python ↔ Node：HTTP 错误返 JSON `{code, message, retry_safe: bool}`；Python 按 `retry_safe=true` 自动重试一次。
- LLM/VLM/AIGC 限流/超时：指数退避 3 次；最终失败标 Gap 为"待补全"而非 crash。
- ASR 低置信（WhisperX 平均 logprob < -0.6）：标记该段，UI 提示"需校对"。
- VLM 字幕识别失败（返回空字幕列表）但骨架推断有字幕：标记并 fallback 到无字幕骨架。
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

### 前端设计语言（Anthropic 风格 design tokens）

参照 Anthropic 官网视觉风格——克制、温暖、文档感、工具感而非娱乐感。所有页面（SampleExtract / TemplateLibrary / Editor / LongVideoEditor / Workbench / WorkbenchGantt / SubcapabilityLab / Visualize）共用同一套 token，**禁止逐页面自创色板**。

```css
/* 颜色 · 写入 frontend/src/styles/tokens.css */
:root {
  /* 背景层级 */
  --bg-canvas: #FAF9F7;          /* 主背景，温暖米白 */
  --bg-surface: #FFFFFF;         /* 卡片/面板背景 */
  --bg-subtle: #F5F4F0;          /* 次级面板/输入框 */
  --bg-inverted: #1F1E1C;        /* 工作台中栏的暗背景日志区可选 */

  /* 文字层级 */
  --text-primary: #1F1E1C;       /* 正文 */
  --text-secondary: #6B6962;     /* 次级说明 */
  --text-tertiary: #A8A49B;      /* 元信息/时间戳 */
  --text-inverted: #FAF9F7;

  /* 强调色（暖橙系，Anthropic logo 衍生） */
  --accent-primary: #CC785C;     /* CTA 按钮、活跃 step、当前 VLM 高亮 bbox */
  --accent-hover: #B86A50;
  --accent-subtle: #F5E5DD;      /* 强调色的弱填充（被选中卡片背景） */

  /* 语义色（克制使用） */
  --color-success: #5C8A6E;
  --color-warning: #C99846;
  --color-error: #C76B5A;
  --color-info: #6B8CAE;

  /* 边框 */
  --border-default: #E8E5DE;     /* 细线条卡片用 */
  --border-strong: #C9C5BC;
  --border-focus: var(--accent-primary);

  /* 字体 */
  --font-serif: "Source Serif 4", "Source Han Serif SC", Georgia, serif;
  --font-sans: "Inter", "Source Han Sans SC", -apple-system, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "Source Han Sans Mono", Consolas, monospace;

  /* 间距（克制留白，8px 基准 + 大模块用 24/48） */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-6: 24px; --space-8: 32px; --space-12: 48px; --space-16: 64px;

  /* 圆角（细微，避免 ios 过圆） */
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 8px;

  /* 阴影（极少用；偏向用边框分层） */
  --shadow-subtle: 0 1px 2px rgba(31, 30, 28, 0.04);
  --shadow-card: 0 1px 3px rgba(31, 30, 28, 0.06), 0 1px 2px rgba(31, 30, 28, 0.04);
}
```

**关键应用规则**：
- **卡片**默认 `bg-surface + border-default + radius-md`，**不用 shadow**——边框承担分层，符合 Anthropic 的文档感
- **按钮**：主按钮 `accent-primary` 填充 + 白字；次按钮透明 + `border-default` + `text-primary`；危险按钮 `color-error` 边框 + 文字（不填充）
- **AI 工作台第二栏（语义日志）**用 `bg-inverted + text-inverted + font-mono`，制造"AI 内部思考"的可读感（类似 IDE 调试面板）
- **VLM bbox 高亮**：`border: 2px solid var(--accent-primary)` + 标签气泡 `bg-accent-subtle + text-accent-primary`
- **强调文字**用 serif 字体（标题、模板名、Section 名），正文用 sans，代码/日志用 mono——三体并用制造 Anthropic 的"出版物"感
- **大量留白**：单页面有效内容宽度不超过 1280px，外围都是 `--space-12`+ 的边距

**组件库选型**：Tailwind CSS（写入 `frontend/tailwind.config.ts` 把上述 tokens 注册为 theme.extend）+ Radix UI primitives（Dialog/Dropdown/Tooltip/Tabs 用 Radix 无样式版本，外观用 token 套）。**不引入 MUI / Ant Design / Chakra**——它们的视觉语言与 Anthropic 风格冲突。

**插画与图标**：lucide-react（线条克制、weight 一致）。绝不用 Material Icons / Font Awesome。

**动效原则**：所有过渡 200-300ms ease-out；工作台事件出现用 80ms 短淡入 + 4px 上移；bbox 高亮用 1.5s fade-in-out 循环。**禁止任何"弹性 spring"动画**——会破坏文档感。

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
│  ├─ luts/                        # 调色预设库（5-10 个），VLM 调色语义匹配的目标 ID 集合
│  │  └─ luts_index.json           # {id, name, hue_shift, saturation, brightness, category}
│  ├─ sfx_pool/                    # 音效池（Phase 4 音效预设注入用）
│  │  ├─ {sfx_id}.mp3
│  │  └─ sfx_index.json            # {id, name, category, file_path}
│  └─ models/                      # ML 模型缓存
│     ├─ whisperx/
│     └─ demucs/
├─ samples/                        # 提取模板的样例（输入）
│  └─ {sample_id}/
│     ├─ source.mp4                # 原始上传
│     ├─ normalized.mp4            # FFmpeg 归一化版
│     ├─ thumbnail.jpg             # 首帧
│     └─ extracted/                # 中间产物
│        ├─ scenes.json
│        ├─ captions.json          # VLM 给的 CaptionStyle 列表（非 OCR 原文）
│        ├─ stickers_crops/        # 贴纸区域裁图
│        ├─ bgm_stem.wav           # Demucs 分离的 BGM
│        ├─ frames/                # 关键帧抽样器输出 {ts}.jpg，VLM 调用与工作台共用
│        ├─ events_{task_id}.jsonl # 本次 extract 任务的 AI 决策事件流（每次 ingest/rerun 一文件）
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
│     │  ├─ pipeline_state.json
│     │  ├─ events_{task_id}.jsonl # 本次 apply/long-pipeline 任务的事件流
│     │  └─ frames/                # 用户素材关键帧抽样 {ts}.jpg（apply 阶段 VLM 与工作台用）
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
├─ docs/{PLAN.md, dev-setup.md, decisions/, future-plans/, proposals/, 003ISSUES.md}
│                                   # proposals/ 含 001-ai-decision-workbench-v4.md 等架构提案
├─ .github/workflows/{ci.yml, release.yml}
├─ shared/
│  └─ ir.schema.json                # pydantic 导出的 JSON Schema（含 VisionEvent / IRTarget）
├─ scripts/
│  └─ gen_schema.py                 # pydantic → JSON Schema
├─ backend/                         # Python FastAPI
│  ├─ pyproject.toml                # 依赖: sse-starlette, anthropic
│  ├─ ruff.toml
│  ├─ .venv/                        # gitignore
│  └─ app/
│     ├─ main.py                    # FastAPI 入口（挂载 api/events.py）
│     ├─ config.py                  # 环境变量加载（含 model_provider/anthropic_api_key/enable_dev_mock/dual_check_stages）
│     ├─ cli.py                     # ingest 命令（dev only）
│     ├─ tasks_store.py             # tasks 表 CRUD（含 resource_kind/resource_id/events_jsonl_path/last_event_sequence）
│     ├─ event_bus.py               # asyncio 内存广播 + jsonl 持久化 + replay
│     ├─ api/{samples, templates, projects, edit, tasks, pipeline, reorder}.py
│     │                             # 额外: events.py(SSE) / replay.py / dev_workbench.py / lab.py(Phase 1A 子能力调试)
│     ├─ ir/{template, project, ledger, patch, pipeline, narrative, export}.py
│     │                             # 额外: vision_event.py（VisionEvent + IRTarget）
│     ├─ extract/{scenes, motion, captions, audio, stickers, skeleton, normalize, pipeline}.py
│     │                             # Phase 1A 额外: frame_sampler.py / captions_anim.py / transitions.py / masks.py / color.py
│     │                             # Phase 4 增: title_bar.py
│     ├─ understand/{asr, vad, dedup, segment, vision}.py
│     ├─ apply/{mapping, gaps, fill, style, pipeline, long_pipeline, pipeline_state, quality}.py
│     ├─ render/{client.py, ffmpeg.py}
│     ├─ kb/{store, tagging, select, recommend}.py
│     ├─ agent/{tools, orchestrator, nl_edit, aigc, narrative, render_queue}.py
│     │                             # Phase 4 增: sfx_preset.py
│     ├─ llm/{client.py, prompts/}  # OpenAICompatClient + AnthropicClient 双适配器
│     │   └─ prompts/scenarios/     # mock 工作台事件脚本（dev only）
│     └─ logging.py                 # structlog 配置
│  └─ tests/{unit/, integration/, conftest.py}
│                                   # 仅后端单测/集测代码；fixtures 与 golden_runs 在项目根的 tests/fixtures/ 下，
│                                   # 由 backend/tests/conftest.py 通过 REPO_ROOT/tests/fixtures 引用
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
│     ├─ preflight.ts               # 渲染前资源完整性检查（Phase 2 引入）
│     ├─ types/ir.ts                # generated from JSON Schema（含 VisionEvent）
│     └─ compositions/
│        ├─ Project.tsx
│        ├─ Caption.tsx             # 支持 placeholder_text 渲染（模板预览模式）
│        ├─ ZoomLayer.tsx
│        ├─ Sticker.tsx
│        ├─ Mask.tsx                # 几何蒙版（Phase 1B 集成）
│        ├─ ColorLayer.tsx          # 调色层（Phase 1B 集成）
│        ├─ TitleBar.tsx            # Phase 4
│        └─ Transition.tsx          # Phase 4
├─ frontend/                        # React + Vite
│  ├─ package.json                  # 依赖: tailwindcss, @radix-ui/react-*, lucide-react
│  ├─ vite.config.ts
│  ├─ tailwind.config.ts            # 注册 design tokens 到 theme.extend
│  ├─ scripts/gen-types.ts
│  └─ src/
│     ├─ api/{index, events}.ts     # events.ts: subscribeEvents / fetchEventHistory / fetchReplayEvents
│     ├─ types/ir.ts                # generated from JSON Schema
│     ├─ styles/tokens.css          # Anthropic 风格 design tokens（颜色/字体/留白/圆角）
│     ├─ pages/
│     │   ├─ SampleExtract.tsx
│     │   ├─ TemplateLibrary.tsx
│     │   ├─ Editor.tsx
│     │   ├─ LongVideoEditor.tsx
│     │   ├─ Workbench.tsx          # 核心三栏工作台（/workbench/:taskId）
│     │   ├─ Visualize.tsx          # 事件回放器（/projects/:id/replay）
│     │   └─ SubcapabilityLab.tsx   # 1A 子能力单点验证（/lab，dev only）
│     ├─ components/
│     │   ├─ RemotionPlayer.tsx
│     │   ├─ ParamPanel.tsx
│     │   ├─ NLBar.tsx
│     │   ├─ TaskProgress.tsx
│     │   ├─ workbench/             # 三栏组件 + 公共组件
│     │   │   ├─ WorkbenchVisionPane.tsx
│     │   │   ├─ WorkbenchEventStream.tsx
│     │   │   ├─ WorkbenchIRPane.tsx
│     │   │   ├─ BboxOverlay.tsx    # 帧上 SVG bbox + 气泡
│     │   │   └─ EventBadge.tsx     # stage 染色徽章
│     │   └─ review/                # Phase 3 增：StepVADReview / StepDedupReview / StepSegmentReview /
│     │                             #   StepSelectReview / StepReorderReview / StepFinalReview / StepQualityReview
│     └─ state/                     # Zustand stores（含 workbench.ts: events/filterStage/irSnapshot）
├─ tests/                           # 项目根 fixtures 与 golden runs（跨服务共享 + git tracked）
│  └─ fixtures/
│     ├─ {sample_id}/source.mp4     # 开发期 fixtures（S12 路径约定）
│     ├─ baselines.json             # CI 指标基线
│     └─ golden_runs/               # 每个标杆样例的 events.jsonl + template.json 作 ReplayClient 回归 fixture
│        └─ {sample_id}/{events.jsonl, template.json}
├─ pnpm-workspace.yaml              # 管理 renderer + frontend
├─ .gitignore
├─ .env.example                     # 含 MODEL_PROVIDER / ANTHROPIC_API_KEY / ENABLE_DEV_MOCK / DUAL_CHECK_STAGES
└─ README.md
```

### 总体数据流
```
[样例 mp4] ─extract─▶ TemplateIR ─▶ KB（带标签）
     │      │                  │  用户指定 template_id（Phase 2）/ 自动 select（Phase 3）
     │      └─VisionEvent─┐    │
     │      stream         │    │
[用户口播素材] ─understand─▶ 账本 ─┐   │
     │      │              ▼     ▼
     │      │  apply: 映射 + 缺口识别 + 缺口补全 + 套风格
     │      ├─VisionEvent stream──┤
     │      │                     ▼
     │      │   ProjectIR（保序 EDL + Caption 列表）
     │      │                     │ render.client
     │      │                     ▼
     │      │   Node Remotion 服务 + FFmpeg
     │      │                     ▼
     │      │                 MP4 产物
     ▼      ▼
┌────────────────────────┐
│  event_bus              │   ←── 所有 AI 决策（VLM/CV/ASR/audio/text_llm）发事件至此
│  (asyncio in-memory     │
│   + jsonl 持久化)        │
└─────────┬──────────────┘
          │ SSE /api/tasks/{id}/events  (event 类型: vision / progress / stage)
          ▼
┌────────────────────────────────────────────────────────────────┐
│  AI 透明工作台 /workbench/{task_id}（项目第一产品页 · 三栏）      │
│  ┌─────────┬─────────┬─────────┐                              │
│  │ VLM 看到 │ VLM 怎么 │ VLM 决定 │  事件回放页 /projects/{id}/replay │
│  │ 帧+bbox  │ 想 reason│ IR 填充  │  按 sequence 重播全过程         │
│  └─────────┴─────────┴─────────┘                              │
└────────────────────────────────────────────────────────────────┘

[自然语言指令 / 参数面板修改] ─agent.nl_edit─▶ Patch ─▶ 重渲染（同时发 VisionEvent）
[用户勾选 AI 补画面]        ─agent.aigc────▶ 调外部 API ─▶ 替换素材（同时发 VisionEvent）
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

#### AI 透明工作台事件流（与账本机制并列的项目第二 novel 设计）

**核心**：所有 AI 决策（VLM 视觉、Text LLM 文本、ASR 转写、Demucs/librosa 音频、CV 信号处理）同步发射结构化的 `VisionEvent`，通过 SSE 事件总线实时推送到前端 `/workbench/{task_id}` 三栏页面。AI "看到/听到什么 / 怎么想 / 决定了什么"三件事被结构化、可订阅、可回放、可否决。

**为什么这么设计**——用一个反例说明：

如果让 VLM 的视觉理解输出"只返回结构化结果给后端处理"，会发生：
1. 用户上传样例后等 30s–5min 才看到结果，整段过程是黑盒，焦虑感真实存在
2. 评审打开系统看不到 AI 在"做什么"，"迁移过程可视化"评分项只能事后回看 Visualize 页
3. VLM 给出错误识别时（比如把广告条认成 CTA 字幕），用户无法在过程中干预，只能等结果出来后整体重跑
4. "AI 决策的可解释性"加分项缺乏过程证据，只能靠最终 IR 的文字说明

**工作台机制下**：
- `llm.client.chat_vision(messages, model)` 强制返回 `tuple[structured_result, list[VisionEvent]]`
- VLM 客户端层在返回时自动调 `event_bus.publish(task_id, events)` 广播到所有订阅者
- 前端 `EventSource('/api/tasks/{id}/events')` 实时拿到事件流，按 stage 分组渲染到三栏
- 左栏：根据 `frame_url` + `bbox_norm` 在帧上叠加 bbox 高亮；右栏：根据 `ir_target` 触发 IR 字段填充动画；中栏：按 `sequence` 时序展示 `reasoning` + `semantic_label` + `confidence`
- 用户在中栏可对任一事件"否决" → 产生 `reject_vision_event` Patch → 触发该子能力 rerun（保留账本机制的"决策可回滚"语义）

**事件持久化**：每个任务的事件流按资源 kind 分支路径落对应资源目录——`samples/{sid}/extracted/events_{task_id}.jsonl`（样例提取任务）或 `projects/{pid}/pipeline/events_{task_id}.jsonl`（项目应用任务），由 `event_bus.publish` 根据 `tasks.resource_kind + resource_id` 路由（详见"核心数据结构 · VisionEvent · 持久化路径"小节）。Phase 2.5 的回放页面可按时间顺序重播全过程，作为答辩 demo 录屏的素材库。

**与账本机制的关系**：
- 账本机制管的是"LLM 文本决策的可解释与可回滚"（id 决策 + Unit 不可变）
- 工作台事件流管的是"所有 AI 决策的可观测与可干预"（VisionEvent + 事件回放，含 Text LLM/ASR/audio/CV/VLM）
- 二者共享设计哲学：**AI 决策对人类透明、可结构化追溯、可干预、不丢失中间态**

**水平扩展约束（已知 trade-off · S2）**：`event_bus` 当前是单进程内存广播（`asyncio.Queue` + `dict[task_id, list[Queue]]`）。MVP 单实例后端足够；若未来部署多 worker 后端，需替换为 Redis pub/sub（`channel = events:{task_id}`）或专用消息队列。这一限制在 demo 阶段不构成阻塞。

#### AI 调用协议（强约束 · 拓宽到全部 AI 客户端）

**契约**：

```python
def chat_vision(
    messages: list[dict],
    model: str,
    stage: str,                      # "1A.captions" / "1A.stickers" / ...
    task_id: str,                    # 用于事件总线广播
    frames: list[FrameRef] | None,   # 输入帧的引用（含 ts 与 url），用于自动填 VisionEvent.frame_ts/frame_url
    ir_target_template: IRTarget | None,  # 调用方预声明本次调用结果会写入哪个 IR 节点
    schema: type[BaseModel],         # 强制结构化输出（pydantic 校验）
) -> tuple[BaseModel, list[VisionEvent]]:
    ...
    # 内部行为：
    # 1. 调外部 VLM API（OpenAI/Anthropic 双适配器自动选）
    # 2. 用 schema 校验返回 JSON
    # 3. 自动构造 VisionEvent 列表（每个识别到的实体一个事件）
    # 4. 客户端层用 time.perf_counter() 自动测得 duration_ms 写入每个 event（外层调用方零侵入）
    # 5. 调 event_bus.publish(task_id, events) 广播
    # 6. 返回 (structured_result, events) 元组
```

**对其他 AI 客户端方法的同等约束（D13）**：`chat_text()`、ASR、Demucs 等所有 AI 调用必采用相同模式——返回 `tuple[BaseModel, list[VisionEvent]]` 元组，内部调 `event_bus.publish()`，event.source 按调用类型填 `text_llm` / `asr` / `audio` 等。签名规范：

```python
def chat_text(
    messages: list[dict],
    model: str,
    stage: str,                      # "2.5.nl_edit" / "3.step03.dedup" / "3.step04.segment" / ...
    task_id: str,
    ir_target_template: IRTarget | None,
    schema: type[BaseModel],
    silent: bool = False,
) -> tuple[BaseModel, list[VisionEvent]]:
    ...    # 内部行为同 chat_vision，event.source="text_llm"

def transcribe(
    audio_path: str,
    stage: str,                      # "3.step01.asr" / "2.asr"
    task_id: str,
    ir_target_template: IRTarget | None,
) -> tuple[TranscriptLedger, list[VisionEvent]]:
    ...    # event.source="asr"，每个 Unit 一条事件或按句聚合

def extract_bgm(
    normalized_path: str,
    save_stem: bool,
    task_id: str,
    stage: str = "1A.audio",
) -> tuple[AudioStyle, list[VisionEvent]]:
    ...    # event.source="audio"，has_bgm / bpm / mood 各发一条
```

CI 通过 `scripts/check_event_emission.py` grep 所有 AI 客户端方法定义，校验函数体内是否调用了 `event_bus.publish`；缺则 fail。

**编码规范**：
- 调用方必须传 `stage`、`task_id`、`ir_target_template`，缺一个 CI 红
- 调用方拿到 `events` 后不需要手动发布——客户端层已经发了；events 列表的作用是让调用方可以在拿到结果后做后续逻辑（如选其中 confidence 最高的事件做下一步动作）
- 工作台页面的"事件类型"染色按 `stage` 前缀（如 `1A.*` 用蓝色、`2.*` 用绿色、`3.*` 用橙色）

**模型选择策略**：
- 默认 `qwen-vl-max-latest`（中文最优、单调用 2–5s）
- **dual-model cross-check 启用规则（S3）**：默认关闭。要启用，在 `.env` 设 `DUAL_CHECK_STAGES="1A.captions.semantic_purpose,1A.masks.has_mask,1A.color_lut.dominant_tag"` 列出需要双模的具体 stage。客户端层在 `chat_vision()` 内检查当前 `stage` 是否命中列表，命中则自动走 `chat_vision_dual()`：并发调 Qwen + Claude，两者**结构化字段**一致才写入 IR，否则在 VisionEvent 加 `confidence_warning=True` 提示用户在工作台 review。延迟翻倍、token 翻倍是已知代价，仅用于真正关键的决策。
- Provider 切换由 `MODEL_PROVIDER` env 控制（`openai` | `anthropic` | `mixed`）。`mixed` 模式按 `stage` 前缀路由（如 1A 视觉走 OpenAI 兼容 Qwen，2.recommend 文本推理走 Anthropic Claude），具体路由表在 `llm.client.PROVIDER_ROUTING_TABLE` 维护。
- **silent 模式**：`chat_vision(..., silent=True)` 时跳过 `event_bus.publish` 但仍 log；用于背景 sanity check 等不需要在工作台展示的辅助调用，避免事件流被次要事件淹没。

#### stage 命名规范（强约束 · H2）

VisionEvent.stage 字段所有合法取值集中在此表，工作台前端按 stage 前缀染色与过滤：

| Stage 模式 | 阶段 | 染色 | 示例 |
|-----------|------|------|------|
| `0.5.mock` | Phase 0.5 mock 流 | 灰 | `0.5.mock.captions_demo` |
| `1A.{capability}` | Phase 1A 子能力 | 蓝 | `1A.scenes` / `1A.captions` / `1A.captions_anim` / `1A.stickers` / `1A.zoom_direction` / `1A.zoom_curve` / `1A.transitions` / `1A.masks` / `1A.color_lut` / `1A.audio` / `1A.caption_function` |
| `1B.{step}` | Phase 1B 集成 | 蓝 | `1B.skeleton` / `1B.tagging` / `1B.sanity_check` |
| `2.{step}` | Phase 2 应用 | 绿 | `2.recommend` / `2.asr` / `2.mapping` / `2.gaps` / `2.fill` / `2.style.caption` / `2.style.bgm` |
| `2.5.nl_edit` | Phase 2.5 NL 编辑 | 紫 | `2.5.nl_edit` |
| `3.step{NN}.{kind}` | Phase 3 长视频 step | 橙 | `3.step01.asr`（ASR 转写，source="asr"）/ `3.step02.vad` / `3.step03.dedup` / `3.step04.segment` / `3.step05.select` / `3.step06.reorder.score` / `3.step06.reorder.deps` / `3.step06.reorder.plan` / `3.step07.apply` / `3.step08.quality` / `3.step09.render`（渲染进度，event 类型 progress 而非 vision）|
| `4.{capability}` | Phase 4 | 青 | `4.title_bar` / `4.sfx_preset` |
| `5.aigc.{kind}` | Phase 5 AIGC | 粉 | `5.aigc.sticker` / `5.aigc.broll` / `5.aigc.cover` |

**注意**：Phase 7 重排逻辑虽是"叙事分析"，但实际是 Phase 3 Step 06 的实现，stage 沿用 `3.step06.reorder.*`，**不**用 `7.narrative.*`——避免 stage 前缀与 phase 号交叉冲突，工作台按 stage_filter 时统一在 `3.*` 命名空间下。

**新增 stage 时**：必须先在本规范表添加，再写代码；CI 校验 `git grep -nE 'stage="[^"]+"'` 出现的所有字面量是否都匹配本表前缀模式（脚本 `scripts/check_stage_naming.py`）。

#### SSE 服务端约定（强约束 · H3）

`GET /api/tasks/{task_id}/events` 端点的响应格式：每条 SSE event 必须由三行组成，**`id:` 字段不可省略**——浏览器原生 EventSource 依赖这个字段在重连时自动通过 `Last-Event-ID` header 回传：

```
id: {event.event_id}
event: vision
data: {json.dumps(event.model_dump())}

```
（双换行表示 event 结束。）

服务端处理 `Last-Event-ID` header 时：从 `event_bus.replay(task_id, from_event_id=...)` 拿到 last event 之后的所有历史事件先推，再订阅 live queue 推后续。心跳每 15s 发空 comment `: heartbeat\n\n` 保活。

前端封装 `frontend/src/api/events.ts::subscribeEvents()` 直接用浏览器 EventSource 不需手动管理 last id（浏览器自动维护）；只需在 onError 时记录最后看到的 event_id 供调试。

#### 提取流水线（Phase 1B 集成）

```
FFmpeg 归一化
  → 切点（PySceneDetect）                              ← 时间精度专用工具
  → 关键帧抽样器（采样首/中/末 + 各切点前后 + 1fps 全局，
                  写 data/samples/{id}/extracted/frames/{ts}.jpg，
                  作为后续所有 VLM 调用的输入帧源 + 工作台左栏的展示源）
  ↓
  ↓ 以下子流程并发执行，每个 VLM 调用同步发射 VisionEvent ↓
  ├─ 字幕（VLM 主）：位置 + 样式（颜色/字体推测/描边/字号）+ 动画类型 + placeholder_text + length_constraint + semantic_purpose
  ├─ 字幕动画细节（CV）：5fps 采样 + 帧差 + Lucas-Kanade 光流，验证 VLM 给的 anim_in 类型的微观细节
  ├─ 贴纸：VLM 网格抽帧（每 4-6 帧一组）→ 描述 + position_norm + semantic_category；CV 帧差 + Canny 精化 bbox 到 ±5px
  ├─ 缩放方向（VLM）：看首/中/末三帧粗判推进/拉远/稳定/抖动
  ├─ 缩放关键帧曲线（CV，仅非稳定 scene）：goodFeaturesToTrack + Lucas-Kanade 光流采样 5fps
  ├─ 转场分类（VLM）：看相邻 scene 边界 3 帧判硬切/叠化/滑入/推拉
  ├─ 几何蒙版（VLM）：看采样帧判有无 + 几何参数（圆/线分屏/矩形 + 归一化坐标）；SAM2 仅复杂场景 fallback
  ├─ 调色语义（VLM）：看采样帧给"暖/冷/高饱和/低饱和/电影感"标签 + 直方图微调匹配 5–10 LUT 预设库
  └─ BGM（Demucs + librosa）：分离 → BPM / energy / mood，按 BGM_STRATEGY 决定保留 stem
  ↓ 各子流程结果归并 ↓
  → 骨架发现（位置阈值 rule：0–30%/30–70%/70–100%）
  → 字幕功能分类（VLM 综合各 Caption 段位置 + ASR 上下文 → CTA/标题/卖点/强调/regular）
  → 标签建议（VLM + Text LLM，看 3 采样帧 + 骨架概要 + StyleRule 摘要）
  → sanity check（VLM 看整体 + KB 对比）
  → 入 KB（事件流落 events.jsonl）
```

**Phase 1A 单点验证版本**：上述流程的每个 ◯VLM 节点 / ◯CV 节点都先独立交付——独立 fixture + 独立指标基线 + 独立工作台事件流验证。1A 全过后才允许在 1B 串成上面这条线。详见 Phase 1A 节。

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
- AI 调用 token 数（LLM/VLM/ASR 等）累计到 `pipeline_states.llm_cost`，UI 显示成本。
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

**CI 校验脚本**（在 Phase 0.5 实施时一并创建）：
- `scripts/check_stage_naming.py`：grep 源码所有 `stage="..."` 字面量，校验是否匹配"stage 命名规范"表的前缀模式；不匹配则 fail（参考 H2）
- `scripts/check_event_emission.py`：grep 所有 AI 客户端方法定义（`def chat_vision` / `def chat_text` / `def transcribe` / `def extract_bgm` 等），校验函数体内是否调用了 `event_bus.publish`；缺则 fail（参考 D13）
- `scripts/check_parent_event_id.py`：grep 所有"两阶段"VLM 调用点（命名匹配 `*_refine` / `*_phase2` / `*_classify`），校验函数体内 `chat_vision()` 调用是否传了 `parent_event_id=` 关键字参数；缺则 fail（参考 Phase 1A 设计约束 + Phase 2.6 因果链）

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

### VisionEvent（AI 透明工作台的核心 IR）

每次 AI 决策的"副产品"（D13 拓宽，含 VLM/Text LLM/ASR/audio/CV），由 `llm.client.chat_vision()` / `chat_text()` / 各 AI 客户端方法强制返回，由 `event_bus` 广播到前端工作台。它把 AI "看到什么 / 怎么想的 / 决定写入 IR 哪个字段"三件事结构化。

```python
class IRTarget(BaseModel):
    """指向 IR 树的某个节点，让前端工作台第三栏的字段填充动画能精确触发"""
    ir_type: Literal["TemplateIR", "ProjectIR", "TranscriptLedger"]
    path: str            # **lodash get/set 风格**（不是标准 JSONPath）：点+方括号路径
                         # 示例："skeleton.slots[1].style.caption" / "sections[0].segments[2].applied_style"
                         # 前端用 lodash.set(state.ir, path, value) 做增量写入（S14）
    field: str | None    # 如果是给某个字段赋值："placeholder_text"
    op: Literal["set", "append", "remove"] = "set"

class VisionEvent(BaseModel):
    event_id: str        # UUID，便于工作台中央栏跳转回放
    task_id: str         # 关联到任务表，前端按 task_id 订阅 SSE
    sequence: int        # 任务内单调递增，前端按 sequence 排序与去重
    timestamp: str       # ISO8601；事件**起始**时刻
    duration_ms: int = 0 # 事件持续时长（毫秒）。长程任务（如一次 VLM 调用从发请求到收响应）填实际耗时；瞬时事件（如"切点检测"）填 0。甘特图横条按 [timestamp, timestamp + duration_ms] 画区间；0 渲染为竖线
    source: Literal["vlm", "cv", "asr", "audio", "text_llm", "system"]
    model_used: str | None       # AI 调用时填具体 model id（VLM/Text LLM 都填），便于 cross-check 对比；CV/audio 等非模型来源填 None
    stage: str           # 见"AI 调用协议·stage 命名规范"小节；示例 "1A.captions" / "3.step03.dedup" / "5.aigc.sticker"
    frame_ts: float | None       # 视频时间戳（如果事件由某帧触发）
    frame_url: str | None        # /data/{kind}/{id}/extracted/frames/{ts}.jpg
    bbox_norm: tuple[float, float, float, float] | None  # 0-999 归一化 (x, y, w, h)；None 表示事件不针对具体位置
    semantic_label: str          # "CTA字幕" | "强调贴纸" | "推进缩放" | "硬切转场" | "暖色调"
    reasoning: str               # VLM 给的中文解释（≤ 200 字），原文直接展示在工作台中栏
    confidence: float            # 0-1
    ir_target: IRTarget | None   # 这条事件最终写入了 IR 哪个字段
    ir_value: dict | None        # 写入的具体值（前端工作台第三栏拿来做字段填充动画）
    parent_event_id: str | None  # 事件的因果链（"贴纸语义判断" 依赖 "贴纸 bbox 检测"），便于工作台连线可视化。**强约束**：所有两阶段 VLM 调用（粗判 → 精化）的第二阶段事件必填此字段指向第一阶段 event_id（详见 Phase 1A 设计约束 + Phase 2.6 因果链可视化）；前端从 events 列表反向 O(1) 增量构建 `childIndex: Map<parentId, eventId[]>`，不冗余存 child_event_ids 字段
    cost_tokens: int | None      # AI 调用 token 数（VLM/Text LLM 都填），工作台可展示但不当作核心约束；CV/audio 等非 token 来源填 None
```

**生命周期**：内存广播（asyncio queue）+ 任务持久化。

**持久化路径（方案 B：按资源 kind 分支）**：events 文件随资源走，task_id 作为文件后缀：
- 样例提取任务：`data/samples/{sample_id}/extracted/events_{task_id}.jsonl`
- 项目应用任务：`data/projects/{project_id}/pipeline/events_{task_id}.jsonl`

由 `event_bus.publish(task_id, event)` 根据 `tasks.resource_kind + tasks.resource_id` 字段路由到对应路径（tasks 表写入时落 `events_jsonl_path` 全路径缓存）。同一资源被多次 extract/apply 时，每个 task_id 一份独立文件；删 sample/project 时整目录级联清理；step rerun 时按 task_id 软关闭旧文件、新建新文件。

**sequence 并发分配（强约束 · S1）**：`event_bus` 内部维护 `dict[task_id, AtomicCounter]`，`publish()` 在落盘前原子 `counter.next()` 分配 sequence。同一 task_id 下 1A 各子能力并发发事件时，sequence 仍保证全局单调递增。跨 task_id 的 sequence 不可比较（前端按 sequence 排序仅在同 task 维度有效）。

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
    position: tuple[float, float]  # 归一化坐标 (0~1)，渲染时映射，与 VLM 0-999 坐标系做一次 /1000 转换
    layout: str = "single"         # single | multi（D2 支持多行）
    max_chars_per_line: int = 12   # D2 多行布局参数
    anim_in: str                   # 逐字弹入|整句滑入|淡入|打字机|unknown
    anim_emphasis: str | None      # 关键词高亮|抖动|放大|None
    emphasis_words: list[str] = [] # VLM 识别出的强调词
    # 以下字段由 VLM 在判断字幕样式时一次性返回（不是 OCR 来的原文）
    placeholder_text: list[str] = []         # 描述性占位列表，按 VLM 推荐顺序，第 0 个首选；
                                             # 示例：["4-6 字 CTA 强调短语", "立即抢购", "促销+数字"]
                                             # 应用阶段 LLM 拿到的是整个列表作为引导，给更多选择空间（S15）
    length_constraint: dict | None = None    # {min_chars: 3, max_chars: 8, max_lines: 1}
    semantic_purpose: str | None = None      # VLM 给的语义标签："CTA强调"|"标题"|"卖点说明"|"过渡引语"
    coord_system: str = "normalized_0_999"   # 显式标注源坐标系，便于日后切换

class ZoomKeyframe(BaseModel):
    relative_time: float   # 0~1 相对槽位时长
    scale: float           # >1 推进，<1 拉远

class VisualStyle(BaseModel):
    zoom_keyframes: list[ZoomKeyframe] = []
    mask: str | None = None          # D3 (Phase 4)
    color_lut: str | None = None     # D3 (Phase 4 - 预设库 ID，不做 1:1 LUT 提取)
    title_bar: bool = False          # D3 (Phase 4)
    # speed_curve 提取端不填（变速识别不做）；应用端 D8 时长自适应直接写 PlacedSegment.speed

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
    position: tuple[float, float]    # 归一化坐标 (0~1)，从 VLM 0-999 坐标 /1000
    size: tuple[float, float]
    start: float; end: float         # 相对槽位时长 0~1
    generated_image: str | None = None  # Phase 5 生图后填
    semantic_category: str | None = None   # "强调提示"|"装饰"|"信息标签"|"情绪表达"，前端工作台用此色标
    coord_system: str = "normalized_0_999"

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
        # 占位文字与语义占位（CaptionStyle 的 placeholder 三件套）
        "set_placeholder_text",   # 改 CaptionStyle.placeholder_text（用户在模板编辑界面调整 VLM 给的占位描述）
        "set_length_constraint",  # 改 CaptionStyle.length_constraint
        "set_semantic_purpose",   # 改 CaptionStyle.semantic_purpose
        # AI 工作台事件级操作（reject 确实改 IR；replay 不改 IR，已移到 Workbench API 而不是 Patch op）
        "reject_vision_event",    # 标记某条 VisionEvent 为"识别错误"（清除该 event.ir_target 处之前写入的值），并触发该步重跑
    ]
    target: dict      # {section_idx, segment_idx, unit_id, step_no, event_id, ...} 视 op 而定
    value: dict       # op 对应的参数
    source: str       # "nl" | "panel" | "review" | "timeline" | "workbench"
    timestamp: str
    pipeline_step: int | None = None  # 来自哪个 step（来自分步审核时填）
    triggered_by_event_id: str | None = None  # 如果是 workbench 中"否决 VLM 决策"产出的 patch，记录源 event 便于追溯
```

---

## 阶段 0: 地基与渲染骨架 ✅

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

## 阶段 0.5: AI 透明工作台骨架 📋

### 前置条件
- 阶段 0 完成（三服务脚手架 + IR codegen + CI + 最小渲染链路均已验证）
- 阶段 0 的 `tasks` 表与 `BackgroundTasks` 任务机制可用

### 目标
搭建 AI 透明工作台的可观测性底座，使得后续阶段（1A/1B/2/2.5/3）任何 VLM 调用都能"零额外工作"地把识别过程实时推送到前端三栏页面、并持久化到 `events.jsonl` 供答辩 demo 回放。

本阶段**不调任何真实 VLM**——用 mock 事件流验证整套机制。1A 起才开始接入真实 VLM。

### 设计约束（本阶段必守）
- D13：所有 AI 调用（VLM / Text LLM / ASR / audio / CV）必发射 VisionEvent；本阶段建立这条契约的客户端层（chat_vision + chat_text 两套签名均符合协议）。
- 事件总线必须支持多订阅者（前端工作台 + 持久化 writer 同时订阅）。
- SSE 连接断开重连后能从 `last_event_id` 续推（前端长任务不能因为网络抖动错过事件）。
- 工作台页面骨架可独立运行（不依赖任何真实 VLM 输出，用 mock generator 驱动）。

### 后端改动（backend/）
- **新增** `backend/app/ir/vision_event.py`：`VisionEvent` + `IRTarget` pydantic 模型（同核心数据结构定义）；`ir_value: Any`（标量/列表/dict 任一），与 lodash.set 语义对齐；同步更新 `backend/app/ir/export.py` 把 VisionEvent 加入 JSON Schema 导出。
- **新增** `backend/app/ir/path_validator.py`：lodash 风路径校验器（给定 root pydantic 模型 + path 字符串，结构化验证命中真实字段；dict 字段宽容）。`tests/unit/test_scenarios.py` 用它对 mock JSON 的 ir_target.path 做 CI 静态校验，防止 mock 与真实 IR 漂移。
- **新增** `backend/app/event_bus.py`：内存事件总线 + jsonl 持久化（路径方案 B）
  - `class EventBus`：维护 `dict[task_id, list[asyncio.Queue]]` 订阅者表 + `dict[task_id, int]` sequence 计数器（首次 publish 从 jsonl 末尾的最高 sequence 懒初始化）；jsonl 是 high-water mark 的唯一真理源
  - `subscribe_with_snapshot(task_id) -> tuple[Queue, int]`：在 task lock 内原子返回新 queue 与当前 sequence high-water；snapshot 把"已持久化历史（≤snapshot）"与"将经队列下发的 live 事件（>snapshot）"清晰切分，SSE 消费者不再需要任何 sequence dedup
  - `subscribe(task_id) -> asyncio.Queue`：同步版本，供测试与非 SSE 调用方使用，不提供 snapshot 语义
  - `unsubscribe(task_id, queue)`：清理
  - `publish(task_id, event)`：① 在 task lock 内分配 `event.sequence = counter+1`、append jsonl ② lock 外 broadcast 用 `await q.put`（队列无界）反压慢消费者，确保事件不丢失
  - `replay(task_id, from_event_id=None, until_seq=None) -> list[VisionEvent]`：从 jsonl 读历史；`from_event_id` 跳过指定事件之前（Last-Event-ID 续推语义）；`until_seq` 切到 snapshot 边界（SSE replay 专用）
  - `resolve_events_path(resource_kind, resource_id, task_id) -> str`：路径计算工具函数，按方案 B：
    - `sample` → `samples/{resource_id}/extracted/events_{task_id}.jsonl`
    - `project` → `projects/{resource_id}/pipeline/events_{task_id}.jsonl`
    - `template` → `samples/{source_sample_id}/extracted/events_{task_id}.jsonl`（模板继承自 sample；Phase 0.5 暂回退到 `system/dev_events/template_{id}/`，KB 接入后回填真实 sample 路径）
  - `set_lookup_callback(callback)`：依赖注入接口；`main.py` lifespan 内传入 `tasks_store.get_task`，event_bus 模块不再 import tasks_store，分层依赖单向
- **扩展** `backend/app/tasks_store.py`：`create_task(kind, *, resource_kind, resource_id, task_id=None)` 调 `EventBus.resolve_events_path()`（仅静态方法调用，不引入运行时反向依赖）写 `events_jsonl_path` 字段；`tasks` 表 schema 加 `resource_kind` / `resource_id` / `events_jsonl_path` 三列；老库通过 `init_db` 内置 idempotent ALTER 自动迁移
- **扩展** `backend/app/config.py`：Settings 类加四个字段：`model_provider: Literal["openai","anthropic","mixed"] = "openai"`、`anthropic_api_key: str | None = None`、`enable_dev_mock: bool = False`、`dual_check_stages: list[str] = []`（env 里逗号分隔解析）
- **新增** `backend/app/llm/client.py`（占位骨架，1A 才填真实逻辑）：
  - `class LLMClient`：抽象基类，定义 `chat_text` / `chat_vision` 接口
  - `class OpenAICompatClient(LLMClient)`：占位实现（本阶段返 mock 数据 + 发 mock VisionEvent）
  - `class AnthropicClient(LLMClient)`：占位实现（同上）
  - `def get_llm_client(model_provider: str) -> LLMClient`：工厂，按 `MODEL_PROVIDER` env 选
  - **强约定（拓宽到全部 AI 客户端）**：
    - `chat_vision` 签名必为 `(messages, model, stage, task_id, frames, ir_target_template, schema, silent=False) -> tuple[BaseModel, list[VisionEvent]]`
    - `chat_text` 签名必为 `(messages, model, stage, task_id, ir_target_template, schema, silent=False) -> tuple[BaseModel, list[VisionEvent]]`（无 frames 参数，其余同 chat_vision）
    - 本阶段两个方法的实现都内部直接构造 mock VisionEvent 列表、调 `event_bus.publish()`、返回 mock 结构化结果
    - 后续 Phase 3 的 dedup/segment 等 Text LLM 调用直接走 `chat_text`，自动满足 D13
- **新增** `backend/app/api/events.py`：
  - `GET /api/tasks/{task_id}/events`：SSE 端点（`sse-starlette.EventSourceResponse`）
    - 读 `Last-Event-ID` 请求 header（浏览器原生 EventSource 重连时自动回传）
    - 流程：`subscribe_with_snapshot(task_id)` 原子拿到 (queue, snapshot) → `replay(from_event_id=last_event_id, until_seq=snapshot)` 推历史 → 队列推 live 事件；history 与 live 永不重叠，无须 dedup
    - **每条 event 必须三行格式**（H3 强约束）：`id: {event.event_id}\nevent: vision\ndata: {json}\n\n`；`id:` 字段不可省略，浏览器自动用它续推
    - 心跳：每 15s 发空 comment `: heartbeat\n\n` 保活（sse-starlette `ping` 参数）
    - 任务终态（completed/failed）即刻发 `event: done\ndata: {status}\n\n`，包括"订阅时任务已结束"的兜底情况
  - `GET /api/tasks/{task_id}/events/history`：一次性返回所有历史事件 JSON 数组（供 Visualize 回放页加载全量；Workbench 主页不要叠用，会与 SSE replay 冲突）
- **扩展** `backend/app/main.py`：挂载 `api/events.py` 路由
- **扩展** `backend/pyproject.toml`：加 `sse-starlette` 依赖
- **新增** `backend/app/api/dev_workbench.py`（仅 `ENABLE_DEV_MOCK=true` 时启用）：
  - `POST /api/dev/workbench/mock-stream` body `{task_id, scenario}` → 在 BackgroundTask 中读 `backend/app/llm/prompts/scenarios/{scenario}.json`（S7）按脚本每 500ms 发一条 mock VisionEvent，供前端工作台开发期验证
  - 脚本格式：`[{delay_ms: int, event: VisionEvent}, ...]`
  - 内置脚本：`captions_demo.json` / `stickers_demo.json` / `full_extract_demo.json`（用户需在动手 Phase 0.5 前一次性补齐这几个 JSON，每个 8-15 条事件覆盖三栏所有 UI 状态）
- **新增** `backend/tests/conftest.py` 补：`mock_event_stream(task_id, events)` fixture，集测用
- **新增** `backend/tests/unit/test_event_bus.py`：多订阅者广播、replay 一致性、持久化 jsonl 格式

### 前端改动（frontend/）
- **扩展** `frontend/src/styles/`：新增 `tokens.css` 实现"前端设计语言"章节定义的 design tokens；扩展 `tailwind.config.ts` 注册 tokens 到 theme.extend
- **扩展** `frontend/package.json`：加 `tailwindcss`、`@radix-ui/react-dialog`、`@radix-ui/react-tabs`、`@radix-ui/react-tooltip`、`lucide-react`
- **新增** `frontend/src/api/events.ts`：
  - `subscribeEvents(taskId, onEvent, onError, lastEventId?) -> () => void`：封装 `EventSource`，自动重连、保存 last event id、断线时从 lastEventId 续推
  - `fetchEventHistory(taskId) -> Promise<VisionEvent[]>`：调 history 接口
- **新增** `frontend/src/state/workbench.ts`：Zustand store，维护 `{taskId, events: VisionEvent[], filterStage, selectedEventId, irSnapshot}`
- **新增** `frontend/src/pages/Workbench.tsx`：核心三栏页面骨架
  - 路由：`/workbench/:taskId`
  - 顶部 bar：任务名 + 当前 stage（"1A 字幕能力调试中"）+ 进度 + 「⏸ 暂停接收」按钮（可选，用于截图）
  - 三栏布局（CSS grid `1fr 1fr 1fr`，移动端折叠为单列 tab）：
    - **左栏 `WorkbenchVisionPane.tsx`**：根据 `selectedEventId` 显示对应帧（`<img src={event.frame_url}>`）+ 在帧上用 SVG overlay 画 bbox（按 `event.bbox_norm` 计算位置）+ 标签气泡（`event.semantic_label`）。多个 bbox 时按 confidence 高低用粗细区分。
    - **中栏 `WorkbenchEventStream.tsx`**：按 sequence 倒序滚动展示事件流，每条卡片显示 `{sequence, stage badge, semantic_label, reasoning（≤200字）, confidence, model_used, [跳到对应帧] 按钮, [否决] 按钮}`。stage 按前缀用 token 染色（按"stage 命名规范"表）。**键盘快捷键（O7）**：↑/↓ 切换 selectedEventId（联动左栏帧切换 + 右栏字段高亮）、Enter 跳到对应帧、X 否决当前事件。**双维过滤（O5）**：URL 参数支持 `?stage_filter=1A.*&time_range=6.0-7.0`，stage 与时间区间正交组合。
    - **右栏 `WorkbenchIRPane.tsx`**：实时拼接的 TemplateIR/ProjectIR 树，**用 `react-arborist` 做 virtualized 树**（避免长视频 ProjectIR 几千 segments 全展开导致 React 卡死，S5/O7）；状态用 `immer` produce + `lodash.set(draftIr, event.ir_target.path, event.ir_value)` 做增量写入。`ir_target` 命中的字段做 200ms 高亮闪烁动画（accent-primary 边框淡入淡出），自动展开命中子树。
  - 底部 bar：累计事件数 + 累计 VLM token 数 + 任务总耗时
- **新增** `frontend/src/components/workbench/`：上面三个 pane 组件
- **新增** `frontend/src/components/workbench/EventBadge.tsx`：stage 染色徽章
- **新增** `frontend/src/components/workbench/BboxOverlay.tsx`：在视频帧 img 上画 bbox + 气泡的 SVG overlay
- **扩展** `frontend/src/main.tsx`：路由表加 `/workbench/:taskId`
- **扩展** `frontend/src/api/index.ts`：导出 `events` 模块

### 渲染服务改动
- 无（工作台不涉及渲染）。

### 工作区与 CI 改动
- **扩展** `.env.example`：加 `MODEL_PROVIDER`（openai|anthropic|mixed）、`ANTHROPIC_API_KEY`、`ENABLE_DEV_MOCK`
- **扩展** `.github/workflows/ci.yml`：python job 跑 `pytest backend/tests/unit/test_event_bus.py`；frontend job 跑 `pnpm -F frontend test`（含工作台组件 unit test）

### 验证方式
1. **mock 流端到端**：浏览器 `pnpm dev` → 打开 `/workbench/test-task-001` → curl `POST /api/dev/workbench/mock-stream {"task_id":"test-task-001","scenario":"captions_demo"}` → 工作台页面在 ≤ 1s 内开始出事件、左栏切帧、中栏滚动、右栏字段填充动画触发。
2. `pytest backend/tests/unit/test_event_bus.py`：
   - 三个订阅者同时 subscribe → publish 一条事件 → 三个 queue 各收到一份
   - 写入持久化 jsonl 后 unsubscribe → 重新 subscribe + 带 last_event_id → 从断点续推
   - 持久化 jsonl 每行可被 `VisionEvent.model_validate_json` 解析
3. **SSE 断线重连**：浏览器开 `/workbench/test-task-001` → 后端 kill 重启 → 前端 EventSource 自动重连 → 续推从 last_event_id 起的事件，不丢、不重。
4. **设计 token 走查**：访问 `/workbench/test-task-001` 主观检查色彩 / 字体 / 留白 / 卡片样式与"前端设计语言"章节定义一致；用 axe DevTools 检查对比度（正文 ≥ 4.5:1，次级文字 ≥ 3:1）。
5. **CI 绿灯**：push → Actions 全 job 通过；故意删除 `chat_vision` 签名里的 `task_id` 参数 → 单测 mock 实现 fail（约束 D13 被触发）。
6. **持久化文件格式**：用 dev_workbench 创建一个 dummy sample task → `data/samples/{dummy_sid}/extracted/events_{task_id}.jsonl` 存在 + 每行可被 `jq` 解析为合法 VisionEvent + 每行的 task_id 字段一致。

---

## 阶段 1A: 视觉理解能力单点验证 📋

### 前置条件
- 阶段 0.5 的 SSE 事件总线 + VisionEvent IR + 工作台三栏页面骨架可独立运行（阶段 0.5 验证 1+3+5 通过）。
- 阶段 0 的 `render_project()` 可将最小 ProjectIR 渲成 mp4。
- Python venv 已切 3.11/3.12，可装 Demucs / PySceneDetect / opencv-python / librosa / whisperx（**不装 PaddleOCR**——模板提取不需要 OCR）。
- `.env` 已配 `MODEL_PROVIDER`、`LLM_BASE_URL`、`LLM_API_KEY`、`ANTHROPIC_API_KEY`、`MODEL_VLM`、`MODEL_TEXT`、`MODEL_TEXT_CHEAP`。
- `data/system/fonts/` 已放入至少 2 个中文字体；`data/system/luts/` 已放入 5–10 个调色预设。
- 测试 fixtures 准备见下方"fixtures 矩阵"。

### 目标
逐个交付视觉理解能力，每个能力**独立 fixture + 独立指标基线 + 独立工作台事件流验证**通过后才允许进 1B 的端到端集成。本阶段不产出 TemplateIR，只产出可独立调用的子能力函数 + 它们的指标基线写入 `tests/baselines.json`。

> **方法论**：拒绝"大整合 → 集成测试失败 → 不知道是哪个子能力拖后腿"的失败模式。每个子能力都先单点完工，再 1B 集成。

### 设计约束（本阶段必守）
- 每个子能力函数对外暴露统一签名 `def detect_X(normalized_path, frames_dir, task_id, stage) -> tuple[X_Result, list[VisionEvent]]`，由 `llm.client.chat_vision` 客户端层强制发射 VisionEvent。
- 每个 VLM 调用必须传 `stage="1A.<能力名>"`、`task_id`、`ir_target_template`；未传 CI 红（D13）。
- 不要在 1A 出现 `extract_template()` 这种串联函数——那是 1B 的事。
- VLM 坐标使用 0-999 归一化系统；客户端层负责映射到 0-1 写入 IR。
- 单点验证可在 `pnpm dev` 起服务后通过工作台 `/workbench/{task_id}` 实时观察事件流。
- **parent_event_id 强约束（为 Phase 2.6 因果链可视化准备）**：所有"两阶段"VLM 调用——VLM 粗判后再调一次精化（如：贴纸 bbox 检测 → 贴纸语义判断、字幕样式识别 → 字幕功能分类、几何蒙版有无判 → 几何参数给出、调色 dominant_tag → 直方图微调），**第二阶段事件必填 `parent_event_id` 指向第一阶段 event_id**。零成本（多写一行 `parent_event_id=prev_event.event_id`），但前置了 Phase 2.6 因果链 / 甘特图跨 lane 连线的核心数据。CI 脚本 `scripts/check_parent_event_id.py` grep 校验：所有命名为 `*_refine` / `*_phase2` / `*_classify` 的子能力函数体内若调 `chat_vision()`，必传 `parent_event_id=` 关键字参数；缺则 fail。

### Fixtures 矩阵（用户准备 / 一次性补齐）

**路径约定（S12）**：开发期 fixtures 放 `tests/fixtures/{sample_id}/source.mp4`（仓库内 git-tracked，便于 CI）；运行时通过 `python -m app.cli ingest-sample tests/fixtures/{sample_id}/source.mp4 --name {sample_id}` 把它 ingest 到 `data/samples/{sid}/source.mp4`（已 normalized）。Phase 1A/1B/2 的 fixture 引用都用 `sample_id`（不带前缀路径），实际加载时由 `tasks_store.get_sample_path(sample_id)` 路由到 `data/samples/{sid}/normalized.mp4`。

| Fixture | 用途 | 关键人工标注 |
|---------|------|------------|
| `sample_basic_15s` | 字幕样式 + 缩放方向 + BGM | 字幕首现时刻、字幕 bbox 归一化、缩放方向、BGM 有无 |
| `sample_with_sticker_12s` | 贴纸 + 字幕功能 | 贴纸 bbox、贴纸类型、字幕功能（CTA/标题/regular） |
| `sample_fast_pace_8s` | 切点 + 节奏 + 转场 | 切点时间戳、转场类型（硬切/叠化/滑入/推拉） |
| `sample_no_bgm_10s` | 无 BGM 负例 + 字幕动画细节 | 字幕动画类型（逐字弹入/滑入/淡入）、是否纯人声 |
| `sample_with_mask_10s` | 几何蒙版 | 蒙版类型（圆/线分屏/矩形）+ 归一化几何参数 |
| `sample_warm_lut_10s` | 调色语义 | 主观色调标签（暖/冷/电影感）+ 直方图均值范围 |
| `sample_title_bar_8s`（Phase 4 复用） | 标题条 | 标题条 bbox + 颜色 + 文字结构 |

> **fixtures 不齐时的降级**：缺哪个 fixture，对应子能力的指标基线临时跳过，但子能力函数本身必须完工、可被 mock fixture 单测覆盖。

### 后端改动（按子能力分组，每组独立可交付）

#### LLM/VLM 客户端正式实现（升级 0.5 占位）
- **重写** `backend/app/llm/client.py`：
  - `OpenAICompatClient`：实现真实 OpenAI-compatible API 调用（Qwen-VL-Max / GPT-4o），含 temperature=0 + seed 控制
  - `AnthropicClient`：实现真实 Anthropic API 调用（Claude Sonnet 4.6 / Opus 4.7）
  - `chat_vision()`：实现协议——发请求 → schema 校验返回 → 自动构造 VisionEvent 列表（一个识别到的实体一个事件）→ `event_bus.publish` → 返回 `(result, events)`
  - `chat_vision_dual()` 关键决策可启用：同时调两 provider → 两者一致才写入 IR，否则 `confidence_warning=True` 让用户在工作台 review
  - 重试策略：指数退避 3 次；最终失败发一个 `severity=error` 的 VisionEvent 让用户看见
- **新增** `backend/app/llm/prompts/`：
  - `1a_captions.md` / `1a_stickers.md` / `1a_zoom_direction.md` / `1a_transition.md` / `1a_mask.md` / `1a_color_lut.md` / `1a_caption_function.md`
  - 每个 prompt 含：任务描述 + 输出 JSON Schema 示例 + 0-999 坐标系明确约束 + 要求附 `reasoning` 中文解释（≤200 字，用作 VisionEvent.reasoning）

#### 1A-T1 切点检测（CV 沿用）
- **新增** `backend/app/extract/scenes.py`：`detect_scenes(normalized_path, task_id) -> tuple[list[Scene], list[VisionEvent]]`，PySceneDetect `ContentDetector(threshold=27)`，每个切点发一条 `source="cv"` 的 VisionEvent（stage="1A.scenes"，bbox=None，semantic_label="切点 #N"）。
- **指标基线**：切点 F1 ≥ 0.80（容差 ±0.2s）

#### 1A-T2 关键帧抽样器
- **新增** `backend/app/extract/frame_sampler.py`：`sample_frames(normalized_path, scenes, fps_global=1, around_scene_cut=True) -> list[FrameRef]`，写帧到 `extracted/frames/{ts}.jpg`，返回 `[{ts, url, scene_idx}]`。后续所有 VLM 调用都从这个 frames_dir 取输入。

#### 1A-V1 字幕（VLM 主路径）
- **新增** `backend/app/extract/captions.py`：`detect_captions(normalized_path, frames, task_id) -> tuple[list[CaptionEvent], list[VisionEvent]]`
  > **CaptionEvent vs CaptionStyle 命名澄清（S10）**：`CaptionEvent` 是 extract 阶段的中间产物（含 `style: CaptionStyle + start: float + end: float + frames_appeared: list[int]`），1B 集成时拆出 `style` 写入对应 `Slot.style.caption`，并由 Caption 列表（ProjectIR）按 start/end 渲染。CaptionEvent 在 `backend/app/extract/captions.py` 内定义为 dataclass，不入 IR（不导出 JSON Schema），区分于 ledger 里的 Unit 与 ProjectIR 里的 Caption。
  - 用 VLM 看采样帧，prompt `1a_captions.md` 要求一次返回：每个字幕的 `{position_norm_0_999, size_norm, color_hex, stroke_color_hex, stroke_width_px, size_px_estimate, anim_in_type, placeholder_text, length_constraint, semantic_purpose, frames_appeared, confidence, reasoning}`
  - 跨帧追踪同一字幕（IoU > 0.5 + semantic_purpose 一致）→ 合并为 CaptionEvent
  - 不识别字幕文本字符；`placeholder_text` 由 VLM 描述给出（"4-6 字 CTA 强调短语"或具象示例"立即抢购"）
- **指标基线**：字幕首现时刻 median 误差 < 0.3s；字幕位置 median 误差 < 5%（归一化）；多行布局判定正确率 ≥ 80%；`semantic_purpose` 与人工标注一致率 ≥ 80%

#### 1A-V2 字幕动画细节验证（CV）
- **新增** `backend/app/extract/captions_anim.py`：`verify_caption_anim(caption_event, normalized_path) -> AnimDetail`，在 VLM 给的字幕时间区间内 5fps 采样 + 帧差 + Lucas-Kanade 光流跟踪字符 / bbox 顶点，判：
  - 逐字弹入：bbox 宽度逐帧增长 + 字符 stagger ≥ 50ms
  - 整句滑入：bbox 整体 Y 位移 > 5% + alpha 不变
  - 淡入：alpha 0→1 + bbox 位置不变
  - 打字机：bbox 宽度阶梯增长 + 每步 stagger ≈ 100-200ms
- 输出 `AnimDetail{verified_anim_in, stagger_ms, confidence}`，覆盖或确认 VLM 给的 `anim_in` 字段；每次校正发一条 `source="cv"` 的 VisionEvent
- **指标基线**：动画类型与人工标注一致率 ≥ 85%；stagger_ms 误差 < 30ms

#### 1A-V3 贴纸（VLM 主路径）
- **新增** `backend/app/extract/stickers.py`：`detect_stickers(normalized_path, frames, scenes, task_id) -> tuple[list[StickerEvent], list[VisionEvent]]`
  - 步骤 1：在 scene 切点前后额外采样 1 帧（贴纸常在切点出现）
  - 步骤 2：每 4–6 帧合成 2×2 或 2×3 网格图（带帧号水印），一次 VLM 调用，prompt `1a_stickers.md` 要求 JSON：`[{description, semantic_category: "强调提示"|"装饰"|"信息标签"|"情绪表达", frames_appeared, position_norm_0_999, size_norm, confidence, reasoning}]`
  - 步骤 3：每个候选 → CV 帧差 + Canny 在 ±10% 范围内精化 bbox 到 ±5px
  - 步骤 4：跨帧合并（IoU > 0.5 或描述余弦相似度 > 0.8）→ 写 `extracted/stickers_crops/{n}/`
- **指标基线**：贴纸位置 IoU ≥ 0.6；描述与人工标注 LLM 评 ≥ 3/5；semantic_category 一致率 ≥ 75%

#### 1A-V4 缩放方向粗判（VLM）+ 1A-V5 缩放曲线精化（CV）
- **新增** `backend/app/extract/motion.py`：
  - `judge_zoom_direction(scenes, frames, task_id) -> dict[scene_idx, direction]`：每 scene 取首/中/末三帧合成 1×3 网格 → VLM 判 `direction ∈ {推进, 拉远, 稳定, 抖动}`，每 scene 发一条 VisionEvent
  - `estimate_zoom_curve(scene, normalized_path) -> list[ZoomKeyframe]`：仅在非稳定 scene 跑，OpenCV `goodFeaturesToTrack` + Lucas-Kanade，5 个 ZoomKeyframe；scale 变化 > 3.0 视为抖动
- **指标基线**：方向判定正确率 ≥ 85%；非稳定 scene 的 scale 曲线相对峰值误差 < 20%

#### 1A-V6 转场分类（VLM）
- **新增** `backend/app/extract/transitions.py`：`classify_transitions(scenes, normalized_path, task_id) -> list[TransitionType]`，对每对相邻 scene 取边界各 1 帧 + 中间过渡帧 1 帧 → VLM 判 `{硬切, 叠化, 滑入, 推拉, unknown}` + reasoning。
- **指标基线**：转场类型一致率 ≥ 80%

#### 1A-V7 几何蒙版（VLM）
- **新增** `backend/app/extract/masks.py`：`detect_masks(scenes, frames, task_id) -> list[MaskParams]`：
  - 步骤 1：每 scene 取中间一帧 → VLM 判"有无几何蒙版"（圆/线分屏/矩形/none），无则跳过
  - 步骤 2：有蒙版 → VLM 给参数（圆心+半径归一化 / 分屏线起止点 / 矩形 bbox）
  - 步骤 3：复杂场景 fallback SAM2（仅 confidence < 0.5 时触发）
- **指标基线**：有无判定正确率 ≥ 90%；参数 IoU ≥ 0.6（有蒙版样本）

#### 1A-V8 调色语义（VLM）
- **新增** `backend/app/extract/color.py`：`classify_color_lut(scenes, frames, task_id) -> ColorStyle`：
  - VLM 看 3 张采样帧 → 给主观标签 `{暖色, 冷色, 高饱和, 低饱和, 电影感, 平淡}` 多选 + dominant_lut_id（匹配 `data/system/luts/` 库 ID）
  - 配合 OpenCV 算 HSV 均值 + 直方图，作为 VLM 标签的数值微调
- **指标基线**：主观标签 top-1 一致率 ≥ 60%；LUT 匹配 top-3 命中 ≥ 80%

#### 1A-A1 BGM（Demucs + librosa）
- **新增** `backend/app/extract/audio.py`：`extract_bgm(normalized_path, save_stem, task_id) -> AudioStyle`，每个关键判定（has_bgm / is_instrumental / bpm / mood）各发一条 `source="audio"` 的 VisionEvent。
- **指标基线**：BGM 有/无 100% 正确；BPM 误差 ≤ 5；mood top-1 ≥ 70%

#### 字幕功能分类（VLM）
- **新增** `backend/app/understand/vision.py`：`classify_caption_function(caption_event, frame, task_id) -> str`，VLM 送字幕区域裁图 + placeholder + 语境 → 返回 `regular|标题|强调|卖点|CTA`，发 VisionEvent。
- **指标基线**：与人工标注一致率 ≥ 80%

#### SubcapabilityLab 后端入口（H5）
- **新增** `backend/app/api/lab.py`：仅 `ENABLE_DEV_MOCK=true` 时挂载
  - `GET /api/lab/subcaps` 返回所有可单点跑的子能力列表 `[{name, fixtures: [...], baseline_path}]`
  - `POST /api/lab/run-subcap/{name}` body `{fixture_id, dry_run?}` → 创建 task（resource_kind=sample, resource_id=fixture_id）→ BackgroundTask 调对应 `detect_X(...)` → 返回 `{task_id, workbench_url}`
  - `GET /api/lab/baselines/{name}` 返回 `tests/baselines.json/subcap.<name>` 当前基线数值

### 渲染服务改动
- 无（1A 不渲染，只识别）。

### 前端改动
- **新增** `frontend/src/pages/SubcapabilityLab.tsx`（关键页 · S11：`import.meta.env.DEV` 守卫，生产 build 时该路由 404 不挂载）：单点验证工作台
  - 左侧：fixture 下拉 + 子能力下拉（"VLM 字幕"/"CV 字幕动画"/"VLM 贴纸"/…）
  - 中央：「跑此子能力」按钮 → 调对应 `POST /api/lab/run-subcap/{name}` → 跳转 `/workbench/{generated_task_id}`
  - 右侧：上次跑的指标基线 + 当前结果对比（绿/红判定）
- **扩展** `frontend/src/pages/SampleExtract.tsx`：上传后展示样例基础信息，**新增"打开工作台看 AI 工作过程"按钮** → 直接跳 `/workbench/{task_id}`

### 验证方式
1. **每个子能力独立单测**（`pytest backend/tests/integration/test_subcap_<name>.py`）：
   - 用 fixture 跑该子能力 → 与人工标注比对 → 写指标到 `tests/baselines.json/subcap.<name>`
   - 调用计数器：单次跑只调对应 VLM 路径，不允许触发其他子能力（隔离性验证）
   - VisionEvent 校验：返回的 events 列表非空 + 每条 schema 合法 + 都已通过 event_bus 发布
2. **工作台事件流人工走查**（每个子能力一次）：浏览器 `/sublab` → 选 fixture + 子能力 → 「跑」→ `/workbench/{task_id}` → 左栏看到帧 + bbox 高亮、中栏看到 reasoning 中文解释、右栏看到该子能力对应 IR 字段填充动画。
3. **指标基线集成判定**（`pytest backend/tests/integration/test_1a_baselines.py`）：跑全部子能力的 baseline 比对，所有指标达标 → 1A 视为 ready，可进 1B；任一未达标 → 列出未达标项 + fail。
4. **VLM 模型切换冒烟**：设 `MODEL_PROVIDER=anthropic` → 跑 `sample_basic_15s` 的字幕子能力 → 同样通过指标基线（Claude 与 Qwen 在 0-999 坐标系上等价）。
5. **D13 约束验证**：CI 脚本 `scripts/check_event_emission.py` 扫所有 AI 客户端方法（`chat_vision` / `chat_text` / ASR / VAD / Demucs 调用点）是否都在返回前调过 `event_bus.publish`；故意删任一处的 publish → CI 红。验证方式：人为把 `chat_text()` 内的 publish 注释掉 → 期望 CI 报告"chat_text at backend/app/llm/client.py:LXX missing event_bus.publish"。

---

## 阶段 1B: 模板提取集成 → KB 📋

### 前置条件
- 阶段 1A 全部子能力指标基线达标（1A 验证 3 通过）。
- 阶段 0.5 工作台可正常订阅事件流。

### 目标
串联 1A 各子能力 → 完整 `TemplateIR`（含 D2-core + D2-extended：切点 + 字幕样式含 placeholder 三件套含多行 + 缩放 + BGM + 贴纸 + 转场 + 几何蒙版 + 调色 + 骨架三段 + 字幕功能分类 + 标签 + sanity check）→ 存入 KB，工作台可观察全链路。

### 设计约束（本阶段必守）
- 只提"怎么剪"，不判断样例说了什么（D2）。
- 骨架按位置阈值发现（D5）；material_req 按字幕/贴纸/缩放有无标。
- 槽位时长输出 `{min, nominal, max}` 区间（D8）。
- 整个 extract pipeline 的所有 VLM 调用都通过工作台事件流可观察（D13）。
- 任一子能力失败时不阻塞整个 pipeline；该字段标 `degraded=true` 并发 `severity=warning` 的 VisionEvent。

### 后端改动
- **新增** `backend/app/extract/skeleton.py`：`build_skeleton(scenes, captions, stickers, masks, duration) -> list[Slot]`；位置阈值 `start/duration < 0.30` → 开头、`> 0.70` → 结尾、其余 → 主体；槽位时长 `{min=slot_duration*0.7, nominal=slot_duration, max=slot_duration*1.5}`；`material_req`：有字幕=人物口播，无字幕但有缩放/贴纸/蒙版=B-roll/包装，二者皆无=待定。每个 Slot 推断发一条 VisionEvent。
- **新增** `backend/app/extract/pipeline.py`：`extract_template(sample_id, task_id) -> TemplateIR`，按下方 DAG 调度（不能再说"并发跑各子能力"，要明确 DAG）。**绝不重写 1A 子能力**——pipeline 是组合层。

  **子能力依赖 DAG（H4）**：

  ```
  normalize ──▶ scenes ──┬──▶ frame_sampler ──┬──▶ captions ──▶ captions_anim
                         │                    ├──▶ stickers
                         │                    ├──▶ zoom_direction ──▶ zoom_curve (仅非稳定 scene)
                         │                    ├──▶ transitions
                         │                    ├──▶ masks
                         │                    └──▶ color_lut
                         └──▶ (audio 与上方独立) ──▶ extract_bgm
  
  上述全部完成后：
  ──▶ skeleton (用 scenes + captions + stickers + masks + duration)
  ──▶ caption_function (按 captions 调 VLM 综合判)
  ──▶ tagging (综合骨架+style+音频)
  ──▶ sanity_check (整体 VLM 复查)
  ──▶ save_template ──▶ KB
  ```

  实现用 `asyncio.gather()` 并发同层节点；上层节点 `await` 所有依赖完成后启动；任一子能力 raise 时该节点的下游链路标 `degraded=true` 不阻塞其他子树。
- **新增** `backend/app/kb/store.py`：SQLite `templates` 表（`id, name, source_sample, ir_json, tags_json, thumbnail_path, last_extract_task_id, created_at`）+ `save_template` / `get_template` / `list_templates` / `init_db` WAL 模式。**注意**：events 文件不直接挂模板表——它跟随 sample 资源存（`samples/{sid}/extracted/events_{task_id}.jsonl`），模板表只记录 `last_extract_task_id` 反查最近一次提取的事件流路径，避免重复存储。
- **新增** `backend/app/kb/tagging.py`：`suggest_tags(ir, sample_frames, task_id) -> Tags`，VLM 综合判 → 发 VisionEvent。
- **新增** `backend/app/kb/select.py`：`select_template(query_tags, kb) -> template_id`，标签精确匹配 + LLM 重排；1B 占位（Phase 3 完整）。
- **新增** `backend/app/agent/aigc.py`：v0 占位空函数（Phase 5 填）。
- **扩展** `backend/app/api/samples.py`：`POST /samples/{id}/extract` 触发 `extract_template()` BackgroundTask → 入 KB → 返回 `{task_id, workbench_url: "/workbench/{task_id}"}`。批量：同批次多个 sample_id 独立 extract。
- **新增** `backend/app/api/templates.py`：`GET /templates` / `GET /templates/{id}` / `PATCH /templates/{id}/tags` / `PATCH /templates/{id}/caption-placeholder`（手工改 placeholder_text） / `DELETE /templates/{id}` / `GET /templates/{id}/events`（事件回放）

### 渲染服务改动
- **扩展** `renderer/src/types/ir.ts`：跑 `pnpm gen:types` 重生成（含 VisionEvent / TemplateIR / 扩展后的 CaptionStyle / StickerEvent 等完整 schema）。
- **扩展** `renderer/src/compositions/Caption.tsx`：双模式渲染（S9）
  - **模板预览模式**（TemplateLibrary 详情页 / Phase 0.5 dev_workbench）：渲染 `placeholder_text[0]` 作为示例字幕
  - **应用产物模式**（Phase 2 渲染 ProjectIR）：渲染 ProjectIR.captions[i].text（来自用户素材的 Unit.text）
  - 模式由调用方传 `renderMode: "template_preview" | "project_output"` props 区分，不在组件内自动判断
  - anim_in 全套实现；多行布局；字体加载从 `data/system/fonts/`
- **扩展** `renderer/src/compositions/Project.tsx`：消费 ProjectIR 的 Caption 列表，按 start/end 显隐。
- **新增** `renderer/src/compositions/Mask.tsx`：渲染几何蒙版—— SVG clipPath 实现圆 / 线分屏 / 矩形蒙版
- **新增** `renderer/src/compositions/ColorLayer.tsx`：调色层—— 按 dominant_lut_id 应用 CSS filter（hue-rotate / saturate / brightness 组合）

### 前端改动
- **扩展** `frontend/src/pages/SampleExtract.tsx`：上传后展示样例基础信息（时长、镜头数、BGM 有无、字幕数预览、封面缩略图、骨架三段标注、转场/蒙版/调色摘要）；支持一次上传 2–3 条样例独立提取；「提取模板」按钮触发 extract → 顶部 banner 提示「正在提取，[打开 AI 工作台]」→ 完成后展示提取出的骨架/风格摘要。
- **新增** `frontend/src/pages/TemplateLibrary.tsx`：列表展示 KB 所有模板（名称/标签/来源缩略图）；点击查看详情页（骨架可视化 + StyleRule 详情 + placeholder_text 编辑入口 + sanity check 结果 + 「回放工作台事件流」按钮 → 历史事件回放页）

### 验证方式
1. **测试集**：3+ fixtures 样例（`sample_basic_15s` / `sample_with_sticker_12s` / `sample_fast_pace_8s` / `sample_no_bgm_10s` / `sample_with_mask_10s` 中至少 4 个）。
2. **集成基线**（`pytest backend/tests/integration/test_extract_1b.py --baseline`，写入 `tests/baselines.json/1b`）：
   - 全 1A 子能力基线达标 → 集成跑通 → 产出 TemplateIR 通过 pydantic 校验
   - 骨架三段：4/4 与人工一致
   - 字幕含 placeholder_text + length_constraint + semantic_purpose 三字段都非空
   - VLM sanity check 通过 ≥ 75%（含"placeholder 描述是否合理"维度）
   - 工作台事件总数 ≥ 30 条；每条事件可被 `model_validate_json` 解析
3. **IR round-trip**：`save_template(ir)` → `get_template(id)` 各字段一致（含 VisionEvent IR、placeholder 三件套）。
4. **VLM 调用延迟**：单次 extract 端到端 ≤ 5 分钟（含工作台 SSE 推送延迟 ≤ 1s/event）；工作台让用户全程不焦虑。
5. **端到端**：UI 上传 `sample_basic_15s` → extract → 工作台看完整识别过程（≥ 30 条事件）→ 模板库看到模板（含 placeholder、转场、蒙版、调色字段）+ 缩略图 + sanity check 状态。
6. **失败降级**：故意删 `LLM_API_KEY` → extract 在 VLM 步骤 发 `severity=error` 事件 → 该字段标 `degraded=true` → pipeline 不阻塞，产出可入库 TemplateIR + degraded warning。
7. **课题对齐验证**：打开任一模板的工作台事件回放 → 评审能看到"从样例中抽取了什么"（事件流）+ "为什么这么抽"（reasoning）+ "写入了 IR 哪里"（字段填充动画）——直接满足评分项 7。
8. **Golden runs 种子录制（为 Phase 2.6 ReplayClient 准备）**：1B 完工 close-out 时，选 ≥ 3 个稳定的标杆 fixture（建议 `sample_basic_15s` / `sample_with_sticker_12s` / `sample_with_mask_10s`），每个跑一次完整 extract → 把 `data/samples/{sid}/extracted/events_{task_id}.jsonl` 与对应 `TemplateIR`（从 `kb.sqlite` 导出为 `template.json`）一并 copy 到 `tests/fixtures/golden_runs/{sample_id}/{events.jsonl, template.json}` → 人工 review（无 PII / 无密钥 / IR 字段语义符合预期）→ git commit。本步无需写代码（手工脚本 + cp 即可），但产出的种子文件是 Phase 2.6 `test_golden_runs.py` 的输入；不录种子 → Phase 2.6 ReplayClient 无可回放对象。

---

## 阶段 2: ★MVP 应用闭环（短素材 + 指定模板） 📋

### 前置条件
- 阶段 1B 的 `extract_template()` 可产出完整 TemplateIR 入 KB（阶段 1B 验证 2+3+5 通过）。
- KB 中至少存在 2 个带 Tags + placeholder 三件套的模板（fixtures 提前 extract 准备）。
- `render_project()` 已能处理多 PlacedSegment + Caption 列表 + 缩放层（阶段 0 基础上 + 本阶段渲染端扩展）。
- `data/system/bgm_pool/` 已放至少 5 首免版权曲 + `bgm_index.json`。
- 阶段 0.5 工作台可订阅事件流（推荐 + apply 全程都发 VisionEvent）。

### 目标
用户传 10–20s 一镜到底口播短素材 + 从 KB 指定一个模板 → ASR 对齐 → 映射到模板骨架 → 套字幕风格（含多行 + placeholder 引导）+ 缩放 + BGM（features 或 original）+ 贴纸（占位）→ 渲染 MP4 返回；推荐 + apply 全过程在工作台可见。**MVP 闭环在此完成。**

### 设计约束（本阶段必守）
- 短素材场景下天然保序（D3）；账本仍要建，为 Caption 精确时间戳服务。
- 时长自适应（D8）：用户素材时长 vs 模板骨架总时长，按各槽位 `{min,max}` 缩放或裁切；变速幅度 ≤ ±20%。
- 缺口补全只用 MVP 三法（D10：不引入 AIGC）。
- 渲染走 Remotion + FFmpeg，输出 MP4（D7）。
- 用户素材若 canvas 与模板不匹配，走 letterbox + 模糊背景，**不裁切用户脸**。
- **D13 强化**：模板推荐 / 缺口补全决策 / 字幕填充时 LLM 用 placeholder 做参考的过程，全部发 VisionEvent → 工作台第二栏展示"为什么推荐这个模板"、"为什么填这个字幕"。

### 后端改动
- **新增** `backend/app/understand/asr.py`：`transcribe(normalized_path) -> TranscriptLedger`，WhisperX `large-v3` + language=zh + word_timestamps + forced alignment；按停顿（>0.3s gap）合并 Unit 到句级；`avg_logprob` 写入 Unit。
- **新增** `backend/app/kb/recommend.py`：`recommend_templates(material_path, ledger, kb, task_id, k=3) -> tuple[list[Recommendation], list[VisionEvent]]`，**模板智能推荐**（B1）：
  - 从 user material 取 3 帧采样（首 / 中 / 末）+ ASR 摘要（前 200 字）
  - VLM 接收：采样帧 + ASR 摘要 + KB 中所有模板的 Tags 概要 + 每个模板的 caption.placeholder/semantic_purpose 摘要
  - prompt 要求 VLM 输出 top-k 推荐及理由（中文），每个推荐发一条 VisionEvent（stage="2.recommend"，ir_target 指向 Editor 的推荐区）
  - 前端 Editor 在上传素材后立即调，预填模板下拉；用户可采纳推荐或手动浏览全库；工作台同步展示推荐推理过程
- **新增** `backend/app/apply/mapping.py`：`map_short_to_template(ledger, template) -> list[PlacedSegment]`；策略：按 Unit 时间顺序对应到模板骨架槽位（10–20s 短素材通常对应 1–3 个槽）；时长不足时按比例拉伸槽位 nominal（速度调整 ≤ ±20%）；时长超出时裁切尾部或顺延到下一槽（保序）；记录 `src_timerange` 和 `timeline_start`；**用户素材槽位是否完全等于模板骨架**：MVP 假设是（用户被引导上传与模板长度相近的素材），不等时打 warning。
- **新增** `backend/app/apply/gaps.py`：`detect_gaps(segments, template) -> list[Gap]`，槽位 `material_req` 无对应用户片段 → Gap；MVP 通常 Gap 数 ≤ 1（用户口播覆盖人物口播槽，B-roll/包装槽可能 Gap）。
- **新增** `backend/app/apply/fill.py`：`fill_gap(gap, ledger, style, allow_aigc=False) -> str`，三法：① 文案补全（Text LLM 按上下文生成字幕文案，标 `is_fill=True`）；② 包装补全（生成标题条/卖点卡片占位文字 + StyleRule 填色）；③ 素材复用（裁取相邻片段 zoom-in 0.5–1s 重复）；`allow_aigc=True` 时增加 AIGC 占位（Phase 5 实现）。
- **新增** `backend/app/apply/style.py`：`apply_style(segments, template, ledger, task_id) -> tuple[list[PlacedSegment], list[Caption], str|None]`；
  - 按 `StyleRule.caption` 生成 Caption 列表（text/start/end 来自账本 Unit；style 来自模板）
    - **字幕填充策略**：Caption.text 来自用户 Unit.text；但 LLM 选取 `emphasis_words`、生成补充字幕（Gap 场景）时，prompt 注入模板 caption 的 `placeholder_text` + `length_constraint` + `semantic_purpose` 作为视觉锚点，例如 `"模板这个槽位期望 4-6 字 CTA 强调短语，如'立即抢购'。请从用户素材这段 Unit 中选 1-3 个最相关字符作 emphasis"`
    - 每次 LLM 决策发 VisionEvent（stage="2.style.caption"）
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
10. **工作台端到端**：上传素材后点「打开 AI 工作台」→ 看到模板推荐推理（top-3 + 中文 reason）→ 选模板后看到 apply 全程事件流（ASR → 映射 → 缺口 → 字幕填充 LLM 看 placeholder 后选词）→ 总事件数 ≥ 15 条；右栏 ProjectIR 字段实时填充。
11. **placeholder 利用验证**：构造一个用户 Unit text 长度远超模板 length_constraint.max_chars 的 case → LLM 应基于 placeholder 截取或选取关键字符，不直接灌长文 → Caption.text 字符数落在约束内。

---

## 阶段 2.5: NL 编辑 + 参数面板 + 工作台事件回放 + 提取历史入口 📋

### 前置条件
- 阶段 2 的 `apply_short()` 可产出 ProjectIR 并渲染出 mp4（阶段 2 验证 7+9 通过）。
- 阶段 0.5 工作台 events.jsonl 持久化文件已稳定可读。
- 阶段 1B `tasks` 表 `resource_kind / resource_id` 字段已稳定写入（Phase 1B 验证 4 通过）。

### 目标
用户用自然语言或参数面板改 ProjectIR → 重渲染拿新 mp4；前端 Visualize 页升级为**工作台事件回放器**——从 `events.jsonl` 读历史按时间顺序重放整个识别 + 应用过程，可作为答辩 demo 录屏素材库；**样例 / 项目详情页补"提取历史"区块 + 工作台顶栏补面包屑**，把 task_id 唯一寻址升级为有目录的可寻址，杜绝"离开工作台就找不回上次跑过的 task"。

### 设计约束（本阶段必守）
- NL 编辑/参数面板修改都只改 IR 结构，不改像素；patch 可回滚（D3 / 核心原则）。
- 参数面板 = NL 的等价表单入口，二者都经统一 patch 路径（D11）。
- 高频编辑节流：300ms debounce 后再 trigger 重渲染；用户连续编辑时取消正在排队的旧渲染任务。
- NL 编辑产生的 patch 也发 VisionEvent（source="workbench"，stage="2.5.nl_edit"），让工作台能展示"用户说了什么 → LLM 翻译成什么 patch → 写入了 IR 哪个字段"。

### 后端改动
- **新增** `backend/app/agent/nl_edit.py`：
  - `nl_edit(project_ir, instruction, context, task_id) -> tuple[list[Patch], list[VisionEvent]]`：Text LLM 把自然语言指令翻成 Patch 列表（按 Patch op 枚举约束 JSON 输出）；prompt 提供当前 ProjectIR 摘要 + 模板骨架 + 可用 op 清单 + 模板 caption.placeholder/length_constraint（让 LLM 知道字幕长度/语气约束）；每个生成的 Patch 同时发一条 VisionEvent
  - `apply_patches(project_ir, patches) -> ProjectIR`：按 op 调度处理函数；版本号 +1 用于乐观锁
  - `panel_to_patches(field, old_value, new_value) -> list[Patch]`：参数面板改字段 → 生成等价 Patch（不发 VisionEvent，因为参数面板本身已经是可见操作）
  - 维护 `patch_history.jsonl` 追加写
  - `undo(project_id) -> ProjectIR`：读最后一条 patch 反操作
- **新增** `backend/app/api/edit.py`：
  - `POST /projects/{id}/edit` body `{instruction}` → 调 `nl_edit` → `apply_patches` → 重渲染（带 debounce/cancel）→ 返回 `{new_ir, patches_applied, render_task_id}`
  - `POST /projects/{id}/panel-edit` body `{field, old, new}` → 等价路径
  - `POST /projects/{id}/undo` 回滚
  - `GET /projects/{id}/history` 返回 patch 列表
- **新增** `backend/app/api/replay.py`（路径方案 B）：
  - `GET /projects/{id}/replay/events?task_id=<tid>` 返回指定 task 的 `events_{task_id}.jsonl` 全部事件 + 按 sequence 重建的 IR 快照序列。`task_id` 不传时默认返回 `tasks` 表 `WHERE resource_kind="project" AND resource_id={id} ORDER BY created_at DESC LIMIT 1` 的最近一次 task。
  - `GET /projects/{id}/replay/tasks` 返回该 project 历史所有 task 的列表（task_id + kind + status + created_at），供用户选哪次回放。
  - `POST /projects/{id}/replay/snapshot` body `{task_id, sequence}` 把项目 IR 临时回退到指定事件点状态（不持久化、仅录屏预览）。
  - **样例 extract 回放**同理走 `GET /samples/{id}/replay/events?task_id=...`（在 `api/samples.py` 加对称接口）。
  - Workbench 的"回放/否决事件"是 UI 操作不是 IR Patch（S6 修订）：UI 直接调 replay API + reject API（`POST /workbench/{task_id}/reject-event/{event_id}` 产出 `reject_vision_event` Patch 并触发子步重跑）。
- **扩展** `backend/app/api/projects.py`：`GET /projects/{id}/lineage` 返回迁移可视化数据（template 骨架 + 用户 Unit → Slot 映射表 + Gap 列表 + 各 Gap 的 fill_result + 当前 ProjectIR vs 初始 ProjectIR 的差异摘要）。
- **新增** `backend/app/agent/render_queue.py`：项目级渲染节流（同 project_id 的新渲染请求 cancel 之前未完成的）。

### 渲染服务改动
- **新增** `renderer/src/server.ts` 接口 `DELETE /render/{task_id}`：取消队列中未开始的任务；已在跑的任务标 cancelled 但不强 kill。

### 前端改动
- **扩展** `frontend/src/pages/Editor.tsx`：
  - 增加底部 `NLBar.tsx`（发送 instruction → 调 `/edit`）
  - 增加左侧 `ParamPanel.tsx`：字幕颜色 / 字号 / 位置 / 入场动画下拉、缩放强度滑块、节奏快慢滑块、BGM 选择 dropdown、模板替换 dropdown、强调词输入、**placeholder_text 编辑器**；改任何参数都生成对应 patch 调 `/panel-edit`；参数面板**双向 sync**：每次 ProjectIR 更新后回填表单当前值
  - 增加右侧 patch 历史 + Undo 按钮 + **「打开工作台看 NL 编辑解析过程」按钮**
  - 编辑后 Player 实时反映新 ProjectIR；渲染按钮触发完整出片
- **重写** `frontend/src/pages/Visualize.tsx` 为 **工作台事件回放页**：
  - URL：`/projects/:id/replay`
  - 顶部：时间线进度条（按 events 时间均匀分布，可拖拽、可暂停、播放速度 0.5x / 1x / 2x / 4x）
  - 中央：复用 `Workbench` 三栏页面布局（VisionPane + EventStream + IRPane），但事件源换成 `/projects/{id}/replay/events` 的历史数据，IRPane 按事件 sequence 重建 IR 快照
  - 顶部右上：「导出录屏」按钮（用 MediaRecorder API 录中央栏 30-60s 片段，输出 webm/vp9；Chromium/Firefox 原生支持；**Safari 已知不兼容 webm**（S8）→ Safari 用户提示"请用 Chrome/Edge/Firefox"，不做服务端转码 fallback（demo 阶段不值）
  - 底部：四步链路摘要（抽取 / 映射 / 缺口 / 补全）作为静态卡片，每张卡片可点击「跳到该步对应的事件区间」
- **扩展** `frontend/src/api/events.ts`：加 `fetchReplayEvents(projectId)` 与 `snapshotAtSequence(projectId, sequence)`

### 提取历史入口与工作台面包屑改动（建议 5 收口）

> 痛点定位：当前 Workbench 通过 task_id 唯一寻址进入，但前端没有任何"目录"——用户在样例上传页跳转到 `/workbench/{task_id}` 后，离开页面就再也找不到这次提取的入口；样例侧也没有"本样例历史所有提取任务"的列表。寻址表完全缺失。

- **扩展** `backend/app/api/samples.py`：
  - `GET /samples/{id}/tasks` 返回 `[{task_id, kind, status, progress, stage, created_at, updated_at}]`，按 `created_at DESC` 排序；底层 `tasks_store.list_by_resource(resource_kind="sample", resource_id=id)`
- **扩展** `backend/app/api/projects.py`：
  - `GET /projects/{id}/tasks` 对称返回该 project 所有 task；底层同 `list_by_resource`
- **扩展** `backend/app/tasks_store.py`：
  - `list_by_resource(resource_kind, resource_id) -> list[TaskRow]`：纯查询，加 `WHERE resource_kind=? AND resource_id=?` 索引
  - DB 迁移加 `idx_tasks_resource` 复合索引 `(resource_kind, resource_id, created_at DESC)`
- **扩展** `frontend/src/pages/SampleExtract.tsx`（样例上传 / 详情页）：
  - 详情区下方新增 `<ExtractHistoryList sampleId={id}>` 子组件：调 `GET /samples/{id}/tasks`，按时间倒序列出，每行 `{task_id 短哈希 / status 徽章 / stage / created_at 相对时间}`，行点击 → `navigate("/workbench/" + task_id)`
  - 失败/进行中的 task 用 `--color-warning / --color-info` 染色徽章区分
- **扩展** `frontend/src/pages/TemplateLibrary.tsx`：模板详情页"事件回放"按钮旁追加"本样例其它提取记录"折叠区（同 `<ExtractHistoryList>` 子组件复用）
- **新增** `frontend/src/components/workbench/WorkbenchBreadcrumb.tsx`：
  - 挂在 `Workbench.tsx` 顶栏左侧（与 view 切换器同一行）
  - 数据源：进入 Workbench 时按 `task_id` 查 `GET /tasks/{task_id}`（已有端点）拿 `resource_kind / resource_id`，再按 kind 取 `sample.name` / `project.name`（`GET /samples/{id}` / `GET /projects/{id}` 任一存在则展示）
  - 渲染：`样例 > {sample_name} > 提取任务 #{task_id 前 8 位}`，每段可点击；最后一段为当前任务、非链接
  - 失败回退：拉不到 resource 时只渲染 `任务 #{task_id 前 8 位}`，不阻塞页面

### 验证方式
1. `pytest backend/tests/integration/test_nl_edit.py`：固定 ProjectIR 测典型指令：
   - `"字幕改黄色描边黑色"` → patches 含 `{"op":"set_caption_style","value":{"color":"#FFD400","stroke_color":"#000000"}}`
   - `"节奏加快一点"` → patches 含 `{"op":"adjust_rhythm","value":{"scale":0.8}}`
   - `"换成模板 B 风格"` → patches 含 `{"op":"swap_template","value":{"template_id":"B"}}`
   - `"开头第一句强调'独家'"` → patches 含 `{"op":"set_emphasis","value":{"words":["独家"],"section_idx":0}}`
   - 非法指令 `"把视频翻转"` → 返回可读报错，ProjectIR 不变
   - 每条 patch 都对应一条 VisionEvent 发到 event_bus
2. `pytest backend/tests/integration/test_undo.py`：apply 3 patch → undo 2 次 → ProjectIR 回到第 1 patch 后状态、版本号正确。
3. 参数面板 ↔ NL 等价性：在 Editor 用面板改字幕色 → 看到 Player 更新；NL "字幕改红色" → 应得到相同 ProjectIR；二者 patch_history 内容等价。
4. 重渲染 cancel：连续 3 次 NL 编辑（每次间隔 100ms）→ 后台应只完成最后一次渲染。
5. **工作台事件回放**：访问 `/projects/{id}/replay` → 时间线从 0% 走到 100% → 三栏与原始任务跑时一致 → IRPane 字段填充顺序与 sequence 严格对应 → 导出 30s 录屏 webm 文件存在。
6. 端到端：浏览器在 Editor 输入"字幕换成黄色"→ 看到预览字幕变色 → 点渲染 → mp4 字幕变色 → 工作台第二栏出现"NL 解析：字幕颜色改 #FFD400"事件。
7. **提取历史端到端**（建议 5）：浏览器跑两次 `sample_basic_15s` extract（间隔 ≥ 1s）→ 离开 Workbench 回 `/samples/{sample_basic_15s}` → 看到 `ExtractHistoryList` 列出 2 条任务（时间倒序）→ 点第一条 → 进入对应 `/workbench/{task_id}`；Workbench 顶栏面包屑显示 `样例 > sample_basic_15s > 提取任务 #{tid}`，点击"样例"段回到样例详情页。
8. **面包屑容错**：手动构造一个 `tasks` 表里 `resource_kind=NULL` 的旧任务 → 进入 Workbench → 面包屑回退为 `任务 #{tid}`，不报错、不空白。

---

## 阶段 2.6: AI 决策工作台 v4 升级（甘特图 + 媒体时间线 + 因果链 + 回归基础设施）📋

### 前置条件
- 阶段 2 ★MVP 闭环已稳定（Phase 2 验证 7+9+10 通过；短素材选模板出 mp4 + 工作台事件流可见）。
- 阶段 2.5 工作台事件回放器已稳定（Phase 2.5 验证 5+6 通过；events.jsonl 历史文件可读、Visualize 页能拖拽时间线）。
- Phase 0.5 已在 `VisionEvent` IR 加 `duration_ms` 字段、`llm.client.chat_vision()` 已用 `time.perf_counter()` 自动回填该字段。
- **本阶段在 `VisionEvent` IR 加 `media_ts: float | None` 与 `media_ts_range: tuple[float, float] | None` 字段**（Phase 0.5 已完工不回填字段，本阶段补 schema 增量 + gen_schema 重生成 zod），含义为"该事件锚定的视频媒体时间（秒）/ 时间区间"。约定填充规则：单帧型事件（caption_style / sticker / zoom_direction 等含 `frame_url` 的实体事件）填 `media_ts` 为该帧 ts；跨段事件（tagging / sanity_check / segment）填 `media_ts_range` 覆盖区间；无关事件（system / progress）两者皆 null。CI `scripts/check_event_emission.py` 守住"实体事件至少有一项 media_ts*"。所有 1A / 1B 已落地的 `chat_vision()` 发事件处按子能力补一次 `media_ts=ts`（无新事件、只是补字段）；后续 Phase 不需重跑 golden_runs（旧 events 字段缺失等价两者皆 null，回归仍绿）。
- Phase 1A 已对两阶段 VLM 调用强制填 `parent_event_id`（CI `scripts/check_parent_event_id.py` 绿）。
- Phase 1B 已 commit 至少 3 个 sample 的 `tests/fixtures/golden_runs/{sid}/{events.jsonl, template.json}` 种子文件（Phase 1B 验证 8）。

### 目标
把工作台从「事件列表 + 回放器」升级为「壁钟甘特图 + 媒体时间线 + 因果链可视化 + AI 决策痕迹回归基础设施」。四件事是同一份数据（events 流）的四种新用法：
1. **壁钟甘特图视图**：把 1A 子能力的并发 + Phase 3 step 的串行用 lane 形式可视化，横轴为 wall-clock；"30 秒 extract 里 VLM 字幕花 5s、贴纸 8s、调色 3s 并发完成"一眼可见——服务于 AI 工程师 / 调试视角
2. **媒体时间线视图（建议 3）**：以**视频媒体时间**（不是壁钟）为横轴，事件以 marker 落点在时间线上；顶部嵌入原视频 `<video>` 播放器，播放头与 marker 双向联动——服务于创作者 / 产品视角，回答"视频第 3.4s 处 AI 都做了什么决策"
3. **因果链可视化**：父子事件在工作台中栏 + 两个时间线视图上画 dashed line，"识别红色矩形 → 判为 CTA → 决定字幕样式 = 强调红色" 的推理路径可见
4. **events.jsonl 作 regression fixture**：通过 `ReplayClient` 把历史 events 重放到 mock VLM → 验证 IR 重建一致性；模型升级 / 子能力代码改动时 CI 自动跑、IR 字段语义漂移立即被发现

> **为什么不与壁钟甘特图合并**：横轴语义不同——甘特图横轴是"调用何时发起、跑了多久"，媒体时间线横轴是"事件指向视频的哪一刻"。两轴互补不重叠；同一份 events 数据、两种投影。在统一视图里同时承载两种横轴会让 hover / zoom / selection 语义打架。

> **方法论**：工作台从"被动观测"升级为"AI 治理基础设施"。这四件事共享同一套渲染管线（hover 联动、`selectedEventId` state、stage 染色）与同一份数据（events 流），因此打包到一个阶段而非分散到 1A/1B/2.5 各处。

### 设计约束（本阶段必守）
- **实时增量渲染**：甘特图与媒体时间线都必须支持 SSE 推一条事件 → SVG 增加/更新一个横条或 marker，不全量重画；用 visx 的 React 声明式管线天然支持（避免 D3 命令式 enter/update/exit 心智负担）。
- **四视图共享 selection state**：列表 / 帧 / IR 树 / 甘特图 / 媒体时间线五种视图共享 `workbench.ts` 的 `selectedEventId` Zustand state；任一视图点选 → 其他视图联动高亮。
- **媒体时间线 ↔ 视频播放头双向 sync**：视频播放进度推送 `currentMediaTs` → marker 高亮当前 ts 邻域 ±0.5s 内的事件；点击 marker → `<video>.currentTime = event.media_ts`；拖拽时间轴游标 → 视频 seek。
- **ReplayClient 纯函数性**：同一 fixture 跑两次必产出位级别一致的 IR；ReplayClient 不调任何外部 API（无网络依赖，CI 毫秒级跑过）。
- **golden_runs 入库 review 强制**：种子文件入库时必须人工 review 一遍 events.jsonl（无 PII / 无 API key 泄漏 / IR 字段语义符合预期），review 通过才 git commit；CI 跑 ReplayClient 与 commit 的 golden IR 比对。
- **不加 `child_event_ids` 双向链**：前端从 `events` 列表按 `parent_event_id` O(1) 增量构建 `childIndex: Map<parentId, eventId[]>`，避免后端 schema 冗余字段、避免父事件发出后回头改的逻辑复杂度。

### 后端改动
- **扩展** `backend/app/api/events.py`：新增 `GET /api/tasks/{task_id}/gantt` 端点，从 `events_{task_id}.jsonl` 聚合返回 visx 友好的 lane 列表 `{lanes: [{stage, color_token, events: [{event_id, start_ms, duration_ms, semantic_label, parent_event_id, reasoning, confidence}]}], total_duration_ms: int}`；按 stage 命名规范前缀分组（`1A.captions` 与 `1A.captions_anim` 同 lane group 还是分两 lane？默认按完整 stage 字符串分 lane，超过 20 lane 时折叠到 stage 前缀第一级——保留扩展空间）。
- **扩展** `backend/app/api/events.py`：新增 `GET /api/tasks/{task_id}/media-timeline` 端点（建议 3 媒体时间线），从 `events_{task_id}.jsonl` 聚合返回 `{markers: [{event_id, media_ts | null, media_ts_range | null, stage, color_token, semantic_label, parent_event_id, reasoning, confidence, frame_url | null}], video_url: str, video_duration_sec: float}`；只输出含 `media_ts` 或 `media_ts_range` 的事件，过滤 `media_ts*` 全 null 的系统事件；`video_url` 按 `task.resource_kind / resource_id` 反查 `samples/{sid}/normalized.mp4` 或 `projects/{pid}/normalized.mp4` 静态路径。
- **新增** `backend/app/llm/replay_client.py`：
  - `class ReplayClient(LLMClient)`：实现 `LLMClient` 抽象基类的所有方法（`chat_vision` / `chat_text` / `transcribe` / `extract_bgm`）
  - 构造时传 `golden_run_path: str` → 读 events.jsonl 到 `dict[stage, deque[VisionEvent]]`（按 stage 维护 FIFO 队列）
  - 调用 `chat_vision(stage, ...)` 时从对应 stage 队列 popleft 一条 event → 用 `event.ir_value` 重建 `BaseModel`（pydantic 反序列化）→ 返回 `(reconstructed_result, [event])`
  - `event_bus.publish` 仍调用（重放也走相同事件总线），便于测试同步验证 SSE 链路
  - 队列空时 raise `ReplayExhaustedError` 提示 "golden run 缺事件，stage=X"
- **新增** `scripts/record_golden.py`（typer CLI）：
  - `record-golden --sample SID` → 用真实 client 跑 `extract_template(SID)` → 跑完后 copy `data/samples/{SID}/extracted/events_{task_id}.jsonl` 与 `kb.sqlite` 里对应 `TemplateIR.model_dump_json(indent=2)` 到 `tests/fixtures/golden_runs/{SID}/{events.jsonl, template.json}`
  - 不自动 git add（强制人工 review 后 commit）
- **新增** `backend/tests/integration/test_golden_runs.py`：
  - `@pytest.mark.parametrize("sample_id", os.listdir("tests/fixtures/golden_runs"))`
  - 每个 sample：构造 `ReplayClient(golden_runs/{sid}/events.jsonl)` → 用依赖注入替换默认 client → 跑 `extract_template(sid)` → 与 `golden_runs/{sid}/template.json` 加载的 `TemplateIR` 做 `model_dump(mode='json')` 深度对比 → assert 一致
  - diff 时输出 jsonpatch 风格的差异（用 `jsondiff` 库）

### 前端改动
- **扩展** `frontend/package.json`：加 `@visx/scale@3.x` / `@visx/zoom@3.x` / `@visx/group@3.x` / `@visx/responsive@3.x` / `@visx/text@3.x`（visx 模块化，按需引入，gzipped ~50KB）
- **新增** `frontend/src/pages/WorkbenchGantt.tsx`（路由：`/workbench/:taskId?view=gantt`，也作为 `Workbench.tsx` 的可切换 tab）：
  - 顶部 ResponsiveContainer：X 轴时间轴（`@visx/scale.scaleLinear`，domain=[0, total_duration_ms]，range=[0, container_width]）；Y 轴 lane 列表（`scaleBand`）
  - 中央 SVG：
    - **lane 背景**：斑马纹 `<rect>`（偶数 lane 浅灰），lane header 文字（stage 全称 + 事件数 badge）
    - **横条**：`duration_ms > 0` 的事件，`<rect x={scale(start_ms)} y={laneY} width={scale(duration_ms)} height={16} fill={stageColor}>`；hover 显示 tooltip（stage / duration / reasoning / confidence）
    - **竖线**：`duration_ms == 0` 的瞬时事件，`<line x1={scale(start_ms)} y1={0} x2={scale(start_ms)} y2={containerHeight}>`，hover tooltip
    - **因果链**：`parent_event_id` 链上的事件间画 `<path d="M parent.endX,parent.midY Q midX,midY child.startX,child.midY" stroke-dasharray="4,4">`（贝塞尔曲线，从父事件横条右端连到子事件横条左端）
  - 缩放/平移：`@visx/zoom.useZoom` 鼠标滚轮缩放（scale 0.1x~10x）+ 拖拽平移；长视频任务 500+ 事件不卡（visx 按 React reconciliation 增量 diff，未变化的 `<rect>` 不重渲染）
  - lane 折叠：默认只展开"近 5s 内有事件"的 lane，其余 lane header 折叠（点击展开）；解决长视频 9 step 全展开占屏问题
  - 点击横条/竖线 → `setSelectedEventId(event_id)` → URL 切回 `?view=list`、Workbench.tsx 中栏自动滚到该事件
- **新增** `frontend/src/components/workbench/CausalChainOverlay.tsx`（中栏 + 右栏共用）：
  - 维护 `Map<eventId, DOMRect>` 记录每张事件卡片在中栏的位置（用 `ResizeObserver` + `forwardRef`）
  - 根据 `childIndex` 画 SVG `<path>` overlay 连父子卡片
  - hover 父事件 → 所有子卡片加 `border: var(--accent-primary)`；反之亦然（与甘特图同步）
- **扩展** `frontend/src/state/workbench.ts`：
  - 加 `view: "list" | "gantt" | "media_timeline"`（URL query param 同步）
  - 加 `selectedEventId: string | null`（多视图共享）
  - 加 `currentMediaTs: number | null`（媒体时间线视图当前播放头 / 拖拽位置，供 marker 高亮邻域计算用）
  - 加派生 selector `childIndex: Map<parentId, eventId[]>`（从 `events` 数组 useMemo 增量计算；events push 时 O(1) 更新）
- **扩展** `frontend/src/api/events.ts`：`fetchGanttData(taskId): Promise<GanttLanes>` 调 `/api/tasks/{taskId}/gantt`；`fetchMediaTimeline(taskId): Promise<MediaTimelinePayload>` 调 `/api/tasks/{taskId}/media-timeline`
- **新增** `frontend/src/pages/WorkbenchMediaTimeline.tsx`（路由：`/workbench/:taskId?view=media_timeline`，也作为 `Workbench.tsx` 的可切换 tab）：
  - 顶部：`<video src={video_url} controls>` 嵌入原视频；`onTimeUpdate` 持续 push `currentMediaTs` 到 store
  - 中央 SVG：单一时间轴（`scaleLinear` domain=[0, video_duration_sec]），按 stage 分若干横向条带（每个 stage 一行 lane）；事件按 `media_ts` 落点为小三角 marker（`<polygon points="0,-6 -5,4 5,4">`），`media_ts_range` 事件渲染为半透明矩形条段（`<rect>` width=range 长度）
  - **播放头联动**：`currentMediaTs` 处画竖线 `<line stroke="var(--accent-primary)">`；±0.5s 邻域内 marker 加 `accent-primary` 描边
  - **marker 交互**：hover 显示 tooltip（stage / media_ts / reasoning 摘要 / frame_url 缩略图）；点击 marker → `setSelectedEventId(event_id)` + `<video>.currentTime = media_ts`，URL `?view=list` 时其他视图同步高亮
  - **拖拽时间游标**：在时间轴顶部放一个 `<rect>` cursor handle，鼠标拖拽 → `<video>.currentTime = ts` + 更新 `currentMediaTs`
  - **因果链**：复用 Gantt 同一套 `parent_event_id` 渲染逻辑，dashed `<path>` 连父 marker → 子 marker
- **扩展** `frontend/src/pages/Workbench.tsx`：顶栏加 view 切换 segmented control（5 选 1：列表 / 帧 / IR 树 / 甘特图 / 媒体时间线）；URL `?view=` query param 双向同步；切换时复用同一 `taskId` 的 events 数据，不重新 fetch

### 渲染服务改动
- 无（本阶段不涉及渲染）。

### 工作区与 CI 改动
- **新增** `tests/fixtures/golden_runs/README.md`：解释录制 / review / commit 流程；说明何时需要重录（IR 字段语义变更 / 子能力 prompt 改 / 新模型上线）
- **扩展** `.github/workflows/ci.yml`：加 `golden-runs` job——纯 CPU pytest 跑 `test_golden_runs.py`，0 API key 依赖；run 在 `python` job 之后但与 `integration` 并行
- **新增** `scripts/check_parent_event_id.py`：CI grep 校验脚本（在 Phase 1A 已声明，本阶段实际写代码）；扫源码所有"两阶段"VLM 调用函数（命名匹配 `*_refine` / `*_phase2` / `*_classify` 或函数 docstring 包含 "two-stage"），校验函数体内 `chat_vision()` 调用是否传 `parent_event_id=` 关键字参数；缺则 fail

### 验证方式
1. **甘特图端到端**（短素材）：浏览器跑 `sample_basic_15s` extract → 切换甘特图视图 → 看到 ≥ 5 个 lane（`1A.scenes` / `1A.captions` / `1A.stickers` / `1A.zoom_direction` / `1A.audio`）+ ≥ 10 个横条 + 至少 1 条因果链 dashed line；鼠标滚轮缩放、拖拽平移流畅（FPS ≥ 50）；hover 横条 tooltip 显示 stage + duration + reasoning。
2. **长视频甘特图**：跑 `long_3min` Phase 3 9 step → 甘特图显示 9 个 lane group（按 step 分组）+ 500+ 事件不卡（FPS ≥ 30）；lane 折叠功能可用。
3. **因果链联动**（中栏 ↔ 甘特图双向）：在中栏 hover "贴纸语义判断" 事件卡片 → 其父事件 "贴纸 bbox 检测" 卡片加 accent border + 中间画虚线；切到甘特图视图 → 同样虚线跨 lane 连接两事件 + 两横条同步高亮。
4. **ReplayClient round-trip**（`pytest backend/tests/integration/test_golden_runs.py`）：
   - 用 `ReplayClient(golden_runs/sample_basic_15s/events.jsonl)` 替换默认 client → 跑 `extract_template("sample_basic_15s")` → 与 `golden_runs/sample_basic_15s/template.json` deep equal 通过
   - 故意改 `CaptionStyle.placeholder_text` 默认值（如 list 改回 str）→ test fail + jsondiff 输出指向该字段
   - 故意 push 一个 1A 子能力的 prompt 微调 commit（不改 IR 字段）→ ReplayClient 不走真实 VLM 所以 test 仍绿（证明回归测试只盯 IR 字段稳定性，不会被 prompt 变化误报）
5. **golden runs 录制流程**：`python scripts/record_golden.py --sample sample_basic_15s` → `tests/fixtures/golden_runs/sample_basic_15s/{events.jsonl, template.json}` 生成 → git diff 显示新增 2 文件 → 人工 review 无 PII → commit。
6. **CI golden-runs job 绿灯**：push → Actions 该 job 通过（不需 GPU、不需 API key、< 5s 跑完）；故意 push 一个修了 IR 字段语义的 commit → 该 job 红 + diff 提示具体字段。
7. **视图切换 URL 同步**：手动改 URL `?view=gantt` ↔ `?view=list` ↔ `?view=ir` ↔ `?view=media_timeline` → Workbench 顶栏切换器 + 实际视图同步切换；浏览器后退按钮可回到上一个 view。
8. **媒体时间线端到端**（建议 3）：跑 `sample_basic_15s` extract → 切到媒体时间线视图 → 视频可播放、播放时游标随播放头滑动、邻域内的事件 marker 加 accent 描边；点击 marker → 视频跳到该 `media_ts` + 中栏卡片高亮；拖拽时间游标到 8s 处 → 视频跳到 8s + marker 高亮邻域更新；hover marker tooltip 显示 stage + media_ts + reasoning 摘要 + 帧缩略图。
9. **答辩演示价值验证**（主观）：录一段 30s 屏幕录像，开场 5s 切到甘特图视图 → 评审一眼看到"AI 30 秒里到底干了什么"——这是项目可解释性的视觉冲击点；中段切因果链 hover → 展示"AI 的思考链"；尾段切媒体时间线 → 演示"视频任意一刻 AI 做了什么决策"，三视图互补呈现可解释性。

### 课题对齐
- **评分项 6（迁移过程可视化，10 分）**：甘特图 + 因果链把"迁移过程"从"日志列表"升级为"调度时间线 + 推理图谱"，直接命中"清晰展示如何迁移、如何补全"的高分要求
- **加分项"对'结构迁移'有较强的可解释性展示"**：因果链 + ReplayClient 把"可解释性"从"展示给人看"扩展到"机器可验证"——这是工程力上的差异化
- **加分项"有较好的工程质量、交互细节或视觉完成度"**：CI golden-runs job 是质量门体现工程化成熟度；visx + 因果链 SVG 渲染是交互细节
- **答辩动线开场冲击力**：甘特图是 30 秒可视化爆点，比"事件列表"叙事性更强

### 已明确不做（本阶段范围内）
- **VisionEvent.child_event_ids 双向链字段**：前端反向 O(1) 增量构建索引足够，无需后端冗余字段
- **甘特图导出 PNG/SVG**：浏览器右键截图或用 Phase 2.5 已实现的 MediaRecorder 录屏即可；专门做导出按钮 ROI 低
- **TapFlow 风格的命令式 D3.js**：与实时 SSE 场景不匹配 + 与 React 心智模型冲突，改用 visx
- **gantt-chart 商业库（react-gantt-task 等）**：商业项目调度风格无法表达"AI 子能力 lane"语义

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
- **D13 强化**：每个 step 的 LLM/VLM/audio/CV 调用使用专属 stage 前缀（`3.step01.asr` / `3.step02.vad` / `3.step03.dedup` / `3.step04.segment` / `3.step05.select` / `3.step08.quality` / `3.step09.render`），事件流按方案 B 落 `projects/{pid}/pipeline/events_{task_id}.jsonl`；工作台支持按 stage 过滤，每个 step 的 review UI 加「打开工作台看本 step 决策过程」按钮直接深链跳转 `/workbench/{task_id}?stage_filter=3.step{n}`。Step rerun 时按 task_id 软关闭旧 events 文件 + 新建新文件（事件不残留、不混淆）。

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
7. **工作台 per-step 验证**：完成完整 9 step 跑通后访问 `/workbench/{task_id}?stage_filter=3.step03` → 只看到 dedup 相关 VisionEvent；切换 `?stage_filter=3.step05` → 只看到 select_template 相关事件；Rollback to Step 03 后 stage_filter=3.step03 之后的事件应已清除（不出现幽灵事件）。

### 课题对齐
- 任务 2 结构拆解（段落 + 节奏 + 包装）→ Step 02-04 直接产出
- 任务 7 迁移过程可视化 → 分步审核每 step 暴露中间产物（评审能"看见"AI 决策）
- 任务 12 人工可调（hook/包装/节奏/结尾）→ 分步审核 + NL 编辑覆盖全部

---

## 阶段 4: 标题条 + 音效预设注入 📝

### 目标
在 1A 已把蒙版 / 调色 / 转场识别消化掉之后，Phase 4 只剩两件事：① 标题条 / 卖点卡片识别——口播视频里出现频率最高、价值最大的视觉包装元素；② 音效**预设注入**（不识别样例音效，用户手工配）。所有 D3 字段在 1A 已能产出，TemplateIR 不再有"D2 vs D3"的字段层级。

### 前置条件
- 阶段 1A 的转场分类 / 几何蒙版 / 调色语义三项子能力指标基线达标且 1B 集成稳定 ≥ 1 个月，或 5+ 样例 fixture 覆盖。
- `data/system/sfx_pool/`（音效池）已放置 5–10 个常用音效（whoosh / ding / pop / 打字音 / swoosh / impact / …）+ `sfx_index.json` 元数据。

### 设计约束
- 标题条识别采 VLM 主路径——VLM 看采样帧给「位置 + 颜色 + 文字结构（不识别文字字符）+ 出现时段」，发 VisionEvent；不走 OCR 长矩形检测。
- 音效**只做注入**，不做识别（口播样例里基本没有可学的音效）。
- D2 基线指标不退步。

### 子能力 4-1 标题条识别（VLM）
- **新增** `backend/app/extract/title_bar.py`：`detect_title_bars(scenes, frames, task_id) -> list[TitleBarEvent]`
  - VLM 看采样帧 → 判"是否有屏幕顶/底的彩色长矩形带"，有则给 `{position_norm_0_999, height_norm, bg_color_hex, text_color_hex, text_layout: "single"|"multi", placeholder_text, semantic_purpose, time_range_within_scene, reasoning}`
  - 跨帧追踪同一标题条（IoU > 0.6）→ 合并
  - 每次识别发 VisionEvent（stage="4.title_bar"）
- **数据结构**：在 `TemplateIR.global_style` 或 `StyleRule` 加 `title_bars: list[TitleBarEvent]` 字段
- **指标基线**：bbox IoU ≥ 0.7；颜色 hex 与人工标注 ΔE < 10；存在/不存在判定 ≥ 90%
- **渲染**：`renderer/src/compositions/TitleBar.tsx` 按 placeholder_text + 用户素材对应字幕渲染

### 子能力 4-2 音效预设注入（用户手工配 + FFmpeg 混入）
- **新增** `backend/app/agent/sfx_preset.py`：
  - `list_sfx_presets() -> list[SFXPreset]`：读 `data/system/sfx_pool/sfx_index.json`，返回 `[{id, name, file_path, category: "whoosh"|"ding"|"pop"|...}]`
  - `assign_sfx_to_template(template_id, slot_idx, time_within_slot, sfx_id, gain_db) -> TemplateIR`：用户在模板编辑界面手工标"在 Slot N 的 t 秒触发音效 X"
  - `mix_sfx_into_audio(voice_track, bgm_track, sfx_events, output) -> str`：FFmpeg 滤波器 `amix` 把音效叠加到合并轨上
- **API**：`PATCH /templates/{id}/sfx` body `{slot_idx, time, sfx_id, gain_db}` 添加/修改音效配置
- **前端**：TemplateLibrary 详情页加「音效配置」面板（每个 Slot 一行可加音效），可在 RemotionPlayer 预览试听
- **验证**：模板配 3 个音效（开头 whoosh + 中间 ding + 结尾 pop）→ 渲染输出 mp4 → 音轨可听到三个音效准确出现在指定时间点

### 已砍项（不在本阶段范围）
| 项 | 状态 |
|----|--------|
| 转场分类 / 几何蒙版 / 调色 LUT | **已纳入 Phase 1A**（VLM 主路径直接给参数，不属于 Tier B 升级范围）|
| 音效**识别**（从样例提取） | 不识别，改为预设注入 |
| 高潮位置 | 不做，语义高潮合并到 Phase 7 `narrative.energy` |
| 画面缩放出框 | 不做，canvas 归一化处理 |
| 变速**识别**（从样例提取） | 不做，应用端 D8 时长自适应保留主动变速 |

### 验证方式
1. `pytest backend/tests/integration/test_title_bar.py`：3 个含标题条 fixtures → bbox IoU ≥ 0.7 + 颜色 ΔE < 10
2. D2-extended 基线回归：跑 Phase 1A 全套测试集，指标退步 ≤ 5%（1A 已涵盖 Phase 4 所需的核心识别）
3. 音效端到端：模板编辑界面给 `sample_basic_15s` 配 2 个音效 → 应用到 `test_short_15s` → 渲染 mp4 → 主观验收音效准时出现 + 不盖人声
4. 工作台验证：标题条识别过程在工作台可见（stage="4.title_bar"）

### 待讨论的问题
- 音效 gain 自动 ducking 策略（当音效与人声重叠时是否需要 sidechaincompress）

**SFX schema 明确（S13）**：`data/system/sfx_pool/sfx_index.json` 格式：
```json
[
  {"id": "whoosh_01", "name": "Whoosh 短", "file_path": "whoosh_01.mp3",
   "category": "whoosh", "duration_ms": 350, "loudness_lufs": -16.0, "license": "CC0"},
  ...
]
```
category 取值：`whoosh | ding | pop | typing | swoosh | impact | bell | transition_woosh`（初始集合，扩展时直接加新值，前端按 category 分组下拉）。

---

## 阶段 5: AIGC 扩展（生图 + 视频生成 + 封面） 📝

### 目标
接入第三方生图 API（生成**贴纸图形** + **封面**）+ 视频生成 API（生成 B-roll 画面），由用户主动触发；产物明确披露 AI 内容；强缓存避免重复成本。

### 前置条件
- 阶段 1B 已稳定输出 StickerEvent.description；阶段 2 已稳定运行单段闭环；阶段 2.5 NL 编辑已支持 `mark_aigc` patch。

### 设计约束
- D10：绝不自动启用 AIGC；所有调用都有用户显式确认。
- 失败降级：API 不可用时 fallback 到占位符 + 提示用户。
- 缓存：按内容 hash 全局复用，避免重复支付。
- 安全：prompt 注入防御 + 内容审查（API 自带或调 moderation endpoint）。
- 成本追踪：每次调用记 `tasks.aigc_cost` 字段；UI 显示项目总成本。
- **D13 强化**：每次 AIGC 调用前发 VisionEvent（stage="5.aigc.{kind}"，semantic_label="生成请求"，reasoning 含 prompt 摘要 + 风格 hint）；生成完成后再发一条（含产物 url + 缓存命中 true/false + 耗时）。工作台第二栏可看到每次 AIGC "为什么生成 / 生成了什么"。

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
- Phase 3 长视频分步审核管线稳定（除 Step 06 之外的 8 个 step 均能跑通，Phase 3 7 项验证全过——含"工作台 per-step 验证"）。
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
- **D13 强化**：narrative score 每段评分 + dependency 检测 + 每个 reorder plan 生成都发 VisionEvent，**stage 命名按"stage 命名规范"表归在 Phase 3 命名空间下**：`3.step06.reorder.score` / `3.step06.reorder.deps` / `3.step06.reorder.plan`（不用 `7.narrative.*`，避免 stage 前缀与 phase 号交叉冲突；Phase 7 是 Step 06 的实现升级，事件仍属于长视频 step 06 命名空间）。每个 Plan 的 rationale + role_assignments 在工作台第三栏渲染为可视化"叙事角色染色"动画。

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
  - `score_sections(sections, ledger, task_id) -> tuple[list[NarrativeScore], list[VisionEvent]]`：Text LLM（推理模型 `MODEL_TEXT`）输入 = 每 section 的 unit_ids 对应 ASR 文本 + 时长 + 模板标签；prompt 要求按 hook/卖点/CTA/过渡四维打分并给中文 reasoning；JSON mode 输出。每段评分一条 VisionEvent（stage="3.step06.reorder.score"，source="text_llm"，ir_target 指向 `pipeline.step06.scores[section_id]`）。
  - `detect_dependencies(sections, ledger, task_id) -> tuple[list[Dependency], list[VisionEvent]]`：Text LLM 检测代词/指代（"刚刚说的"、"这个"、"上面提到的"、"前面"），输出依赖图；标 `can_break=false` 表示打破后语义无法理解。每条依赖一条 VisionEvent（stage="3.step06.reorder.deps"）。
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
  - 整体 AI 架构图（含 Python/Node/前端 三服务关系 + 数据流 + AI 透明工作台事件总线）
  - 工具协议 IO schema（Agent 工具协议章节列举的所有 tool 的 JSON schema + VisionEvent schema）
  - **AI 工具使用披露**（课题要求）：① 使用了哪些 AI 工具（WhisperX / Demucs / silero-VAD / Text LLM（Claude / Qwen）/ VLM（Qwen-VL-Max / Claude Sonnet / GPT-4o）/ 生图 API / 视频生成 API）；② 各工具用于哪个环节（VLM 主路径覆盖视觉理解任务，CV 守动画细节/缩放曲线，专用模型守时间/音频）；③ 哪些部分属于自主设计与实现（IR schema、账本机制、**AI 透明工作台事件流机制**、骨架发现算法、apply/render 管线、NL 编辑 patch 协议、AIGC 触发协议、渲染队列、跨服务 IR 同步管线、**VLM 客户端协议与 VisionEvent 强约束**）
  - **安全边界**：AIGC 内容审查 + 披露；BGM features vs original 双策略 + 版权说明；用户上传内容合规审核；prompt 注入防御；ASR 错误降级；服务故障降级；数据生命周期与清理。
  - **第一性原理：视频理解技术选型**（本 plan "视频理解技术选型" 章节的精简版）：解释为何 VLM 主路径化 + 时间/音频/动画微观精度由专用工具守底。

---

## 改动点总结

### v3.3（2026-06-09）：Phase 1B 用户反馈 — 媒体时间线 + 提取历史入口

Phase 1B 成品试用反馈把"看不到原视频"+"VLM 卡片乱序"+"Reasoning 截断"+"离开工作台找不回 task"四个工作台体感缺口逼出来。判断后：

- **前三条合并为一条 Issue 走 003ISSUES.md 修代码（ISS-011）**：均为 Phase 0.5 / Phase 1B 已落地的 UI 缺陷（右栏视频入口在原视频帧位置补 video 元素 / 中栏按 stage 分组视图 / Reasoning 折叠展开），同源同栈、一次性收口，不进 Plan 正文也不拆为三条 issue。
- **后两条进 Plan**：媒体时间线是新视图（与 Phase 2.6 壁钟甘特图正交、共用同一份 events 数据），提取历史入口是寻址表层缺失（需后端补 `list_by_resource` 查询 + 前端 `ExtractHistoryList` + Workbench 面包屑）；均不属于 Issue 修补可覆盖的范围，按阶段性新能力规划。

**Phase 2.5 扩展**：标题升级为「NL 编辑 + 参数面板 + 工作台事件回放 + 提取历史入口」；新增"提取历史入口与工作台面包屑改动"小节——后端 `GET /samples/{id}/tasks` + `GET /projects/{id}/tasks` + `tasks_store.list_by_resource`；前端 `<ExtractHistoryList>` 子组件 + `WorkbenchBreadcrumb.tsx`；DB 加 `idx_tasks_resource` 复合索引。验证方式追加 7 / 8（端到端 + 面包屑容错）。

**Phase 2.6 扩展**：标题升级为「甘特图 + 媒体时间线 + 因果链 + 回归基础设施」；目标从三件事升级为四件事。Phase 0.5 前置条件追加 `VisionEvent.media_ts: float | None` 与 `media_ts_range: tuple[float, float] | None` 字段约束 + CI 守住"实体事件至少有一项 media_ts*"；后端新增 `GET /api/tasks/{task_id}/media-timeline` 端点；前端新增 `WorkbenchMediaTimeline.tsx` 页面（顶部嵌入 `<video>` + 时间轴 marker + 播放头双向 sync + dashed 因果链复用）；`workbench.ts` 加 `view` 第三值 `"media_timeline"` + `currentMediaTs`；Workbench 顶栏 view 切换器 4 选 1 → 5 选 1。验证方式追加 8（媒体时间线端到端），原 8 顺延为 9。

**与 Phase 2.6 壁钟甘特图的边界**：两视图横轴语义不同，互补不重叠——甘特图横轴是 wall-clock（"调用何时发起、跑了多久"，服务调试视角）；媒体时间线横轴是 media time（"事件指向视频的哪一刻"，服务创作者视角）。同一份 events 数据、两种投影。

**这一轮工作量**：
- 文档：PLAN.md 局部改（阶段总览 / Phase 2.5 / Phase 2.6 / 本节）+ 003ISSUES.md 新增 1 条 Issue（ISS-011 合并工作台三处体感缺陷）
- 实际编码：Phase 2.5 ExtractHistoryList + Breadcrumb 大致 0.5 天；Phase 2.6 MediaTimeline 大致 1.5 天（在已有 Gantt 渲染管线基础上复用 visx + 视频 sync）

---

### v3.2（2026-06-07）：工作台 v4 升级 — 甘特图 + 因果链 + 回归基础设施

v3.1 通读核查 + `docs/proposals/001-ai-decision-workbench-v4.md` 提案评审后，把 3 条 🟢 P1 提案（O11 / O3 / O2）打包到新增的 Phase 2.6 实施。三者本质同源——都是 events 流这份数据的不同用法（按时间维度排成 lane / 按因果维度排成图 / 反向作为 ReplayClient 输入），因此放同一阶段而非分散。

**新增 Phase 2.6 阶段**：位于 Phase 2.5 之后、Phase 3 之前。理由：①Phase 2 ★MVP 已经能出片，工作台已有真实事件流可供甘特图消费；②Phase 1B 完工时已 commit golden_runs 种子供 ReplayClient 回放；③Phase 3 长视频 9 step 调度天然受益于甘特图视图（开场冲击力强）；④不阻塞 ★MVP 主路径。

**前期阶段的零成本"埋点"**（无新工程，只是约束声明）：
- Phase 0.5：`VisionEvent` IR 加 `duration_ms: int = 0` 字段；`chat_vision()` 客户端层用 `time.perf_counter()` 自动回填——子能力代码零侵入
- Phase 1A 设计约束追加"两阶段 VLM 调用必填 `parent_event_id`"强约束 + CI `scripts/check_parent_event_id.py` 校验脚本
- Phase 1B 验证方式追加第 8 条 "Golden runs 种子录制"——完工 close-out 时把 ≥ 3 个 fixture 的 events.jsonl + TemplateIR 复制到 `tests/fixtures/golden_runs/` git-commit

**Phase 2.6 三项新能力**：
1. **甘特图视图（O11）**：用 `@visx/scale + @visx/zoom + @visx/group` 实现 SVG 甘特图；lane = stage、横条 = 长程事件（`duration_ms > 0`）、竖线 = 瞬时事件；与中栏 EventStream 共享 `selectedEventId` 双向联动。**技术栈第一性原理选型**：visx 而非 TapFlow 借鉴的命令式 D3——后者与实时 SSE 增量场景不匹配，且与现有 React 心智模型冲突；visx 是 React 友好的 D3 包装（d3-scale/d3-zoom 的 hooks），bundle ~50KB gzipped。
2. **因果链可视化（O3）**：parent_event_id 已是 v3 IR 字段但 v3 / v3.1 未真正用起来。v3.2 强约束所有两阶段 VLM 调用必填 + 工作台中栏 + 甘特图都画 SVG dashed `<path>` 连父子事件 + hover 联动。**v3.2 决策**：不加 `child_event_ids` 双向链——前端从 `events` 列表按 parent_event_id 反向 O(1) 增量构建 `childIndex: Map<parentId, eventId[]>`，避免后端 schema 冗余。
3. **events.jsonl 作 regression fixture（O2）**：新增 `backend/app/llm/replay_client.py ReplayClient(LLMClient)` 从 golden_runs 读 events 重放；`pytest test_golden_runs.py` 用 ReplayClient 跑 extract → 与 commit 的 golden IR 深度比对；任何 IR 字段语义漂移立即被 CI 发现。CI golden-runs job 0 API key 依赖，<5s 跑完。

**已明确不做（v3.2 范围内 · 提案 P2 推迟）**：
- O6 对外可解释性 API：推迟到 Phase 2.6 完工后单独评估
- O8 SubcapabilityLab 升一等公民：Phase 1A 完工后再评估
- O9 VLM 成本/延迟仪表盘：数据已有（cost_tokens 字段），仪表盘 UI 推到 Phase 1B 后期
- O10 答辩演示动线：纯文档，无代码工作，Phase 全部完工前再写
- VisionEvent.child_event_ids 双向链字段：前端反向 O(1) 增量构建索引足够
- TapFlow 风格命令式 D3.js：技术栈第一性原理评估后改用 visx

**这一轮工作量**：
- 文档：1 新增 Phase 章节 + 4 处其他章节小改（阶段总览 / 依赖链 / 技术栈表 / VisionEvent IR / Phase 1A 设计约束 / Phase 1B 验证方式 / CI 脚本约定）
- 实际编码：Phase 2.6 大致 4-5 天（visx 学习 + 因果链 SVG 渲染 + ReplayClient + golden_runs CI + 跨视图联动）

---

### v3.1（2026-06-07）：核查修复 — 18 处硬错误 + 15 处优化 + D13 拓宽

v3 第二轮通读核查后修订。改动分三类：硬错误修复（破坏可执行性）、明确性优化（不影响执行但减少新工程师歧义）、架构层拔高（D13 扩边界）。

**架构层拔高**：
- **D13 拓宽 · "VLM 调用必发事件" → "所有 AI 决策必发事件"**：原 D13 仅约束 VLM 调用，v3.1 扩到所有 AI 决策（Text LLM 去重/分段/NL→Patch、ASR、VAD、Demucs、audio 判定都强制发 VisionEvent）。`VisionEvent.source` 枚举扩展为 `{vlm, cv, asr, audio, text_llm, system}`。这把"VLM 透明工作台"升级为"AI 整体决策工作台"，覆盖项目所有 AI 黑盒环节。

**硬错误修复（H1-H18）**：

1. **H1 events 持久化路径错误** → 改方案 B：events 按资源 kind 分支，`samples/{sid}/extracted/events_{task_id}.jsonl` / `projects/{pid}/pipeline/events_{task_id}.jsonl`；`event_bus.resolve_events_path()` 工具函数路由；同资源多次任务用 task_id 后缀区分；删资源时事件级联清理。
2. **H2 stage 命名三套不兼容** → 新增"VLM 调用协议·stage 命名规范"小节，集中表格列出所有合法 stage 取值（`0.5.mock` / `1A.*` / `1B.*` / `2.*` / `2.5.*` / `3.step{NN}.{kind}` / `4.*` / `5.aigc.*`）；Phase 7 narrative stage 归到 `3.step06.reorder.*` 不用 `7.*`；CI 加 `scripts/check_stage_naming.py` grep 校验。
3. **H3 SSE 重连缺服务端 id 字段约定** → VLM 调用协议章节加"SSE 服务端约定"小节，明确每条 event 必须三行格式 `id: {event_id}\nevent: vision\ndata: {json}\n\n`；浏览器原生 EventSource 自动用 Last-Event-ID header 续推；服务端按 from_event_id 调 replay。
4. **H4 Phase 1B 子能力依赖图缺失** → 在 `extract/pipeline.py` 描述里加完整依赖 DAG（normalize→scenes→frame_sampler→{captions→captions_anim, stickers, zoom_direction→zoom_curve, transitions, masks, color_lut} + audio 独立支线）；明确 asyncio.gather 同层并发 + 上层 await 依赖。
5. **H5 `/api/lab/run-subcap/{name}` 端点缺后端** → Phase 1A 加 `backend/app/api/lab.py`：3 个端点（subcaps 列表 / run-subcap / baselines）；项目结构图补 `api/lab.py`。
6. **H6 Phase 5 引用过时"阶段 1"** → 改为 "阶段 1B"。
7. **H7 Phase 4/5 之间缺分隔符** → 补 `---`。
8. **H8 data/system/models 残留 `paddleocr/`** → 删除（v3 OCR 已退场）。
9. **H9 config.py 没同步加 v3 env** → Phase 0.5 后端改动追加"扩展 config.py Settings"加 `model_provider` / `anthropic_api_key` / `enable_dev_mock` / `dual_check_stages` 四字段。
10. **H10 异步任务进度上报段过时** → 改为 SSE 主路径，事件类型 `progress`/`vision`/`stage`；tasks 表加 `resource_kind` / `resource_id` / `events_jsonl_path` / `last_event_sequence` 四列。
11. **H11 错误处理段残留 OCR** → "OCR 无字幕识别 fallback" 改为 "VLM 字幕识别失败 fallback"。
12. **H12 术语表 Tier B / D2/D3 描述过时** → Tier B 改为"标题条 + 音效预设注入"；D2-core / D2-extended / D3 三层定义按 v3 Phase 拆分。
13. **H13 术语表缺 v3 核心术语** → 加 VisionEvent / IRTarget / AI 透明工作台 / 0-999 归一化坐标系 / placeholder 三件套 / stage 前缀 / SubcapabilityLab 共 7 条。
14. **H14 总体数据流图缺工作台** → 重画数据流图，明示 VisionEvent stream → event_bus → SSE → 工作台三栏 + 事件回放页。
15. **H15 项目结构图大幅过时** → 补 15+ 个 v3 新模块：后端 `event_bus.py` / `tasks_store.py` 扩展 / `ir/vision_event.py` / `api/{events,replay,dev_workbench,lab}.py` / `extract/{frame_sampler,captions_anim,transitions,masks,color}.py` / `llm/prompts/scenarios/`；前端 `pages/{Workbench,SubcapabilityLab}.tsx` / `components/workbench/*` / `state/workbench.ts` / `styles/tokens.css` / `tailwind.config.ts`；data 加 `luts/` `sfx_pool/` `frames/` `events_{tid}.jsonl` `golden_runs/`。
16. **H16 D 约定排序乱** → D11 → D12 → D13 数字顺序复原。
17. **H17 环境变量列表没列 v3 新 env** → 补 MODEL_PROVIDER / ANTHROPIC_API_KEY / ENABLE_DEV_MOCK / DUAL_CHECK_STAGES / BACKEND_URL。
18. **H18 Phase 4 待讨论自相矛盾** → 删除"标题条 placeholder 是否需要"（描述里已明示必有），保留音效 ducking 待讨论项。

**明确性优化（S1-S15）**：

1. **S1 VisionEvent.sequence 并发分配** → event_bus 内部 `dict[task_id, AtomicCounter]`，publish 原子分配，同 task_id 全局递增；跨 task 不可比较。
2. **S2 event_bus 单进程约束** → "工作台事件流"章节加"水平扩展约束"小节，明确 MVP 单实例 OK，多 worker 需 Redis pub/sub 替换，demo 不阻塞。
3. **S3 chat_vision_dual 启用规则** → 默认关闭；通过 `.env DUAL_CHECK_STAGES="..."` 列出需双模的具体 stage；命中即并发双调，结构化字段一致才写 IR，否则 `confidence_warning=True`。
4. **S4 tasks 表 schema 缺事件字段** → 已与 H10 合并修订（4 列）。
5. **S5 Workbench IRPane 增量重建策略不清** → 明确用 `react-arborist` virtualized 树（避免长视频几千 segments 卡死）+ `immer + lodash.set` 增量写入。
6. **S6 Patch op `replay_vision_event` 语义错位** → 从 Patch 列表移除（UI 操作，不修 IR）；保留 `reject_vision_event`（清除该 event 写入并触发子步重跑，真实修 IR）；replay 改为 Workbench API（`POST /workbench/{task_id}/reject-event/{event_id}`）。
7. **S7 dev_workbench mock scenarios 路径** → 明确 `backend/app/llm/prompts/scenarios/{scenario}.json`；内置 3 个 scenario：captions_demo / stickers_demo / full_extract_demo，用户在动手前一次性补齐。
8. **S8 Phase 2.5 录屏 webm 浏览器兼容** → 明示 Chromium/Firefox 支持，Safari 不兼容时提示用户换浏览器，不做服务端转码。
9. **S9 Caption.tsx 双模式渲染** → 明确 `renderMode: "template_preview" | "project_output"` props 区分；模板预览用 `placeholder_text[0]`，应用产物用 `Caption.text`（来自用户素材 Unit.text）。
10. **S10 CaptionEvent vs CaptionStyle 命名澄清** → 加注释说明 CaptionEvent 是 extract 阶段中间产物（dataclass，不入 IR），CaptionStyle 是 IR 字段。
11. **S11 SubcapabilityLab dev 模式守卫** → 明确用 `import.meta.env.DEV` 守卫，生产 build 该路由 404 不挂载。
12. **S12 fixtures 路径不一致** → 统一开发期 `tests/fixtures/{sample_id}/source.mp4`（git tracked）+ 运行时通过 CLI ingest 到 `data/samples/{sid}/`；Phase 1A/1B/2 引用都用 `sample_id`。
13. **S13 sfx_index.json schema 缺规范** → Phase 4 加完整 JSON schema 示例 + category 初始集合（whoosh/ding/pop/typing/swoosh/impact/bell/transition_woosh）。
14. **S14 IRTarget.path 用 lodash 风格说明** → 明确不是 JSONPath，是 `lodash.set(state.ir, path, value)` 的点+方括号路径。
15. **S15 placeholder_text 改 list[str]** → CaptionStyle.placeholder_text 改为 `list[str]`，VLM 按推荐顺序给多种选择（"4-6 字 CTA 短语" + "立即抢购" + "促销+数字"），应用阶段 LLM 拿到整个列表作引导。

**这一轮工作量**：18 处硬错误 + 15 处优化 = 33 处修订，未引入任何新功能，全部是清理 + 明确化。架构层第一性原理拔高（O1-O10，含"工作台升级为甘特图视图"）拆出独立提案文档 `docs/proposals/001-ai-decision-workbench-v4.md`，等下一轮单独决策。

### v3（2026-06-07）：第一性原理重审 — VLM 主路径化 + AI 透明工作台 + 单点验证方法论

**设计背景**：v2.4 的架构以"成本可控的 hybrid CV+VLM"为出发点；v3 重新定义出发点为**「在 demo 阶段不计 API 成本、追求识别效果与可解释性最优」**。基于该立场，PLAN 在五条主轴上重审，所有"为成本而牺牲识别效果"的旧决策被允许重审，推翻 v2.4 的几条核心约定。

**重新出发的五条主轴**：
1. **VLM 升级为视觉理解主路径**。原 plan 第 112–117 行"为什么不 VLM 一把梭"的五条理由中，第 2 条"像素位置模糊"被推翻——参考 Open-AutoGLM 在生产中跑通的 0-999 归一化坐标系（`x = coord / 1000 * width`），通用 VLM 同样能给出 ±5–10% 精度的归一化 bbox，足以覆盖字幕/贴纸/标题条/几何蒙版的"识别 + 复用"需求。仅保留两条物理上限：①切点级时间精度（±0.04s）；②音频信号处理。
2. **OCR（字符识别）整体退场**。模板提取不需要原文，只需要"长什么样、怎么动"。CaptionStyle 新增 `placeholder_text` / `length_constraint` / `semantic_purpose` 三字段由 VLM 同步给出，作为应用阶段填字幕的视觉锚点。
3. **新增"AI 透明工作台"为第一产品页**。SSE 事件总线 + VisionEvent IR 把所有 VLM 决策实时推送到前端 `/workbench/{task_id}` 三栏页面（左：VLM 看到什么 / 中：怎么想的 / 右：决定了什么）。直接对应课题评分项 7（迁移过程可视化，10 分）+ 加分项"结构迁移可解释性"。
4. **Phase 1 拆 1A（单点验证）+ 1B（集成）**。每个识别能力（字幕样式/贴纸/缩放方向/转场/调色/蒙版/动画细节）独立 fixture + 指标基线 + 工作台事件流三件套；单点全过后才允许 1B 端到端集成。避免"大整合崩塌、找不到拖后腿的子能力"。
5. **Tier B 部分项目前置到 1A**。几何蒙版 / 调色语义 / 转场分类的 VLM 实现成本骤降，从 Phase 4 前置到 Phase 1A。Phase 4 显著瘦身，只剩标题条 + 音效预设注入。

**核心数据结构变更**：
1. 新增 `VisionEvent` + `IRTarget`：AI 工作台事件总线的核心 IR。`source ∈ {vlm, cv, asr, audio, system}`，含 `frame_url / bbox_norm / semantic_label / reasoning / confidence / ir_target / ir_value / cost_tokens` 等字段。生命周期 = 内存广播 + `projects/{id}/pipeline/events.jsonl` 持久化。**（v3.1 修订：source 已扩展为 6 个含 `text_llm`；持久化路径已改方案 B，详见 v3.1 改动总结 H1）**
2. `CaptionStyle` 加三字段：`placeholder_text` / `length_constraint` / `semantic_purpose`，由 VLM 在判断字幕样式时同步返回。
3. `StickerEvent` 加 `semantic_category` + `coord_system`。
4. `Patch` 加 4 个 op：`set_placeholder_text` / `set_length_constraint` / `set_semantic_purpose` / `reject_vision_event`；加 `triggered_by_event_id` 与 `source="workbench"` 字段追溯。（v3.1 修订：`replay_vision_event` 已从 Patch 移除，改为 Workbench API `POST /workbench/{task_id}/reject-event/{event_id}`——因为它本质是 UI 操作不修 IR，详见 v3.1 S6 修订）
5. 全局约定加 `D13 VLM 调用必发射 VisionEvent`（CI grep 强制校验）。**（v3.1 拓宽：D13 已从 VLM 调用扩到所有 AI 调用，详见 v3.1 改动总结"架构层拔高"）**
6. `D4` 保真度分层调整：D2-core（Phase 1B）+ D2-extended（1A 单点+1B 集成）+ D3（Phase 4 标题条/音效）。
7. `D11` 补充：placeholder_text 不属于"改写文本"，是 VLM 的语义占位描述。

**新增阶段与重大重写**：
1. **Phase 0.5 AI 工作台骨架**：SSE 端点 + VisionEvent IR + 前端三栏页面骨架 + mock 事件流验证机制。`llm.client.chat_vision()` 强制契约。
2. **Phase 1A 视觉理解能力单点验证**：每个识别子能力独立验证。配 SubcapabilityLab 前端单测页 + per-subcap 指标基线写入 `tests/baselines.json/subcap.<name>`。
3. **Phase 1B 模板提取集成 → KB**：串联 1A 各能力，extract 全程在工作台可见。OCR 删除，Tier B 部分前置项随 1B 一起入 KB。
4. **Phase 4 大幅瘦身**：蒙版 / 调色 / 转场全部前置到 1A 后，Phase 4 只剩标题条 + 音效预设注入。

**前后端架构补强**：
1. 后端加 `backend/app/event_bus.py`（asyncio 内存广播 + jsonl 持久化）、`backend/app/ir/vision_event.py`、`backend/app/api/events.py`（SSE）、`backend/app/api/replay.py`（Phase 2.5 回放）、`backend/app/api/dev_workbench.py`（mock 流）。
2. `LLMClient` 重构为 `OpenAICompatClient` + `AnthropicClient` 双协议适配器，按 `MODEL_PROVIDER` env 切换，关键决策可启用 `chat_vision_dual()` 双 provider cross-check。
3. 前端加 `frontend/src/pages/Workbench.tsx` + `frontend/src/pages/SubcapabilityLab.tsx` + 三栏组件 `WorkbenchVisionPane` / `WorkbenchEventStream` / `WorkbenchIRPane` + `BboxOverlay` SVG + `EventBadge`；`Visualize` 页升级为工作台事件回放器。
4. 前端 design tokens 章节落地 Anthropic 风格（米白底 + 暖橙强调 + 衬线/无衬线/mono 三体 + 细线条卡片 + 极少阴影）；Tailwind + Radix UI primitives + lucide-react，明确不引入 MUI / Ant / Chakra。

**Phase 2/2.5/3/5/7 的工作台对接修订**：
- Phase 2：模板推荐 + apply 全程发 VisionEvent；style.py 填字幕时利用 placeholder_text + length_constraint 引导 LLM。
- Phase 2.5：`Visualize` 页重写为工作台事件回放器（支持时间轴拖拽、变速回放、录屏导出）；NL 编辑生成的 patch 也发 VisionEvent（source="workbench"）。
- Phase 3：每个 step 自己的 stage 前缀（`3.step02` / `3.step03` / ...），工作台支持按 stage 过滤；rerun 时清除对应 stage 历史事件。
- Phase 5：AIGC 调用发 VisionEvent（生成请求 + 完成回执，含 prompt 摘要 + 缓存命中状态）。
- Phase 7：narrative score / dependency detection / reorder plan 各自发 VisionEvent；plan 的角色染色在工作台第三栏可视化。

**技术栈调整**：
- 删除：PaddleOCR（模板提取不需要文本字符识别）
- 新增：sse-starlette（SSE 端点）、Anthropic SDK（双协议适配器）、Tailwind CSS + Radix UI primitives + lucide-react（Anthropic 风格 UI 落地）
- 调整：Phase 4 SAM2 从主路径降级为仅复杂场景 fallback；调色 LUT 从"颜色直方图匹配"主升级为"VLM 语义 + 直方图微调"

**已砍项（v3 进一步细化）**：
- 同次调用结果可变性问题（原 v2.4 第 115 行第 3 条）：通过 temperature=0 + seed + 双 provider cross-check 解决
- 失败定位困难（原第 117 行第 5 条）：通过 VisionEvent 的 reasoning + IRTarget 完全白盒化解决
- OCR 字符识别：模板提取不需要原文
- 字幕动画的逐帧位移启发式：升级为 VLM 语义判 + CV 5fps 帧差/光流验证细节

**对应课题评分加成**：
- 评分项 7（迁移过程可视化 10 分）：AI 透明工作台 + 事件回放器 = 直接拿满
- 评分项 6（迁移过程可视化展示 10 分）：每个 VLM 决策有 reasoning + bbox 高亮 + IR 填充动画
- 加分项"对'结构迁移'有较强的可解释性展示"：工作台是该项的最强证据
- 加分项"有较好的工程质量、交互细节或视觉完成度"：Anthropic 风格 design tokens 落地
- 加分项"支持自然语言改片"：v2.4 已有，v3 让 NL 解析过程也可见

**v3 已知代价 / 待讨论**：
- 单样例 extract 端到端从 ≤ 30s 涨到 ≤ 5 分钟（VLM 调用从 ≤8 次到 15–30 次）。代价已知并接受，因为工作台让用户全程不焦虑。
- VLM 模型选型需实测：Qwen-VL-Max / Claude Sonnet 4.6 / GPT-4o 三者在 0-999 坐标系上的实际精度需要在 1A 启动前用 sample_basic_15s 跑一遍 prereq 测试。
- Phase 0.5 工作台骨架的 fake event scenarios（`scenarios/captions_demo.json` 等）需要在动手实现前用户先帮忙编几个典型样本（一次性工作）。
- 标题条文字是否需要 VLM 给 placeholder（倾向需要，待 Phase 4 启动前确认）。
- AI 工作台录屏导出格式（webm vs gif）的浏览器兼容性。

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
- **时间轴拖拽编辑器**：移出主路线 → `docs/future-plans/001-timeline-editor.md`，触发条件见该文档。
- **向量检索（FAISS/embedding）**：≤50 模板用标签匹配 + LLM 重排足够；上百模板后再引入。
- **Tier C 特效**（任意特效 1:1 还原）：研究级，只做白名单近似。
- **精确 BGM 曲目识别**：Demucs 特征 + 情绪标签够用；曲目指纹识别 = Future。
- **多样例融合建模**：MVP 单样例学习；多样例聚类 / 风格 averaging = Future。
- **VLM 一把梭视频理解**：视觉理解 VLM 主路径化，时间精度（切点 / WhisperX）+ 音频信号处理（Demucs / librosa）+ 动画微观位移（CV 5fps 帧差光流）仍由专用工具把守。详见"视频理解技术选型"章节。
- **样例端音效/高潮/变速/缩放出框识别**：详见 Phase 4 已砍项。
- **句级任意重排**：Phase 7 重排粒度恒为主题段级，不做句级（拼贴感、逻辑断裂）。
- **模板端 OCR 字符识别**：不识别字幕的具体文本，只识别"字幕长什么样、动效是什么"。用户素材的字幕文本来自用户自己的录音，模板复用的是样式而非文字。
- **AI 静默调用**：所有 AI 客户端方法（`chat_vision` / `chat_text` / ASR / Demucs 等）必发射 VisionEvent；不发事件的调用视为 bug，CI `scripts/check_event_emission.py` 强制扫源码。`silent=True` 模式仅用于背景 sanity check 等明确不需要在工作台展示的辅助调用（详见"AI 调用协议·silent 模式"小节）。

### 关键设计决策（后人重新提出方向时先查 docs/decisions/）

- **D1 输入 MP4 而非工程文件** —— 与实际使用场景吻合，无需逆向解析。
- **D7 渲染走 Remotion + FFmpeg** —— 见 v2 重构，剪映退场原因详见 `docs/decisions/001-jianying-out.md`（待写）。
- **D8 模板为可伸缩规则集** —— 样例 5–20s、产出 10s–3min，定长无法自适应。
- **D11 LLM 决策 ≠ 文本改写** —— 保证时间戳不丢、字幕同步精确、NL 编辑精确定位。
- **Python + Node 双服务** —— Python 占 ML 生态优势，Node 占 Remotion 生态唯一性，混合最务实。
- **D10 AIGC 用户主动触发** —— 避免"AI 决定一切"导致的版权/可控性问题。
- **VLM 主路径 + CV 守底** —— 视觉理解 VLM 主、CV 守时间/音频/动画微观精度。详见"视频理解技术选型"章节。
- **D13 所有 AI 调用必发射 VisionEvent** —— 不只 VLM，含 Text LLM / ASR / audio / CV 所有 AI 决策。AI 透明工作台的可观测性底座，CI 强制约束。
- **0-999 归一化坐标系** —— VLM 输出坐标统一用 0-999 系统（参考 Open-AutoGLM 在生产中跑通的方案），客户端层映射到 0-1 写入 IR。
- **BGM 双策略** —— 满足"个人 demo"vs"公开发布"两种使用场景。
