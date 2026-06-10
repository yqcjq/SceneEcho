"""2.pipeline · DAG orchestrator for ★MVP apply (PLAN 1609).

    normalize ─▶ asr ─▶ map ─▶ gaps ─▶ fill ─▶ style ─▶ save project.json
                  │              │       │       │
                  └ ledger       └ gaps  └ outcomes      └ captions + bgm

Concurrency: this is mostly **sequential** by data dependency — each step
needs the prior step's full output. The internal LLM calls per-Unit /
per-Gap inside ``style`` / ``fill`` could fan out with ``asyncio.gather``
later, but for MVP-scale (~3-5 Units / ≤1 Gap) the serial latency is
small enough that single-threaded ordering keeps the event stream readable.

Degradation contract (mirrors 1B's _safe pattern):
- Every stage wrapped in ``_safe(label, ir_path, coro)``;
- Failures land in ``ProjectIR.degraded[<ir_path>]`` + emit warning event;
- Pipeline never raises for *stage* failures — only ``save_project`` /
  unrecoverable disk-write paths propagate (caller marks task failed).

The translation table ``STAGE_TO_IR_PATH`` keeps ``ProjectIR.degraded``
keys in the ProjectIR dialect (mirror of TemplateIR's
``SUBCAP_TO_IR_PATH`` from 1B).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from app import tasks_store
from app.apply.fill import fill_gaps
from app.apply.gaps import detect_gaps
from app.apply.mapping import map_short_to_template
from app.apply.style import apply_style
from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.ledger import TranscriptLedger
from app.ir.project import Caption, Gap, PlacedSegment, ProjectIR, Section
from app.ir.template import TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.kb import store as kb_store
from app.logging import get_logger
from app.render import ffmpeg as ffx
from app.understand.asr import transcribe

STAGE = "2.pipeline"
log = get_logger(__name__)

T = TypeVar("T")


# Stage → ProjectIR-relative dotted path. Mirrors 1B's SUBCAP_TO_IR_PATH —
# the single source of truth for ProjectIR.degraded keys so the UI banner
# can navigate from a degraded entry straight to the affected field.
STAGE_TO_IR_PATH: dict[str, str] = {
    "probe_duration": "canvas.duration_sec",
    "asr": "ledger",
    "mapping": "sections.0.segments",
    "gaps": "sections.0.gaps",
    "fill": "sections.0.gaps",
    "style": "captions",
    "bgm": "bgm_track",
    "bgm_mix": "bgm_track",
    "save_project": "project_id",
}


def _ir_path_for(field_key: str) -> str:
    """Resolve a stage's degraded key into a ProjectIR-relative path."""
    if field_key in STAGE_TO_IR_PATH:
        return STAGE_TO_IR_PATH[field_key]
    head = field_key.split(".", 1)[0]
    if head in STAGE_TO_IR_PATH:
        return STAGE_TO_IR_PATH[head]
    return field_key


# ---------------------------------------------------------------------------
# Degradation wrapper
# ---------------------------------------------------------------------------


@dataclass
class _StageResult:
    value: Any
    ok: bool
    error: str | None = None


async def _safe(
    label: str,
    field_key: str,
    coro: Awaitable[T],
    *,
    task_id: str,
    degraded: dict[str, str],
) -> _StageResult:
    started = time.perf_counter()
    bus = get_event_bus()
    try:
        value = await coro
        return _StageResult(value=value, ok=True)
    except Exception as e:  # noqa: BLE001
        log.warning("2.stage_failed", stage=label, error=str(e))
        degraded[_ir_path_for(field_key)] = f"{type(e).__name__}: {e}"
        await bus.publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="system",
                stage=f"{STAGE}.degraded",
                semantic_label=f"[degraded] {label} 失败",
                reasoning=(
                    f"阶段 {label} 抛出 {type(e).__name__}: {str(e)[:200]}。"
                    f"已标记 ProjectIR.degraded[{_ir_path_for(field_key)}]；pipeline 继续。"
                    f"耗时 {int((time.perf_counter() - started) * 1000)}ms。"
                ),
                confidence=0.0,
                severity="warning",
                duration_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        return _StageResult(value=None, ok=False, error=str(e))


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


