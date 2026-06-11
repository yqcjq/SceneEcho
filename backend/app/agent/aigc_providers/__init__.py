"""AIGC provider implementations.

Each module exposes ``get_provider()`` returning an object that satisfies
``app.agent.aigc.BrollProvider`` — currently a single
``generate_image(prompt, *, style_keywords) -> bytes`` method.
``AIGC_BROLL_PROVIDER`` selects one by module name — e.g.
``AIGC_BROLL_PROVIDER=ppio`` loads ``ppio.py``. The image bytes returned
here are looped into mp4 by ``aigc.py`` (via ``render.ffmpeg.image_to_video``)
for the B-roll path; the sticker path keeps the raw image.

Providers are the network-IO surface only: they raise the ``AIGC*`` typed
errors for classified failures (missing key / quota / content rejected) and
let raw ``httpx`` errors propagate for transient ones so the retry layer in
``aigc.py`` can classify them. They never call ``event_bus.publish`` —
event emission is centralised in ``aigc.py`` so the D13 guard verifies one
surface.
"""

from __future__ import annotations
