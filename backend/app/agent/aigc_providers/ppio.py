"""ppio · PPIO image generation provider (Phase 5, ISS-028).

Reference shape (OpenAI-compatible image gen — PPIO mirrors OpenAI's
``/v1/images/generations`` schema for its image-gen catalog):

    POST {AIGC_BROLL_BASE_URL}                    Authorization: Bearer {key}
        {"model": "<model_id>", "prompt": "...", "n": 1,
         "size": "1024x1024", "response_format": "b64_json"}
        → {"data": [{"b64_json": "..."}]}            (or {"url": "https://..."})

The B-roll path in ``agent.aigc`` then converts the returned image bytes
to mp4 via ffmpeg loop — see :func:`agent.aigc.generate_broll`. PPIO image
gen is synchronous (the response carries the image inline), so this
provider exposes only ``generate_image`` (no submit/poll).

Failure classification (so ``aigc.py`` either retries or degrades cleanly):
- no api_key                       → AIGCMissingCredentials (no HTTP call)
- HTTP 401 / 403                   → AIGCMissingCredentials
- HTTP 429                         → AIGCQuotaExceeded
- moderation reject (400 + flag)   → AIGCContentRejected
- HTTP 5xx / timeout / network     → raw httpx error propagates (retryable)
- other 4xx / malformed payload    → AIGCAPIError

This module never imports ``event_bus`` — emission is centralised in aigc.py.
"""

from __future__ import annotations

import base64

import httpx

from app.agent.aigc import (
    AIGCAPIError,
    AIGCContentRejected,
    AIGCMissingCredentials,
    AIGCQuotaExceeded,
)
from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)

_REQUEST_TIMEOUT = httpx.Timeout(120.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0)
# Substrings in a 400 body that mark a moderation rejection rather than a
# malformed-request error. Kept broad — a misclassified reject just means we
# degrade to reuse instead of surfacing "content rejected", both acceptable.
_MODERATION_MARKERS = (
    "moderation",
    "content_policy",
    "sensitive",
    "审核",
    "违规",
    "safety",
)
_DEFAULT_SIZE = "1024x1024"


class PPIOImageProvider:
    """Synchronous text-to-image over the PPIO gateway (OpenAI-compat schema)."""

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._key = api_key
        self._url = base_url
        self._model = model

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def _classify_status(self, e: httpx.HTTPStatusError) -> Exception:
        """Map a 4xx response onto the AIGC* hierarchy.

        5xx is left unwrapped — returning the original error lets the retry
        layer's ``_is_retryable`` see an httpx 5xx and retry.
        """
        code = e.response.status_code
        body = e.response.text[:300]
        if code in (401, 403):
            return AIGCMissingCredentials(f"PPIO auth rejected (HTTP {code}): {body}")
        if code == 429:
            return AIGCQuotaExceeded(f"PPIO quota/rate limit (HTTP 429): {body}")
        if code == 400 and any(m in body.lower() for m in _MODERATION_MARKERS):
            return AIGCContentRejected(f"PPIO moderation rejected prompt: {body}")
        if code >= 500:
            return e  # retryable — let it propagate unchanged
        return AIGCAPIError(f"PPIO HTTP {code}: {body}")

    async def generate_image(self, prompt: str, *, style_keywords: list[str]) -> bytes:
        """Submit a text prompt, return image bytes (PNG/JPG decided by API).

        Style keywords are appended to the prompt as a ", "-joined suffix so
        downstream image models with no dedicated ``style`` field still see
        them. Empty list → bare prompt.
        """
        full_prompt = prompt
        if style_keywords:
            full_prompt = f"{prompt}, {', '.join(style_keywords)}"
        body = {
            "model": self._model,
            "prompt": full_prompt,
            "n": 1,
            "size": _DEFAULT_SIZE,
            "response_format": "b64_json",
        }
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            r = await client.post(self._url, json=body, headers=self._headers)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise self._classify_status(e) from e
            data = r.json() or {}

        items = data.get("data") or []
        if not items or not isinstance(items, list):
            raise AIGCAPIError(f"PPIO image gen returned no data: {data}")
        first = items[0] or {}
        b64 = first.get("b64_json")
        if isinstance(b64, str) and b64:
            return base64.b64decode(b64)
        url = first.get("url")
        if isinstance(url, str) and url:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
                img = await client.get(url)
                try:
                    img.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise self._classify_status(e) from e
                return img.content
        raise AIGCAPIError(f"PPIO image gen returned no b64_json / url: {data}")


def get_provider() -> PPIOImageProvider:
    """Factory consumed by ``aigc._get_broll_provider``.

    Raises ``AIGCMissingCredentials`` up front when key or model is absent
    so the caller never makes a misconfigured HTTP call.
    """
    s = get_settings()
    if not s.aigc_broll_api_key:
        raise AIGCMissingCredentials(
            "AIGC_BROLL_API_KEY not configured — cannot call PPIO image gen"
        )
    if not s.aigc_broll_model:
        raise AIGCMissingCredentials(
            "AIGC_BROLL_MODEL not configured — set it to a PPIO image-gen model id"
        )
    return PPIOImageProvider(
        api_key=s.aigc_broll_api_key,
        base_url=s.aigc_broll_base_url,
        model=s.aigc_broll_model,
    )


__all__ = ["PPIOImageProvider", "get_provider"]
