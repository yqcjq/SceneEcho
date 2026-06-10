import PQueue from "p-queue";

// MVP: serial rendering to avoid headless Chromium contention.
export const renderQueue = new PQueue({ concurrency: 1 });

// Phase 2.5: per-task cancellation registry. The backend's render-throttle
// fires DELETE /render/{tid} when a project gets a fresher edit; we look
// the task up here and either skip its job (if it's still queued) or set
// the flag so the running render reports `cancelled` instead of `completed`.
// p-queue doesn't expose "remove a queued job by id" — wrapping each job
// with a `cancelled` check at the top of its callback is the canonical
// workaround.
interface RenderState {
  cancelled: boolean;
  started: boolean;
}
const renderStates = new Map<string, RenderState>();

export function registerRender(taskId: string): RenderState {
  const state: RenderState = { cancelled: false, started: false };
  renderStates.set(taskId, state);
  return state;
}

export function cancelRender(taskId: string): { found: boolean; wasRunning: boolean } {
  const state = renderStates.get(taskId);
  if (!state) return { found: false, wasRunning: false };
  const wasRunning = state.started;
  state.cancelled = true;
  return { found: true, wasRunning };
}

export function finalizeRender(taskId: string): void {
  // Once a render terminates (completed / failed / cancelled) we no
  // longer need its state — keep the map small even under heavy churn.
  renderStates.delete(taskId);
}

export function queueStatus() {
  return {
    pending: renderQueue.size,
    running: renderQueue.pending,
    tracked: renderStates.size,
  };
}
