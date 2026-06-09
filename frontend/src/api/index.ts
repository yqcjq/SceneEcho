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

export * from "./events.js";
export * from "./templates.js";
