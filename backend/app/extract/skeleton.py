"""1B · Skeleton inference from Phase1AReport → TemplateIR.skeleton[].

Reads the identified scenes / captions / stickers / zoom / masks / transitions
already accumulated in ``Phase1AReport`` and projects them into the
"reusable style recipe" view of TemplateIR — a list of ``Slot`` objects with
role / duration range / material_req / per-slot ``StyleRule``.

Design (PLAN 1510):
- 3 roles by position threshold (D5: skeleton "discovered" not "preset"):
    start ratio < 0.30           → 开头
    start ratio > 0.70           → 结尾
    everything else              → 主体
  Scenes that share a role merge into one Slot whose duration spans them.
- Per-slot ``StyleRule`` aggregates:
    caption: the dominant caption whose [start,end] overlaps the slot
    visual.zoom_keyframes: stitched zoom_curves of scenes in the slot
    visual.mask: first mask kind detected inside the slot
    visual.color_lut: dominant_lut_id from Phase1AReport.color (global)
    stickers: every detection whose time range overlaps the slot
    transition_in / out: classify_transitions assigned to the slot's
        entering / leaving boundary
- Audio is **template-global**, not per-slot — Phase1AReport.audio is a
  single AudioStyle object and skeleton.py does not copy it onto every
  slot. The pipeline writes it to ``TemplateIR.audio`` directly.
- material_req inference (PLAN 1510):
    has caption                  → 人物口播
    no caption, has zoom/sticker/mask → B-roll/包装
    neither                      → 待定
- Slot duration band (PLAN 1505): {min = span * 0.7, nominal = span, max = span * 1.5}
- One VisionEvent per Slot inference so the workbench right pane lights
  up the TemplateIR.skeleton[N] field as each slot is built.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.event_bus import get_event_bus
from app.ir.phase1a_report import Phase1AReport
from app.ir.template import (
    CaptionStyle,
    Slot,
    StickerEvent,
    StyleRule,
    VisualStyle,
    ZoomKeyframe,
)
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger

STAGE = "1B.skeleton"
log = get_logger(__name__)


@dataclass
class _Segment:
    """Working struct for a single Slot under construction."""

    role: str
    scene_indices: list[int]
    start: float
    end: float


def _role_for_position(start_ratio: float) -> str:
    """Map a scene's start position (0..1) to one of the three basic roles."""
    if start_ratio < 0.30:
        return "开头"
    if start_ratio > 0.70:
        return "结尾"
    return "主体"


def _group_scenes(report: Phase1AReport, total_duration: float) -> list[_Segment]:
    """Bin consecutive same-role scenes into segments.

    A single-scene video collapses to one "主体" segment (it lives in the
    middle by default); empty reports return [].
    """
    if not report.scenes or total_duration <= 0:
        return []
    segs: list[_Segment] = []
    for sc in report.scenes:
        ratio = sc.start_sec / total_duration
        role = _role_for_position(ratio)
        if segs and segs[-1].role == role:
            segs[-1].scene_indices.append(sc.idx)
            segs[-1].end = sc.end_sec
        else:
            segs.append(
                _Segment(
                    role=role,
                    scene_indices=[sc.idx],
                    start=sc.start_sec,
                    end=sc.end_sec,
                )
            )
    return segs


def _captions_in(seg: _Segment, report: Phase1AReport) -> list:
    """Caption entries overlapping the segment's time range."""
    return [c for c in report.captions if c.end > seg.start and c.start < seg.end]


def _stickers_in(seg: _Segment, report: Phase1AReport) -> list[StickerEvent]:
    """Sticker events overlapping the segment's time range."""
    out: list[StickerEvent] = []
    for det in report.stickers:
        s = det.sticker
        if s.end > seg.start and s.start < seg.end:
            out.append(s)
    return out


def _zoom_keyframes_for(seg: _Segment, report: Phase1AReport) -> list[ZoomKeyframe]:
    """Concat the per-scene zoom curves owned by this segment.

    Each scene's curve uses ``relative_time`` in [0,1]; we stitch them into
    one slot-local timeline by offsetting each curve's relative_time into
    the slot span and concatenating. When a scene has no curve (stable),
    we anchor a single scale=1.0 keyframe at its slot-local start.
    """
    out: list[ZoomKeyframe] = []
    slot_span = max(0.04, seg.end - seg.start)
    scene_lookup = {sc.idx: sc for sc in report.scenes}
    for sidx in seg.scene_indices:
        sc = scene_lookup.get(sidx)
        if sc is None:
            continue
        sc_span = max(0.04, sc.end_sec - sc.start_sec)
        sc_rel_start = (sc.start_sec - seg.start) / slot_span
        kfs = report.zoom_curves.get(str(sidx), [])
        if not kfs:
            out.append(ZoomKeyframe(relative_time=round(sc_rel_start, 4), scale=1.0))
            continue
        for kf in kfs:
            t = sc_rel_start + kf.relative_time * (sc_span / slot_span)
            out.append(
                ZoomKeyframe(relative_time=round(max(0.0, min(1.0, t)), 4), scale=kf.scale)
            )
    return out


def _dominant_mask(seg: _Segment, report: Phase1AReport) -> tuple[str | None, dict | None]:
    """First scene in the segment with a confirmed mask. Returns (kind, params).

    Both fields move together — the renderer needs the geometry, not just
    the kind. Returns (None, None) when no scene in the segment has one.
    """
    for sidx in seg.scene_indices:
        m = report.masks.get(str(sidx))
        if m is not None and m.has_mask and m.kind:
            # params_norm_0_999 in Phase1AMaskParams is shaped like
            # {kind: {cx, cy, radius}} — unwrap to the inner dict so the
            # renderer doesn't have to know about the wrapper layer.
            params = None
            if isinstance(m.params_norm_0_999, dict):
                params = m.params_norm_0_999.get(m.kind) or m.params_norm_0_999
            return m.kind, params
    return None, None


