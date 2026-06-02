# SceneEcho — 口播视频「结构 + 风格」迁移引擎 · 分阶段实施计划

## Context

SceneEcho 解决一个真实痛点：口播创作者能感觉到"哪些视频的剪辑结构更出效果"，却很难把这种**剪辑方法 / 风格**抽象、复用到自己的素材上——手动一比一模仿样例的字幕动画、缩放、卡点、BGM、转场成本极高。本项目给一段 5–20s 优质口播样例，自动学出它的「**结构骨架 + 视听风格**」模板；再给用户自己录的 ~3min 口播长素材，自动 **去冗余 → 按结构套模板 → 补全画面缺口**，产出一个**可在剪映里继续编辑**的工程草稿（draft）。**硬约束**：输入是导出后的 **MP4 成片**（非剪映工程文件），"学模板"只能靠 CV / ASR / 多模态**推断**。定位：真实需求驱动，课题（见 `docs/赛题.md`）仅作参照、不复述。

> **宏观流程（对应导师建议四步）**：样例理解 → 结构抽取（`extract`）→ 素材适配（`understand`+`apply`）→ 结果生成（`render`）。
> **阅读约定**：「架构设计」是全局共享设计；每个 `## 阶段` 都自带「设计约束 + 涉及数据结构」，即使单独抽出某阶段交给无上下文的执行者，也不会丢掉保序、账本、骨架发现等前提。

---

## 阶段总览

| 阶段 | 名称 | 状态 | 一句话说明 |
|------|------|------|-----------|
| 阶段 0 | 地基与最小闭环骨架 | 📋 待开始 | 跑通 `mp4 → 剪映能打开的最简 draft` + 前后端脚手架 |
| 阶段 1 | 模板提取（骨架 + Tier A 风格） | 📋 待开始 | 样例 → 结构骨架 + 字幕/缩放/切点/BGM 风格 → 入库 |
| **阶段 2** | **应用主闭环** | 📋 待开始 | **★MVP**：3min 粗剪保序 + 套模板 + 缺口补全 → 可编辑 draft |
| 阶段 2.5 | 自然语言编辑 + 迁移可视化 | 📋 待开始 | 一句话改 IR 重渲染 + 「抽取/映射/缺口/补全」可视化 |
| 阶段 3 | 保真升级 Tier B + 画面识别 | 📝 部分 Future | 几何蒙版/字幕精化/转场/贴纸/音效 + 镜别·高光·废镜筛选 |
| 阶段 4 | 多版本 + 卡点 + 前端完善 | 📝 Future | IR 变体多版本 + librosa 卡点 + FFmpeg 后台批量渲染 |
| 阶段 5 | 内容优化层 | 📝 Future | 结构重排 + AIGC 补 B-roll + 精确 BGM 曲目识别 |

> **依赖链路**：阶段 0（地基/渲染命脉）→ 阶段 1（提取入库）→ 阶段 2（应用闭环 ★MVP）→ 阶段 2.5（NL 编辑/可视化）→ 阶段 3（保真增量）→ 阶段 4 / 5（Future 增强）。阶段 2.5 可与阶段 3 并行。
> **唯一明确不采用**：Remotion —— 产物是 flat MP4、无法回剪映、非 GUI 编辑器；除非未来能直出剪映，否则不纳入。
> **其他待排期 Future**：封面生成、多样例融合、向量检索选模板（见 D6）。

---

## 架构设计

### 核心原则
- **真实需求驱动 > 迎合评分**：难的 / 前期非必要的一律标 `[Future]`，不一次性堆完。
- **IR 是地基**：模板与剪辑决策都落在结构化中间表示（IR）上——IR 是"人(自然语言) / AI(LLM) / 渲染器(剪映)"的**共同语言**，可解释、可调整、可对话式编辑。NL 编辑、多版本、AIGC 补全、迁移可视化都是在这同一份 IR 上做读写。
- **保序优先**：MVP **不重排**用户片段顺序；内容理解只服务于"去重 / 选模板 / 补缺口"。重排是 Future（阶段 5），届时需用户显式确认。
- **闭环优先**：先打通 `学样例 → 套长素材 → 出可编辑 draft`，再加增强能力。

