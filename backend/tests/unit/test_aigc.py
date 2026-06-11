"""Unit tests for ``app.agent.aigc`` (Phase 5, ISS-028).

Covers the provider-agnostic surface: typed errors, hash cache, event schema,
duration clamping, image→mp4 ffmpeg conversion. The PPIO provider's HTTP
shape is exercised through the integration test that monkey-patches
``_get_broll_provider`` end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings


@pytest.fixture
def aigc_disabled(monkeypatch):
    """Default state: no provider configured → generate_broll raises."""
    monkeypatch.setenv("AIGC_BROLL_PROVIDER", "")
    monkeypatch.setenv("AIGC_BROLL_API_KEY", "")
    monkeypatch.setenv("AIGC_BROLL_MODEL", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def aigc_enabled(monkeypatch):
    """Provider configured + key + model set → generate_broll calls the (mocked) provider."""
    monkeypatch.setenv("AIGC_BROLL_PROVIDER", "ppio")
    monkeypatch.setenv("AIGC_BROLL_API_KEY", "fake-key")
    monkeypatch.setenv("AIGC_BROLL_MODEL", "test/fake-image-model")
    monkeypatch.setenv("AIGC_BROLL_MAX_DURATION_SEC", "6.0")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def stub_image_to_video(monkeypatch):
    """Replace ffmpeg image_to_video with a write-bytes stub.

    Unit tests don't need real video output; this avoids the ffmpeg
    subprocess (slow, env-dependent) while keeping the function-call
    contract intact.
    """
    from app.agent import aigc

    calls: list[dict] = []

    def _fake(src_image, dst_path, *, duration_sec, width=1080, height=1920, fps=30):
        Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
        Path(dst_path).write_bytes(b"FAKE_MP4_FROM_IMAGE")
        calls.append(
            {
                "src": str(src_image),
                "dst": str(dst_path),
                "duration": duration_sec,
                "wh": (width, height),
                "fps": fps,
                "src_bytes": Path(src_image).read_bytes(),
            }
        )
        return Path(dst_path)

    monkeypatch.setattr(aigc, "image_to_video", _fake)
    return calls


class _FakeProvider:
    """Minimal BrollProvider that hands back canned image bytes."""

    def __init__(self, *, image_bytes: bytes = b"FAKEPNG\x00DATA") -> None:
        self.image_bytes = image_bytes
        self.calls: list[tuple[str, list[str]]] = []

    async def generate_image(self, prompt, *, style_keywords):
        self.calls.append((prompt, list(style_keywords)))
        return self.image_bytes


def test_cache_key_stability_and_sensitivity():
    """Same inputs → same hash; any input change → different hash."""
    from app.agent.aigc import _cache_key

    a = _cache_key("hello", {"scene": "studio"}, 5.0)
    b = _cache_key("hello", {"scene": "studio"}, 5.0)
    assert a == b
    # different prompt
    assert _cache_key("hi", {"scene": "studio"}, 5.0) != a
    # different style
    assert _cache_key("hello", {"scene": "outdoor"}, 5.0) != a
    # different duration
    assert _cache_key("hello", {"scene": "studio"}, 4.5) != a
    # rounding to 2dp: 5.001 collapses to 5.0
    assert _cache_key("hello", {"scene": "studio"}, 5.001) == a
    # sticker key (no duration) is also stable across calls
    s1 = _cache_key("ribbon", {"scene": "ad"}, None)
    s2 = _cache_key("ribbon", {"scene": "ad"}, None)
    assert s1 == s2


@pytest.mark.asyncio
async def test_generate_broll_missing_provider_raises(task_with_events, aigc_disabled):
    """Empty AIGC_BROLL_PROVIDER → AIGCMissingCredentials, no provider call."""
    from app.agent.aigc import AIGCMissingCredentials, generate_broll

    task_id, _ = task_with_events
    with pytest.raises(AIGCMissingCredentials):
        await generate_broll(
            "any prompt", 3.0, {"scene": "studio"}, project_id="prj_x", task_id=task_id
        )


@pytest.mark.asyncio
async def test_generate_broll_happy_path_writes_cache_and_event(
    task_with_events, aigc_enabled, stub_image_to_video, monkeypatch
):
    """Cache miss → provider returns image → ffmpeg loops to mp4 → cached + event emitted."""
    from app.agent import aigc
    from app.event_bus import get_event_bus

    fake = _FakeProvider(image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    monkeypatch.setattr(aigc, "_get_broll_provider", lambda _name: fake)

    task_id, _ = task_with_events
    rel, events = await aigc.generate_broll(
        "a wide shot of a quiet desk",
        4.0,
        {"scene": "studio", "style_keywords": ["clean", "minimal"]},
        project_id="prj_test",
        task_id=task_id,
    )

    settings = get_settings()
    assert rel.startswith("aigc/broll/") and rel.endswith(".mp4")
    abs_path = settings.data_root / rel
    assert abs_path.exists()
    # ffmpeg stub wrote the placeholder mp4 bytes; intermediate .png cleaned up.
    assert abs_path.read_bytes() == b"FAKE_MP4_FROM_IMAGE"
    assert not abs_path.with_suffix(".png").exists()
    # provider got called once with our style keywords passed through
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == ["clean", "minimal"]
    # ffmpeg stub got the requested duration + the provider's image bytes
    assert len(stub_image_to_video) == 1
    assert stub_image_to_video[0]["duration"] == 4.0
    assert stub_image_to_video[0]["src_bytes"].startswith(b"\x89PNG")

    assert len(events) == 1
    ev = events[0]
    assert ev.stage == "5.aigc.broll"
    assert ev.source == "system"
    assert ev.media_ts_range == (0.0, 4.0)
    assert ev.frame_url is None  # no source frame for AIGC
    assert "cache_hit=False" in ev.reasoning
    # event also persisted to JSONL via bus.publish
    bus = get_event_bus()
    persisted = [e for e in bus.replay(task_id) if e.stage == "5.aigc.broll"]
    assert len(persisted) == 1


@pytest.mark.asyncio
async def test_generate_broll_cache_hit_skips_provider(
    task_with_events, aigc_enabled, stub_image_to_video, monkeypatch
):
    """Same prompt + style + duration → second call returns from cache, no provider call."""
    from app.agent import aigc

    fake = _FakeProvider(image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    monkeypatch.setattr(aigc, "_get_broll_provider", lambda _name: fake)

    task_id, _ = task_with_events
    rel1, _ = await aigc.generate_broll(
        "same prompt", 3.0, {"scene": "studio"}, project_id="prj_a", task_id=task_id
    )
    assert len(fake.calls) == 1
    assert len(stub_image_to_video) == 1

    rel2, events = await aigc.generate_broll(
        "same prompt", 3.0, {"scene": "studio"}, project_id="prj_a", task_id=task_id
    )
    assert rel1 == rel2
    # provider must NOT have been called again, and ffmpeg must NOT re-run
    assert len(fake.calls) == 1
    assert len(stub_image_to_video) == 1
    # cache-hit event has cache_hit=True in its reasoning
    assert "cache_hit=True" in events[0].reasoning


@pytest.mark.asyncio
async def test_generate_broll_clamps_to_max_duration(
    task_with_events, aigc_enabled, stub_image_to_video, monkeypatch
):
    """Requested duration > max → ffmpeg gets the clamped value, event reflects it."""
    from app.agent import aigc

    fake = _FakeProvider()
    monkeypatch.setattr(aigc, "_get_broll_provider", lambda _name: fake)

    task_id, _ = task_with_events
    _, events = await aigc.generate_broll(
        "long shot", 12.0, {"scene": "studio"}, project_id="prj_c", task_id=task_id
    )
    # Settings default max is 6.0 (env override pinned via aigc_enabled fixture)
    assert stub_image_to_video[0]["duration"] == 6.0
    assert events[0].media_ts_range == (0.0, 6.0)


@pytest.mark.asyncio
async def test_generate_broll_provider_error_propagates(
    task_with_events, aigc_enabled, stub_image_to_video, monkeypatch
):
    """Quota error from provider → AIGCQuotaExceeded raised (caller falls back)."""
    from app.agent import aigc
    from app.agent.aigc import AIGCQuotaExceeded

    class _QuotaProvider:
        async def generate_image(self, *_a, **_kw):
            raise AIGCQuotaExceeded("PPIO quota exhausted")

    monkeypatch.setattr(aigc, "_get_broll_provider", lambda _name: _QuotaProvider())

    task_id, _ = task_with_events
    with pytest.raises(AIGCQuotaExceeded):
        await aigc.generate_broll(
            "prompt", 3.0, {}, project_id="prj_q", task_id=task_id
        )
    # ffmpeg never runs when generation fails — no cache poisoning.
    assert stub_image_to_video == []


@pytest.mark.asyncio
async def test_generate_sticker_image_happy_path(
    task_with_events, aigc_enabled, monkeypatch
):
    """Sticker gen writes data/aigc/stickers/{hash}.png + emits 5.aigc.sticker event.

    No ffmpeg conversion — sticker is the raw image bytes.
    """
    from app.agent import aigc

    fake = _FakeProvider(image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    monkeypatch.setattr(aigc, "_get_broll_provider", lambda _name: fake)

    task_id, _ = task_with_events
    rel, events = await aigc.generate_sticker_image(
        "red star ribbon", {"scene": "ad"}, project_id="prj_s", task_id=task_id
    )
    assert rel.startswith("aigc/stickers/") and rel.endswith(".png")
    settings = get_settings()
    abs_path = settings.data_root / rel
    assert abs_path.exists()
    assert abs_path.read_bytes() == b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert events[0].stage == "5.aigc.sticker"
    # No video duration → no media_ts_range
    assert events[0].media_ts_range is None
