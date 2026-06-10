import axios from "axios";

const api = axios.create({ baseURL: "/api" });

export interface UploadSampleResponse {
  sample_id: string;
  source_path: string;
  normalized_path: string;
  info: { format: any; streams: any[] };
}

export interface RenderDemoResponse {
  task_id: string;
  project_id: string;
}

export interface TaskStatus {
  id: string;
  kind: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  stage: string;
  resource_kind: string | null;
  resource_id: string | null;
  /** /data/* URL of the resource's normalized.mp4, or null if absent. */
  normalized_media_url: string | null;
  result: { output_path?: string; absolute_path?: string; duration_sec?: number } | null;
  error: string | null;
}

export async function uploadSample(file: File): Promise<UploadSampleResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<UploadSampleResponse>("/samples", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function renderDemo(sampleId: string): Promise<RenderDemoResponse> {
  const { data } = await api.post<RenderDemoResponse>(`/samples/${sampleId}/render-demo`);
  return data;
}

export async function pollTask(taskId: string): Promise<TaskStatus> {
  const { data } = await api.get<TaskStatus>(`/tasks/${taskId}`);
  return data;
}

export function dataUrl(rel: string): string {
  return `/data/${rel.replace(/^\/+/, "")}`;
}

// ---------------------------------------------------------------------------
// Phase 2 · projects + apply + render
// ---------------------------------------------------------------------------

export interface UploadProjectResponse {
  project_id: string;
  user_material_path: string;
  normalized_path: string;
  info: any;
}

export interface RecommendItem {
  template_id: string;
  score: number;
  reason: string;
  name: string | null;
  thumbnail_path: string | null;
  tags: any | null;
}

export interface RecommendResponse {
  task_id: string;
  workbench_url: string;
  recommendations: RecommendItem[];
}

export interface ApplyResponse {
  task_id: string;
  project_id: string;
  workbench_url: string;
}

export interface ProjectResponse {
  project_id: string;
  ir: any | null;
  user_material_url: string | null;
}

export interface PreviewProps {
  project_id: string;
  canvas: { width: number; height: number; fps: number; [k: string]: any };
  sections: Array<{
    topic: string;
    template_id: string;
    segments: Array<{
      slot_role: string;
      src_timerange: [number, number];
      timeline_start: number;
      speed: number;
      is_fill: boolean;
      applied_style: any;
    }>;
  }>;
  captions: any[];
  user_material_url: string | null;
  bgm_url: string | null;
}

export async function uploadProject(file: File): Promise<UploadProjectResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<UploadProjectResponse>("/projects", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function recommendTemplates(
  projectId: string,
  k = 3,
): Promise<RecommendResponse> {
  const { data } = await api.post<RecommendResponse>(
    `/projects/${projectId}/recommend-templates`,
    { k },
  );
  return data;
}

export async function applyTemplate(
  projectId: string,
  templateId: string,
  allowAigcBroll = false,
): Promise<ApplyResponse> {
  const { data } = await api.post<ApplyResponse>(`/projects/${projectId}/apply`, {
    template_id: templateId,
    allow_aigc_broll: allowAigcBroll,
  });
  return data;
}

export async function getProject(projectId: string): Promise<ProjectResponse> {
  const { data } = await api.get<ProjectResponse>(`/projects/${projectId}`);
  return data;
}

export async function getPreviewProps(projectId: string): Promise<PreviewProps> {
  const { data } = await api.get<PreviewProps>(`/projects/${projectId}/preview-props`);
  return data;
}

export async function renderProject(
  projectId: string,
): Promise<{ task_id: string; project_id: string }> {
  const { data } = await api.post<{ task_id: string; project_id: string }>(
    `/projects/${projectId}/render`,
  );
  return data;
}

export interface ProjectSummary {
  project_id: string;
  has_ir: boolean;
  template_id: string | null;
  updated_at: number;
}

export async function listProjects(): Promise<{ projects: ProjectSummary[] }> {
  const { data } = await api.get<{ projects: ProjectSummary[] }>("/projects");
  return data;
}

// ---------------------------------------------------------------------------
// Phase 2.5 · NL / panel edits + history + replay
// ---------------------------------------------------------------------------

export interface EditResponse {
  task_id: string;
  workbench_url: string;
  patches_applied: number;
  ir: any | null;
  render_task_id: string | null;
}

export async function nlEdit(
  projectId: string,
  instruction: string,
  render = true,
): Promise<EditResponse> {
  const { data } = await api.post<EditResponse>(`/projects/${projectId}/edit`, {
    instruction,
    render,
  });
  return data;
}

export async function panelEdit(
  projectId: string,
  field: string,
  value: unknown,
  target?: Record<string, unknown>,
  render = true,
): Promise<EditResponse> {
  const { data } = await api.post<EditResponse>(`/projects/${projectId}/panel-edit`, {
    field,
    value,
    target,
    render,
  });
  return data;
}

export async function undoEdit(
  projectId: string,
  render = true,
): Promise<EditResponse> {
  const { data } = await api.post<EditResponse>(`/projects/${projectId}/undo`, { render });
  return data;
}

export interface PatchHistoryEntry {
  task_id: string;
  kind: string;
  timestamp: string;
  sequence: number;
  op: string | null;
  target: Record<string, unknown> | null;
  value: Record<string, unknown> | null;
  source: string | null;
  reasoning: string;
  event_id: string;
}

export async function listPatchHistory(
  projectId: string,
): Promise<{ project_id: string; patches: PatchHistoryEntry[] }> {
  const { data } = await api.get<{ project_id: string; patches: PatchHistoryEntry[] }>(
    `/projects/${projectId}/history`,
  );
  return data;
}

export interface ResourceTask {
  task_id: string;
  kind: string;
  status: string;
  progress: number;
  stage: string | null;
  created_at: number | null;
  updated_at: number | null;
  error: string | null;
}

export async function listSampleTasks(
  sampleId: string,
): Promise<{ sample_id: string; tasks: ResourceTask[] }> {
  const { data } = await api.get<{ sample_id: string; tasks: ResourceTask[] }>(
    `/samples/${sampleId}/tasks`,
  );
  return data;
}

export async function listProjectTasks(
  projectId: string,
): Promise<{ project_id: string; tasks: ResourceTask[] }> {
  const { data } = await api.get<{ project_id: string; tasks: ResourceTask[] }>(
    `/projects/${projectId}/tasks`,
  );
  return data;
}

export interface ReplayEvent {
  event_id: string;
  task_id: string;
  sequence: number;
  timestamp: string;
  duration_ms: number;
  source: string;
  model_used: string | null;
  stage: string;
  frame_ts: number | null;
  frame_url: string | null;
  bbox_norm: [number, number, number, number] | null;
  semantic_label: string;
  reasoning: string;
  confidence: number;
  ir_target: { ir_type: string; path: string; field: string | null; op: string } | null;
  ir_value: unknown;
  parent_event_id: string | null;
  cost_tokens: number | null;
  severity: string;
  confidence_warning: boolean;
}

export interface ReplayEventsResponse {
  task_id: string;
  task: {
    kind: string | null;
    status: string | null;
    stage: string | null;
    resource_kind: string | null;
    resource_id: string | null;
  };
  events: ReplayEvent[];
}

export async function fetchReplayEvents(
  projectId: string,
  taskId?: string,
): Promise<ReplayEventsResponse> {
  const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
  const { data } = await api.get<ReplayEventsResponse>(
    `/projects/${projectId}/replay/events${query}`,
  );
  return data;
}

export async function fetchReplayEventsForSample(
  sampleId: string,
  taskId?: string,
): Promise<ReplayEventsResponse> {
  const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
  const { data } = await api.get<ReplayEventsResponse>(
    `/samples/${sampleId}/replay/events${query}`,
  );
  return data;
}

export async function snapshotAtSequence(
  projectId: string,
  taskId: string,
  sequence: number,
): Promise<{ task_id: string; sequence: number; snapshot: any; events_count: number }> {
  const { data } = await api.post(`/projects/${projectId}/replay/snapshot`, {
    task_id: taskId,
    sequence,
  });
  return data;
}

export interface LineageResponse {
  project_id: string;
  template: any | null;
  mapping: Array<{
    slot_role: string;
    source_unit_ids: number[];
    src_timerange: [number, number];
    speed: number;
    is_fill: boolean;
  }>;
  placed_segments: any[];
  gaps: Array<{
    slot_role: string;
    reason: string;
    fill_strategy: string;
    fill_result: string;
  }>;
  captions_count: number;
  bgm_track: string | null;
  canvas: any;
  version: number;
  edit_count: number;
  degraded: Record<string, string>;
}

export async function fetchProjectLineage(projectId: string): Promise<LineageResponse> {
  const { data } = await api.get<LineageResponse>(`/projects/${projectId}/lineage`);
  return data;
}

export async function rejectEvent(
  taskId: string,
  eventId: string,
): Promise<{ ok: boolean; vetoed_event_id: string; veto_event_id: string }> {
  const { data } = await api.post(
    `/workbench/${taskId}/reject-event/${encodeURIComponent(eventId)}`,
  );
  return data;
}

export * from "./events.js";
export * from "./templates.js";
