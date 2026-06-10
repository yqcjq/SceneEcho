import React from "react";
import { Link } from "react-router-dom";
import { listProjects, type ProjectSummary } from "../../api/index.js";

/**
 * ProjectHistoryStrip — Editor 顶部的「历史项目」入口（Phase 2.5 二核）。
 *
 * Plan addressed the "leave-workbench-can't-find-task" pain via per-resource
 * task lists, but global navigation still had no entry to past projects. The
 * strip closes that gap: enter ``/editor`` → see horizontal chips of recent
 * projects → one click reopens. The chip layout doubles as a low-cost
 * directory affordance without forcing a separate ``/projects`` route.
 *
 * The current project stays in the list and is visually highlighted with
 * a "当前" badge instead of being filtered out — filtering creates a "did I
 * just click?" disconnect every time the URL changes. Showing-as-selected
 * is the standard tab / sidebar pattern.
 */
interface Props {
  currentProjectId?: string | null;
  /** Optional cap; default 6. The strip lists the most-recently-updated. */
  limit?: number;
}

function formatRelative(epochSec: number): string {
  if (!epochSec) return "";
  const delta = Date.now() / 1000 - epochSec;
  if (delta < 60) return `${Math.round(delta)}s 前`;
  if (delta < 3600) return `${Math.round(delta / 60)}m 前`;
  if (delta < 86400) return `${Math.round(delta / 3600)}h 前`;
  return `${Math.round(delta / 86400)}d 前`;
}

export const ProjectHistoryStrip: React.FC<Props> = ({
  currentProjectId,
  limit = 6,
}) => {
  const [items, setItems] = React.useState<ProjectSummary[] | null>(null);
  const [expanded, setExpanded] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((r) => {
        if (cancelled) return;
        setItems(r.projects);
      })
      .catch((e) => !cancelled && setError(String(e?.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [currentProjectId]); // refetch on project switch so the strip stays fresh

  if (error) {
    return (
      <div className="rounded-md border border-border bg-surface px-4 py-3 text-xs text-error">
        读取历史项目失败：{error}
      </div>
    );
  }
  if (!items) {
    return (
      <div className="rounded-md border border-border bg-surface px-4 py-3 text-xs text-tertiary">
        读取历史项目中…
      </div>
    );
  }

  // Keep API mtime DESC order — the current project stays where it
  // naturally falls so its visual position doesn't jump when selected.
  // It's still highlighted (border-accent-primary + "当前" badge) so the
  // user can immediately spot the active choice.
  if (items.length === 0) return null;

  const shown = expanded ? items : items.slice(0, limit);
  const hasMore = items.length > limit;

  return (
    <div className="rounded-md border border-border bg-surface px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="font-serif text-sm text-primary">历史项目</span>
        <span className="text-xs text-tertiary">{items.length} 个</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {shown.map((p) => {
          const isCurrent = p.project_id === currentProjectId;
          const short =
            p.project_id.length > 16
              ? `${p.project_id.slice(0, 12)}…`
              : p.project_id;
          return (
            <Link
              key={p.project_id}
              to={`/editor/${p.project_id}`}
              className={`group flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs ${
                isCurrent
                  ? "border-accent-primary bg-accent-subtle"
                  : "border-border bg-canvas hover:border-accent-primary"
              }`}
              title={p.project_id}
              aria-current={isCurrent ? "page" : undefined}
            >
              <code
                className={`font-mono ${
                  isCurrent
                    ? "font-semibold text-accent-primary"
                    : "text-primary group-hover:text-accent-primary"
                }`}
              >
                {short}
              </code>
              {isCurrent && (
                <span className="rounded-sm bg-accent-primary px-1.5 py-0.5 text-[10px] font-medium text-inverted">
                  当前
                </span>
              )}
              <span
                className={`text-[10px] ${
                  p.has_ir ? "text-success" : "text-tertiary"
                }`}
              >
                {p.has_ir ? "已应用" : "未应用"}
              </span>
              <span className="text-tertiary">{formatRelative(p.updated_at)}</span>
            </Link>
          );
        })}
        {hasMore && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="rounded-md border border-border bg-canvas px-3 py-1.5 text-xs text-secondary hover:border-accent-primary hover:text-accent-primary"
          >
            查看全部 ({items.length - limit} 更多)
          </button>
        )}
      </div>
    </div>
  );
};