async def apply_short(
    project_id: str,
    template_id: str,
    *,
    task_id: str,
    allow_aigc_broll: bool = False,
) -> ProjectIR:
    """End-to-end MVP apply for a short user material.

    Looks up the user material at ``projects/{id}/normalized.mp4`` (falls
    back to ``user_material.mp4`` if normalization didn't run). The
    template is fetched from KB; missing template → raises (caller
    marks task failed, since "apply without template" is a programmer
    error, not a degradation).

    Returns the assembled ProjectIR. Caller is responsible for the task
    lifecycle (status / progress / close_task) and for kicking off
    rendering afterward.
    """
    settings = get_settings()
    bus = get_event_bus()
    started = time.perf_counter()
    degraded: dict[str, str] = {}

    project_dir = settings.data_root / "projects" / project_id
    normalized = project_dir / "normalized.mp4"
    if not normalized.exists():
        normalized = project_dir / "user_material.mp4"
    if not normalized.exists():
        raise FileNotFoundError(
            f"project {project_id}: neither normalized.mp4 nor user_material.mp4 on disk"
        )

    user_material_rel = str(normalized.relative_to(settings.data_root)).replace("\\", "/")

    # Fetch template — missing means programmer error, raise.
    row = kb_store.get_template(template_id)
    if not row or not row.get("ir"):
        raise LookupError(f"template {template_id} not found in KB")
    template = TemplateIR.model_validate(row["ir"])

    await bus.publish(
        task_id,
        VisionEvent(
            task_id=task_id,
            source="system",
            stage=STAGE,
            semantic_label=(
                f"开始应用 · project={project_id} · template={template_id} · "
                f"骨架 {len(template.skeleton)} 段"
            ),
            reasoning=(
                f"normalized.mp4 = {normalized.name}；template.audio.has_bgm="
                f"{getattr(template.audio, 'has_bgm', False)}；进入 apply DAG。"
            ),
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="project_id"),
            ir_value=project_id,
            duration_ms=0,
        ),
    )
    tasks_store.update_task(task_id, status="running", stage=STAGE, progress=0.05)

    # --------- Stage 1: probe duration ----------
    async def _probe() -> float:
        info = ffx.get_media_info(normalized)
        return float(info.get("format", {}).get("duration", 0.0))

    probe_res = await _safe(
        "probe_duration", "probe_duration", _probe(), task_id=task_id, degraded=degraded
    )
    duration = probe_res.value if probe_res.ok and probe_res.value else 0.0
    tasks_store.update_task(task_id, stage="2.asr", progress=0.10)

    # --------- Stage 2: ASR ----------
    # Prefer the cached ledger written by recommend_templates_endpoint — the
    # user's flow is recommend → apply on the same project with the same
    # normalized.mp4, so re-running ASR (especially the GLM provider with a
    # ~2s round trip) is pure waste. Falls through to live transcribe() when
    # the cache is absent or fails to parse.
    ledger: TranscriptLedger | None = None
    transcript_path = project_dir / "transcript.json"
    if transcript_path.exists():
        try:
            cached = TranscriptLedger.model_validate_json(
                transcript_path.read_text(encoding="utf-8")
            )
            if cached.units:
                ledger = cached
                avg_lp = sum(u.avg_logprob for u in cached.units) / len(cached.units)
                await bus.publish(
                    task_id,
                    VisionEvent(
                        task_id=task_id,
                        source="system",
                        stage=f"{STAGE}.asr_reuse",
                        semantic_label=f"复用推荐阶段 ledger · {len(cached.units)} 个 Unit",
                        reasoning=(
                            f"projects/{project_id}/transcript.json 存在且非空,跳过 ASR 重跑;"
                            f" avg_logprob={avg_lp:.2f},language={cached.language}。"
                        ),
                        confidence=1.0,
                        ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.segments"),
                    ),
                )
        except Exception as e:  # noqa: BLE001
            log.warning("apply.transcript_reuse_failed", error=str(e))

    if ledger is None:
        asr_res = await _safe(
            "asr",
            "asr",
            transcribe(normalized, task_id=task_id),
            task_id=task_id,
            degraded=degraded,
        )
        if asr_res.ok and asr_res.value:
            ledger, _ = asr_res.value
        else:
            ledger = TranscriptLedger(units=[], language="zh", media_path=user_material_rel)
    tasks_store.update_task(task_id, stage="2.map", progress=0.35)

    # --------- Stage 3: mapping ----------
    map_res = await _safe(
        "mapping",
        "mapping",
        map_short_to_template(ledger, template, task_id=task_id),
        task_id=task_id,
        degraded=degraded,
    )
    segments: list[PlacedSegment] = []
    if map_res.ok and map_res.value:
        segments, _ = map_res.value
    tasks_store.update_task(task_id, stage="2.gaps", progress=0.55)

    # --------- Stage 4: gaps ----------
    gaps_res = await _safe(
        "gaps",
        "gaps",
        detect_gaps(segments, template, task_id=task_id),
        task_id=task_id,
        degraded=degraded,
    )
    gaps: list[Gap] = []
    if gaps_res.ok and gaps_res.value:
        gaps, _ = gaps_res.value
    tasks_store.update_task(task_id, stage="2.fill", progress=0.65)

    # --------- Stage 5: fill ----------
    fill_segments: list[PlacedSegment] = []
    fill_captions: list[Caption] = []
    if gaps:
        fill_res = await _safe(
            "fill",
            "fill",
            fill_gaps(
                gaps,
                template,
                segments,
                ledger,
                task_id=task_id,
                allow_aigc_broll=allow_aigc_broll,
            ),
            task_id=task_id,
            degraded=degraded,
        )
        if fill_res.ok and fill_res.value:
            outcomes, _ = fill_res.value
            for o in outcomes:
                if o.segment is not None:
                    fill_segments.append(o.segment)
                if o.caption is not None:
                    fill_captions.append(o.caption)
                # Pipeline owns the Gap.fill_result write so fill.py stays
                # input-immutable. Per outcome.gap_idx → original gap.
                if 0 <= o.gap_idx < len(gaps):
                    gaps[o.gap_idx].fill_result = o.text or o.reasoning

    # Merge real + fill segments and re-sort by timeline_start so style.py
    # / renderer see one monotonic sequence.
    all_segments = sorted(
        [*segments, *fill_segments], key=lambda s: s.timeline_start
    )
    tasks_store.update_task(task_id, stage="2.style", progress=0.75)

    # --------- Stage 6: style + caption + BGM ----------
    style_res = await _safe(
        "style",
        "style",
        apply_style(all_segments, template, ledger, task_id=task_id),
        task_id=task_id,
        degraded=degraded,
    )
    styled_segments: list[PlacedSegment] = all_segments
    captions: list[Caption] = list(fill_captions)
    bgm_track: str | None = None
    if style_res.ok and style_res.value:
        styled_segments, real_captions, bgm_track, _ = style_res.value
        # Merge: real Unit-driven captions + the fill-text captions from
        # text_fill outcomes. Sort by start so renderer's Caption list is
        # in display order.
        captions = sorted([*real_captions, *fill_captions], key=lambda c: c.start)

    # --------- Stage 6.5: BGM ducking mix ----------
    # ffmpeg sidechaincompress against the extracted voice → bgm_ducked.aac.
    # On failure the bgm_track stays as the raw selection (renderer plays
    # un-ducked BGM) so the project is still renderable.
    if bgm_track:
        tasks_store.update_task(task_id, stage="2.bgm_mix", progress=0.85)
        mix_res = await _safe(
            "bgm_mix",
            "bgm_mix",
            _mix_bgm_for_project(
                bgm_track,
                normalized,
                project_dir,
                template=template,
                task_id=task_id,
            ),
            task_id=task_id,
            degraded=degraded,
        )
        if mix_res.ok and mix_res.value:
            bgm_track = mix_res.value

    tasks_store.update_task(task_id, stage="2.save", progress=0.95)

    # --------- Stage 7: assemble + save ----------
    canvas = template.global_style.get("canvas") or {"width": 1080, "height": 1920, "fps": 30}
    section = Section(
        topic=template.tags.scene if template.tags else "",
        template_id=template_id,
        segments=styled_segments,
        gaps=gaps,
    )
    ir = ProjectIR(
        project_id=project_id,
        user_material=user_material_rel,
        sections=[section],
        captions=captions,
        canvas=canvas,
        allow_aigc_broll=allow_aigc_broll,
        bgm_track=bgm_track,
        degraded=degraded,
    )
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "project.json").write_text(
            ir.model_dump_json(indent=2), encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        log.error("2.save_project_failed", project_id=project_id, error=str(e))
        await bus.publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="system",
                stage=f"{STAGE}.save_failed",
                semantic_label="保存 ProjectIR 失败",
                reasoning=f"{type(e).__name__}: {str(e)[:200]}",
                confidence=0.0,
                severity="error",
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
                f"应用完成 · {len(styled_segments)} 段 · {len(captions)} 字幕 · "
                f"BGM={'有' if bgm_track else '无'} · degraded {len(degraded)} 项 · "
                f"耗时 {elapsed_ms / 1000:.1f}s · 时长 {duration:.1f}s"
            ),
            reasoning=(
                f"project_id={project_id}；degraded keys: "
                f"{list(degraded.keys()) or 'none'}；version={ir.version}。"
            ),
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="project_id"),
            ir_value=project_id,
            duration_ms=elapsed_ms,
        ),
    )
    return ir


