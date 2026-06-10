import React from "react";
import { Link } from "react-router-dom";
import {
  listPatchHistory,
  type PatchHistoryEntry,
  undoEdit,
  type EditResponse,
} from "../../api/index.js";

/**
 * PatchHistoryList — right pane of the Editor (Phase 2.5).
 *
 * Lists every NL / panel edit for this project, newest first, with
 * the op + value snippet + workbench link. Top button performs Undo
 * (snapshot stack pop). The history itself is read from the backend
 * which scans events.jsonl files for stage="2.5.nl_edit" — there is
 * no separate patch_history.jsonl, see decision 008.
 *
 * Re-fetches whenever ``refreshKey`` ticks (the parent ticks it on
 * every successful nl_edit / panel_edit / undo).
 */
interface Props {
  projectId: string;
  refreshKey: number;
  onUndone: (r: EditResponse) => void;
  applyTaskId: string | null;
}

const OP_LABEL: Record<string, string> = {
  set_caption_style: "改字幕样式",
  set_visual_style: "改视觉样式",
  adjust_rhythm: "调节奏",
  set_emphasis: "改强调词",
  swap_template: "换模板",
  delete_segment: "删段",
  set_canvas: "改画布",
  set_bgm: "改 BGM",
};

export const PatchHistoryList: React.FC<Props> = ({
  projectId,
  refreshKey,
  onUndone,
  applyTaskId,
}) => {
  const [items, setItems] = React.useState<PatchHistoryEntry[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [undoing, setUndoing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listPatchHistory(projectId)
      .then((r) => {
        if (cancelled) return;
        setItems(r.patches);
      })
      .catch((e) => !cancelled && setError(String(e?.message ?? e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey]);

  const onUndo = async () => {
    setUndoing(true);
    setError(null);
    try {
      const r = await undoEdit(projectId, true);
      onUndone(r);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    } finally {
      setUndoing(false);
    }
  };

  // Show in reverse chronological order so the newest patch is at the top.
  const reversed = [...items].reverse();

  return (
    <aside className="w-80 shrink-0 border-l border-border bg-surface px-4 py-4 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h3 className="font-serif text-base text-primary">编辑历史</h3>
        <button
          type="button"
          className="rounded-md border border-border px-3 py-1 text-xs hover:bg-canvas disabled:opacity-50"
          onClick={onUndo}
          disabled={undoing || items.length === 0}
        >
          {undoing ? "撤销中…" : `↺ 撤销 (${items.length})`}
        </button>
      </div>
      {applyTaskId && (
        <div className="mt-2">
          <Link
            to={`/workbench/${applyTaskId}`}
            className="text-xs text-accent-primary hover:underline"
          >
            打开工作台看 apply 全链路 →
          </Link>
        </div>
      )}
      {error && <div className="mt-2 text-error text-xs">{error}</div>}
      {loading ? (
        <div className="mt-3 text-tertiary text-xs">读取中…</div>
      ) : items.length === 0 ? (
        <div className="mt-3 text-tertiary text-xs">
          还没有编辑历史。在下方 NLBar 输入指令或在左侧调参数即可触发。
        </div>
      ) : (
        <ul className="mt-3 space-y-2">
          {reversed.map((p) => (
            <li
              key={`${p.task_id}-${p.event_id}`}
              className="border border-border bg-canvas p-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-tertiary">{p.kind}</span>
                <Link
                  to={`/workbench/${p.task_id}`}
                  className="text-accent-primary hover:underline"
                >
                  #{p.task_id.slice(0, 8)}
                </Link>
              </div>
              <div className="mt-1 text-primary">
                {OP_LABEL[p.op ?? ""] ?? p.op ?? "(unknown op)"}
              </div>
              {p.value && Object.keys(p.value).length > 0 && (
                <pre className="mt-1 text-tertiary text-[10px] font-mono whitespace-pre-wrap break-all">
                  {JSON.stringify(p.value, null, 0)}
                </pre>
              )}
              {p.reasoning && (
                <div className="mt-1 text-secondary text-[11px]">{p.reasoning}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
};
