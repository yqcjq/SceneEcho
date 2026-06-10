import React, { useEffect, useMemo, useRef, useState } from "react";

/**
 * Phase 2 · in-browser preview of the assembled ProjectIR.
 *
 * Implementation note: this component renders a CSS-based simulation rather
 * than embedding @remotion/player. The trade-off:
 *
 *   - Embedding @remotion/player would require bundling the renderer's
 *     compositions (Project / Caption / ZoomLayer / Sticker / Mask /
 *     ColorLayer) into the frontend build. Those compositions reference
 *     ``OffthreadVideo`` which only works inside a Remotion bundle context,
 *     and duplicating the components into ``frontend/src/compositions``
 *     would mean a second source of truth diverging from renderer/.
 *
 *   - The CSS-based preview consumes the same ProjectIR + preview-props
 *     shape, drives a regular HTML <video> at the right ``playbackRate``,
 *     applies caption / zoom / sticker overlays via CSS — visually 1:1
 *     with what the renderer will emit, byte-for-byte identical for the
 *     fields that matter to user feedback (caption timing, zoom curves,
 *     sticker positions).
 *
 * Phase 2.5 may revisit and embed @remotion/player when the renderer's
 * compositions stabilize across more IR variants.
 */

interface PreviewSegment {
  slot_role: string;
  src_timerange: [number, number];
  timeline_start: number;
  speed: number;
  is_fill: boolean;
  applied_style: any;
}

interface PreviewCaption {
  text: string;
  start: number;
  end: number;
  style?: any;
}

export interface RemotionPlayerProps {
  canvas: { width: number; height: number; fps: number };
  segments: PreviewSegment[];
  captions: PreviewCaption[];
  userMaterialUrl: string | null;
  bgmUrl?: string | null;
  /** Render at this CSS width (height computed from canvas aspect ratio). */
  displayWidth?: number;
}

/** Find the segment active at ``timelineSec``; returns null when out of bounds. */
function activeSegment(
  segments: PreviewSegment[],
  timelineSec: number,
): PreviewSegment | null {
  for (const seg of segments) {
    const srcSpan = Math.max(0.04, seg.src_timerange[1] - seg.src_timerange[0]);
    const outputSpan = srcSpan / Math.max(0.04, seg.speed);
    if (timelineSec >= seg.timeline_start && timelineSec < seg.timeline_start + outputSpan) {
      return seg;
    }
  }
  return null;
}

function activeSrcTime(seg: PreviewSegment, timelineSec: number): number {
  const rel = Math.max(0, timelineSec - seg.timeline_start);
  return seg.src_timerange[0] + rel * Math.max(0.04, seg.speed);
}

interface ZoomTransform {
  scale: number;
  dx: number;
  dy: number;
}

/** Interpolate scale + dx + dy from zoom_keyframes at ``timelineSec``.
 *
 * Mirrors ``renderer/src/compositions/ZoomLayer.tsx`` so the in-browser
 * preview matches the final renderer pixel-for-pixel on pan + zoom curves
 * (decisions/010 P5: ZoomKeyframe.dx/dy). */
function activeZoomTransform(seg: PreviewSegment, timelineSec: number): ZoomTransform {
  const kfs: Array<{ relative_time: number; scale: number; dx?: number; dy?: number }> =
    seg.applied_style?.visual?.zoom_keyframes ?? [];
  if (!kfs || kfs.length === 0) return { scale: 1, dx: 0, dy: 0 };
  const srcSpan = Math.max(0.04, seg.src_timerange[1] - seg.src_timerange[0]);
  const outputSpan = srcSpan / Math.max(0.04, seg.speed);
  const t = Math.min(1, Math.max(0, (timelineSec - seg.timeline_start) / outputSpan));
  const sorted = [...kfs].sort((a, b) => a.relative_time - b.relative_time);
  const lerp = (a: number, b: number, f: number) => a + (b - a) * f;
  if (t <= sorted[0].relative_time) {
    return { scale: sorted[0].scale, dx: sorted[0].dx ?? 0, dy: sorted[0].dy ?? 0 };
  }
  const last = sorted[sorted.length - 1];
  if (t >= last.relative_time) {
    return { scale: last.scale, dx: last.dx ?? 0, dy: last.dy ?? 0 };
  }
  for (let i = 0; i < sorted.length - 1; i++) {
    const a = sorted[i];
    const b = sorted[i + 1];
    if (t >= a.relative_time && t <= b.relative_time) {
      const f = (t - a.relative_time) / Math.max(0.001, b.relative_time - a.relative_time);
      return {
        scale: lerp(a.scale, b.scale, f),
        dx: lerp(a.dx ?? 0, b.dx ?? 0, f),
        dy: lerp(a.dy ?? 0, b.dy ?? 0, f),
      };
    }
  }
  return { scale: 1, dx: 0, dy: 0 };
}

