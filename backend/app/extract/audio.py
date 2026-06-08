"""1A-A1 · BGM extraction (Demucs) + acoustic features (librosa).

Each meaningful audio judgement (has_bgm / is_instrumental / bpm /
mood_tag) emits its own VisionEvent so the workbench shows the audio
pipeline as a separate lane in the gantt view. Demucs and librosa are
lazy-imported so the unit tests don't pay the model-download tax. All
events write into ``Phase1AReport.audio`` (sub-fields).
"""

from __future__ import annotations

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.ir.template import AudioStyle
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger

STAGE = "1A.audio"
log = get_logger(__name__)


async def extract_bgm(
    ctx: Phase1AContext,
    *,
    save_stem: bool = True,
    parent_event_id: str | None = None,
) -> tuple[AudioStyle, list[VisionEvent]]:
    """Run Demucs + librosa; emit per-judgement VisionEvents.

    On dependency failure, returns ``AudioStyle()`` defaults + a warning
    event so the rest of the pipeline can continue without audio info.
    """
    bus = get_event_bus()
    settings = get_settings()
    try:
        import librosa  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as e:
        log.warning("audio.dep_missing", error=str(e))
        return await _fallback(ctx.task_id, parent_event_id, str(e))

    sr = 22050
    try:
        y, sr_loaded = librosa.load(str(ctx.normalized_path), sr=sr, mono=True)
    except Exception as e:  # noqa: BLE001
        log.warning("audio.load_failed", error=str(e))
        return await _fallback(ctx.task_id, parent_event_id, str(e))

    # 1) Energy curve — per-second RMS (truncate to integer second count).
    rms_full = librosa.feature.rms(y=y).flatten()
    hop_length = 512
    seconds = max(1, int(len(y) / sr_loaded))
    hops_per_sec = max(1, int(sr_loaded / hop_length))
    energy_curve: list[float] = []
    for i in range(seconds):
        chunk = rms_full[i * hops_per_sec : (i + 1) * hops_per_sec]
        if len(chunk):
            energy_curve.append(round(float(chunk.mean()), 5))
    overall_energy = float(np.mean(rms_full)) if len(rms_full) else 0.0

    # 2) Demucs source separation (vocals vs accompaniment).
    has_bgm = False
    is_instrumental = True
    bgm_rel_path: str | None = None
    try:
        bgm_rel_path, has_bgm, is_instrumental = await _demucs_separate(
            ctx, save_stem=save_stem
        )
    except Exception as e:  # noqa: BLE001
        log.warning("audio.demucs_failed", error=str(e))

    bgm_evt = VisionEvent(
        task_id=ctx.task_id,
        source="audio",
        stage=STAGE,
        semantic_label=f"BGM 有/无：{'有' if has_bgm else '无'}",
        reasoning=(
            "Demucs htdemucs 分离后比对 vocals 与 accompaniment stem 能量；"
            "accompaniment RMS > 静音阈值视为有 BGM。"
        ),
        confidence=0.95,
        ir_target=IRTarget(ir_type="Phase1AReport", path="audio", field="has_bgm"),
        ir_value=has_bgm,
        parent_event_id=parent_event_id,
        duration_ms=0,
    )
    await bus.publish(ctx.task_id, bgm_evt)

    # 3) BPM estimation.
    try:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr_loaded)
        bpm: float | None = float(tempo) if tempo else None
    except Exception as e:  # noqa: BLE001
        log.warning("audio.bpm_failed", error=str(e))
        bpm = None

    bpm_evt = VisionEvent(
        task_id=ctx.task_id,
        source="audio",
        stage=STAGE,
        semantic_label=f"BPM：{bpm:.1f}" if bpm else "BPM：未检测",
        reasoning="librosa beat_track on mono mix.",
        confidence=0.85 if bpm else 0.3,
        ir_target=IRTarget(ir_type="Phase1AReport", path="audio", field="bpm"),
        ir_value=bpm,
        parent_event_id=bgm_evt.event_id,
        duration_ms=0,
    )
    await bus.publish(ctx.task_id, bpm_evt)

    # 4) Mood tag from BPM + energy heuristic.
    mood_tag = _mood_from_features(bpm or 0.0, overall_energy)
    mood_evt = VisionEvent(
        task_id=ctx.task_id,
        source="audio",
        stage=STAGE,
        semantic_label=f"情绪标签：{mood_tag}",
        reasoning=(
            f"BPM {bpm or 0:.1f} + overall RMS {overall_energy:.4f} → 规则映射 {mood_tag}。"
        ),
        confidence=0.7,
        ir_target=IRTarget(ir_type="Phase1AReport", path="audio", field="mood_tag"),
        ir_value=mood_tag,
        parent_event_id=bgm_evt.event_id,
        duration_ms=0,
    )
    await bus.publish(ctx.task_id, mood_evt)

    style = AudioStyle(
        has_bgm=has_bgm,
        is_instrumental=is_instrumental,
        bpm=bpm,
        energy_curve=energy_curve,
        mood_tag=mood_tag,
        bgm_path=bgm_rel_path if settings.bgm_strategy == "original" else None,
        bgm_features={"hop_length": hop_length, "sr": sr_loaded}
        if settings.bgm_strategy == "features"
        else None,
    )
    return style, [bgm_evt, bpm_evt, mood_evt]


