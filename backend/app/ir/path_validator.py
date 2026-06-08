"""Validate lodash-style IR paths against pydantic IR models.

Used by ``tests/unit/test_scenarios.py`` to keep mock VisionEvent paths
honest — every ``ir_target.path`` in a scenario JSON must point into a
real field of ``TemplateIR`` / ``ProjectIR`` / ``TranscriptLedger`` so that
1A's real VLM clients can reuse the same paths without reshaping.

Path grammar (mirrors ``lodash.set``):
- Field names: ``[A-Za-z_][A-Za-z0-9_]*``
- Array indices: ``[<digits>]``
- Field separator: ``.``
- Examples: ``skeleton[0].style.caption.color``, ``tags.position``

Tolerance rules:
- ``Optional[X]`` is peeled to ``X`` before inspection.
- A ``dict`` field accepts any further sub-path (schema-less). PLAN.md
  intentionally keeps ``TemplateIR.global_style`` and ``sanity_check`` as
  free-form dicts; deep validation there belongs to those subsystems.
- A path that runs past a leaf (str/int/etc.) reports a failure — fields
  are leaves only when the writer means to set them whole.
"""

from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel


def _parse_path(path: str) -> list[tuple[str, str]] | None:
    """Tokenize ``path`` into (kind, value) pairs.

    Returns ``None`` on syntactically invalid input.
    """
    segments: list[tuple[str, str]] = []
    i = 0
    n = len(path)
    while i < n:
        c = path[i]
        if c == "[":
            j = path.find("]", i)
            if j == -1:
                return None
            idx = path[i + 1 : j]
            if not idx.isdigit():
                return None
            segments.append(("index", idx))
            i = j + 1
        elif c == ".":
            i += 1
        else:
            j = i
            while j < n and (path[j].isalnum() or path[j] == "_"):
                j += 1
            if j == i:
                return None
            segments.append(("field", path[i:j]))
            i = j
    return segments


def _peel_optional(t: Any) -> Any:
    origin = get_origin(t)
    # ``X | None`` is ``types.UnionType`` in 3.10+; ``Optional[X]`` is ``Union``.
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(t) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return t


def _is_list_type(t: Any) -> bool:
    return get_origin(_peel_optional(t)) is list


def _list_inner(t: Any) -> Any:
    return get_args(_peel_optional(t))[0]


def _is_dict_type(t: Any) -> bool:
    """True for ``dict``, ``dict[K, V]``, or a subclass thereof."""
    t = _peel_optional(t)
    if get_origin(t) is dict or t is dict:
        return True
    return isinstance(t, type) and issubclass(t, dict)


def _is_pydantic_model(t: Any) -> bool:
    t = _peel_optional(t)
    return isinstance(t, type) and issubclass(t, BaseModel)


def validate_path(root: type[BaseModel], path: str) -> tuple[bool, str]:
    """Return ``(ok, error_msg)``. ``error_msg`` is empty on success."""
    segments = _parse_path(path)
    if segments is None:
        return False, f"path syntax invalid: {path!r}"

    current: Any = root
    for kind, val in segments:
        current = _peel_optional(current)
        if kind == "index":
            if not _is_list_type(current):
                return False, f"can't index into {current!r} at [{val}] (not a list)"
            current = _list_inner(current)
            continue
        # field name
        if _is_dict_type(current):
            # Schema-less dict — accept any remaining sub-path without further
            # structural checks.
            return True, ""
        if not _is_pydantic_model(current):
            return False, f"can't read field {val!r} on non-model type {current!r}"
        field_info = _peel_optional(current).model_fields.get(val)  # type: ignore[union-attr]
        if field_info is None:
            return (
                False,
                f"field {val!r} does not exist on {_peel_optional(current).__name__}",  # type: ignore[union-attr]
            )
        current = field_info.annotation
    return True, ""
