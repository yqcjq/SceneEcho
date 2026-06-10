"""record_golden.py — capture a real extract run as a regression fixture.

Usage:

    python scripts/record_golden.py --sample sample_basic_15s

The script runs ``extract.pipeline.extract_template`` against an existing
sample with the real LLM client (so credentials must be configured and the
sample must already be ingested at ``data/samples/{sid}/``). After the run
finishes it copies two artefacts into ``tests/fixtures/golden_runs/{sid}/``:

- ``events.jsonl`` — the full ordered event stream from the run.
- ``template.json`` — the TemplateIR row that landed in the KB.

Files are NOT auto-staged with git. The doc PLAN line 1786 requires a
human review pass (no PII, no API keys, IR field semantics OK) before the
fixture is committed. The CLI prints the next steps so reviewers don't
guess.

Re-running for the same sample overwrites the fixture in place — the
recording is whatever the real client just produced.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

import typer

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import tasks_store  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.event_bus import get_event_bus  # noqa: E402
from app.extract.pipeline import extract_template  # noqa: E402
from app.kb import store as kb_store  # noqa: E402

app = typer.Typer(add_completion=False, help=__doc__)


def _golden_dir(sample_id: str) -> Path:
    return REPO_ROOT / "tests" / "fixtures" / "golden_runs" / sample_id


async def _run(sample_id: str, *, name: str | None) -> str:
    """Run the real extract pipeline; return the task_id used."""
    settings = get_settings()
    sample_dir = settings.data_root / "samples" / sample_id
    if not sample_dir.exists():
        raise typer.BadParameter(
            f"sample not found: {sample_dir}. Ingest first via "
            "`python -m app.cli ingest-sample <path>` or the UI."
        )
    tasks_store.init_db()
    kb_store.init_db()

    bus = get_event_bus()
    bus.set_lookup_callback(tasks_store.get_task)

    task_id = uuid.uuid4().hex[:12]
    tasks_store.create_task(
        task_id,
        kind="extract_template",
        resource_kind="sample",
        resource_id=sample_id,
    )
    typer.echo(f"recording → task_id={task_id}, sample={sample_id}")
    try:
        ir = await extract_template(sample_id, task_id, name=name)
        tasks_store.update_task(
            task_id,
            status="completed",
            progress=1.0,
            result={"template_id": ir.id},
        )
    except Exception as e:  # noqa: BLE001
        tasks_store.update_task(task_id, status="failed", error=str(e))
        raise
    finally:
        bus.close_task(task_id)
    return task_id


def _copy_artefacts(sample_id: str, task_id: str) -> None:
    settings = get_settings()
    events_src = (
        settings.data_root
        / "samples"
        / sample_id
        / "extracted"
        / f"events_{task_id}.jsonl"
    )
    if not events_src.exists():
        raise typer.BadParameter(f"events.jsonl missing at {events_src}")

    template = kb_store.get_template(f"tpl_{sample_id}")
    if template is None:
        raise typer.BadParameter(
            f"template tpl_{sample_id} not in KB; extract appears to have failed"
        )
    # ``kb_store.get_template`` always returns the parsed TemplateIR under
    # the ``ir`` key (after pydantic round-trip). Use that as the canonical
    # snapshot — the regression test does the same model_dump comparison.
    ir = template.get("ir")
    if ir is None:
        raise typer.BadParameter(
            f"template tpl_{sample_id} returned ir=None; KB row malformed"
        )

    out_dir = _golden_dir(sample_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(events_src, out_dir / "events.jsonl")
    (out_dir / "template.json").write_text(
        json.dumps(ir, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


@app.command()
def record_golden(
    sample: str = typer.Option(..., "--sample", "-s", help="Existing sample_id"),
    name: str | None = typer.Option(None, help="Optional template name override"),
) -> None:
    """Run extract_template against ``sample`` and snapshot the outputs."""
    typer.echo(
        "record_golden: this will call the REAL LLM client. "
        "Ensure your .env has live credentials.\n"
    )
    task_id = asyncio.run(_run(sample, name=name))
    _copy_artefacts(sample, task_id)
    out = _golden_dir(sample)
    typer.echo("\nrecorded:")
    typer.echo(f"  {out / 'events.jsonl'}")
    typer.echo(f"  {out / 'template.json'}")
    typer.echo(
        "\nnext: review the JSONL by hand (no PII / no API keys / IR fields look right) "
        "before `git add tests/fixtures/golden_runs/`."
    )


if __name__ == "__main__":
    app()