async def _demucs_separate(
    ctx: Phase1AContext, *, save_stem: bool
) -> tuple[str | None, bool, bool]:
    """Run Demucs and return (stem rel path, has_bgm, is_instrumental).

    Returns (None, False, True) when Demucs is missing or fails.
    """
    try:
        import torch  # type: ignore[import-not-found]
        from demucs.apply import apply_model  # type: ignore[import-not-found]
        from demucs.audio import save_audio  # type: ignore[import-not-found]
        from demucs.pretrained import get_model  # type: ignore[import-not-found]
        from demucs.separate import load_track  # type: ignore[import-not-found]
    except ImportError as e:
        log.warning("audio.demucs_missing", error=str(e))
        return None, False, True

    settings = get_settings()
    model = get_model("htdemucs")
    model.cpu().eval()
    wav = load_track(ctx.normalized_path, model.audio_channels, model.samplerate)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / ref.std()
    with torch.no_grad():
        sources = apply_model(model, wav[None], split=True, overlap=0.25, progress=False)[0]
    sources = sources * ref.std() + ref.mean()

    by_name = dict(zip(model.sources, sources, strict=False))
    vocals = by_name.get("vocals")
    accompaniment = sum(s for k, s in by_name.items() if k != "vocals")  # type: ignore[arg-type]
    if accompaniment is None or vocals is None:
        return None, False, True

    accomp_rms = float(accompaniment.pow(2).mean().sqrt().item())
    vocals_rms = float(vocals.pow(2).mean().sqrt().item())
    has_bgm = accomp_rms > 1e-3
    is_instrumental = vocals_rms < accomp_rms * 0.10

    rel: str | None = None
    if save_stem and has_bgm:
        out_dir = ctx.normalized_path.parent / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "bgm_stem.wav"
        save_audio(accompaniment, str(out_path), samplerate=model.samplerate)
        try:
            rel = str(out_path.relative_to(settings.data_root)).replace("\\", "/")
        except ValueError:
            rel = str(out_path)
    return rel, has_bgm, is_instrumental


def _mood_from_features(bpm: float, energy: float) -> str:
    if bpm <= 0 or energy < 0.005:
        return "舒缓"
    if bpm >= 130 and energy >= 0.05:
        return "欢快"
    if bpm >= 130:
        return "紧张"
    if bpm >= 95:
        return "稳健"
    return "舒缓"


async def _fallback(
    task_id: str, parent_event_id: str | None, reason: str
) -> tuple[AudioStyle, list[VisionEvent]]:
    bus = get_event_bus()
    style = AudioStyle()
    ev = VisionEvent(
        task_id=task_id,
        source="audio",
        stage=STAGE,
        semantic_label="[fallback] 音频管线缺依赖",
        reasoning=f"librosa / Demucs 不可用：{reason}。返回默认 AudioStyle。",
        confidence=0.0,
        parent_event_id=parent_event_id,
        duration_ms=0,
        severity="warning",
    )
    await bus.publish(task_id, ev)
    return style, [ev]
