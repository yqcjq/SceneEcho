"""TemplateIR — reusable style recipe = skeleton + style rules + tags."""

from __future__ import annotations

from pydantic import BaseModel, Field

SlotRole = str  # open enum; basic: 开头|主体|结尾


class CaptionStyle(BaseModel):
    """Visual + behavioral style of a caption.

    The visual subset (font / color / stroke / shadow / background / padding /
    align / spacing / bbox / position / layout / max_chars_per_line) is what
    the model-level palette dedupes over (see ``TemplateIR.caption_style_palette``).
    The behavioral subset (anim_in / anim_emphasis / emphasis_words) is filled
    by ``caption_function`` (1A) / ``apply.style`` (Phase 2) onto the same
    object — palette stores defaults, per-Caption instances override.
    """

    # ----- visual: typography -------------------------------------------------
    font_family: str = "NotoSansSC"
    size: int = 56
    color: str = "#FFFFFF"
    stroke_color: str | None = "#000000"
    stroke_width: int = 2
    # Subtitle drop shadow — accept None to mean "no shadow".
    shadow_color: str | None = None
    shadow_offset: tuple[int, int] = (0, 0)  # (dx, dy) in px
    shadow_blur: int = 0
    background_color: str | None = None
    # Internal padding inside the bbox (top, right, bottom, left) px.
    padding: tuple[int, int, int, int] = (0, 0, 0, 0)
    text_align: str = "center"  # left | center | right
    letter_spacing: float = 0.0
    line_height: float = 1.2

    # ----- visual: layout / position -----------------------------------------
    # Center point in normalized [0,1] (kept for legacy renderers + simple
    # placement hints). New consumers should prefer ``bbox_norm`` for full
    # rectangle so anchor-aware fitting works.
    position: tuple[float, float] = (0.5, 0.85)
    # Full bbox in 0-999 normalized coordinates [x_left, y_top, w, h]. Zero
    # tuple means unknown — caller falls back to ``position`` + estimated
    # width from text length.
    bbox_norm: tuple[int, int, int, int] = (0, 0, 0, 0)
    layout: str = "single"
    max_chars_per_line: int = 12

    # ----- behavioral (palette default; Caption instance overrides) ----------
    anim_in: str = "fade"
    anim_emphasis: str | None = None
    emphasis_words: list[str] = Field(default_factory=list)

    # ----- VLM-supplied placeholders + semantic purpose ----------------------
    # Phase 1B: VLM-supplied semantic placeholder ("4-6 字 CTA 短语示例：立即抢购")
    # carried directly on the style. Skeleton copies it from the corresponding
    # Phase1ACaptionEvent so renderer's template_preview mode + Phase 2's
    # caption-fill LLM both read from one canonical field. Not the same as
    # ``Unit.text`` — this is a hint for the fill prompt, never displayed in
    # the final project_output render.
    placeholder_text: list[str] = Field(default_factory=list)
    length_constraint: dict[str, int] = Field(default_factory=dict)
    semantic_purpose: str = "regular"


class ZoomKeyframe(BaseModel):
    relative_time: float
    scale: float
    # Camera pan offsets — normalized to frame size; 0.0 = no pan. Combined
    # with ``scale`` to give a 3-DoF transform per keyframe (translateX,
    # translateY, scale). Set by ``motion.estimate_zoom_curve`` (LK optical
    # flow centroid drift) so the renderer can express "向左推进" with both
    # ``scale > 1`` and ``dx > 0``. Default 0.0 keeps existing fixtures
    # backward-compatible.
    dx: float = 0.0
    dy: float = 0.0


class VisualStyle(BaseModel):
    zoom_keyframes: list[ZoomKeyframe] = Field(default_factory=list)
    # ``mask`` is the kind ("circle" / "rectangle" / "line_split"); the
    # geometry lives in ``mask_params`` so the renderer can draw without
    # making a second lookup. Both must be set together (skeleton.py enforces).
    mask: str | None = None
    mask_params: dict | None = None
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
    # Coarse semantic tag (e.g. "强调提示" / "信息标签" / "情绪表达"). The
    # 1A sticker pipeline emits this in its second-pass classify step;
    # Phase 0.5 mocks include it so the workbench can demo the field flash.
    semantic_category: str | None = None


class StyleRule(BaseModel):
    # Caption is referenced by index into ``TemplateIR.caption_style_palette``
    # rather than carried inline — the palette is the model-level dedup view
    # of all distinct caption styles in the sample. None = this slot has no
    # caption. Use ``TemplateIR.get_slot_caption(slot)`` for safe lookup
    # (returns None when idx is out of range).
    caption_palette_idx: int | None = None
    visual: VisualStyle = Field(default_factory=VisualStyle)
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
    # Model-level palette of distinct caption visual styles. Slots reference
    # by index via ``Slot.style.caption_palette_idx``. Building this happens
    # in ``extract/skeleton.py`` after captions detection.
    caption_style_palette: list[CaptionStyle] = Field(default_factory=list)
    audio: AudioStyle | None = None
    global_style: dict = Field(
        default_factory=lambda: {"canvas": {"width": 1080, "height": 1920, "fps": 30}}
    )
    tags: Tags = Field(default_factory=Tags)
    sanity_check: dict | None = None
    created_at: str = ""
    # Phase 1B: per-field degradation flags so the UI can flag partial
    # results without losing the rest of the template. Keys are dotted
    # TemplateIR paths (e.g. "skeleton.*.style.caption" / "tags" / "audio").
    # Set by ``pipeline.extract_template`` when a subcap raises; the
    # ``SUBCAP_TO_IR_PATH`` table in pipeline.py is the single source of
    # truth for the mapping from subcap label → TemplateIR path so the UI
    # banner can navigate to the affected field.
    degraded: dict[str, str] = Field(default_factory=dict)

    def get_slot_caption(self, slot: Slot) -> CaptionStyle | None:
        """Resolve a slot's caption style via the palette. Returns None when
        the slot has no caption or the index is out of range."""
        idx = slot.style.caption_palette_idx
        if idx is None or not (0 <= idx < len(self.caption_style_palette)):
            return None
        return self.caption_style_palette[idx]
