import React from "react";
import { useNavigate } from "react-router-dom";
import {
  getBaseline,
  listSubcaps,
  runSubcap,
  type SubcapDef,
} from "../api/lab.js";

/**
 * Phase 1A SubcapabilityLab — pick a fixture × subcap, fire a single
 * detection run, jump to the workbench. Dev-only: ``main.tsx`` guards
 * the route on ``import.meta.env.DEV`` so production builds 404.
 */
export const SubcapabilityLab: React.FC = () => {
  const navigate = useNavigate();
  const [subcaps, setSubcaps] = React.useState<SubcapDef[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [fixture, setFixture] = React.useState<string>("");
  const [baseline, setBaseline] = React.useState<unknown>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [running, setRunning] = React.useState(false);
  const [forceRefresh, setForceRefresh] = React.useState(false);

  React.useEffect(() => {
    listSubcaps()
      .then((items) => {
        setSubcaps(items);
        if (items.length) {
          setSelected(items[0].name);
          setFixture(items[0].fixtures[0] ?? "");
        }
      })
      .catch((err) => {
        setError(
          err?.response?.status === 403
            ? "ENABLE_DEV_MOCK 未启用——在 .env 设 ENABLE_DEV_MOCK=true 后可用。"
            : "无法加载子能力列表。",
        );
      });
  }, []);

  React.useEffect(() => {
    if (!selected) return;
    getBaseline(selected)
      .then(setBaseline)
      .catch(() => setBaseline(null));
  }, [selected]);

  const cur = subcaps.find((s) => s.name === selected) ?? null;

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

  return (
    <div className="mx-auto max-w-[960px] px-6 py-12">
      <h1 className="font-serif text-2xl">SubcapabilityLab · 子能力单点验证</h1>
      <p className="mt-2 text-secondary text-sm">
        Phase 1A 把 11 个子能力（切点 / 字幕 / 贴纸 / 缩放 / 转场 / 蒙版 / 调色 / BGM / 字幕功能…）拆开
        独立验证。每条 fixture × 子能力一次跑，通过工作台事件流观察识别过程。
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
              onClick={() => {
                setSelected(s.name);
                setFixture(s.fixtures[0] ?? "");
              }}
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
                <label className="block text-xs text-secondary">
                  Fixture（在 data/samples/ 下需可见 normalized.mp4）
                </label>
                <select
                  className="mt-1 w-full rounded-md border border-border bg-subtle px-3 py-2 font-mono text-sm"
                  value={fixture}
                  onChange={(e) => setFixture(e.target.value)}
                >
                  {cur.fixtures.map((fid) => (
                    <option key={fid} value={fid}>
                      {fid}
                    </option>
                  ))}
                </select>
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
                  强制重抽帧（清掉 <code className="font-mono">data/samples/{fixture || "{fixture}"}/extracted/</code>）
                </span>
              </label>

              <button
                type="button"
                disabled={running || !fixture}
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
