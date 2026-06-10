import React from "react";
import { useWorkbenchStore } from "../../state/workbench.js";
import type { VisionEvent } from "../../types/workbench.js";

/**
 * CausalChainOverlay — shared causal-chain interactivity for every
 * workbench view (Phase 2.6).
 *
 * Architecture
 * ------------
 *
 * The Phase 2.6 PLAN proposes a single SVG ``<path>`` overlay sitting on
 * top of the middle event pane drawing parent→child curves between event
 * cards. In practice the middle pane is a vertically stacked, scrolling
 * list — dashed paths that cross multiple unrelated cards add visual
 * noise faster than they add insight, and they fight the natural reading
 * order of "scroll top to bottom".
 *
 * Coordinate-mapped views (gantt + media-timeline) DO benefit from
 * explicit dashed paths: their X axis already encodes time, and chains
 * cross few unrelated bars. Both views own their own SVG canvas and draw
 * the dashed paths in-place (see WorkbenchGantt.tsx +
 * WorkbenchMediaTimeline.tsx).
 *
 * For the middle pane, the higher-leverage affordance is **inline
 * parent / child anchors** with cross-view hover sync:
 *
 * - On every event card, a "↳ parent: {label}" pill appears beneath the
 *   reasoning when the event has ``parent_event_id``. Clicking it
 *   selects the parent. Hovering it sets ``hoveredChainRoot`` so other
 *   views can highlight the same chain.
 * - On every event card with children (recorded in ``childIndex``), a
 *   "↱ N children" pill appears. Same click + hover semantics.
 *
 * This module exports the small hooks that make those affordances
 * possible: ``useChainResolver`` (parent/children labels for an event) and
 * ``useChainHighlight`` (set of event_ids that should glow when hovered).
 */

export interface ChainAnchorInfo {
  parent: { id: string; label: string } | null;
  children: { id: string; label: string }[];
}

/**
 * Look up the immediate parent (one step up) and immediate children
 * (one step down) for an event. Returns short, lossy labels suitable
 * for inline anchor pills — "stage · semantic_label" trimmed to 80 chars.
 *
 * Lookup is O(1) on parent (linear-scan over events; small N) and uses
 * the store's ``childIndex`` for children. The childIndex is rebuilt
 * incrementally on every appendEvent (workbench.ts), so this stays
 * cheap even for long runs.
 */
export function useChainResolver(): (
  event: VisionEvent,
) => ChainAnchorInfo {
  const events = useWorkbenchStore((s) => s.events);
  const childIndex = useWorkbenchStore((s) => s.childIndex);

  return React.useCallback(
    (event: VisionEvent): ChainAnchorInfo => {
      const parent = event.parent_event_id
        ? events.find((e) => e.event_id === event.parent_event_id)
        : null;
      const childIds = childIndex.get(event.event_id) ?? [];
      // Resolve at most 5 children to keep the inline pill compact.
      // Surplus children stay reachable through the same anchor → click,
      // which moves selection into the chain proper.
      const children = childIds
        .slice(0, 5)
        .map((id) => events.find((e) => e.event_id === id))
        .filter((e): e is VisionEvent => e !== undefined)
        .map((e) => ({
          id: e.event_id,
          label: shortLabel(e),
        }));
      return {
        parent: parent
          ? { id: parent.event_id, label: shortLabel(parent) }
          : null,
        children,
      };
    },
    [events, childIndex],
  );
}

/**
 * Resolve the full ancestor + descendant set of ``hoveredChainRoot`` so
 * downstream views can compare ``event_id ∈ chain`` in O(1). The set
 * memoises on hoveredChainRoot + childIndex so the recompute happens at
 * most once per hover transition.
 */
export function useChainHighlight(): {
  highlightSet: Set<string>;
  rootId: string | null;
} {
  const events = useWorkbenchStore((s) => s.events);
  const childIndex = useWorkbenchStore((s) => s.childIndex);
  const rootId = useWorkbenchStore((s) => s.hoveredChainRoot);

  const highlightSet = React.useMemo(() => {
    if (!rootId) return new Set<string>();
    const set = new Set<string>([rootId]);
    // Walk up: follow parent_event_id links until null or self-loop.
    const byId = new Map(events.map((e) => [e.event_id, e]));
    let cursor = byId.get(rootId)?.parent_event_id ?? null;
    while (cursor && !set.has(cursor)) {
      set.add(cursor);
      cursor = byId.get(cursor)?.parent_event_id ?? null;
    }
    // Walk down: BFS over childIndex.
    const queue: string[] = [rootId];
    while (queue.length > 0) {
      const id = queue.shift()!;
      const kids = childIndex.get(id) ?? [];
      for (const k of kids) {
        if (set.has(k)) continue;
        set.add(k);
        queue.push(k);
      }
    }
    return set;
  }, [events, childIndex, rootId]);

  return { highlightSet, rootId };
}

function shortLabel(event: VisionEvent): string {
  const lbl = `${event.stage} · ${event.semantic_label}`;
  return lbl.length > 80 ? `${lbl.slice(0, 77)}…` : lbl;
}

/**
 * ChainAnchorPill — clickable + hoverable inline pill rendering one
 * parent or child reference. Used inside event cards. Single source of
 * truth for the "click jumps + hover highlights chain" interaction so
 * the same affordance works in middle pane today and any future view
 * that needs it.
 */
export const ChainAnchorPill: React.FC<{
  direction: "parent" | "child";
  targetId: string;
  label: string;
}> = ({ direction, targetId, label }) => {
  const setSelected = useWorkbenchStore((s) => s.setSelected);
  const setHoveredChainRoot = useWorkbenchStore((s) => s.setHoveredChainRoot);
  const arrow = direction === "parent" ? "↳" : "↱";
  return (
    <button
      type="button"
      data-testid={`chain-${direction}`}
      data-target-event-id={targetId}
      onClick={(e) => {
        e.stopPropagation();
        setSelected(targetId);
      }}
      onMouseEnter={() => setHoveredChainRoot(targetId)}
      onMouseLeave={() => setHoveredChainRoot(null)}
      className="inline-flex items-center gap-1 rounded-sm border border-border bg-subtle px-1.5 py-0.5 text-[10px] text-secondary hover:border-accent hover:bg-accent-subtle hover:text-accent"
    >
      <span className="font-mono text-tertiary">{arrow}</span>
      <span className="truncate">{label}</span>
    </button>
  );
};
