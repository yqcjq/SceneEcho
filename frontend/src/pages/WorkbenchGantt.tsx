import { Group } from "@visx/group";
import { ParentSize } from "@visx/responsive";
import { scaleBand, scaleLinear } from "@visx/scale";
import { Zoom } from "@visx/zoom";
import React from "react";
import { useChainHighlight } from "../components/workbench/CausalChainOverlay.js";
import {
  buildGantt,
  type GanttEvent,
  type GanttPayload,
} from "../lib/aggregateEvents.js";
import { useWorkbenchStore } from "../state/workbench.js";

/**
 * WorkbenchGantt — wall-clock lanes for AI engineers debugging a run.
 *
 * Reads events directly from the workbench store (which the SSE
 * subscription already keeps live) and derives lane data via
 * ``buildGantt``. No HTTP fetch — the page becomes a pure projection of
 * the store, and live updates are free.
 *
 * Each ``stage`` is one Y-band lane; events render as horizontal bars
 * (``duration_ms > 0``) or vertical ticks (``duration_ms == 0``). The X
 * axis is "ms since the run's earliest call started" (NOT since the
 * earliest event was published — those would put the bar in the future).
 *
 * Causal chains (``parent_event_id``) draw dashed quadratic curves between
 * the parent event's end and the child event's start. When the lane count
 * exceeds the viewport's vertical capacity, the SVG height grows past the
 * container and the wrapping ``<div>`` scrolls vertically — the X axis is
 * pinned to the visible viewport via a separate scroll-fixed footer so
 * users can scroll lanes without losing the time axis.
 */

const LANE_HEIGHT = 32;
const LANE_PADDING = 0.25;
const BAR_HEIGHT = 16;
const LEFT_MARGIN = 220;
const TOP_MARGIN = 28;
const BOTTOM_MARGIN = 32;
const RIGHT_MARGIN = 16;
const AXIS_TICK_COUNT = 6;

interface Props {
  taskId: string;
}

export const WorkbenchGantt: React.FC<Props> = ({ taskId: _taskId }) => {
  // taskId is plumbed for routing parity but not needed here — the store
  // is already scoped to one task by ``Workbench.tsx``'s ``reset`` call.
  void _taskId;
  const events = useWorkbenchStore((s) => s.events);
  const data = React.useMemo<GanttPayload>(() => buildGantt(events), [events]);

  if (data.lanes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-secondary">
        暂无事件，等待 AI 决策……
      </div>
    );
  }
  return (
    <ParentSize>
      {({ width, height }) =>
        width > 0 && height > 0 ? (
          <GanttCanvas data={data} width={width} height={height} />
        ) : null
      }
    </ParentSize>
  );
};

interface CanvasProps {
  data: GanttPayload;
  width: number;
  height: number;
}

