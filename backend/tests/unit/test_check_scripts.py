"""Smoke tests for the three Phase 1A CI guard scripts.

Each script is also runnable standalone — these tests just verify they
import + parse the codebase without crashing, and recognize the canonical
allowed inputs / reject the canonical violations.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_check_stage_naming_passes_on_canonical_prefixes():
    mod = _load("check_stage_naming")
    for prefix in ("1A.captions", "2.5.nl_edit", "3.step03.dedup", "5.aigc.sticker"):
        assert mod._is_allowed(prefix), prefix


def test_check_stage_naming_rejects_unknown():
    mod = _load("check_stage_naming")
    for bad in ("foo.bar", "1.captions", "phase1a"):
        assert not mod._is_allowed(bad), bad


def test_check_event_emission_runs_on_repo():
    mod = _load("check_event_emission")
    # Should return 0 — backend extract / understand / llm modules do call
    # event_bus.publish (directly or indirectly through chat_vision).
    code = mod.main()
    assert code == 0


def test_check_parent_event_id_runs_on_repo():
    mod = _load("check_parent_event_id")
    code = mod.main()
    assert code == 0


def test_check_stage_naming_runs_on_repo():
    mod = _load("check_stage_naming")
    code = mod.main()
    assert code == 0
