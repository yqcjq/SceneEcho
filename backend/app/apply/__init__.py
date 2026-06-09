"""Apply package — Phase 2 ★MVP 闭环 (PLAN 1593-1666).

Maps a user short-form口播 + a chosen template → ProjectIR ready for renderer.

Modules:
- :mod:`mapping`  — Unit → Slot binding (short-material, in-order)
- :mod:`gaps`     — slots without user coverage
- :mod:`fill`     — three fill strategies (text / wrap / reuse)
- :mod:`style`    — apply slot StyleRule to PlacedSegments + Captions + BGM
- :mod:`pipeline` — DAG orchestrator (normalize → asr → recommend? → map → gaps → fill → style → save)
"""
