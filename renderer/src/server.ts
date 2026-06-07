import express from "express";
import { z } from "zod";

import { logger } from "./logger.js";
import { renderProjectIR } from "./render.js";
import { renderQueue, queueStatus } from "./queue.js";
import { reportProgress } from "./progress.js";

const PORT = Number(process.env.RENDERER_PORT ?? 8001);

const app = express();
app.use(express.json({ limit: "10mb" }));

// Phase 0 keeps validation loose so the renderer matches whatever the backend
// posts; deeper zod validation moves in once gen-types is wired up end-to-end.
const RenderRequest = z.object({
  project_ir: z.record(z.any()),
  task_id: z.string().optional(),
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "renderer", queue: queueStatus() });
});

app.get("/render/queue", (_req, res) => {
  res.json(queueStatus());
});

app.post("/render", async (req, res) => {
  const parsed = RenderRequest.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ code: "bad_request", message: parsed.error.message });
  }
  const { project_ir, task_id } = parsed.data;
  const taskId = task_id ?? `r_${Date.now()}`;
  const queuedPosition = renderQueue.size;

  // Acknowledge synchronously and queue the render; backend tracks progress via
  // /internal/task-progress webhooks rather than awaiting this HTTP call.
  const job = renderQueue.add(async () => {
    try {
      await reportProgress(taskId, 0.05, "queued_pop");
      const result = await renderProjectIR(project_ir, taskId);
      await reportProgress(taskId, 1.0, "done", "completed", result as any);
      return result;
    } catch (err: any) {
      logger.error({ err, taskId }, "render_error");
      await reportProgress(taskId, 1.0, "failed", "failed", undefined, String(err?.message ?? err));
      throw err;
    }
  });

  // Await the job so backend's awaiting client gets a final answer too.
  try {
    const result = await job;
    res.json({ task_id: taskId, queued_position: queuedPosition, ...result });
  } catch (err: any) {
    res.status(500).json({ code: "render_failed", message: String(err?.message ?? err), retry_safe: false });
  }
});

app.listen(PORT, () => {
  logger.info({ port: PORT }, "renderer_listening");
});
