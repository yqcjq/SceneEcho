import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence } from "remotion";
import { Caption } from "./Caption";
import { ColorLayer } from "./ColorLayer";
import { Mask } from "./Mask";

export interface ProjectIRProps {
  // Loose typing on the composition boundary; zod has already validated at /render.
  projectIR: any;
  // Absolute file:// or http(s) URL to the user material, resolved by the server.
  userMaterialUrl: string;
}

/**
 * Phase 1B composition order, bottom-up:
 *   <ColorLayer>            (color filter wraps the video stack)
 *     <Video sequences>
 *   </ColorLayer>
 *   <Mask>                  (geometric mask overlay, dims outside region)
 *   <Caption list>          (text on top, never filtered or masked)
 *
 * Color filter wraps only the video so captions stay legible. The mask
 * is sourced from the *first* slot's ``style.visual`` for Phase 1B
 * (Phase 2's multi-slot ProjectIR will move both into per-segment
 * <Sequence> children). ``mask`` (kind) and ``mask_params`` (geometry)
 * MUST both be set — skeleton.py writes them together; the renderer
 * refuses to draw the mask if either is missing.
 */
export const Project: React.FC<ProjectIRProps> = ({ projectIR, userMaterialUrl }) => {
  const sections = projectIR?.sections ?? [];
  const captions = projectIR?.captions ?? [];
  const canvas = projectIR?.canvas ?? { width: 1080, height: 1920, fps: 30 };

  const firstSlotStyle = sections[0]?.segments?.[0]?.applied_style ?? {};
  const lutId = firstSlotStyle?.visual?.color_lut ?? null;
  const maskKind = firstSlotStyle?.visual?.mask ?? null;
  const maskParams = firstSlotStyle?.visual?.mask_params ?? null;
  const renderMode = projectIR?.render_mode ?? "project_output";

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <ColorLayer lutId={lutId}>
        {sections.map((section: any, si: number) =>
          (section.segments ?? []).map((seg: any, gi: number) => {
            const [srcStart, srcEnd] = seg.src_timerange ?? [0, 0];
            const durSec = Math.max(0.04, srcEnd - srcStart);
            const fps = canvas.fps ?? 30;
            return (
              <Sequence
                key={`seg-${si}-${gi}`}
                from={Math.round((seg.timeline_start ?? 0) * fps)}
                durationInFrames={Math.round(durSec * fps)}
              >
                <OffthreadVideo
                  src={userMaterialUrl}
                  startFrom={Math.round(srcStart * fps)}
                  endAt={Math.round(srcEnd * fps)}
                  muted={false}
                />
              </Sequence>
            );
          }),
        )}
      </ColorLayer>

      {maskKind && maskParams ? (
        <Mask
          mask={{ kind: maskKind, params: maskParams }}
          canvasWidth={canvas.width ?? 1080}
          canvasHeight={canvas.height ?? 1920}
        />
      ) : null}

      {captions.map((cap: any, ci: number) => (
        <Caption
          key={`cap-${ci}`}
          text={cap.text ?? ""}
          startSec={cap.start}
          endSec={cap.end}
          fontFamily={cap.style?.font_family}
          size={cap.style?.size}
          color={cap.style?.color}
          strokeColor={cap.style?.stroke_color}
          strokeWidth={cap.style?.stroke_width}
          position={cap.style?.position}
          animIn={cap.style?.anim_in}
          layout={cap.style?.layout}
          maxCharsPerLine={cap.style?.max_chars_per_line}
          // placeholder_text lives ON the style now (1B IR change), not on
          // the Caption itself — every consumer (Phase 2 fill LLM included)
          // reads the same canonical field.
          placeholderText={cap.style?.placeholder_text ?? []}
          renderMode={renderMode}
        />
      ))}
    </AbsoluteFill>
  );
};
