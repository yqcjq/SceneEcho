"""SubcapabilityLab API unit tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import lab as lab_mod
from app.config import get_settings


@pytest.fixture
def lab_app(temp_data_root, monkeypatch):
    """Boot a minimal FastAPI app with only the lab router for testing."""
    monkeypatch.setenv("ENABLE_DEV_MOCK", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    from fastapi import FastAPI

    from app import tasks_store

    tasks_store.init_db()
    app = FastAPI()
    app.include_router(lab_mod.router, prefix="/api")
    yield TestClient(app)
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_subcaps_list_contains_canonical_entries(lab_app):
    r = lab_app.get("/api/lab/subcaps")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["subcaps"]]
    for required in (
        "scenes",
        "captions",
        "stickers",
        "zoom",
        "transitions",
        "masks",
        "color_lut",
        "audio",
    ):
        assert required in names


def test_subcaps_403_when_dev_disabled(temp_data_root, monkeypatch):
    """Production builds should not see the lab routes."""
    monkeypatch.setenv("ENABLE_DEV_MOCK", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(lab_mod.router, prefix="/api")
        client = TestClient(app)
        r = client.get("/api/lab/subcaps")
        assert r.status_code == 403
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_run_subcap_404_for_unknown(lab_app):
    r = lab_app.post("/api/lab/run-subcap/does_not_exist", json={"fixture_id": "x"})
    assert r.status_code == 404


def test_run_subcap_404_when_fixture_missing(lab_app):
    r = lab_app.post("/api/lab/run-subcap/scenes", json={"fixture_id": "no_such_sample"})
    assert r.status_code == 404


def test_run_subcap_dry_run_returns_workbench_url(lab_app, temp_data_root):
    sample_id = "lab_dry"
    sample_dir = temp_data_root / "samples" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "normalized.mp4").write_bytes(b"")
    r = lab_app.post(
        "/api/lab/run-subcap/scenes",
        json={"fixture_id": sample_id, "dry_run": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["workbench_url"].startswith("/workbench/")
