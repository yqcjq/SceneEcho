"""LLM/VLM clients and prompt assets.

Phase 0.5 ships placeholder implementations: ``chat_vision`` and ``chat_text``
honor the protocol shape (``-> tuple[BaseModel, list[VisionEvent]]``) and emit
mock VisionEvents through the event bus. Phase 1A replaces the body with real
API calls.
"""
