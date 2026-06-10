"""Phase1AReport — 1A 阶段所有子能力的识别结果聚合 IR。

PLAN.md 1349-1492 行约束 1A "本阶段不产出 TemplateIR，只产出可独立调用的子能力函数"。
但 D9/D13 又要求每个 AI 调用必发 VisionEvent + 可选 ir_target，于是 1A 早期实现把所有
事件硬塞 ir_type='TemplateIR' + path='skeleton[N].xxx'，前端 lodash.set 把它们拼成
半成品 TemplateIR——架构上自相矛盾。

Phase1AReport 是 1A 自己的"识别报告" IR：每个 1A 子能力的 VisionEvent 都把 ir_target
指向这棵树，工作台右栏在 1A.* stage 任务下渲染 Phase1AReport（而不是 TemplateIR）。
1B 集成阶段 skeleton.py 读 Phase1AReport → 映射到 TemplateIR.skeleton[N].style.{...} +
聚类成 TemplateIR.caption_style_palette。

decisions/010 + decisions/011 落地后：
- Phase1ACaptionEvent 不再持有动画/raw 字段（``verified_anim_in`` / ``stagger_ms`` /
  ``color_hex_raw`` / ``anim_in_type_raw`` / ``layout_raw`` 等字段已删除）；动画语义改由
  ``Phase1ACaptionFunctionEvent`` 承担。captions_anim 子能力整体删除。
- Phase1AReport 加 ``caption_style_palette`` 与 ``caption_functions`` 两个新分支：palette
  存 1A 阶段已聚类的字幕视觉样式（1B 直接搬到 ``TemplateIR.caption_style_palette``），
  caption_functions 保留每条字幕的功能 + 动画类型记录（per-caption 时序信息）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.ir.template import AudioStyle, CaptionStyle, StickerEvent, ZoomKeyframe


class Phase1AScene(BaseModel):
    """单个切点（PySceneDetect 结果）。"""

    idx: int
    start_sec: float
    end_sec: float


class Phase1ACaptionEvent(BaseModel):
    """画面字幕识别中间产物（VLM 主路径）。

    本字段仅描述**画面里烧入的视觉字幕**（visual caption / burnt-in subtitle），
    不处理语音转写——音频字幕由后续 ASR 阶段产出。``placeholder_text`` 是
    描述性占位短语（如「4-6 字 CTA 强调短语」），不抄字幕原文。

    1B 集成时：捕获到的视觉样式会被聚类成 ``TemplateIR.caption_style_palette``
    元素；每个 Phase1ACaptionEvent 通过 ``palette_idx`` 字段引用所属 palette
    元素（聚类前 None；聚类后填充）。每个 Slot 通过 dominant Phase1ACaptionEvent
    的 palette_idx 反查对应 ``CaptionStyle``。

    动画类型不在本结构中——它由 ``Phase1ACaptionFunctionEvent`` 承担，per-caption
    一对一关联（through ``caption_idx``）。captions_anim 子能力已被 decisions/011
    删除，``verified_anim_in`` / ``stagger_ms`` 等字段不再存在。
    """

    style: CaptionStyle
    start: float
    end: float
    placeholder_text: list[str] = Field(default_factory=list)
    length_constraint: dict[str, int] = Field(default_factory=dict)
    semantic_purpose: str = "regular"
    bbox_norm_0_999: tuple[int, int, int, int] = (0, 0, 0, 0)
    frames_appeared: list[float] = Field(default_factory=list)
    confidence: float = 0.0
    # VLM 给的中文解释（≤200 字），用作工作台右栏审计
    reasoning: str = ""
    # 聚类后填上：指向 ``Phase1AReport.caption_style_palette`` / ``TemplateIR
    # .caption_style_palette`` 的索引。None = 尚未聚类或属"未匹配的"独立样式。
    palette_idx: int | None = None


class Phase1ACaptionFunctionEvent(BaseModel):
    """字幕功能 + 动画类型（per-caption 关联到 ``Phase1AReport.captions[caption_idx]``）。

    decisions/011 落地后：caption_function 子能力承担"字幕扮演什么功能 + 用什么动画类型"
    二维语义。captions_anim 子能力已删除，原由其负责的 ``verified_anim_in`` / ``stagger_ms``
    现由 caption_function VLM 估算（精度从 ±30ms 退到 ±100-200ms，已知代价 1）。
    """

    caption_idx: int  # ref into ``Phase1AReport.captions``
    function: Literal[
        "标题", "强调", "卖点", "CTA", "regular", "过渡引语"
    ] = "regular"
    anim_in_type: Literal[
        "逐字弹入", "整句滑入", "淡入", "打字机", "unknown"
    ] = "unknown"
    anim_emphasis: str | None = None  # 关键词高亮 / 抖动 / 放大 / None
    stagger_ms_estimate: int | None = None  # VLM 估算的逐字 stagger 间隔（ms）
    role_in_template: str | None = None  # "开头主标题" / "卖点反复强化" / "结尾 CTA" 等
    confidence: float = 0.0
    reasoning: str = ""


class Phase1AStickerDetection(BaseModel):
    """贴纸检测中间产物（VLM 网格识别 + CV bbox 精化）。

    ``reasoning`` 是 VLM 给的中文解释（≤200 字），``description`` 复制自
    ``sticker.description``（≤30 字外观描述），保留两份以便右栏 IR 树
    一眼看到要点。
    """

    sticker: StickerEvent
    bbox_norm_0_999: tuple[int, int, int, int]
    frames_appeared: list[float] = Field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""


class Phase1AMaskParams(BaseModel):
    """每 scene 的几何蒙版判定 + 参数。"""

    has_mask: bool = False
    kind: Literal["circle", "rectangle", "line_split"] | None = None
    params_norm_0_999: dict | None = None
    confidence: float = 0.0


class Phase1AColorReport(BaseModel):
    """全局调色语义 + OpenCV 直方图微调。"""

    tags: list[str] = Field(default_factory=list)
    dominant_lut_id: str | None = None
    confidence: float = 0.0
    histogram: dict[str, float] | None = None


class BRollSegment(BaseModel):
    """画面构成识别结果（per-scene）。

    decisions/010 决策 6（ISS-023）落地后引入。VLM 看每个 scene 的中间帧
    分类成四类（人物主导 / 全屏 B-roll / 画中画 / 侧栏）+ 可选 ROI bbox。
    Phase 5 ``generate_broll`` 真接入时直接消费 ``Phase1AReport.b_roll_segments``
    判断哪段时间该启用 AI 补画面，本期 1A 仅落识别字段、不触发任何
    AIGC 调用，与 D10「AIGC 用户主动触发」不冲突。

    1B ``skeleton.py::_infer_material_req`` 在 Slot 内有任一非 ``人物主导``
    BRollSegment 时把 material_req 标为 ``AI生成画面``。
    """

    scene_idx: int
    kind: Literal["人物主导", "全屏 B-roll", "画中画", "侧栏"] = "人物主导"
    start: float = 0.0
    end: float = 0.0
    bbox_norm_0_999: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    reasoning: str = ""


class Phase1AReport(BaseModel):
    """1A 单次抽取的全部识别结果聚合。

    工作台右栏在 ``stage.startswith("1A.")`` 任务下渲染这棵树（取代假装写入
    TemplateIR）。键设计原则：
    - 列表型（scenes / captions / stickers / caption_style_palette / caption_functions）
      支持 ``ir_target.op="append"`` 逐条增量写入，方便事件流驱动的命中字段闪烁。
    - 字典型（zoom_directions / transitions / masks / zoom_curves）以
      ``str(scene_idx)`` 作 key（JSON 友好），lodash 路径形如
      ``zoom_directions.0`` / ``masks.2`` 直接命中。
    - 单值型（color / audio）整对象写。

    1B 集成时 ``caption_style_palette`` 直接搬到 ``TemplateIR.caption_style_palette``，
    1A.captions 阶段的事件流也写到这里，让工作台可在 1A 阶段就看到 palette 拼装过程。
    """

    scenes: list[Phase1AScene] = Field(default_factory=list)
    captions: list[Phase1ACaptionEvent] = Field(default_factory=list)
    # 1A 阶段已聚类的字幕视觉样式 palette。captions[i].palette_idx 引用本列表。
    caption_style_palette: list[CaptionStyle] = Field(default_factory=list)
    # per-caption 功能 + 动画分类。caption_functions[k].caption_idx 关联回 captions。
    caption_functions: list[Phase1ACaptionFunctionEvent] = Field(default_factory=list)
    stickers: list[Phase1AStickerDetection] = Field(default_factory=list)
    zoom_directions: dict[str, str] = Field(default_factory=dict)
    zoom_curves: dict[str, list[ZoomKeyframe]] = Field(default_factory=dict)
    transitions: dict[str, str] = Field(default_factory=dict)
    masks: dict[str, Phase1AMaskParams] = Field(default_factory=dict)
    color: Phase1AColorReport | None = None
    audio: AudioStyle | None = None
    # decisions/010 决策 6（ISS-023）：每 scene 一条 BRollSegment 记录画面
    # 构成类型（人物主导 / 全屏 B-roll / 画中画 / 侧栏），1B skeleton 据此
    # 把含非「人物主导」段的 Slot 标 material_req=AI生成画面。
    b_roll_segments: list[BRollSegment] = Field(default_factory=list)
