"""5.aigc · AIGC generation layer (Phase 5 B-roll subset, ISS-028).

Two public coroutines, both following the D9 client contract
``(...) -> tuple[str | None, list[VisionEvent]]`` (the path replaces the
usual ``BaseModel`` — generation produces a file, not a structured doc):

- :func:`generate_broll` — third-party text-to-image for "AI生成画面" slots.
  The image is then converted by ffmpeg into a duration-second mp4 so the
  consumer (apply/fill writes ``aigc_broll_path``; renderer plays it via
  ``<OffthreadVideo>``) stays a pure video segment. This is intentional —
  motion comes from the slot's zoom_keyframes at render time, not from the
  generation API. Keeps the implementation portable across image-gen
  providers (Stable Diffusion / Flux / DALL-E / Kolors / 智谱 CogView).
- :func:`generate_sticker_image` — text-to-image for template stickers.
  Implemented because it shares the provider account / hash-cache / event
  protocol with B-roll (marginal cost ≈ 0), but **not yet consumed** in
  any apply path (decisions/013 代价 5).

Design:

- **Hash cache** (``_cache_path``): identical (prompt, style, duration)
  never re-pays the API. Cache key = sha256 over those inputs; files land
  in ``data/aigc/{broll,stickers}/{hash}.{mp4,png}`` (永久缓存, D2 POSIX
  rel path returned to callers). The B-roll cache stores the *converted*
  mp4 — re-running with the same prompt + same duration is a single disk
  read.
- **Typed errors** (:class:`AIGCProviderError` + subclasses): every failure
  mode raises one of these; ``apply/fill.py`` catches the base class and
  degrades the slot to the ``reuse`` strategy (D28 — never block the
  pipeline). Empty ``AIGC_BROLL_PROVIDER`` raises ``AIGCMissingCredentials``
  rather than returning ``None`` silently, so the apply side can record
  *why* no B-roll was produced.
- **Events** (D13): one ``5.aigc.broll`` / ``5.aigc.sticker`` VisionEvent
  per call, carrying prompt summary + cache_hit + elapsed + provider. The
  provider submodule never touches ``event_bus`` — emission is centralised
  here so the D13 guard has a single surface to verify.
- **Retry** reuses ``llm.client._is_retryable``: transient httpx 5xx /
  timeout / network errors retry with the same ``_RETRY_DELAYS`` ladder as
  ``_invoke``; semantic failures (missing key / quota / content rejected /
  4xx) raise immediately.

Provider modules live in ``aigc_providers/{name}.py`` and expose
``get_provider()``; ``AIGC_BROLL_PROVIDER`` selects by module name.
Providers implement only ``generate_image`` — the B-roll → image-then-ffmpeg
pipeline is owned by this module so swapping providers is a one-file change.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import time
from pathlib import Path
from typing import Protocol

from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import _RETRY_DELAYS, _is_retryable
from app.logging import get_logger
from app.render.ffmpeg import image_to_video

log = get_logger(__name__)

STAGE_BROLL = "5.aigc.broll"
STAGE_STICKER = "5.aigc.sticker"


# ---------------------------------------------------------------------------
# Typed errors — apply/fill catches the base class and degrades to reuse.
# ---------------------------------------------------------------------------


class AIGCProviderError(Exception):
    """Base class. ``apply/fill`` catches this to fall back to ``reuse``."""


class AIGCMissingCredentials(AIGCProviderError):
    """No provider configured, or the provider's API key is absent."""


class AIGCQuotaExceeded(AIGCProviderError):
    """Provider returned a quota / rate-limit signal (HTTP 429)."""


class AIGCAPIError(AIGCProviderError):
    """5xx / timeout / network / malformed response after retries exhausted."""


class AIGCContentRejected(AIGCProviderError):
    """Provider's built-in moderation rejected the prompt."""


class BrollProvider(Protocol):
    """Synchronous text-to-image provider surface.

    Both the B-roll path (image → ffmpeg → mp4) and the sticker path
    (image → cached png) call ``generate_image``. Providers raise the
    AIGC* hierarchy for classified failures and let raw httpx errors
    propagate for transient ones (so the retry layer's ``_is_retryable``
    can classify them). They never call ``event_bus.publish``.
    """

    async def generate_image(
        self, prompt: str, *, style_keywords: list[str]
    ) -> bytes: ...


# ---------------------------------------------------------------------------
# Cache helpers (shared by broll + sticker)
# ---------------------------------------------------------------------------


