import express from "express";
import { z } from "zod";

import { logger } from "./logger.js";
import { renderProjectIR } from "./render.js";
import {
  renderQueue,
  queueStatus,
  registerRender,
  cancelRender,
  finalizeRender,
} from "./queue.js";
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

// Phase 2.5: per-task cancellation. The backend's render-throttle module
// fires this when a fresh NL/panel edit superseds a pending render. Two
// shapes of effect:
//   - the task is still queued → the wrapper sees `cancelled=true` at
//     the top of its callback and short-circuits before doing any work
//   - the task is already rendering → we set the flag but Chromium keeps
//     going (terminating it cleanly is brittle); the callback reports
//     status=cancelled when it finishes
// Returns 200 in both found cases + 404 when the task_id is unknown so
// the backend can tell stale cancels (already finalized) from real ones.
app.delete("/render/:taskId", (req, res) => {
  const { taskId } = req.params;
  const result = cancelRender(taskId);
  if (!result.found) {
    return res.status(404).json({ code: "not_tracked", task_id: taskId });
  }
  logger.info({ taskId, wasRunning: result.wasRunning }, "render_cancel");
  res.json({
    ok: true,
    task_id: taskId,
    was_running: result.wasRunning,
  });
});

app.post("/render", async (req, res) => {
  const parsed = RenderRequest.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ code: "bad_request", message: parsed.error.message });
  }
  const { project_ir, task_id } = parsed.data;
  const taskId = task_id ?? `r_${Date.now()}`;
  const queuedPosition = renderQueue.size;

  const state = registerRender(taskId);

  // Acknowledge synchronously and queue the render; backend tracks progress via
  // /internal/task-progress webhooks rather than awaiting this HTTP call.
  const job = renderQueue.add(async () => {
    if (state.cancelled) {
      // The DELETE arrived while we were queued; never touch Chromium.
      logger.info({ taskId }, "render_skipped_cancelled_pre_start");
      await reportProgress(taskId, 1.0, "cancelled", "cancelled");
      finalizeRender(taskId);
      return { cancelled: true } as any;
    }
    state.started = true;
    try {
      await reportProgress(taskId, 0.05, "queued_pop");
      const result = await renderProjectIR(project_ir, taskId);
      if (state.cancelled) {
        // Cancel arrived mid-render; report cancelled rather than completed
        // so the backend's UI doesn't claim a fresh MP4 the user already
        // moved past. The half-rendered file (if any) stays on disk.
        logger.info({ taskId }, "render_completed_but_cancelled");
        await reportProgress(taskId, 1.0, "cancelled", "cancelled");
        finalizeRender(taskId);
        return { cancelled: true, ...result } as any;
      }
      await reportProgress(taskId, 1.0, "done", "completed", result as any);
      finalizeRender(taskId);
      return result;
    } catch (err: any) {
      logger.error({ err, taskId }, "render_error");
      await reportProgress(taskId, 1.0, "failed", "failed", undefined, String(err?.message ?? err));
      finalizeRender(taskId);
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
