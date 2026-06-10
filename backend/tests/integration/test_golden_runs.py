"""Phase 2.6 regression: ReplayClient round-trip vs committed golden runs.

For each sample under ``tests/fixtures/golden_runs/{sid}/``:

1. Construct a :class:`ReplayClient` from the recorded ``events.jsonl``.
2. Patch ``app.llm.client.get_llm_client`` to return that instance, so
   every chat_vision / chat_text call inside ``extract_template`` reads
   from the recording rather than the network.
3. Run the real ``extract_template(sid, task_id)``.
4. Compare the resulting ``TemplateIR`` (model-dumped JSON) against
   ``template.json`` from the recording.

The test passes if and only if the same recorded VLM responses still
rebuild the same TemplateIR — catches IR field renames, list-vs-string
shape flips, and silent semantic drift in the assembly logic.

The directory may be empty in fresh checkouts: ``parametrize`` over
``os.listdir`` produces zero parameters, the test reports "skipped" with
a reason rather than failing. Once the user runs ``record_golden`` and
commits the seeds, the parameter list grows and CI starts gating.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_ROOT = REPO_ROOT / "tests" / "fixtures" / "golden_runs"


def _samples_with_golden_runs() -> list[str]:
    if not GOLDEN_ROOT.exists():
        return []
    out: list[str] = []
    for child in sorted(GOLDEN_ROOT.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "events.jsonl").exists():
            continue
        if not (child / "template.json").exists():
            continue
        out.append(child.name)
    return out


def _diff_summary(actual: dict, expected: dict, path: str = "") -> list[str]:
    """Return human-readable diff lines for ``actual`` vs ``expected``.

    pytest's ``assert ==`` truncates large dicts; this gives us paths to
    the actual divergent leaves so a "schema drift" failure points right
    at the offending field.
    """
    lines: list[str] = []
    if type(actual) is not type(expected):
        return [f"{path or '<root>'}: type {type(actual).__name__} != {type(expected).__name__}"]
    if isinstance(actual, dict):
        keys = sorted(set(actual) | set(expected))
        for k in keys:
            sub = f"{path}.{k}" if path else k
            if k not in actual:
                lines.append(f"{sub}: missing in actual")
            elif k not in expected:
                lines.append(f"{sub}: extra in actual")
            else:
                lines.extend(_diff_summary(actual[k], expected[k], sub))
        return lines
    if isinstance(actual, list):
        if len(actual) != len(expected):
            lines.append(
                f"{path or '<root>'}: list length {len(actual)} != {len(expected)}"
            )
        for i, (a, e) in enumerate(zip(actual, expected, strict=False)):
            lines.extend(_diff_summary(a, e, f"{path}[{i}]"))
        return lines
    if actual != expected:
        # Trim very long values so the failure log stays readable.
        a_repr = repr(actual)[:80]
        e_repr = repr(expected)[:80]
        lines.append(f"{path or '<root>'}: {a_repr!s} != {e_repr!s}")
    return lines


@pytest.mark.parametrize("sample_id", _samples_with_golden_runs())
def test_golden_run_round_trip(
    sample_id: str, temp_data_root, fresh_event_bus, monkeypatch
) -> None:
    """ReplayClient + extract_template should rebuild the recorded TemplateIR."""
    from app import tasks_store
    from app.extract.pipeline import extract_template
    from app.kb import store as kb_store
    from app.llm import client as llm_client_module
    from app.llm.replay_client import ReplayClient

    tasks_store.init_db()
    kb_store.init_db()

    golden_dir = GOLDEN_ROOT / sample_id
    expected = json.loads((golden_dir / "template.json").read_text(encoding="utf-8"))

    # The recorded sample's video must already exist in the temp DATA_ROOT
    # for scenes / frame_sampler / mask CV detectors (which run on real
    # frames). conftest.temp_data_root copies known fixtures; if this
    # sample isn't one of them, skip with a clear message.
    sample_dir = temp_data_root / "samples" / sample_id
    if not (sample_dir / "source.mp4").exists() and not (sample_dir / "normalized.mp4").exists():
        pytest.skip(
            f"sample {sample_id} not in tests/fixtures/{sample_id}/source.mp4 — "
            "ingest the fixture before running golden-run regression"
        )

    replay = ReplayClient(golden_dir / "events.jsonl")

    def _patched_get_llm_client(*args, **kwargs):
        return replay

    monkeypatch.setattr(
        llm_client_module, "get_llm_client", _patched_get_llm_client
    )

    task_id = uuid.uuid4().hex[:12]
    tasks_store.create_task(
        task_id,
        kind="extract_template",
        resource_kind="sample",
        resource_id=sample_id,
    )

    import asyncio

    actual_ir = asyncio.run(extract_template(sample_id, task_id))
    actual = actual_ir.model_dump(mode="json")

    diff = _diff_summary(actual, expected)
    assert not diff, "TemplateIR drift detected:\n  " + "\n  ".join(diff[:40])
