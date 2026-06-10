import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

/**
 * Phase 2 · zoom + pan keyframe layer (PLAN 1629; ZoomKeyframe.dx/dy in
 * decisions/010 P5).
 *
 * Consumes ``zoom_keyframes`` (StyleRule.visual.zoom_keyframes) — an array of
 * ``{relative_time: 0..1, scale: number, dx?: number, dy?: number}`` — and
 * interpolates scale/dx/dy via Remotion's ``interpolate`` across the segment's
 * local frame range. CSS ``transform: translate3d(dx*100%, dy*100%, 0) scale(s)``
 * applies all three with center origin in one composite transform.
 *
 * dx/dy are normalized to frame width/height; ±0.5 = half-frame pan. Camera
 * pan source is ``motion.estimate_zoom_curve`` (LK optical flow centroid drift,
 * decisions/010 P2). Default 0.0 keeps existing fixtures backward-compatible —
 * old templates without dx/dy render identically to before.
 *
 * Center origin is fixed at (50%, 50%) for Phase 2; face-aware center
 * (chase the speaker's mouth) is Phase 4.
 */
export interface ZoomKeyframe {
  relative_time: number;
  scale: number;
  /** Normalized pan offset (frame-width / frame-height units). 0.0 = no pan. */
  dx?: number;
  dy?: number;
}

export interface ZoomLayerProps {
  zoomKeyframes: ZoomKeyframe[];
  segmentDurationInFrames: number;
  children: React.ReactNode;
}

/** True identity: scale ≈ 1 AND no pan. Single-frame curves with non-zero
 * dx/dy still need the wrapper so the pan applies. */
function isIdentity(kfs: ZoomKeyframe[]): boolean {
  if (!kfs || kfs.length === 0) return true;
  if (kfs.length !== 1) return false;
  const k = kfs[0];
  return Math.abs(k.scale - 1) < 0.01 && Math.abs(k.dx ?? 0) < 0.001 && Math.abs(k.dy ?? 0) < 0.001;
}

export const ZoomLayer: React.FC<ZoomLayerProps> = ({
  zoomKeyframes,
  segmentDurationInFrames,
  children,
}) => {
  const frame = useCurrentFrame();
  // Identity transform → skip the CSS wrapper to avoid unnecessary repaints.
  if (isIdentity(zoomKeyframes)) {
    return <>{children}</>;
  }

  // Sort by relative_time defensively — pipeline stitches per-scene curves
  // and could produce slightly out-of-order entries at slot boundaries.
  const sorted = [...zoomKeyframes].sort((a, b) => a.relative_time - b.relative_time);
  const inputRange = sorted.map((kf) =>
    Math.max(0, Math.min(segmentDurationInFrames, kf.relative_time * segmentDurationInFrames)),
  );
  const scaleRange = sorted.map((kf) => kf.scale);
  const dxRange = sorted.map((kf) => kf.dx ?? 0);
  const dyRange = sorted.map((kf) => kf.dy ?? 0);

  // interpolate needs at least 2 points to do useful work; duplicate when
  // only one keyframe was given so all three channels stay consistent.
  const xs = inputRange.length === 1 ? [inputRange[0], inputRange[0] + 1] : inputRange;
  const dup = xs.length !== inputRange.length;
  const ys = dup ? [scaleRange[0], scaleRange[0]] : scaleRange;
  const dxs = dup ? [dxRange[0], dxRange[0]] : dxRange;
  const dys = dup ? [dyRange[0], dyRange[0]] : dyRange;

  const scale = interpolate(frame, xs, ys, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const dx = interpolate(frame, xs, dxs, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const dy = interpolate(frame, xs, dys, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        // Order matters: translate first, then scale around center. Both
        // operations originate at (50%, 50%) so pan + zoom feel cinematic.
        transform: `translate(${dx * 100}%, ${dy * 100}%) scale(${scale})`,
        transformOrigin: "50% 50%",
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
