"""Dev-only mock event stream for the workbench frontend.

Mounted only when ``ENABLE_DEV_MOCK=true``. Lets the browser open
``/workbench/{task_id}`` against a running backend without invoking any real
AI client — useful for design-token review, three-pane UI iteration, and
SSE reconnect testing.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app import tasks_store
from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.vision_event import VisionEvent
from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "scenarios"


class MockStreamRequest(BaseModel):
    scenario: str = Field(
        ..., description="One of captions_demo / stickers_demo / full_extract_demo"
    )
    task_id: str | None = Field(
        default=None, description="Reuse an existing task id; otherwise auto-create."
    )


def _scenario_path(name: str) -> Path:
    p = SCENARIO_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, f"scenario not found: {name}")
    return p


async def _replay_scenario(task_id: str, scenario_name: str) -> None:
    bus = get_event_bus()
    try:
        data = json.loads(_scenario_path(scenario_name).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("dev_workbench.scenario_parse_failed", task_id=task_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=f"scenario parse: {e}")
        return

    tasks_store.update_task(task_id, status="running", progress=0.0, stage="0.5.mock")
    total = len(data.get("events", [])) or 1

    # Remap scenario event_ids → fresh UUIDs so re-running the same scenario
    # against the same task_id never produces a duplicate id (which would
    # break Last-Event-ID resume semantics).
    id_remap: dict[str, str] = {}

    try:
        for i, item in enumerate(data["events"]):
            await asyncio.sleep(max(0, item.get("delay_ms", 500) / 1000.0))
            raw = dict(item.get("event", {}))
            raw["task_id"] = task_id
            original_id = raw.get("event_id")
            if isinstance(original_id, str) and original_id:
                new_id = uuid.uuid4().hex
                id_remap[original_id] = new_id
                raw["event_id"] = new_id
            else:
                raw["event_id"] = uuid.uuid4().hex
            parent = raw.get("parent_event_id")
            if isinstance(parent, str) and parent in id_remap:
                raw["parent_event_id"] = id_remap[parent]
            elif isinstance(parent, str):
                # Forward reference (parent appears later in the scenario): drop
                # the link rather than silently dangle.
                raw["parent_event_id"] = None
            try:
                ev = VisionEvent.model_validate(raw)
            except Exception as e:  # noqa: BLE001
                log.warning("dev_workbench.event_parse_skipped", index=i, error=str(e))
                continue
            await bus.publish(task_id, ev)
            tasks_store.update_task(task_id, progress=(i + 1) / total, stage=ev.stage)
    except Exception as e:  # noqa: BLE001
        # Any failure in the broadcast loop must still leave the task in a
        # terminal state, otherwise SSE consumers wait forever for `done`.
        log.error("dev_workbench.replay_failed", task_id=task_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))
        bus.close_task(task_id)
        return

    tasks_store.update_task(task_id, status="completed", progress=1.0, stage="0.5.mock.done")
    bus.close_task(task_id)


@router.post("/dev/workbench/mock-stream")
async def mock_stream(req: MockStreamRequest, background_tasks: BackgroundTasks) -> dict:
    settings = get_settings()
    if not settings.enable_dev_mock:
        raise HTTPException(403, "ENABLE_DEV_MOCK is not set")

    # Ensure the scenario exists before we create any state.
    _scenario_path(req.scenario)

    # Reuse an existing task if the caller provided one (lets the user
    # navigate to /workbench/{id} *first* and then start the stream from
    # the dev launcher in another window).
    if req.task_id:
        existing = tasks_store.get_task(req.task_id)
        if existing:
            task_id = req.task_id
            dummy_sample_id = existing.get("resource_id") or f"dev_mock_{req.scenario}"
            sample_dir = settings.data_root / "samples" / dummy_sample_id / "extracted"
            sample_dir.mkdir(parents=True, exist_ok=True)
            background_tasks.add_task(_replay_scenario, task_id, req.scenario)
            return {
                "task_id": task_id,
                "sample_id": dummy_sample_id,
                "workbench_url": f"/workbench/{task_id}",
            }

    # Auto-create a dummy sample resource so the events JSONL has a stable
    # home on disk; matches Phase 0.5 path scheme B.
    dummy_sample_id = f"dev_mock_{req.scenario}_{uuid.uuid4().hex[:6]}"
    sample_dir = settings.data_root / "samples" / dummy_sample_id / "extracted"
    sample_dir.mkdir(parents=True, exist_ok=True)

    task_id = tasks_store.create_task(
        "mock_stream",
        resource_kind="sample",
        resource_id=dummy_sample_id,
        task_id=req.task_id,
    )

    background_tasks.add_task(_replay_scenario, task_id, req.scenario)
    return {
        "task_id": task_id,
        "sample_id": dummy_sample_id,
        "workbench_url": f"/workbench/{task_id}",
    }


@router.get("/dev/workbench/scenarios")
def list_scenarios() -> dict:
    """Enumerate available scenarios for the frontend's dev launcher."""
    if not get_settings().enable_dev_mock:
        raise HTTPException(403, "ENABLE_DEV_MOCK is not set")
    items = []
    for p in sorted(SCENARIO_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items.append(
                {
                    "name": data.get("name", p.stem),
                    "description": data.get("description", ""),
                    "event_count": len(data.get("events", [])),
                }
            )
        except Exception:  # noqa: BLE001
            continue
    return {"scenarios": items}
