import React from "react";

/**
 * Overlay one or more bboxes onto a video frame.
 *
 * Coordinates arrive in the 0–999 normalized system (PLAN.md "0-999 归一化坐标系").
 * The conversion is `pixel = coord / 1000 * frameSize` — handled inside this
 * component so callers only ever speak normalized space.
 */
export interface BboxOverlayProps {
  /** Natural pixel size of the underlying frame. */
  frameWidth: number;
  frameHeight: number;
  /** [x, y, w, h] in 0–999 space. */
  bbox: [number, number, number, number];
  label?: string;
  /** Optional secondary stroke (used for "alternate proposal" cross-check). */
  variant?: "primary" | "secondary";
}

const DIVISOR = 1000;

export function bboxToRect(
  bbox: [number, number, number, number],
  frameWidth: number,
  frameHeight: number,
): { x: number; y: number; width: number; height: number } {
  return {
    x: (bbox[0] / DIVISOR) * frameWidth,
    y: (bbox[1] / DIVISOR) * frameHeight,
    width: (bbox[2] / DIVISOR) * frameWidth,
    height: (bbox[3] / DIVISOR) * frameHeight,
  };
}

export const BboxOverlay: React.FC<BboxOverlayProps> = ({
  frameWidth,
  frameHeight,
  bbox,
  label,
  variant = "primary",
}) => {
  const rect = bboxToRect(bbox, frameWidth, frameHeight);
  const stroke =
    variant === "primary" ? "var(--accent-primary)" : "var(--color-warning)";

  return (
    <svg
      data-testid="bbox-overlay"
      viewBox={`0 0 ${frameWidth} ${frameHeight}`}
      preserveAspectRatio="xMidYMid meet"
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      <rect
        x={rect.x}
        y={rect.y}
        width={rect.width}
        height={rect.height}
        className="se-bbox"
        stroke={stroke}
        data-rect-x={rect.x}
        data-rect-y={rect.y}
        data-rect-width={rect.width}
        data-rect-height={rect.height}
      />
      {label ? (
        <g>
          <rect
            x={rect.x}
            y={Math.max(0, rect.y - 28)}
            rx={4}
            width={Math.min(label.length * 9 + 16, frameWidth - rect.x)}
            height={22}
            fill="var(--accent-subtle)"
          />
          <text
            x={rect.x + 8}
            y={Math.max(16, rect.y - 12)}
            fontFamily="var(--font-sans)"
            fontSize={13}
            fill="var(--accent-primary)"
          >
            {label}
          </text>
        </g>
      ) : null}
    </svg>
  );
};
