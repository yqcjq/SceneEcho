import React from "react";
import { nlEdit, type EditResponse } from "../../api/index.js";

/**
 * NLBar — Phase 2.5 natural-language editing input.
 *
 * Sits at the bottom of the Editor. User types "字幕改黄色" / "节奏加快"
 * → onSent fires with the freshly-returned ProjectIR + the workbench
 * link so the Editor can re-fetch preview-props and the user can drop
 * into /workbench to see the LLM trace.
 *
 * 300ms debounce of *future* edits while a previous request is still
 * in-flight is intentionally NOT done here — the user explicitly hits
 * Enter / clicks 发送. The Editor's render side is what gets supersede
 * semantics (a fresh edit before the prior render finishes cancels
 * the prior render).
 */
interface Props {
  projectId: string;
  onSent: (r: EditResponse) => void;
  disabled?: boolean;
}

export const NLBar: React.FC<Props> = ({ projectId, onSent, disabled }) => {
  const [value, setValue] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [lastTaskId, setLastTaskId] = React.useState<string | null>(null);
  const [lastReply, setLastReply] = React.useState<string | null>(null);

  const send = async () => {
    const text = value.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await nlEdit(projectId, text, true);
      setLastTaskId(r.task_id);
      const message =
        r.patches_applied === 0
          ? "未生成 patch — LLM 判断指令不可翻译。"
          : `已应用 ${r.patches_applied} 个 patch · 版本 v${r.ir?.version ?? "?"}`;
      setLastReply(message);
      setValue("");
      onSent(r);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-border bg-surface px-4 py-3">
      <div className="flex items-center gap-2">
        <input
          type="text"
          className="flex-1 border border-border bg-canvas px-3 py-2 text-sm"
          placeholder="自然语言指令：如「字幕改黄色描边黑色」、「节奏加快一点」、「换成模板 B 风格」"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          disabled={busy || disabled}
        />
        <button
          type="button"
          className="rounded-md bg-accent-primary px-4 py-2 text-sm text-inverted hover:bg-accent-hover disabled:opacity-50"
          onClick={send}
          disabled={busy || disabled || !value.trim()}
        >
          {busy ? "解析中…" : "发送"}
        </button>
      </div>
      {(lastReply || lastTaskId) && (
        <div className="mt-2 flex items-center justify-between text-xs">
          <span className="text-secondary">{lastReply}</span>
          {lastTaskId && (
            <a
              href={`/workbench/${lastTaskId}`}
              target="_blank"
              rel="noreferrer"
              className="text-accent-primary hover:underline"
            >
              查看 LLM 解析过程 →
            </a>
          )}
        </div>
      )}
      {error && (
        <div className="mt-2 text-error text-xs">错误：{error}</div>
      )}
    </div>
  );
};
