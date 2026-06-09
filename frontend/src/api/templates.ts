import axios from "axios";

// Phase 1B · KB template API client.

export interface TemplateSummary {
  id: string;
  name: string;
  source_sample: string;
  tags: {
    position: string;
    function: string;
    scene: string;
    notes: string;
  };
  thumbnail_path: string | null;
  last_extract_task_id: string | null;
  created_at: number;
}

export interface TemplateDetail extends TemplateSummary {
  ir: any;
}

export interface ExtractTemplateResponse {
  task_id: string;
  sample_id: string;
  workbench_url: string;
}

export async function triggerExtract(
  sampleId: string,
  name?: string,
): Promise<ExtractTemplateResponse> {
  const { data } = await axios.post<ExtractTemplateResponse>(
    `/api/samples/${encodeURIComponent(sampleId)}/extract`,
    null,
    { params: name ? { name } : {} },
  );
  return data;
}

export async function listTemplates(): Promise<TemplateSummary[]> {
  const { data } = await axios.get<{ templates: TemplateSummary[] }>("/api/templates");
  return data.templates;
}

export async function getTemplate(id: string): Promise<TemplateDetail> {
  const { data } = await axios.get<TemplateDetail>(
    `/api/templates/${encodeURIComponent(id)}`,
  );
  return data;
}

export async function patchTemplateTags(
  id: string,
  tags: Partial<TemplateSummary["tags"]>,
): Promise<void> {
  await axios.patch(`/api/templates/${encodeURIComponent(id)}/tags`, tags);
}

export async function patchCaptionPlaceholder(
  id: string,
  slotIdx: number,
  placeholderText: string[],
): Promise<void> {
  await axios.patch(`/api/templates/${encodeURIComponent(id)}/caption-placeholder`, {
    slot_idx: slotIdx,
    placeholder_text: placeholderText,
  });
}

export async function deleteTemplate(id: string): Promise<void> {
  await axios.delete(`/api/templates/${encodeURIComponent(id)}`);
}

export interface TemplateEventsResponse {
  task_id: string | null;
  events: any[];
}

export async function getTemplateEvents(id: string): Promise<TemplateEventsResponse> {
  const { data } = await axios.get<TemplateEventsResponse>(
    `/api/templates/${encodeURIComponent(id)}/events`,
  );
  return data;
}
