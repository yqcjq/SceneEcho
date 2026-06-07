import { logger } from "./logger.js";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:18521";

export async function reportProgress(
  taskId: string,
  progress: number,
  stage?: string,
  status?: string,
  result?: Record<string, unknown>,
  error?: string,
): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}/api/internal/task-progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_id: taskId,
        progress,
        stage,
        status,
        result,
        error,
      }),
    });
  } catch (err) {
    logger.warn({ err, taskId }, "progress_report_failed");
  }
}
