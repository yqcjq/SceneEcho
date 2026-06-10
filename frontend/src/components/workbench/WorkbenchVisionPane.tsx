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

export interface WorkbenchVisionPaneProps {
  /** /data/* URL of the task's normalized.mp4. ``null`` hides the video toggle. */
  videoUrl: string | null;
}

export const WorkbenchVisionPane: React.FC<WorkbenchVisionPaneProps> = ({
  videoUrl,
}) => {
  const events = useWorkbenchStore((s) => s.events);
  const eventsById = useWorkbenchStore((s) => s.eventsById);
  const selectedId = useWorkbenchStore((s) => s.selectedEventId);
  const mode = useWorkbenchStore((s) => s.visionPaneMode);
  const setMode = useWorkbenchStore((s) => s.setVisionPaneMode);
  const autoFollow = useWorkbenchStore((s) => s.autoFollow);
  // Selected event lookup is O(1) via ``eventsById``; falls back to the
  // most recent event when nothing is pinned. Without the forward index
  // this used to scan ``events`` linearly on every render.
  const event: VisionEvent | null =
    selectedId === null
      ? events[events.length - 1] ?? null
      : eventsById.get(selectedId) ?? null;

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

  // Once the task's video URL goes away (e.g. resource was deleted, or the
  // store was reset to a sample-less mock task), fall back to frame view so
  // the pane never shows an "empty video" widget.
  React.useEffect(() => {
    if (!videoUrl && mode === "video") setMode("frame");
  }, [videoUrl, mode, setMode]);

  const showVideo = mode === "video" && !!videoUrl;
  const headerBadge = event ? (
    <>
      <EventBadge stage={event.stage} />
      <span className="text-secondary text-xs">
        #{event.sequence} · {event.frame_ts !== null ? `${event.frame_ts.toFixed(2)}s` : "no frame"}
      </span>
    </>
  ) : (
    <span className="text-tertiary text-xs">等待 AI 决策事件…</span>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">{headerBadge}</div>
          {videoUrl ? (
            <div
              role="tablist"
              aria-label="vision pane mode"
              className="inline-flex shrink-0 rounded-sm border border-border bg-subtle p-0.5 text-[11px] font-mono"
            >
              <button
                type="button"
                role="tab"
                aria-selected={mode === "frame"}
                data-testid="vision-mode-frame"
                onClick={() => setMode("frame")}
                className={`rounded-[2px] px-2 py-0.5 ${
                  mode === "frame" ? "bg-accent text-text-inverted" : "text-secondary"
                }`}
              >
                帧截图
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "video"}
                data-testid="vision-mode-video"
                onClick={() => setMode("video")}
                className={`rounded-[2px] px-2 py-0.5 ${
                  mode === "video" ? "bg-accent text-text-inverted" : "text-secondary"
                }`}
              >
                原视频
              </button>
            </div>
          ) : null}
        </div>
        {event ? (
          <h2 className="mt-2 font-serif text-lg text-primary">{event.semantic_label}</h2>
        ) : null}
      </div>
      {showVideo ? (
        <VideoPanel
          videoUrl={videoUrl!}
          seekTo={event?.frame_ts ?? null}
          autoFollow={autoFollow}
        />
      ) : (
        <FramePanel
          event={event}
          frameSize={frameSize}
          frameError={frameError}
          onLoadSize={setFrameSize}
          onError={() => setFrameError(true)}
        />
      )}
    </div>
  );
};

interface FramePanelProps {
  event: VisionEvent | null;
  frameSize: { w: number; h: number } | null;
  frameError: boolean;
  onLoadSize: (size: { w: number; h: number }) => void;
  onError: () => void;
}

const FramePanel: React.FC<FramePanelProps> = ({
  event,
  frameSize,
  frameError,
  onLoadSize,
  onError,
}) => {
  if (!event) {
    return (
      <div className="flex flex-1 items-center justify-center bg-subtle text-secondary">
        <p className="text-sm">等待 AI 决策事件…</p>
      </div>
    );
  }
  const hasFrame = !!event.frame_url;
  const fw = frameSize?.w ?? DEFAULT_FRAME_W;
  const fh = frameSize?.h ?? DEFAULT_FRAME_H;

  return (
    <div className="relative flex-1 bg-inverted">
      {hasFrame ? (
        <img
          src={event.frame_url ?? undefined}
          alt={event.semantic_label}
          decoding="async"
          loading="eager"
          className="absolute inset-0 h-full w-full object-contain"
          draggable={false}
          onLoad={(e) =>
            onLoadSize({
              w: e.currentTarget.naturalWidth || DEFAULT_FRAME_W,
              h: e.currentTarget.naturalHeight || DEFAULT_FRAME_H,
            })
          }
          onError={onError}
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-text-inverted/60">
          <div className="text-center">
            <p className="font-mono text-xs uppercase">no frame</p>
            <p className="mt-2 text-sm">{event.source}-only event</p>
          </div>
        </div>
      )}
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
  );
};

interface VideoPanelProps {
  videoUrl: string;
  /** Seconds. When non-null on (re)render, seek the player there. */
  seekTo: number | null;
  /**
   * Auto-follow tracks every new VLM event. If true, ``seekTo`` changes
   * are ignored — otherwise the player would yank to every newly arriving
   * event during SSE replay and the user could never just watch the clip.
   * Once the user manually picks a card (autoFollow → false), seeks resume.
   */
  autoFollow: boolean;
}

/**
 * Single <video> element across the workbench lifetime. We deliberately do
 * NOT remount on ``seekTo`` change — remount would tear down the decoder,
 * reset playback, and produce a black flicker every time the user clicks a
 * card with a new ``frame_ts``. Instead we seek imperatively via the ref.
 */
const VideoPanel: React.FC<VideoPanelProps> = ({ videoUrl, seekTo, autoFollow }) => {
  const ref = React.useRef<HTMLVideoElement | null>(null);

  // Seek when the selected event's frame_ts changes. Guard against
  // ``readyState=0`` (metadata not loaded yet) by deferring the seek until
  // ``loadedmetadata``; otherwise the seek is silently dropped.
  React.useEffect(() => {
    if (autoFollow) return;
    const v = ref.current;
    if (!v || seekTo == null) return;
    const doSeek = () => {
      // Bail if the user already manually scrubbed close to this point —
      // jumping back yanks them out of their own playback.
      if (Math.abs(v.currentTime - seekTo) < 0.25) return;
      v.currentTime = seekTo;
    };
    if (v.readyState >= 1) {
      doSeek();
    } else {
      const onMeta = () => {
        doSeek();
        v.removeEventListener("loadedmetadata", onMeta);
      };
      v.addEventListener("loadedmetadata", onMeta);
      return () => v.removeEventListener("loadedmetadata", onMeta);
    }
  }, [seekTo, videoUrl, autoFollow]);

  return (
    <div className="relative flex-1 bg-inverted">
      <video
        ref={ref}
        data-testid="vision-pane-video"
        src={videoUrl}
        controls
        preload="metadata"
        className="absolute inset-0 h-full w-full object-contain"
      />
    </div>
  );
};