### 关键决策固化（全局约束，各阶段回引）
- **D1 输入是 MP4 ⇒ 提取靠推断**：成片是像素、无剪辑元数据；逆向剪映 draft 格式只用于**输出**，`pyJianYingDraft` 只出现在渲染侧。
- **D2 模板 ≠ 产物**：模板是 KB 里的可复用配方；产物 = 模板 + 用户素材实例化后的 draft。
- **D3 "不考虑内容" = 保序**：提取侧只提"怎么剪"、不深挖样例语义；应用侧内容感知（ASR/去重/分段/画面识别）但**不改时间线顺序**。
- **D4 保真度分层**：Tier A（MVP：切点/缩放/逐字字幕/静音/BGM 有无）→ Tier B（阶段 3：几何蒙版/字幕精化/转场/贴纸/音效）→ Tier C（Future：特效白名单 + 分类器，集合内 1:1、集合外不支持）。
- **D5 骨架"发现"非"预设"**：基础三段（开头 / 主体 / 结尾）几乎所有口播都有；其余角色按样例实际出现、**开放可扩展**；不预设固定清单、不假设是某类视频。
- **D6 选模板用标签、不用向量**：≤50 模板用标签足够、可解释；FAISS = Future。
- **D7 渲染锁剪映 draft**：用户工作流在剪映、产物可二次编辑；演示片用剪映手动导出 hero case。
- **D8 模板是「可伸缩风格规则集」，不是定长时间线**：样例只有 5–20s、产出却 ~3min，所以模板编码的是**风格 + 节奏规则**（字幕怎么弹、按停顿怎么切、何时推镜/缩放、蒙版/BGM 在什么语境用），套用时按用户素材实际长度**自适应铺开**，而非把素材塞进固定槽位。
- **D9 长视频 = 多主题段 × 模板**：长素材先按主题分段（保序），**每个主题段各选一个模板**，多段套完按原序**拼接**成片；"几个模板的一次或多次组合"即可剪好整条长视频。

### 技术栈
| 组件 | 选型 | 引入阶段 |
|------|------|----------|
| 后端框架 | FastAPI（异步，长任务先 BackgroundTasks） | 阶段 0 |
| 前端 | React + TypeScript + Vite | 阶段 0 |
| draft 生成 | pyJianYingDraft | 阶段 0 |
| 媒体处理 | FFmpeg / OpenCV | 阶段 0 / 1 |
| 分镜切点 | PySceneDetect | 阶段 1 |
| 字幕识别 | PaddleOCR | 阶段 1 |
| BGM 提取 | 人声/伴奏分离（如 Demucs） | 阶段 1 |
| 语音转写 | WhisperX（词级时间戳）+ silero-VAD | 阶段 2 |
| LLM 编排 | 去重 / 分段 / 选标签 / NL 编辑 | 阶段 1 / 2 |
| 存储 | SQLite + 本地文件（FAISS = Future） | 阶段 1 |
| 画面识别 | CLIP / VLM | 阶段 3 |
| 卡点 | librosa | 阶段 4 |

### 运行环境要求
- **Python**：后端建议统一锁 **3.11 / 3.12**（WhisperX / PaddleOCR / torch 对 3.13 适配常滞后）。当前机器为 **3.13**——阶段 0 仅用 pyJianYingDraft 可暂用，**进阶段 1 前应新建 3.11/3.12 的 venv**，避免 ML 依赖装不上而返工。
- **系统依赖**：需安装 **ffmpeg + ffprobe** 并加入 PATH（抽帧 / 切片 / WhisperX 解码依赖；**当前未安装**，阶段 1 前装好）。
- **虚拟环境**：`backend/.venv`（Python）；前端 Node ≥ 18 + npm。
- **剪映**：锁定**国内剪映**某版本（**非国际版 CapCut**），版本号 + draft 工程根目录写入 `config.py`（Windows 默认 `…/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft`）。pyJianYingDraft 草稿生成支持**剪映 5+**，不使用模板模式/批量导出，故不受剪映 6+ 的 `draft_content.json` 加密影响；真实 API 命名**以安装后实测为准**。
- **LLM**：配置 provider + API key（`.env` 管理）。

