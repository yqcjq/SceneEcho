import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * Phase 1B · dual-mode caption renderer (PLAN 1542).
 *
 * - ``renderMode="template_preview"``: render the first ``style.placeholder_text``
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
 *
 * The component takes the entire ``CaptionStyle`` object as a single
 * prop (decisions/010 P5). Adding visual fields to the IR (shadow /
 * background / padding / text_align / letter_spacing / line_height /
 * bbox_norm) needs zero prop-signature changes — IR is the contract.
 */
export type CaptionRenderMode = "template_preview" | "project_output";

/** Shape of TemplateIR/CaptionStyle as far as the renderer cares. Mirrors
 * ``backend/app/ir/template.py::CaptionStyle`` — keep in sync, but zod
 * validation at /render is the actual guarantor. */
export interface CaptionStyleShape {
  font_family?: string;
  size?: number;
  color?: string;
  stroke_color?: string | null;
  stroke_width?: number;
  shadow_color?: string | null;
  shadow_offset?: [number, number];
  shadow_blur?: number;
  background_color?: string | null;
  padding?: [number, number, number, number];
  text_align?: string;
  letter_spacing?: number;
  line_height?: number;
  position?: [number, number];
  bbox_norm?: [number, number, number, number];
  layout?: string;
  max_chars_per_line?: number;
  anim_in?: string;
  anim_emphasis?: string | null;
  emphasis_words?: string[];
  placeholder_text?: string[];
}

