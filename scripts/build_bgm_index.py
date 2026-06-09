"""Build ``data/system/bgm_pool/bgm_index.json`` from the BGM files on disk.

PLAN 1578 expects ``bgm_pool/`` to contain ≥ 5 royalty-free tracks plus a
``bgm_index.json`` whose ``tracks[].bpm`` + ``tracks[].mood_tag`` feed
``apply/style._bgm_features``'s nearest-neighbour BGM selection.

Schema (mirrors ``fonts_index.json``'s ``schema_version`` convention)::

    {
      "schema_version": 1,
      "tracks": [
        {
          "name": "human-readable label, defaults to the filename stem",
          "path": "system/bgm_pool/<filename>",   # DATA_ROOT-relative POSIX
          "bpm": 96.3,                             # librosa.beat.beat_track
          "mood_tag": "neutral",                   # manual: calm/upbeat/...
          "duration_sec": 132.4                    # for debug; not consumed
        },
        ...
      ]
    }

Run as::

    cd backend && .venv/Scripts/python.exe ../scripts/build_bgm_index.py

The script is idempotent: existing ``mood_tag`` values in the on-disk
index are preserved when the file already exists (so re-running after a
manual mood edit doesn't clobber it). BPM is re-extracted each run since
the file content is the source of truth for tempo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def _detect_bpm(path: Path) -> tuple[float, float]:
    """Return ``(bpm, duration_sec)`` via librosa. ~3-5s per track on CPU.

    Tempo extraction reads the first 60 seconds (more than enough for a
    stable beat estimate on royalty-free BGM); the duration field reads
    the file header separately so it reflects the true track length.
    """
    import librosa  # type: ignore  # noqa: PLC0415
    import numpy as np  # type: ignore  # noqa: PLC0415

    y, sr = librosa.load(str(path), sr=None, mono=True, duration=60.0)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    # librosa ≥ 0.10 returns a 1-d ndarray (shape (1,)); older versions
    # returned a 0-d scalar. np.atleast_1d normalises both into a 1-d
    # array so the index-then-float coercion works either way.
    bpm = float(np.atleast_1d(tempo)[0])
    duration = float(librosa.get_duration(path=str(path)))
    return round(bpm, 1), round(duration, 1)


def main() -> int:
    s = get_settings()
    pool = s.data_root / "system" / "bgm_pool"
    if not pool.is_dir():
        print(f"error: {pool} does not exist", file=sys.stderr)
        return 1
    index_path = pool / "bgm_index.json"

    # Preserve any operator-edited mood_tag values across re-runs.
    existing_mood: dict[str, str] = {}
    if index_path.exists():
        try:
            old = json.loads(index_path.read_text(encoding="utf-8"))
            for t in old.get("tracks", []):
                existing_mood[t["path"]] = t.get("mood_tag", "neutral")
        except Exception as e:  # noqa: BLE001
            print(f"warn: failed to read existing index ({e}); regenerating", file=sys.stderr)

    audio_files = sorted(
        p for p in pool.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )
    if not audio_files:
        print(f"error: no audio files under {pool}", file=sys.stderr)
        return 1

    tracks: list[dict] = []
    for path in audio_files:
        rel = f"system/bgm_pool/{path.name}"
        try:
            bpm, duration = _detect_bpm(path)
        except Exception as e:  # noqa: BLE001
            print(f"warn: {path.name}: librosa failed ({e}); bpm=100 default", file=sys.stderr)
            bpm, duration = 100.0, 0.0
        tracks.append(
            {
                "name": path.stem,
                "path": rel,
                "bpm": bpm,
                "mood_tag": existing_mood.get(rel, "neutral"),
                "duration_sec": duration,
            }
        )
        print(f"  {path.name}: bpm={bpm} duration={duration}s mood={tracks[-1]['mood_tag']}")

    catalog = {"schema_version": 1, "tracks": tracks}
    index_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {len(tracks)} tracks → {index_path}")
    if len(tracks) < 5:
        print(
            f"note: PLAN 1578 recommends ≥ 5 tracks; currently {len(tracks)}. "
            "Selection still works with fewer (nearest-neighbour over what exists).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
