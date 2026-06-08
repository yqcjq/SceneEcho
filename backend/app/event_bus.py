"""In-process event bus for AI decision events.

Single source of truth for the workbench observability fabric (D13). The
client layer (``app.llm.client``) calls :meth:`EventBus.publish` after every
AI decision; the SSE endpoint (``app.api.events``) subscribes and pushes to
browsers; events are persisted line-by-line as JSONL alongside their owning
resource ("path scheme B" in PLAN.md).

Design contract (Phase 0.5 second-pass):
- One ``asyncio.Lock`` per task. ``publish`` and ``subscribe_with_snapshot``
  share the same lock so a subscriber's ``snapshot`` plus the queue together
  form a half-open partition: every event with sequence ≤ snapshot is fully
  persisted in the JSONL; every event with sequence > snapshot will arrive
  via the queue. **No overlap.** SSE consumers therefore never need
  sequence-based dedup — replay until_seq=snapshot, then read the queue.
- ``publish`` broadcasts with ``await q.put`` so a slow consumer applies
  back-pressure to the publisher rather than dropping events. Queues are
  unbounded; correctness over throughput at MVP scale.
- High-water mark on first publish is read from the JSONL file's last line,
  not from any SQL column. The JSONL is the only source of truth.
- Tasks-store coupling is inverted via :meth:`set_lookup_callback` injected
  by ``main.py``'s lifespan. ``event_bus`` itself never imports tasks_store.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable

from app.config import get_settings
from app.ir.vision_event import VisionEvent

log = logging.getLogger(__name__)

# Sentinel pushed onto subscriber queues by close_task to wake SSE handlers.
CLOSE_SENTINEL: VisionEvent | None = None  # alias for readability

LookupPathCallback = Callable[[str], dict | None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._counters: dict[str, int] = defaultdict(int)
        self._counter_initialized: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Cache the resolved JSONL path per task so publish never hits SQL on
        # the hot path after the first lookup.
        self._jsonl_paths: dict[str, str] = {}
        # Dependency injection: main.py wires this to ``tasks_store.get_task``
        # at lifespan time. ``None`` during isolated unit tests; callers that
        # need a path should pre-register via ``register_path``.
        self._lookup_path: LookupPathCallback | None = None

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------
    @staticmethod
    def resolve_events_path(resource_kind: str, resource_id: str, task_id: str) -> str:
        """Return DATA_ROOT-relative POSIX path for a task's events JSONL.

        Routing follows path scheme B: events live with the resource, suffixed
        by task_id so concurrent extracts/applies don't collide.
        """
        if resource_kind == "sample":
            return f"samples/{resource_id}/extracted/events_{task_id}.jsonl"
        if resource_kind == "project":
            return f"projects/{resource_id}/pipeline/events_{task_id}.jsonl"
        if resource_kind == "template":
            # Phase 0.5: templates inherit from their source sample, but the
            # template→sample lookup belongs to Phase 1B's KB layer. Until
            # then, fall back to a system path so dev paths never crash.
            return f"system/dev_events/template_{resource_id}/events_{task_id}.jsonl"
        log.warning(
            "event_bus.unknown_resource_kind",
            extra={"kind": resource_kind, "task_id": task_id},
        )
        return f"system/dev_events/unknown_{resource_kind}/events_{task_id}.jsonl"

    def register_path(self, task_id: str, jsonl_rel_path: str) -> None:
        """Tell the bus which JSONL file backs ``task_id`` so publish can append."""
        self._jsonl_paths[task_id] = jsonl_rel_path

    def set_lookup_callback(self, lookup_path: LookupPathCallback) -> None:
        """Wire in the tasks-store reader. Called once from main.py's lifespan.

        Inverting the dependency means ``event_bus`` does not import
        ``tasks_store`` — the layered architecture stays unidirectional.
        """
        self._lookup_path = lookup_path

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------
    async def subscribe_with_snapshot(self, task_id: str) -> tuple[asyncio.Queue, int]:
        """Atomically: register a queue and return the current high-water seq.

        Returned tuple ``(queue, snapshot)`` partitions events cleanly:
        - Events 1..snapshot are fully persisted in the JSONL (replay them).
        - Events snapshot+1.. will arrive on ``queue``.

        Holding the per-task lock for the duration of the registration is
        what gives the SSE endpoint its no-overlap guarantee — a publish
        that tries to ``put`` while we're inside this method must wait.
        """
        async with self._locks[task_id]:
            self._maybe_init_counter(task_id)
            q: asyncio.Queue = asyncio.Queue()  # unbounded
            self._subscribers[task_id].append(q)
            return q, self._counters[task_id]

    def subscribe(self, task_id: str) -> asyncio.Queue:
        """Synchronous variant for tests / non-SSE callers.

        Does not provide the snapshot guarantee — concurrent publishes may
        race and a subscriber here can miss events that already wrote to
        the JSONL. Tests typically subscribe before any publish so the
        race never materializes.
        """
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[task_id].append(q)
        return q

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        if task_id in self._subscribers and queue in self._subscribers[task_id]:
            self._subscribers[task_id].remove(queue)
            if not self._subscribers[task_id]:
                del self._subscribers[task_id]

    # ------------------------------------------------------------------
    # Publish + persistence
    # ------------------------------------------------------------------
    async def publish(self, task_id: str, event: VisionEvent) -> VisionEvent:
        """Atomically assign sequence + append to JSONL; broadcast outside lock.

        Broadcast uses ``await q.put`` (queues are unbounded) so a slow
        consumer applies back-pressure rather than losing events. The lock
        is released before broadcast so the slow path doesn't serialize
        publishers against each other beyond their own sequence assignment.
        """
        async with self._locks[task_id]:
            self._maybe_init_counter(task_id)
            self._counters[task_id] += 1
            event.sequence = self._counters[task_id]
            event.task_id = task_id
            jsonl_rel = self._resolve_jsonl(task_id)
            if jsonl_rel:
                self._append_jsonl(jsonl_rel, event)
            subscribers = list(self._subscribers.get(task_id, []))

        for q in subscribers:
            await q.put(event)
        return event

    def _maybe_init_counter(self, task_id: str) -> None:
        """Initialize the counter from the JSONL tail on first touch.

        Called inside the per-task lock. The JSONL is the source of truth
        for sequence numbers — reading from there means a backend restart
        (or any reuse of an existing task_id) resumes at the correct value
        with no SQL involvement.
        """
        if task_id in self._counter_initialized:
            return
        self._counter_initialized.add(task_id)
        rel = self._resolve_jsonl(task_id)
        if not rel:
            return
        self._counters[task_id] = self._read_jsonl_tail_seq(rel)

    def _resolve_jsonl(self, task_id: str) -> str | None:
        cached = self._jsonl_paths.get(task_id)
        if cached:
            return cached
        if self._lookup_path is None:
            return None
        try:
            row = self._lookup_path(task_id)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "event_bus.lookup_path_failed",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None
        if not row:
            return None
        path = row.get("events_jsonl_path")
        if isinstance(path, str) and path:
            self._jsonl_paths[task_id] = path
            return path
        return None

    def _append_jsonl(self, rel_path: str, event: VisionEvent) -> None:
        abs_path = get_settings().resolve(rel_path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        with abs_path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    @staticmethod
    def _read_jsonl_tail_seq(rel: str) -> int:
        """Return the highest sequence value persisted to ``rel``.

        Reads the entire file rather than seeking from the end — JSONL files
        for a single task stay small (1A real workloads expect O(100s) of
        events; even O(10k) is < 10 MB) and the linear scan is invoked once
        per task per process lifetime.
        """
        path = get_settings().resolve(rel)
        if not path.exists():
            return 0
        last_seq = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = VisionEvent.model_validate_json(line)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "event_bus.tail_parse_failed",
                    extra={"path": rel, "error": str(e)},
                )
                continue
            if ev.sequence > last_seq:
                last_seq = ev.sequence
        return last_seq

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------
    def replay(
        self,
        task_id: str,
        from_event_id: str | None = None,
        until_seq: int | None = None,
    ) -> list[VisionEvent]:
        """Read persisted events; optionally bound by sequence (inclusive).

        ``until_seq`` is the SSE endpoint's snapshot — events with
        ``sequence > until_seq`` are skipped because they will be (or have
        already been) delivered through the live queue. This is what
        eliminates the overlap that previously required dedup-by-sequence.

        ``from_event_id`` matches browser ``Last-Event-ID`` semantics:
        return events strictly after the matching record. Unknown id falls
        back to full history (safer than silent drop).
        """
        rel = self._jsonl_paths.get(task_id) or self._resolve_jsonl(task_id)
        if not rel:
            return []
        path = get_settings().resolve(rel)
        if not path.exists():
            return []
        out: list[VisionEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = VisionEvent.model_validate_json(line)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "event_bus.replay_parse_failed",
                    extra={"task_id": task_id, "error": str(e)},
                )
                continue
            if until_seq is not None and ev.sequence > until_seq:
                continue
            out.append(ev)
        if from_event_id is None:
            return out
        for i, ev in enumerate(out):
            if ev.event_id == from_event_id:
                return out[i + 1 :]
        return out

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def close_task(self, task_id: str) -> None:
        """Wake all subscribers with a sentinel and clear per-task state."""
        for q in list(self._subscribers.get(task_id, [])):
            # put_nowait is fine here: queues are unbounded.
            q.put_nowait(CLOSE_SENTINEL)
        self._subscribers.pop(task_id, None)
        self._counters.pop(task_id, None)
        self._counter_initialized.discard(task_id)
        self._locks.pop(task_id, None)
        self._jsonl_paths.pop(task_id, None)


# Module-level singleton. main.py wires lookup callback + binds via
# app.state.event_bus so dependency overrides remain possible in tests.
_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus


def reset_event_bus() -> None:
    """Test helper — wipe the singleton's state without re-importing."""
    global _bus
    _bus = EventBus()