export interface CaptionProps {
  text: string;
  startSec: number;
  endSec: number;
  style: CaptionStyleShape;
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

/** Compose a CSS text-shadow from stroke (4-corner outline) + drop shadow. */
function buildTextShadow(
  strokeColor: string | null | undefined,
  strokeWidth: number,
  shadowColor: string | null | undefined,
  shadowOffset: [number, number],
  shadowBlur: number,
): string | undefined {
  const parts: string[] = [];
  if (strokeColor && strokeWidth > 0) {
    parts.push(
      `-${strokeWidth}px -${strokeWidth}px 0 ${strokeColor}`,
      `${strokeWidth}px -${strokeWidth}px 0 ${strokeColor}`,
      `-${strokeWidth}px ${strokeWidth}px 0 ${strokeColor}`,
      `${strokeWidth}px ${strokeWidth}px 0 ${strokeColor}`,
    );
  }
  if (shadowColor && (shadowOffset[0] !== 0 || shadowOffset[1] !== 0 || shadowBlur > 0)) {
    parts.push(`${shadowOffset[0]}px ${shadowOffset[1]}px ${shadowBlur}px ${shadowColor}`);
  }
  return parts.length ? parts.join(",") : undefined;
}

/** When ``bbox_norm`` is non-zero (in 0-999 coords), use it as the anchor —
 * left/top in CSS percent + width clamps the text region. ``position`` (0–1
 * normalized center) is the legacy fallback. */
function bboxIsValid(bbox?: [number, number, number, number]): bbox is [number, number, number, number] {
  if (!bbox) return false;
  const [, , w, h] = bbox;
  return w > 0 && h > 0;
}

interface PlacementCss {
  left: string;
  top: string;
  transform: string;
  maxWidth: string;
  textAlign: "left" | "center" | "right";
}

function placementFromStyle(
  style: CaptionStyleShape,
  translateY: number,
): PlacementCss {
  const align = (style.text_align as PlacementCss["textAlign"]) || "center";
  if (bboxIsValid(style.bbox_norm)) {
    const [x, y, w, h] = style.bbox_norm;
    const leftPct = (x / 999) * 100;
    const topPct = (y / 999) * 100;
    const widthPct = (w / 999) * 100;
    const heightPct = (h / 999) * 100;
    return {
      left: `${leftPct}%`,
      top: `calc(${topPct}% + ${heightPct / 2}% + ${translateY}px)`,
      transform: "translateY(-50%)",
      maxWidth: `${widthPct}%`,
      textAlign: align,
    };
  }
  const [px, py] = style.position ?? [0.5, 0.85];
  return {
    left: `${px * 100}%`,
    top: `${py * 100}%`,
    transform: `translate(-50%, calc(-50% + ${translateY}px))`,
    maxWidth: "90%",
    textAlign: align,
  };
}

/**
 * Phase 2 · emphasis-aware text splitter.
 *
 * Walks ``text`` and splits it into ``<span>`` fragments. Substrings that
 * match any entry in ``emphasisWords`` get an emphasis-styled span (bigger
 * size + accent color + optional shake). The split is greedy left-to-right;
 * overlapping emphasis substrings prefer the longer match.
 *
 * When ``emphasisWords`` is empty we return a single string fragment so
 * React doesn't allocate an array. This matches the Phase 1B behaviour
 * (no emphasis support) byte-for-byte.
 */
function renderWithEmphasis(
  text: string,
  emphasisWords: string[],
  animEmphasis: string | null | undefined,
  frame: number,
  fps: number,
  startFrame: number,
): React.ReactNode {
  if (!emphasisWords || emphasisWords.length === 0) return text;
  const sorted = [...emphasisWords].sort((a, b) => b.length - a.length);
  const fragments: React.ReactNode[] = [];
  let i = 0;
  while (i < text.length) {
    let matched = false;
    for (const ew of sorted) {
      if (!ew) continue;
      if (text.startsWith(ew, i)) {
        // Drive shake / scale animation by frame so the renderer remains
        // deterministic (no Date.now() etc — Remotion requirement).
        const t = (frame - startFrame) / Math.max(1, fps);
        let transform = "";
        if (animEmphasis === "抖动" || animEmphasis === "shake") {
          const dx = Math.sin(t * 20) * 3;
          transform = `translateX(${dx}px)`;
        } else if (animEmphasis === "放大" || animEmphasis === "scale") {
          const s = 1.0 + Math.max(0, Math.sin(t * 8)) * 0.18;
          transform = `scale(${s})`;
        }
        fragments.push(
          <span
            key={`em-${i}`}
            style={{
              color: "#CC785C", // accent-primary
              display: "inline-block",
              transform: transform || undefined,
              transformOrigin: "50% 50%",
              fontWeight: 900,
            }}
          >
            {ew}
          </span>,
        );
        i += ew.length;
        matched = true;
        break;
      }
    }
    if (matched) continue;
    // Group consecutive non-emphasis characters into one text fragment so
    // we don't emit one span per character.
    const startSlice = i;
    while (i < text.length) {
      const hits = sorted.some((ew) => ew && text.startsWith(ew, i));
      if (hits) break;
      i++;
    }
    fragments.push(text.slice(startSlice, i));
  }
  return fragments;
}

export const Caption: React.FC<CaptionProps> = ({
  text,
  startSec,
  endSec,
  style,
  renderMode = "project_output",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tSec = frame / fps;
  if (tSec < startSec || tSec > endSec) return null;

  const placeholderText = style.placeholder_text ?? [];

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
  const animIn = style.anim_in ?? "fade";

  // PLAN 1546: anim_in 全套 — fade / slide / typewriter / stagger.
  // Each animation tweaks two things: (a) what fraction of ``renderedText``
  // is currently visible (typewriter substring) and (b) the (opacity,
  // translateY) pair driving the wrapping div. All other style — placement
  // / shadow / padding / background — is shared across animations so we
  // never grow a second render path.
  let displayText = renderedText;
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
    // Reveal one character per (1/fps)*charsPerSec; substring grows over
    // time. Opacity stays 1 — the "not yet revealed" characters are
    // expressed by being absent, not faded.
    const charsPerSec = Math.max(4, renderedText.length / Math.max(0.5, endSec - startSec - 0.3));
    const visible = Math.floor((tSec - startSec) * charsPerSec);
    displayText = renderedText.slice(0, Math.max(1, visible));
  } else if (animIn === "逐字弹入") {
    opacity = interpolate(frame, [startFrame, startFrame + fadeFrames], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  const layout = style.layout ?? "single";
  const maxCharsPerLine = style.max_chars_per_line ?? 12;
  const wrapped = layout === "multi"
    ? wrapByCharLimit(displayText, maxCharsPerLine)
    : displayText;

  const textShadow = buildTextShadow(
    style.stroke_color,
    style.stroke_width ?? 2,
    style.shadow_color,
    style.shadow_offset ?? [0, 0],
    style.shadow_blur ?? 0,
  );

  const renderedFragments = renderWithEmphasis(
    wrapped,
    style.emphasis_words ?? [],
    style.anim_emphasis ?? null,
    frame,
    fps,
    startFrame,
  );

  const placement = placementFromStyle(style, translateY);
  const padding = style.padding ?? [0, 0, 0, 0];
  const paddingCss = `${padding[0]}px ${padding[1]}px ${padding[2]}px ${padding[3]}px`;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: placement.left,
          top: placement.top,
          transform: placement.transform,
          maxWidth: placement.maxWidth,
          fontFamily: style.font_family ?? "sans-serif",
          fontSize: style.size ?? 56,
          color: style.color ?? "#FFFFFF",
          fontWeight: 700,
          textAlign: placement.textAlign,
          letterSpacing: `${style.letter_spacing ?? 0}px`,
          lineHeight: style.line_height ?? 1.2,
          padding: paddingCss,
          background: style.background_color ?? undefined,
          borderRadius: style.background_color ? 4 : undefined,
          textShadow,
          opacity,
          whiteSpace: "pre-wrap",
        }}
      >
        {renderedFragments}
      </div>
    </AbsoluteFill>
  );
};
