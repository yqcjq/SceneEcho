import React from "react";
import { panelEdit, type EditResponse } from "../../api/index.js";

/**
 * ParamPanel — Phase 2.5 parameter-panel editor.
 *
 * Lives on the left of the Editor. Each control mirrors a single
 * CaptionStyle / VisualStyle / canvas / bgm field; ``panelEdit``
 * translates the mutation into a Patch via ``panel_to_patches`` on the
 * backend, applies it, and returns the new ProjectIR.
 *
 * Bidirectional sync (PLAN 1710): the form values are derived from
 * ``ir.captions[0].style`` / ``ir.canvas`` / etc. on every render so
 * an NL edit elsewhere reshapes the panel without manual reset.
 *
 * The "render" param is true so any change immediately retriggers
 * MP4 generation; the backend's render-throttle keeps the renderer
 * from piling up sample renders when the user is sliding sliders.
 */
interface Props {
  projectId: string;
  ir: any;
  onApplied: (r: EditResponse) => void;
}

const COLORS: Array<{ label: string; value: string }> = [
  { label: "白", value: "#FFFFFF" },
  { label: "黄", value: "#FFD400" },
  { label: "红", value: "#FF3B30" },
  { label: "蓝", value: "#0066FF" },
  { label: "黑", value: "#000000" },
];

const ANIM_IN: Array<{ label: string; value: string }> = [
  { label: "淡入", value: "fade" },
  { label: "滑入", value: "slide" },
  { label: "逐字", value: "typewriter" },
  { label: "弹入", value: "pop" },
];

const POSITIONS: Array<{ label: string; value: [number, number] }> = [
  { label: "顶", value: [0.5, 0.15] },
  { label: "中", value: [0.5, 0.5] },
  { label: "底", value: [0.5, 0.85] },
];

