"""LLM/VLM client protocol (D13) — Phase 1A real implementation.

Every AI client method:
1. Accepts ``stage``, ``task_id``, ``ir_target_template`` and a pydantic
   ``schema`` for structured output validation;
2. Times itself with ``time.perf_counter()`` and writes ``duration_ms`` onto
   the emitted VisionEvent — caller code is zero-touch;
3. Returns ``tuple[BaseModel, list[VisionEvent]]`` so callers can chain
   parent_event_id without re-querying the bus.

Two real adapters share one base:
- :class:`OpenAICompatClient` talks to any ``/v1/chat/completions`` endpoint
  (Qwen-VL via DashScope, GPT-4o, vLLM/Ollama).
- :class:`AnthropicClient` talks to ``/v1/messages`` natively (no SDK — same
  ``httpx`` plumbing keeps deps thin).

Defensive fallback: when ``LLM_API_KEY`` is missing or the upstream errors
through three retries, the call returns a deterministic stub response (a
default-constructed schema) and emits a ``severity="warning"`` VisionEvent so
the workbench surfaces the degradation. CI / unit tests therefore run without
network access.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger

log = get_logger(__name__)


class FrameRef(BaseModel):
    """Reference to a sampled key-frame on disk.

    ``url`` is a DATA_ROOT-relative POSIX path (e.g. ``samples/sid/extracted/frames/1.20.jpg``).
    The client layer resolves it to either a local file (for base64 inlining)
    or an absolute ``{BACKEND_URL}/data/<rel>`` URL when the upstream supports
    remote URLs.
    """

    ts: float
    url: str
    scene_idx: int | None = None


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LLMClient(ABC):
    """Abstract client. Concrete subclasses implement chat_vision/chat_text."""

    @abstractmethod
    async def chat_vision(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        frames: Sequence[FrameRef] | None,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        parent_event_id: str | None = None,
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]: ...

    @abstractmethod
    async def chat_text(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        parent_event_id: str | None = None,
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Retry plan for the inner provider call. Backoff is intentionally short so a
# fallback path lands quickly; real production tuning belongs to the caller.
_RETRY_DELAYS = (0.5, 2.0, 6.0)


def _is_retryable(exc: BaseException) -> bool:
    """Classify a provider exception as retryable.

    The split is the difference between "the upstream is having a moment"
    (5xx, timeout, connection reset, JSON-parse glitch) and "the request
    itself is wrong" (4xx auth / shape errors). Retrying the latter is
    pure latency cost — the response won't change.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    if isinstance(
        exc,
        httpx.TimeoutException
        | httpx.ConnectError
        | httpx.ReadError
        | httpx.WriteError
        | httpx.RemoteProtocolError,
    ):
        return True
    # Schema/JSON parse failure — give the model one more shot before giving up.
    return isinstance(exc, ValueError)


def _construct_default(schema: type[BaseModel]) -> BaseModel:
    """Best-effort default instance for fallback returns.

    ``schema()`` works when every field has a default; otherwise we use
    ``model_construct`` (skip validation) so callers still receive a typed
    object even when the fallback can't fabricate plausible content.
    """
    try:
        return schema()
    except Exception:  # noqa: BLE001
        return schema.model_construct()


def _extract_json(content: str) -> dict | list | None:
    """Pull the first balanced JSON object/array out of a model reply.

    Many providers wrap JSON in code fences or chat boilerplate even when we
    ask for raw output. Stripping by character class is more robust than
    regex with nested braces.
    """
    if not content:
        return None
    s = content.strip()
    if s.startswith("```"):
        # ``` ... ``` or ```json ... ```
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    # Find the outermost { ... } or [ ... ]
    start = -1
    open_ch = ""
    for i, c in enumerate(s):
        if c in "{[":
            start = i
            open_ch = c
            break
    if start == -1:
        return None
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    end = -1
    for i in range(start, len(s)):
        if s[i] == open_ch:
            depth += 1
        elif s[i] == close_ch:
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return None
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None


