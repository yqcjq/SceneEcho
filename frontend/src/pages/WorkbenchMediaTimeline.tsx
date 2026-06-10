import { Group } from "@visx/group";
import { ParentSize } from "@visx/responsive";
import { scaleBand, scaleLinear } from "@visx/scale";
import React from "react";
import { useChainHighlight } from "../components/workbench/CausalChainOverlay.js";
import {
  buildMediaTimeline,
  type MediaTimelineMarker,
} from "../lib/aggregateEvents.js";
import { useWorkbenchStore } from "../state/workbench.js";

/**
 * WorkbenchMediaTimeline — video-anchored marker timeline for creators.
 *
 * Reads events directly from the workbench store (populated by SSE) and
 * derives markers via ``buildMediaTimeline``. Pure projection — no HTTP
 * fetches, live updates for free.
 *
 * Layout: top half is the source video (passed in via ``videoUrl`` prop —
 * resolved by ``Workbench.tsx`` from the same task status that powers the
 * frame/video toggle in the list view). Bottom half is a per-stage lane
 * chart where each AI decision is a marker (triangle for ``media_ts``;
 * shaded rectangle for ``media_ts_range``). The video's playhead pushes
 * ``currentMediaTs`` into the workbench store; markers within ±0.5s of
 * the playhead get an accent border. Clicking a marker seeks the video
 * AND selects the event in the central store, so other workbench panes
 * stay in sync.
 */

const PLAYHEAD_NEIGHBOURHOOD_SEC = 0.5;
const LANE_HEIGHT = 28;
const LANE_PADDING = 0.2;
const LEFT_MARGIN = 200;
const RIGHT_MARGIN = 16;
const TOP_MARGIN = 24;
const BOTTOM_MARGIN = 32;
const MARKER_HALF = 5;

interface Props {
  taskId: string;
  videoUrl: string | null;
}

