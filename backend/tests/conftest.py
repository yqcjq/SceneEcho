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
    for sub in ("samples", "projects", "system", "aigc", "logs", "system/dev_events"):
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


@pytest.fixture
def fresh_event_bus(temp_data_root, monkeypatch):
    """Provide a fresh EventBus singleton per test, isolated from siblings."""
    from app import event_bus as eb

    eb.reset_event_bus()
    yield eb.get_event_bus()
    eb.reset_event_bus()


@pytest.fixture
def task_with_events(temp_data_root, fresh_event_bus):
    """Create a sample-resource task with an events_jsonl_path wired up."""
    from app import tasks_store

    tasks_store.init_db()
    sample_id = "evt_test_sample"
    (temp_data_root / "samples" / sample_id / "extracted").mkdir(parents=True, exist_ok=True)
    task_id = tasks_store.create_task("test", resource_kind="sample", resource_id=sample_id)
    fresh_event_bus.register_path(
        task_id, fresh_event_bus.resolve_events_path("sample", sample_id, task_id)
    )
    return task_id, sample_id
