"""1B · Extract pipeline — DAG orchestrator → TemplateIR → KB.

This is the **composition** layer. It does NOT reimplement any 1A subcap;
it just sequences and accumulates results. PLAN.md 1511 explicitly bans
"and now we rewrite 1A here" — this module imports each detector and
treats it as a black box.

The DAG (PLAN 1516):

    normalize ─▶ scenes ─┬─▶ frame_sampler ─┬─▶ captions ─▶ captions_anim
                         │                  ├─▶ stickers
                         │                  ├─▶ zoom_direction ─▶ zoom_curve
                         │                  ├─▶ transitions
                         │                  ├─▶ masks
                         │                  └─▶ color_lut
                         └─▶ extract_bgm (audio independent of frames)

    after all of the above:
        skeleton → caption_function (per-caption) → tagging → sanity_check
        → save_template → KB

Concurrency:
- Top of DAG: ``Phase1AContext.scenes()`` + ``Phase1AContext.frames()`` are
  lazy-cached; the first dependant triggers them once.
- Same-layer fan-out uses ``asyncio.gather``. Per PLAN 1532, any subcap
  raising marks its branch ``degraded`` and emits a warning event but the
  rest keeps running.

Degradation contract (PLAN 1507):
- Every "subcap unit" wrapped in :func:`_safe` — exceptions are caught,
  a severity=warning VisionEvent is published, the field is left empty,
  and ``TemplateIR.degraded[<field_path>]`` records the failure reason.
- Pipeline never raises after this wrapper; the worst case is an empty
  TemplateIR shell with every field flagged degraded.

Event volume target (PLAN 1562): ≥ 30 events for a typical run. With
~3 scenes × (cap+stkr+zoom_dir+trans+mask) ≈ 15 entity events + scene
cuts + per-slot inferences + tagging + sanity check, this lands.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, TypeVar

from app import tasks_store
from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.extract.skeleton import build_skeleton
from app.ir.phase1a_report import Phase1AReport
from app.ir.template import TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.kb import store as kb_store
from app.logging import get_logger
from app.render import ffmpeg as ffx

STAGE = "1B.pipeline"
log = get_logger(__name__)

T = TypeVar("T")


# Mapping from subcap label → TemplateIR-relative dotted path. The single
# source of truth for ``TemplateIR.degraded`` keys: ``_safe`` translates
# every ``field_key`` through this table before writing to ``ir.degraded``,
# so the UI banner can navigate from a degraded entry to the affected IR
# field with a single lodash get/set. ``*`` is a glob over slots — the
# field applies to every Slot in skeleton, not a specific one. Phase 1A
# field_keys (e.g. ``zoom_curves.0`` / ``captions.3.verified_anim_in``)
# strip their per-index suffix and resolve to the same skeleton path
# because the UI cares which IR field is partial, not which scene index.
SUBCAP_TO_IR_PATH: dict[str, str] = {
    "scenes": "skeleton",
    "frames": "skeleton",
    "captions": "skeleton.*.style.caption",
    "stickers": "skeleton.*.style.stickers",
    "zoom_directions": "skeleton.*.style.visual.zoom_keyframes",
    "zoom_curves": "skeleton.*.style.visual.zoom_keyframes",
    "transitions": "skeleton.*.style.transition_in",
    "masks": "skeleton.*.style.visual.mask",
    "color": "skeleton.*.style.visual.color_lut",
    "audio": "audio",
    "skeleton": "skeleton",
    "tags": "tags",
    "sanity_check": "sanity_check",
    "duration": "global_style.duration_sec",
    # Per-caption sub-fields fold under the same path.
    "captions.verified_anim_in": "skeleton.*.style.caption",
    "captions.function": "skeleton.*.style.caption",
}


def _ir_path_for(field_key: str) -> str:
    """Translate ``_safe``'s field_key to a TemplateIR-relative path.

    Phase 1A subcap keys are typed against Phase1AReport (e.g. ``captions``,
    ``zoom_curves.3``); we project them through ``SUBCAP_TO_IR_PATH`` so
    every entry in ``TemplateIR.degraded`` speaks the same dialect. Unknown
    keys pass through unchanged — better to surface a literal label than
    swallow it silently.
    """
    if field_key in SUBCAP_TO_IR_PATH:
        return SUBCAP_TO_IR_PATH[field_key]
    # Strip trailing ``.<index>`` (zoom_curves.0) or ``.<idx>.<sub>``
    # (captions.3.verified_anim_in) and look up the prefix family.
    head = field_key.split(".", 1)[0]
    if head in SUBCAP_TO_IR_PATH:
        return SUBCAP_TO_IR_PATH[head]
    if "." in field_key:
        # captions.3.verified_anim_in → captions.verified_anim_in
        parts = field_key.split(".")
        if len(parts) >= 3:
            collapsed = f"{parts[0]}.{parts[-1]}"
            if collapsed in SUBCAP_TO_IR_PATH:
                return SUBCAP_TO_IR_PATH[collapsed]
    return field_key


# ---------------------------------------------------------------------------
# Degradation wrapper
# ---------------------------------------------------------------------------


@dataclass
class _SubcapResult:
    """Outcome of a single subcap invocation under :func:`_safe`."""

    value: Any  # the subcap's structured return (or None on failure)
    ok: bool
    error: str | None = None


async def _safe(
    label: str,
    field_key: str,
    coro: Awaitable[T],
    *,
    task_id: str,
    degraded: dict[str, str],
) -> _SubcapResult:
    """Run a subcap coroutine; catch + record any exception without raising.

    ``field_key`` is the dotted path within TemplateIR we'd want to flag if
    this subcap fails — written to ``ir.degraded[field_key]`` by the
    caller. The warning event is published *here* so all degradation
    events show up in the same stage / source for the workbench filter.
    """
    started = time.perf_counter()
    try:
        value = await coro
        return _SubcapResult(value=value, ok=True)
    except Exception as e:  # noqa: BLE001
        log.warning("1b.subcap_failed", subcap=label, error=str(e))
        # Translate the subcap-level field_key to a TemplateIR-relative
        # path so every entry in ir.degraded speaks one dialect and the
        # UI banner can navigate to the affected field.
        degraded[_ir_path_for(field_key)] = f"{type(e).__name__}: {e}"
        await get_event_bus().publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="system",
                stage=f"{STAGE}.degraded",
                semantic_label=f"[degraded] {label} 失败",
                reasoning=(
                    f"子能力 {label} 抛出异常 {type(e).__name__}: {str(e)[:200]}。"
                    f"该字段标 degraded=true，pipeline 继续。耗时 "
                    f"{int((time.perf_counter() - started) * 1000)}ms。"
                ),
                confidence=0.0,
                severity="warning",
                duration_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        return _SubcapResult(value=None, ok=False, error=str(e))


# ---------------------------------------------------------------------------
# Phase 1A fan-out → Phase1AReport
# ---------------------------------------------------------------------------


async def _run_phase1a(
    ctx: Phase1AContext, degraded: dict[str, str]
) -> Phase1AReport:
    """Fan out every 1A subcap concurrently; assemble Phase1AReport.

    scenes/frames are themselves wrapped in ``_safe`` — they hit ffmpeg /
    PySceneDetect / disk and DO fail in real environments (missing
    [extract] extras, corrupt mp4, disk full). A failed scenes call
    short-circuits the whole 1A layer to empty results + degraded marker
    rather than raising into ``extract_template``'s top level.

    The cheap "top-of-DAG" subcaps (captions / stickers / zoom_direction /
    transitions / masks / color_lut) all depend on frames. They run in
    one ``asyncio.gather`` so frames are computed once (by the first
    awaiter) and the rest of the call latency stacks instead of summing.
    Audio is independent — fires in the same gather to overlap with the
    visual subcaps. captions_anim and zoom_curve are dependent and fire
    only after their parent resolves.
    """
    from app.extract.audio import extract_bgm
    from app.extract.captions import detect_captions
    from app.extract.captions_anim import verify_caption_anim
    from app.extract.color import classify_color_lut
    from app.extract.masks import detect_masks
    from app.extract.motion import estimate_zoom_curve, judge_zoom_direction
    from app.extract.stickers import detect_stickers
    from app.extract.transitions import classify_transitions

    task_id = ctx.task_id

    # Materialize scenes + frames once before fan-out. Both wrapped in
    # _safe so a missing dep or corrupt file degrades to "no scenes" +
    # warning event, rather than propagating up.
    scenes_res = await _safe(
        "scenes", "scenes", ctx.scenes(), task_id=task_id, degraded=degraded
    )
    if not scenes_res.ok or not scenes_res.value:
        # Without scenes there's nothing downstream can do. Emit an empty
        # report; the skeleton/tagging/sanity stages will produce a degraded
        # TemplateIR shell.
        return Phase1AReport()
    scenes = scenes_res.value
    frames_res = await _safe(
        "frames", "frames", ctx.frames(), task_id=task_id, degraded=degraded
    )
    if not frames_res.ok:
        return Phase1AReport(scenes=[s.to_report_entry() for s in scenes])
    # frames cached on ctx so the per-subcap awaits hit cache instantly.

    (
        cap_res,
        stk_res,
        zoom_dir_res,
        trans_res,
        masks_res,
        color_res,
        audio_res,
    ) = await asyncio.gather(
        _safe("captions", "captions", detect_captions(ctx), task_id=task_id, degraded=degraded),
        _safe("stickers", "stickers", detect_stickers(ctx), task_id=task_id, degraded=degraded),
        _safe(
            "zoom_direction",
            "zoom_directions",
            judge_zoom_direction(ctx),
            task_id=task_id,
            degraded=degraded,
        ),
        _safe(
            "transitions",
            "transitions",
            classify_transitions(ctx),
            task_id=task_id,
            degraded=degraded,
        ),
        _safe("masks", "masks", detect_masks(ctx), task_id=task_id, degraded=degraded),
        _safe("color_lut", "color", classify_color_lut(ctx), task_id=task_id, degraded=degraded),
        _safe("audio", "audio", extract_bgm(ctx), task_id=task_id, degraded=degraded),
    )

    captions = cap_res.value[0] if cap_res.ok and cap_res.value else []
    stickers = stk_res.value[0] if stk_res.ok and stk_res.value else []
    zoom_dirs = zoom_dir_res.value[0] if zoom_dir_res.ok and zoom_dir_res.value else {}
    transitions = trans_res.value[0] if trans_res.ok and trans_res.value else {}
    masks = masks_res.value[0] if masks_res.ok and masks_res.value else {}
    color = color_res.value[0] if color_res.ok and color_res.value else None
    audio = audio_res.value[0] if audio_res.ok and audio_res.value else None

    # Dependent: zoom curve only for non-stable scenes (PLAN 1518).
    zoom_curve_tasks: list[Awaitable[Any]] = []
    curve_scene_idx: list[int] = []
    for sc in scenes:
        d = zoom_dirs.get(sc.idx)
        if d is not None and getattr(d, "direction", "稳定") != "稳定":
            zoom_curve_tasks.append(
                _safe(
                    f"zoom_curve.{sc.idx}",
                    f"zoom_curves.{sc.idx}",
                    estimate_zoom_curve(ctx, sc),
                    task_id=task_id,
                    degraded=degraded,
                )
            )
            curve_scene_idx.append(sc.idx)
    curve_results = (
        await asyncio.gather(*zoom_curve_tasks) if zoom_curve_tasks else []
    )
    zoom_curves: dict = {}
    for sidx, res in zip(curve_scene_idx, curve_results, strict=False):
        if res.ok and res.value:
            kfs, _ = res.value
            zoom_curves[str(sidx)] = kfs

    # Dependent: captions_anim verifies each detected caption.
    cached_frames = await ctx.frames()
    anim_tasks = []
    for idx, cap in enumerate(captions):
        anchor = (
            min(cached_frames, key=lambda f: abs(f.ts - cap.start))
            if cached_frames
            else None
        )
        anchor_url = (
            f"/data/{anchor.rel_path.lstrip('/')}" if anchor is not None else None
        )
        anim_tasks.append(
            _safe(
                f"captions_anim.{idx}",
                f"captions.{idx}.verified_anim_in",
                verify_caption_anim(
                    cap,
                    ctx.normalized_path,
                    task_id=task_id,
                    caption_idx=idx,
                    anchor_frame_url=anchor_url,
                ),
                task_id=task_id,
                degraded=degraded,
            )
        )
    if anim_tasks:
        anim_results = await asyncio.gather(*anim_tasks)
        for idx, res in enumerate(anim_results):
            if res.ok and res.value:
                detail, _ = res.value
                captions[idx].verified_anim_in = detail.verified_anim_in
                captions[idx].stagger_ms = detail.stagger_ms

    # Dependent: classify_caption_function (per caption, parallel).
    from app.understand.vision import classify_caption_function

    fn_tasks = []
    for idx, cap in enumerate(captions):
        anchor = next(
            (f for f in cached_frames if cap.start <= f.ts <= cap.end), None
        )
        fn_tasks.append(
            _safe(
                f"caption_function.{idx}",
                f"captions.{idx}.function",
                classify_caption_function(
                    cap,
                    anchor,
                    task_id=task_id,
                    caption_idx=idx,
                    parent_event_id=None,
                ),
                task_id=task_id,
                degraded=degraded,
            )
        )
    if fn_tasks:
        fn_results = await asyncio.gather(*fn_tasks)
        for idx, res in enumerate(fn_results):
            if res.ok and res.value:
                fn_result, _ = res.value
                captions[idx].function = fn_result.function

    from app.extract.color import to_color_report

    # Phase1AReport stores all per-scene maps with string keys (JSON-friendly,
    # matches the lodash path "zoom_curves.0" the workbench uses). Subcaps
    # produce dict[int, ...] so we coerce here at the seam.
    return Phase1AReport(
        scenes=[s.to_report_entry() for s in scenes],
        captions=captions,
        stickers=stickers,
        zoom_directions={str(k): v.direction for k, v in zoom_dirs.items()},
        zoom_curves=zoom_curves,
        transitions={str(k): v.transition for k, v in transitions.items()},
        masks={str(k): v for k, v in masks.items()},
        color=to_color_report(color) if color is not None else None,
        audio=audio,
    )


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


async def extract_template(
    sample_id: str,
    task_id: str,
    *,
    name: str | None = None,
) -> TemplateIR:
    """End-to-end: build Phase1AReport → assemble TemplateIR → KB.save.

    Caller owns the task lifecycle (status / progress / close_task). This
    function emits a ``1B.pipeline.done`` event on success **only** —
    save_template failure raises so the caller marks the task failed
    rather than the workbench misleadingly showing "completed" while the
    KB row is missing.

    The pipeline never raises for *subcap* failures — those degrade
    silently via ``_safe``. The only paths that raise are:
    - a programmer-level bug in this function body (not a subcap);
    - ``kb_store.save_template`` failing (disk full, sqlite locked).
    """
    settings = get_settings()
    bus = get_event_bus()
    started = time.perf_counter()
    degraded: dict[str, str] = {}

    # Deterministic id so re-extract on the same sample overwrites the
    # existing KB row (INSERT OR REPLACE). A timestamp-suffixed id would
    # leak ghost templates every time the user re-runs extraction; the
    # KB would balloon and the "回放工作台事件流" link would always
    # point at the *first* extract, not the latest.
    template_id = f"tpl_{sample_id}"

    # Locate the input mp4 (normalized preferred). Probe duration via
    # _safe so a missing file / corrupt header degrades to duration=0
    # (skeleton then produces 0 slots, sanity flags the issue).
    sample_dir = settings.data_root / "samples" / sample_id
    normalized = sample_dir / "normalized.mp4"
    if not normalized.exists():
        normalized = sample_dir / "source.mp4"

    async def _probe_duration() -> float:
        info = ffx.get_media_info(normalized)
        return float(info.get("format", {}).get("duration", 0.0))

    probe_res = await _safe(
        "probe_duration", "duration", _probe_duration(), task_id=task_id, degraded=degraded
    )
    duration = probe_res.value if probe_res.ok and probe_res.value is not None else 0.0

    ctx = Phase1AContext(
        sample_id=sample_id, normalized_path=normalized, task_id=task_id
    )

    await bus.publish(
        task_id,
        VisionEvent(
            task_id=task_id,
            source="system",
            stage=STAGE,
            semantic_label=f"开始抽取模板 · sample={sample_id} · 时长 {duration:.1f}s",
            reasoning=(
                f"normalized.mp4 = {normalized.name}；template_id = {template_id}；"
                "进入 Phase 1A 子能力 fan-out。"
            ),
            confidence=1.0,
            duration_ms=0,
        ),
    )
    tasks_store.update_task(task_id, status="running", stage=STAGE, progress=0.1)

    # ---------------- stage 1: Phase 1A fan-out -----------------------
    report = await _run_phase1a(ctx, degraded)
    tasks_store.update_task(task_id, stage="1B.skeleton", progress=0.55)

    # ---------------- stage 2: skeleton -------------------------------
    skel_res = await _safe(
        "skeleton",
        "skeleton",
        build_skeleton(report, duration, task_id=task_id),
        task_id=task_id,
        degraded=degraded,
    )
    slots = skel_res.value[0] if skel_res.ok and skel_res.value else []

    ir = TemplateIR(
        id=template_id,
        name=name or f"模板·{sample_id}",
        source_sample=sample_id,
        skeleton=slots,
        audio=report.audio,
        global_style={
            "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "duration_sec": round(duration, 3),
        },
        degraded=degraded,
    )

    # ---------------- stage 3: tagging --------------------------------
    tasks_store.update_task(task_id, stage="1B.tagging", progress=0.7)
    from app.kb.tagging import suggest_tags

    # frames may have failed earlier — _safe in _run_phase1a logged the
    # warning + cached []. Re-await ctx.frames() (cache-hit, no work)
    # rather than reaching into the private _frames attribute.
    try:
        frames_for_summary = await ctx.frames()
    except Exception:  # noqa: BLE001
        frames_for_summary = []
    tag_res = await _safe(
        "tagging",
        "tags",
        suggest_tags(ir, frames_for_summary, task_id=task_id),
        task_id=task_id,
        degraded=degraded,
    )
    if tag_res.ok and tag_res.value:
        tags, _ = tag_res.value
        ir.tags = tags

    # ---------------- stage 4: sanity check ---------------------------
    tasks_store.update_task(task_id, stage="1B.sanity_check", progress=0.85)
    from app.kb.sanity import sanity_check

    sanity_res = await _safe(
        "sanity_check",
        "sanity_check",
        sanity_check(ir, frames_for_summary, task_id=task_id),
        task_id=task_id,
        degraded=degraded,
    )
    if sanity_res.ok and sanity_res.value:
        sanity, _ = sanity_res.value
        ir.sanity_check = sanity.model_dump(mode="json")

    # ---------------- stage 5: save to KB -----------------------------
    tasks_store.update_task(task_id, stage="1B.save_template", progress=0.95)
    thumb_rel: str | None = f"samples/{sample_id}/thumbnail.jpg"
    if not (settings.data_root / thumb_rel).exists():
        thumb_rel = None
    ir.degraded = degraded  # refresh after all stages

    # save_template raising is a hard failure — the workbench must not
    # show "done" when the KB row is missing. Re-raise after emitting
    # the error event; the caller (BackgroundTask) marks the task failed.
    try:
        kb_store.save_template(
            ir, thumbnail_path=thumb_rel, last_extract_task_id=task_id
        )
    except Exception as e:
        log.error("1b.save_template_failed", error=str(e))
        await bus.publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="system",
                stage=f"{STAGE}.save_failed",
                semantic_label="保存模板失败",
                reasoning=(
                    f"kb_store.save_template 抛出 {type(e).__name__}: {str(e)[:200]}。"
                    "整个 extract 视为失败，不发 done 事件。"
                ),
                confidence=0.0,
                severity="error",
                duration_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    await bus.publish(
        task_id,
        VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.done",
            semantic_label=(
                f"模板抽取完成 · slots={len(slots)} · degraded {len(degraded)} 项 · "
                f"耗时 {elapsed_ms / 1000:.1f}s"
            ),
            reasoning=(
                f"template_id={template_id}；degraded keys: "
                f"{list(degraded.keys()) or 'none'}。"
            ),
            confidence=1.0,
            ir_target=IRTarget(ir_type="TemplateIR", path="id"),
            ir_value=template_id,
            duration_ms=elapsed_ms,
        ),
    )
    return ir


__all__ = ["STAGE", "extract_template"]