### 项目结构
```
SceneEcho/
  docs/{PLAN.md, 赛题.md, architecture.md}
  backend/
    pyproject.toml
    .venv/                         # 本地虚拟环境（gitignore）
    app/
      main.py                      # FastAPI 入口
      config.py                    # 剪映版本/draft 目录/模型/LLM key
      api/{samples,templates,projects,edit}.py
      ir/{template,project,ledger}.py         # pydantic 模型
      extract/{scenes,motion,captions,audio,skeleton,pipeline}.py   # 样例 → TemplateIR
      understand/{asr,vad,dedup,segment,vision}.py                  # 用户素材理解
      apply/{mapping,gaps,fill,style,pipeline}.py                   # → ProjectIR
      render/{jianying,ffmpeg,resources}.py                         # IR → 剪映 draft
      kb/{store,tagging,select}.py            # 知识库 + 标签
      agent/{tools,orchestrator,nl_edit}.py   # 工具协议 + LLM 编排 + NL→patch
      llm/{client, prompts/}
    tests/{fixtures/, test_*.py}
    data/                          # uploads/ drafts/ kb.sqlite（gitignore）
  frontend/
    package.json, vite.config.ts
    src/{api/, types/ir.ts, pages/{SampleExtract,TemplateLibrary,Editor,Visualize}.tsx, components/}
  .gitignore                       # 需补 node_modules/ dist/ backend/.venv/ data/
  README.md
```

### 总体数据流
```
[样例 mp4] ──extract(画面+字幕+音频/BGM)──▶ TemplateIR ──▶ 知识库(KB, 带标签)
                                                          │ select(按主题段·标签匹配)
[用户 ~3min mp4] ──understand──▶ 账本 + 主题段 ──┐          │
                                              ▼          ▼
            apply(逐主题段): 片段→槽位(保序·时长自适应) + 缺口识别 + 缺口补全 + 套风格
                                              ▼
                              ProjectIR (多主题段 × 模板，按原序拼接的 EDL)
                                              │ render
                                              ▼
                                       剪映 draft（可编辑）
       [自然语言指令] ──agent──▶ 对 ProjectIR/TemplateIR 的结构化 patch ──▶ 重渲染
```

