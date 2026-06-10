"""1B · Skeleton inference from Phase1AReport → TemplateIR.skeleton[] +
caption_style_palette.

Reads the identified scenes / captions / stickers / zoom / masks / transitions
already accumulated in ``Phase1AReport`` and projects them into the
"reusable style recipe" view of TemplateIR — a list of ``Slot`` objects with
role / duration range / material_req / per-slot ``StyleRule``, plus a model-
level ``caption_style_palette`` referenced by every Slot via
``style.caption_palette_idx``.

decisions/010 changes:
- Slots no longer carry an inline ``CaptionStyle``; they carry an integer
  ``caption_palette_idx`` into ``TemplateIR.caption_style_palette``. The
  palette is built here (1B) by clustering ``Phase1ACaptionEvent.style``
  values across the whole sample. P1 uses a coarse signature
  (``_palette_key``) — same font / size / color / layout / semantic_purpose
  collapse into one palette entry; finer cosine clustering is a P2 follow-up.

- ``Slot.caption_function`` is filled by majority vote over
  ``Phase1AReport.caption_functions`` entries whose ``caption_idx``-pointed
  CaptionEvent overlaps this Slot's time range — captions_anim has been
  removed (decisions/011), caption_function carries the function classification
  including animation type.

Design (PLAN 1510):
- 3 roles by position threshold (D5: skeleton "discovered" not "preset"):
    start ratio < 0.30           → 开头
    start ratio > 0.70           → 结尾
    everything else              → 主体
  Scenes that share a role merge into one Slot whose duration spans them.
- Per-slot ``StyleRule`` aggregates:
    caption_palette_idx: index of the dominant caption (by confidence) in
        the model-level palette
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
- One VisionEvent per Slot inference + one per palette assembly so the
  workbench right pane lights up the TemplateIR.skeleton[N] field +
  caption_style_palette as each slot / palette entry is built.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.event_bus import get_event_bus
from app.ir.phase1a_report import (
    BRollSegment,
    Phase1ACaptionEvent,
    Phase1ACaptionFunctionEvent,
    Phase1AReport,
)
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


def _captions_in(seg: _Segment, report: Phase1AReport) -> list[Phase1ACaptionEvent]:
    """Caption entries overlapping the segment's time range."""
    return [c for c in report.captions if c.end > seg.start and c.start < seg.end]


def _stickers_in(seg: _Segment, report: Phase1AReport) -> list[StickerEvent]:
    """Sticker events overlapping the segment, with timing **renormalized to
    slot-local [0,1]**.

    Phase 1A's ``Phase1AStickerDetection.sticker.start/end`` are sample-clock
    seconds (where the sticker appeared in the original sample video). At the
    template (TemplateIR) layer we want a coordinate system that survives
    being applied to *any* user material — slot-local fractional time does
    that. Phase 2's ``apply/style.py`` converts [0,1] → segment-local seconds
    so the renderer never sees fractions.

    PLAN 2 verification 7: stickers must appear at the modelled timestamps
    when applied; before this remap, the absolute sample-clock time was
    being subtracted from the ProjectIR timeline (different coordinate
    systems), and stickers showed up at the wrong moments.
    """
    out: list[StickerEvent] = []
    slot_span = max(0.04, seg.end - seg.start)
    for det in report.stickers:
        s = det.sticker
        if s.end > seg.start and s.start < seg.end:
            rel_start = max(0.0, (s.start - seg.start) / slot_span)
            rel_end = min(1.0, (s.end - seg.start) / slot_span)
            if rel_end <= rel_start:
                rel_end = min(1.0, rel_start + 0.01)
            out.append(
                s.model_copy(
                    update={
                        "start": round(rel_start, 4),
                        "end": round(rel_end, 4),
                    }
                )
            )
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
                ZoomKeyframe(
                    relative_time=round(max(0.0, min(1.0, t)), 4),
                    scale=kf.scale,
                    dx=kf.dx,
                    dy=kf.dy,
                )
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


def _b_roll_in(seg: _Segment, report: Phase1AReport) -> list[BRollSegment]:
    """BRollSegment entries whose scene_idx falls inside this segment."""
    indices = set(seg.scene_indices)
    return [b for b in report.b_roll_segments if b.scene_idx in indices]