def _file_to_data_url(path: Path) -> str:
    """Return a ``data:image/jpeg;base64,...`` URL for inlining a frame."""
    raw = path.read_bytes()
    mime = "image/jpeg"
    suffix = path.suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix in (".webp",):
        mime = "image/webp"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _resolve_frame(frame: FrameRef) -> tuple[Path | None, str]:
    """Return (local_path, public_url). Public URL is BACKEND_URL+/data prefixed."""
    settings = get_settings()
    p = Path(frame.url)
    if p.is_absolute():
        return p, frame.url
    # DATA_ROOT-relative
    abs_path = settings.resolve(frame.url)
    public = f"{settings.backend_url.rstrip('/')}/data/{frame.url.lstrip('/')}"
    return abs_path if abs_path.exists() else None, public


def _attach_frames_openai(
    messages: list[dict[str, Any]], frames: Sequence[FrameRef] | None
) -> list[dict[str, Any]]:
    """Inline frames as ``image_url`` parts on the first user message.

    Uses base64 data URLs when the file exists locally, otherwise the
    public ``{BACKEND_URL}/data/...`` URL — DashScope and GPT-4o accept both.
    """
    if not frames:
        return messages
    parts: list[dict[str, Any]] = []
    for f in frames:
        local, public = _resolve_frame(f)
        url = _file_to_data_url(local) if local is not None else public
        parts.append({"type": "image_url", "image_url": {"url": url}})
    out: list[dict[str, Any]] = []
    user_done = False
    for m in messages:
        if not user_done and m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                merged = parts + [{"type": "text", "text": content}]
            else:
                merged = parts + list(content)
            out.append({**m, "content": merged})
            user_done = True
        else:
            out.append(dict(m))
    if not user_done:
        out.append({"role": "user", "content": parts})
    return out


def _attach_frames_anthropic(
    messages: list[dict[str, Any]], frames: Sequence[FrameRef] | None
) -> list[dict[str, Any]]:
    """Inline frames as ``image`` blocks on the first user message (base64 only).

    Anthropic's image blocks need ``base64`` source; URL ingestion isn't
    universal across all model versions. We require local file presence.
    """
    if not frames:
        return messages
    parts: list[dict[str, Any]] = []
    for f in frames:
        local, _ = _resolve_frame(f)
        if local is None or not local.exists():
            log.warning("anthropic.frame_missing", path=f.url)
            continue
        suffix = local.suffix.lower()
        media_type = (
            "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
        )
        data = base64.b64encode(local.read_bytes()).decode("ascii")
        parts.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": data},
            }
        )
    out: list[dict[str, Any]] = []
    user_done = False
    for m in messages:
        if not user_done and m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                merged = parts + [{"type": "text", "text": content}]
            else:
                merged = parts + list(content)
            out.append({**m, "content": merged})
            user_done = True
        else:
            out.append(dict(m))
    if not user_done:
        out.append({"role": "user", "content": parts})
    return out


def _summarise_for_label(parsed: BaseModel | None, fallback: str) -> str:
    """Pick a short human label for the call-level VisionEvent.

    If the schema exposes ``__workbench_label__()``, use it; otherwise fall
    back to "<stage> N items" when the schema has a top-level list field.
    """
    if parsed is None:
        return fallback
    label = getattr(parsed, "__workbench_label__", None)
    if callable(label):
        try:
            return str(label())
        except Exception:  # noqa: BLE001
            pass
    for name, _ in type(parsed).model_fields.items():
        v = getattr(parsed, name, None)
        if isinstance(v, list):
            return f"{fallback} · {len(v)} items"
    return fallback


# ---------------------------------------------------------------------------
# Real client base
# ---------------------------------------------------------------------------


