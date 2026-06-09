"""FastAPI entry point for SceneEcho backend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import tasks_store
from app.api import dev_workbench, events, lab, projects, samples, tasks, templates
from app.config import get_settings
from app.event_bus import get_event_bus
from app.kb import store as kb_store
from app.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)


def _init_data_tree() -> None:
    root = settings.data_root
    for sub in (
        "samples",
        "projects",
        "system",
        "aigc",
        "logs",
        "system/bgm_pool",
        "system/fonts",
        "system/stickers_reference",
        "system/luts",
        "system/models",
        "system/dev_events",
        "aigc/stickers",
        "aigc/broll",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    _init_data_tree()
    tasks_store.init_db()
    kb_store.init_db()
    bus = get_event_bus()
    # Inject the tasks-store reader so event_bus never imports tasks_store
    # — the layered architecture stays unidirectional (event_bus is below
    # tasks_store in the dependency graph).
    bus.set_lookup_callback(tasks_store.get_task)
    app.state.event_bus = bus
    log.info(
        "backend_started",
        data_root=str(settings.data_root),
        enable_dev_mock=settings.enable_dev_mock,
    )
    yield
    log.info("backend_stopped")


app = FastAPI(title="SceneEcho Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(samples.router, prefix="/api", tags=["samples"])
app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(templates.router, prefix="/api", tags=["templates"])

if settings.enable_dev_mock:
    app.include_router(dev_workbench.router, prefix="/api", tags=["dev"])
    app.include_router(lab.router, prefix="/api", tags=["lab"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "backend"}


# Serve DATA_ROOT for media playback (dev convenience).
settings.data_root.mkdir(parents=True, exist_ok=True)
app.mount("/data", StaticFiles(directory=str(settings.data_root)), name="data")