def _infer_material_req(
    captions: list,
    stickers: list,
    has_zoom: bool,
    has_mask: bool,
    b_rolls: list[BRollSegment],
) -> str:
    """PLAN 1510 + decisions/010 决策 6 mapping.

    Priority order (most specific wins):
    1. Any non-人物主导 BRollSegment in this slot → ``AI生成画面``
       (covers 全屏 B-roll / 画中画 / 侧栏). Phase 5 generate_broll later
       reads ``Phase1AReport.b_roll_segments`` to know which slots to fill.
    2. Captions present → ``人物口播``.
    3. Visual extras (sticker / zoom / mask) without captions → ``B-roll/包装``.
    4. Nothing distinctive → ``待定``.
    """
    if any(b.kind != "人物主导" for b in b_rolls):
        return "AI生成画面"
    if captions:
        return "人物口播"
    if stickers or has_zoom or has_mask:
        return "B-roll/包装"
    return "待定"


# ----- caption palette clustering ---------------------------------------------


def _palette_key(style: CaptionStyle) -> tuple:
    """Coarse signature for clustering captions into one palette entry.

    Same font / size / color / stroke / layout / semantic_purpose collapse
    into one palette element. This is the P1 simple version — finer cosine
    clustering on shadow / background / padding (the new visual fields) is
    a P2 follow-up. Keeping it simple now means the palette stays ≤ 5
    entries on typical口播 fixtures, which is what the model-level dedup
    contract demands.
    """
    return (
        style.font_family,
        int(style.size),
        style.color,
        style.stroke_color,
        int(style.stroke_width),
        style.layout,
        int(style.max_chars_per_line),
        style.semantic_purpose,
    )


def _build_palette(
    captions: list[Phase1ACaptionEvent],
) -> tuple[list[CaptionStyle], list[int]]:
    """Cluster caption styles into a palette; return (palette, caption_to_idx).

    The returned ``caption_to_idx[k]`` is the palette index for
    ``captions[k]``. Palette element ``i`` adopts the highest-confidence
    raw style amongst its cluster (so visual fields like shadow / padding
    that are still uncertain in some captions get the most reliable values).
    """
    palette: list[CaptionStyle] = []
    key_to_idx: dict[tuple, int] = {}
    cap_to_idx: list[int] = []
    # Cluster bookkeeping for "highest-confidence wins" within a cluster.
    cluster_best_conf: list[float] = []
    for cap in captions:
        key = _palette_key(cap.style)
        if key in key_to_idx:
            idx = key_to_idx[key]
            cap_to_idx.append(idx)
            if cap.confidence > cluster_best_conf[idx]:
                # Adopt the more-confident raw style + carry placeholder
                # fields onto the canonical palette entry.
                palette[idx] = cap.style.model_copy(
                    update={
                        "placeholder_text": list(cap.placeholder_text or []),
                        "length_constraint": dict(cap.length_constraint or {}),
                        "semantic_purpose": cap.semantic_purpose or "regular",
                    }
                )
                cluster_best_conf[idx] = cap.confidence
            continue
        idx = len(palette)
        key_to_idx[key] = idx
        palette.append(
            cap.style.model_copy(
                update={
                    "placeholder_text": list(cap.placeholder_text or []),
                    "length_constraint": dict(cap.length_constraint or {}),
                    "semantic_purpose": cap.semantic_purpose or "regular",
                }
            )
        )
        cluster_best_conf.append(cap.confidence)
        cap_to_idx.append(idx)
    return palette, cap_to_idx


def _dominant_caption_palette_idx(
    seg_captions: list[Phase1ACaptionEvent],
    cap_to_idx: list[int],
    captions_all: list[Phase1ACaptionEvent],
) -> int | None:
    """Pick the palette idx of the highest-confidence caption in this slot.

    ``seg_captions`` is the subset of ``captions_all`` whose time range
    overlaps the slot. We resolve them back to their original index in
    ``captions_all`` (via identity) so we can read the palette idx from
    the global ``cap_to_idx`` map. Returns None when the slot has no
    captions.
    """
    if not seg_captions:
        return None
    # Identity map: the same Phase1ACaptionEvent objects appear in both
    # lists — Python list.index by identity / equality is fine since
    # captions_all is the de-facto source of truth.
    best = max(seg_captions, key=lambda c: (c.confidence, -c.start))
    try:
        global_idx = captions_all.index(best)
    except ValueError:
        return None
    if 0 <= global_idx < len(cap_to_idx):
        return cap_to_idx[global_idx]
    return None


