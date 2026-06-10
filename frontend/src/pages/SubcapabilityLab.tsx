import React from "react";
import { useNavigate } from "react-router-dom";
import {
  getBaseline,
  listLabSamples,
  listSubcaps,
  runSubcap,
  type LabSample,
  type SubcapDef,
} from "../api/lab.js";
import { uploadSample } from "../api/index.js";

/**
 * Phase 1A SubcapabilityLab — pick a sample × subcap, fire a single
 * detection run, jump to the workbench. Dev-only: ``main.tsx`` guards
 * the route on ``import.meta.env.DEV`` so production builds 404.
 *
 * Sample list comes from ``/api/lab/samples`` at request time
 * (decisions/010 P7) — every subcap can run against every sample, no
 * per-subcap fixture allowlist. ``＋ 上传新样例`` calls the regular
 * ``POST /samples`` ingest path so uploaded mp4s land in
 * ``data/samples/{generated_id}/`` exactly like UI uploads on the
 * sample-extract page; after ingest the new sample is auto-selected
 * in the dropdown.
 */
export const SubcapabilityLab: React.FC = () => {
  const navigate = useNavigate();
  const [subcaps, setSubcaps] = React.useState<SubcapDef[]>([]);
  const [samples, setSamples] = React.useState<LabSample[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [fixture, setFixture] = React.useState<string>("");
  const [baseline, setBaseline] = React.useState<unknown>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [running, setRunning] = React.useState(false);
  const [forceRefresh, setForceRefresh] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  // Load subcaps + samples in parallel; failure on either falls through
  // to a single error banner so the user knows ENABLE_DEV_MOCK gating.
  const refreshSamples = React.useCallback(async () => {
    try {
      const list = await listLabSamples();
      setSamples(list);
      // Auto-select the first runnable sample if none chosen yet.
      setFixture((prev) => {
        if (prev && list.some((s) => s.id === prev)) return prev;
        const firstRunnable = list.find((s) => s.has_normalized) ?? list[0];
        return firstRunnable?.id ?? "";
      });
    } catch (err: any) {
      setError(
        err?.response?.status === 403
          ? "ENABLE_DEV_MOCK 未启用——在 .env 设 ENABLE_DEV_MOCK=true 后可用。"
          : "无法加载样例列表。",
      );
    }
  }, []);

  React.useEffect(() => {
    listSubcaps()
      .then((items) => {
        setSubcaps(items);
        if (items.length) setSelected(items[0].name);
      })
      .catch((err) => {
        setError(
          err?.response?.status === 403
            ? "ENABLE_DEV_MOCK 未启用——在 .env 设 ENABLE_DEV_MOCK=true 后可用。"
            : "无法加载子能力列表。",
        );
      });
    void refreshSamples();
  }, [refreshSamples]);

  React.useEffect(() => {
    if (!selected) return;
    getBaseline(selected)
      .then(setBaseline)
      .catch(() => setBaseline(null));
  }, [selected]);

  const cur = subcaps.find((s) => s.name === selected) ?? null;
  const fixtureMeta = samples.find((s) => s.id === fixture) ?? null;
  const fixtureRunnable = fixtureMeta?.has_normalized ?? false;

  const onRun = async () => {
    if (!cur || !fixture) return;
    setRunning(true);
    setError(null);
    try {
      const r = await runSubcap(cur.name, fixture, { force_refresh: forceRefresh });
      navigate(r.workbench_url);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    } finally {
      setRunning(false);
    }
  };

  const onUploadClick = () => fileInputRef.current?.click();

  const onUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";  // allow re-selecting the same file later
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const r = await uploadSample(file);
      await refreshSamples();
      setFixture(r.sample_id);
    } catch (err: any) {
      setError(
        `上传失败：${String(err?.response?.data?.detail ?? err?.message ?? err)}`,
      );
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto max-w-[960px] px-6 py-12">
      <h1 className="font-serif text-2xl">SubcapabilityLab · 子能力单点验证</h1>
      <p className="mt-2 text-secondary text-sm">
        Phase 1A 把子能力（切点 / 字幕 / 贴纸 / 缩放 / 转场 / 蒙版 / 调色 / BGM / 字幕功能 / B-roll…）拆开
        独立验证。任意子能力 × 任意样例自由组合，通过工作台事件流观察识别过程。
      </p>

      {error ? (
        <div className="mt-6 rounded-md border border-error bg-accent-subtle px-4 py-3 text-sm text-error">
          {error}
        </div>
      ) : null}

      <div className="mt-8 grid gap-6 md:grid-cols-[280px_1fr]">
        <aside className="se-card flex flex-col divide-y divide-border">
          {subcaps.map((s) => (
            <button
              key={s.name}
              type="button"
              onClick={() => setSelected(s.name)}
              className={
                "px-4 py-3 text-left text-sm transition-colors " +
                (s.name === selected
                  ? "bg-accent-subtle text-accent"
                  : "hover:bg-subtle")
              }
            >
              <div className="font-mono text-xs text-tertiary">{s.stage}</div>
              <div className="text-primary">{s.label}</div>
            </button>
          ))}
        </aside>

        <section className="se-card px-6 py-5">
          {cur ? (
            <>
              <div className="mb-4">
                <h2 className="font-serif text-lg">{cur.label}</h2>
                <p className="text-xs text-tertiary font-mono">{cur.stage}</p>
              </div>

              <div className="mb-4">
                <div className="flex items-baseline justify-between">
                  <label className="block text-xs text-secondary">
                    样例（在 data/samples/ 下扫描，选任意一条）
                  </label>
                  <button
                    type="button"
                    onClick={onUploadClick}
                    disabled={uploading}
                    className="se-btn-ghost text-xs"
                  >
                    {uploading ? "上传中…" : "＋ 上传新样例"}
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="video/mp4,video/quicktime,video/webm"
                    className="hidden"
                    onChange={onUploadFile}
                  />
                </div>
                <select
                  className="mt-1 w-full rounded-md border border-border bg-subtle px-3 py-2 font-mono text-sm"
                  value={fixture}
                  onChange={(e) => setFixture(e.target.value)}
                  disabled={samples.length === 0}
                >
                  {samples.length === 0 ? (
                    <option value="">尚无样例 · 点上方上传新样例</option>
                  ) : (
                    samples.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.id}
                        {!s.has_normalized && s.has_source ? "（仅 source.mp4）" : ""}
                      </option>
                    ))
                  )}
                </select>
                {fixtureMeta && !fixtureRunnable ? (
                  <p className="mt-1 text-xs text-warning">
                    该样例缺 normalized.mp4——请在样例页重新触发 ingest。
                  </p>
                ) : null}
              </div>

              <div className="mb-4">
                <div className="text-xs text-secondary">指标基线</div>
                <pre className="mt-1 max-h-48 overflow-auto rounded-md border border-border bg-subtle px-3 py-2 font-mono text-xs">
                  {baseline != null
                    ? JSON.stringify(baseline, null, 2)
                    : "尚未录入基线"}
                </pre>
              </div>

              <label className="mb-4 flex items-center gap-2 text-xs text-secondary">
                <input
                  type="checkbox"
                  checked={forceRefresh}
                  onChange={(e) => setForceRefresh(e.target.checked)}
                />
                <span>
                  强制重抽帧（清掉 <code className="font-mono">data/samples/{fixture || "{sample_id}"}/extracted/</code>）
                </span>
              </label>

              <button
                type="button"
                disabled={running || !fixture || !fixtureRunnable}
                onClick={onRun}
                className="se-btn-primary"
              >
                {running ? "启动中…" : "跑此子能力"}
              </button>
            </>
          ) : (
            <p className="text-sm text-secondary">请选择一个子能力。</p>
          )}
        </section>
      </div>
    </div>
  );
};
