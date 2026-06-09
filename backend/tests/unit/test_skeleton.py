"""Phase 1B · skeleton inference unit tests.

Skeleton is the only "computation" of 1B (the rest is orchestration);
unit tests verify the role/material_req/duration logic against synthetic
Phase1AReport inputs so the regression surface is well-defined.
"""

from __future__ import annotations

import pytest

from app.extract.skeleton import _role_for_position, build_skeleton
from app.ir.phase1a_report import (
    Phase1ACaptionEvent,
    Phase1AColorReport,
    Phase1AReport,
    Phase1AScene,
    Phase1AStickerDetection,
)
from app.ir.template import AudioStyle, CaptionStyle, StickerEvent, ZoomKeyframe


def test_role_for_position_threshold_boundaries():
    # PLAN 1510: start<0.30 → 开头, start>0.70 → 结尾, else 主体.
    assert _role_for_position(0.0) == "开头"
    assert _role_for_position(0.29) == "开头"
    assert _role_for_position(0.30) == "主体"  # boundary inclusive in "else"
    assert _role_for_position(0.50) == "主体"
    assert _role_for_position(0.70) == "主体"
    assert _role_for_position(0.71) == "结尾"


@pytest.mark.asyncio
async def test_build_skeleton_three_roles_for_3_scenes(task_with_events):
    task_id, _ = task_with_events
    total = 10.0
    report = Phase1AReport(
        scenes=[
            Phase1AScene(idx=0, start_sec=0.0, end_sec=3.0),
            Phase1AScene(idx=1, start_sec=3.0, end_sec=7.0),
            Phase1AScene(idx=2, start_sec=7.5, end_sec=10.0),
        ],
        audio=AudioStyle(),
        color=Phase1AColorReport(),
    )
    slots, events = await build_skeleton(report, total, task_id=task_id)
    assert [s.role for s in slots] == ["开头", "主体", "结尾"]
    # Per-slot duration band: nominal ≈ span, min = 0.7 * span, max = 1.5 * span
    open_span = slots[0].duration["nominal"]
    assert slots[0].duration["min"] == pytest.approx(open_span * 0.7, abs=0.01)
    assert slots[0].duration["max"] == pytest.approx(open_span * 1.5, abs=0.01)
    # One VisionEvent per slot.
    assert len(events) == 3
    for ev in events:
        assert ev.stage == "1B.skeleton"
        assert ev.ir_target is not None
        assert ev.ir_target.ir_type == "TemplateIR"
        assert ev.ir_target.path == "skeleton"
        assert ev.ir_target.op == "append"


@pytest.mark.asyncio
async def test_build_skeleton_material_req_by_signal(task_with_events):
    """Caption presence → 人物口播; zoom/sticker/mask only → B-roll/包装; none → 待定."""
    task_id, _ = task_with_events
    total = 10.0
    report = Phase1AReport(
        scenes=[Phase1AScene(idx=0, start_sec=4.0, end_sec=6.0)],
        captions=[
            Phase1ACaptionEvent(
                style=CaptionStyle(),
                start=4.5,
                end=5.5,
                bbox_norm_0_999=(100, 800, 800, 100),
                frames_appeared=[5.0],
                confidence=0.9,
            )
        ],
    )
    slots, _ = await build_skeleton(report, total, task_id=task_id)
    assert len(slots) == 1
    assert slots[0].material_req == "人物口播"

    # Sticker only → B-roll/包装
    report2 = Phase1AReport(
        scenes=[Phase1AScene(idx=0, start_sec=4.0, end_sec=6.0)],
        stickers=[
            Phase1AStickerDetection(
                sticker=StickerEvent(
                    description="x",
                    position=(0.5, 0.5),
                    size=(0.1, 0.1),
                    start=4.0,
                    end=6.0,
                ),
                bbox_norm_0_999=(500, 500, 100, 100),
            )
        ],
    )
    slots, _ = await build_skeleton(report2, total, task_id=task_id)
    assert slots[0].material_req == "B-roll/包装"

    # Neither caption nor sticker/zoom/mask → 待定
    report3 = Phase1AReport(scenes=[Phase1AScene(idx=0, start_sec=4.0, end_sec=6.0)])
    slots, _ = await build_skeleton(report3, total, task_id=task_id)
    assert slots[0].material_req == "待定"


@pytest.mark.asyncio
async def test_build_skeleton_empty_report(task_with_events):
    task_id, _ = task_with_events
    slots, events = await build_skeleton(Phase1AReport(), 0.0, task_id=task_id)
    assert slots == []
    assert events == []


@pytest.mark.asyncio
async def test_build_skeleton_consecutive_same_role_merges(task_with_events):
    """Two consecutive scenes that both land in 主体 collapse into one slot."""
    task_id, _ = task_with_events
    report = Phase1AReport(
        scenes=[
            Phase1AScene(idx=0, start_sec=3.5, end_sec=5.0),
            Phase1AScene(idx=1, start_sec=5.0, end_sec=6.5),
        ],
        zoom_curves={
            "0": [ZoomKeyframe(relative_time=0.0, scale=1.0)],
            "1": [ZoomKeyframe(relative_time=0.5, scale=1.2)],
        },
    )
    slots, _ = await build_skeleton(report, 10.0, task_id=task_id)
    # Both scenes land in 主体 (start_ratio 0.35 and 0.50) → one slot.
    assert len(slots) == 1
    assert slots[0].role == "主体"
    # Zoom keyframes from both scenes are stitched.
    assert len(slots[0].style.visual.zoom_keyframes) >= 2
