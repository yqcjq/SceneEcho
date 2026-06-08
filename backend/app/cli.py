"""Dev-only CLI for ingesting local media into samples/ and projects/.

Gated by ENABLE_CLI_INGEST=true to avoid exposing arbitrary file reads.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import typer

from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.render import ffmpeg as ffx

app_cli = typer.Typer(help="SceneEcho dev CLI")
log = get_logger(__name__)


def _require_enabled() -> None:
    if not get_settings().enable_cli_ingest:
        typer.echo(
            "CLI ingest disabled. Set ENABLE_CLI_INGEST=true in .env to enable.",
            err=True,
        )
        raise typer.Exit(code=2)


def _ingest(kind: str, src: Path, name: str | None) -> dict:
    settings = get_settings()
    if not src.exists():
        typer.echo(f"source not found: {src}", err=True)
        raise typer.Exit(1)
    prefix = "smp" if kind == "samples" else "prj"
    new_id = f"{prefix}_{uuid.uuid4().hex[:10]}"
    base = settings.data_root / kind / new_id
    base.mkdir(parents=True, exist_ok=True)
    dst = base / ("source.mp4" if kind == "samples" else "user_material.mp4")
    shutil.copy2(src, dst)
    norm = base / "normalized.mp4"
    info = ffx.normalize(dst, norm)
    if kind == "samples":
        try:
            ffx.extract_thumbnail(norm, base / "thumbnail.jpg", at=0.1)
        except Exception as e:  # noqa: BLE001
            log.warning("thumbnail_failed", error=str(e))
    typer.echo(f"ingested {kind} {new_id} from {src.name}")
    return {"id": new_id, "path": str(base), "info": info.get("format", {})}


@app_cli.command("ingest-sample")
def ingest_sample(src: Path, name: str | None = typer.Option(None, "--name")) -> None:
    """Ingest a local MP4 as a sample."""
    configure_logging(get_settings().log_level)
    _require_enabled()
    _ingest("samples", src, name)


@app_cli.command("ingest-project")
def ingest_project(src: Path, name: str | None = typer.Option(None, "--name")) -> None:
    """Ingest a local MP4 as a user project material."""
    configure_logging(get_settings().log_level)
    _require_enabled()
    _ingest("projects", src, name)


if __name__ == "__main__":
    app_cli()
