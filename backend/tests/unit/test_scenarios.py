"""Validate that mock scenarios reference real IR fields.

Phase 0.5 mocks drive the workbench without touching real VLMs, but their
``ir_target.path`` strings are the same paths Phase 1A will write through
``llm.client.chat_vision``. If the mocks reference non-existent fields, 1A
will inherit broken code; this test catches that drift at CI time.

Tolerance: ``dict``-typed IR fields (``global_style``, ``sanity_check``)
accept any sub-path — the workbench only structurally validates the spine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ir.ledger import TranscriptLedger
from app.ir.path_validator import validate_path
from app.ir.project import ProjectIR
from app.ir.template import TemplateIR
from app.ir.vision_event import VisionEvent

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "app" / "llm" / "prompts" / "scenarios"

ROOT_BY_TYPE = {
    "TemplateIR": TemplateIR,
    "ProjectIR": ProjectIR,
    "TranscriptLedger": TranscriptLedger,
}


def _scenario_files() -> list[Path]:
    return sorted(SCENARIO_DIR.glob("*.json"))


@pytest.mark.parametrize("scenario_path", _scenario_files(), ids=lambda p: p.stem)
def test_scenario_events_parse(scenario_path: Path) -> None:
    """Every event in every scenario JSON parses as a VisionEvent."""
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    assert "events" in data, f"{scenario_path.stem}: missing 'events'"
    for i, item in enumerate(data["events"]):
        raw = dict(item.get("event", {}))
        try:
            VisionEvent.model_validate(raw)
        except Exception as e:
            pytest.fail(f"{scenario_path.stem}#{i} ({raw.get('event_id')}): {e}")


@pytest.mark.parametrize("scenario_path", _scenario_files(), ids=lambda p: p.stem)
def test_scenario_ir_paths_match_real_ir(scenario_path: Path) -> None:
    """Every event's ``ir_target.path`` (+ field) lands on a real IR field."""
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for i, item in enumerate(data["events"]):
        raw = dict(item.get("event", {}))
        ev = VisionEvent.model_validate(raw)
        if ev.ir_target is None:
            continue
        root = ROOT_BY_TYPE.get(ev.ir_target.ir_type)
        if root is None:
            errors.append(f"#{i} ({ev.event_id}): unknown ir_type {ev.ir_target.ir_type!r}")
            continue
        full_path = ev.ir_target.path
        if ev.ir_target.field:
            full_path = f"{full_path}.{ev.ir_target.field}"
        ok, msg = validate_path(root, full_path)
        if not ok:
            errors.append(f"#{i} ({ev.event_id}) path={full_path!r}: {msg}")
    assert not errors, f"{scenario_path.stem} has invalid IR paths:\n" + "\n".join(errors)


@pytest.mark.parametrize("scenario_path", _scenario_files(), ids=lambda p: p.stem)
def test_scenario_parent_event_ids_resolve(scenario_path: Path) -> None:
    """If an event names a parent_event_id, the parent must appear earlier."""
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    errors: list[str] = []
    for i, item in enumerate(data["events"]):
        raw = item.get("event", {})
        eid = raw.get("event_id")
        parent = raw.get("parent_event_id")
        if parent is not None and parent not in seen:
            errors.append(f"#{i} ({eid}): parent_event_id {parent!r} appears later or missing")
        if isinstance(eid, str):
            seen.add(eid)
    assert not errors, "\n".join(errors)
