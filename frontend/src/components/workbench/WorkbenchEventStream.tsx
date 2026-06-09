import React from "react";
import { useSearchParams } from "react-router-dom";
import { useWorkbenchStore } from "../../state/workbench.js";
import type { VisionEvent } from "../../types/workbench.js";
import { EventBadge } from "./EventBadge.js";

interface RowProps {
  event: VisionEvent;
  parentLabel: string | null;
  selected: boolean;
  vetoed: boolean;
  onSelect: () => void;
  rowRef?: (el: HTMLButtonElement | null) => void;
}

const EventRow: React.FC<RowProps> = ({
  event,
  parentLabel,
  selected,
  vetoed,
  onSelect,
  rowRef,
}) => {
  const baseBg = selected ? "bg-accent-subtle" : "bg-surface";
  const severityBorder =
    event.severity === "warning" || event.confidence_warning
      ? "border-l-warning"
      : event.severity === "error"
      ? "border-l-error"
      : "border-l-transparent";
  const dimmed = vetoed ? "opacity-50" : "";

  return (
    <button
      ref={rowRef}
      type="button"
      data-testid="event-row"
      data-event-id={event.event_id}
      data-vetoed={vetoed ? "true" : "false"}
      onClick={onSelect}
      className={`se-event-in ${baseBg} ${severityBorder} ${dimmed} mb-2 w-full rounded-md border border-border px-3 py-2 text-left transition-colors hover:border-strong`}
      style={{ borderLeftWidth: "4px" }}
    >
      <div className="flex items-center gap-2">
        <EventBadge stage={event.stage} />
        <span className="text-tertiary font-mono text-[11px]">#{event.sequence}</span>
        {event.duration_ms > 0 ? (
          <span className="text-tertiary font-mono text-[11px]">
            {event.duration_ms}ms
          </span>
        ) : null}
        {event.confidence_warning ? (
          <span className="text-warning text-[11px]">⚠ cross-check</span>
        ) : null}
        {vetoed ? (
          <span className="text-error text-[11px]">✕ 已否决</span>
        ) : null}
      </div>
      <div className={`mt-2 text-sm text-primary ${vetoed ? "line-through" : ""}`}>
        {event.semantic_label}
      </div>
      {event.reasoning ? (
        // pre-wrap preserves the model's natural line breaks and lets the
        // paragraph flow over as many lines as needed. The card has finite
        // width but unlimited height — no CSS clamp, no toggle: VLM
        // reasoning is the explainability promise (D19), so it stays fully
        // visible in the card. The right-pane IR tree handles the
        // "fixed-height-row leaf can't show long strings" problem
        // separately via its detail strip.
        <p
          data-testid="event-reasoning"
          className="mt-1 whitespace-pre-wrap text-xs text-secondary"
        >
          {event.reasoning}
        </p>
      ) : null}
      <div className="mt-2 flex items-center justify-between text-xs text-tertiary">
        <span className="font-mono">
          {event.source}
          {event.model_used ? ` · ${event.model_used}` : ""}
        </span>
        <span>
          conf {event.confidence.toFixed(2)}
          {event.cost_tokens ? ` · ${event.cost_tokens}t` : ""}
        </span>
      </div>
      {parentLabel ? (
        <div className="mt-2 border-l-2 border-accent-subtle pl-2 text-xs text-tertiary">
          ← 因 {parentLabel}
        </div>
      ) : null}
    </button>
  );
};

interface StageGroup {
  stage: string;
  firstSeq: number;
  events: VisionEvent[];
}

/**
 * Bucket events by ``stage`` (full string, e.g. ``1A.captions``). Within a
 * bucket events stay in arrival order (the order they hit the store).
 * Buckets are themselves ordered by the ``sequence`` of each bucket's first
 * event — this gives a stable, pipeline-ish ordering without depending on
 * ``media_ts`` (which Phase 1A doesn't yet emit per D17).
 */
