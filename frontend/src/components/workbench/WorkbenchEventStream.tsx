import React from "react";
import { useSearchParams } from "react-router-dom";
import {
  selectVisibleEvents,
  useWorkbenchStore,
} from "../../state/workbench.js";
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
        <p className="mt-1 line-clamp-3 text-xs text-secondary">{event.reasoning}</p>
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

export const WorkbenchEventStream: React.FC = () => {
  const events = useWorkbenchStore(selectVisibleEvents);
  const selectedId = useWorkbenchStore((s) => s.selectedEventId);
  const setSelected = useWorkbenchStore((s) => s.setSelected);
  const toggleVetoed = useWorkbenchStore((s) => s.toggleVetoed);
  const vetoedIds = useWorkbenchStore((s) => s.vetoedIds);
  const allEvents = useWorkbenchStore((s) => s.events);
  const setFilter = useWorkbenchStore((s) => s.setFilter);
  const [searchParams] = useSearchParams();

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
  const eventsRef = React.useRef(events);
  const selectedIdRef = React.useRef(selectedId);
  const rowRefs = React.useRef<Map<string, HTMLButtonElement>>(new Map());
  React.useEffect(() => {
    eventsRef.current = events;
  }, [events]);
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
      const list = eventsRef.current;
      if (list.length === 0) return;
      const idx = list.findIndex((ev) => ev.event_id === selectedIdRef.current);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = list[Math.min(list.length - 1, idx + 1)];
        if (next) setSelected(next.event_id);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev = list[Math.max(0, idx - 1)];
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

  if (events.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-secondary">
        <p className="text-sm">暂无事件，等待中…</p>
      </div>
    );
  }

  const ordered = [...events].reverse();
  const lookupParent = (id: string | null) => {
    if (!id) return null;
    const parent = allEvents.find((e) => e.event_id === id);
    return parent ? `${parent.stage} · ${parent.semantic_label}` : null;
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3">
        <h2 className="font-serif text-lg text-primary">VLM 怎么想</h2>
        <p className="text-tertiary text-xs">
          {allEvents.length} 事件 · ↑↓ 切换 · Enter 跳到帧 · X 否决
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3">
        {ordered.map((e) => (
          <EventRow
            key={e.event_id}
            event={e}
            parentLabel={lookupParent(e.parent_event_id)}
            selected={e.event_id === selectedId}
            vetoed={vetoedIds.has(e.event_id)}
            onSelect={() => setSelected(e.event_id)}
            rowRef={(el) => {
              if (el) rowRefs.current.set(e.event_id, el);
              else rowRefs.current.delete(e.event_id);
            }}
          />
        ))}
      </div>
    </div>
  );
};
