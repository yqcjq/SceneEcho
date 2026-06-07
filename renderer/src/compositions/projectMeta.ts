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
      durSec = Math.max(durSec, (seg.timeline_start ?? 0) + (e - s));
    }
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