export const WorkbenchMediaTimeline: React.FC<Props> = ({
  taskId: _taskId,
  videoUrl,
}) => {
  // taskId mirrored for routing parity; the store is already scoped.
  void _taskId;
  const events = useWorkbenchStore((s) => s.events);
  const { markers } = React.useMemo(() => buildMediaTimeline(events), [events]);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const setCurrentMediaTs = useWorkbenchStore((s) => s.setCurrentMediaTs);
  const currentMediaTs = useWorkbenchStore((s) => s.currentMediaTs);
  const setSelected = useWorkbenchStore((s) => s.setSelected);
  const setHoveredChainRoot = useWorkbenchStore((s) => s.setHoveredChainRoot);
  const selectedEventId = useWorkbenchStore((s) => s.selectedEventId);
  const { highlightSet } = useChainHighlight();
  const [videoDuration, setVideoDuration] = React.useState<number>(0);

  React.useEffect(() => {
    return () => setCurrentMediaTs(null);
  }, [setCurrentMediaTs]);

  const seekTo = React.useCallback((ts: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.max(0, ts);
  }, []);

  const handleMarkerClick = React.useCallback(
    (ev: MediaTimelineMarker) => {
      setSelected(ev.event_id);
      const ts = ev.media_ts ?? ev.media_ts_range?.[0] ?? null;
      if (ts !== null) seekTo(ts);
    },
    [setSelected, seekTo],
  );

  const lanes = React.useMemo(() => groupByStage(markers), [markers]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-default bg-surface px-4 py-2">
        <span className="font-mono text-[11px] text-tertiary">视频时长</span>
        <span className="font-mono text-[11px] text-secondary">
          {videoDuration > 0 ? `${videoDuration.toFixed(1)}s` : "—"}
        </span>
        <span className="font-mono text-[11px] text-tertiary">·</span>
        <span className="font-mono text-[11px] text-secondary">
          {markers.length} 个 anchored 事件
        </span>
        <span className="font-mono text-[11px] text-tertiary">·</span>
        <span className="font-mono text-[11px] text-secondary">
          当前 {currentMediaTs !== null ? `${currentMediaTs.toFixed(2)}s` : "未播放"}
        </span>
      </div>

      <div className="flex flex-shrink-0 justify-center bg-bg-canvas py-3">
        {videoUrl ? (
          <video
            ref={videoRef}
            src={videoUrl}
            controls
            className="max-h-[40vh] rounded-sm border border-default"
            onLoadedMetadata={(e) => {
              const v = e.target as HTMLVideoElement;
              if (Number.isFinite(v.duration)) setVideoDuration(v.duration);
              setCurrentMediaTs(v.currentTime);
            }}
            onTimeUpdate={(e) =>
              setCurrentMediaTs((e.target as HTMLVideoElement).currentTime)
            }
          />
        ) : (
          <div className="flex h-32 items-center text-tertiary">
            该任务无关联的 normalized.mp4，无法播放视频
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        <ParentSize>
          {({ width, height }) =>
            width > 0 && height > 0 && lanes.length > 0 ? (
              <TimelineCanvas
                lanes={lanes}
                width={width}
                height={height}
                videoDuration={videoDuration}
                currentMediaTs={currentMediaTs}
                selectedEventId={selectedEventId}
                highlightSet={highlightSet}
                onMarkerClick={handleMarkerClick}
                onScrub={seekTo}
                onMarkerHover={(id) => setHoveredChainRoot(id)}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-secondary">
                暂无 anchored 事件 · 媒体时间线为空
              </div>
            )
          }
        </ParentSize>
      </div>
    </div>
  );
};

interface CanvasProps {
  lanes: { stage: string; events: MediaTimelineMarker[] }[];
  width: number;
  height: number;
  videoDuration: number;
  currentMediaTs: number | null;
  selectedEventId: string | null;
  highlightSet: Set<string>;
  onMarkerClick: (ev: MediaTimelineMarker) => void;
  onScrub: (ts: number) => void;
  onMarkerHover: (id: string | null) => void;
}

const TimelineCanvas: React.FC<CanvasProps> = ({
  lanes,
  width,
  height,
  videoDuration,
  currentMediaTs,
  selectedEventId,
  highlightSet,
  onMarkerClick,
  onScrub,
  onMarkerHover,
}) => {
  // Lane content can exceed viewport — wrapper supplies vertical scroll.
  const laneContentHeight = lanes.length * LANE_HEIGHT;
  const innerH = Math.max(height - TOP_MARGIN - BOTTOM_MARGIN, laneContentHeight);
  const innerW = Math.max(0, width - LEFT_MARGIN - RIGHT_MARGIN);
  const totalSvgHeight = innerH + TOP_MARGIN + BOTTOM_MARGIN;

  // Domain falls back to 1 second when video duration hasn't been read
  // yet (loadedMetadata may still be pending) — keeps the X scale valid
  // until the real value arrives.
  const xScale = React.useMemo(
    () =>
      scaleLinear<number>({
        domain: [0, Math.max(videoDuration, 1)],
        range: [0, innerW],
      }),
    [videoDuration, innerW],
  );

  const yScale = React.useMemo(
    () =>
      scaleBand<string>({
        domain: lanes.map((l) => l.stage),
        range: [0, innerH],
        padding: LANE_PADDING,
      }),
    [lanes, innerH],
  );

  const handleScrub = React.useCallback(
    (e: React.MouseEvent<SVGRectElement>) => {
      const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
      const dx = e.clientX - rect.left;
      const ratio = dx / rect.width;
      const ts = ratio * Math.max(videoDuration, 1);
      onScrub(Math.max(0, Math.min(videoDuration, ts)));
    },
    [onScrub, videoDuration],
  );

  const xTicks = xScale.ticks(8);

  return (
    <div className="h-full w-full overflow-y-auto overflow-x-hidden">
      <svg width={width} height={totalSvgHeight} className="block">
        {/* Lane background bands. Rendered FIRST so the scrub rect we
            place next sits visually below markers but on top of the
            backgrounds. */}
        <Group left={LEFT_MARGIN} top={TOP_MARGIN}>
          {lanes.map((lane, i) => (
            <rect
              key={`bg-${lane.stage}`}
              x={0}
              y={yScale(lane.stage) ?? 0}
              width={innerW}
              height={yScale.bandwidth()}
              fill={i % 2 ? "var(--bg-subtle)" : "transparent"}
            />
          ))}

          {/* Vertical reference grid. */}
          {xTicks.map((t) => (
            <line
              key={`grid-${t}`}
              x1={xScale(t)}
              x2={xScale(t)}
              y1={0}
              y2={innerH}
              stroke="var(--border-default)"
              strokeDasharray="2 4"
              opacity={0.6}
            />
          ))}

          {/* Scrub overlay — placed BEFORE markers so it sits below them
              in SVG hit-test z-order. Empty areas between markers fall
              through to this rect; markers on top intercept their own
              clicks. The previous version put this rect last, which
              swallowed every marker click. */}
          <rect
            x={0}
            y={0}
            width={innerW}
            height={innerH}
            fill="transparent"
            onClick={handleScrub}
            style={{ cursor: "crosshair" }}
          />

          {/* Markers — on top of the scrub overlay so their onClick wins. */}
          {lanes.map((lane) => {
            const laneY = yScale(lane.stage) ?? 0;
            const midY = laneY + yScale.bandwidth() / 2;
            return lane.events.map((ev) => {
              const isSelected = selectedEventId === ev.event_id;
              const inChain = highlightSet.has(ev.event_id);
              const baseColor = ev.color_token;
              if (ev.media_ts_range) {
                const [s, e] = ev.media_ts_range;
                const x = xScale(s);
                const w = Math.max(2, xScale(e) - x);
                const isNear =
                  currentMediaTs !== null &&
                  currentMediaTs >= s - PLAYHEAD_NEIGHBOURHOOD_SEC &&
                  currentMediaTs <= e + PLAYHEAD_NEIGHBOURHOOD_SEC;
                const accent = isSelected || isNear || inChain;
                return (
                  <rect
                    key={ev.event_id}
                    x={x}
                    y={laneY + 4}
                    width={w}
                    height={yScale.bandwidth() - 8}
                    fill={baseColor}
                    opacity={inChain ? 0.55 : 0.35}
                    stroke={accent ? "var(--accent-primary)" : "transparent"}
                    strokeWidth={accent ? 1.5 : 0}
                    rx={2}
                    style={{ cursor: "pointer" }}
                    onClick={() => onMarkerClick(ev)}
                    onMouseEnter={() => onMarkerHover(ev.event_id)}
                    onMouseLeave={() => onMarkerHover(null)}
                  >
                    <title>
                      {ev.stage} · {s.toFixed(2)}s–{e.toFixed(2)}s
                      {"\n"}
                      {ev.semantic_label}
                    </title>
                  </rect>
                );
              }
              const ts = ev.media_ts;
              if (ts === null) return null;
              const x = xScale(ts);
              const isNear =
                currentMediaTs !== null &&
                Math.abs(currentMediaTs - ts) <= PLAYHEAD_NEIGHBOURHOOD_SEC;
              const accent = isSelected || isNear || inChain;
              return (
                <polygon
                  key={ev.event_id}
                  points={`${x - MARKER_HALF},${midY + MARKER_HALF} ${
                    x + MARKER_HALF
                  },${midY + MARKER_HALF} ${x},${midY - MARKER_HALF}`}
                  fill={baseColor}
                  stroke={accent ? "var(--accent-primary)" : "transparent"}
                  strokeWidth={accent ? 1.5 : 0}
                  style={{ cursor: "pointer" }}
                  onClick={() => onMarkerClick(ev)}
                  onMouseEnter={() => onMarkerHover(ev.event_id)}
                  onMouseLeave={() => onMarkerHover(null)}
                >
                  <title>
                    {ev.stage} · {ts.toFixed(2)}s
                    {"\n"}
                    {ev.semantic_label}
                  </title>
                </polygon>
              );
            });
          })}

          {/* Causal chains — only between events that both render here. */}
          {(() => {
            const positionByEv = new Map<
              string,
              { x: number; y: number }
            >();
            for (const lane of lanes) {
              const laneY =
                (yScale(lane.stage) ?? 0) + yScale.bandwidth() / 2;
              for (const ev of lane.events) {
                const ts = ev.media_ts ?? ev.media_ts_range?.[0] ?? null;
                if (ts === null) continue;
                positionByEv.set(ev.event_id, { x: xScale(ts), y: laneY });
              }
            }
            const paths: React.ReactNode[] = [];
            for (const lane of lanes) {
              for (const ev of lane.events) {
                if (!ev.parent_event_id) continue;
                const child = positionByEv.get(ev.event_id);
                const parent = positionByEv.get(ev.parent_event_id);
                if (!child || !parent) continue;
                paths.push(
                  <path
                    key={`chain-${ev.parent_event_id}-${ev.event_id}`}
                    d={`M ${parent.x},${parent.y} Q ${
                      (parent.x + child.x) / 2
                    },${(parent.y + child.y) / 2 - 16} ${child.x},${child.y}`}
                    fill="none"
                    stroke="var(--accent-primary)"
                    strokeWidth={0.8}
                    strokeDasharray="3 3"
                    opacity={0.5}
                    pointerEvents="none"
                  />,
                );
              }
            }
            return paths;
          })()}

          {/* Playhead. Drawn last (top-most) and pointer-events-none so
              it doesn't block clicks on markers underneath. */}
          {currentMediaTs !== null ? (
            <line
              x1={xScale(currentMediaTs)}
              x2={xScale(currentMediaTs)}
              y1={-6}
              y2={innerH + 6}
              stroke="var(--accent-primary)"
              strokeWidth={1.5}
              pointerEvents="none"
            />
          ) : null}
        </Group>

        {/* Lane labels. */}
        <Group top={TOP_MARGIN}>
          {lanes.map((lane) => (
            <text
              key={`lbl-${lane.stage}`}
              x={LEFT_MARGIN - 12}
              y={(yScale(lane.stage) ?? 0) + yScale.bandwidth() / 2 + 4}
              textAnchor="end"
              className="fill-text-secondary font-mono text-[11px]"
            >
              {lane.stage}
            </text>
          ))}
        </Group>

        {/* X-axis seconds. */}
        <Group left={LEFT_MARGIN} top={TOP_MARGIN + innerH + 6}>
          {xTicks.map((t) => (
            <text
              key={`tick-${t}`}
              x={xScale(t)}
              y={14}
              textAnchor="middle"
              className="fill-text-tertiary font-mono text-[10px]"
            >
              {t.toFixed(t < 1 ? 2 : 1)}s
            </text>
          ))}
        </Group>
      </svg>
    </div>
  );
};

function groupByStage(
  markers: readonly MediaTimelineMarker[],
): { stage: string; events: MediaTimelineMarker[] }[] {
  // Stable order: stages first appear in the marker list (already sorted
  // by media_ts). Within a stage, retain the server's order — predictable
  // for keyboard navigation later.
  const groups = new Map<string, MediaTimelineMarker[]>();
  for (const ev of markers) {
    const list = groups.get(ev.stage) ?? [];
    list.push(ev);
    groups.set(ev.stage, list);
  }
  return Array.from(groups.entries()).map(([stage, evs]) => ({
    stage,
    events: evs,
  }));
}
