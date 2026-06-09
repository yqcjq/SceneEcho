import React from "react";
import { AbsoluteFill } from "remotion";

/**
 * Phase 1B · color LUT layer (PLAN 1549).
 *
 * Applies a CSS filter chain derived from the template's
 * ``dominant_lut_id``. We don't ship real 3D LUT files in Phase 1B —
 * the VLM-classified semantic tag maps to a small preset table.
 *
 * The mapping below covers the categories the 1A color_lut prompt is
 * configured to emit. Unknown ids → no filter (identity). Extending to
 * real CUBE LUTs is Phase 4+.
 */
export interface ColorLayerProps {
  lutId: string | null | undefined;
  children?: React.ReactNode;
}

const PRESETS: Record<string, string> = {
  // semantic tag → CSS filter chain
  warm: "hue-rotate(-10deg) saturate(1.10) brightness(1.02)",
  warm_01: "hue-rotate(-15deg) saturate(1.15) brightness(1.05)",
  cool: "hue-rotate(15deg) saturate(0.90) brightness(0.98)",
  cool_01: "hue-rotate(20deg) saturate(0.85) brightness(0.95)",
  cinematic: "contrast(1.15) saturate(0.85) brightness(0.92)",
  high_saturation: "saturate(1.30)",
  low_saturation: "saturate(0.65)",
  flat: "contrast(0.95) saturate(0.90)",
};

export const ColorLayer: React.FC<ColorLayerProps> = ({ lutId, children }) => {
  // Identity filter when lutId is unknown — children render untouched.
  const filter = lutId && PRESETS[lutId] ? PRESETS[lutId] : "none";
  return (
    <AbsoluteFill style={{ filter }}>
      {children}
    </AbsoluteFill>
  );
};
