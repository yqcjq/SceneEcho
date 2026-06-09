import React from "react";
import { Composition } from "remotion";
import { Project } from "./Project";
import { projectMeta } from "./projectMeta";

// Single source of truth for per-render metadata: derive width/height/fps/
// durationInFrames from inputProps.projectIR via calculateMetadata. The static
// defaults are fallbacks for Remotion Studio (dev only).
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Project"
        component={Project as any}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          projectIR: {
            sections: [],
            captions: [],
            canvas: { width: 1080, height: 1920, fps: 30 },
          },
          userMaterialUrl: "",
          bgmUrl: null,
        }}
        calculateMetadata={({ props }) => {
          const meta = projectMeta((props as any).projectIR);
          return {
            width: meta.width,
            height: meta.height,
            fps: meta.fps,
            durationInFrames: meta.durationInFrames,
          };
        }}
      />
    </>
  );
};
