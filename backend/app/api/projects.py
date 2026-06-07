"""Projects API — Phase 0 placeholder upload."""
from __future__ import annotations

import shutil
import uuid

from fastapi import APIRouter, HTTPException, UploadFile

from app.config import get_settings
from app.logging import get_logger
from app.render import ffmpeg as ffx

router = APIRouter()
log = get_logger(__name__)


@router.post("/projects")
async def upload_project(file: UploadFile) -> dict:
    settings = get_settings()
    project_id = f"prj_{uuid.uuid4().hex[:10]}"
    base = settings.data_root / "projects" / project_id
    base.mkdir(parents=True, exist_ok=True)
    src_path = base / "user_material.mp4"
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    norm_path = base / "normalized.mp4"
    try:
        info = ffx.normalize(src_path, norm_path)
    except Exception as e:  # noqa: BLE001
        log.error("project_normalize_failed", project_id=project_id, error=str(e))
        raise HTTPException(500, f"normalize failed: {e}") from e

    return {
        "project_id": project_id,
        "info": info.get("format", {}),
    }
