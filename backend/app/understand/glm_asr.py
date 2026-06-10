"""2.asr.glm · GLM-ASR-2512 transcription via PPIO gateway.

Reference: https://ppio.com/docs/models/reference-glm-asr

    POST {ASR_BASE_URL}                       # default https://api.ppio.com/v3/glm-asr
        Authorization: Bearer {LLM_API_KEY}
        Content-Type: application/json
    body: {"file": "<base64-of-wav-or-mp3>", "hotwords": [...], "prompt": "..."}
    → {"text": "<完整转录文本>"}

GLM-ASR returns text only — no timestamps. The outer asr.py pipes the text
through wav2vec2 forced alignment to recover word-level timestamps. This
module is the network-IO surface; alignment lives in asr.py so the two
fallback ladders stay in one place.

Limits per PPIO docs: wav/mp3 ≤ 25 MB, audio duration ≤ 30 s. We enforce
both up-front so a too-long clip raises GLMASRTooLong cleanly instead of
getting an opaque mid-call 4xx with no usable error message.
"""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

import httpx

from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger
from app.render.ffmpeg import get_media_info

STAGE = "2.asr.glm"
log = get_logger(__name__)

_MAX_DURATION_SEC = 29.0
_MAX_FILE_BYTES = 24 * 1024 * 1024


class GLMASRError(Exception):
    """Base class — caller (asr.py) catches and degrades to WhisperX."""


class GLMASRTooLong(GLMASRError):
    """Audio duration exceeds GLM-ASR's 30s ceiling."""


class GLMASRTooBig(GLMASRError):
    """Audio file size exceeds GLM-ASR's 25MB ceiling."""


class GLMASRMissingKey(GLMASRError):
    """LLM_API_KEY not configured."""


async def transcribe_glm(
    audio_path: Path,
    *,
    task_id: str,
    hotwords: list[str] | None = None,
    parent_event_id: str | None = None,
) -> str:
    """Transcribe a wav/mp3 file via GLM-ASR-2512. Returns plain text.

    Raises ``GLMASRError`` variants on validation/config/network failures so
    the outer ``asr.py`` degrades to WhisperX. On success emits one
    ``VisionEvent`` (stage="2.asr.glm") so the workbench surfaces the call
    parented to whatever started the asr pipeline.
    """
    s = get_settings()
    bus = get_event_bus()

    if not s.llm_api_key:
        raise GLMASRMissingKey("LLM_API_KEY missing — cannot call PPIO GLM-ASR")

    info = get_media_info(audio_path)
    duration = float(info.get("format", {}).get("duration", 0.0))
    size_bytes = audio_path.stat().st_size

    if duration > _MAX_DURATION_SEC:
        raise GLMASRTooLong(
            f"audio {duration:.1f}s > GLM-ASR 30s limit; degrade to WhisperX"
        )
    if size_bytes > _MAX_FILE_BYTES:
        raise GLMASRTooBig(
            f"audio {size_bytes / 1024 / 1024:.1f}MB > GLM-ASR 25MB limit"
        )

    def _b64() -> str:
        return base64.b64encode(audio_path.read_bytes()).decode("ascii")

    b64 = await asyncio.to_thread(_b64)

    body: dict[str, object] = {"file": b64}
    if hotwords:
        body["hotwords"] = hotwords[:100]

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            r = await client.post(
                s.asr_base_url,
                json=body,
                headers={
                    "Authorization": f"Bearer {s.llm_api_key}",
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        raise GLMASRError(
            f"PPIO GLM-ASR HTTP {e.response.status_code}: {e.response.text[:200]}"
        ) from e
    except httpx.HTTPError as e:
        raise GLMASRError(f"PPIO GLM-ASR network error: {type(e).__name__}: {e}") from e

    text = (data or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise GLMASRError(f"PPIO GLM-ASR empty/invalid response: {data}")

    duration_ms = int((time.perf_counter() - started) * 1000)
    await bus.publish(
        task_id,
        VisionEvent(
            task_id=task_id,
            source="asr",
            model_used=s.model_asr,
            stage=STAGE,
            semantic_label=f"GLM-ASR 转写完成 · {len(text)} 字 · {duration:.1f}s 音频",
            reasoning=(
                f"endpoint={s.asr_base_url}; model={s.model_asr}; "
                f"audio_size={size_bytes / 1024:.0f}KB; "
                f"hotwords={len(hotwords or [])}; "
                f"text_preview={text[:60]!r}{'…' if len(text) > 60 else ''}"
            ),
            confidence=0.95,
            ir_target=IRTarget(ir_type="TranscriptLedger", path="units", op="set"),
            parent_event_id=parent_event_id,
            duration_ms=duration_ms,
        ),
    )
    return text


__all__ = [
    "STAGE",
    "transcribe_glm",
    "GLMASRError",
    "GLMASRTooLong",
    "GLMASRTooBig",
    "GLMASRMissingKey",
]
