import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { dataUrl, renderDemo, triggerExtract, uploadSample } from "../api/index.js";
import { ExtractHistoryList } from "../components/ExtractHistoryList.js";
import { StepCard } from "../components/editor/StepCard.js";
import { TaskProgress } from "../components/TaskProgress.js";

/**
 * Phase 1B extension (PLAN 1552):
 * After upload, display sample basic info (duration / streams).
 * Add an "提取模板" button → calls POST /samples/{id}/extract → navigates
 * the user to the workbench so they can watch the DAG run end-to-end.
 *
 * Phase 2.5 二核: pages use ``StepCard`` for visual parity with Editor —
 * upload / extract / history all three sections become numbered cards
 * so the user sees the flow as a guided document, not naked text.
 * Also accepts ``?sample_id=`` so the workbench breadcrumb's "样例" link
 * can deep-link back into a specific sample's extract history without
 * forcing the user to re-upload (PLAN 1736).
 */
export const SampleExtract: React.FC = () => {
  const [search] = useSearchParams();
  const urlSampleId = search.get("sample_id");
  const [sampleId, setSampleId] = useState<string | null>(urlSampleId);
  const [sampleInfo, setSampleInfo] = useState<any | null>(null);
  const [renderTaskId, setRenderTaskId] = useState<string | null>(null);
  const [extractTaskId, setExtractTaskId] = useState<string | null>(null);
  const [outputPath, setOutputPath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setBusy(true);
    setOutputPath(null);
    try {
      const r = await uploadSample(file);
      setSampleId(r.sample_id);
      setSampleInfo(r.info);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    } finally {
      setBusy(false);
    }
  };

  const onRender = async () => {
    if (!sampleId) return;
    setError(null);
    setOutputPath(null);
    try {
      const r = await renderDemo(sampleId);
      setRenderTaskId(r.task_id);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  };

  const onExtract = async () => {
    if (!sampleId) return;
    setError(null);
    try {
      const r = await triggerExtract(sampleId);
      setExtractTaskId(r.task_id);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  };

  // Pluck a quick summary from the ffprobe-style info blob.
  const videoStream = sampleInfo?.streams?.find((s: any) => s.codec_type === "video");
  const durationSec = parseFloat(sampleInfo?.format?.duration ?? "0");

  const step1Status = sampleId ? "done" : "active";
  const step2Status = !sampleId ? "pending" : extractTaskId ? "done" : "active";

  return (
    <div className="mx-auto max-w-[1180px] px-6 py-12">
      <header className="mb-8">
        <h1 className="font-serif text-2xl">SceneEcho · 阶段 1B 模板提取</h1>
        <p className="text-secondary text-sm mt-1">
          上传 5–20s 样例 → 「提取模板」启动 Phase 1B pipeline → 工作台实时观察全链路 AI 决策 → 完成后入 KB。
        </p>
      </header>

      <div className="space-y-6">
        <StepCard
          step={1}
          title="上传样例"
          status={step1Status}
          meta={sampleId ? <code className="font-mono">{sampleId}</code> : null}
        >
          <input
            type="file"
            accept="video/mp4,video/quicktime,video/webm"
            onChange={onUpload}
            disabled={busy}
          />
          {busy && <span className="ml-3 text-secondary text-sm">上传中…</span>}
          {sampleInfo && (
            <div className="mt-3 text-sm text-secondary">
              时长 {durationSec.toFixed(1)}s
              {videoStream
                ? ` · ${videoStream.width}×${videoStream.height}@${videoStream.r_frame_rate}`
                : ""}
            </div>
          )}
        </StepCard>

        {sampleId && (
          <StepCard
            step={2}
            title="提取模板"
            status={step2Status}
            meta={
              extractTaskId ? (
                <Link
                  to={`/workbench/${extractTaskId}`}
                  className="text-accent-primary hover:underline"
                >
                  AI 工作台 #{extractTaskId.slice(0, 8)} →
                </Link>
              ) : null
            }
          >
            <p className="text-secondary text-sm mb-3">
              Phase 1B pipeline 跑 7+ 个视觉子能力 → 抽取骨架与样式 → 入模板库。
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onExtract}
                disabled={!!extractTaskId}
                className="rounded-md bg-accent-primary px-3 py-1.5 text-sm text-inverted hover:bg-accent-hover disabled:opacity-50"
              >
                提取模板（Phase 1B）
              </button>
              <button
                type="button"
                onClick={onRender}
                disabled={!!renderTaskId && !outputPath}
                className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent-primary"
              >
                渲染 demo
              </button>
              <Link
                to="/templates"
                className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent-primary"
              >
                模板库
              </Link>
              {import.meta.env.DEV && (
                <Link
                  to="/lab"
                  className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent-primary"
                >
                  SubcapabilityLab
                </Link>
              )}
            </div>
            {extractTaskId && (
              <div className="mt-4 rounded-md border border-warning bg-subtle px-3 py-2 text-sm text-primary">
                正在提取模板，<Link to={`/workbench/${extractTaskId}`} className="text-accent-primary hover:underline">打开 AI 工作台</Link>{" "}
                看 VLM/CV 全链路。完成后会进入模板库。
              </div>
            )}
            {renderTaskId && (
              <div className="mt-4">
                <TaskProgress
                  taskId={renderTaskId}
                  onComplete={(t) => {
                    if (t.status === "completed" && t.result?.output_path) {
                      setOutputPath(t.result.output_path);
                    } else if (t.status === "failed") {
                      setError(t.error ?? "render failed");
                    }
                  }}
                />
              </div>
            )}
            {outputPath && (
              <div className="mt-4">
                <div className="text-sm">输出：<code className="text-secondary">{outputPath}</code></div>
                <video src={dataUrl(outputPath)} controls style={{ width: "100%", maxWidth: 480, marginTop: 8, borderRadius: 4 }} />
              </div>
            )}
          </StepCard>
        )}

        {sampleId && (
          <StepCard
            step={3}
            title="提取历史"
            status="pending"
            meta={<span className="text-tertiary">点击行可重开工作台</span>}
          >
            <ExtractHistoryList
              resourceKind="sample"
              resourceId={sampleId}
              emptyHint={
                <span className="text-tertiary text-sm">
                  尚无提取任务。点击「提取模板」开始。
                </span>
              }
            />
          </StepCard>
        )}

        {error && (
          <div className="rounded-md border border-error bg-surface px-4 py-3 text-sm text-error">
            错误：{error}
          </div>
        )}
      </div>
    </div>
  );
};
