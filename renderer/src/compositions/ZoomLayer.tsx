import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * Phase 2 · zoom keyframe layer (PLAN 1629).
 *
 * Consumes ``zoom_keyframes`` (StyleRule.visual.zoom_keyframes) — an array of
 * ``{relative_time: 0..1, scale: number}`` — and interpolates the current
 * scale via Remotion's ``interpolate`` across the segment's local frame
 * range. CSS ``transform: scale(N)`` applies the value with center origin.
 *
 * Center origin is fixed at (50%, 50%) for Phase 2; face-aware center
 * (chase the speaker's mouth) is Phase 4.
 *
 * Designed to wrap one PlacedSegment's video: ``segmentDurationInFrames``
 * comes from the parent ``<Sequence durationInFrames=...>``. ``children``
 * is the video stack the zoom should apply to.
 */
export interface ZoomKeyframe {
  relative_time: number;
  scale: number;
}

export interface ZoomLayerProps {
  zoomKeyframes: ZoomKeyframe[];
  segmentDurationInFrames: number;
  children: React.ReactNode;
}

export const ZoomLayer: React.FC<ZoomLayerProps> = ({
  zoomKeyframes,
  segmentDurationInFrames,
  children,
}) => {
  const frame = useCurrentFrame();
  // Empty / single-stable keyframe → identity transform. Skipping the
  // CSS wrapper avoids unnecessary repaints when 0 zoom is the actual
  // template intent.
  if (
    !zoomKeyframes ||
    zoomKeyframes.length === 0 ||
    (zoomKeyframes.length === 1 && Math.abs(zoomKeyframes[0].scale - 1) < 0.01)
  ) {
    return <>{children}</>;
  }

  // Sort by relative_time defensively — pipeline stitches per-scene curves
  // and could produce slightly out-of-order entries at slot boundaries.
  const sorted = [...zoomKeyframes].sort((a, b) => a.relative_time - b.relative_time);
  const inputRange = sorted.map((kf) =>
    Math.max(0, Math.min(segmentDurationInFrames, kf.relative_time * segmentDurationInFrames)),
  );
  const outputRange = sorted.map((kf) => kf.scale);

  // interpolate needs at least 2 points to do useful work; duplicate when
  // only one keyframe was given.
  const xs = inputRange.length === 1 ? [inputRange[0], inputRange[0] + 1] : inputRange;
  const ys = outputRange.length === 1 ? [outputRange[0], outputRange[0]] : outputRange;

  const scale = interpolate(frame, xs, ys, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        transform: `scale(${scale})`,
        transformOrigin: "50% 50%",
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
