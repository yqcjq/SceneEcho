import React from "react";
import { Link } from "react-router-dom";
import { pollTask, type TaskStatus } from "../../api/index.js";

/**
 * Workbench breadcrumb (Phase 2.5, PLAN 1736).
 *
 * Mounts in the top bar of /workbench/:taskId and renders
 *   样例 > {sample_name} > 提取任务 #{tid前8位}
 * or
 *   项目 > {project_name} > 应用任务 #{tid前8位}
 *
 * Data flow: task → resource_kind / resource_id → resource detail
 * fetch. When the resource detail fetch fails (deleted sample / old
 * task) we degrade to ``任务 #{tid前8位}`` rather than leaving the
 * breadcrumb empty — the workbench still works on the task_id alone.
 */
interface Props {
  taskId: string | null;
}

const RESOURCE_BUCKETS: Record<string, { label: string; routeBase: string }> = {
  sample: { label: "样例", routeBase: "/samples" },
  project: { label: "项目", routeBase: "/editor" },
};

const KIND_LABEL: Record<string, string> = {
  extract_template: "提取任务",
  recommend_templates: "推荐任务",
  apply_short: "应用任务",
  nl_edit: "NL 编辑",
  panel_edit: "面板编辑",
  undo: "撤销",
  render: "渲染任务",
};

export const WorkbenchBreadcrumb: React.FC<Props> = ({ taskId }) => {
  const [task, setTask] = React.useState<TaskStatus | null>(null);
  const [resourceName, setResourceName] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    if (!taskId) {
      setTask(null);
      setResourceName(null);
      return;
    }
    void (async () => {
      try {
        const t = await pollTask(taskId);
        if (cancelled) return;
        setTask(t);
        if (!t.resource_kind || !t.resource_id) {
          setResourceName(null);
          return;
        }
        // Best-effort resource name fetch — we only need .name. Sample
        // detail endpoint isn't a real thing yet (samples are anonymous
        // uploads) so fall back to the resource_id itself for samples.
        if (t.resource_kind === "project") {
          const res = await fetch(`/api/projects/${t.resource_id}`);
          if (!res.ok) {
            setResourceName(t.resource_id);
            return;
          }
          // ProjectResponse currently exposes no name; fall back to id.
          setResourceName(t.resource_id);
        } else {
          setResourceName(t.resource_id);
        }
      } catch {
        setTask(null);
        setResourceName(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  if (!taskId) return null;
  const short = taskId.slice(0, 8);
  if (!task || !task.resource_kind || !task.resource_id) {
    return (
      <span className="font-mono text-tertiary text-xs">任务 #{short}</span>
    );
  }
  const bucket = RESOURCE_BUCKETS[task.resource_kind];
  const kindLabel = KIND_LABEL[task.kind] ?? task.kind;
  if (!bucket) {
    return (
      <span className="font-mono text-tertiary text-xs">任务 #{short}</span>
    );
  }
  const resourceHref =
    task.resource_kind === "project"
      ? `${bucket.routeBase}/${task.resource_id}`
      : `/sample-extract?sample_id=${task.resource_id}`;
  return (
    <nav aria-label="breadcrumb" className="text-xs">
      <ol className="flex items-center gap-1.5 text-tertiary">
        <li>
          <Link
            to={resourceHref}
            className="text-secondary hover:text-accent-primary hover:underline"
          >
            {bucket.label}
          </Link>
        </li>
        <li>&gt;</li>
        <li>
          <Link
            to={resourceHref}
            className="text-secondary hover:text-accent-primary hover:underline"
          >
            {resourceName ?? task.resource_id}
          </Link>
        </li>
        <li>&gt;</li>
        <li className="font-mono text-primary">
          {kindLabel} #{short}
        </li>
      </ol>
    </nav>
  );
};
