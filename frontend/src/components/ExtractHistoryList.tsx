import React from "react";
import { Link } from "react-router-dom";
import { listProjectTasks, listSampleTasks, type ResourceTask } from "../api/index.js";

/**
 * ExtractHistoryList — Phase 2.5 "提取/编辑历史" entry.
 *
 * Drops into a sample / project detail page and renders every prior
 * task attached to that resource as a short list of links into the
 * workbench. Eliminates the "I uploaded yesterday, can't remember the
 * task_id, can't find my extract" dead end PLAN 1723 flagged.
 *
 * Stays presentational on purpose — the parent decides when to fetch
 * (we re-fetch on every mount + on resource-id change). Errors degrade
 * to an empty list with a small notice so the parent page isn't
 * blocked by a transient backend hiccup.
 */
interface Props {
  resourceKind: "sample" | "project";
  resourceId: string;
  className?: string;
  emptyHint?: React.ReactNode;
}

const KIND_LABELS: Record<string, string> = {
  extract_template: "提取模板",
  recommend_templates: "推荐模板",
  apply_short: "应用模板",
  nl_edit: "自然语言编辑",
  panel_edit: "参数面板编辑",
  undo: "撤销",
  render: "渲染",
  lab_captions: "lab · 字幕",
  lab_stickers: "lab · 贴纸",
  lab_zoom_direction: "lab · 缩放方向",
  lab_zoom_curve: "lab · 缩放曲线",
  lab_transitions: "lab · 转场",
  lab_masks: "lab · 蒙版",
  lab_color_lut: "lab · 调色",
  lab_audio: "lab · 音频",
  lab_caption_function: "lab · 字幕功能",
  test: "调试",
};

function statusColor(status: string): string {
  if (status === "completed") return "text-success";
  if (status === "failed") return "text-error";
  if (status === "running") return "text-accent";
  if (status === "superseded") return "text-tertiary";
  return "text-secondary";
}

function relativeTime(ts: number | null): string {
  if (!ts) return "";
  const now = Date.now() / 1000;
  const delta = now - ts;
  if (delta < 60) return `${Math.round(delta)}s 前`;
  if (delta < 3600) return `${Math.round(delta / 60)}m 前`;
  if (delta < 86400) return `${Math.round(delta / 3600)}h 前`;
  return `${Math.round(delta / 86400)}d 前`;
}

export const ExtractHistoryList: React.FC<Props> = ({
  resourceKind,
  resourceId,
  className,
  emptyHint,
}) => {
  const [tasks, setTasks] = React.useState<ResourceTask[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const fetch =
      resourceKind === "sample"
        ? listSampleTasks(resourceId)
        : listProjectTasks(resourceId);
    fetch
      .then((r) => {
        if (cancelled) return;
        setTasks(r.tasks);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e?.message ?? e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [resourceKind, resourceId]);

  if (loading) {
    return (
      <div className={className}>
        <span className="text-tertiary text-sm">读取历史中…</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className={className}>
        <span className="text-error text-sm">读取失败：{error}</span>
      </div>
    );
  }
  if (tasks.length === 0) {
    return (
      <div className={className}>
        {emptyHint ?? <span className="text-tertiary text-sm">暂无任务历史。</span>}
      </div>
    );
  }
  return (
    <div className={className}>
      <ul className="divide-border divide-y border-border rounded-md border">
        {tasks.map((t) => {
          const short = t.task_id.slice(0, 8);
          const label = KIND_LABELS[t.kind] ?? t.kind;
          return (
            <li key={t.task_id} className="px-3 py-2 hover:bg-surface-hover">
              <Link
                to={`/workbench/${t.task_id}`}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-tertiary text-xs">#{short}</span>
                  <span className="text-primary">{label}</span>
                  {t.stage && t.stage !== label ? (
                    <span className="text-tertiary text-xs">{t.stage}</span>
                  ) : null}
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <span className={`font-mono ${statusColor(t.status)}`}>{t.status}</span>
                  <span className="text-tertiary">{relativeTime(t.created_at)}</span>
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
};
