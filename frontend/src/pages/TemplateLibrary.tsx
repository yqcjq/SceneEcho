import React from "react";
import { Link, useParams } from "react-router-dom";
import {
  dataUrl,
  deleteTemplate,
  getTemplate,
  listTemplates,
  patchCaptionPlaceholder,
  patchTemplateTags,
  type TemplateDetail,
  type TemplateSummary,
} from "../api/index.js";

/**
 * Phase 1B · KB browse page (PLAN 1553).
 *
 * Two routes share this module:
 *   /templates            → list
 *   /templates/:id        → detail (skeleton + style summary + placeholder
 *                            editor + sanity verdict + workbench replay)
 *
 * Visual language follows the Anthropic-style tokens registered in
 * tokens.css (card = bg-surface + border-default, no shadow; warm-orange
 * accent for actions; serif for headings).
 */
export const TemplateLibrary: React.FC = () => {
  const params = useParams<{ id?: string }>();
  if (params.id) {
    return <TemplateDetailView id={params.id} />;
  }
  return <TemplateListView />;
};

const TemplateListView: React.FC = () => {
  const [items, setItems] = React.useState<TemplateSummary[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    try {
      setItems(await listTemplates());
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error) {
    return (
      <div className="mx-auto max-w-[1024px] px-6 py-12 text-error">
        加载模板库失败：{error}
      </div>
    );
  }
  if (items === null) {
    return <div className="mx-auto max-w-[1024px] px-6 py-12 text-secondary">加载中…</div>;
  }
  return (
    <div className="mx-auto max-w-[1024px] px-6 py-12">
      <div className="flex items-baseline justify-between">
        <h1 className="font-serif text-2xl text-primary">模板库</h1>
        <Link to="/sample-extract" className="se-btn-ghost text-sm">
          ＋ 上传新样例
        </Link>
      </div>
      <p className="mt-2 text-secondary text-sm">
        Phase 1B extract pipeline 写入的可复用风格配方。
      </p>
      {items.length === 0 ? (
        <div className="mt-8 border border-border bg-surface p-6 text-secondary text-sm">
          KB 为空。回到样例页上传一段 5–20s 样例并点「提取模板」即可看到结果。
        </div>
      ) : (
        <ul className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
          {items.map((t) => (
            <li
              key={t.id}
              className="border border-border bg-surface p-4"
            >
              <Link to={`/templates/${t.id}`} className="block">
                {t.thumbnail_path ? (
                  <img
                    src={dataUrl(t.thumbnail_path)}
                    alt=""
                    className="mb-3 h-32 w-full object-cover"
                  />
                ) : (
                  <div className="mb-3 flex h-32 items-center justify-center bg-subtle text-tertiary text-xs">
                    无缩略图
                  </div>
                )}
                <div className="font-serif text-lg text-primary">{t.name}</div>
                <div className="mt-1 text-tertiary text-xs font-mono">{t.id}</div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="border border-border px-2 py-0.5">
                    {t.tags.function}
                  </span>
                  <span className="border border-border px-2 py-0.5">
                    {t.tags.scene}
                  </span>
                  <span className="border border-border px-2 py-0.5">
                    {t.tags.position}
                  </span>
                </div>
                {t.tags.notes && (
                  <div className="mt-2 text-secondary text-xs">{t.tags.notes}</div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

const TemplateDetailView: React.FC<{ id: string }> = ({ id }) => {
  const [t, setT] = React.useState<TemplateDetail | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    try {
      setT(await getTemplate(id));
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  }, [id]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const onDelete = async () => {
    if (!confirm(`删除模板 ${id}？此操作不可撤销。`)) return;
    try {
      await deleteTemplate(id);
      window.location.href = "/templates";
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  };

  if (error) {
    return (
      <div className="mx-auto max-w-[1024px] px-6 py-12 text-error">
        加载失败：{error}
      </div>
    );
  }
  if (!t) {
    return <div className="mx-auto max-w-[1024px] px-6 py-12 text-secondary">加载中…</div>;
  }

  const ir = t.ir ?? {};
  const skeleton = ir.skeleton ?? [];
  const degraded = ir.degraded ?? {};
  const degradedCount = Object.keys(degraded).length;
  const sanity = ir.sanity_check;

  return (
    <div className="mx-auto max-w-[1024px] px-6 py-12">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="font-serif text-2xl text-primary">{t.name}</h1>
          <div className="mt-1 text-tertiary text-xs font-mono">{t.id}</div>
        </div>
        <div className="flex gap-2 text-sm">
          <Link to="/templates" className="se-btn-ghost">← 返回</Link>
          {t.last_extract_task_id && (
            <Link
              to={`/workbench/${t.last_extract_task_id}`}
              className="se-btn-ghost"
            >
              回放工作台事件流
            </Link>
          )}
          <button type="button" onClick={onDelete} className="se-btn-ghost text-error">
            删除
          </button>
        </div>
      </div>

      {degradedCount > 0 && (
        <div className="mt-4 border border-warning bg-subtle p-3 text-sm text-primary">
          ⚠ 此模板有 {degradedCount} 项 degraded：{Object.keys(degraded).join(", ")}
        </div>
      )}

      {sanity && (
        <div className="mt-4 border border-border bg-surface p-4 text-sm">
          <div className="font-serif text-base">Sanity check</div>
          <div className={`mt-1 ${sanity.ok ? "text-success" : "text-error"}`}>
            {sanity.ok ? "✓ 通过" : `✗ ${(sanity.issues ?? []).length} 项问题`}
          </div>
          {(sanity.issues ?? []).map((iss: string, i: number) => (
            <div key={i} className="mt-1 text-secondary text-xs">
              · {iss}
            </div>
          ))}
          {sanity.reasoning && (
            <div className="mt-2 text-tertiary text-xs">{sanity.reasoning}</div>
          )}
        </div>
      )}

      <h2 className="mt-8 font-serif text-xl">骨架</h2>
      <div className="mt-3 grid grid-cols-1 gap-3">
        {skeleton.map((slot: any, i: number) => (
          <SlotCard key={i} slot={slot} slotIdx={i} templateId={id} onSaved={refresh} />
        ))}
      </div>

      <h2 className="mt-8 font-serif text-xl">原始 IR</h2>
      <pre className="mt-3 max-h-[480px] overflow-auto border border-border bg-subtle p-3 text-xs font-mono">
        {JSON.stringify(ir, null, 2)}
      </pre>
    </div>
  );
};

const SlotCard: React.FC<{
  slot: any;
  slotIdx: number;
  templateId: string;
  onSaved: () => void;
}> = ({ slot, slotIdx, templateId, onSaved }) => {
  const cap = slot.style?.caption;
  // placeholder_text lives directly on CaptionStyle (1B IR). The renderer
  // and the Phase 2 fill LLM both read from this exact path; no second
  // home, no rhythm-dict hack.
  const existingPlaceholder: string[] = cap?.placeholder_text ?? [];
  const [draft, setDraft] = React.useState(existingPlaceholder.join(", "));
  const [saving, setSaving] = React.useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await patchCaptionPlaceholder(
        templateId,
        slotIdx,
        draft.split(",").map((s) => s.trim()).filter(Boolean),
      );
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border border-border bg-surface p-4 text-sm">
      <div className="flex items-baseline justify-between">
        <div className="font-serif text-base">
          slot {slotIdx} · {slot.role} · {slot.material_req}
        </div>
        <div className="text-tertiary text-xs font-mono">
          {slot.duration?.min}–{slot.duration?.nominal}–{slot.duration?.max}s
        </div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-3 text-xs text-secondary">
        <div>
          <div className="font-mono text-tertiary">字幕</div>
          {cap ? (
            <div>
              {cap.font_family} {cap.size}px · {cap.color} · {cap.layout} ·{" "}
              anim_in={cap.anim_in}
            </div>
          ) : (
            <div className="text-tertiary">无</div>
          )}
        </div>
        <div>
          <div className="font-mono text-tertiary">视觉</div>
          <div>
            zoom {slot.style?.visual?.zoom_keyframes?.length ?? 0} kf · mask=
            {slot.style?.visual?.mask ?? "—"} · lut=
            {slot.style?.visual?.color_lut ?? "—"}
          </div>
        </div>
        <div>
          <div className="font-mono text-tertiary">贴纸</div>
          <div>{(slot.style?.stickers ?? []).length} 枚</div>
        </div>
        <div>
          <div className="font-mono text-tertiary">转场</div>
          <div>
            in={slot.style?.transition_in ?? "—"} / out=
            {slot.style?.transition_out ?? "—"}
          </div>
        </div>
      </div>
      {cap && (
        <div className="mt-3 border-t border-border pt-3">
          <div className="font-mono text-tertiary text-xs">
            placeholder_text（逗号分隔，应用阶段 LLM 填字幕的视觉锚点）
          </div>
          <div className="mt-1 flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="flex-1 border border-border bg-canvas px-2 py-1 text-xs font-mono"
              placeholder="4-6 字 CTA 短语示例：立即抢购"
            />
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="se-btn-ghost text-xs"
            >
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
