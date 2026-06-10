"""2.5.nl_edit · Natural-language + parameter-panel editing of ProjectIR.

Single entrypoint module for Phase 2.5's edit loop (PLAN 1684-1689):

- :func:`nl_edit` translates a Chinese instruction into a list of
  :class:`~app.ir.patch.Patch` ops via a Text LLM call (structured output,
  no rewriting of user material text — D3 hard rule).
- :func:`panel_to_patches` is the equivalent translator for parameter-panel
  edits: same Patch dialect, no LLM call (the panel itself is the
  visible decision so a workbench event would be noise).
- :func:`apply_patches` is a pure-function dispatcher: ``ProjectIR ×
  list[Patch] → ProjectIR``. Op handlers mutate a model_dump dict + we
  re-validate via pydantic at the end so the result is always a sound IR.
- :func:`push_snapshot` / :func:`undo` implement the snapshot-stack
  undo strategy (see ``decisions/008-phase2-5-edit-storage.md``): each
  successful apply persists the *prior* ``project.json`` under
  ``projects/{id}/snapshots/v{N}.json``; ``undo`` restores the latest
  snapshot file and removes it. No per-op inverse logic — adding a new
  ``PatchOp`` only needs a forward handler.
- :func:`list_patch_history` materializes the patch log by scanning the
  project's nl_edit / panel_edit tasks and reading their events.jsonl
  files — patches live in events.jsonl alongside their reasoning, so
  there is no separate patch_history.jsonl to keep in sync.

Each generated Patch is broadcast as a ``stage="2.5.nl_edit"`` VisionEvent
so the workbench can show "user said X → LLM produced Patch Y → wrote
ProjectIR field Z" (PLAN 1681).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app import tasks_store
from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.patch import Patch
from app.ir.project import Caption, PlacedSegment, ProjectIR
from app.ir.template import CaptionStyle
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import get_llm_client
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "2.5.nl_edit"
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# LLM structured output schema for nl_edit
# ---------------------------------------------------------------------------


class _PatchDraft(BaseModel):
    """LLM-emitted Patch payload (loose target/value typed as dict)."""

    op: str
    target: dict[str, Any] = Field(default_factory=dict)
    value: dict[str, Any] = Field(default_factory=dict)


class _NLEditResult(BaseModel):
    patches: list[_PatchDraft] = Field(default_factory=list)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# NL → Patch
# ---------------------------------------------------------------------------


def _summarize_ir(ir: ProjectIR) -> dict[str, Any]:
    """Bounded summary fed to the LLM — keeps the prompt compact."""
    captions_preview = [
        {
            "idx": i,
            "text": c.text[:30] + ("…" if len(c.text) > 30 else ""),
            "start": round(c.start, 2),
            "end": round(c.end, 2),
            "color": c.style.color,
            "emphasis_words": list(c.style.emphasis_words),
        }
        for i, c in enumerate(ir.captions[:20])
    ]
    sections_preview = [
        {
            "idx": i,
            "template_id": sec.template_id,
            "segment_count": len(sec.segments),
            "segments": [
                {
                    "idx": j,
                    "slot_role": s.slot_role,
                    "src": list(s.src_timerange),
                    "timeline_start": round(s.timeline_start, 2),
                    "speed": round(s.speed, 3),
                    "is_fill": s.is_fill,
                }
                for j, s in enumerate(sec.segments[:20])
            ],
        }
        for i, sec in enumerate(ir.sections)
    ]
    return {
        "version": ir.version,
        "canvas": ir.canvas,
        "bgm_track": ir.bgm_track,
        "sections": sections_preview,
        "captions": captions_preview,
        "caption_count": len(ir.captions),
    }


def _summarize_template(template: dict | None) -> dict[str, Any]:
    if not template:
        return {}
    ir = template.get("ir") or {}
    skeleton = ir.get("skeleton") or []
    return {
        "id": template.get("id"),
        "name": template.get("name"),
        "skeleton": [
            {
                "role": s.get("role"),
                "duration": s.get("duration"),
                "caption.placeholder_text": ((s.get("style") or {}).get("caption") or {}).get(
                    "placeholder_text"
                ),
                "caption.length_constraint": (
                    (s.get("style") or {}).get("caption") or {}
                ).get("length_constraint"),
            }
            for s in skeleton[:6]
        ],
    }


async def nl_edit(
    project_ir: ProjectIR,
    instruction: str,
    *,
    task_id: str,
    current_template: dict | None = None,
    available_templates: list[dict] | None = None,
) -> tuple[list[Patch], list[VisionEvent]]:
    """Translate a Chinese instruction into Patch ops via Text LLM.

    Returns ``(patches, events)``. An empty patch list means the LLM
    judged the instruction untranslatable (e.g. "翻转视频") — callers
    surface the LLM's ``reasoning`` to the user instead of silently
    no-op'ing. The accompanying ``events`` list has already been
    published to the bus; callers don't need to re-publish.
    """
    settings = get_settings()
    bus = get_event_bus()
    started = time.perf_counter()
    events: list[VisionEvent] = []

    summary = _summarize_ir(project_ir)
    catalog = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "tags": t.get("tags"),
        }
        for t in (available_templates or [])
    ]

    cl = get_llm_client(stage=STAGE)
    system = load_prompt("2_5_nl_edit")
    user_payload = {
        "instruction": instruction,
        "current_ir_summary": summary,
        "template_skeleton": _summarize_template(current_template),
        "available_templates": catalog[:50],
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _stringify_payload(user_payload)},
    ]
    result, llm_events = await cl.chat_text(
        messages,
        model=settings.model_text,
        stage=STAGE,
        task_id=task_id,
        ir_target_template=None,
        schema=_NLEditResult,
    )
    events.extend(llm_events)

    parent_id = llm_events[-1].event_id if llm_events else None
    patches: list[Patch] = []
    for draft in result.patches:
        if draft.op not in _OP_HANDLERS:
            # Drop unknown ops silently — they cannot be applied. We emit a
            # warning event so the workbench shows the LLM produced
            # something untranslatable instead of pretending it succeeded.
            warning = VisionEvent(
                task_id=task_id,
                source="text_llm",
                stage=f"{STAGE}.unknown_op",
                semantic_label=f"[warning] LLM 输出未知 op：{draft.op}",
                reasoning=f"op={draft.op} 不在 PatchOp 枚举中；跳过。",
                confidence=0.0,
                severity="warning",
                ir_target=None,
                parent_event_id=parent_id,
            )
            await bus.publish(task_id, warning)
            events.append(warning)
            continue
        patch = Patch(
            op=draft.op,
            target=draft.target,
            value=draft.value,
            source="nl",
            timestamp=_now_iso(),
        )
        patches.append(patch)
        ev = VisionEvent(
            task_id=task_id,
            source="text_llm",
            stage=STAGE,
            semantic_label=f"NL 翻译 · op={patch.op}",
            reasoning=(
                f"指令='{instruction[:80]}'；op={patch.op}；"
                f"target={patch.target}；value={patch.value}。"
                f"{result.reasoning[:120] if result.reasoning else ''}"
            ),
            confidence=0.9,
            ir_target=IRTarget(
                ir_type="ProjectIR",
                path=_describe_patch_target_path(patch),
            ),
            ir_value=patch.model_dump(mode="json"),
            parent_event_id=parent_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)

    if not patches:
        warning = VisionEvent(
            task_id=task_id,
            source="text_llm",
            stage=f"{STAGE}.no_patch",
            semantic_label=f"[warning] 指令无法翻译为 Patch",
            reasoning=(
                f"指令='{instruction[:80]}'。LLM reasoning: "
                f"{result.reasoning[:200] if result.reasoning else '(空)'}。"
                "请改用更具体的描述（颜色用 HEX / 段号 0-indexed）。"
            ),
            confidence=0.0,
            severity="warning",
            ir_target=None,
            parent_event_id=parent_id,
        )
        await bus.publish(task_id, warning)
        events.append(warning)

    elapsed = int((time.perf_counter() - started) * 1000)
    log.info(
        "nl_edit_done",
        task_id=task_id,
        instruction_len=len(instruction),
        patch_count=len(patches),
        elapsed_ms=elapsed,
    )
    return patches, events


def _stringify_payload(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Panel → Patch (no LLM)
# ---------------------------------------------------------------------------


# Per-field translation table for panel-edit. The key is the dotted
# UI-friendly field name; the value is a callable returning a Patch.
# Adding a new panel field = adding one row here.
def panel_to_patches(field: str, value: Any, *, target: dict | None = None) -> list[Patch]:
    """Translate a parameter-panel mutation to one or more Patch ops.

    ``target`` carries panel-specific scope (e.g. which segment / caption
    is being edited). Unlike :func:`nl_edit` this does NOT emit
    VisionEvents — the panel UI itself is the visible record.

    Recognised ``field`` values mirror the panel controls in
    ``ParamPanel.tsx``::

        caption.color, caption.stroke_color, caption.size, caption.position,
        caption.anim_in, caption.layout, caption.max_chars_per_line,
        caption.placeholder_text                  → set_caption_style
        rhythm.scale                              → adjust_rhythm
        visual.color_lut, visual.mask             → set_visual_style
        canvas.width, canvas.height, canvas.fps   → set_canvas
        bgm.track, bgm.strategy                   → set_bgm
        emphasis.words                            → set_emphasis
    """
    tgt = dict(target or {})
    now = _now_iso()

    if field.startswith("caption."):
        key = field.split(".", 1)[1]
        return [
            Patch(
                op="set_caption_style",
                target=tgt or {"all": True},
                value={key: value},
                source="panel",
                timestamp=now,
            )
        ]
    if field == "rhythm.scale":
        return [
            Patch(
                op="adjust_rhythm",
                target=tgt or {"all": True},
                value={"scale": float(value)},
                source="panel",
                timestamp=now,
            )
        ]
    if field.startswith("visual."):
        key = field.split(".", 1)[1]
        return [
            Patch(
                op="set_visual_style",
                target=tgt or {"all": True},
                value={key: value},
                source="panel",
                timestamp=now,
            )
        ]
    if field.startswith("canvas."):
        key = field.split(".", 1)[1]
        return [
            Patch(
                op="set_canvas",
                target={},
                value={key: value},
                source="panel",
                timestamp=now,
            )
        ]
    if field == "bgm.track":
        return [
            Patch(
                op="set_bgm",
                target={},
                value={"bgm_track": value},
                source="panel",
                timestamp=now,
            )
        ]
    if field == "bgm.strategy":
        return [
            Patch(
                op="set_bgm",
                target={},
                value={"strategy": value},
                source="panel",
                timestamp=now,
            )
        ]
    if field == "emphasis.words":
        return [
            Patch(
                op="set_emphasis",
                target=tgt,
                value={"words": list(value or [])},
                source="panel",
                timestamp=now,
            )
        ]
    if field == "template.swap":
        return [
            Patch(
                op="swap_template",
                target=tgt,
                value={"template_id": str(value)},
                source="panel",
                timestamp=now,
            )
        ]
    # Unknown field — return empty list so caller can warn.
    return []


# ---------------------------------------------------------------------------
# apply_patches dispatcher
# ---------------------------------------------------------------------------


class PatchApplyError(ValueError):
    """Raised when a Patch's payload would corrupt the IR.

    Distinct from "skip silently" — handlers raise this on logically
    invalid inputs (e.g. ``adjust_rhythm`` with scale outside [0.5,
    2.0], or ``set_emphasis`` words that aren't substrings of the
    referenced Unit text). The API layer turns this into a 400 with
    the reason so the UI can surface it.
    """


def apply_patches(project_ir: ProjectIR, patches: Iterable[Patch]) -> ProjectIR:
    """Apply ``patches`` in order and return a new ProjectIR.

    Pure function: does NOT touch disk, does NOT emit events. The caller
    (``api/edit.py``) is responsible for persistence + workbench events.
    Re-validates the final dict via pydantic so even sloppy in-place
    mutations get caught.
    """
    state = project_ir.model_dump(mode="python")
    for patch in patches:
        handler = _OP_HANDLERS.get(patch.op)
        if handler is None:
            raise PatchApplyError(f"unknown patch op: {patch.op}")
        state = handler(state, patch.target, patch.value)
    state["version"] = int(state.get("version", 1)) + 1
    return ProjectIR.model_validate(state)


# ---------------- handlers ---------------------------------------------------


def _walk_captions(state: dict, target: dict) -> list[int]:
    captions = state.get("captions") or []
    if target.get("all"):
        return list(range(len(captions)))
    explicit = target.get("caption_indices")
    if isinstance(explicit, list):
        return [i for i in explicit if isinstance(i, int) and 0 <= i < len(captions)]
    if isinstance(target.get("caption_idx"), int):
        idx = target["caption_idx"]
        if 0 <= idx < len(captions):
            return [idx]
    # Fall back to "all" so a NL request like "字幕改红色" without indices
    # applies to every caption — matches user mental model.
    return list(range(len(captions)))


def _walk_segments(state: dict, target: dict) -> list[tuple[int, int]]:
    """Return list of (section_idx, segment_idx) tuples matching ``target``."""
    sections = state.get("sections") or []
    out: list[tuple[int, int]] = []
    if target.get("all"):
        for si, sec in enumerate(sections):
            for sj, _ in enumerate(sec.get("segments") or []):
                out.append((si, sj))
        return out
    if "segment_indices" in target:
        # Indices are flat over section 0 for MVP (single section).
        for idx in target.get("segment_indices", []):
            if isinstance(idx, int):
                for si, sec in enumerate(sections):
                    segs = sec.get("segments") or []
                    if 0 <= idx < len(segs):
                        out.append((si, idx))
                        break
        return out
    if isinstance(target.get("segment_idx"), int):
        idx = target["segment_idx"]
        for si, sec in enumerate(sections):
            segs = sec.get("segments") or []
            if 0 <= idx < len(segs):
                return [(si, idx)]
        return []
    # default: all segments in section 0
    if sections:
        segs = sections[0].get("segments") or []
        return [(0, j) for j in range(len(segs))]
    return out


# Allowed CaptionStyle subset accepted via Patch.value — anything else is
# dropped so a malicious / hallucinated payload can't introduce extra
# pydantic-Unknown fields.
_ALLOWED_CAPTION_FIELDS: frozenset[str] = frozenset(
    {
        "font_family",
        "size",
        "color",
        "stroke_color",
        "stroke_width",
        "position",
        "layout",
        "max_chars_per_line",
        "anim_in",
        "anim_emphasis",
        "emphasis_words",
        "placeholder_text",
        "length_constraint",
        "semantic_purpose",
    }
)

_ALLOWED_VISUAL_FIELDS: frozenset[str] = frozenset(
    {"zoom_keyframes", "mask", "mask_params", "color_lut", "title_bar"}
)

_ALLOWED_CANVAS_FIELDS: frozenset[str] = frozenset({"width", "height", "fps"})


def _filter_dict(payload: dict, allowed: frozenset[str]) -> dict:
    return {k: v for k, v in payload.items() if k in allowed}


def _handle_set_caption_style(state: dict, target: dict, value: dict) -> dict:
    indices = _walk_captions(state, target)
    payload = _filter_dict(value, _ALLOWED_CAPTION_FIELDS)
    if not payload:
        return state
    captions = state.get("captions") or []
    for i in indices:
        style = captions[i].get("style") or {}
        # Use CaptionStyle default if no style yet (defensive — ProjectIR
        # always assigns one but kb migrations have shipped without it).
        merged = {**CaptionStyle().model_dump(), **style, **payload}
        captions[i]["style"] = merged
    state["captions"] = captions
    return state


def _handle_set_visual_style(state: dict, target: dict, value: dict) -> dict:
    payload = _filter_dict(value, _ALLOWED_VISUAL_FIELDS)
    if not payload:
        return state
    for si, sj in _walk_segments(state, target):
        seg = state["sections"][si]["segments"][sj]
        applied = seg.get("applied_style") or {}
        visual = dict(applied.get("visual") or {})
        visual.update(payload)
        applied["visual"] = visual
        seg["applied_style"] = applied
    return state


def _handle_adjust_rhythm(state: dict, target: dict, value: dict) -> dict:
    scale = float(value.get("scale") or 1.0)
    if not (0.5 <= scale <= 2.0):
        raise PatchApplyError(
            f"adjust_rhythm scale={scale} outside [0.5, 2.0]; refuse to corrupt timeline"
        )
    cumulative_shift = 0.0
    affected = set(_walk_segments(state, target))
    sections = state.get("sections") or []
    # Walk segments in timeline order so we can keep timeline_start contiguous.
    flat: list[tuple[int, int, dict]] = []
    for si, sec in enumerate(sections):
        for sj, seg in enumerate(sec.get("segments") or []):
            flat.append((si, sj, seg))
    flat.sort(key=lambda t: float((t[2].get("timeline_start") or 0.0)))
    for si, sj, seg in flat:
        old_speed = float(seg.get("speed") or 1.0)
        old_start, old_end = (
            float(seg["src_timerange"][0]),
            float(seg["src_timerange"][1]),
        )
        old_output = max(0.0, old_end - old_start) / max(0.04, old_speed)
        seg["timeline_start"] = round(float(seg.get("timeline_start") or 0.0) + cumulative_shift, 3)
        if (si, sj) in affected:
            new_speed = round(max(0.5, min(2.0, old_speed * scale)), 3)
            seg["speed"] = new_speed
            new_output = max(0.0, old_end - old_start) / max(0.04, new_speed)
            cumulative_shift += new_output - old_output
    # Caption start/end stay aligned to the Unit times relative to their
    # PlacedSegment; we don't recompute them here (the renderer / preview
    # take ProjectIR.captions verbatim). NL "节奏加快" expectation is the
    # video plays faster — caption timing is the timeline_start shift that
    # already happened above.
    return state


def _handle_set_emphasis(state: dict, target: dict, value: dict) -> dict:
    words_raw = value.get("words") or []
    if not isinstance(words_raw, list):
        raise PatchApplyError("set_emphasis.value.words must be a list of strings")
    words = [str(w).strip() for w in words_raw if w]
    captions = state.get("captions") or []
    targets: list[int] = []
    if isinstance(target.get("caption_idx"), int):
        idx = target["caption_idx"]
        if 0 <= idx < len(captions):
            targets = [idx]
    elif isinstance(target.get("section_idx"), int) and isinstance(
        target.get("unit_idx_in_section"), int
    ):
        # Map section_idx + unit_idx_in_section back to a caption index. The
        # MVP has section 0 only, so the unit_idx_in_section is effectively
        # caption_idx; defend anyway.
        sec_idx = target["section_idx"]
        unit_idx = target["unit_idx_in_section"]
        # caption index = unit_idx (since style.apply_style emits one caption
        # per Unit in order).
        if 0 <= unit_idx < len(captions):
            targets = [unit_idx]
    else:
        targets = list(range(len(captions)))
    for i in targets:
        cap = captions[i]
        text = cap.get("text") or ""
        filtered = [w for w in words if w and w in text]
        cap["style"] = {**(cap.get("style") or {}), "emphasis_words": filtered[:3]}
    state["captions"] = captions
    return state


def _handle_swap_template(state: dict, target: dict, value: dict) -> dict:
    """Swap the template_id of the targeted section.

    This patch is *not* a full re-apply — that would require running the
    apply pipeline which the edit endpoint can't do synchronously without
    blocking the request. The semantic contract here: change
    ``sections[N].template_id``, then the api/edit layer kicks off a full
    re-apply as a separate background task (which produces a new
    ProjectIR overwriting this patched one). The patch itself is the
    *intent* recorded; the new IR is the *effect*.
    """
    tid = str(value.get("template_id") or "").strip()
    if not tid:
        raise PatchApplyError("swap_template.value.template_id is required")
    sections = state.get("sections") or []
    if not sections:
        return state
    section_idx = (
        target.get("section_idx") if isinstance(target.get("section_idx"), int) else 0
    )
    if 0 <= section_idx < len(sections):
        sections[section_idx]["template_id"] = tid
    return state


def _handle_delete_segment(state: dict, target: dict, value: dict) -> dict:
    sections = state.get("sections") or []
    if not sections:
        return state
    section_idx = (
        target.get("section_idx") if isinstance(target.get("section_idx"), int) else 0
    )
    seg_idx = target.get("segment_idx")
    if not isinstance(seg_idx, int) or not (0 <= section_idx < len(sections)):
        return state
    segs = sections[section_idx].get("segments") or []
    if not (0 <= seg_idx < len(segs)):
        return state
    removed = segs.pop(seg_idx)
    sections[section_idx]["segments"] = segs
    # Compact the timeline: shift downstream segments left by the removed
    # output span so the rendered video doesn't leave a black gap.
    speed = float(removed.get("speed") or 1.0)
    src_start, src_end = removed["src_timerange"]
    output_span = max(0.0, float(src_end) - float(src_start)) / max(0.04, speed)
    for s in segs[seg_idx:]:
        s["timeline_start"] = round(max(0.0, float(s.get("timeline_start") or 0.0) - output_span), 3)
    return state


def _handle_set_canvas(state: dict, target: dict, value: dict) -> dict:
    payload = _filter_dict(value, _ALLOWED_CANVAS_FIELDS)
    if not payload:
        return state
    canvas = dict(state.get("canvas") or {})
    canvas.update({k: int(v) if k in ("width", "height", "fps") else v for k, v in payload.items()})
    state["canvas"] = canvas
    return state


def _handle_set_bgm(state: dict, target: dict, value: dict) -> dict:
    if "bgm_track" in value:
        track = value["bgm_track"]
        state["bgm_track"] = (str(track) if track else None)
        return state
    if "strategy" in value and value["strategy"] in ("none",):
        state["bgm_track"] = None
        return state
    # Other strategy values (features / original) would require re-running
    # apply.style._select_bgm; defer to swap_template-style background re-apply.
    return state


_OP_HANDLERS: dict[str, Any] = {
    "set_caption_style": _handle_set_caption_style,
    "set_visual_style": _handle_set_visual_style,
    "adjust_rhythm": _handle_adjust_rhythm,
    "set_emphasis": _handle_set_emphasis,
    "swap_template": _handle_swap_template,
    "delete_segment": _handle_delete_segment,
    "set_canvas": _handle_set_canvas,
    "set_bgm": _handle_set_bgm,
}


# ---------------------------------------------------------------------------
# Snapshot stack — undo / redo
# ---------------------------------------------------------------------------


def _snapshot_dir(project_id: str) -> Path:
    return get_settings().data_root / "projects" / project_id / "snapshots"


_SNAPSHOT_NAME_RE = re.compile(r"^v(\d+)\.json$")


def _list_snapshot_versions(project_id: str) -> list[int]:
    """Return existing snapshot version numbers, ascending."""
    sdir = _snapshot_dir(project_id)
    if not sdir.exists():
        return []
    versions: list[int] = []
    for p in sdir.iterdir():
        m = _SNAPSHOT_NAME_RE.match(p.name)
        if m:
            versions.append(int(m.group(1)))
    versions.sort()
    return versions


def push_snapshot(project_id: str, ir_before_apply: ProjectIR) -> int:
    """Persist ``ir_before_apply`` so a subsequent undo can restore it.

    Snapshot file name = ``v{ir_before_apply.version}.json`` — the
    version number on disk is the *pre-apply* version, which is exactly
    what undo wants to restore to.

    Returns the persisted version number.
    """
    sdir = _snapshot_dir(project_id)
    sdir.mkdir(parents=True, exist_ok=True)
    version = int(ir_before_apply.version)
    path = sdir / f"v{version}.json"
    path.write_text(ir_before_apply.model_dump_json(indent=2), encoding="utf-8")
    return version


def undo(project_id: str) -> ProjectIR | None:
    """Restore the most recent snapshot. Returns the restored IR.

    Removes the consumed snapshot file (no redo support at MVP — adding
    redo means keeping a forward stack, which the snapshot count
    already permits if a caller wants to layer it later). Returns
    ``None`` when the snapshot stack is empty (caller surfaces 400).
    """
    versions = _list_snapshot_versions(project_id)
    if not versions:
        return None
    latest = versions[-1]
    sdir = _snapshot_dir(project_id)
    snap_path = sdir / f"v{latest}.json"
    if not snap_path.exists():
        return None
    ir = ProjectIR.model_validate_json(snap_path.read_text(encoding="utf-8"))
    project_dir = get_settings().data_root / "projects" / project_id
    (project_dir / "project.json").write_text(
        ir.model_dump_json(indent=2), encoding="utf-8"
    )
    snap_path.unlink()
    return ir


# ---------------------------------------------------------------------------
# Patch history via events.jsonl
# ---------------------------------------------------------------------------


def list_patch_history(project_id: str) -> list[dict]:
    """Materialize the patch log for one project.

    Reads ``tasks WHERE kind IN ('nl_edit','panel_edit') AND
    resource_id={project_id}`` ordered by ``created_at ASC``, then for
    each task reads its ``events.jsonl`` and yields VisionEvents with
    ``stage == STAGE``. The event's ``ir_value`` carries the Patch
    payload; we surface (task_id, timestamp, op, target, value,
    reasoning) as a flat list the UI can render directly.

    No separate ``patch_history.jsonl`` exists — events.jsonl is the
    only source of truth. See ``decisions/008-phase2-5-edit-storage.md``.
    """
    rows = tasks_store.list_by_resource("project", project_id)
    edit_rows = [
        r for r in rows if r.get("kind") in ("nl_edit", "panel_edit", "undo")
    ]
    edit_rows.sort(key=lambda r: float(r.get("created_at") or 0.0))
    bus = get_event_bus()
    out: list[dict] = []
    for r in edit_rows:
        tid = r.get("id")
        if not tid:
            continue
        for ev in bus.replay(tid):
            if ev.stage != STAGE:
                continue
            value = ev.ir_value if isinstance(ev.ir_value, dict) else {}
            out.append(
                {
                    "task_id": tid,
                    "kind": r.get("kind"),
                    "timestamp": ev.timestamp,
                    "sequence": ev.sequence,
                    "op": value.get("op"),
                    "target": value.get("target"),
                    "value": value.get("value"),
                    "source": value.get("source"),
                    "reasoning": ev.reasoning,
                    "event_id": ev.event_id,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC).isoformat(timespec="milliseconds")


# Map a Patch op to the ProjectIR path it primarily writes — used as the
# VisionEvent's ir_target.path so the workbench's right-pane flashes the
# affected field.
_OP_PRIMARY_PATH: dict[str, str] = {
    "set_caption_style": "captions",
    "set_visual_style": "sections.0.segments",
    "adjust_rhythm": "sections.0.segments",
    "set_emphasis": "captions",
    "swap_template": "sections.0.template_id",
    "delete_segment": "sections.0.segments",
    "set_canvas": "canvas",
    "set_bgm": "bgm_track",
}


def _describe_patch_target_path(patch: Patch) -> str:
    return _OP_PRIMARY_PATH.get(patch.op, "project_id")


__all__ = [
    "STAGE",
    "PatchApplyError",
    "apply_patches",
    "list_patch_history",
    "nl_edit",
    "panel_to_patches",
    "push_snapshot",
    "undo",
]
