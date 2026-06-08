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
  const [frameError, setFrameError] = React.useState(false);
  // Reset frameSize when the displayed frame URL changes — stale dimensions
  // from the previous frame would mis-position the new frame's bbox.
  React.useEffect(() => {
    setFrameSize(null);
    setFrameError(false);
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
            // decoding=async + loading=eager: prefer immediate display,
            // decode off the main thread so the bbox overlay doesn't jank.
            decoding="async"
            loading="eager"
            className="absolute inset-0 h-full w-full object-contain"
            draggable={false}
            onLoad={(e) =>
              setFrameSize({
                w: e.currentTarget.naturalWidth || DEFAULT_FRAME_W,
                h: e.currentTarget.naturalHeight || DEFAULT_FRAME_H,
              })
            }
            onError={() => setFrameError(true)}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-text-inverted/60">
            <div className="text-center">
              <p className="font-mono text-xs uppercase">no frame</p>
              <p className="mt-2 text-sm">{event.source}-only event</p>
            </div>
          </div>
        )}
        {/* Loading hint while the frame JPEG is fetching. preloadFrame()
            in the store kicks off the request the moment the event hits
            the bus, so this state is brief, but during a heavy SSE
            replay it's still the difference between "blank pane" and
            "feedback that something's loading". */}
        {hasFrame && !frameSize && !frameError ? (
          <div className="absolute inset-0 flex items-center justify-center text-text-inverted/50">
            <div className="text-center">
              <p className="font-mono text-xs uppercase animate-pulse">loading frame…</p>
              <p className="mt-2 text-xs">
                {event.frame_ts !== null ? `${event.frame_ts.toFixed(2)}s` : ""}
              </p>
            </div>
          </div>
        ) : null}
        {hasFrame && frameError ? (
          <div className="absolute inset-0 flex items-center justify-center text-error/80">
            <div className="text-center">
              <p className="font-mono text-xs uppercase">frame load failed</p>
              <p className="mt-2 text-xs break-all">{event.frame_url}</p>
            </div>
          </div>
        ) : null}
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