### 关键机制
- **时间戳账本**：WhisperX 词级强制对齐 → 每个 Unit 带精确 `start/end`；账本不可变；去重 / 分段 / NL 编辑时**给 LLM 带 id 的列表、只让它返回对 id 的决策**（例：`{"keep":[3,4,7],"drop":[{"id":5,"dup_of":3}],"topics":[{"name":"A","units":[1,2,3,4]}]}`），**绝不改写文本**；再用 id 映回精确时间 ⇒ 时间戳不丢（同时解决字幕帧级同步、切点落词/句边界、NL 编辑精确定位）。
- **提取流水线**：切点+节奏(PySceneDetect) → 缩放(OpenCV 尺度变化估计) → 字幕样式/时机/动画(PaddleOCR + 跨帧追踪) → **BGM 提取**(人声/伴奏分离 → BGM 片段 + tempo/情绪特征；精确曲目识别 = Future) → 骨架发现(按位置定基础三段 + 按出现标可选角色) → LLM 建议标签 → 入库。
- **应用流水线**：WhisperX→账本 → VAD 去静音 → LLM 按 id 去重(同句多遍取最佳) → **LLM 主题分段(保序，得到 N 个主题段)** → **逐主题段**：select 选模板(标签匹配) → 片段→槽位映射(保序) → 缺口识别 → 缺口补全 → 套风格 → 拼接 N 段(保序) → ProjectIR。
- **时长自适应（D8 的落地）**：模板槽位时长是 `{min, nominal, max}` 区间。用户某段比槽位 **长** → 裁切 / 轻微变速 / 拆成多片填多个槽位；比槽位 **短** → 在 `min~max` 内拉伸，或素材复用(局部放大/重复)兜底；整段主题缺槽位所需素材 → 走缺口补全。
- **缺口识别与补全**：槽位 `material_req` 无用户片段满足 = 缺口。**MVP 三法（均不改顺序）**：① 文案/字幕补全 ② 包装补全(标题条/卖点卡片) ③ 素材复用(裁切/局部放大/重复)。`[Future]`：AIGC 补 B-roll、结构重排。
- **自然语言编辑（NL→IR patch）**：LLM 把指令翻成对 IR 的**结构化 patch**（例：`{"op":"delete_segment","section":0,"index":1}`、`{"op":"set_caption_style","color":"#FFD400","stroke":"black"}`、`{"op":"swap_template","section":2,"template_id":"B"}`）→ 应用 → 重渲染；改结构不改像素，可回滚、可解释。
- **Agent 编排 + 工具协议**：每个能力注册为 tool，其基于 IR 的 IO schema 即**工具协议**（写进交付文档）。示例：`transcribe(media)->Ledger`、`dedup(Ledger)->kept_ids`、`segment_topics(Ledger)->Sections`、`select_template(Section, KB)->template_id`、`detect_gaps(Section, Template)->[Gap]`、`fill_gap(Gap, strategy)->result`、`render_draft(ProjectIR)->path`、`nl_edit(ProjectIR, 指令)->patch`。NL 编辑 = agent 把人话翻成对这些 tool 的调用。
- **边界与鲁棒性**：① 无标签匹配的模板 → fallback 到最通用模板或标记需人工选；② ASR 低置信/失败 → 标记该段、提供人工校正入口；③ 用户素材几乎全是废片/无有效片段 → 明确提示而非硬生成；④ 渲染所需剪映资源(动画/蒙版 ID) 不在白名单 → 降级为最接近的内置项并记录。

### 后端 API（草案）
`POST /samples` · `POST /samples/{id}/extract` · `GET /templates[/{id}]` · `PATCH /templates/{id}/tags` · `POST /projects` · `POST /projects/{id}/apply` · `GET /projects/{id}`（含可视化数据）· `POST /projects/{id}/edit` · `POST /projects/{id}/export` · `GET /tasks/{id}`

---

## 核心数据结构：IR（按阶段递增构建）

> 阶段 0 建 `ProjectIR` 最小版（1 视频 + 1 caption）；阶段 1 建 `TemplateIR`；阶段 2 建 `TranscriptLedger` + 完整 `ProjectIR`（多主题段）。风格规则按 **字幕 / 画面 / 音频 / 贴纸 / 节奏** 五维组织。

### TranscriptLedger（转写账本——时间戳的唯一真相源）
```python
class Unit(BaseModel):
    id: int            # 稳定不变
    text: str
    start: float; end: float       # 秒（WhisperX 词/句级）

class TranscriptLedger(BaseModel):
    units: list[Unit]  # 不可变；所有 LLM 操作只引用 id，绝不改写 text
```