def _vote_caption_function(
    seg_captions: list[Phase1ACaptionEvent],
    captions_all: list[Phase1ACaptionEvent],
    fn_events: list[Phase1ACaptionFunctionEvent],
) -> str:
    """Majority vote ``Slot.caption_function`` from caption_functions overlapping this slot.

    For each caption in this slot, look up its Phase1ACaptionFunctionEvent
    by ``caption_idx``; tally the ``function`` strings; return the most
    common (defaults to "regular" when the slot has no functions tied to it).
    """
    if not seg_captions or not fn_events:
        return "regular"
    fn_by_caption: dict[int, str] = {ev.caption_idx: ev.function for ev in fn_events}
    tally: dict[str, int] = {}
    for cap in seg_captions:
        try:
            global_idx = captions_all.index(cap)
        except ValueError:
            continue
        fn = fn_by_caption.get(global_idx)
        if fn:
            tally[fn] = tally.get(fn, 0) + 1
    if not tally:
        return "regular"
    return max(tally.items(), key=lambda kv: kv[1])[0]


def _build_slot(
    seg: _Segment,
    report: Phase1AReport,
    *,
    cap_to_idx: list[int],
    prev_seg_last_scene: int | None,
    next_seg_first_scene: int | None,
) -> Slot:
    """Assemble a Slot from one segment + the global Phase1AReport fields."""
    captions = _captions_in(seg, report)
    stickers = _stickers_in(seg, report)
    zoom = _zoom_keyframes_for(seg, report)
    mask_kind, mask_params = _dominant_mask(seg, report)
    b_rolls = _b_roll_in(seg, report)
    # Has-zoom signal: any non-trivial curve (anything other than a single
    # scale=1.0 keyframe at t=0).
    has_real_zoom = any(abs(kf.scale - 1.0) > 0.02 for kf in zoom)

    palette_idx = _dominant_caption_palette_idx(captions, cap_to_idx, report.captions)
    style = StyleRule(
        caption_palette_idx=palette_idx,
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

    caption_function = _vote_caption_function(
        captions, report.captions, report.caption_functions
    )

    span = max(0.04, seg.end - seg.start)
    return Slot(
        role=seg.role,
        duration={
            "min": round(span * 0.7, 3),
            "nominal": round(span, 3),
            "max": round(span * 1.5, 3),
        },
        material_req=_infer_material_req(
            captions, stickers, has_real_zoom, mask_kind is not None, b_rolls
        ),
        style=style,
        caption_function=caption_function,
    )


async def build_skeleton(
    report: Phase1AReport,
    total_duration: float,
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[list[Slot], list[CaptionStyle], list[VisionEvent]]:
    """Project Phase1AReport → list[Slot] + caption_style_palette + per-slot VisionEvents.

    Empty reports / zero-duration videos return ([], [], []) — the pipeline
    layer treats this as a degraded skeleton and proceeds with an empty
    TemplateIR shell so downstream tagging / sanity check still run.

    The palette is built first (one event per palette entry, op="append"),
    then slots reference into it. Palette can be empty even when slots
    exist (no captions detected); palette idx None on every slot in that
    case.
    """
    bus = get_event_bus()
    palette, cap_to_idx = _build_palette(report.captions)

    # Emit one event per palette entry so the workbench right-pane shows
    # the palette assembling. Mirrors how stickers / scenes append.
    palette_events: list[VisionEvent] = []
    for i, entry in enumerate(palette):
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=STAGE,
            semantic_label=(
                f"字幕样式调色板 #{i} · {entry.semantic_purpose} · "
                f"{entry.font_family} {entry.size}px · {entry.color}"
            ),
            reasoning=(
                f"按 (font / size / color / stroke / layout / semantic_purpose) 签名聚类，"
                f"采纳簇内最高置信度字幕的视觉字段。簇键 = {_palette_key(entry)}"
            ),
            confidence=0.9,
            ir_target=IRTarget(
                ir_type="TemplateIR", path="caption_style_palette", op="append"
            ),
            ir_value=entry.model_dump(mode="json"),
            parent_event_id=parent_event_id,
            duration_ms=0,
        )
        await bus.publish(task_id, ev)
        palette_events.append(ev)

    segments = _group_scenes(report, total_duration)
    if not segments:
        return [], palette, palette_events

    slots: list[Slot] = []
    events: list[VisionEvent] = list(palette_events)
    for i, seg in enumerate(segments):
        prev_last = segments[i - 1].scene_indices[-1] if i > 0 else None
        next_first = segments[i + 1].scene_indices[0] if i + 1 < len(segments) else None
        slot = _build_slot(
            seg,
            report,
            cap_to_idx=cap_to_idx,
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
                f"位置阈值发现：start_ratio={(seg.start / total_duration):.2f} → {slot.role}；"
                f"覆盖 scenes {seg.scene_indices}；"
                f"字幕 {len(_captions_in(seg, report))} 条 (palette_idx={slot.style.caption_palette_idx}) / "
                f"贴纸 {len(_stickers_in(seg, report))} 枚 / "
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
    return slots, palette, events


__all__ = ["STAGE", "build_skeleton"]
