import { produce } from "immer";
import get from "lodash/get.js";
import set from "lodash/set.js";
import unset from "lodash/unset.js";
import { create } from "zustand";
import type { VisionEvent } from "../types/workbench.js";

/**
 * Workbench store. Holds the live event log + a derived IR snapshot.
 *
 * Auto-follow semantics: by default, every new event becomes the selected
 * one (the workbench "tails" the AI's progress). The first manual
 * ``setSelected`` call flips ``autoFollow`` off so the user's pinned
 * selection is no longer hijacked by incoming events. ``reset`` restores
 * auto-follow.
 *
 * Dedup-by-event_id: ``appendEvent`` is idempotent. SSE delivers events
 * live; a separate "history sync" path may re-deliver the same events
 * after a task hits terminal status (or when the SSE ``done`` fires). The
 * ``eventIds`` set lets both paths run without clobbering — whichever
 * arrives first wins, the second is silently dropped. This is the
 * first-principles answer to "cards don't appear until I refresh": rather
 * than hunting the SSE race window, make the final state converge
 * regardless of delivery path.
 */
/**
 * Workbench top-level layout — three full-page modes share the same event
 * data. ``list`` is the existing 3-pane (frame | events | IR tree); ``gantt``
 * replaces it with a wall-clock visx gantt; ``media_timeline`` replaces it
 * with a video-anchored marker timeline. URL ?view= keeps the choice
 * shareable.
 */
export type WorkbenchView = "list" | "gantt" | "media_timeline";

interface WorkbenchState {
  taskId: string | null;
  events: VisionEvent[];
  /**
   * Forward index: event_id -> VisionEvent. Same provenance as ``childIndex``
   * (both are derived from the events array). Lets every "look up an event by
   * id" consumer (causal chain anchors, vision pane, gantt parent edges,
   * future filters) read in O(1) instead of scanning ``events`` linearly.
   * Without this, mid-pane card rendering on a long run is O(N²) — N cards
   * × N-scan-per-card on every event arrival.
   */
  eventsById: Map<string, VisionEvent>;
  /** Reverse index: parent_event_id -> child event_ids. Rebuilt on every append. */
  childIndex: Map<string, string[]>;
  /** O(1) dedup by event_id — SSE + history fetch can both deliver the same id. */
  eventIds: Set<string>;
  irSnapshot: Record<string, unknown>;
  selectedEventId: string | null;
  vetoedIds: Set<string>;
  filterStage: string | null;
  timeRange: [number, number] | null;
  paused: boolean;
  autoFollow: boolean;
  /** Right-pane content: single-frame screenshot (default) vs full normalized.mp4 playback. */
  visionPaneMode: "frame" | "video";
  /** Middle-pane layout: stage-grouped (default) vs flat arrival-order list. */
  streamViewMode: "by_stage" | "by_arrival";
  /** Top-level layout — Phase 2.6 adds gantt + media_timeline alongside list. */
  view: WorkbenchView;
  /**
   * Current media-timeline playhead (seconds into the source video). Pushed
   * by the <video> element's onTimeUpdate; read by markers to highlight a
   * ±0.5s neighbourhood. ``null`` until the user opens the media-timeline
   * view at least once.
   */
  currentMediaTs: number | null;
  /**
   * Event id whose causal chain (ancestors + descendants) should be
   * highlighted across all workbench views. Set by hovering a parent/child
   * anchor in the middle pane; consumed by gantt + media-timeline + IR
   * pane to draw the same dashed chain emphasis. ``null`` clears the
   * highlight everywhere.
   */
  hoveredChainRoot: string | null;

  appendEvent: (event: VisionEvent) => void;
  setSelected: (id: string | null) => void;
  toggleVetoed: (id: string) => void;
  setFilter: (stage: string | null, range: [number, number] | null) => void;
  togglePause: () => void;
  setVisionPaneMode: (mode: "frame" | "video") => void;
  setStreamViewMode: (mode: "by_stage" | "by_arrival") => void;
  setView: (view: WorkbenchView) => void;
  setCurrentMediaTs: (ts: number | null) => void;
  setHoveredChainRoot: (id: string | null) => void;
  reset: (taskId: string | null) => void;
}