### TemplateIR（模板 = 结构骨架 + 风格规则 + 标签）
```python
SlotRole = str   # 开放枚举，从样例发现；基础三段: 开头|主体|结尾，其余按需扩展

class CaptionStyle(BaseModel):            # 字幕
    font: str; size: int; color: str; stroke: str | None
    position: tuple[float, float]; layout: str
    anim_in: str; anim_emphasis: str | None     # 动画；触发时机由账本时间戳驱动

class VisualStyle(BaseModel):             # 画面
    scale: list[tuple[float, float]] | None     # 镜头：变大/变小关键帧 (相对时间, scale)
    mask: str | None = None                     # 蒙版（圆/线性/矩形…，阶段3）
    effects: list[str] = []                     # 特效白名单（阶段4 / Tier C）
    title_bar: bool = False; sale_card: bool = False   # 通用包装元素

class AudioStyle(BaseModel):              # 音频
    has_bgm: bool = False
    bgm_clip: str | None = None                 # 提取出的 BGM 片段引用
    bgm_mood: str | None = None                 # 情绪/风格标签（tempo/energy）；精确曲目识别 = Future
    sfx: list[dict] = []                        # 音效（转场/强调音效，时机）；从成片识别较难 = Tier B/Future

class StickerStyle(BaseModel):            # 贴纸
    items: list[dict] = []                      # 类型/位置/时机（阶段3）

class StyleRule(BaseModel):
    caption: CaptionStyle | None
    visual: VisualStyle
    audio: AudioStyle
    stickers: StickerStyle | None
    rhythm: dict                                # 切点节奏 / 卡点规则
    transition_in: str | None; transition_out: str | None

class Slot(BaseModel):
    role: SlotRole
    duration: dict                              # {min, nominal, max} 可伸缩（D8）
    material_req: str                           # 人物口播 / B-roll / 文字卡
    style: StyleRule

class Tags(BaseModel):                    # 选模板用；示例取值见注释
    position: str    # 开头 | 中间 | 结尾
    function: str    # 开头引入 | 逻辑讲述 | 关键词强调 | 转折 | 结尾收束 …（开放）
    scene: str       # 纯口播 | 讲解 | …（开放）
    notes: str       # 一句人话："什么情况下用"

class TemplateIR(BaseModel):
    id: str; name: str; source_sample: str
    skeleton: list[Slot]
    global_style: dict                          # 画幅 / 调色 / 全局 BGM
    tags: Tags
```

### ProjectIR / EDL（实例化时间线，多主题段 × 模板）
```python
class PlacedSegment(BaseModel):
    slot_role: SlotRole
    source_unit_ids: list[int]            # 引用账本（保序的依据）
    src_timerange: tuple[float, float]
    timeline_start: float
    applied_style: StyleRule
    is_fill: bool = False

class Caption(BaseModel):
    text: str; start: float; end: float; style: CaptionStyle   # 来自账本

class Gap(BaseModel):
    slot_role: SlotRole; reason: str
    fill_strategy: str                    # 文案|包装|素材复用|（AIGC/重排=Future）
    fill_result: str

class Section(BaseModel):                 # 一个主题段 → 套一个模板（D9）
    topic: str
    template_id: str
    segments: list[PlacedSegment]         # 段内保序
    gaps: list[Gap]

class ProjectIR(BaseModel):
    sections: list[Section]               # 多主题段，按原时间线顺序拼接（保序）
    captions: list[Caption]
    canvas: dict
    # 注：单模板场景 = sections 长度为 1，结构向后兼容
```

---

## 阶段 0: 地基与最小闭环骨架 📋

### 目标
一段 mp4 → 一个剪映能打开的最简 draft；立起前后端脚手架。先证明命脉——**能生成剪映可解析的 draft**。

### 设计约束（本阶段必守）
- **IR 是地基**（核心原则）：先定 IR v0、渲染只认 IR，不在剪映原始 JSON 上写业务。
- **渲染锁剪映 draft、不用 Remotion**（D7）。
- **draft-writer 隔离在 IR→draft 转换器之后**：剪映版本漂移只改 `render/jianying.py` 一处。

### 涉及数据结构
`ProjectIR` v0（最小：1 个 Section、1 视频段 + 1 caption + canvas）、`config`（剪映版本 / draft 目录）。账本、模板本阶段留空壳。

### 关键实现
- **新增** `backend/app/render/jianying.py`：安装后**实测 pyJianYingDraft 真实 API**（文档示例如下，命名 CamelCase/snake_case 历版有别，以实测为准）→ `build_draft(project_ir, draft_root)` 生成 1 视频 + 1 静态字幕。
  ```python
  import pyJianYingDraft as draft
  from pyJianYingDraft import trange
  script = draft.DraftFolder(draft_root).create_draft("demo", 1080, 1920)
  script.add_track(draft.TrackType.video)
  script.add_segment(draft.VideoSegment("video.mp4", trange("0s", "5s")))
  script.add_segment(draft.TextSegment("字幕", trange("0s", "5s")))
  script.save()
  ```
