"""Phase 1A LLM client unit tests — fallback, retry, dual-check, JSON parsing."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from app.config import get_settings
from app.ir.vision_event import IRTarget
from app.llm.client import (
    AnthropicClient,
    OpenAICompatClient,
    _extract_json,
    _is_retryable,
    _structurally_equal,
    chat_vision_dual,
    get_llm_client,
    should_dual_check,
)


class _Schema(BaseModel):
    foo: str = "default"
    items: list[int] = Field(default_factory=list)


# ---- _extract_json ---------------------------------------------------------


def test_extract_json_plain():
    assert _extract_json('{"foo": "bar"}') == {"foo": "bar"}


def test_extract_json_inside_codefence():
    s = 'Here you go:\n```json\n{"foo": "bar"}\n```\nthanks'
    assert _extract_json(s) == {"foo": "bar"}


def test_extract_json_array():
    assert _extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_json_garbage_returns_none():
    assert _extract_json("the model said no.") is None


def test_extract_json_nested_braces():
    s = 'prefix {"a": {"b": 1}, "c": [2, 3]} suffix'
    assert _extract_json(s) == {"a": {"b": 1}, "c": [2, 3]}


# ---- structural equality ---------------------------------------------------


def test_structurally_equal_same():
    a = _Schema(foo="x", items=[1, 2])
    b = _Schema(foo="x", items=[1, 2])
    assert _structurally_equal(a, b)


def test_structurally_equal_diff():
    a = _Schema(foo="x", items=[1, 2])
    b = _Schema(foo="y", items=[1, 2])
    assert not _structurally_equal(a, b)


# ---- fallback on missing credentials ---------------------------------------


@pytest.fixture
def no_credentials(monkeypatch):
    """Pin the Settings to credential-less so chat_vision falls back."""
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_openai_fallback_returns_default_and_warns(task_with_events, no_credentials):
    task_id, _ = task_with_events
    client = OpenAICompatClient()
    result, events = await client.chat_vision(
        [{"role": "user", "content": "ping"}],
        model="qwen-vl-max-latest",
        stage="1A.captions",
        task_id=task_id,
        frames=None,
        ir_target_template=IRTarget(ir_type="TemplateIR", path="skeleton"),
        schema=_Schema,
    )
    assert isinstance(result, _Schema)
    assert result.foo == "default"
    assert len(events) == 1
    assert events[0].severity == "warning"
    assert "fallback" in events[0].semantic_label


@pytest.mark.asyncio
async def test_anthropic_fallback_returns_default_and_warns(task_with_events, no_credentials):
    task_id, _ = task_with_events
    client = AnthropicClient()
    result, events = await client.chat_text(
        [{"role": "user", "content": "ping"}],
        model="claude-sonnet-4-6",
        stage="2.recommend",
        task_id=task_id,
        ir_target_template=None,
        schema=_Schema,
    )
    assert isinstance(result, _Schema)
    assert events[0].severity == "warning"
    assert events[0].source == "text_llm"


# ---- silent flag suppresses publish but still returns event ----------------


@pytest.mark.asyncio
async def test_silent_does_not_publish(task_with_events, no_credentials, fresh_event_bus):
    task_id, _ = task_with_events
    queue = fresh_event_bus.subscribe(task_id)
    client = OpenAICompatClient()
    _, events = await client.chat_vision(
        [{"role": "user", "content": "ping"}],
        model="m",
        stage="1A.captions",
        task_id=task_id,
        frames=None,
        ir_target_template=None,
        schema=_Schema,
        silent=True,
    )
    assert len(events) == 1
    assert queue.empty()


# ---- factory routing -------------------------------------------------------


def test_get_llm_client_routes_to_anthropic_explicit():
    assert isinstance(get_llm_client("anthropic"), AnthropicClient)


def test_get_llm_client_routes_to_openai_default():
    # default settings: MODEL_PROVIDER=openai
    assert isinstance(get_llm_client(), OpenAICompatClient)


def test_get_llm_client_mixed_routes_by_stage(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "mixed")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        assert isinstance(get_llm_client(stage="1A.captions"), OpenAICompatClient)
        assert isinstance(get_llm_client(stage="2.recommend"), AnthropicClient)
        assert isinstance(get_llm_client(stage="2.5.nl_edit"), AnthropicClient)
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_should_dual_check_reads_settings(monkeypatch):
    monkeypatch.setenv("DUAL_CHECK_STAGES", "1A.captions,2.recommend")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        assert should_dual_check("1A.captions") is True
        assert should_dual_check("1A.stickers") is False
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


# ---- dual-check (with stub clients in fallback mode) -----------------------


@pytest.mark.asyncio
async def test_dual_check_skips_when_either_side_falls_back(
    task_with_events, no_credentials, fresh_event_bus
):
    """First-principles fix: a fallback secondary used to manufacture a
    cross-check disagreement (default schema vs real primary). Now we
    detect ``severity=warning`` on either side and skip comparison."""
    task_id, _ = task_with_events
    primary = OpenAICompatClient()
    secondary = AnthropicClient()
    # Both fall back; the new logic short-circuits before _structurally_equal.
    _, events = await chat_vision_dual(
        primary=primary,
        secondary=secondary,
        messages=[{"role": "user", "content": "ping"}],
        model_primary="m1",
        model_secondary="m2",
        stage="1A.stickers",
        task_id=task_id,
        frames=None,
        ir_target_template=None,
        schema=_Schema,
    )
    # Only the primary's fallback event — no synthetic disagreement warning.
    assert len(events) == 1
    assert events[0].severity == "warning"


# ---- retry classification --------------------------------------------------


def test_is_retryable_5xx_yes():
    import httpx

    response = httpx.Response(503)
    request = httpx.Request("POST", "https://example.test")
    exc = httpx.HTTPStatusError("server", request=request, response=response)
    assert _is_retryable(exc) is True


def test_is_retryable_4xx_no():
    import httpx

    response = httpx.Response(401)
    request = httpx.Request("POST", "https://example.test")
    exc = httpx.HTTPStatusError("auth", request=request, response=response)
    assert _is_retryable(exc) is False


def test_is_retryable_timeout_yes():
    import httpx

    assert _is_retryable(httpx.ConnectTimeout("slow")) is True
    assert _is_retryable(httpx.ConnectError("refused")) is True


def test_is_retryable_value_error_yes():
    """JSON parse failures get one more shot — temperature jitter sometimes helps."""
    assert _is_retryable(ValueError("not json")) is True


def test_is_retryable_unknown_no():
    assert _is_retryable(RuntimeError("unrelated")) is False
    assert _is_retryable(TypeError("oops")) is False
