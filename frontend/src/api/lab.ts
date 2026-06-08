import axios from "axios";

export interface SubcapDef {
  name: string;
  label: string;
  stage: string;
  fixtures: string[];
  baseline_key: string;
}

export interface RunSubcapResponse {
  task_id: string;
  subcap: string;
  fixture_id: string;
  workbench_url: string;
  dry_run: boolean;
}

export async function listSubcaps(): Promise<SubcapDef[]> {
  const { data } = await axios.get<{ subcaps: SubcapDef[] }>(
    "/api/lab/subcaps",
  );
  return data.subcaps;
}

export async function runSubcap(
  name: string,
  fixture_id: string,
  dry_run = false,
): Promise<RunSubcapResponse> {
  const { data } = await axios.post<RunSubcapResponse>(
    `/api/lab/run-subcap/${encodeURIComponent(name)}`,
    { fixture_id, dry_run },
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
