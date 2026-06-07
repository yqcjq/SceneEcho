"""TemplateIR — reusable style recipe = skeleton + style rules + tags."""
from __future__ import annotations

from pydantic import BaseModel, Field

SlotRole = str  # open enum; basic: 开头|主体|结尾


class CaptionStyle(BaseModel):
    font_family: str = "NotoSansSC"
    size: int = 56
    color: str = "#FFFFFF"
    stroke_color: str | None = "#000000"
    stroke_width: int = 2
    position: tuple[float, float] = (0.5, 0.85)
    layout: str = "single"
    max_chars_per_line: int = 12
    anim_in: str = "fade"
    anim_emphasis: str | None = None
    emphasis_words: list[str] = Field(default_factory=list)


class ZoomKeyframe(BaseModel):
    relative_time: float
    scale: float


class VisualStyle(BaseModel):
    zoom_keyframes: list[ZoomKeyframe] = Field(default_factory=list)
    mask: str | None = None
    color_lut: str | None = None
    title_bar: bool = False


class AudioStyle(BaseModel):
    has_bgm: bool = False
    is_instrumental: bool = True
    bpm: float | None = None
    energy_curve: list[float] = Field(default_factory=list)
    mood_tag: str | None = None
    bgm_path: str | None = None
    bgm_features: dict | None = None


class StickerEvent(BaseModel):
    description: str
    position: tuple[float, float]
    size: tuple[float, float]
    start: float
    end: float
    generated_image: str | None = None


class StyleRule(BaseModel):
    caption: CaptionStyle | None = None
    visual: VisualStyle = Field(default_factory=VisualStyle)
    audio: AudioStyle = Field(default_factory=AudioStyle)
    stickers: list[StickerEvent] = Field(default_factory=list)
    rhythm: dict = Field(default_factory=dict)
    transition_in: str | None = None
    transition_out: str | None = None


class Slot(BaseModel):
    role: SlotRole
    duration: dict = Field(default_factory=lambda: {"min": 1.0, "nominal": 3.0, "max": 6.0})
    material_req: str = "人物口播"
    style: StyleRule = Field(default_factory=StyleRule)
    caption_function: str = "regular"


class Tags(BaseModel):
    position: str = "中间"
    function: str = "逻辑讲述"
    scene: str = "纯口播"
    notes: str = ""


class TemplateIR(BaseModel):
    id: str
    name: str
    source_sample: str
    skeleton: list[Slot] = Field(default_factory=list)
    global_style: dict = Field(
        default_factory=lambda: {"canvas": {"width": 1080, "height": 1920, "fps": 30}}
    )
    tags: Tags = Field(default_factory=Tags)
    sanity_check: dict | None = None
    created_at: str = ""