function groupByStage(events: VisionEvent[]): StageGroup[] {
  const map = new Map<string, StageGroup>();
  for (const e of events) {
    let g = map.get(e.stage);
    if (!g) {
      g = { stage: e.stage, firstSeq: e.sequence, events: [] };
      map.set(e.stage, g);
    }
    g.events.push(e);
  }
  return Array.from(map.values()).sort((a, b) => a.firstSeq - b.firstSeq);
}

export const WorkbenchEventStream: React.FC = () => {
  // Pull only primitive references from the store. Derived collections live
  // in component-local useMemo so each subscription returns a stable
  // reference — Zustand's getSnapshot must not return a fresh array every
  // call (that triggers React 18's "Maximum update depth" loop via
  // useSyncExternalStore).
  const allEvents = useWorkbenchStore((s) => s.events);
  const filterStage = useWorkbenchStore((s) => s.filterStage);
  const timeRange = useWorkbenchStore((s) => s.timeRange);
  const selectedId = useWorkbenchStore((s) => s.selectedEventId);
  const setSelected = useWorkbenchStore((s) => s.setSelected);
  const toggleVetoed = useWorkbenchStore((s) => s.toggleVetoed);
  const vetoedIds = useWorkbenchStore((s) => s.vetoedIds);
  const setFilter = useWorkbenchStore((s) => s.setFilter);
  const viewMode = useWorkbenchStore((s) => s.streamViewMode);
  const setViewMode = useWorkbenchStore((s) => s.setStreamViewMode);
  const [searchParams] = useSearchParams();
  // Per-stage collapse state for grouped view. Defaults to "open" via the
  // null-coalesce in ``isCollapsed`` — we only flip on explicit user click.
  const [collapsedStages, setCollapsedStages] = React.useState<Set<string>>(
    () => new Set(),
  );
  const toggleStageCollapsed = React.useCallback((stage: string) => {
    setCollapsedStages((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });
  }, []);

  const events = React.useMemo<VisionEvent[]>(() => {
    return allEvents.filter((e) => {
      if (filterStage && !e.stage.startsWith(filterStage)) return false;
      if (timeRange && e.frame_ts != null) {
        const [lo, hi] = timeRange;
        if (e.frame_ts < lo || e.frame_ts > hi) return false;
      }
      return true;
    });
  }, [allEvents, filterStage, timeRange]);

  /**
   * Visible flat order — what the keyboard navigates over. Two modes:
   *
   * - ``by_arrival``: newest first (.reverse), matching the original
   *   "real-time tail" UX. Used for debugging.
   * - ``by_stage`` (default): events grouped by ``stage``; within a group,
   *   arrival order; collapsed groups contribute zero rows. This reads in
   *   roughly pipeline order (stage A's first event fired before stage B's),
   *   which gives the user a "video from start to end" mental model that
   *   the asyncio.gather fan-out in extract_template otherwise destroys.
   */
  const groups = React.useMemo(() => groupByStage(events), [events]);
  const ordered = React.useMemo<VisionEvent[]>(() => {
    if (viewMode === "by_arrival") return [...events].reverse();
    return groups.flatMap((g) =>
      collapsedStages.has(g.stage) ? [] : g.events,
    );
  }, [viewMode, events, groups, collapsedStages]);

  React.useEffect(() => {
    const stage = searchParams.get("stage_filter");
    const range = searchParams.get("time_range");
    let parsedRange: [number, number] | null = null;
    if (range) {
      const [a, b] = range.split("-").map(Number);
      if (!isNaN(a) && !isNaN(b)) parsedRange = [a, b];
    }
    setFilter(stage, parsedRange);
  }, [searchParams, setFilter]);

  // Refs hold the latest values so the keyboard listener installs once.
  const orderedRef = React.useRef<VisionEvent[]>(ordered);
  const selectedIdRef = React.useRef(selectedId);
  const rowRefs = React.useRef<Map<string, HTMLButtonElement>>(new Map());
  React.useEffect(() => {
    orderedRef.current = ordered;
  }, [ordered]);
  React.useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA")
      ) {
        return;
      }
      const list = orderedRef.current;
      if (list.length === 0) return;
      const idx = list.findIndex((ev) => ev.event_id === selectedIdRef.current);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        // Visual "down" — next row below in the rendered list.
        const next = idx < 0 ? list[0] : list[Math.min(list.length - 1, idx + 1)];
        if (next) setSelected(next.event_id);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        // Visual "up" — prior row above in the rendered list.
        const prev = idx <= 0 ? list[0] : list[idx - 1];
        if (prev) setSelected(prev.event_id);
      } else if (e.key === "Enter") {
        // "Jump to the frame" — the left pane already mirrors selectedEventId
        // (so the frame is on screen). Scroll the row into view as visual
        // confirmation.
        e.preventDefault();
        const id = selectedIdRef.current;
        if (id) {
          rowRefs.current.get(id)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      } else if (e.key === "x" || e.key === "X") {
        e.preventDefault();
        const id = selectedIdRef.current;
        if (id) toggleVetoed(id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setSelected, toggleVetoed]);

  const lookupParent = React.useCallback(
    (id: string | null) => {
      if (!id) return null;
      const parent = allEvents.find((e) => e.event_id === id);
      return parent ? `${parent.stage} · ${parent.semantic_label}` : null;
    },
    [allEvents],
  );

  const renderRow = (event: VisionEvent) => (
    <EventRow
      key={event.event_id}
      event={event}
      parentLabel={lookupParent(event.parent_event_id)}
      selected={event.event_id === selectedId}
      vetoed={vetoedIds.has(event.event_id)}
      onSelect={() => setSelected(event.event_id)}
      rowRef={(el) => {
        if (el) rowRefs.current.set(event.event_id, el);
        else rowRefs.current.delete(event.event_id);
      }}
    />
  );

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-serif text-lg text-primary">VLM 怎么想</h2>
          <div
            role="tablist"
            aria-label="event stream view mode"
            className="inline-flex shrink-0 rounded-sm border border-border bg-subtle p-0.5 text-[11px] font-mono"
          >
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === "by_stage"}
              data-testid="stream-mode-by-stage"
              onClick={() => setViewMode("by_stage")}
              className={`rounded-[2px] px-2 py-0.5 ${
                viewMode === "by_stage" ? "bg-accent text-text-inverted" : "text-secondary"
              }`}
            >
              按阶段
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === "by_arrival"}
              data-testid="stream-mode-by-arrival"
              onClick={() => setViewMode("by_arrival")}
              className={`rounded-[2px] px-2 py-0.5 ${
                viewMode === "by_arrival" ? "bg-accent text-text-inverted" : "text-secondary"
              }`}
            >
              按到达顺序
            </button>
          </div>
        </div>
        <p className="text-tertiary text-xs">
          {allEvents.length} 事件 · ↑↓ 切换 · Enter 跳到帧 · X 否决
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3">
        {events.length === 0 ? (
          <div className="flex h-full items-center justify-center text-secondary">
            <p className="text-sm">暂无事件，等待中…</p>
          </div>
        ) : viewMode === "by_arrival" ? (
          ordered.map(renderRow)
        ) : (
          groups.map((g) => {
            const collapsed = collapsedStages.has(g.stage);
            return (
              <section
                key={g.stage}
                data-testid="stage-group"
                data-stage={g.stage}
                className="mb-3"
              >
                <button
                  type="button"
                  onClick={() => toggleStageCollapsed(g.stage)}
                  className="flex w-full items-center gap-2 px-1 py-1 text-left text-xs text-secondary hover:text-primary"
                >
                  <span className="font-mono text-[11px]">{collapsed ? "▸" : "▾"}</span>
                  <EventBadge stage={g.stage} />
                  <span className="text-tertiary">{g.events.length}</span>
                </button>
                {!collapsed ? (
                  <div className="mt-1">{g.events.map(renderRow)}</div>
                ) : null}
              </section>
            );
          })
        )}
      </div>
    </div>
  );
};
