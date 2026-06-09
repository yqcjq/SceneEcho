import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * Phase 1B · dual-mode caption renderer (PLAN 1542).
 *
 * - ``renderMode="template_preview"``: render the first placeholder_text
 *   as illustrative caption text (TemplateLibrary detail page, Phase 0.5
 *   dev_workbench preview). The IR's CaptionStyle came from VLM
 *   identification, but no real text exists yet — placeholder_text is
 *   the VLM-supplied "this slot expects a 4-6 char CTA" hint.
 * - ``renderMode="project_output"``: render the ProjectIR's
 *   ``Caption.text`` (sourced from the user's recorded audio Unit.text).
 *
 * Mode is passed explicitly by the caller (Project.tsx). The renderer
 * never auto-detects mode by inspecting ``text`` for emptiness — that's
 * the kind of implicit fallback that bites later when a legitimately
 * empty user caption silently switches modes.
 */
export type CaptionRenderMode = "template_preview" | "project_output";

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
  layout?: string;
  maxCharsPerLine?: number;
  /** Phase 1B placeholder-aware preview text (first element). */
  placeholderText?: string[];
  renderMode?: CaptionRenderMode;
}

const wrapByCharLimit = (text: string, maxChars: number): string => {
  if (maxChars <= 0 || text.length <= maxChars) return text;
  const lines: string[] = [];
  for (let i = 0; i < text.length; i += maxChars) {
    lines.push(text.slice(i, i + maxChars));
  }
  return lines.join("\n");
};

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
  layout = "single",
  maxCharsPerLine = 12,
  placeholderText = [],
  renderMode = "project_output",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tSec = frame / fps;
  if (tSec < startSec || tSec > endSec) return null;

  // Mode selection: template_preview replaces text with placeholder_text[0]
  // when available, otherwise falls through to whatever text was passed
  // (typically "" — preview pages should pass placeholder explicitly).
  const renderedText =
    renderMode === "template_preview" && placeholderText.length > 0
      ? placeholderText[0]
      : text;

  const fadeFrames = Math.max(1, Math.round(0.3 * fps));
  const startFrame = startSec * fps;
  const endFrame = endSec * fps;

  // PLAN 1546: anim_in 全套 — fade / slide / typewriter / stagger.
  // Each animation is implemented as an opacity + transform pair; the
  // chosen branch is the IR's ``style.anim_in`` string.
  let opacity = 1;
  let translateY = 0;
  if (animIn === "fade") {
    opacity = interpolate(
      frame,
      [startFrame, startFrame + fadeFrames, endFrame - fadeFrames, endFrame],
      [0, 1, 1, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );
  } else if (animIn === "整句滑入" || animIn === "slide") {
    opacity = interpolate(
      frame,
      [startFrame, startFrame + fadeFrames],
      [0, 1],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );
    translateY = interpolate(
      frame,
      [startFrame, startFrame + fadeFrames],
      [40, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );
  } else if (animIn === "淡入") {
    opacity = interpolate(
      frame,
      [startFrame, startFrame + fadeFrames],
      [0, 1],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );
  } else if (animIn === "打字机" || animIn === "typewriter") {
    // Reveal one character every (1/fps)*charDuration; substring shrinks
    // until full string is displayed.
    const charsPerSec = Math.max(4, renderedText.length / Math.max(0.5, endSec - startSec - 0.3));
    const visible = Math.floor((tSec - startSec) * charsPerSec);
    return renderTypewriter(
      renderedText.slice(0, Math.max(1, visible)),
      position,
      { fontFamily, size, color, strokeColor, strokeWidth, layout, maxCharsPerLine },
    );
  } else if (animIn === "逐字弹入") {
    opacity = interpolate(frame, [startFrame, startFrame + fadeFrames], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  const [px, py] = position;
  const wrapped = layout === "multi"
    ? wrapByCharLimit(renderedText, maxCharsPerLine)
    : renderedText;
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
          transform: `translate(-50%, calc(-50% + ${translateY}px))`,
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
        {wrapped}
      </div>
    </AbsoluteFill>
  );
};

function renderTypewriter(
  visibleText: string,
  position: [number, number],
  styles: {
    fontFamily: string;
    size: number;
    color: string;
    strokeColor: string | null;
    strokeWidth: number;
    layout: string;
    maxCharsPerLine: number;
  },
) {
  const [px, py] = position;
  const wrapped =
    styles.layout === "multi"
      ? wrapByCharLimit(visibleText, styles.maxCharsPerLine)
      : visibleText;
  const textShadow =
    styles.strokeColor && styles.strokeWidth > 0
      ? `-${styles.strokeWidth}px -${styles.strokeWidth}px 0 ${styles.strokeColor},` +
        `${styles.strokeWidth}px -${styles.strokeWidth}px 0 ${styles.strokeColor},` +
        `-${styles.strokeWidth}px ${styles.strokeWidth}px 0 ${styles.strokeColor},` +
        `${styles.strokeWidth}px ${styles.strokeWidth}px 0 ${styles.strokeColor}`
      : undefined;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: `${px * 100}%`,
          top: `${py * 100}%`,
          transform: "translate(-50%, -50%)",
          fontFamily: styles.fontFamily,
          fontSize: styles.size,
          color: styles.color,
          fontWeight: 700,
          textAlign: "center",
          textShadow,
          whiteSpace: "pre-wrap",
          maxWidth: "90%",
        }}
      >
        {wrapped}
      </div>
    </AbsoluteFill>
  );
}
