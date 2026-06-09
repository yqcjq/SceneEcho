"""1B · Template selector — Phase 1B placeholder.

PLAN.md keeps the full select+rerank pipeline for Phase 3. In Phase 1B
we ship the function signature and an exact-tag-match implementation so
the workbench API can already wire ``GET /templates`` to a real chooser
without throwing NotImplementedError.
"""

from __future__ import annotations

from app.ir.template import Tags


def select_template(query_tags: Tags, kb: list[dict]) -> str | None:
    """Return the template_id of the closest tag match (exact > partial).

    ``kb`` is a list of rows shaped like ``app.kb.store.list_templates()``
    output. None when KB is empty. Phase 3 will replace with full LLM
    rerank.
    """
    if not kb:
        return None
    q = {
        "function": query_tags.function,
        "scene": query_tags.scene,
        "position": query_tags.position,
    }
    best_id: str | None = None
    best_score = -1
    for row in kb:
        t = row.get("tags") or {}
        score = sum(1 for k, v in q.items() if t.get(k) == v)
        if score > best_score:
            best_score = score
            best_id = row.get("id")
    return best_id


__all__ = ["select_template"]
