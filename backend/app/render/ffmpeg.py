"""FFmpeg / ffprobe wrappers. Uses imageio-ffmpeg's bundled binaries as fallback."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

from app.logging import get_logger

log = get_logger(__name__)


def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_bin() -> str:
    # imageio-ffmpeg doesn't bundle ffprobe; require system install or fallback to ffmpeg.
    return shutil.which("ffprobe") or "ffprobe"


def get_media_info(path: str | Path) -> dict:
    """Run ffprobe and return parsed format+streams info."""
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def normalize(
    src_path: str | Path,
    dst_path: str | Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    pad_mode: str = "black",
) -> dict:
    """Transcode to H.264 baseline + AAC + yuv420p + target canvas/fps.

    Default 1080x1920 (9:16). For aspect-ratio-mismatched sources two
    letterbox modes are supported:

    - ``pad_mode="black"`` (default, sample-extract path): fast pad with
      solid black bars. Cheap, predictable, used by template extraction
      where blurred backgrounds would corrupt the recognized stage.
    - ``pad_mode="blur"`` (Phase 2 user uploads, PLAN 1657): blurred
      copy of the source fills the bars; foreground stays centred.
      Aesthetic match for ProjectIR rendering when the user uploads a
      16:9 clip into a 9:16 canvas.

    Returns the resulting media info.
    """
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if pad_mode == "blur":
        # Background path: scale-cover the canvas (so the bars are filled
        # by source pixels), then heavy boxblur to erase identifiable
        # detail. Foreground path: scale-decrease to keep aspect, then
        # overlay centred. setsar=1 smooths out non-square pixel sources
        # before the overlay so Chromium / x264 don't complain about
        # sar mismatch. The leading [0:v] tags the video stream
        # explicitly so split has a defined source.
        vf = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:1,setsar=1[bg2];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"setsar=1[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,fps={fps}"
        )
    else:
        # Canonical FFmpeg idiom for "fit-and-letterbox to W x H":
        #   1. scale preserves source aspect ratio (decrease = fit inside the box)
        #   2. pad fills remaining area with black
        #   3. fps locks frame rate
        # Avoids expression strings with single-quote escaping that subprocess + Windows
        # don't pass through cleanly.
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={fps}"
        )
    if pad_mode == "blur":
        # filter_complex needs -filter_complex (not -vf) when using split.
        cmd = [
            ffmpeg_bin(),
            "-y",
            "-i",
            str(src_path),
            "-filter_complex",
            vf,
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-movflags",
            "+faststart",
            str(dst),
        ]
    else:
        cmd = [
            ffmpeg_bin(),
            "-y",
            "-i",
            str(src_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-movflags",
            "+faststart",
            str(dst),
        ]
    log.info("ffmpeg_normalize", src=str(src_path), dst=str(dst), pad_mode=pad_mode)
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return get_media_info(dst)


def extract_thumbnail(src_path: str | Path, dst_path: str | Path, at: float = 0.0) -> Path:
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-ss",
        f"{at:.2f}",
        "-i",
        str(src_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return dst


def image_to_video(
    src_image: str | Path,
    dst_path: str | Path,
    *,
    duration_sec: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> Path:
    """Loop a still image into an H.264 mp4 of ``duration_sec`` seconds.

    Phase 5 (ISS-028) AIGC backend uses an image-generation API rather than
    a video-generation one, so ``agent/aigc.py`` produces a PNG/JPG and
    converts it here to mp4 — keeping the ``aigc_broll_path`` consumer
    contract (renderer's OffthreadVideo + preflight) unchanged.

    The slot's existing zoom_keyframes provide motion at render time
    (renderer's ZoomLayer), so this conversion intentionally outputs a
    *static* loop — adding a Ken Burns / zoompan filter here would compose
    with the slot's zoom and double-animate.

    Letterbox via ``force_original_aspect_ratio=decrease + pad`` mirrors
    :func:`normalize` for visual consistency between user material and
    AIGC segments. ``-tune stillimage`` keeps the encoder cheap.
    """
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps}"
    )
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-i",
        str(src_image),
        "-t",
        f"{max(0.04, float(duration_sec)):.3f}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-tune",
        "stillimage",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return dst


def extract_audio(src_path: str | Path, dst_path: str | Path) -> Path:
    """Extract the audio track of a media file as 44.1k stereo WAV.

    Used by Phase 2's BGM mixer to feed the voice track into FFmpeg's
    ``sidechaincompress`` filter. WAV is cheap to read and the size is
    fine for short user material (10-20s ≈ 4-8 MB).
    """
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i",
        str(src_path),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return dst


def mix_bgm(
    voice_track: str | Path,
    bgm_path: str | Path,
    output: str | Path,
    *,
    duck_db: float = 12.0,
    is_instrumental: bool = True,
) -> Path:
    """Sidechain-compress BGM against the voice track and write the mix.

    PLAN 1611: ``sidechaincompress`` filter with the voice track as the
    sidechain input — whenever the voice exceeds the threshold, the BGM
    is attenuated by ``duck_db`` dB. ``is_instrumental=False`` (BGM with
    vocals) ducks more aggressively (lower threshold, longer release)
    because the lyric overlap is the worst case for口播 clarity.

    The output is BGM-only, ducked relative to the voice. The renderer
    plays this alongside the unmuted user-material video so the voice
    is audible without double-mixing.
    """
    dst = Path(output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Threshold / ratio / attack / release / makeup tuned for口播-over-BGM.
    # 默认人声 RMS ≈ -18 dBFS, BGM ≈ -22 dBFS. threshold=0.05 (~-26 dBFS)
    # makes the compressor trigger on normal speech bursts.
    threshold = 0.03 if not is_instrumental else 0.05
    ratio = 16 if not is_instrumental else 8
    release = 400 if not is_instrumental else 250
    duck_amount = max(0.0, duck_db)
    # Filter graph:
    #   [bgm][voice] sidechaincompress=...    -> ducked BGM
    #   then volume drop to bring overall level under voice.
    sidechain = (
        f"[0:a]aresample=44100,asetpts=PTS-STARTPTS[bgm0];"
        f"[1:a]aresample=44100,asetpts=PTS-STARTPTS[voice0];"
        f"[bgm0][voice0]sidechaincompress="
        f"threshold={threshold}:ratio={ratio}:attack=5:release={release}"
        f":makeup=1:level_sc=1[duck];"
        f"[duck]volume=-{duck_amount}dB[out]"
    )
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i",
        str(bgm_path),
        "-i",
        str(voice_track),
        "-filter_complex",
        sidechain,
        "-map",
        "[out]",
        "-c:a",
        "aac",
        "-ar",
        "44100",
        "-b:a",
        "192k",
        str(dst),
    ]
    log.info("ffmpeg_mix_bgm", bgm=str(bgm_path), voice=str(voice_track), dst=str(dst))
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return dst


def compose_segments(
    segments: list[dict],
    src_video: str | Path,
    output: str | Path,
    *,
    fps: int = 30,
) -> Path:
    """Cut + concat PlacedSegments from a single source video.

    Each segment dict has ``src_timerange=(start, end)`` and ``speed``.
    Per PLAN 1612 this composes the bare video (no captions, no stickers,
    no zoom — those layers live in the renderer). Used by Phase 2's
    fallback non-Remotion render path (when the renderer service is down)
    and by Phase 3's pre-render stitch.

    For Phase 2 the renderer's Remotion pipeline does the segment stitching
    itself, so this is a defensive utility. Kept here so the apply pipeline
    can produce a "raw cut" mp4 for debugging before sending to Remotion.
    """
    dst = Path(output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not segments:
        raise ValueError("compose_segments: empty segments")

    # Build a filter_complex that selects each src_timerange + speed-adjusts
    # via setpts/atempo, then concats them.
    parts: list[str] = []
    concat_inputs: list[str] = []
    for i, seg in enumerate(segments):
        src_start, src_end = seg["src_timerange"]
        speed = float(seg.get("speed", 1.0))
        atempo = max(0.5, min(2.0, speed))
        setpts = 1.0 / atempo
        parts.append(
            f"[0:v]trim=start={src_start}:end={src_end},"
            f"setpts={setpts}*(PTS-STARTPTS)[v{i}];"
            f"[0:a]atrim=start={src_start}:end={src_end},"
            f"atempo={atempo},asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[v{i}][a{i}]")
    concat = (
        "".join(p + ";" for p in parts)
        + f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=1[v][a]"
    )
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i",
        str(src_video),
        "-filter_complex",
        concat,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    log.info("ffmpeg_compose_segments", count=len(segments), dst=str(dst))
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return dst
