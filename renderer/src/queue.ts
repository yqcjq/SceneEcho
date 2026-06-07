import PQueue from "p-queue";

// MVP: serial rendering to avoid headless Chromium contention.
export const renderQueue = new PQueue({ concurrency: 1 });

export function queueStatus() {
  return {
    pending: renderQueue.size,
    running: renderQueue.pending,
  };
}