- **新增** `backend/app/render/ffmpeg.py`：读时长 / 分辨率（无系统 ffmpeg 时借 pyJianYingDraft 自带 imageio-ffmpeg）。
- **新增** `backend/app/ir/{project,ledger,template}.py`：IR v0 pydantic 模型。
- **新增** `backend/app/{main,config}.py` + `api/samples.py`：FastAPI 入口 + 上传/导出链路。
- **新增** `frontend/`：React/Vite 脚手架，上传 → 下载 draft。

### 验证方式
1. 准备 `tests/fixtures/sample_10s.mp4`。
2. `pytest test_min_draft`：解析生成的 `draft_content.json`，断言 tracks 恰好 1 视频段 + 1 文本段；视频段 `duration ≈ 源时长`（±100ms）；material 引用完整。
3. 手动在**锁定版本剪映**打开草稿 → 看到视频 + 字幕、**无"媒体丢失/缺资源"弹窗**（截图存档）。
4. 前端：上传 mp4 → 下载到 draft.zip。

---

## 阶段 1: 模板提取（结构骨架 + Tier A 风格） 📋

### 目标
5–20s 样例 →「骨架 + 风格(字幕/画面/音频/贴纸/节奏) + 标签」→ 入库。这是"模板学习"的核心，是该砸资源做扎实的地方。

### 设计约束（本阶段必守）
- 提取侧**只提怎么剪、不深挖样例语义**（D3）。
- 骨架**发现非预设**、基础三段必有、角色开放（D5）；模板编码为**可伸缩规则集**（D8）。
- 保真度只做 **Tier A**（D4）；选模板用**标签**、不用向量（D6）。

### 涉及数据结构
`TemplateIR`（`skeleton: list[Slot]`，slot 时长为 `{min,nominal,max}` 区间；`StyleRule{caption, visual(缩放/蒙版/包装), audio(BGM), stickers, rhythm}`；`Tags{position,function,scene,notes}`）。

### 关键实现
- **新增** `backend/app/extract/scenes.py`：PySceneDetect 切点 + 镜头时长序列（节奏）。
- **新增** `backend/app/extract/motion.py`：OpenCV 尺度变化估计 → 缩放（变大变小）关键帧规则。
- **新增** `backend/app/extract/captions.py`：PaddleOCR 字幕区域 → 样式 + 出现/消失时机 + 动画类型（跨帧追踪文字位移推断弹入方式）。
- **新增** `backend/app/extract/audio.py`：人声/伴奏分离 → BGM 有无 + 片段 + tempo/情绪特征。
- **新增** `backend/app/extract/skeleton.py`：按位置定基础三段 + 按出现标可选角色；slot 时长输出为可伸缩区间。
- **新增** `backend/app/kb/{store.py(SQLite), tagging.py(LLM 建议标签)}`。

### 验证方式
1. 测试集：3 个已知风格样例，人工标注（切点数、缩放时间点、字幕首现时间/位置/颜色、骨架分段、BGM 有无）。
2. 指标：切点 F1 ≥ 0.8（±0.2s 容差）；字幕出现时机误差中位 < 0.3s；字幕位置误差 < 5%（归一化）；基础三段划分 3/3 与人工一致；BGM 有/无判断正确。
3. IR round-trip：存 KB 再读回字段无损（pytest）。
4. 端到端：样例 → IR → 给占位素材出 draft，剪映里字幕样式/缩放与样例**肉眼接近**（截图对照）。

---

## 阶段 2: 应用主闭环（智能粗剪保序 + 套模板 + 缺口补全） ★MVP 📋

### 目标
3min 口播 → 去重保序分段 → **逐主题段套模板** → 识别并补全缺口 → 拼接 → 可编辑 draft。**MVP 闭环在此完成。**

