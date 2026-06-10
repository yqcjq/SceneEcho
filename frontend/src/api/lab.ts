import axios from "axios";

export interface SubcapDef {
  name: string;
  label: string;
  stage: string;
  baseline_key: string;
}

export interface LabSample {
  id: string;
  has_normalized: boolean;
  has_source: boolean;
  thumbnail_url: string | null;
}

export interface RunSubcapResponse {
  task_id: string;
  subcap: string;
  fixture_id: string;
  workbench_url: string;
  dry_run: boolean;
}

export interface RunSubcapOptions {
  dry_run?: boolean;
  /** Wipe ``data/samples/{fixture}/extracted/`` (frame jpgs + jsonl) before running. */
  force_refresh?: boolean;
}

export async function listSubcaps(): Promise<SubcapDef[]> {
  const { data } = await axios.get<{ subcaps: SubcapDef[] }>(
    "/api/lab/subcaps",
  );
  return data.subcaps;
}

/** List every directory under ``data/samples/`` runnable by the lab.
 *
 * Replaces the old per-subcap ``fixtures: string[]`` allowlist. Every
 * subcap can run against every returned sample (decisions/010 P7). */
export async function listLabSamples(): Promise<LabSample[]> {
  const { data } = await axios.get<{ samples: LabSample[] }>(
    "/api/lab/samples",
  );
  return data.samples;
}

export async function runSubcap(
  name: string,
  fixture_id: string,
  opts: RunSubcapOptions = {},
): Promise<RunSubcapResponse> {
  const { data } = await axios.post<RunSubcapResponse>(
    `/api/lab/run-subcap/${encodeURIComponent(name)}`,
    {
      fixture_id,
      dry_run: opts.dry_run ?? false,
      force_refresh: opts.force_refresh ?? false,
    },
  );
  return data;
}

export async function getBaseline(
  name: string,
): Promise<unknown> {
  const { data } = await axios.get<{ baseline: unknown }>(
    `/api/lab/baselines/${encodeURIComponent(name)}`,
  );
  return data.baseline;
}
