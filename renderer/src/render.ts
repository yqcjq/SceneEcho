import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

import { projectMeta } from "./compositions/projectMeta.js";
import { withTask } from "./logger.js";
import { dataRoot, rendererSrcDir, resolveDataPath } from "./paths.js";
import { PreflightError, preflight } from "./preflight.js";
import { reportProgress } from "./progress.js";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:18521";

let cachedBundleUrl: string | null = null;

async function getBundleUrl(): Promise<string> {
  if (cachedBundleUrl) return cachedBundleUrl;
  const entry = resolve(rendererSrcDir(), "remotion.root.tsx");
  cachedBundleUrl = await bundle({ entryPoint: entry });
  return cachedBundleUrl;
}

export interface RenderResult {
  output_path: string; // POSIX-style, relative to DATA_ROOT
  absolute_path: string;
  duration_sec: number;
}

function publicDataUrl(rel: string): string {
  const cleaned = String(rel).replace(/\\/g, "/").replace(/^\/+/, "");
  return `${BACKEND_URL}/data/${cleaned.split("/").map(encodeURIComponent).join("/")}`;
}

export async function renderProjectIR(
  projectIR: any,
  taskId: string,
): Promise<RenderResult> {
  const log = withTask(taskId);
  const meta = projectMeta(projectIR);

  // Preflight: every external resource referenced in the IR must exist.
  // Failing fast here beats Chromium silently substituting a 404 frame.
  const pf = preflight(projectIR);
  if (!pf.ok) {
    log.error({ missing: pf.missing }, "preflight_failed");
    throw new PreflightError(pf.missing);
  }

  // Remotion 4.x only fetches http(s) assets, so serve user material via the
  // backend's /data static mount instead of a file:// URL.
  const userMaterialAbs = resolveDataPath(projectIR.user_material);
  const userMaterialUrl = publicDataUrl(projectIR.user_material);
  const bgmUrl: string | null = projectIR.bgm_track
    ? publicDataUrl(projectIR.bgm_track)
    : null;

  log.info({ meta, userMaterialAbs, userMaterialUrl, bgmUrl }, "render_start");
  await reportProgress(taskId, 0.1, "bundling");

  const bundleUrl = await getBundleUrl();
  await reportProgress(taskId, 0.3, "selecting");

  const inputProps = { projectIR, userMaterialUrl, bgmUrl };
  // calculateMetadata in Root.tsx handles width/height/fps/duration.
  const composition = await selectComposition({
    serveUrl: bundleUrl,
    id: "Project",
    inputProps,
  });

  const projectId: string = projectIR.project_id ?? "demo";
  const outRel = `projects/${projectId}/outputs/render_${Date.now()}.mp4`;
  const outAbs = resolve(dataRoot(), outRel);
  mkdirSync(dirname(outAbs), { recursive: true });

  await reportProgress(taskId, 0.4, "rendering");
  await renderMedia({
    composition,
    serveUrl: bundleUrl,
    codec: "h264",
    outputLocation: outAbs,
    inputProps,
    onProgress: ({ progress }) => {
      const overall = 0.4 + Math.min(1, Math.max(0, progress)) * 0.55;
      void reportProgress(taskId, overall, "rendering");
    },
    chromiumOptions: { headless: true },
  });

  await reportProgress(taskId, 0.97, "finalizing");
  log.info({ outAbs }, "render_done");

  return {
    output_path: outRel,
    absolute_path: outAbs,
    duration_sec: meta.durationSec,
  };
}
