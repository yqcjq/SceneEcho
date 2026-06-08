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
) -> dict:
    """Transcode to H.264 baseline + AAC + yuv420p + target canvas/fps.

    Default 1080x1920 (9:16). Uses 'pad' to letterbox sources of other aspect ratios.
    Returns the resulting media info.
    """
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
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
    log.info("ffmpeg_normalize", src=str(src_path), dst=str(dst))
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