const GanttCanvas: React.FC<CanvasProps> = ({ data, width, height }) => {
  const setSelected = useWorkbenchStore((s) => s.setSelected);
  const setHoveredChainRoot = useWorkbenchStore((s) => s.setHoveredChainRoot);
  const selectedEventId = useWorkbenchStore((s) => s.selectedEventId);
  const { highlightSet } = useChainHighlight();

  // Lane-content height = lanes.length * LANE_HEIGHT. When this exceeds the
  // viewport, we let the wrapper div scroll. The SVG width still fills the
  // container so the X axis isn't artificially compressed.
  const laneContentHeight = data.lanes.length * LANE_HEIGHT;
  const innerH = Math.max(height - TOP_MARGIN - BOTTOM_MARGIN, laneContentHeight);
  const innerW = Math.max(0, width - LEFT_MARGIN - RIGHT_MARGIN);
  const totalSvgHeight = innerH + TOP_MARGIN + BOTTOM_MARGIN;

  // Total domain padded by 5% so a task with one tiny event still gets a
  // sensible X axis instead of a degenerate zero-width domain.
  const xMax = Math.max(data.total_duration_ms, 100);
  const xPadded = Math.ceil(xMax * 1.05);

  const xScale = React.useMemo(
    () => scaleLinear<number>({ domain: [0, xPadded], range: [0, innerW] }),
    [xPadded, innerW],
  );
  const yScale = React.useMemo(
    () =>
      scaleBand<string>({
        domain: data.lanes.map((l) => l.stage),
        range: [0, innerH],
        padding: LANE_PADDING,
      }),
    [data.lanes, innerH],
  );

  // Index events for parent → child lookup so causal chains can resolve in
  // O(1). The key is event_id; the value carries the rendered geometry so
  // chain rendering doesn't redo the scale math.
  const eventGeom = React.useMemo(() => {
    const map = new Map<
      string,
      {
        ev: GanttEvent;
        stage: string;
        x: number;
        w: number;
        y: number;
      }
    >();
    for (const lane of data.lanes) {
      const laneY = yScale(lane.stage) ?? 0;
      const midY = laneY + (yScale.bandwidth() - BAR_HEIGHT) / 2;
      for (const ev of lane.events) {
        const x = xScale(ev.start_ms);
        const wRaw = xScale(ev.end_ms) - x;
        const w = Math.max(1.5, wRaw);
        map.set(ev.event_id, { ev, stage: lane.stage, x, w, y: midY });
      }
    }
    return map;
  }, [data.lanes, xScale, yScale]);

  const xTicks = React.useMemo(() => xScale.ticks(AXIS_TICK_COUNT), [xScale]);

  return (
    // ``overflow-y-auto`` lets the wrapper scroll when totalSvgHeight
    // exceeds the parent height (e.g. long-video Phase 3 with many
    // stages). The X axis ticks travel with the SVG so they're correct
    // at every scroll position; lane labels are part of the SVG so they
    // also scroll with the content.
    <div className="relative h-full w-full overflow-y-auto overflow-x-hidden bg-canvas">
      <Zoom<SVGSVGElement>
        width={width}
        height={totalSvgHeight}
        scaleXMin={0.5}
        scaleXMax={20}
        scaleYMin={1}
        scaleYMax={1}
        initialTransformMatrix={{
          scaleX: 1,
          scaleY: 1,
          translateX: 0,
          translateY: 0,
          skewX: 0,
          skewY: 0,
        }}
      >
        {(zoom) => (
          <svg
            ref={zoom.containerRef}
            width={width}
            height={totalSvgHeight}
            className="block touch-none cursor-grab active:cursor-grabbing"
            onWheel={(e) => {
              // Hold shift to translate horizontally; default wheel is
              // X-axis zoom. Vertical scroll passes through to the wrapper
              // when the user is NOT zooming — that's the natural
              // "scroll lanes" gesture.
              if (!e.shiftKey && e.ctrlKey === false && e.altKey === false) {
                // Pure scroll without modifier: defer to the wrapper's
                // native vertical scrolling. Don't preventDefault so the
                // page scrolls.
                if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && !e.metaKey) {
                  // Modifier-free vertical wheel → let the parent scroll.
                  return;
                }
              }
              e.preventDefault();
              const point = { x: e.clientX, y: e.clientY };
              if (e.shiftKey) {
                zoom.translate({ translateX: -e.deltaY, translateY: 0 });
              } else {
                const factor = e.deltaY > 0 ? 0.95 : 1.05;
                zoom.scale({ scaleX: factor, scaleY: 1, point });
              }
            }}
            onMouseDown={zoom.dragStart}
            onMouseMove={zoom.dragMove}
            onMouseUp={zoom.dragEnd}
            onMouseLeave={() => {
              if (zoom.isDragging) zoom.dragEnd();
            }}
          >
            {/* Lane background bands. */}
            <Group left={LEFT_MARGIN} top={TOP_MARGIN}>
              {data.lanes.map((lane, i) => (
                <rect
                  key={`bg-${lane.stage}`}
                  x={0}
                  y={yScale(lane.stage) ?? 0}
                  width={innerW}
                  height={yScale.bandwidth()}
                  fill={i % 2 ? "var(--bg-subtle)" : "transparent"}
                />
              ))}
            </Group>

            {/* Lane labels (left gutter). */}
            <Group top={TOP_MARGIN}>
              {data.lanes.map((lane) => (
                <text
                  key={`lbl-${lane.stage}`}
                  x={LEFT_MARGIN - 12}
                  y={
                    (yScale(lane.stage) ?? 0) +
                    yScale.bandwidth() / 2 +
                    4
                  }
                  textAnchor="end"
                  className="fill-text-secondary font-mono text-[11px]"
                >
                  {lane.stage}
                  <tspan className="fill-text-tertiary"> · {lane.events.length}</tspan>
                </text>
              ))}
            </Group>

            {/* Zoomable layer — bars + ticks + causal chains. Apply the
                zoom transform only to the X dimension by extracting
                translateX/scaleX from the matrix; vertical layout stays
                static so lane bands keep aligning with the labels. */}
            <Group left={LEFT_MARGIN} top={TOP_MARGIN}>
              <g
                transform={`translate(${zoom.transformMatrix.translateX}, 0) scale(${zoom.transformMatrix.scaleX}, 1)`}
              >
                {data.lanes.map((lane) =>
                  lane.events.map((ev) => {
                    const geom = eventGeom.get(ev.event_id);
                    if (!geom) return null;
                    const isSelected = selectedEventId === ev.event_id;
                    const inChain = highlightSet.has(ev.event_id);
                    const baseColor = lane.color_token;
                    const accent =
                      isSelected || inChain ? "var(--accent-primary)" : null;
                    if ((ev.duration_ms ?? 0) > 0) {
                      return (
                        <rect
                          key={ev.event_id}
                          x={geom.x}
                          y={geom.y}
                          width={geom.w}
                          height={BAR_HEIGHT}
                          rx={3}
                          fill={baseColor}
                          opacity={ev.severity === "warning" ? 0.6 : 0.9}
                          stroke={accent ?? "transparent"}
                          strokeWidth={isSelected ? 2 : inChain ? 1.5 : 0}
                          // Counter-scale stroke so it doesn't grow with
                          // X zoom — keeps the bars crisp.
                          vectorEffect="non-scaling-stroke"
                          style={{ cursor: "pointer" }}
                          onClick={() => setSelected(ev.event_id)}
                          onMouseEnter={() => setHoveredChainRoot(ev.event_id)}
                          onMouseLeave={() => setHoveredChainRoot(null)}
                        >
                          <title>
                            {ev.stage} · {ev.semantic_label}
                            {"\n"}
                            duration {ev.duration_ms}ms · 置信度{" "}
                            {ev.confidence.toFixed(2)}
                            {ev.reasoning ? `\n${ev.reasoning.slice(0, 200)}` : ""}
                          </title>
                        </rect>
                      );
                    }
                    return (
                      <line
                        key={ev.event_id}
                        x1={geom.x}
                        x2={geom.x}
                        y1={geom.y - 2}
                        y2={geom.y + BAR_HEIGHT + 2}
                        stroke={accent ?? baseColor}
                        strokeWidth={isSelected ? 3 : inChain ? 2 : 1.5}
                        vectorEffect="non-scaling-stroke"
                        style={{ cursor: "pointer" }}
                        onClick={() => setSelected(ev.event_id)}
                        onMouseEnter={() => setHoveredChainRoot(ev.event_id)}
                        onMouseLeave={() => setHoveredChainRoot(null)}
                      >
                        <title>
                          {ev.stage} · {ev.semantic_label}
                          {ev.reasoning ? `\n${ev.reasoning.slice(0, 200)}` : ""}
                        </title>
                      </line>
                    );
                  }),
                )}

                {/* Causal chains — dashed quadratic curve from parent's
                    right edge to child's left edge. Skipped when the
                    parent event isn't on this view. */}
                {Array.from(eventGeom.values()).map(({ ev, x, y }) => {
                  const parentId = ev.parent_event_id;
                  if (!parentId) return null;
                  const parent = eventGeom.get(parentId);
                  if (!parent) return null;
                  const px = parent.x + parent.w;
                  const py = parent.y + BAR_HEIGHT / 2;
                  const cy = y + BAR_HEIGHT / 2;
                  const midX = (px + x) / 2;
                  return (
                    <path
                      key={`chain-${parentId}-${ev.event_id}`}
                      d={`M ${px},${py} Q ${midX},${py} ${midX},${cy} T ${x},${cy}`}
                      fill="none"
                      stroke="var(--accent-primary)"
                      strokeWidth={1}
                      strokeDasharray="3 3"
                      opacity={0.55}
                      vectorEffect="non-scaling-stroke"
                    />
                  );
                })}
              </g>
            </Group>

            {/* X axis ticks — at the bottom of the lane area. */}
            <Group left={LEFT_MARGIN} top={TOP_MARGIN + innerH + 6}>
              <g
                transform={`translate(${zoom.transformMatrix.translateX}, 0) scale(${zoom.transformMatrix.scaleX}, 1)`}
              >
                {xTicks.map((t) => (
                  <line
                    key={`tick-${t}`}
                    x1={xScale(t)}
                    x2={xScale(t)}
                    y1={-innerH - 6}
                    y2={4}
                    stroke="var(--border-default)"
                    strokeDasharray="2 4"
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              </g>
              {xTicks.map((t) => {
                // Compute post-zoom x manually so labels translate but
                // don't scale — keeps text at fixed font size.
                const px =
                  zoom.transformMatrix.translateX +
                  xScale(t) * zoom.transformMatrix.scaleX;
                if (px < -40 || px > innerW + 40) return null;
                return (
                  <text
                    key={`tlbl-${t}`}
                    x={px}
                    y={20}
                    textAnchor="middle"
                    className="fill-text-tertiary font-mono text-[10px]"
                  >
                    {t >= 1000 ? `${(t / 1000).toFixed(1)}s` : `${t}ms`}
                  </text>
                );
              })}
            </Group>
          </svg>
        )}
      </Zoom>
      <div className="pointer-events-none sticky bottom-2 right-3 ml-auto w-fit rounded-sm border border-default bg-surface px-2 py-1 font-mono text-[10px] text-tertiary">
        滚轮 X 缩放 · 拖拽 X 平移 · Shift+滚轮 横向滚动 · 纵向滚动看更多 lane
      </div>
    </div>
  );
};
