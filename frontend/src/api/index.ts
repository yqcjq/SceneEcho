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
