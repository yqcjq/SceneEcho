"""Templates API — Phase 1B KB CRUD + event replay."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.event_bus import get_event_bus
from app.ir.template import Tags
from app.kb import store as kb_store

router = APIRouter()


class TagsPatch(BaseModel):
    position: str | None = None
    function: str | None = None
    scene: str | None = None
    notes: str | None = None


class PlaceholderPatch(BaseModel):
    slot_idx: int
    placeholder_text: list[str]


@router.get("/templates")
def list_templates() -> dict:
    """Return all KB templates, newest first. Lightweight (no ir_json)."""
    return {"templates": kb_store.list_templates()}


@router.get("/templates/{template_id}")
def get_template(template_id: str) -> dict:
    """Return one template with full parsed IR + tags + thumbnail path."""
    t = kb_store.get_template(template_id)
    if not t:
        raise HTTPException(404, f"template {template_id} not found")
    return t


@router.patch("/templates/{template_id}/tags")
def patch_tags(template_id: str, patch: TagsPatch) -> dict:
    """Partially update Tags; missing fields keep their existing value."""
    t = kb_store.get_template(template_id)
    if not t:
        raise HTTPException(404, f"template {template_id} not found")
    current = Tags.model_validate(t["tags"])
    merged = Tags(
        position=patch.position if patch.position is not None else current.position,
        function=patch.function if patch.function is not None else current.function,
        scene=patch.scene if patch.scene is not None else current.scene,
        notes=patch.notes if patch.notes is not None else current.notes,
    )
    ok = kb_store.update_template_tags(template_id, merged)
    if not ok:
        raise HTTPException(500, "update failed")
    return {"ok": True, "tags": merged.model_dump()}


@router.patch("/templates/{template_id}/caption-placeholder")
def patch_caption_placeholder(template_id: str, patch: PlaceholderPatch) -> dict:
    """Manually override one slot's caption placeholder_text (PLAN 1538)."""
    ok = kb_store.update_caption_placeholder(
        template_id, patch.slot_idx, patch.placeholder_text
    )
    if not ok:
        raise HTTPException(
            404,
            f"template {template_id} / slot {patch.slot_idx} not found or has no caption",
        )
    return {"ok": True}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str) -> dict:
    if not kb_store.delete_template(template_id):
        raise HTTPException(404, f"template {template_id} not found")
    return {"ok": True}


@router.get("/templates/{template_id}/events")
def template_events(template_id: str) -> dict:
    """Replay the extract task's VisionEvents by reading the JSONL.

    Uses ``last_extract_task_id`` on the template row → event_bus.replay
    (same underlying file the live SSE endpoint reads). Returns ``[]``
    when no recorded extract task is linked (older templates / Phase 0.5
    seeds).
    """
    t = kb_store.get_template(template_id)
    if not t:
        raise HTTPException(404, f"template {template_id} not found")
    task_id = t.get("last_extract_task_id")
    if not task_id:
        return {"task_id": None, "events": []}
    events = get_event_bus().replay(task_id)
    return {
        "task_id": task_id,
        "events": [e.model_dump(mode="json") for e in events],
    }
