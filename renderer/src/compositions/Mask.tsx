import React from "react";
import { AbsoluteFill } from "remotion";

/**
 * Phase 1B · geometric mask overlay (PLAN 1548).
 *
 * Goal: dim the area *outside* the kept region so the masked region pops.
 * Implementation: SVG ``<mask>`` element with white background + black
 * shape — when applied to a full-canvas semi-transparent black rect, the
 * white (=outside) area renders opaque (dimming) and the black (=kept)
 * area renders transparent (untouched).
 *
 * The prior implementation used ``clipPath`` with evenodd fill-rule,
 * which produced the inverse effect (only the kept region was dimmed).
 * SVG masks are the canonical primitive for "subtract a shape from an
 * overlay"; clipPath strictly intersects, which can't express inversion
 * without a second clipPath wrapping the whole canvas.
 */
export interface MaskParams {
  kind: "circle" | "rectangle" | "line_split";
  params: Record<string, number | string>;
}

export interface MaskProps {
  mask: MaskParams;
  canvasWidth: number;
  canvasHeight: number;
  /** 0..1 dim opacity for the masked-out area. Default 0.4. */
  dim?: number;
}

export const Mask: React.FC<MaskProps> = ({
  mask,
  canvasWidth,
  canvasHeight,
  dim = 0.4,
}) => {
  // 0-999 → canvas px. Mask geometry uses normalized 0-999 across both
  // axes for cx/cy/x/y and across min(w,h) for radius (extract/masks.py).
  const normX = (v: number) => (v / 1000) * canvasWidth;
  const normY = (v: number) => (v / 1000) * canvasHeight;
  const normMin = (v: number) => (v / 1000) * Math.min(canvasWidth, canvasHeight);

  // Stable mask id per render. Using a deterministic value derived from
  // kind is fine because at most one Mask renders per Project — the
  // Mask layer is global, not per-segment in Phase 1B.
  const maskId = `se-mask-${mask.kind}`;

  // Build the "keep" shape (black on the SVG mask = transparent in the overlay).
  let keepShape: React.ReactNode = null;
  if (mask.kind === "circle") {
    keepShape = (
      <circle
        cx={normX(Number(mask.params.cx ?? 500))}
        cy={normY(Number(mask.params.cy ?? 500))}
        r={normMin(Number(mask.params.radius ?? 200))}
        fill="black"
      />
    );
  } else if (mask.kind === "rectangle") {
    keepShape = (
      <rect
        x={normX(Number(mask.params.x ?? 0))}
        y={normY(Number(mask.params.y ?? 0))}
        width={normX(Number(mask.params.w ?? 500))}
        height={normY(Number(mask.params.h ?? 500))}
        fill="black"
      />
    );
  } else if (mask.kind === "line_split") {
    const side = String(mask.params.side_kept ?? "top");
    const lineY =
      (normY(Number(mask.params.y1 ?? 500)) + normY(Number(mask.params.y2 ?? 500))) / 2;
    const lineX =
      (normX(Number(mask.params.x1 ?? 500)) + normX(Number(mask.params.x2 ?? 500))) / 2;
    let points = "";
    if (side === "top") points = `0,0 ${canvasWidth},0 ${canvasWidth},${lineY} 0,${lineY}`;
    else if (side === "bottom")
      points = `0,${lineY} ${canvasWidth},${lineY} ${canvasWidth},${canvasHeight} 0,${canvasHeight}`;
    else if (side === "left")
      points = `0,0 ${lineX},0 ${lineX},${canvasHeight} 0,${canvasHeight}`;
    else points = `${lineX},0 ${canvasWidth},0 ${canvasWidth},${canvasHeight} ${lineX},${canvasHeight}`;
    keepShape = <polygon points={points} fill="black" />;
  }

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <svg
        viewBox={`0 0 ${canvasWidth} ${canvasHeight}`}
        width="100%"
        height="100%"
        preserveAspectRatio="none"
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse">
            {/* White = opaque overlay; black shape = transparent (kept). */}
            <rect x={0} y={0} width={canvasWidth} height={canvasHeight} fill="white" />
            {keepShape}
          </mask>
        </defs>
        <rect
          x={0}
          y={0}
          width={canvasWidth}
          height={canvasHeight}
          fill={`rgba(0,0,0,${dim})`}
          mask={`url(#${maskId})`}
        />
      </svg>
    </AbsoluteFill>
  );
};