async def _mix_bgm_for_project(
    bgm_track_rel: str,
    normalized: Path,
    project_dir: Path,
    *,
    template: TemplateIR,
    task_id: str,
) -> str:
    """Extract the user-material voice and duck the chosen BGM against it.

    Renders ``projects/{id}/bgm_ducked.aac`` (BGM-only, sidechain-ducked
    by the voice). Returns the DATA_ROOT-relative POSIX path; the apply
    pipeline writes that into ``ProjectIR.bgm_track`` so the renderer's
    ``<Audio>`` track plays the ducked mix while the user material's own
    audio (the voice) keeps playing on top — same as ARCHITECTURE 链路 F.
    Raises on ffmpeg failure; the caller's _safe wraps and degrades.
    """
    settings = get_settings()
    bgm_abs = settings.resolve(bgm_track_rel)
    if not bgm_abs.exists():
        raise FileNotFoundError(f"bgm_track {bgm_track_rel} not on disk")
    voice_path = project_dir / "voice.wav"
    output = project_dir / "bgm_ducked.aac"
    is_instrumental = bool(template.audio.is_instrumental) if template.audio else True

    def _do_mix() -> Path:
        ffx.extract_audio(normalized, voice_path)
        ffx.mix_bgm(voice_path, bgm_abs, output, is_instrumental=is_instrumental)
        return output

    out = await asyncio.to_thread(_do_mix)
    rel = str(out.relative_to(settings.data_root)).replace("\\", "/")
    bus = get_event_bus()
    await bus.publish(
        task_id,
        VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.bgm_mix",
            semantic_label=f"BGM ducking 完成 · {Path(rel).name}",
            reasoning=(
                f"voice 提取自 {normalized.name}；BGM={bgm_track_rel}；"
                f"is_instrumental={is_instrumental}；输出 {rel}。"
            ),
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="bgm_track"),
            ir_value=rel,
        ),
    )
    return rel


__all__ = ["STAGE", "apply_short"]
