"""Phase1AReport — 1A 阶段所有子能力的识别结果聚合 IR。

PLAN.md 1349-1492 行约束 1A "本阶段不产出 TemplateIR，只产出可独立调用的子能力函数"。
但 D9/D13 又要求每个 AI 调用必发 VisionEvent + 可选 ir_target，于是 1A 早期实现把所有
事件硬塞 ir_type='TemplateIR' + path='skeleton[N].xxx'，前端 lodash.set 把它们拼成
半成品 TemplateIR——架构上自相矛盾。

Phase1AReport 是 1A 自己的"识别报告" IR：每个 1A 子能力的 VisionEvent 都把 ir_target
指向这棵树，工作台右栏在 1A.* stage 任务下渲染 Phase1AReport（而不是 TemplateIR）。
1B 集成阶段 skeleton.py 读 Phase1AReport → 映射到 TemplateIR.skeleton[N].style.{...}。
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
    """画面字幕识别中间产物（VLM 主路径 + CV 动画细节 + 功能分类填充）。

    本字段仅描述**画面里烧入的视觉字幕**（visual caption / burnt-in subtitle），
    不处理语音转写——音频字幕由后续 ASR 阶段产出。``placeholder_text`` 是
    描述性占位短语（如「4-6 字 CTA 强调短语」），不抄字幕原文。

    1B 集成时拆 ``style`` 写入对应 ``Slot.style.caption``，并由 Caption 列表
    （ProjectIR）按 start/end 渲染。``verified_anim_in`` / ``stagger_ms``
    由 ``captions_anim`` 后续 verify 填上；``function`` 由 caption_function
    classify 填上；``reasoning`` 是 VLM 给出的中文解释（≤200 字）。
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
    # VLM 给的中文解释 + 原始字段（用于工作台右栏审计）
    reasoning: str = ""
    color_hex_raw: str | None = None
    anim_in_type_raw: str | None = None
    layout_raw: str | None = None
    # captions_anim 填上
    verified_anim_in: str | None = None
    stagger_ms: int | None = None
    # classify_caption_function 填上
    function: str | None = None  # 标题/强调/卖点/CTA/regular/过渡


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


class Phase1AReport(BaseModel):
    """1A 单次抽取的全部识别结果聚合。

    工作台右栏在 ``stage.startswith("1A.")`` 任务下渲染这棵树（取代假装写入
    TemplateIR）。键设计原则：
    - 列表型（scenes / captions / stickers）支持 ``ir_target.op="append"``
      逐条增量写入，方便事件流驱动的命中字段闪烁。
    - 字典型（zoom_directions / transitions / masks / zoom_curves）以
      ``str(scene_idx)`` 作 key（JSON 友好），lodash 路径形如
      ``zoom_directions.0`` / ``masks.2`` 直接命中。
    - 单值型（color / audio）整对象写。
    """

    scenes: list[Phase1AScene] = Field(default_factory=list)
    captions: list[Phase1ACaptionEvent] = Field(default_factory=list)
    stickers: list[Phase1AStickerDetection] = Field(default_factory=list)
    zoom_directions: dict[str, str] = Field(default_factory=dict)
    zoom_curves: dict[str, list[ZoomKeyframe]] = Field(default_factory=dict)
    transitions: dict[str, str] = Field(default_factory=dict)
    masks: dict[str, Phase1AMaskParams] = Field(default_factory=dict)
    color: Phase1AColorReport | None = None
    audio: AudioStyle | None = None
