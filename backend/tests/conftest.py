"""Test fixtures. Copies fixture media into a temp DATA_ROOT per session."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def temp_data_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("data_root")
    os.environ["DATA_ROOT"] = str(root)
    for sub in ("samples", "projects", "system", "aigc", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if FIXTURE_ROOT.exists():
        # Copy fixture videos into samples/ for convenience.
        for name in ("sample_basic_15s", "short_15s"):
            src = FIXTURE_ROOT / name / "source.mp4"
            if src.exists():
                dst = root / "samples" / name / "source.mp4"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    # Reset cached settings so the env var takes effect.
    from app.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    return root