const writeIr = (
  ir: Record<string, unknown>,
  event: VisionEvent,
): Record<string, unknown> => {
  if (!event.ir_target) return ir;
  const op = event.ir_target.op ?? "set";
  if (
    (event.ir_value === null || event.ir_value === undefined) &&
    op !== "remove"
  ) {
    return ir;
  }
  return produce(ir, (draft) => {
    const target = event.ir_target!;
    const path = target.field ? `${target.path}.${target.field}` : target.path;
    if (op === "remove") {
      unset(draft as object, path);
    } else if (op === "append") {
      // Append to an array at `path`. Initialize as a one-element array if
      // the slot is missing or not yet an array — lodash.set's bracketed
      // path handling can't express "push" on its own.
      const current = get(draft as object, path);
      if (Array.isArray(current)) {
        current.push(event.ir_value);
      } else {
        set(draft as object, path, [event.ir_value]);
      }
    } else {
      set(draft as object, path, event.ir_value);
    }
  });
};

const indexChild = (
  index: Map<string, string[]>,
  event: VisionEvent,
): Map<string, string[]> => {
  if (!event.parent_event_id) return index;
  const next = new Map(index);
  const list = next.get(event.parent_event_id) ?? [];
  if (!list.includes(event.event_id)) {
    next.set(event.parent_event_id, [...list, event.event_id]);
  }
  return next;
};

/**
 * Kick off a background HTTP fetch for the event's frame image so by the
 * time autoFollow selects the event, the browser already has the JPEG in
 * its HTTP cache. Without this, a burst of events during SSE replay causes
 * the <img> src to change rapidly — every src change cancels the in-flight
 * request, so only the final event's image actually finishes loading,
 * which the user perceives as "frames don't appear until I refresh".
 *
 * `new Image()` doesn't insert anything into the DOM; the browser fetches
 * normally, populates its cache, then the eventual <img> on the page
 * resolves from cache instantly. URL dedup is handled by the browser
 * (same URL → single request).
 */
const preloadFrame = (url: string | null | undefined): void => {
  if (!url || typeof Image === "undefined") return;
  const img = new Image();
  // decoding=async lets the browser decode off the main thread — when the
  // real <img> later mounts, paint is already ready.
  img.decoding = "async";
  img.src = url;
};

export const useWorkbenchStore = create<WorkbenchState>((set, get) => ({
  taskId: null,
  events: [],
  eventsById: new Map(),
  childIndex: new Map(),
  eventIds: new Set<string>(),
  irSnapshot: {},
  selectedEventId: null,
  vetoedIds: new Set<string>(),
  filterStage: null,
  timeRange: null,
  paused: false,
  autoFollow: true,
  visionPaneMode: "frame",
  streamViewMode: "by_stage",
  view: "list",
  currentMediaTs: null,
  hoveredChainRoot: null,

  appendEvent: (event) => {
    const state = get();
    if (state.paused) return;
    if (state.eventIds.has(event.event_id)) return;
    // Preload the frame image off-state so it lands in the browser cache
    // before autoFollow selects this event. See preloadFrame() docstring.
    preloadFrame(event.frame_url);
    const nextIds = new Set(state.eventIds);
    nextIds.add(event.event_id);
    const nextById = new Map(state.eventsById);
    nextById.set(event.event_id, event);
    set({
      events: [...state.events, event],
      eventIds: nextIds,
      eventsById: nextById,
      irSnapshot: writeIr(state.irSnapshot, event),
      childIndex: indexChild(state.childIndex, event),
      // Tail the newest event only while the user hasn't taken manual control.
      selectedEventId: state.autoFollow ? event.event_id : state.selectedEventId,
    });
  },

  setSelected: (id) => set({ selectedEventId: id, autoFollow: false }),

  toggleVetoed: (id) => {
    const next = new Set(get().vetoedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    set({ vetoedIds: next });
  },

  setFilter: (stage, range) => set({ filterStage: stage, timeRange: range }),
  togglePause: () => set({ paused: !get().paused }),
  setVisionPaneMode: (mode) => set({ visionPaneMode: mode }),
  setStreamViewMode: (mode) => set({ streamViewMode: mode }),
  setView: (view) => set({ view }),
  setCurrentMediaTs: (ts) => set({ currentMediaTs: ts }),
  setHoveredChainRoot: (id) => set({ hoveredChainRoot: id }),
  reset: (taskId) =>
    set({
      taskId,
      events: [],
      eventIds: new Set<string>(),
      eventsById: new Map(),
      irSnapshot: {},
      childIndex: new Map(),
      selectedEventId: null,
      vetoedIds: new Set<string>(),
      filterStage: null,
      timeRange: null,
      paused: false,
      autoFollow: true,
      visionPaneMode: "frame",
      streamViewMode: "by_stage",
      // ``view`` is intentionally NOT reset — the URL ?view= drives it,
      // and resetting on every taskId change would fight the query param
      // on navigation. Leave the user's current layout choice intact.
      currentMediaTs: null,
      hoveredChainRoot: null,
    }),
}));
