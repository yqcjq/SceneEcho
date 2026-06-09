import React from "react";
import { Img, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * Phase 2 · sticker overlay (PLAN 1630).
 *
 * - ``generated_image`` set → render the image at the sticker's normalized
 *   position + size during ``[start, end]``.
 * - ``generated_image`` unset (the MVP default until Phase 5 AIGC kicks in)
 *   → render a *placeholder block*: dashed border + ``description`` text +
 *   a "Phase 5 替换" badge so the user immediately understands "this is a
 *   slot the template expects a sticker, but no image yet".
 *
 * The placeholder style intentionally screams "work in progress" rather
 * than trying to look like a real sticker — silent fallback would mislead
 * users into thinking the template's sticker palette is already in place.
 */
export interface StickerProps {
  /** Sticker description (≤30 chars). Used as placeholder text + alt. */
  description: string;
  /** Normalized [x, y] center, 0..1. */
  position: [number, number];
  /** Normalized [w, h] size, 0..1. */
  size: [number, number];
  /** Seconds the sticker is on screen (segment-local). */
  startSec: number;
  endSec: number;
  /** When non-null, renders an <Img> from this DATA_ROOT-relative URL. */
  generatedImage?: string | null;
  /** Optional semantic_category tag — surfaces on the placeholder. */
  semanticCategory?: string | null;
}

export const Sticker: React.FC<StickerProps> = ({
  description,
  position,
  size,
  startSec,
  endSec,
  generatedImage,
  semanticCategory,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  if (t < startSec || t > endSec) return null;

  const [cx, cy] = position;
  const [w, h] = size;
  const wrapperStyle: React.CSSProperties = {
    position: "absolute",
    left: `${(cx - w / 2) * 100}%`,
    top: `${(cy - h / 2) * 100}%`,
    width: `${w * 100}%`,
    height: `${h * 100}%`,
    pointerEvents: "none",
  };

  if (generatedImage) {
    return (
      <div style={wrapperStyle}>
        <Img
          src={generatedImage}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </div>
    );
  }

  // Placeholder mode — "this slot wants a sticker, Phase 5 will fill it"
  return (
    <div
      style={{
        ...wrapperStyle,
        border: "2px dashed rgba(204, 120, 92, 0.85)", // accent-primary 半透
        background: "rgba(245, 229, 221, 0.45)", // accent-subtle 半透
        borderRadius: 6,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 6,
        fontFamily: "system-ui, sans-serif",
        color: "#1F1E1C",
        textAlign: "center",
      }}
    >
      <span style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.2 }}>
        {description || "贴纸占位"}
      </span>
      {semanticCategory ? (
        <span style={{ fontSize: 11, color: "#6B6962", marginTop: 2 }}>
          {semanticCategory}
        </span>
      ) : null}
      <span
        style={{
          fontSize: 10,
          color: "#FAF9F7",
          background: "#CC785C",
          padding: "1px 6px",
          borderRadius: 999,
          marginTop: 4,
          letterSpacing: 0.5,
        }}
      >
        Phase 5 替换
      </span>
    </div>
  );
};
