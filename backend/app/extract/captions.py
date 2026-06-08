"""1A-V1 · Caption style + position detection (VLM main path).

One VLM call per ``detect_captions`` invocation; cross-frame merging by
IoU > 0.5 + style + semantic_purpose. The structured output schema enforces
the 0-999 normalized coord system; this module maps to 0-1 when constructing
the final ``CaptionStyle.position``.

Per-caption events append to ``Phase1AReport.captions`` (pydantic IR
exported by ``app.ir.phase1a_report``). 1B integration reads
``Phase1AReport.captions[N].style`` and lifts it into ``Slot.style.caption``.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.extract.frame_sampler import FrameSample
from app.ir.phase1a_report import Phase1ACaptionEvent
from app.ir.template import CaptionStyle
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import (
    AnthropicClient,
    FrameRef,
    OpenAICompatClient,
    chat_vision_dual,
    should_dual_check,
)
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "1A.captions"
log = get_logger(__name__)


# ---------- VLM response schema (0-999 coords, raw VLM output) ----------


class _CaptionRaw(BaseModel):
    position_norm_0_999: list[int] = Field(default_factory=list)
    size_norm_0_999: list[int] = Field(default_factory=list)
    color_hex: str = "#FFFFFF"
    stroke_color_hex: str | None = None
    stroke_width_px: int = 0
    font_size_px_estimate: int = 56
    anim_in_type: str = "unknown"
    layout: str = "single"
    max_chars_per_line: int = 12
    placeholder_text: list[str] = Field(default_factory=list)
    length_constraint: dict[str, int] = Field(default_factory=dict)
    semantic_purpose: str = "regular"
    frames_appeared: list[int] = Field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""


class CaptionsRawResult(BaseModel):
    captions: list[_CaptionRaw] = Field(default_factory=list)

    def __workbench_label__(self) -> str:
        return f"字幕识别 · {len(self.captions)} 条"


# ---------- Public API ----------


async def detect_captions(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[list[Phase1ACaptionEvent], list[VisionEvent]]:
    """Issue one VLM call covering up to 6 sampled frames; return merged captions.

    Cross-frame deduplication happens here (IoU + visual style); the workbench
    sees one call event (no IR write) plus one append-event per merged caption.
    """
    frames = await ctx.frames()
    if not frames:
        return [], []
    settings = get_settings()
    cl = ctx.client(STAGE)
    bus = get_event_bus()

    # Cap frames per call so the prompt stays under context budget.
    limited = list(frames)[:6]
    frame_refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in limited]
    user_prompt = (
        "请按上述 schema 识别这些采样帧中的字幕。"
        f"采样时间戳依次为 {[round(f.ts, 2) for f in limited]}（秒）。"
        "frames_appeared 用 0-indexed 整数，对应上述时间戳数组的下标。"
    )
    messages = [
        {"role": "system", "content": load_prompt("1a_captions")},
        {"role": "user", "content": user_prompt},
    ]
    if should_dual_check(STAGE):
        primary, secondary = (
            (cl, AnthropicClient())
            if isinstance(cl, OpenAICompatClient)
            else (cl, OpenAICompatClient())
        )
        result, events = await chat_vision_dual(
            primary=primary,
            secondary=secondary,
            messages=messages,
            model_primary=settings.model_vlm,
            model_secondary="claude-sonnet-4-6",
            stage=STAGE,
            task_id=ctx.task_id,
            frames=frame_refs,
            ir_target_template=None,  # call-level event has no IR write
            schema=CaptionsRawResult,
            parent_event_id=parent_event_id,
        )
    else:
        result, events = await cl.chat_vision(
            messages,
            model=settings.model_vlm,
            stage=STAGE,
            task_id=ctx.task_id,
            frames=frame_refs,
            ir_target_template=None,  # call-level event has no IR write
            schema=CaptionsRawResult,
            parent_event_id=parent_event_id,
        )
    # Merge same-caption rows that the model returned per-frame.
    merged = _merge_captions(result.captions)
    out: list[Phase1ACaptionEvent] = []
    call_ev_id = events[0].event_id if events else parent_event_id
    for cap in merged:
        if not cap.frames_appeared:
            continue
        anchor_idx = next((i for i in cap.frames_appeared if 0 <= i < len(limited)), None)
        if anchor_idx is None:
            continue
        anchor = limited[anchor_idx]
        ts_appeared = [limited[i].ts for i in cap.frames_appeared if 0 <= i < len(limited)]
        bbox = _bbox_from_pos_size(cap.position_norm_0_999, cap.size_norm_0_999)
        style = _to_caption_style(cap, bbox)
        entry = Phase1ACaptionEvent(
            style=style,
            start=min(ts_appeared),
            end=max(ts_appeared) + 0.5,  # tail buffer
            placeholder_text=cap.placeholder_text,
            length_constraint=cap.length_constraint,
            semantic_purpose=cap.semantic_purpose,
            bbox_norm_0_999=bbox,
            frames_appeared=ts_appeared,
            confidence=cap.confidence,
            reasoning=cap.reasoning[:200],
            color_hex_raw=cap.color_hex,
            anim_in_type_raw=cap.anim_in_type,
            layout_raw=cap.layout,
        )
        # Entity-level event: append to Phase1AReport.captions. ``frame_url``
        # is the anchor frame the caption first appears on so the workbench
        # left pane can render the frame image + bbox overlay.
        entity_ev = VisionEvent(
            task_id=ctx.task_id,
            source="vlm",
            model_used=settings.model_vlm,
            stage=STAGE,
            frame_ts=anchor.ts,
            frame_url=f"/data/{anchor.rel_path.lstrip('/')}",
            bbox_norm=tuple(float(v) for v in bbox),
            semantic_label=f"画面字幕：{cap.semantic_purpose} · {style.layout}",
            reasoning=cap.reasoning[:200],
            confidence=cap.confidence,
            ir_target=IRTarget(ir_type="Phase1AReport", path="captions", op="append"),
            ir_value=entry.model_dump(mode="json"),
            parent_event_id=call_ev_id,
            duration_ms=0,
        )
        await bus.publish(ctx.task_id, entity_ev)
        events.append(entity_ev)
        out.append(entry)
    return out, events


# ---------- helpers ----------


def _merge_captions(rows: list[_CaptionRaw]) -> list[_CaptionRaw]:
    """Group rows referring to the same visual caption.

    Heuristic: same ``semantic_purpose`` + bbox IoU > 0.5 → merge. Works
    because the VLM was already asked to consolidate, but providers
    occasionally return per-frame copies.
    """
    if not rows:
        return []
    groups: list[_CaptionRaw] = []
    for r in rows:
        merged = False
        for g in groups:
            if (
                r.semantic_purpose == g.semantic_purpose
                and _iou(r.position_norm_0_999, g.position_norm_0_999) > 0.5
            ):
                g.frames_appeared = sorted(set(g.frames_appeared) | set(r.frames_appeared))
                if r.confidence > g.confidence:
                    g.placeholder_text = r.placeholder_text or g.placeholder_text
                    g.reasoning = r.reasoning or g.reasoning
                merged = True
                break
        if not merged:
            groups.append(r)
    return groups


def _iou(a: list[int], b: list[int]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 0.0
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _bbox_from_pos_size(pos: list[int], size: list[int]) -> tuple[int, int, int, int]:
    if len(pos) >= 4:
        return tuple(pos[:4])  # type: ignore[return-value]
    if len(pos) >= 2 and len(size) >= 2:
        return (pos[0], pos[1], size[0], size[1])
    return (0, 0, 0, 0)


def _to_caption_style(cap: _CaptionRaw, bbox: tuple[int, int, int, int]) -> CaptionStyle:
    cx = (bbox[0] + bbox[2] / 2) / 1000.0
    cy = (bbox[1] + bbox[3] / 2) / 1000.0
    return CaptionStyle(
        size=cap.font_size_px_estimate,
        color=cap.color_hex,
        stroke_color=cap.stroke_color_hex,
        stroke_width=cap.stroke_width_px,
        position=(round(cx, 4), round(cy, 4)),
        layout=cap.layout if cap.layout in ("single", "multi") else "single",
        max_chars_per_line=cap.max_chars_per_line,
        anim_in=cap.anim_in_type,
    )


# ---------- legacy alias (back-compat for callers that import the dataclass) ----------

# The pre-二核 implementation exposed ``CaptionEvent`` (a dataclass) as the
# return-type of detect_captions; downstream code (captions_anim, the lab
# runner, integration tests) imports it. Map the alias to the new pydantic
# IR model so existing imports keep working without ABC churn.
CaptionEvent = Phase1ACaptionEvent

__all__ = [
    "CaptionEvent",
    "CaptionsRawResult",
    "Phase1ACaptionEvent",
    "STAGE",
    "detect_captions",
]


def _scene_anchor_frames(frames: Sequence[FrameSample]) -> list[FrameSample]:
    """Used by older imports — returns frames unchanged. Kept as a no-op."""
    return list(frames)
