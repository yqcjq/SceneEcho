import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence } from "remotion";
import { Caption } from "./Caption";

export interface ProjectIRProps {
  // Loose typing on the composition boundary; zod has already validated at /render.
  projectIR: any;
  // Absolute file:// or http(s) URL to the user material, resolved by the server.
  userMaterialUrl: string;
}

export const Project: React.FC<ProjectIRProps> = ({ projectIR, userMaterialUrl }) => {
  const sections = projectIR?.sections ?? [];
  const captions = projectIR?.captions ?? [];

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {sections.map((section: any, si: number) =>
        (section.segments ?? []).map((seg: any, gi: number) => {
          const [srcStart, srcEnd] = seg.src_timerange ?? [0, 0];
          const durSec = Math.max(0.04, srcEnd - srcStart);
          const fps = projectIR?.canvas?.fps ?? 30;
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

      {captions.map((cap: any, ci: number) => (
        <Caption
          key={`cap-${ci}`}
          text={cap.text}
          startSec={cap.start}
          endSec={cap.end}
          fontFamily={cap.style?.font_family}
          size={cap.style?.size}
          color={cap.style?.color}
          strokeColor={cap.style?.stroke_color}
          strokeWidth={cap.style?.stroke_width}
          position={cap.style?.position}
          animIn={cap.style?.anim_in}
        />
      ))}
    </AbsoluteFill>
  );
};