class _RealClientBase(LLMClient):
    """Shared retry / fallback / event-emission for the two providers.

    Subclasses implement two adapter methods:
    - :meth:`_call_vision_provider` → raw HTTP round-trip returning
      ``(text_content, usage_tokens, model_used)``.
    - :meth:`_call_text_provider` → same shape, no images.

    Falls back to a deterministic stub when ``LLM_API_KEY`` (or the
    provider-specific key) is absent, or when all retries fail.
    """

    provider_name: str = "real"

    @abstractmethod
    async def _call_vision_provider(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        frames: Sequence[FrameRef] | None,
    ) -> tuple[str, int | None, str]: ...

    @abstractmethod
    async def _call_text_provider(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
    ) -> tuple[str, int | None, str]: ...

    @abstractmethod
    def _has_credentials(self) -> bool: ...

    # ------------------------------------------------------------------
    # Public API (chat_vision / chat_text share most logic)
    # ------------------------------------------------------------------
    async def chat_vision(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        frames: Sequence[FrameRef] | None,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        parent_event_id: str | None = None,
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        return await self._invoke(
            kind="vision",
            messages=list(messages),
            model=model,
            stage=stage,
            task_id=task_id,
            frames=frames,
            ir_target_template=ir_target_template,
            schema=schema,
            parent_event_id=parent_event_id,
            silent=silent,
        )

    async def chat_text(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        parent_event_id: str | None = None,
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        return await self._invoke(
            kind="text",
            messages=list(messages),
            model=model,
            stage=stage,
            task_id=task_id,
            frames=None,
            ir_target_template=ir_target_template,
            schema=schema,
            parent_event_id=parent_event_id,
            silent=silent,
        )

    async def _invoke(
        self,
        *,
        kind: Literal["vision", "text"],
        messages: list[dict[str, Any]],
        model: str,
        stage: str,
        task_id: str,
        frames: Sequence[FrameRef] | None,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        parent_event_id: str | None,
        silent: bool,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        started = time.perf_counter()
        source = "vlm" if kind == "vision" else "text_llm"
        if not self._has_credentials():
            return await self._fallback(
                source=source,
                stage=stage,
                task_id=task_id,
                model=model,
                frames=frames,
                ir_target=ir_target_template,
                schema=schema,
                started_at=started,
                parent_event_id=parent_event_id,
                silent=silent,
                reason="missing API credentials",
            )
        last_err: str | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                if kind == "vision":
                    text, tokens, model_used = await self._call_vision_provider(
                        messages, model=model, frames=frames
                    )
                else:
                    text, tokens, model_used = await self._call_text_provider(messages, model=model)
                payload = _extract_json(text)
                if payload is None:
                    raise ValueError(f"upstream returned non-JSON: {text[:200]!r}")
                parsed = schema.model_validate(payload)
                duration_ms = int((time.perf_counter() - started) * 1000)
                event = self._build_event(
                    source=source,
                    stage=stage,
                    task_id=task_id,
                    model=model_used,
                    frames=frames,
                    ir_target=ir_target_template,
                    parsed=parsed,
                    payload=payload,
                    duration_ms=duration_ms,
                    cost_tokens=tokens,
                    parent_event_id=parent_event_id,
                    severity="info",
                )
                if not silent:
                    await get_event_bus().publish(task_id, event)
                return parsed, [event]
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                retryable = _is_retryable(e)
                log.warning(
                    "llm.retry" if retryable else "llm.non_retryable",
                    provider=self.provider_name,
                    stage=stage,
                    attempt=attempt,
                    error=last_err[:200],
                )
                if not retryable:
                    # 4xx / unknown failures won't fix on retry; bail to fallback.
                    break
                if attempt < len(_RETRY_DELAYS) - 1:
                    await asyncio.sleep(delay)
        return await self._fallback(
            source=source,
            stage=stage,
            task_id=task_id,
            model=model,
            frames=frames,
            ir_target=ir_target_template,
            schema=schema,
            started_at=started,
            parent_event_id=parent_event_id,
            silent=silent,
            reason=f"upstream failed: {last_err}",
        )

    # ------------------------------------------------------------------
    # Event construction
    # ------------------------------------------------------------------
    def _build_event(
        self,
        *,
        source: str,
        stage: str,
        task_id: str,
        model: str,
        frames: Sequence[FrameRef] | None,
        ir_target: IRTarget | None,
        parsed: BaseModel,
        payload: dict | list | None,
        duration_ms: int,
        cost_tokens: int | None,
        parent_event_id: str | None,
        severity: Literal["info", "warning", "error"],
    ) -> VisionEvent:
        frame = frames[0] if frames else None
        # ir_value: if the call has an ir_target, we set the parsed result so
        # the workbench's right pane fills the targeted field. Subcaps that
        # want per-entity events emit them via the event bus directly.
        ir_value: Any = None
        if ir_target is not None:
            ir_value = parsed.model_dump(mode="json") if parsed is not None else payload
        return VisionEvent(
            task_id=task_id,
            source=source,  # type: ignore[arg-type]
            model_used=model,
            stage=stage,
            frame_ts=frame.ts if frame else None,
            frame_url=f"/data/{frame.url.lstrip('/')}" if frame else None,
            bbox_norm=None,
            semantic_label=_summarise_for_label(parsed, stage),
            reasoning="",
            confidence=1.0,
            ir_target=ir_target,
            ir_value=ir_value,
            parent_event_id=parent_event_id,
            duration_ms=duration_ms,
            cost_tokens=cost_tokens,
            severity=severity,
        )

    async def _fallback(
        self,
        *,
        source: str,
        stage: str,
        task_id: str,
        model: str,
        frames: Sequence[FrameRef] | None,
        ir_target: IRTarget | None,
        schema: type[BaseModel],
        started_at: float,
        parent_event_id: str | None,
        silent: bool,
        reason: str,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        """Emit a warning event + return a default-constructed schema."""
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        parsed = _construct_default(schema)
        frame = frames[0] if frames else None
        event = VisionEvent(
            task_id=task_id,
            source=source,  # type: ignore[arg-type]
            model_used=f"{model}#stub",
            stage=stage,
            frame_ts=frame.ts if frame else None,
            frame_url=f"/data/{frame.url.lstrip('/')}" if frame else None,
            bbox_norm=None,
            semantic_label=f"[fallback] {stage}",
            reasoning=f"未能调用真实模型，回退至 deterministic stub。原因：{reason}",
            confidence=0.0,
            ir_target=ir_target,
            ir_value=None,
            parent_event_id=parent_event_id,
            duration_ms=duration_ms,
            cost_tokens=None,
            severity="warning",
        )
        if not silent:
            await get_event_bus().publish(task_id, event)
        return parsed, [event]


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter
# ---------------------------------------------------------------------------


class OpenAICompatClient(_RealClientBase):
    """Talks to ``/v1/chat/completions`` (Qwen-VL via DashScope, GPT-4o, vLLM).

    Uses ``response_format={"type": "json_object"}`` when the upstream
    supports it; the JSON extractor in :func:`_extract_json` is robust to
    providers that ignore the hint.
    """

    provider_name = "openai_compat"

    def _has_credentials(self) -> bool:
        s = get_settings()
        return bool(s.llm_base_url and s.llm_api_key)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        s = get_settings()
        url = s.llm_base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            r = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {s.llm_api_key}"},
            )
            r.raise_for_status()
            return r.json()

    async def _call_vision_provider(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        frames: Sequence[FrameRef] | None,
    ) -> tuple[str, int | None, str]:
        body = {
            "model": model,
            "messages": _attach_frames_openai(messages, frames),
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        data = await self._post(body)
        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens")
        return text, tokens, data.get("model", model)

    async def _call_text_provider(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
    ) -> tuple[str, int | None, str]:
        body = {
            "model": model,
            "messages": list(messages),
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        data = await self._post(body)
        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens")
        return text, tokens, data.get("model", model)


# ---------------------------------------------------------------------------
# Anthropic native adapter
# ---------------------------------------------------------------------------


class AnthropicClient(_RealClientBase):
    """Talks to ``https://api.anthropic.com/v1/messages`` directly via httpx.

    Avoids the ``anthropic`` SDK to keep the dependency footprint thin —
    the API is stable and JSON-only.
    """

    provider_name = "anthropic"

    def _has_credentials(self) -> bool:
        return bool(get_settings().anthropic_api_key)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        s = get_settings()
        url = "https://api.anthropic.com/v1/messages"
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            r = await client.post(
                url,
                json=body,
                headers={
                    "x-api-key": s.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            r.raise_for_status()
            return r.json()

    @staticmethod
    def _split_system(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict]]:
        """Anthropic puts ``system`` at top level, not in messages list."""
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        sys_str = "\n\n".join(c for c in system_parts if isinstance(c, str)) or None
        return sys_str, rest

    async def _call_vision_provider(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        frames: Sequence[FrameRef] | None,
    ) -> tuple[str, int | None, str]:
        sys_str, rest = self._split_system(messages)
        body: dict[str, Any] = {
            "model": model,
            "messages": _attach_frames_anthropic(rest, frames),
            "max_tokens": 4096,
            "temperature": 0.0,
        }
        if sys_str:
            body["system"] = sys_str
        data = await self._post(body)
        text = "".join(
            blk.get("text", "") for blk in data.get("content", []) if blk.get("type") == "text"
        )
        usage = data.get("usage", {})
        tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
        return text, tokens or None, data.get("model", model)

    async def _call_text_provider(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
    ) -> tuple[str, int | None, str]:
        sys_str, rest = self._split_system(messages)
        body: dict[str, Any] = {
            "model": model,
            "messages": rest,
            "max_tokens": 4096,
            "temperature": 0.0,
        }
        if sys_str:
            body["system"] = sys_str
        data = await self._post(body)
        text = "".join(
            blk.get("text", "") for blk in data.get("content", []) if blk.get("type") == "text"
        )
        usage = data.get("usage", {})
        tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
        return text, tokens or None, data.get("model", model)


# ---------------------------------------------------------------------------
# Dual-check (for stages listed in DUAL_CHECK_STAGES)
# ---------------------------------------------------------------------------


def _structurally_equal(a: BaseModel, b: BaseModel) -> bool:
    """Compare two structured outputs by JSON dump (ignore floats < 1e-6 drift)."""
    da = a.model_dump(mode="json")
    db = b.model_dump(mode="json")
    return _json_equal(da, db)


def _json_equal(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_json_equal(x, y) for x, y in zip(a, b, strict=False))
    if isinstance(a, float):
        return abs(a - b) < 1e-6
    return a == b


def _is_fallback_event(events: list[VisionEvent]) -> bool:
    """A single warning event from chat_vision = fallback path."""
    return bool(events) and events[0].severity == "warning"


async def chat_vision_dual(
    *,
    primary: LLMClient,
    secondary: LLMClient,
    messages: Sequence[dict[str, Any]],
    model_primary: str,
    model_secondary: str,
    stage: str,
    task_id: str,
    frames: Sequence[FrameRef] | None,
    ir_target_template: IRTarget | None,
    schema: type[BaseModel],
    parent_event_id: str | None = None,
) -> tuple[BaseModel, list[VisionEvent]]:
    """Run the same VLM call against two providers concurrently; warn on mismatch.

    Returns the primary result and the primary's events. When the structured
    output of both providers disagrees, an additional ``confidence_warning``
    event is appended so the workbench can flag the call for human review.

    Cross-check is suppressed when either side fell back (no API key,
    upstream error). A fallback returns a default-constructed schema —
    comparing it against the other side's real result would manufacture
    disagreement out of thin air. This is the first-principles fix for
    the false-positive that bit Phase 1A's first review.

    Concurrency: both calls launch in parallel via :func:`asyncio.gather`.
    Wall-clock = max(primary, secondary), not sum — the cross-check
    latency cost is what gates this behind ``DUAL_CHECK_STAGES`` in
    ``.env`` instead of always-on.
    """
    primary_task = primary.chat_vision(
        messages,
        model=model_primary,
        stage=stage,
        task_id=task_id,
        frames=frames,
        ir_target_template=ir_target_template,
        schema=schema,
        parent_event_id=parent_event_id,
    )
    secondary_task = secondary.chat_vision(
        messages,
        model=model_secondary,
        stage=stage,
        task_id=task_id,
        frames=frames,
        ir_target_template=ir_target_template,
        schema=schema,
        parent_event_id=parent_event_id,
        silent=True,  # only the primary's call event hits the workbench
    )
    primary_result, secondary_result = await asyncio.gather(
        primary_task, secondary_task, return_exceptions=True
    )

    if isinstance(primary_result, BaseException):
        # The primary pathway is supposed to internally fall back rather than
        # raise, but defend regardless: re-raise so callers see the bug.
        raise primary_result
    res_a, evs_a = primary_result

    if isinstance(secondary_result, BaseException):
        log.warning("dual_check.secondary_raised", stage=stage, error=str(secondary_result))
        return res_a, evs_a
    res_b, evs_b = secondary_result

    if _is_fallback_event(evs_a) or _is_fallback_event(evs_b):
        # One side never reached its provider; comparison would compare a
        # real answer to a default-constructed one. Skip cross-check, keep
        # the primary as-is (its warning event already surfaces the issue).
        return res_a, evs_a

    if _structurally_equal(res_a, res_b):
        return res_a, evs_a

    warning = VisionEvent(
        task_id=task_id,
        source="vlm",
        model_used=model_secondary,
        stage=stage,
        semantic_label=f"双模 cross-check 异议 · {stage}",
        reasoning=(
            f"主模 ({model_primary}) 与备模 ({model_secondary}) 结构化字段不一致。"
            "已写入主模结果，请在工作台复核。"
        ),
        confidence=0.5,
        ir_target=ir_target_template,
        ir_value=res_b.model_dump(mode="json"),
        parent_event_id=evs_a[0].event_id if evs_a else parent_event_id,
        confidence_warning=True,
        severity="warning",
    )
    await get_event_bus().publish(task_id, warning)
    return res_a, [*evs_a, warning]


# ---------------------------------------------------------------------------
# Factory — provider routing + dual-check awareness
# ---------------------------------------------------------------------------

# Stage prefix → provider routing for ``MODEL_PROVIDER=mixed``. Adjust as
# needed once we benchmark Phase 1A across providers.
PROVIDER_ROUTING_TABLE: dict[str, str] = {
    "1A.": "openai",  # Qwen-VL is the cheapest accurate Chinese VLM
    "1B.tagging": "anthropic",
    "1B.sanity_check": "anthropic",
    "2.recommend": "anthropic",
    "2.5.": "anthropic",
    "3.step03": "openai",
    "3.step04": "anthropic",
    "3.step06": "anthropic",
}


def get_llm_client(provider: str | None = None, *, stage: str | None = None) -> LLMClient:
    """Return a client for the requested provider (or the configured default).

    When ``MODEL_PROVIDER=mixed`` and ``stage`` is supplied, route via
    :data:`PROVIDER_ROUTING_TABLE` (longest matching prefix wins). Otherwise
    obey the explicit provider or the env default.
    """
    p = provider or get_settings().model_provider
    if p == "mixed" and stage:
        match = ""
        chosen = "openai"
        for prefix, target in PROVIDER_ROUTING_TABLE.items():
            if stage.startswith(prefix) and len(prefix) > len(match):
                match = prefix
                chosen = target
        p = chosen
    if p == "anthropic":
        return AnthropicClient()
    return OpenAICompatClient()


def should_dual_check(stage: str) -> bool:
    """Whether ``stage`` is configured for ``DUAL_CHECK_STAGES`` cross-check."""
    return stage in get_settings().dual_check_stages
