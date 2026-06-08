"""Phase 1A visual-understanding subcapabilities.

Each module exposes one or more ``detect_*`` / ``classify_*`` functions
returning ``(structured_result, list[VisionEvent])``. Heavy ML deps
(scenedetect, opencv, librosa, demucs) are lazy-imported inside each
function — base ``pip install -e ".[dev]"`` runs unit tests without them.

stage constants live at module top: see ``STAGE`` in each file.
"""
