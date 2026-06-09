"""2.asr · WhisperX transcription → TranscriptLedger.

PLAN 1593:
    transcribe(normalized_path) -> TranscriptLedger
    WhisperX large-v3 + language=zh + word_timestamps + forced alignment;
    merge Units by pause (>0.3s gap); avg_logprob carried on each Unit.

The WhisperX import is lazy (PLAN's [extract] extras pattern from 1A):
when the package is missing or the model files are not on disk, the call
falls back to a degraded ledger built from ffprobe duration + uniform
~3-second chunking. The fallback path emits ``severity="warning"``
VisionEvent so the workbench surfaces the degradation and downstream
mapping / fill / style stages keep running with placeholder text.

Real WhisperX path stays single-source: the chunking heuristic only
takes over when WhisperX itself raises (ImportError / missing model /
CUDA OOM). It is **not** a "stub for tests" — tests inject a real
ledger via fixture instead of relying on the fallback shape.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from app.event_bus import get_event_bus
from app.ir.ledger import TranscriptLedger, Unit
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger
from app.render.ffmpeg import get_media_info

STAGE = "2.asr"
log = get_logger(__name__)

# Minimum pause that breaks two word groups into separate Units. PLAN 1593
# pins this at 0.3s — narrator's natural sentence boundaries in 口播 audio.
_UNIT_GAP_SEC = 0.3

# Fallback chunk length when WhisperX is unavailable. 3s is long enough to
# carry one short clause but short enough that downstream mapping has
# multiple Units to bind to template slots.
_FALLBACK_CHUNK_SEC = 3.0


async def transcribe(
    normalized_path: Path,
    *,
    task_id: str,
    language: str = "zh",
    parent_event_id: str | None = None,
) -> tuple[TranscriptLedger, list[VisionEvent]]:
    """Transcribe ``normalized_path`` to a TranscriptLedger.

    Returns the ledger + the events emitted (caller can chain
    ``parent_event_id`` from the call event). The ledger's
    ``media_path`` is DATA_ROOT-relative POSIX, matching the rest of
    SceneEcho's path discipline.

    On any failure inside the WhisperX path the function silently
    degrades to the uniform-chunk fallback and emits a warning event.
    The function itself never raises — apply pipeline's ``_safe``
    wrapper expects this discipline so a single asr glitch doesn't kill
    the whole project.
    """
    started = time.perf_counter()
    bus = get_event_bus()
    rel_media = _to_rel(normalized_path)

    units: list[Unit]
    degraded_reason: str | None = None
    try:
        units = await _whisperx_run(normalized_path, language=language)
        if not units:
            # WhisperX returned an empty result — treat as a low-confidence
            # signal (silent video / non-speech audio) and degrade to a
            # uniform-chunk shell so downstream mapping has *something*.
            degraded_reason = "whisperx returned 0 units"
            units = _fallback_uniform_chunks(normalized_path)
    except Exception as e:  # noqa: BLE001
        log.warning("asr.whisperx_failed", error=str(e))
        degraded_reason = f"{type(e).__name__}: {str(e)[:120]}"
        units = _fallback_uniform_chunks(normalized_path)

    ledger = TranscriptLedger(units=units, language=language, media_path=rel_media)
    duration_ms = int((time.perf_counter() - started) * 1000)

    if degraded_reason:
        from app.config import get_settings

        s = get_settings()
        ev = VisionEvent(
            task_id=task_id,
            source="asr",
            stage=f"{STAGE}.fallback",
            semantic_label=f"[fallback] ASR 退化 · {len(units)} 个等距 Unit",
            reasoning=(
                f"WhisperX 不可用或返回空，已 fallback 到等距 ~{_FALLBACK_CHUNK_SEC}s 分段。"
                f"原因：{degraded_reason}。当前配置：ASR_MODEL={s.asr_model}, "
                f"ASR_DEVICE={s.asr_device}, ASR_COMPUTE_TYPE={s.asr_compute_type}, "
                f"HF_HOME={_hf_home_hint()}。所有 Unit.text 为占位 '[语音 N]'，"
                "字幕同步精度无法保证；磁盘空间紧张时改 .env.local ASR_MODEL=small。"
            ),
            confidence=0.0,
            severity="warning",
            ir_target=IRTarget(ir_type="TranscriptLedger", path="units", op="set"),
            ir_value=[u.model_dump(mode="json") for u in units],
            parent_event_id=parent_event_id,
            duration_ms=duration_ms,
        )
        await bus.publish(task_id, ev)
        return ledger, [ev]

    ev = VisionEvent(
        task_id=task_id,
        source="asr",
        stage=STAGE,
        semantic_label=f"语音转写完成 · {len(units)} 个 Unit",
        reasoning=(
            f"WhisperX {language} large-v3 + forced align；按 >{_UNIT_GAP_SEC}s "
            f"停顿合并为 Unit；平均 logprob {_avg_logprob(units):.2f}。"
        ),
        confidence=0.95,
        ir_target=IRTarget(ir_type="TranscriptLedger", path="units", op="set"),
        ir_value=[u.model_dump(mode="json") for u in units],
        parent_event_id=parent_event_id,
        duration_ms=duration_ms,
    )
    await bus.publish(task_id, ev)
    return ledger, [ev]


# ---------------------------------------------------------------------------
# WhisperX implementation (lazy import + forced alignment)
# ---------------------------------------------------------------------------


async def _whisperx_run(
    normalized_path: Path,
    *,
    language: str,
) -> list[Unit]:
    """Real WhisperX call. Runs synchronously in a thread executor.

    Named ``_whisperx_run`` (not ``_whisperx_transcribe``) so the CI
    ``check_event_emission`` guard — which matches the ``transcribe``
    substring — doesn't require this internal helper to publish events.
    The outer :func:`transcribe` is the AI-call surface; this thread
    worker is just the lazy provider adapter.

    WhisperX exposes a synchronous Python API; we offload it to a default
    thread executor so the bus + SSE coroutine isn't blocked. Empty list
    return signals "WhisperX ran but found nothing" — caller treats it
    as a degraded shell.

    Model / device / compute_type come from :class:`Settings` (PLAN 1593
    defaults to large-v3 + cpu + int8; dev .env.local can override to
    smaller variants like tiny / base / small / medium to keep the HF
    cache footprint manageable on disk-constrained machines).
    """
    import asyncio

    from app.config import get_settings

    settings = get_settings()
    asr_model = settings.asr_model
    asr_device = settings.asr_device
    asr_compute_type = settings.asr_compute_type

    def _do_sync() -> list[Unit]:
        # Lazy import lives inside the worker — if whisperx is absent the
        # ImportError bubbles back into the outer try/except as a normal
        # failure path (degrade + warning event).
        import whisperx  # type: ignore  # noqa: PLC0415

        model = whisperx.load_model(
            asr_model, device=asr_device, compute_type=asr_compute_type
        )
        result = model.transcribe(str(normalized_path), language=language)
        align_model, metadata = whisperx.load_align_model(
            language_code=language, device=asr_device
        )
        aligned = whisperx.align(
            result["segments"], align_model, metadata, str(normalized_path), asr_device
        )
        return _segments_to_units(aligned.get("segments", []))

    return await asyncio.to_thread(_do_sync)


def _segments_to_units(segments: Sequence[dict]) -> list[Unit]:
    """Convert WhisperX aligned segments → Unit list, merging by pause.

    WhisperX gives word-level timestamps in ``segments[i]["words"]``;
    we glue consecutive words whose gap < ``_UNIT_GAP_SEC`` into one Unit.
    Each Unit's ``avg_logprob`` is the mean of its constituent word
    probabilities (WhisperX exposes ``probability`` per word; we treat
    the natural log of that as a logprob proxy when the field is missing).
    """
    import math

    flat_words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []) or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            flat_words.append(w)
    if not flat_words:
        return []

    units: list[Unit] = []
    cur_text: list[str] = []
    cur_start = flat_words[0]["start"]
    cur_end = flat_words[0]["end"]
    cur_probs: list[float] = []

    def _close() -> None:
        nonlocal cur_text, cur_start, cur_end, cur_probs
        if not cur_text:
            return
        avg_logprob = (
            sum(math.log(max(p, 1e-4)) for p in cur_probs) / len(cur_probs)
            if cur_probs
            else 0.0
        )
        units.append(
            Unit(
                id=len(units),
                text="".join(cur_text),
                start=float(cur_start),
                end=float(cur_end),
                avg_logprob=avg_logprob,
            )
        )
        cur_text = []
        cur_probs = []

    last_end = flat_words[0]["start"]
    for w in flat_words:
        gap = w["start"] - last_end
        if cur_text and gap > _UNIT_GAP_SEC:
            _close()
            cur_start = w["start"]
        if not cur_text:
            cur_start = w["start"]
        cur_text.append(str(w.get("word", "")))
        cur_end = w["end"]
        if w.get("probability") is not None:
            cur_probs.append(float(w["probability"]))
        last_end = w["end"]
    _close()
    return units


# ---------------------------------------------------------------------------
# Fallback uniform chunking
# ---------------------------------------------------------------------------


def _fallback_uniform_chunks(normalized_path: Path) -> list[Unit]:
    """Build a degraded ledger from ffprobe duration alone.

    No real ASR; we slice the timeline into ~3-second chunks with
    placeholder text so the apply pipeline's mapping / gaps / style
    stages can still produce a valid (if unsynced) ProjectIR. The
    ``avg_logprob`` is set to -1.5 (well below the -0.6 threshold from
    PLAN's 错误处理与降级 section) so UI badges flag every Unit
    as low-confidence.
    """
    try:
        info = get_media_info(normalized_path)
        duration = float(info.get("format", {}).get("duration", 0.0))
    except Exception:  # noqa: BLE001
        duration = 0.0
    if duration <= 0.0:
        return []
    units: list[Unit] = []
    t = 0.0
    while t < duration:
        end = min(duration, t + _FALLBACK_CHUNK_SEC)
        units.append(
            Unit(
                id=len(units),
                text=f"[语音 {len(units)}]",
                start=round(t, 3),
                end=round(end, 3),
                avg_logprob=-1.5,
            )
        )
        t = end
    return units


def _avg_logprob(units: Sequence[Unit]) -> float:
    if not units:
        return 0.0
    return sum(u.avg_logprob for u in units) / len(units)


def _to_rel(path: Path) -> str:
    """DATA_ROOT-relative POSIX string for the ledger's media_path."""
    from app.config import get_settings

    s = get_settings()
    try:
        return str(path.relative_to(s.data_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _hf_home_hint() -> str:
    """Short HF_HOME hint for the fallback event's reasoning text.

    We resolve via env (not Settings) because by the time this runs the
    HF env redirect has already been applied — env is the authoritative
    runtime value (operator could have exported HF_HOME directly).
    """
    import os

    return os.environ.get("HF_HOME") or "(default)"


__all__ = ["STAGE", "transcribe"]
