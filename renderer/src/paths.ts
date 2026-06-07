import { resolve, isAbsolute, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..");

export function dataRoot(): string {
  const raw = process.env.DATA_ROOT ?? "backend/data";
  return isAbsolute(raw) ? raw : resolve(REPO_ROOT, raw);
}

export function resolveDataPath(rel: string): string {
  if (isAbsolute(rel)) return rel;
  return resolve(dataRoot(), rel);
}

export function repoRoot(): string {
  return REPO_ROOT;
}

export function rendererSrcDir(): string {
  return HERE;
}