def _cache_key(prompt: str, style_hint: dict | None, duration_sec: float | None) -> str:
    """Stable sha256 over (prompt, sorted style, rounded duration).

    Sorting the style items + rounding duration to 2dp means the same
    semantic request always lands on the same file — different durations
    of the same prompt get distinct caches (so a 3s and a 6s B-roll never
    collide). ``ensure_ascii=False`` keeps Chinese prompts readable in the
    hashed payload (the hash is over bytes either way).
    """
    payload = json.dumps(
        {
            "prompt": prompt,
            "style": sorted((str(k), str(v)) for k, v in (style_hint or {}).items()),
            "duration": None if duration_sec is None else round(float(duration_sec), 2),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cache_path(kind: str, key: str, ext: str) -> Path:
    """Absolute path for a cached asset under ``data/aigc/{kind}/{key}{ext}``."""
    return get_settings().data_root / "aigc" / kind / f"{key}{ext}"


def _rel(abs_path: Path) -> str:
    """DATA_ROOT-relative POSIX path (D2) for writing into the IR."""
    return str(abs_path.relative_to(get_settings().data_root)).replace("\\", "/")


def _get_broll_provider(name: str) -> BrollProvider:
    """Resolve ``AIGC_BROLL_PROVIDER`` to a provider instance by module name.

    ``aigc_providers/{name}.py`` must expose ``get_provider()``. Unknown
    names raise ``AIGCAPIError`` (a configuration error, surfaced like any
    other provider failure so the slot degrades to reuse).
    """
    try:
        mod = importlib.import_module(f"app.agent.aigc_providers.{name}")
    except ImportError as e:
        raise AIGCAPIError(f"unknown AIGC provider '{name}': {e}") from e
    factory = getattr(mod, "get_provider", None)
    if factory is None:
        raise AIGCAPIError(f"AIGC provider '{name}' missing get_provider()")
    return factory()


async def _retry(coro_factory):
    """Run ``coro_factory()`` with the same retry ladder as ``llm._invoke``.

    ``coro_factory`` returns a *fresh* coroutine each call (can't re-await a
    spent one). Transient errors (5xx / timeout / network, via
    ``_is_retryable``) retry; everything else raises immediately.
    """
    last: BaseException | None = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return await coro_factory()
        except Exception as e:  # noqa: BLE001
            last = e
            if not _is_retryable(e) or attempt >= len(_RETRY_DELAYS):
                raise
            await asyncio.sleep(_RETRY_DELAYS[attempt])
    if last is not None:  # pragma: no cover — loop always returns or raises
        raise last
    raise AIGCAPIError("retry exhausted with no result")  # pragma: no cover


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_broll(
    prompt: str,
    duration_sec: float,
    style_hint: dict,
    project_id: str,
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[str | None, list[VisionEvent]]:
    """Generate (or cache-hit) a B-roll mp4 for an "AI生成画面" slot.

    Pipeline: provider.generate_image → bytes → ffmpeg loops the still into
    a duration-second mp4 → cache the mp4 at ``data/aigc/broll/{hash}.mp4``.
    The slot's ``style.visual.zoom_keyframes`` provide motion at render
    time, so the generated mp4 is intentionally a static loop.

    Returns ``(rel_path, events)`` where ``rel_path`` is a DATA_ROOT-relative
    POSIX path. Raises an ``AIGCProviderError`` subclass on any failure so
    ``apply/fill`` can fall back to the ``reuse`` strategy and record the
    reason in ``ProjectIR.degraded``.

    ``duration_sec`` is clamped to ``settings.aigc_broll_max_duration_sec``
    (decisions/013 代价 2 — bound the worst-case static-loop length so
    AI 补画面 doesn't dominate the timeline). ``style_hint`` carries
    ``style_keywords`` (passed to the provider) plus any template tags the
    caller wants reflected in the cache key.
    """
    s = get_settings()
    bus = get_event_bus()
    started = time.perf_counter()

    requested = float(duration_sec)
    duration = min(requested, float(s.aigc_broll_max_duration_sec))
    if duration < requested:
        log.warning(
            "aigc.broll_duration_clamped",
            requested=requested,
            clamped=duration,
            project_id=project_id,
        )

    if not s.aigc_broll_provider:
        raise AIGCMissingCredentials(
            "AIGC_BROLL_PROVIDER not configured — set it to enable AI B-roll"
        )

    style_keywords = [str(w) for w in (style_hint or {}).get("style_keywords", [])]
    key = _cache_key(prompt, style_hint, duration)
    abs_path = _cache_path("broll", key, ".mp4")
    rel = _rel(abs_path)
    canvas = (style_hint or {}).get("canvas") or {}
    canvas_w = int(canvas.get("width", 1080))
    canvas_h = int(canvas.get("height", 1920))
    canvas_fps = int(canvas.get("fps", 30))

    def _emit(cache_hit: bool) -> VisionEvent:
        return VisionEvent(
            task_id=task_id,
            source="system",
            model_used=f"{s.aigc_broll_provider}#image2video",
            stage=STAGE_BROLL,
            semantic_label=(
                f"AI 补画面 · {'缓存命中' if cache_hit else '生成完成'} · "
                f"{duration:.1f}s · {Path(rel).name}"
            ),
            reasoning=(
                f"provider={s.aigc_broll_provider}; cache_hit={cache_hit}; "
                f"duration={duration:.2f}s (requested {requested:.2f}); "
                f"style_keywords={style_keywords}; "
                f"prompt={prompt[:100]!r}{'…' if len(prompt) > 100 else ''}"
            ),
            confidence=1.0,
            media_ts_range=(0.0, duration),
            ir_target=IRTarget(
                ir_type="ProjectIR", path="sections.0.segments", op="set"
            ),
            ir_value=rel,
            parent_event_id=parent_event_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    if abs_path.exists():
        ev = _emit(cache_hit=True)
        await bus.publish(task_id, ev)
        return rel, [ev]

    provider = _get_broll_provider(s.aigc_broll_provider)
    image_bytes = await _retry(
        lambda: provider.generate_image(prompt, style_keywords=style_keywords)
    )
    if not image_bytes:
        raise AIGCAPIError("provider returned empty image payload")

    def _convert() -> None:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        # Write the source image alongside the cache mp4 (same stem, .png
        # suffix). Cleanup in finally so a failed ffmpeg run doesn't leave
        # orphaned bytes that masquerade as cached output on next call.
        tmp_img = abs_path.with_suffix(".png")
        tmp_img.write_bytes(image_bytes)
        try:
            image_to_video(
                tmp_img,
                abs_path,
                duration_sec=duration,
                width=canvas_w,
                height=canvas_h,
                fps=canvas_fps,
            )
        finally:
            tmp_img.unlink(missing_ok=True)

    try:
        await asyncio.to_thread(_convert)
    except Exception as e:  # noqa: BLE001 — translate ffmpeg / OS errors so fill.py degrades
        raise AIGCAPIError(
            f"image-to-video conversion failed: {type(e).__name__}: {e}"
        ) from e

    ev = _emit(cache_hit=False)
    await bus.publish(task_id, ev)
    return rel, [ev]


async def generate_sticker_image(
    description: str,
    style_hint: dict,
    project_id: str,
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[str | None, list[VisionEvent]]:
    """Generate (or cache-hit) a sticker PNG. Shares provider + cache + event
    protocol with :func:`generate_broll`.

    Returns ``(rel_path, events)`` for ``data/aigc/stickers/{hash}.png``.
    Implemented for completeness (decisions/013 代价 5) but not consumed by
    any apply path yet — the TemplateLibrary "generate stickers" button is
    the future trigger.
    """
    s = get_settings()
    bus = get_event_bus()
    started = time.perf_counter()

    if not s.aigc_broll_provider:
        raise AIGCMissingCredentials(
            "AIGC_BROLL_PROVIDER not configured — set it to enable AI sticker generation"
        )

    style_keywords = [str(w) for w in (style_hint or {}).get("style_keywords", [])]
    key = _cache_key(description, style_hint, None)
    abs_path = _cache_path("stickers", key, ".png")
    rel = _rel(abs_path)

    def _emit(cache_hit: bool) -> VisionEvent:
        return VisionEvent(
            task_id=task_id,
            source="system",
            model_used=f"{s.aigc_broll_provider}#image",
            stage=STAGE_STICKER,
            semantic_label=(
                f"AI 贴纸 · {'缓存命中' if cache_hit else '生成完成'} · {Path(rel).name}"
            ),
            reasoning=(
                f"provider={s.aigc_broll_provider}; cache_hit={cache_hit}; "
                f"style_keywords={style_keywords}; "
                f"description={description[:100]!r}{'…' if len(description) > 100 else ''}"
            ),
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.segments", op="set"),
            ir_value=rel,
            parent_event_id=parent_event_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    if abs_path.exists():
        ev = _emit(cache_hit=True)
        await bus.publish(task_id, ev)
        return rel, [ev]

    provider = _get_broll_provider(s.aigc_broll_provider)
    image_bytes = await _retry(
        lambda: provider.generate_image(description, style_keywords=style_keywords)
    )
    if not image_bytes:
        raise AIGCAPIError("provider returned empty image payload")

    def _write() -> None:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(image_bytes)

    try:
        await asyncio.to_thread(_write)
    except OSError as e:
        raise AIGCAPIError(f"sticker write failed: {type(e).__name__}: {e}") from e

    ev = _emit(cache_hit=False)
    await bus.publish(task_id, ev)
    return rel, [ev]


__all__ = [
    "STAGE_BROLL",
    "STAGE_STICKER",
    "AIGCProviderError",
    "AIGCMissingCredentials",
    "AIGCQuotaExceeded",
    "AIGCAPIError",
    "AIGCContentRejected",
    "BrollProvider",
    "generate_broll",
    "generate_sticker_image",
]
