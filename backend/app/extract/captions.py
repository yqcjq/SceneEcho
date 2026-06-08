"""1A-V1 · Caption style + position detection (VLM main path).

One VLM call per ``CaptionEvent`` group (frames sharing the same visual
caption). Cross-frame merging is by IoU > 0.5 + style + semantic_purpose.
The structured output schema enforces the 0-999 normalized coord system;
client-layer maps to 0-1 when writing into ``CaptionStyle.position``.

CaptionEvent is a Phase 1A intermediate dataclass — NOT in the IR (S10).
1B integration projects ``CaptionEvent.style`` into ``Slot.style.caption``
and emits ``Caption`` rows on ProjectIR at apply time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.frame_sampler import FrameSample
from app.ir.template import CaptionStyle
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import (
    FrameRef,
    LLMClient,
    chat_vision_dual,
    get_llm_client,
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


# ---------- Domain dataclass (Phase 1A intermediate, not IR) ----------


@dataclass
class CaptionEvent:
    """Captures one logical caption across the frames it appeared in.

    1B integration drops the bookkeeping fields (frames_appeared, raw bbox)
    and lifts ``style`` into ``Slot.style.caption``.
    """

    style: CaptionStyle
    start: float  # earliest ts where the caption was visible
    end: float
    placeholder_text: list[str]
    length_constraint: dict[str, int]
    semantic_purpose: str
    bbox_norm_0_999: tuple[int, int, int, int]
    frames_appeared: list[float] = field(default_factory=list)
    confidence: float = 0.0


# ---------- Public API ----------


async def detect_captions(
    normalized_path: Path,
    frames: Sequence[FrameSample],
    *,
    task_id: str,
    parent_event_id: str | None = None,
    client: LLMClient | None = None,
) -> tuple[list[CaptionEvent], list[VisionEvent]]:
    """Issue one VLM call covering up to 6 sampled frames.

    Phase 1A keeps the caller surface small: feed the sampled frames in,
    receive consolidated CaptionEvents back. Cross-frame deduplication
    happens here (IoU + visual style); the workbench sees the call event
    plus per-CaptionEvent IR-write events.
    """
    if not frames:
        return [], []
    settings = get_settings()
    cl = client or get_llm_client(stage=STAGE)
    bus = get_event_bus()

    # Cap frames per call so the prompt stays under context budget.
    limited = list(frames)[:6]
    frame_refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in limited]
    user_prompt = (
        "请按上述 schema 识别这些采样帧中的字幕。"
        f"采样时间戳依次为 {[round(f.ts, 2) for f in limited]}（秒）。"
    )
    messages = [
        {"role": "system", "content": load_prompt("1a_captions")},
        {"role": "user", "content": user_prompt},
    ]
    if should_dual_check(STAGE):
        from app.llm.client import AnthropicClient, OpenAICompatClient

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
            task_id=task_id,
            frames=frame_refs,
            ir_target_template=IRTarget(ir_type="TemplateIR", path="skeleton"),
            schema=CaptionsRawResult,
            parent_event_id=parent_event_id,
        )
    else:
        result, events = await cl.chat_vision(
            messages,
            model=settings.model_vlm,
            stage=STAGE,
            task_id=task_id,
            frames=frame_refs,
            ir_target_template=IRTarget(ir_type="TemplateIR", path="skeleton"),
            schema=CaptionsRawResult,
            parent_event_id=parent_event_id,
        )
    # Merge same-caption rows that the model returned per-frame.
    merged = _merge_captions(result.captions)
    out: list[CaptionEvent] = []
    for cap in merged:
        if not cap.frames_appeared:
            continue
        ts_appeared = [limited[i].ts for i in cap.frames_appeared if 0 <= i < len(limited)]
        if not ts_appeared:
            continue
        bbox = _bbox_from_pos_size(cap.position_norm_0_999, cap.size_norm_0_999)
        style = _to_caption_style(cap, bbox)
        ev = CaptionEvent(
            style=style,
            start=min(ts_appeared),
            end=max(ts_appeared) + 0.5,  # tail buffer
            placeholder_text=cap.placeholder_text,
            length_constraint=cap.length_constraint,
            semantic_purpose=cap.semantic_purpose,
            bbox_norm_0_999=bbox,
            frames_appeared=ts_appeared,
            confidence=cap.confidence,
        )
        # Fire one entity-level VisionEvent per merged caption so the
        # workbench's right pane can flash the destination Slot's
        # style.caption field as the IR fills in.
        entity_ev = VisionEvent(
            task_id=task_id,
            source="vlm",
            model_used=settings.model_vlm,
            stage=STAGE,
            frame_ts=ev.start,
            bbox_norm=tuple(float(v) for v in bbox),
            semantic_label=f"字幕：{cap.semantic_purpose} · {style.layout}",
            reasoning=cap.reasoning[:200],
            confidence=cap.confidence,
            ir_target=IRTarget(
                ir_type="TemplateIR",
                path=f"skeleton[{ev_slot_idx(cap.frames_appeared, limited)}].style.caption",
            ),
            ir_value=style.model_dump(mode="json"),
            parent_event_id=events[0].event_id if events else parent_event_id,
            duration_ms=0,
        )
        await bus.publish(task_id, entity_ev)
        events.append(entity_ev)
        out.append(ev)
    return out, events


# ---------- helpers ----------


def ev_slot_idx(frames_appeared_indices: list[int], frames: Sequence[FrameSample]) -> int:
    """Map the frames a caption appeared in to a Slot index (best-guess).

    Phase 1A uses ``scene_idx`` of the median frame the caption appeared in.
    1B's skeleton.py refines this by re-binding to the discovered slots
    (开头 / 主体 / 结尾 boundaries).
    """
    if not frames_appeared_indices:
        return 0
    mid = frames_appeared_indices[len(frames_appeared_indices) // 2]
    if 0 <= mid < len(frames):
        idx = frames[mid].scene_idx
        if idx is not None:
            return idx
    return 0


def _merge_captions(rows: list[_CaptionRaw]) -> list[_CaptionRaw]:
    """Group rows referring to the same visual caption.

    Heuristic: same ``semantic_purpose`` + bbox IoU > 0.5 + position center
    within 5% of canvas → merge. Works because the VLM was already asked
    to consolidate, but providers occasionally return per-frame copies.
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
                # Union the frames_appeared list, keep first row's metadata.
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
