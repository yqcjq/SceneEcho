import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

export interface CaptionProps {
  text: string;
  startSec: number;
  endSec: number;
  fontFamily?: string;
  size?: number;
  color?: string;
  strokeColor?: string | null;
  strokeWidth?: number;
  position?: [number, number];
  animIn?: string;
}

export const Caption: React.FC<CaptionProps> = ({
  text,
  startSec,
  endSec,
  fontFamily = "sans-serif",
  size = 56,
  color = "#FFFFFF",
  strokeColor = "#000000",
  strokeWidth = 2,
  position = [0.5, 0.85],
  animIn = "fade",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tSec = frame / fps;
  if (tSec < startSec || tSec > endSec) return null;

  const fadeFrames = Math.max(1, Math.round(0.3 * fps));
  const startFrame = startSec * fps;
  const endFrame = endSec * fps;
  const opacity =
    animIn === "fade"
      ? interpolate(
          frame,
          [startFrame, startFrame + fadeFrames, endFrame - fadeFrames, endFrame],
          [0, 1, 1, 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        )
      : 1;

  const [px, py] = position;
  const textShadow =
    strokeColor && strokeWidth > 0
      ? `-${strokeWidth}px -${strokeWidth}px 0 ${strokeColor},` +
        `${strokeWidth}px -${strokeWidth}px 0 ${strokeColor},` +
        `-${strokeWidth}px ${strokeWidth}px 0 ${strokeColor},` +
        `${strokeWidth}px ${strokeWidth}px 0 ${strokeColor}`
      : undefined;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: `${px * 100}%`,
          top: `${py * 100}%`,
          transform: "translate(-50%, -50%)",
          fontFamily,
          fontSize: size,
          color,
          fontWeight: 700,
          textAlign: "center",
          textShadow,
          opacity,
          whiteSpace: "pre-wrap",
          maxWidth: "90%",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
