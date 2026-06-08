import axios from "axios";
import type {
  ScenarioListItem,
  VisionEvent,
} from "../types/workbench.js";

/**
 * SSE subscription helper. Returns a teardown function.
 *
 * The browser's native EventSource auto-maintains `Last-Event-ID` across
 * reconnects, so we don't pass it manually — that's exactly the contract
 * the backend `/api/tasks/{id}/events` endpoint promises (PLAN.md H3).
 */
export interface SubscribeOptions {
  onEvent: (event: VisionEvent) => void;
  onError?: (err: Event) => void;
  onDone?: () => void;
}

export function subscribeEvents(
  taskId: string,
  options: SubscribeOptions,
): () => void {
  const url = `/api/tasks/${encodeURIComponent(taskId)}/events`;
  const es = new EventSource(url);

  const handleVision = (e: MessageEvent) => {
    try {
      const parsed = JSON.parse(e.data) as VisionEvent;
      options.onEvent(parsed);
    } catch (err) {
      // Bad payload shouldn't kill the stream; surface to caller via onError.
      options.onError?.(new Event("parse-error"));
    }
  };

  const handleDone = () => {
    options.onDone?.();
    es.close();
  };

  es.addEventListener("vision", handleVision as EventListener);
  es.addEventListener("done", handleDone);
  // sse-starlette's heartbeat is an SSE comment line (`: heartbeat\n\n`)
  // — browsers consume it natively, no named event is dispatched. So no
  // "ping" listener here; adding one was a dead handler.
  if (options.onError) {
    es.onerror = options.onError;
  }

  return () => {
    es.removeEventListener("vision", handleVision as EventListener);
    es.removeEventListener("done", handleDone);
    es.close();
  };
}

export async function fetchEventHistory(taskId: string): Promise<VisionEvent[]> {
  const { data } = await axios.get<VisionEvent[]>(
    `/api/tasks/${encodeURIComponent(taskId)}/events/history`,
  );
  return data;
}

export interface MockStreamResponse {
  task_id: string;
  sample_id: string;
  workbench_url: string;
}

export async function startMockStream(scenario: string): Promise<MockStreamResponse> {
  const { data } = await axios.post<MockStreamResponse>(
    "/api/dev/workbench/mock-stream",
    { scenario },
  );
  return data;
}

export async function listScenarios(): Promise<ScenarioListItem[]> {
  const { data } = await axios.get<{ scenarios: ScenarioListItem[] }>(
    "/api/dev/workbench/scenarios",
  );
  return data.scenarios;
}
