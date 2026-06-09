// Phase 2 · preflight resource check (PLAN 1633).
//
// Before rendering we walk the ProjectIR and verify every external file the
// composition is about to fetch actually exists. Failing here is far
// cheaper than failing mid-render: Chromium would silently substitute the
// missing resource with a 404 frame and the user gets half a video.
//
// Checks (paths are DATA_ROOT-relative inside ProjectIR; we resolve them
// via ``resolveDataPath``):
//  - ``projectIR.user_material``     (mandatory)
//  - ``projectIR.bgm_track``         (optional)
//  - Each ``sticker.generated_image`` whose value is non-null
//
// Missing fonts / system LUTs are *not* checked here — fonts are bundled
// system installs and the LUT is a CSS filter name (no file). Add new
// resource categories to ``collectResourceRefs`` as we grow the renderer.

import { existsSync } from "node:fs";
import { resolveDataPath } from "./paths.js";

export interface MissingResource {
  category: "user_material" | "bgm_track" | "sticker_image";
  path: string;
  absolutePath: string;
  hint: string;
}

export interface PreflightResult {
  ok: boolean;
  missing: MissingResource[];
}

function collectResourceRefs(projectIR: any): Array<{
  category: MissingResource["category"];
  path: string | null | undefined;
  hint: string;
}> {
  const refs: ReturnType<typeof collectResourceRefs> = [];
  refs.push({
    category: "user_material",
    path: projectIR?.user_material,
    hint: "上传归一化后的 normalized.mp4 缺失；apply 流水线应已写入此字段。",
  });
  if (projectIR?.bgm_track) {
    refs.push({
      category: "bgm_track",
      path: projectIR.bgm_track,
      hint:
        "BGM 选定但磁盘上的文件缺失；检查 data/system/bgm_pool/ 或 apply 流水线的 BGM 路径。",
    });
  }
  for (const sec of projectIR?.sections ?? []) {
    for (const seg of sec.segments ?? []) {
      for (const stk of seg.applied_style?.stickers ?? []) {
        if (stk?.generated_image) {
          refs.push({
            category: "sticker_image",
            path: stk.generated_image,
            hint: `贴纸生成图缺失（${stk.description ?? "?"}）；Phase 5 AIGC 应已写入此路径。`,
          });
        }
      }
    }
  }
  return refs;
}

export function preflight(projectIR: any): PreflightResult {
  const missing: MissingResource[] = [];
  for (const ref of collectResourceRefs(projectIR)) {
    if (!ref.path) continue;
    const abs = resolveDataPath(ref.path);
    if (!existsSync(abs)) {
      missing.push({
        category: ref.category,
        path: ref.path,
        absolutePath: abs,
        hint: ref.hint,
      });
    }
  }
  return { ok: missing.length === 0, missing };
}

export class PreflightError extends Error {
  missing: MissingResource[];
  constructor(missing: MissingResource[]) {
    super(
      `preflight: ${missing.length} resource(s) missing:\n` +
        missing
          .map((m) => `  - [${m.category}] ${m.path}  (abs: ${m.absolutePath})  // ${m.hint}`)
          .join("\n"),
    );
    this.name = "PreflightError";
    this.missing = missing;
  }
}
