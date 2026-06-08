import React from "react";
import { useNavigate } from "react-router-dom";
import { listScenarios, startMockStream } from "../api/events.js";
import type { ScenarioListItem } from "../types/workbench.js";

/**
 * Dev-only entry to /workbench/{taskId}. Hidden in production builds where
 * `ENABLE_DEV_MOCK=false` causes the backend endpoint to 403.
 */
export const WorkbenchLauncher: React.FC = () => {
  const navigate = useNavigate();
  const [scenarios, setScenarios] = React.useState<ScenarioListItem[]>([]);
  const [loading, setLoading] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    listScenarios()
      .then(setScenarios)
      .catch((err) => {
        setError(
          err?.response?.status === 403
            ? "ENABLE_DEV_MOCK 未开启，工作台 dev 入口在 .env 设 ENABLE_DEV_MOCK=true 后可用。"
            : "无法加载 scenarios。",
        );
      });
  }, []);

  const onLaunch = async (scenario: string) => {
    setLoading(scenario);
    setError(null);
    try {
      const r = await startMockStream(scenario);
      navigate(r.workbench_url);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="mx-auto max-w-[820px] px-6 py-12">
      <h1 className="font-serif text-2xl">工作台 · Dev 入口</h1>
      <p className="mt-2 text-secondary text-sm">
        Phase 0.5 mock 流——后端按脚本顺序广播 VisionEvent，验证三栏页面在「无真实 VLM」时也能跑通。
      </p>

      {error ? (
        <div className="mt-6 rounded-md border border-error bg-accent-subtle px-4 py-3 text-sm text-error">
          {error}
        </div>
      ) : null}

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {scenarios.map((s) => (
          <button
            key={s.name}
            onClick={() => onLaunch(s.name)}
            disabled={loading !== null}
            className="se-card flex flex-col items-start gap-2 px-5 py-4 text-left transition-colors hover:border-strong"
          >
            <span className="font-mono text-xs text-tertiary">
              {s.event_count} 事件
            </span>
            <span className="font-serif text-base text-primary">{s.name}</span>
            <span className="text-sm text-secondary">{s.description}</span>
            {loading === s.name ? (
              <span className="text-xs text-accent">启动中…</span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
};