def _transition_for_boundary(prev_scene_idx: int | None, report: Phase1AReport) -> str | None:
    if prev_scene_idx is None:
        return None
    return report.transitions.get(str(prev_scene_idx))


def _infer_material_req(captions: list, stickers: list, has_zoom: bool, has_mask: bool) -> str:
    """PLAN 1510 mapping — caption presence is the strong signal."""
    if captions:
        return "人物口播"
    if stickers or has_zoom or has_mask:
        return "B-roll/包装"
    return "待定"


def _dominant_caption_style(captions: list) -> CaptionStyle | None:
    """Pick the highest-confidence caption + copy placeholder fields onto its style.

    Phase 1A's ``Phase1ACaptionEvent`` carries ``placeholder_text`` /
    ``length_constraint`` / ``semantic_purpose`` as siblings of ``style``;
    1B's renderer (template_preview mode) and Phase 2's caption-fill LLM
    both need them. Copying them onto ``CaptionStyle`` makes the slot
    self-contained — no Phase1AReport lookup needed at apply time.
    """
    if not captions:
        return None
    best = max(captions, key=lambda c: (c.confidence, -c.start))
    base = best.style.model_copy(
        update={
            "placeholder_text": list(best.placeholder_text or []),
            "length_constraint": dict(best.length_constraint or {}),
            "semantic_purpose": best.semantic_purpose or "regular",
        }
    )
    return base


def _build_slot(
    seg: _Segment,
    report: Phase1AReport,
    *,
    prev_seg_last_scene: int | None,
    next_seg_first_scene: int | None,
) -> Slot:
    """Assemble a Slot from one segment + the global Phase1AReport fields."""
    captions = _captions_in(seg, report)
    stickers = _stickers_in(seg, report)
    zoom = _zoom_keyframes_for(seg, report)
    mask_kind, mask_params = _dominant_mask(seg, report)
    # Has-zoom signal: any non-trivial curve (anything other than a single
    # scale=1.0 keyframe at t=0).
    has_real_zoom = any(abs(kf.scale - 1.0) > 0.02 for kf in zoom)

    span = max(0.04, seg.end - seg.start)
    style = StyleRule(
        caption=_dominant_caption_style(captions),
        visual=VisualStyle(
            zoom_keyframes=zoom,
            mask=mask_kind,
            mask_params=mask_params,
            color_lut=report.color.dominant_lut_id if report.color else None,
        ),
        stickers=stickers,
        transition_in=_transition_for_boundary(prev_seg_last_scene, report),
        transition_out=_transition_for_boundary(seg.scene_indices[-1], report)
        if next_seg_first_scene is not None
        else None,
    )

    # Caption function: pick the dominant caption's function classification if
    # any; "regular" otherwise (1B leaves the per-caption function tagging in
    # Phase 1A's classify_caption_function; here we just surface the slot-level
    # summary).
    caption_function = "regular"
    if captions:
        dominant = max(captions, key=lambda c: (c.confidence, -c.start))
        caption_function = dominant.function or "regular"

    return Slot(
        role=seg.role,
        duration={
            "min": round(span * 0.7, 3),
            "nominal": round(span, 3),
            "max": round(span * 1.5, 3),
        },
        material_req=_infer_material_req(captions, stickers, has_real_zoom, mask_kind is not None),
        style=style,
        caption_function=caption_function,
    )


async def build_skeleton(
    report: Phase1AReport,
    total_duration: float,
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[list[Slot], list[VisionEvent]]:
    """Project Phase1AReport → list[Slot] + per-slot VisionEvents.

    Empty reports / zero-duration videos return ([], []) — the pipeline
    layer treats this as a degraded skeleton and proceeds with an empty
    TemplateIR shell so downstream tagging / sanity check still run.
    """
    bus = get_event_bus()
    segments = _group_scenes(report, total_duration)
    if not segments:
        return [], []

    slots: list[Slot] = []
    events: list[VisionEvent] = []
    for i, seg in enumerate(segments):
        prev_last = segments[i - 1].scene_indices[-1] if i > 0 else None
        next_first = segments[i + 1].scene_indices[0] if i + 1 < len(segments) else None
        slot = _build_slot(
            seg,
            report,
            prev_seg_last_scene=prev_last,
            next_seg_first_scene=next_first,
        )
        slots.append(slot)
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=STAGE,
            semantic_label=(
                f"骨架 #{i} · {slot.role} · {slot.material_req} · "
                f"{seg.start:.1f}–{seg.end:.1f}s"
            ),
            reasoning=(
                f"位置阈值发现：start_ratio={(seg.start / total_duration):.2f} → {seg.role}；"
                f"覆盖 scenes {seg.scene_indices}；"
                f"字幕 {len(_captions_in(seg, report))} 条 / 贴纸 {len(_stickers_in(seg, report))} 枚 / "
                f"缩放关键帧 {len(slot.style.visual.zoom_keyframes)} 个 / "
                f"mask={slot.style.visual.mask}。"
            ),
            confidence=0.9,
            ir_target=IRTarget(
                ir_type="TemplateIR", path="skeleton", op="append"
            ),
            ir_value=slot.model_dump(mode="json"),
            parent_event_id=parent_event_id,
            duration_ms=0,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
    return slots, events


__all__ = ["STAGE", "build_skeleton"]
