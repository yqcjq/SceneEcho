// Derive video dimensions and total duration from a ProjectIR.
// Used by both calculateMetadata (Composition) and render diagnostics.

export interface CanvasMeta {
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  durationSec: number;
}

const DEFAULTS = { width: 1080, height: 1920, fps: 30 };

export function projectMeta(projectIR: any): CanvasMeta {
  const canvas = projectIR?.canvas ?? {};
  const width = canvas.width ?? DEFAULTS.width;
  const height = canvas.height ?? DEFAULTS.height;
  const fps = canvas.fps ?? DEFAULTS.fps;

  let durSec = 0;
  for (const sec of projectIR?.sections ?? []) {
    for (const seg of sec.segments ?? []) {
      const [s, e] = seg.src_timerange ?? [0, 0];
      // Phase 2: segment output duration accounts for the speed factor —
      // a 0.8x speed segment plays longer than its src range. Mapping +
      // fill clamp speed to [0.5, 1.2] so the divisor is always positive.
      const speed = Math.max(0.04, Number(seg.speed ?? 1.0));
      const outputSpan = Math.max(0, (e - s) / speed);
      durSec = Math.max(durSec, (seg.timeline_start ?? 0) + outputSpan);
    }
  }
  // Captions can extend past the last segment (fill text captions sit on
  // gap slots whose styling segment may be shorter than the caption's
  // nominal span). Stretch durSec to include their end.
  for (const cap of projectIR?.captions ?? []) {
    if (typeof cap?.end === "number" && cap.end > durSec) durSec = cap.end;
  }
  if (durSec <= 0) durSec = 5;

  return {
    width,
    height,
    fps,
    durationSec: durSec,
    durationInFrames: Math.max(1, Math.round(durSec * fps)),
  };
}