### 设计约束（本阶段必守，核心）
- 应用侧**内容感知但严格保序**（D3）——**不重排片段顺序**。
- **账本机制**（关键机制）——LLM 只引用 id 决策、**绝不改写文本**。
- **长视频 = 多主题段 × 模板**（D9）+ **时长自适应**（D8）；缺口补全**只用 MVP 三法且不改顺序**；AIGC / 重排是 Future。

### 涉及数据结构
`TranscriptLedger`（不可变）、`ProjectIR/EDL`（`sections: list[Section]`，每 Section 一个 `template_id` + 保序 `segments` + `gaps`）。

### 关键实现
- **新增** `backend/app/understand/asr.py`：WhisperX 逐字转写 → 账本。
- **新增** `backend/app/understand/{vad.py(去静音), dedup.py(LLM 按 id 去重), segment.py(LLM 主题分段，保序，输出 N 段)}`。
- **新增** `backend/app/kb/select.py`：逐主题段按标签匹配选模板（MVP 可单模板兜底）。
- **新增** `backend/app/apply/{mapping.py(片段→槽位，保序+时长自适应), gaps.py, fill.py(三法), style.py(套风格→生成 caption/缩放), pipeline.py(逐段处理后拼接)}`。
- **修改** `backend/app/render/jianying.py`：从最简 draft 扩展为写完整多 Section 的 ProjectIR。

### 验证方式
1. 测试数据：构造 1 条 3min 口播 mp4（含 3 处重录同一句、5 处 >1s 静音、2 个主题段）。
2. 去重：召回 ≥ 0.8、精确 ≥ 0.9（误删代价高）——人工标注重复单元 vs 系统删除。
3. 字幕同步：抽 20 条，median `|caption.start − 语音 start|` < 0.15s。
4. **保序**：把所有 Section 的 `segments` 展平，断言 `source_unit_ids` 首元素全局严格递增。
5. 主题分段：与人工 2 主题边界一致（±1 句）；2 段分别选到模板。
6. 时长自适应：用户段比槽位长/短时，输出时长落在 slot `{min,max}` 内或走裁切/复用，无越界。
7. 缺口：人工标注缺口槽位 vs 系统识别，逐项核对；每个缺口都有合法 `fill_result`。
8. 手动验收：剪映打开可编辑、字幕跟得上语音、无缺资源、整体能看。

---

## 阶段 2.5: 自然语言编辑 + 迁移可视化 📋

### 目标
一句话改结果；评审 / 用户能看懂迁移全过程。

### 设计约束（本阶段必守）
NL 编辑 = **改 IR 结构不改像素、可回滚、可解释**（关键机制 / 核心原则）。

### 涉及数据结构
对 `ProjectIR` / `TemplateIR` 的 patch（结构化操作列表，见关键机制中的 patch 示例）。

### 关键实现
- **新增** `backend/app/agent/nl_edit.py`：NL 指令 → IR patch → 应用 → 重渲染；维护 patch 历史以支持回滚。
- **新增** `frontend/src/pages/{Visualize,Editor}.tsx`：迁移过程可视化（抽取的骨架/风格 → 映射到哪些片段/主题段 → 哪些缺口 → 如何补）+ 编辑入口。

### 验证方式
1. 给定 ProjectIR + 指令集 `["把第2段删掉","字幕改黄色描边","第3段换成模板B风格"]` → 单测断言生成 patch 正确；重渲染后 draft 相应变化；非法指令可读报错；可回滚到上一版。
2. 可视化面板人工走查：能看到"抽取 → 映射 → 缺口 → 补全"全链路。

---

## 阶段 3: 保真升级 Tier B + 画面识别（略写，部分 Future） 📝

### 目标
把视觉保真度从 Tier A 提到 Tier B，并引入用户素材画面识别辅助选段。

