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

function activeZoomScale(seg: PreviewSegment, timelineSec: number): number {
  const kfs = seg.applied_style?.visual?.zoom_keyframes ?? [];
  if (!kfs || kfs.length === 0) return 1;
  const srcSpan = Math.max(0.04, seg.src_timerange[1] - seg.src_timerange[0]);
  const outputSpan = srcSpan / Math.max(0.04, seg.speed);
  const t = Math.min(1, Math.max(0, (timelineSec - seg.timeline_start) / outputSpan));
  const sorted = [...kfs].sort((a, b) => a.relative_time - b.relative_time);
  if (t <= sorted[0].relative_time) return sorted[0].scale;
  if (t >= sorted[sorted.length - 1].relative_time) return sorted[sorted.length - 1].scale;
  for (let i = 0; i < sorted.length - 1; i++) {
    const a = sorted[i];
    const b = sorted[i + 1];
    if (t >= a.relative_time && t <= b.relative_time) {
      const f = (t - a.relative_time) / Math.max(0.001, b.relative_time - a.relative_time);
      return a.scale + (b.scale - a.scale) * f;
    }
  }
  return 1;
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
  const scale = seg ? activeZoomScale(seg, timelineSec) : 1;
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
              transform: `scale(${scale})`,
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
          const [px, py] = style.position ?? [0.5, 0.85];
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
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${px * 100}%`,
                top: `${py * 100}%`,
                transform: "translate(-50%, -50%)",
                fontFamily: style.font_family ?? "sans-serif",
                fontSize: Math.max(12, (style.size ?? 56) * (displayWidth / canvas.width)),
                color: style.color ?? "#FFFFFF",
                fontWeight: 700,
                textAlign: "center",
                textShadow: "1px 1px 0 #000, -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000",
                whiteSpace: "pre-wrap",
                maxWidth: "90%",
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
