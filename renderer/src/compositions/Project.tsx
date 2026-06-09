import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence } from "remotion";
import { Caption } from "./Caption";
import { ColorLayer } from "./ColorLayer";
import { Mask } from "./Mask";
import { Sticker } from "./Sticker";
import { ZoomLayer } from "./ZoomLayer";

export interface ProjectIRProps {
  // Loose typing on the composition boundary; zod has already validated at /render.
  projectIR: any;
  // Absolute file:// or http(s) URL to the user material, resolved by the server.
  userMaterialUrl: string;
  // Optional absolute URL to the pre-ducked BGM track. When unset, the
  // server-resolved fallback to projectIR.bgm_track (DATA_ROOT-relative)
  // is plumbed by render.ts before this composition runs.
  bgmUrl?: string | null;
}

/**
 * Phase 2 composition order (PLAN 1622-1633):
 *
 *   <ColorLayer global>                  // single color filter wraps all segments
 *     <Sequence segment 0>
 *       <ZoomLayer per-segment>
 *         <OffthreadVideo user material>
 *       </ZoomLayer>
 *       <Sticker list per-segment>
 *       <Mask per-segment (if any)>
 *     </Sequence>
 *     ... (one Sequence per PlacedSegment)
 *   </ColorLayer>
 *   <Caption list>                       // top-level captions overlay all
 *   <Audio bgm>                          // pre-ducked BGM (sidechain handled in backend)
 *
 * Phase 2 widens Phase 1B's "take segments[0]" assumption to a per-segment
 * mask / zoom / sticker layer. Captions stay at the top because they are
 * timeline-global in ProjectIR (one flat list, start/end in timeline
 * seconds — fill.py's gap captions + style.py's Unit captions merge here).
 *
 * Color filter intentionally stays *global*: per-segment color shifts on
 * 口播 footage feel jarring; the template's dominant_lut_id is a global
 * mood signal that applies across the project.
 */
export const Project: React.FC<ProjectIRProps> = ({
  projectIR,
  userMaterialUrl,
  bgmUrl,
}) => {
  const sections = projectIR?.sections ?? [];
  const captions = projectIR?.captions ?? [];
  const canvas = projectIR?.canvas ?? { width: 1080, height: 1920, fps: 30 };
  const fps = canvas.fps ?? 30;
  const renderMode = projectIR?.render_mode ?? "project_output";

  // Pick the first non-null color_lut across all segments for the global
  // color filter. Phase 2 doesn't switch palettes mid-timeline.
  let globalLut: string | null = null;
  for (const sec of sections) {
    for (const seg of sec.segments ?? []) {
      const lut = seg.applied_style?.visual?.color_lut;
      if (lut) {
        globalLut = lut;
        break;
      }
    }
    if (globalLut) break;
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <ColorLayer lutId={globalLut}>
        {sections.map((section: any, si: number) =>
          (section.segments ?? []).map((seg: any, gi: number) => {
            const [srcStart, srcEnd] = seg.src_timerange ?? [0, 0];
            const srcSpan = Math.max(0.04, srcEnd - srcStart);
            const speed = Math.max(0.04, Number(seg.speed ?? 1.0));
            const outputSpan = srcSpan / speed;
            const fromFrame = Math.round((seg.timeline_start ?? 0) * fps);
            const durationInFrames = Math.max(1, Math.round(outputSpan * fps));
            const zoomKfs = seg.applied_style?.visual?.zoom_keyframes ?? [];
            const stickers = seg.applied_style?.stickers ?? [];
            const maskKind = seg.applied_style?.visual?.mask ?? null;
            const maskParams = seg.applied_style?.visual?.mask_params ?? null;

            return (
              <Sequence
                key={`seg-${si}-${gi}`}
                from={fromFrame}
                durationInFrames={durationInFrames}
              >
                <ZoomLayer
                  zoomKeyframes={zoomKfs}
                  segmentDurationInFrames={durationInFrames}
                >
                  <OffthreadVideo
                    src={userMaterialUrl}
                    startFrom={Math.round(srcStart * fps)}
                    endAt={Math.round(srcEnd * fps)}
                    muted={false}
                    playbackRate={speed}
                  />
                </ZoomLayer>

                {maskKind && maskParams ? (
                  <Mask
                    mask={{ kind: maskKind, params: maskParams }}
                    canvasWidth={canvas.width ?? 1080}
                    canvasHeight={canvas.height ?? 1920}
                  />
                ) : null}

                {stickers.map((stk: any, sk: number) => (
                  <Sticker
                    key={`stk-${si}-${gi}-${sk}`}
                    description={stk.description ?? ""}
                    position={stk.position ?? [0.5, 0.5]}
                    size={stk.size ?? [0.2, 0.1]}
                    // Phase 2 IR contract: applied_style.stickers[*].start/end
                    // are segment-local seconds (apply/style.py mapped from
                    // slot-local [0,1] using the segment's output_span).
                    // Renderer reads them directly — no coordinate conversion.
                    startSec={stk.start ?? 0}
                    endSec={stk.end ?? outputSpan}
                    generatedImage={stk.generated_image ?? null}
                    semanticCategory={stk.semantic_category ?? null}
                  />
                ))}
              </Sequence>
            );
          }),
        )}
      </ColorLayer>

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
          emphasisWords={cap.style?.emphasis_words ?? []}
          animEmphasis={cap.style?.anim_emphasis ?? null}
          renderMode={renderMode}
        />
      ))}

      {bgmUrl ? <Audio src={bgmUrl} /> : null}
    </AbsoluteFill>
  );
};