export const ParamPanel: React.FC<Props> = ({ projectId, ir, onApplied }) => {
  const captionStyle = ir?.captions?.[0]?.style ?? {};
  const firstSegSpeed = ir?.sections?.[0]?.segments?.[0]?.speed ?? 1.0;
  const canvas = ir?.canvas ?? { width: 1080, height: 1920, fps: 30 };
  const bgmTrack = ir?.bgm_track ?? null;

  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const send = React.useCallback(
    async (field: string, value: unknown, target?: Record<string, unknown>) => {
      setBusy(true);
      setError(null);
      try {
        const r = await panelEdit(projectId, field, value, target, true);
        onApplied(r);
      } catch (err: any) {
        setError(String(err?.response?.data?.detail ?? err?.message ?? err));
      } finally {
        setBusy(false);
      }
    },
    [projectId, onApplied],
  );

  return (
    <aside className="w-72 shrink-0 border-r border-border bg-surface px-4 py-4 overflow-y-auto">
      <h3 className="font-serif text-base text-primary">参数面板</h3>
      <p className="mt-1 text-tertiary text-xs">
        每次改动都通过同一条 Patch 路径写入 ProjectIR；与 NL 编辑等价（D11）。
      </p>

      <Section title="字幕样式">
        <Label>颜色</Label>
        <div className="flex flex-wrap gap-1">
          {COLORS.map((c) => (
            <ColorChip
              key={c.value}
              label={c.label}
              hex={c.value}
              active={captionStyle.color === c.value}
              onPick={() => send("caption.color", c.value, { all: true })}
            />
          ))}
        </div>

        <Label className="mt-3">描边</Label>
        <div className="flex flex-wrap gap-1">
          {COLORS.map((c) => (
            <ColorChip
              key={`stroke-${c.value}`}
              label={c.label}
              hex={c.value}
              active={captionStyle.stroke_color === c.value}
              onPick={() => send("caption.stroke_color", c.value, { all: true })}
            />
          ))}
        </div>

        <Label className="mt-3">字号 ({captionStyle.size ?? 56})</Label>
        <input
          type="range"
          min={32}
          max={96}
          step={2}
          value={captionStyle.size ?? 56}
          onChange={(e) =>
            send("caption.size", parseInt(e.target.value, 10), { all: true })
          }
          className="w-full"
          disabled={busy}
        />

        <Label className="mt-3">位置</Label>
        <div className="flex gap-1">
          {POSITIONS.map((p) => (
            <button
              key={p.label}
              type="button"
              className={`flex-1 border px-2 py-1 text-xs ${
                Array.isArray(captionStyle.position) &&
                Math.abs(captionStyle.position[1] - p.value[1]) < 0.01
                  ? "border-accent-primary bg-accent-subtle"
                  : "border-border"
              }`}
              onClick={() => send("caption.position", p.value, { all: true })}
              disabled={busy}
            >
              {p.label}
            </button>
          ))}
        </div>

        <Label className="mt-3">入场动画</Label>
        <select
          value={captionStyle.anim_in ?? "fade"}
          onChange={(e) => send("caption.anim_in", e.target.value, { all: true })}
          className="w-full border border-border bg-canvas px-2 py-1 text-sm"
          disabled={busy}
        >
          {ANIM_IN.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>

        <Label className="mt-3">多行换行字符数</Label>
        <input
          type="number"
          min={6}
          max={40}
          value={captionStyle.max_chars_per_line ?? 12}
          onChange={(e) =>
            send(
              "caption.max_chars_per_line",
              parseInt(e.target.value || "12", 10),
              { all: true },
            )
          }
          className="w-full border border-border bg-canvas px-2 py-1 text-sm"
          disabled={busy}
        />

        <Label className="mt-3">Placeholder（fill 文案锚点）</Label>
        <input
          type="text"
          value={(captionStyle.placeholder_text ?? [""])[0] ?? ""}
          onChange={(e) =>
            send(
              "caption.placeholder_text",
              e.target.value ? [e.target.value] : [],
              { all: true },
            )
          }
          className="w-full border border-border bg-canvas px-2 py-1 text-sm"
          placeholder="例如：4-6 字 CTA 短语"
          disabled={busy}
        />
      </Section>

      <Section title="节奏">
        <Label>速度倍率 ({firstSegSpeed.toFixed(2)}×)</Label>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => send("rhythm.scale", 0.85, { all: true })}
            className="flex-1 border border-border px-2 py-1 text-xs"
            disabled={busy}
          >
            放慢 -15%
          </button>
          <button
            type="button"
            onClick={() => send("rhythm.scale", 1.15, { all: true })}
            className="flex-1 border border-border px-2 py-1 text-xs"
            disabled={busy}
          >
            加快 +15%
          </button>
        </div>
      </Section>

      <Section title="画布">
        <Label>分辨率</Label>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => {
              void send("canvas.width", 1080);
              void send("canvas.height", 1920);
            }}
            className={`flex-1 border px-2 py-1 text-xs ${
              canvas.width === 1080 && canvas.height === 1920
                ? "border-accent-primary bg-accent-subtle"
                : "border-border"
            }`}
            disabled={busy}
          >
            9:16
          </button>
          <button
            type="button"
            onClick={() => {
              void send("canvas.width", 1920);
              void send("canvas.height", 1080);
            }}
            className={`flex-1 border px-2 py-1 text-xs ${
              canvas.width === 1920 && canvas.height === 1080
                ? "border-accent-primary bg-accent-subtle"
                : "border-border"
            }`}
            disabled={busy}
          >
            16:9
          </button>
        </div>
      </Section>

      <Section title="BGM">
        <Label>当前曲目</Label>
        <code className="block break-all text-xs text-tertiary">
          {bgmTrack ?? "无"}
        </code>
        <div className="mt-2">
          <button
            type="button"
            onClick={() => send("bgm.track", null)}
            className="w-full border border-border px-2 py-1 text-xs"
            disabled={busy}
          >
            清空 BGM
          </button>
        </div>
      </Section>

      {error && <div className="text-error text-xs mt-3">错误：{error}</div>}
    </aside>
  );
};

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section className="mt-4 border-t border-border pt-4">
    <h4 className="font-serif text-sm text-primary">{title}</h4>
    <div className="mt-2 space-y-2">{children}</div>
  </section>
);

const Label: React.FC<{ children: React.ReactNode; className?: string }> = ({
  children,
  className,
}) => (
  <div className={`text-xs text-secondary mb-1 ${className ?? ""}`}>{children}</div>
);

const ColorChip: React.FC<{ label: string; hex: string; active: boolean; onPick: () => void }> = ({
  label,
  hex,
  active,
  onPick,
}) => (
  <button
    type="button"
    title={label}
    onClick={onPick}
    className={`flex h-7 w-9 items-center justify-center border text-[10px] ${
      active ? "border-accent-primary ring-2 ring-accent-primary" : "border-border"
    }`}
    style={{ backgroundColor: hex, color: contrastText(hex) }}
  >
    {label}
  </button>
);

function contrastText(hex: string): string {
  const v = parseInt(hex.replace("#", ""), 16);
  if (Number.isNaN(v)) return "#000";
  const r = (v >> 16) & 0xff;
  const g = (v >> 8) & 0xff;
  const b = v & 0xff;
  // Perceived brightness — flip to white text on dark backgrounds.
  return r * 0.299 + g * 0.587 + b * 0.114 > 140 ? "#000" : "#fff";
}
