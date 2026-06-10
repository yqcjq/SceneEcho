import React from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { fetchEventHistory, subscribeEvents } from "../api/events.js";
import { pollTask, type TaskStatus } from "../api/index.js";
import { WorkbenchBreadcrumb } from "../components/workbench/WorkbenchBreadcrumb.js";
import { WorkbenchEventStream } from "../components/workbench/WorkbenchEventStream.js";
import { WorkbenchIRPane } from "../components/workbench/WorkbenchIRPane.js";
import { WorkbenchVisionPane } from "../components/workbench/WorkbenchVisionPane.js";
import { useWorkbenchStore, type WorkbenchView } from "../state/workbench.js";
import { WorkbenchGantt } from "./WorkbenchGantt.js";
import { WorkbenchMediaTimeline } from "./WorkbenchMediaTimeline.js";

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

/**
 * Two-way binding between ``?view=`` query param and the store's
 * ``view`` field. URL is the source of truth on first load (so a shared
 * link respects ?view=gantt); subsequent ``setView`` calls update the URL
 * to keep the address bar in sync. Browser back/forward also flips the
 * view because the param change is a real navigation.
 */
function useViewParam(): WorkbenchView {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = useWorkbenchStore((s) => s.view);
  const setView = useWorkbenchStore((s) => s.setView);

  // URL → store on first load and on browser navigation.
  React.useEffect(() => {
    const raw = searchParams.get("view");
    const parsed: WorkbenchView =
      raw === "gantt" || raw === "media_timeline" ? raw : "list";
    if (parsed !== view) setView(parsed);
    // Intentionally only depend on the URL — store changes are pushed
    // back to the URL by the second effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Store → URL when the user clicks a view tab.
  React.useEffect(() => {
    const current = searchParams.get("view");
    const desired = view === "list" ? null : view;
    if (current === desired) return;
    const next = new URLSearchParams(searchParams);
    if (desired) next.set("view", desired);
    else next.delete("view");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  return view;
}

const VIEW_OPTIONS: { value: WorkbenchView; label: string }[] = [
  { value: "list", label: "三栏列表" },
  { value: "gantt", label: "壁钟甘特图" },
  { value: "media_timeline", label: "媒体时间线" },
];

const ViewSwitcher: React.FC<{ view: WorkbenchView }> = ({ view }) => {
  const setView = useWorkbenchStore((s) => s.setView);
  return (
    <div
      role="tablist"
      aria-label="workbench view"
      className="inline-flex rounded-sm border border-border bg-subtle p-0.5 font-mono text-[11px]"
    >
      {VIEW_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          aria-selected={view === opt.value}
          data-testid={`view-tab-${opt.value}`}
          onClick={() => setView(opt.value)}
          className={`rounded-[2px] px-2 py-0.5 ${
            view === opt.value ? "bg-accent text-text-inverted" : "text-secondary"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
};

export const Workbench: React.FC = () => {
  const params = useParams<{ taskId: string }>();
  const taskId = params.taskId ?? null;
  const reset = useWorkbenchStore((s) => s.reset);
  const appendEvent = useWorkbenchStore((s) => s.appendEvent);
  const events = useWorkbenchStore((s) => s.events);
  const paused = useWorkbenchStore((s) => s.paused);
  const togglePause = useWorkbenchStore((s) => s.togglePause);
  const view = useViewParam();
  const task = useTaskStatus(taskId);

  /**
   * "History sync" — pull every persisted event and shovel them through
   * ``appendEvent``. Cheap because the store dedups by event_id; idempotent
   * because we never go through the live queue. This is the second leg
   * that closes the SSE race: whatever live missed, history backfills.
   */
  const syncHistory = React.useCallback(
    async (id: string) => {
      try {
        const events = await fetchEventHistory(id);
        for (const e of events) appendEvent(e);
      } catch {
        // Best-effort. SSE may already have everything; user can refresh
        // if both paths fail (which would be a bigger problem than a
        // missing card).
      }
    },
    [appendEvent],
  );

  React.useEffect(() => {
    if (!taskId) return;
    reset(taskId);
    // The SSE endpoint replays history-then-live on connect. We rely on
    // the store's event_id dedup so the optional history sync below
    // won't double-write — meaning we can fearlessly call it on terminal
    // status to close any SSE gap.
    const teardown = subscribeEvents(taskId, {
      onEvent: (e) => appendEvent(e),
      onDone: () => {
        // SSE done means the server flushed its replay+live. Anything
        // still missing is a delivery race — backfill from history.
        void syncHistory(taskId);
      },
    });
    return teardown;
  }, [taskId, reset, appendEvent, syncHistory]);

  /**
   * Terminal-state safety net: if SSE never delivers ``done`` (e.g. the
   * connection dropped mid-flight and reconnect missed the sentinel), the
   * task-status poll still reaches completed/failed. Trigger a history
   * sync there too so the workbench always converges.
   */
  const lastSyncedRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!taskId || !task) return;
    if (task.status !== "completed" && task.status !== "failed") return;
    const key = `${taskId}:${task.status}`;
    if (lastSyncedRef.current === key) return;
    lastSyncedRef.current = key;
    void syncHistory(taskId);
  }, [taskId, task, syncHistory]);

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
        <div className="flex flex-col gap-1">
          <h1 className="font-serif text-lg text-primary">AI 透明工作台</h1>
          <WorkbenchBreadcrumb taskId={taskId} />
          <p className="text-tertiary text-xs font-mono">{taskId}</p>
        </div>
        <div className="flex items-center gap-4 text-xs text-secondary">
          <ViewSwitcher view={view} />
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
      {view === "gantt" ? (
        <div className="min-h-0 flex-1 border-t border-border">
          <WorkbenchGantt taskId={taskId} />
        </div>
      ) : view === "media_timeline" ? (
        <div className="min-h-0 flex-1 border-t border-border">
          <WorkbenchMediaTimeline
            taskId={taskId}
            videoUrl={task?.normalized_media_url ?? null}
          />
        </div>
      ) : (
        <div className="grid flex-1 overflow-hidden border-t border-border md:grid-cols-3 md:grid-rows-1">
          {/*
            md:grid-rows-1 → grid-template-rows: repeat(1, minmax(0, 1fr)). Without
            an explicit row template the row defaults to ``auto`` and grows to its
            tallest cell's content; that broke each pane's internal scroll because
            h-full resolved to the content-driven row height instead of the
            viewport-bounded grid height. The minmax(0, 1fr) lets the row track
            shrink below content size so flex-1 + overflow-y-auto inside each pane
            actually engage.
          */}
          <div className="border-r border-border">
            <WorkbenchVisionPane videoUrl={task?.normalized_media_url ?? null} />
          </div>
          <div className="border-r border-border">
            <WorkbenchEventStream />
          </div>
          <div>
            <WorkbenchIRPane />
          </div>
        </div>
      )}
    </div>
  );
};
