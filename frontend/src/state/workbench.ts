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
interface WorkbenchState {
  taskId: string | null;
  events: VisionEvent[];
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

  appendEvent: (event: VisionEvent) => void;
  setSelected: (id: string | null) => void;
  toggleVetoed: (id: string) => void;
  setFilter: (stage: string | null, range: [number, number] | null) => void;
  togglePause: () => void;
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
  childIndex: new Map(),
  eventIds: new Set<string>(),
  irSnapshot: {},
  selectedEventId: null,
  vetoedIds: new Set<string>(),
  filterStage: null,
  timeRange: null,
  paused: false,
  autoFollow: true,

  appendEvent: (event) => {
    const state = get();
    if (state.paused) return;
    if (state.eventIds.has(event.event_id)) return;
    // Preload the frame image off-state so it lands in the browser cache
    // before autoFollow selects this event. See preloadFrame() docstring.
    preloadFrame(event.frame_url);
    const nextIds = new Set(state.eventIds);
    nextIds.add(event.event_id);
    set({
      events: [...state.events, event],
      eventIds: nextIds,
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
  reset: (taskId) =>
    set({
      taskId,
      events: [],
      eventIds: new Set<string>(),
      irSnapshot: {},
      childIndex: new Map(),
      selectedEventId: null,
      vetoedIds: new Set<string>(),
      filterStage: null,
      timeRange: null,
      paused: false,
      autoFollow: true,
    }),
}));
