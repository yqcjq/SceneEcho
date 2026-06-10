"""Unit tests for /projects/{id}/recommendations replay endpoint.

Covers the Phase 2.6 二核 path: Editor reload reads recommend results from
events.jsonl rather than caching them in project.json (D36). Each test
seeds the events file directly via the bus so we exercise the parser
without depending on the VLM stack.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import event_bus as eb
from app import tasks_store
from app.api import projects as projects_mod
from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.template import Tags, TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.kb import store as kb_store


@pytest.fixture
def projects_app(temp_data_root, monkeypatch):
    """Mount the projects router on its own FastAPI app for isolated testing.

    Resets the EventBus singleton per-test so subscriber/jsonl-path state
    from a prior test can't leak in (mirrors ``fresh_event_bus`` in conftest).
    """
    get_settings.cache_clear()  # type: ignore[attr-defined]
    eb.reset_event_bus()
    tasks_store.init_db()
    kb_store.init_db()
    # main.py wires this in lifespan; the unit-test app doesn't run lifespan
    # so we replicate the wiring manually after the reset.
    get_event_bus().set_lookup_callback(tasks_store.get_task)
    app = FastAPI()
    app.include_router(projects_mod.router, prefix="/api")
    yield TestClient(app)
    eb.reset_event_bus()
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _seed_template(template_id: str, name: str = "tpl 测试模板") -> None:
    """Insert a minimal KB row so the endpoint's reverse-lookup succeeds."""
    ir = TemplateIR(
        id=template_id,
        name=name,
        source_sample="smp_seed",
        skeleton=[],
        tags=Tags(position="中间", function="逻辑讲述", scene="纯口播", notes=""),
    )
    kb_store.save_template(ir, thumbnail_path=f"samples/seed/{template_id}.jpg")


def _seed_recommendation_events(
    project_id: str, recommendations: list[tuple[str, float, str]]
) -> str:
    """Create a recommend_templates task and publish entity events for it.

    Each tuple is ``(template_id, score, reason)``; emitted as one
    ``stage="2.recommend"`` VisionEvent with ``ir_value=template_id``,
    matching the shape ``recommend_templates`` writes in production.
    """
    task_id = tasks_store.create_task(
        "recommend_templates", resource_kind="project", resource_id=project_id
    )
    bus = get_event_bus()

    async def _publish_all() -> None:
        for tid, score, reason in recommendations:
            await bus.publish(
                task_id,
                VisionEvent(
                    task_id=task_id,
                    source="vlm",
                    stage="2.recommend",
                    semantic_label=f"推荐 · {tid}",
                    reasoning=reason,
                    confidence=score,
                    ir_target=IRTarget(
                        ir_type="ProjectIR", path="sections.0.template_id"
                    ),
                    ir_value=tid,
                ),
            )

    asyncio.run(_publish_all())
    return task_id


def _ensure_project_dir(project_id: str) -> None:
    settings = get_settings()
    (settings.data_root / "projects" / project_id).mkdir(parents=True, exist_ok=True)


def test_recommendations_404_for_unknown_project(projects_app):
    r = projects_app.get("/api/projects/does_not_exist/recommendations")
    assert r.status_code == 404


def test_recommendations_empty_when_no_task(projects_app):
    project_id = "prj_empty"
    _ensure_project_dir(project_id)
    r = projects_app.get(f"/api/projects/{project_id}/recommendations")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] is None
    assert body["recommendations"] == []


def test_recommendations_replay_entity_events(projects_app):
    project_id = "prj_with_recs"
    _ensure_project_dir(project_id)
    _seed_template("tpl_a", name="模板 A")
    _seed_template("tpl_b", name="模板 B")

    task_id = _seed_recommendation_events(
        project_id,
        [
            ("tpl_a", 0.92, "节奏快、字幕明显"),
            ("tpl_b", 0.71, "调色风格匹配"),
        ],
    )
    r = projects_app.get(f"/api/projects/{project_id}/recommendations")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["workbench_url"] == f"/workbench/{task_id}"
    assert len(body["recommendations"]) == 2
    a, b = body["recommendations"]
    assert a["template_id"] == "tpl_a"
    assert a["score"] == pytest.approx(0.92)
    assert a["reason"] == "节奏快、字幕明显"
    assert a["name"] == "模板 A"
    assert a["thumbnail_path"] == "samples/seed/tpl_a.jpg"
    assert b["template_id"] == "tpl_b"
    assert b["score"] == pytest.approx(0.71)


def test_recommendations_filter_call_level_event(projects_app):
    """Only ir_value=str entity events count; the chat_vision call event
    carries ir_value=dict (the structured _RecommendResult dump) and must
    be skipped, otherwise duplicate noise leaks into the Editor cards."""
    project_id = "prj_with_call_event"
    _ensure_project_dir(project_id)
    _seed_template("tpl_x", name="X")

    task_id = tasks_store.create_task(
        "recommend_templates", resource_kind="project", resource_id=project_id
    )
    bus = get_event_bus()

    async def _publish() -> None:
        # Call-level event — ir_value is a dict.
        await bus.publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="vlm",
                stage="2.recommend",
                semantic_label="推荐 · 调用",
                ir_value={"recommendations": [{"template_id": "tpl_x", "score": 1.0, "reason": "demo"}]},
            ),
        )
        # Entity event — ir_value is the template_id string.
        await bus.publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="vlm",
                stage="2.recommend",
                semantic_label="推荐 · tpl_x",
                reasoning="风格匹配",
                confidence=1.0,
                ir_value="tpl_x",
            ),
        )
        # Fallback warning — different stage, must be excluded too.
        await bus.publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="system",
                stage="2.recommend.fallback",
                semantic_label="[fallback]",
                ir_value=None,
                severity="warning",
            ),
        )

    asyncio.run(_publish())
    r = projects_app.get(f"/api/projects/{project_id}/recommendations")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert len(body["recommendations"]) == 1
    assert body["recommendations"][0]["template_id"] == "tpl_x"


def test_recommendations_picks_latest_task(projects_app):
    """If the user re-runs recommend, only the newest task's events surface."""
    project_id = "prj_multi_recs"
    _ensure_project_dir(project_id)
    _seed_template("tpl_old", name="旧")
    _seed_template("tpl_new", name="新")

    older = _seed_recommendation_events(project_id, [("tpl_old", 0.8, "first run")])
    # ``time.time()`` resolution on Windows is ~15ms, so two consecutive
    # create_task calls can land on the same created_at and SQLite's
    # ORDER BY created_at DESC would break ties by an implementation-
    # defined order. Sleep just past one tick to make ordering explicit.
    time.sleep(0.02)
    newer = _seed_recommendation_events(project_id, [("tpl_new", 0.95, "second run")])
    assert older != newer

    r = projects_app.get(f"/api/projects/{project_id}/recommendations")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == newer
    assert len(body["recommendations"]) == 1
    assert body["recommendations"][0]["template_id"] == "tpl_new"
