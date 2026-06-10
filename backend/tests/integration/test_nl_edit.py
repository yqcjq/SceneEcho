"""Unit + integration tests for Phase 2.5 nl_edit / undo / replay (ISS-015).

The tests are organised by capability rather than file:
- ``test_nl_edit_*`` exercise the pure-function ``apply_patches`` for
  every PatchOp the panel + LLM emit. Real LLM calls are stubbed —
  ``no_credentials`` makes ``chat_text`` fall back to a default-
  constructed schema, then we feed ``apply_patches`` hand-crafted
  Patch lists directly so we can assert the IR transform without
  depending on an LLM running.
- ``test_apply_undo_*`` round-trip a 3-patch / 2-undo sequence and
  confirm version + content recovery.
- ``test_replay_*`` exercise the snapshot reconstruction lodash.set
  semantics.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.ir.patch import Patch
from app.ir.project import Caption, PlacedSegment, ProjectIR, Section
from app.ir.template import CaptionStyle, StyleRule


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _minimal_ir(project_id: str = "prj_nl") -> ProjectIR:
    return ProjectIR(
        project_id=project_id,
        user_material=f"projects/{project_id}/normalized.mp4",
        sections=[
            Section(
                topic="demo",
                template_id="tpl_demo",
                segments=[
                    PlacedSegment(
                        slot_role="开头",
                        source_unit_ids=[0],
                        src_timerange=(0.0, 3.0),
                        timeline_start=0.0,
                        speed=1.0,
                    ),
                    PlacedSegment(
                        slot_role="主体",
                        source_unit_ids=[1],
                        src_timerange=(3.0, 10.0),
                        timeline_start=3.0,
                        speed=1.0,
                    ),
                ],
            )
        ],
        captions=[
            Caption(text="今天聊聊独家爆款", start=0.0, end=3.0, style=CaptionStyle()),
            Caption(text="限时立减一百块", start=3.0, end=10.0, style=CaptionStyle()),
        ],
        canvas={"width": 1080, "height": 1920, "fps": 30},
        bgm_track="system/bgm_pool/calm_120.mp3",
    )


# ---------------------------------------------------------------------------
# apply_patches — per-op coverage
# ---------------------------------------------------------------------------


def test_apply_set_caption_style_all():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    patch = Patch(
        op="set_caption_style",
        target={"all": True},
        value={"color": "#FFD400", "stroke_color": "#000000"},
    )
    new_ir = apply_patches(ir, [patch])
    assert all(c.style.color == "#FFD400" for c in new_ir.captions)
    assert all(c.style.stroke_color == "#000000" for c in new_ir.captions)
    assert new_ir.version == ir.version + 1


def test_apply_set_caption_style_specific_index():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    patch = Patch(
        op="set_caption_style",
        target={"caption_indices": [0]},
        value={"color": "#FF3B30"},
    )
    new_ir = apply_patches(ir, [patch])
    assert new_ir.captions[0].style.color == "#FF3B30"
    assert new_ir.captions[1].style.color == CaptionStyle().color


def test_apply_set_emphasis_filters_to_substrings_of_unit_text():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    # The user "wants to highlight" 独家 and bogus 不存在 — only 独家 must survive.
    patch = Patch(
        op="set_emphasis",
        target={"caption_idx": 0},
        value={"words": ["独家", "不存在", "爆款"]},
    )
    new_ir = apply_patches(ir, [patch])
    assert new_ir.captions[0].style.emphasis_words == ["独家", "爆款"]
    # Other caption untouched.
    assert new_ir.captions[1].style.emphasis_words == []


def test_apply_adjust_rhythm_clamps_speed_and_compacts_timeline():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    patch = Patch(op="adjust_rhythm", target={"all": True}, value={"scale": 0.8})
    new_ir = apply_patches(ir, [patch])
    segs = new_ir.sections[0].segments
    # Speed scaled.
    assert segs[0].speed == pytest.approx(0.8, abs=1e-3)
    # Output span of seg0 = (3-0)/0.8 = 3.75; seg1.timeline_start shifts by +0.75
    assert segs[1].timeline_start == pytest.approx(3.75, abs=1e-3)


def test_apply_adjust_rhythm_rejects_out_of_bounds():
    from app.agent.nl_edit import PatchApplyError, apply_patches

    ir = _minimal_ir()
    patch = Patch(op="adjust_rhythm", target={"all": True}, value={"scale": 5.0})
    with pytest.raises(PatchApplyError):
        apply_patches(ir, [patch])


def test_apply_swap_template_changes_section_template_id():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    patch = Patch(op="swap_template", target={"section_idx": 0}, value={"template_id": "tpl_B"})
    new_ir = apply_patches(ir, [patch])
    assert new_ir.sections[0].template_id == "tpl_B"


def test_apply_delete_segment_compacts_timeline():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    patch = Patch(op="delete_segment", target={"section_idx": 0, "segment_idx": 0}, value={})
    new_ir = apply_patches(ir, [patch])
    segs = new_ir.sections[0].segments
    assert len(segs) == 1
    # Segment that was at timeline_start=3 now sits at 0 (compacted).
    assert segs[0].timeline_start == 0.0


def test_apply_set_canvas_only_allows_known_fields():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    patch = Patch(
        op="set_canvas",
        target={},
        value={"width": 1920, "height": 1080, "evil_key": "ignored"},
    )
    new_ir = apply_patches(ir, [patch])
    assert new_ir.canvas["width"] == 1920
    assert new_ir.canvas["height"] == 1080
    # evil_key must NOT have leaked through
    assert "evil_key" not in new_ir.canvas


def test_apply_set_bgm_clears_or_sets_track():
    from app.agent.nl_edit import apply_patches

    ir = _minimal_ir()
    new_ir = apply_patches(ir, [Patch(op="set_bgm", target={}, value={"bgm_track": None})])
    assert new_ir.bgm_track is None
    new_ir2 = apply_patches(
        new_ir, [Patch(op="set_bgm", target={}, value={"bgm_track": "system/bgm_pool/edm_140.mp3"})]
    )
    assert new_ir2.bgm_track == "system/bgm_pool/edm_140.mp3"


def test_apply_unknown_op_raises():
    from app.agent.nl_edit import PatchApplyError, apply_patches

    ir = _minimal_ir()
    with pytest.raises(PatchApplyError):
        apply_patches(ir, [Patch(op="not_a_real_op", target={}, value={})])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# panel_to_patches — does NOT call LLM
# ---------------------------------------------------------------------------


def test_panel_to_patches_caption_color():
    from app.agent.nl_edit import panel_to_patches

    patches = panel_to_patches("caption.color", "#FFD400", target={"all": True})
    assert len(patches) == 1
    assert patches[0].op == "set_caption_style"
    assert patches[0].value == {"color": "#FFD400"}
    assert patches[0].source == "panel"


def test_panel_to_patches_unknown_field_returns_empty():
    from app.agent.nl_edit import panel_to_patches

    patches = panel_to_patches("not.a.field", 123)
    assert patches == []


# ---------------------------------------------------------------------------
# Snapshot + undo round trip
# ---------------------------------------------------------------------------


def test_snapshot_undo_roundtrip(tmp_path, monkeypatch):
    """Apply 3 patches, undo 2, the IR matches state after 1 patch."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    from app.agent.nl_edit import apply_patches, push_snapshot, undo

    ir = _minimal_ir()
    project_dir = tmp_path / "projects" / ir.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(ir.model_dump_json(), encoding="utf-8")

    # Apply patch 1: caption yellow
    push_snapshot(ir.project_id, ir)
    ir_after_1 = apply_patches(
        ir, [Patch(op="set_caption_style", target={"all": True}, value={"color": "#FFD400"})]
    )
    (project_dir / "project.json").write_text(ir_after_1.model_dump_json(), encoding="utf-8")

    # Apply patch 2: caption size 80
    push_snapshot(ir.project_id, ir_after_1)
    ir_after_2 = apply_patches(
        ir_after_1, [Patch(op="set_caption_style", target={"all": True}, value={"size": 80})]
    )
    (project_dir / "project.json").write_text(ir_after_2.model_dump_json(), encoding="utf-8")

    # Apply patch 3: swap template
    push_snapshot(ir.project_id, ir_after_2)
    ir_after_3 = apply_patches(
        ir_after_2, [Patch(op="swap_template", target={"section_idx": 0}, value={"template_id": "tpl_B"})]
    )
    (project_dir / "project.json").write_text(ir_after_3.model_dump_json(), encoding="utf-8")

    # Undo twice → state at end of patch 1
    restored = undo(ir.project_id)
    assert restored is not None
    assert restored.sections[0].template_id == "tpl_demo"  # patch 3 undone
    restored = undo(ir.project_id)
    assert restored is not None
    assert all(c.style.size == CaptionStyle().size for c in restored.captions)  # patch 2 undone
    assert all(c.style.color == "#FFD400" for c in restored.captions)  # patch 1 still applied
    # Version: undo restored snapshot taken before patch 2 → version =
    # ir_after_1.version (which is base + 1).
    assert restored.version == ir_after_1.version

    # One more undo → state before any patch
    restored = undo(ir.project_id)
    assert restored is not None
    assert all(c.style.color == CaptionStyle().color for c in restored.captions)

    # Stack empty → undo returns None
    assert undo(ir.project_id) is None