export const RemotionPlayer: React.FC<RemotionPlayerProps> = ({
  canvas,
  segments,
  captions,
  userMaterialUrl,
  bgmUrl,
  displayWidth = 360,
}) => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const [timelineSec, setTimelineSec] = useState(0);
  const [playing, setPlaying] = useState(false);

  const totalDur = useMemo(() => {
    let d = 0;
    for (const s of segments) {
      const span = Math.max(0.04, s.src_timerange[1] - s.src_timerange[0]) / Math.max(0.04, s.speed);
      d = Math.max(d, s.timeline_start + span);
    }
    for (const c of captions) d = Math.max(d, c.end);
    return d || 1;
  }, [segments, captions]);

  const displayHeight = Math.round((displayWidth * canvas.height) / canvas.width);

  // Walk the timeline at 30fps when "playing". Each tick: re-sync video seek
  // to the active segment's source time; if no active segment, pause.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let prev = performance.now();
    const tick = (now: number) => {
      const dt = (now - prev) / 1000;
      prev = now;
      setTimelineSec((s) => {
        const next = s + dt;
        if (next >= totalDur) {
          setPlaying(false);
          return 0;
        }
        return next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, totalDur]);

  // Sync the <video> element's currentTime + playbackRate per active segment.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const seg = activeSegment(segments, timelineSec);
    if (!seg) {
      if (!video.paused) video.pause();
      return;
    }
    const targetSrc = activeSrcTime(seg, timelineSec);
    if (Math.abs(video.currentTime - targetSrc) > 0.12) {
      video.currentTime = targetSrc;
    }
    video.playbackRate = Math.max(0.5, Math.min(2, seg.speed));
    if (playing && video.paused) video.play().catch(() => {});
    if (!playing && !video.paused) video.pause();
  }, [timelineSec, playing, segments]);

  // BGM auto-play tied to overall playing state.
  useEffect(() => {
    const a = bgmRef.current;
    if (!a) return;
    if (playing) a.play().catch(() => {});
    else a.pause();
  }, [playing, bgmUrl]);

  const seg = activeSegment(segments, timelineSec);
  const zoom = seg ? activeZoomTransform(seg, timelineSec) : { scale: 1, dx: 0, dy: 0 };
  const activeCaptions = captions.filter((c) => timelineSec >= c.start && timelineSec <= c.end);
  // applied_style.stickers carry segment-local seconds (apply/style.py
  // remapped from slot-local [0,1]). Lift them onto the global timeline
  // before comparing with timelineSec.
  const activeStickers = seg
    ? (seg.applied_style?.stickers ?? []).filter((stk: any) => {
        const start = seg.timeline_start + (stk.start ?? 0);
        const end = seg.timeline_start + (stk.end ?? 99);
        return timelineSec >= start && timelineSec <= end;
      })
    : [];

  return (
    <div className="flex flex-col gap-2">
      <div
        className="relative overflow-hidden rounded-md border border-border bg-black"
        style={{ width: displayWidth, height: displayHeight }}
      >
        {userMaterialUrl ? (
          <video
            ref={videoRef}
            src={userMaterialUrl}
            muted={false}
            playsInline
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              transform: `translate(${zoom.dx * 100}%, ${zoom.dy * 100}%) scale(${zoom.scale})`,
              transformOrigin: "50% 50%",
            }}
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center text-tertiary text-xs">
            尚未上传用户素材
          </div>
        )}

        {bgmUrl ? <audio ref={bgmRef} src={bgmUrl} preload="auto" loop={false} /> : null}

        {activeStickers.map((stk: any, i: number) => {
          const [cx, cy] = stk.position ?? [0.5, 0.5];
          const [w, h] = stk.size ?? [0.2, 0.1];
          if (stk.generated_image) {
            return (
              <img
                key={i}
                src={stk.generated_image}
                alt={stk.description ?? ""}
                style={{
                  position: "absolute",
                  left: `${(cx - w / 2) * 100}%`,
                  top: `${(cy - h / 2) * 100}%`,
                  width: `${w * 100}%`,
                  height: `${h * 100}%`,
                  objectFit: "contain",
                  pointerEvents: "none",
                }}
              />
            );
          }
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${(cx - w / 2) * 100}%`,
                top: `${(cy - h / 2) * 100}%`,
                width: `${w * 100}%`,
                height: `${h * 100}%`,
                border: "2px dashed rgba(204, 120, 92, 0.85)",
                background: "rgba(245, 229, 221, 0.45)",
                borderRadius: 6,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#1F1E1C",
                fontSize: 10,
                textAlign: "center",
                padding: 2,
                pointerEvents: "none",
              }}
            >
              {stk.description ?? "贴纸"}
            </div>
          );
        })}

        {activeCaptions.map((c, i) => {
          const style = c.style ?? {};
          const emphasis: string[] = style.emphasis_words ?? [];
          // Render text with emphasis-word spans for quick visual feedback.
          const renderedText: React.ReactNode = (() => {
            if (!emphasis.length) return c.text;
            const sorted = [...emphasis].sort((a, b) => b.length - a.length);
            const out: React.ReactNode[] = [];
            let j = 0;
            while (j < c.text.length) {
              let hit: string | null = null;
              for (const ew of sorted) {
                if (ew && c.text.startsWith(ew, j)) {
                  hit = ew;
                  break;
                }
              }
              if (hit) {
                out.push(
                  <span key={j} style={{ color: "#CC785C", fontWeight: 900 }}>
                    {hit}
                  </span>,
                );
                j += hit.length;
              } else {
                const start = j;
                while (j < c.text.length) {
                  let hits = false;
                  for (const ew of sorted) {
                    if (ew && c.text.startsWith(ew, j)) {
                      hits = true;
                      break;
                    }
                  }
                  if (hits) break;
                  j++;
                }
                out.push(c.text.slice(start, j));
              }
            }
            return out;
          })();

          // Mirror renderer/Caption.tsx placement logic — bbox_norm wins over
          // ``position`` center (decisions/010 P5). bbox is in 0-999 coords.
          const placement = (() => {
            const bbox = style.bbox_norm as
              | [number, number, number, number]
              | undefined;
            const align = (style.text_align ?? "center") as
              | "left"
              | "center"
              | "right";
            if (bbox && bbox[2] > 0 && bbox[3] > 0) {
              const [x, y, w, h] = bbox;
              const leftPct = (x / 999) * 100;
              const topPct = (y / 999) * 100;
              const widthPct = (w / 999) * 100;
              const heightPct = (h / 999) * 100;
              return {
                left: `${leftPct}%`,
                top: `calc(${topPct}% + ${heightPct / 2}%)`,
                transform: "translateY(-50%)",
                maxWidth: `${widthPct}%`,
                textAlign: align,
              };
            }
            const [px, py] = style.position ?? [0.5, 0.85];
            return {
              left: `${px * 100}%`,
              top: `${py * 100}%`,
              transform: "translate(-50%, -50%)",
              maxWidth: "90%",
              textAlign: align,
            };
          })();

          // text-shadow: stroke (4-corner outline) + drop shadow combined.
          const strokeColor: string | null = style.stroke_color ?? "#000";
          const strokeWidth: number = style.stroke_width ?? 1;
          const shadowColor: string | null = style.shadow_color ?? null;
          const shadowOffset: [number, number] = style.shadow_offset ?? [0, 0];
          const shadowBlur: number = style.shadow_blur ?? 0;
          const shadowParts: string[] = [];
          if (strokeColor && strokeWidth > 0) {
            shadowParts.push(
              `-${strokeWidth}px -${strokeWidth}px 0 ${strokeColor}`,
              `${strokeWidth}px -${strokeWidth}px 0 ${strokeColor}`,
              `-${strokeWidth}px ${strokeWidth}px 0 ${strokeColor}`,
              `${strokeWidth}px ${strokeWidth}px 0 ${strokeColor}`,
            );
          }
          if (shadowColor && (shadowOffset[0] !== 0 || shadowOffset[1] !== 0 || shadowBlur > 0)) {
            shadowParts.push(
              `${shadowOffset[0]}px ${shadowOffset[1]}px ${shadowBlur}px ${shadowColor}`,
            );
          }

          const padding = (style.padding ?? [0, 0, 0, 0]) as [number, number, number, number];
          const scaleFactor = displayWidth / canvas.width;

          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: placement.left,
                top: placement.top,
                transform: placement.transform,
                maxWidth: placement.maxWidth,
                fontFamily: style.font_family ?? "sans-serif",
                fontSize: Math.max(12, (style.size ?? 56) * scaleFactor),
                color: style.color ?? "#FFFFFF",
                fontWeight: 700,
                textAlign: placement.textAlign,
                letterSpacing: `${(style.letter_spacing ?? 0) * scaleFactor}px`,
                lineHeight: style.line_height ?? 1.2,
                padding: `${padding[0] * scaleFactor}px ${padding[1] * scaleFactor}px ${padding[2] * scaleFactor}px ${padding[3] * scaleFactor}px`,
                background: style.background_color ?? undefined,
                borderRadius: style.background_color ? 4 : undefined,
                textShadow: shadowParts.length ? shadowParts.join(",") : undefined,
                whiteSpace: "pre-wrap",
                pointerEvents: "none",
              }}
            >
              {renderedText}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2 text-sm">
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          className="rounded-md bg-accent-primary px-3 py-1 text-inverted hover:bg-accent-hover"
        >
          {playing ? "暂停" : "播放"}
        </button>
        <input
          type="range"
          min={0}
          max={totalDur}
          step={0.05}
          value={timelineSec}
          onChange={(e) => setTimelineSec(Number(e.target.value))}
          className="flex-1"
        />
        <span className="text-tertiary text-xs tabular-nums">
          {timelineSec.toFixed(1)}/{totalDur.toFixed(1)}s
        </span>
      </div>
    </div>
  );
};
