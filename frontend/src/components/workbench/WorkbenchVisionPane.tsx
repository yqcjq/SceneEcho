import React from "react";
import { useWorkbenchStore } from "../../state/workbench.js";
import type { VisionEvent } from "../../types/workbench.js";
import { BboxOverlay } from "./BboxOverlay.js";
import { EventBadge } from "./EventBadge.js";

// Default canvas (matches SceneEcho's 9:16 default in PLAN). Used as a
// fallback only when the frame image hasn't loaded yet — the real natural
// size comes from <img onLoad>.
const DEFAULT_FRAME_W = 1080;
const DEFAULT_FRAME_H = 1920;

function findEvent(events: VisionEvent[], id: string | null): VisionEvent | null {
  if (!id) return events[events.length - 1] ?? null;
  return events.find((e) => e.event_id === id) ?? null;
}

export const WorkbenchVisionPane: React.FC = () => {
  const events = useWorkbenchStore((s) => s.events);
  const selectedId = useWorkbenchStore((s) => s.selectedEventId);
  const event = findEvent(events, selectedId);

  // Natural dimensions of the currently-displayed frame. We read them from
  // <img onLoad> so bbox coordinates (which the VLM emits in 0–999 normalized
  // space, mapped per axis to the *frame's* actual pixel size) line up
  // correctly regardless of canvas resolution.
  const [frameSize, setFrameSize] = React.useState<{ w: number; h: number } | null>(null);
  // Reset frameSize when the displayed frame URL changes — stale dimensions
  // from the previous frame would mis-position the new frame's bbox.
  React.useEffect(() => {
    setFrameSize(null);
  }, [event?.frame_url]);

  if (!event) {
    return (
      <div className="flex h-full items-center justify-center bg-subtle text-secondary">
        <div className="text-center">
          <p className="font-serif text-base text-primary">VLM 看到什么</p>
          <p className="mt-2 text-sm">等待 AI 决策事件…</p>
        </div>
      </div>
    );
  }

  const hasFrame = !!event.frame_url;
  const fw = frameSize?.w ?? DEFAULT_FRAME_W;
  const fh = frameSize?.h ?? DEFAULT_FRAME_H;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <EventBadge stage={event.stage} />
          <span className="text-secondary text-xs">
            #{event.sequence} · {event.frame_ts !== null ? `${event.frame_ts.toFixed(2)}s` : "no frame"}
          </span>
        </div>
        <h2 className="mt-2 font-serif text-lg text-primary">{event.semantic_label}</h2>
      </div>
      <div className="relative flex-1 bg-inverted">
        {hasFrame ? (
          <img
            src={event.frame_url ?? undefined}
            alt={event.semantic_label}
            className="absolute inset-0 h-full w-full object-contain"
            draggable={false}
            onLoad={(e) =>
              setFrameSize({
                w: e.currentTarget.naturalWidth || DEFAULT_FRAME_W,
                h: e.currentTarget.naturalHeight || DEFAULT_FRAME_H,
              })
            }
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-text-inverted/60">
            <div className="text-center">
              <p className="font-mono text-xs uppercase">no frame</p>
              <p className="mt-2 text-sm">{event.source}-only event</p>
            </div>
          </div>
        )}
        {event.bbox_norm && hasFrame && frameSize ? (
          <BboxOverlay
            frameWidth={fw}
            frameHeight={fh}
            bbox={event.bbox_norm}
            label={event.semantic_label}
            variant={event.confidence_warning ? "secondary" : "primary"}
          />
        ) : null}
      </div>
    </div>
  );
};
