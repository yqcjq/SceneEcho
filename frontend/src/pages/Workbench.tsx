import React from "react";
import { useParams } from "react-router-dom";
import { subscribeEvents } from "../api/events.js";
import { pollTask, type TaskStatus } from "../api/index.js";
import { WorkbenchEventStream } from "../components/workbench/WorkbenchEventStream.js";
import { WorkbenchIRPane } from "../components/workbench/WorkbenchIRPane.js";
import { WorkbenchVisionPane } from "../components/workbench/WorkbenchVisionPane.js";
import { useWorkbenchStore } from "../state/workbench.js";

/**
 * Poll /api/tasks/{taskId} every 1.5s for status/stage/progress. Stops on
 * terminal status — no point pinging a finished task.
 */
function useTaskStatus(taskId: string | null): TaskStatus | null {
  const [task, setTask] = React.useState<TaskStatus | null>(null);
  React.useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const data = await pollTask(taskId);
        if (cancelled) return;
        setTask(data);
        if (data.status === "completed" || data.status === "failed") return;
      } catch {
        // Transient failure (e.g. backend restart). Retry below.
      }
      if (!cancelled) timer = setTimeout(tick, 1500);
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId]);
  return task;
}

export const Workbench: React.FC = () => {
  const params = useParams<{ taskId: string }>();
  const taskId = params.taskId ?? null;
  const reset = useWorkbenchStore((s) => s.reset);
  const appendEvent = useWorkbenchStore((s) => s.appendEvent);
  const events = useWorkbenchStore((s) => s.events);
  const paused = useWorkbenchStore((s) => s.paused);
  const togglePause = useWorkbenchStore((s) => s.togglePause);
  const task = useTaskStatus(taskId);

  React.useEffect(() => {
    if (!taskId) return;
    reset(taskId);
    // The SSE endpoint replays history-then-live on connect. We deliberately
    // do NOT call fetchEventHistory in addition — that would race with live
    // events and possibly clobber them.
    const teardown = subscribeEvents(taskId, {
      onEvent: (e) => appendEvent(e),
    });
    return teardown;
  }, [taskId, reset, appendEvent]);

  if (!taskId) {
    return (
      <div className="mx-auto max-w-[640px] px-6 py-12 text-center">
        <h1 className="font-serif text-2xl">工作台</h1>
        <p className="mt-2 text-secondary">需要有效的 task_id（如 /workbench/abc123）。</p>
      </div>
    );
  }

  const totalTokens = events.reduce((sum, e) => sum + (e.cost_tokens ?? 0), 0);
  const totalDuration = events.reduce((sum, e) => sum + e.duration_ms, 0);
  const progressPct = task ? Math.round((task.progress ?? 0) * 100) : null;
  const status = task?.status ?? null;
  const statusColor =
    status === "completed"
      ? "text-success"
      : status === "failed"
      ? "text-error"
      : status === "running"
      ? "text-accent"
      : "text-secondary";

  return (
    <div className="flex h-[calc(100vh-65px)] flex-col">
      <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
        <div>
          <h1 className="font-serif text-lg text-primary">AI 透明工作台</h1>
          <p className="text-tertiary text-xs font-mono">{taskId}</p>
        </div>
        <div className="flex items-center gap-4 text-xs text-secondary">
          {task ? (
            <span className={`font-mono ${statusColor}`}>
              {status ?? "?"}
              {progressPct !== null ? ` · ${progressPct}%` : ""}
              {task.stage ? ` · ${task.stage}` : ""}
            </span>
          ) : null}
          <span>{events.length} 事件</span>
          <span>{totalTokens} tokens</span>
          <span>{(totalDuration / 1000).toFixed(1)}s</span>
          <button
            type="button"
            onClick={togglePause}
            className="se-btn-ghost text-xs"
          >
            {paused ? "▶ 继续" : "⏸ 暂停"}
          </button>
        </div>
      </div>
      <div className="grid flex-1 overflow-hidden border-t border-border md:grid-cols-3">
        <div className="border-r border-border">
          <WorkbenchVisionPane />
        </div>
        <div className="border-r border-border">
          <WorkbenchEventStream />
        </div>
        <div>
          <WorkbenchIRPane />
        </div>
      </div>
    </div>
  );
};