# ---------------------------------------------------------------------------
# Replay snapshot lodash.set semantics
# ---------------------------------------------------------------------------


def test_replay_lodash_set_supports_dotted_and_list_paths():
    from app.api.replay import _lodash_set

    obj: dict = {}
    _lodash_set(obj, "captions", [], op="set")
    _lodash_set(obj, "captions", {"text": "Hello"}, op="append")
    _lodash_set(obj, "captions.0.color", "#FF0000", op="set")
    assert obj == {"captions": [{"text": "Hello", "color": "#FF0000"}]}


def test_replay_lodash_set_remove_op():
    from app.api.replay import _lodash_set

    obj: dict = {"a": {"b": 1, "c": 2}}
    _lodash_set(obj, "a.b", None, op="remove")
    assert obj == {"a": {"c": 2}}


@pytest.mark.asyncio
async def test_replay_snapshot_reconstructs_from_events(task_with_events):
    from app.api.replay import _snapshot_payload
    from app.event_bus import get_event_bus
    from app.ir.vision_event import IRTarget, VisionEvent

    task_id, _ = task_with_events
    bus = get_event_bus()
    for i, value in enumerate(["first", "second", "third"]):
        await bus.publish(
            task_id,
            VisionEvent(
                task_id=task_id,
                source="system",
                stage="test",
                semantic_label=f"step {i}",
                ir_target=IRTarget(ir_type="ProjectIR", path="captions", op="append"),
                ir_value={"text": value},
            ),
        )

    # Snapshot at sequence 2 should have first two captions only.
    payload = _snapshot_payload(task_id, 2)
    assert payload["snapshot"]["captions"] == [{"text": "first"}, {"text": "second"}]

    # Full snapshot (sequence past the end) has all three.
    payload_full = _snapshot_payload(task_id, 99)
    assert payload_full["snapshot"]["captions"] == [
        {"text": "first"},
        {"text": "second"},
        {"text": "third"},
    ]


def test_list_by_resource_returns_newest_first(tmp_path, monkeypatch):
    """tasks_store.list_by_resource respects created_at DESC ordering."""
    import time

    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    from app import tasks_store

    tasks_store.init_db()
    t1 = tasks_store.create_task("nl_edit", resource_kind="project", resource_id="prj_x")
    time.sleep(0.01)
    t2 = tasks_store.create_task("apply_short", resource_kind="project", resource_id="prj_x")
    time.sleep(0.01)
    t3 = tasks_store.create_task("render", resource_kind="project", resource_id="prj_y")

    rows_x = tasks_store.list_by_resource("project", "prj_x")
    assert [r["id"] for r in rows_x] == [t2, t1]
    rows_y = tasks_store.list_by_resource("project", "prj_y")
    assert [r["id"] for r in rows_y] == [t3]
    rows_none = tasks_store.list_by_resource("project", "absent")
    assert rows_none == []
