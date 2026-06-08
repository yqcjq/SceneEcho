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
 */
interface WorkbenchState {
  taskId: string | null;
  events: VisionEvent[];
  /** Reverse index: parent_event_id -> child event_ids. Rebuilt on every append. */
  childIndex: Map<string, string[]>;
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

export const useWorkbenchStore = create<WorkbenchState>((set, get) => ({
  taskId: null,
  events: [],
  childIndex: new Map(),
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
    set({
      events: [...state.events, event],
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

/** Filter selector: stage prefix + time-range against frame_ts (if present). */
export function selectVisibleEvents(state: WorkbenchState): VisionEvent[] {
  return state.events.filter((e) => {
    if (state.filterStage && !e.stage.startsWith(state.filterStage)) return false;
    if (state.timeRange && e.frame_ts !== null && e.frame_ts !== undefined) {
      const [lo, hi] = state.timeRange;
      if (e.frame_ts < lo || e.frame_ts > hi) return false;
    }
    return true;
  });
}

export function selectChildren(state: WorkbenchState, parentId: string): string[] {
  return state.childIndex.get(parentId) ?? [];
}
