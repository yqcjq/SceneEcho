/**
 * shared/ir.schema.json -> frontend/src/types/ir.ts (zod schemas + inferred TS types).
 * Same strategy as renderer/scripts/gen-types.ts.
 */
import { jsonSchemaToZod } from "json-schema-to-zod";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..");
const SCHEMA = resolve(REPO_ROOT, "shared", "ir.schema.json");
const OUT = resolve(HERE, "..", "src", "types", "ir.ts");

const HEADER = `/* eslint-disable */
// GENERATED FILE — DO NOT EDIT.
// Source: shared/ir.schema.json
// Run \`pnpm gen:types\` from repo root to regenerate.

import { z } from "zod";
`;

function main(): void {
  const schema = JSON.parse(readFileSync(SCHEMA, "utf-8"));
  const defs: Record<string, unknown> = schema.$defs ?? {};
  const lines: string[] = [HEADER];

  for (const [name, def] of Object.entries(defs)) {
    const subSchema = { ...(def as object), $defs: defs };
    const expr = jsonSchemaToZod(subSchema, { module: "none" });
    lines.push(`export const ${name}Schema = ${expr};`);
    lines.push(`export type ${name} = z.infer<typeof ${name}Schema>;`);
    lines.push("");
  }

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, lines.join("\n"), "utf-8");
  console.log(`wrote ${OUT}`);
}

main();