### 初步构想
- 几何蒙版（圆/线性分屏/矩形）帧级识别 → 映射剪映内置蒙版 + 参数（位置/大小，羽化近似）。
- 字幕样式精化（字体近似匹配、描边/阴影、多行布局）、转场粗分类（硬切/叠化/滑动）、贴纸、**音效**识别。
- **新增** `understand/vision.py`（CLIP/VLM）：镜别 / 高光 / 废镜识别，辅助"哪段最好"与匹配。
- 扩展 `VisualStyle.{mask,effects}`、`StickerStyle`、`AudioStyle.sfx`；`render` 支持蒙版/转场/贴纸写出。

### 约束与验证
- 在 Tier A 闭环上**增量**，回归**不破坏保序与账本**。
- 蒙版类型识别正确率（人工对照）；画面识别在标注集上的准确率；阶段 2 闭环回归通过。

---

## 阶段 4: 多版本 + 卡点 + 前端完善（略写，Future） 📝

### 目标
同素材产出多版本、音乐卡点、前端体验闭环。

### 初步构想
- 多版本（对 IR 做不同变体）：**高点击 / 高转化 / 高节奏 / 高质感**版，并排预览选择。
- librosa 节拍：套用时把切点/缩放对齐节拍（用户加 BGM 时）。
- 前端：模板库浏览、提取结果可视化（切点/字幕/蒙版叠加）、套用结果在线预览。
- **FFmpeg 后台批量渲染**预览片（多版本用，纯后台，用户无需学）。

### 待讨论的问题
- 多版本的差异化策略如何定义与度量。
- 在线预览的渲染成本与缓存策略。

---

## 阶段 5: 内容优化层（略写，Future） 📝

### 目标
在保序剪辑之上引入内容理解，按营销结构创造性地重排片段、补全画面。

### 初步构想
- **结构重排**：内容理解 → 按 hook / 卖点推进 / 结尾转化 重排顺序、增删。
- **AIGC 补 B-roll**：对纯口播段落按语义检索素材库 / 生成画面（**检索优先、AIGC 增强**），治"口播画面单一"。
- **精确 BGM 曲目识别 / 选配**：曲目指纹识别 + 按情绪自动选配 BGM。

### 约束
这是**唯一允许打破保序**的层，且必须在**用户显式确认**后才重排。

### 待讨论的问题
- 重排结构的评估方式（人工 / LLM 评分）。
- AIGC 画面一致性与版权策略；检索素材库的来源。

---

## 交付物与文档
- **交付**：代码仓库、演示视频（剪映导出 hero case）、视频产物 case、说明文档。
- **说明文档须含**：整体 AI 架构、**工具协议**（各 tool 在 IR 上的 IO schema）、**安全边界**、**AI 工具使用披露**（用了哪些工具、各用于哪个环节、哪些是自主设计实现）。

## 安全边界
AIGC 内容审查；检索素材 / BGM 版权；文案补全**不编造 / 不夸大卖点**；用户上传内容合规。

## 风险与对策
| 风险 | 对策 |
|------|------|
| 剪映 draft 格式随版本漂移 | `config.py` 锁定版本；draft-writer 隔离在 IR 转换器之后，版本变只改 `render/jianying.py` |
| 特效精确识别难 | 白名单 + 分类器，集合内 1:1、集合外不支持（D4） |
| LLM 去重/分段不稳 | 账本可回溯；人工可调兜底 |
| 时长/数量不匹配（素材与槽位） | D8 时长自适应：伸缩区间 + 裁切/变速/复用兜底 |
| Python 3.13 与 ML 库不兼容 | 进阶段 1 前切 3.11/3.12 venv |
| WhisperX 中文对齐质量 | 预留校正阈值；必要时回退 faster-whisper 词级时间戳 |

## 待你提供的配置（进入阶段 0 前）
1. 剪映：**国内剪映 / 国际 CapCut？版本号？** draft 工程目录路径。
2. LLM：用哪家 provider + API key。
3. 一段 **5–20s 样例 mp4** 与一段 **~3min 口播 mp4**（用于阶段 0 / 2 验证）。
4. 是否同意：进阶段 1 前安装系统 ffmpeg、并新建 3.11/3.12 venv。
