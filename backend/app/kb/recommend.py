"""2.recommend · VLM-driven template recommendation (PLAN 1594-1598).

Given the user's short material (3 sampled frames + ASR summary) and the KB's
templates (with Tags + per-slot caption.placeholder_text/semantic_purpose),
the VLM scores and ranks ``top-k`` templates with a human-readable Chinese
reason for each pick. Each recommendation lands in the workbench as one
VisionEvent (stage="2.recommend") so the right pane "为什么推荐这个模板"
section fills in live.

Design choices:
- The VLM sees the **full template catalog** at once in one call. With ≤50
  templates per PLAN's D6 capacity envelope this fits comfortably under the
  context budget. Multiple per-template calls were considered and rejected:
  they would prevent the model from doing comparative ranking — the whole
  point of "top-k" is choosing among siblings, not scoring in isolation.
- Frames come from ``frame_sampler.sample_frames`` cached by the apply
  pipeline; we ask for first / mid / last to give the VLM a sense of the
  user material's pacing without sending all sampled frames.
- ASR summary is truncated to the first 200 characters (PLAN 1595) to bound
  the input even when the user material is long enough to support longer
  ASR output.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.ledger import TranscriptLedger
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, get_llm_client
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "2.recommend"
log = get_logger(__name__)

# Cap on ASR summary fed to the VLM (PLAN 1595).
_ASR_SUMMARY_CHAR_LIMIT = 200
# Max templates sent to the VLM per call. PLAN D6 capacity envelope is
# ≤50; we still cap defensively because longer catalogs would force a
# context-window bypass that's out of scope for MVP.
_MAX_TEMPLATES_PER_CALL = 50


class _Recommendation(BaseModel):
    template_id: str
    score: float = 0.0
    reason: str = ""


class _RecommendResult(BaseModel):
    recommendations: list[_Recommendation] = Field(default_factory=list)

    def __workbench_label__(self) -> str:
        if not self.recommendations:
            return "推荐 · 0 条"
        head = self.recommendations[0]
        return f"推荐 · top {len(self.recommendations)} · 首选 {head.template_id}"


def _summarize_template(row: dict) -> str:
    """One-line summary of a KB template row for the VLM input.

    Reads from the lightweight list-row shape (no ir_json parse needed): id /
    name / tags / source_sample. When the apply pipeline supplies the full
    parsed IR via ``rows_with_ir`` we additionally surface skeleton snapshot
    + placeholder hints + degraded flags.
    """
    tags = row.get("tags") or {}
    base = (
        f"- {row['id']} · 「{row['name']}」 · "
        f"function={tags.get('function', '?')} · "
        f"scene={tags.get('scene', '?')} · "
        f"position={tags.get('position', '?')} · "
        f"notes={tags.get('notes', '') or '—'}"
    )
    ir = row.get("ir") or {}
    skeleton = ir.get("skeleton") or []
    if skeleton:
        slot_briefs: list[str] = []
        for i, slot in enumerate(skeleton):
            cap = (slot.get("style") or {}).get("caption") or {}
            placeholder = (cap.get("placeholder_text") or [None])[0] or "无字幕"
            purpose = cap.get("semantic_purpose") or "regular"
            slot_briefs.append(
                f"slot{i} {slot.get('role', '?')}/{slot.get('material_req', '?')}/"
                f"{purpose}/{placeholder}"
            )
        base += "\n    骨架：" + " | ".join(slot_briefs)
    degraded = ir.get("degraded") or {}
    if degraded:
        base += f"\n    degraded: {list(degraded.keys())}"
    return base


def _summarize_asr(ledger: TranscriptLedger) -> str:
    full = "".join(u.text for u in ledger.units)
    if len(full) <= _ASR_SUMMARY_CHAR_LIMIT:
        return full
    return full[:_ASR_SUMMARY_CHAR_LIMIT] + "…"


async def recommend_templates(
    *,
    material_path: Path,
    ledger: TranscriptLedger,
    kb_rows: Sequence[dict],
    task_id: str,
    k: int = 3,
    sample_frames: Sequence[tuple[float, str]] | None = None,
    parent_event_id: str | None = None,
) -> tuple[list[_Recommendation], list[VisionEvent]]:
    """Score + rank templates by VLM. Returns top-k recommendations.

    ``kb_rows`` is a list of template dicts with at minimum ``id``, ``name``,
    ``tags``, and optionally ``ir`` (parsed TemplateIR dict). The apply
    pipeline supplies the IR for better-targeted recommendations; calls from
    the UI Editor (where catalog browsing is cheap) can fall back to the
    lightweight list-row shape.

    ``sample_frames`` is a list of ``(ts, rel_path)`` pairs. When None or
    empty, the call still works but the VLM only sees the ASR summary (degrades
    gracefully).

    Failure / no-credentials path: the underlying ``chat_vision`` falls back to
    a stub (warning event, default-constructed result). We then fall back to
    a deterministic ordering (first ``k`` rows in catalog order) so the Editor
    UI still has something to display.
    """
    settings = get_settings()
    bus = get_event_bus()
    cl = get_llm_client(stage=STAGE)

    if not kb_rows:
        return [], []

    rows = list(kb_rows)[:_MAX_TEMPLATES_PER_CALL]
    catalog = "\n".join(_summarize_template(r) for r in rows)
    asr_text = _summarize_asr(ledger)

    frames = [FrameRef(ts=ts, url=rel) for ts, rel in (sample_frames or [])]

    system = load_prompt("2_recommend")
    user_msg = (
        f"用户素材时长 {_duration_hint(ledger)}s\n"
        f"ASR 摘要（前 {_ASR_SUMMARY_CHAR_LIMIT} 字）：{asr_text or '（无）'}\n\n"
        f"KB 模板候选（{len(rows)} 个）：\n{catalog}\n\n"
        f"请按 schema 输出 top-{k} 推荐。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    result, events = await cl.chat_vision(
        messages,
        model=settings.model_vlm,
        stage=STAGE,
        task_id=task_id,
        frames=frames or None,
        ir_target_template=IRTarget(
            ir_type="ProjectIR", path="sections.0.template_id", op="set"
        ),
        schema=_RecommendResult,
        parent_event_id=parent_event_id,
    )

    # Filter out hallucinated template_ids the VLM made up — only KB rows
    # may surface. Preserve the VLM's ordering for surviving entries.
    valid_ids = {r["id"] for r in rows}
    recs = [r for r in result.recommendations if r.template_id in valid_ids][:k]

    # If the VLM (or fallback stub) returned nothing usable, surface the
    # catalog's first k rows so the UI still has something to render — and
    # emit a second warning event so the workbench shows the fallback path.
    extra_events: list[VisionEvent] = []
    if not recs:
        recs = [
            _Recommendation(template_id=r["id"], score=0.0, reason="VLM 未返回有效推荐，按 KB 目录顺序兜底")
            for r in rows[:k]
        ]
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.fallback",
            semantic_label=f"[fallback] 推荐 · 目录前 {len(recs)} 条",
            reasoning="VLM 推荐为空或全部 template_id 无效，已按 KB 目录顺序兜底。",
            confidence=0.0,
            severity="warning",
            ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.template_id"),
            parent_event_id=events[0].event_id if events else parent_event_id,
        )
        await bus.publish(task_id, ev)
        extra_events.append(ev)

    # Emit one per-recommendation event so each top-k card in the Editor
    # has its own VisionEvent (stage="2.recommend") in the workbench.
    rec_events: list[VisionEvent] = []
    parent_id = events[0].event_id if events else parent_event_id
    for i, rec in enumerate(recs):
        ev = VisionEvent(
            task_id=task_id,
            source="vlm",
            model_used=settings.model_vlm,
            stage=STAGE,
            semantic_label=f"推荐 #{i + 1} · {rec.template_id} · {rec.score:.2f}",
            reasoning=rec.reason or "（VLM 未给出 reason）",
            confidence=rec.score,
            ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.template_id"),
            ir_value=rec.template_id,
            parent_event_id=parent_id,
        )
        await bus.publish(task_id, ev)
        rec_events.append(ev)

    return recs, [*events, *extra_events, *rec_events]


def _duration_hint(ledger: TranscriptLedger) -> str:
    if not ledger.units:
        return "0.0"
    return f"{ledger.units[-1].end:.1f}"


__all__ = ["STAGE", "recommend_templates"]
