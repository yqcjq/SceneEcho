import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { dataUrl, renderDemo, triggerExtract, uploadSample } from "../api/index.js";
import { ExtractHistoryList } from "../components/ExtractHistoryList.js";
import { TaskProgress } from "../components/TaskProgress.js";

/**
 * Phase 1B extension (PLAN 1552):
 * After upload, display sample basic info (duration / streams).
 * Add an "提取模板" button → calls POST /samples/{id}/extract → navigates
 * the user to the workbench so they can watch the DAG run end-to-end.
 *
 * Phase 2.5: also accepts ``?sample_id=`` so the workbench breadcrumb's
 * "样例" link can deep-link back into a specific sample's extract
 * history without forcing the user to re-upload (PLAN 1736).
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

  return (
    <div style={{ maxWidth: 720, margin: "40px auto", fontFamily: "system-ui, sans-serif" }}>
      <h1>SceneEcho · 阶段 1B 模板提取</h1>
      <p style={{ color: "#666" }}>
        上传一段 5–20s 样例 → 「提取模板」启动 Phase 1B pipeline → 工作台实时观察全链路 AI 决策 → 完成后入 KB。
      </p>

      <div style={{ marginTop: 16 }}>
        <input type="file" accept="video/mp4,video/quicktime,video/webm" onChange={onUpload} disabled={busy} />
        {busy && <span style={{ marginLeft: 12 }}>上传中…</span>}
      </div>

      {sampleId && (
        <div style={{ marginTop: 16 }}>
          <div>样例 ID：<code>{sampleId}</code></div>
          {sampleInfo && (
            <div style={{ marginTop: 8, fontSize: 13, color: "#555" }}>
              时长 {durationSec.toFixed(1)}s
              {videoStream
                ? ` · ${videoStream.width}×${videoStream.height}@${videoStream.r_frame_rate}`
                : ""}
            </div>
          )}
          <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button onClick={onExtract} disabled={!!extractTaskId}>
              提取模板（Phase 1B）
            </button>
            <button onClick={onRender} disabled={!!renderTaskId && !outputPath}>
              渲染 demo
            </button>
            {extractTaskId && (
              <Link
                to={`/workbench/${extractTaskId}`}
                style={{ padding: "4px 12px", border: "1px solid #ccc", borderRadius: 4 }}
              >
                打开 AI 工作台（提取进行中…）
              </Link>
            )}
            <Link
              to="/templates"
              style={{ padding: "4px 12px", border: "1px solid #ccc", borderRadius: 4 }}
            >
              模板库
            </Link>
            {import.meta.env.DEV && (
              <Link
                to="/lab"
                style={{ padding: "4px 12px", border: "1px solid #ccc", borderRadius: 4 }}
              >
                打开 SubcapabilityLab
              </Link>
            )}
          </div>
          {extractTaskId && (
            <div
              style={{
                marginTop: 12,
                padding: 12,
                background: "#fff7e8",
                border: "1px solid #f1cf85",
                borderRadius: 4,
                fontSize: 13,
              }}
            >
              正在提取模板，<Link to={`/workbench/${extractTaskId}`}>打开 AI 工作台</Link>{" "}
              看 VLM/CV 全链路。完成后会进入模板库。
            </div>
          )}
        </div>
      )}

      {renderTaskId && (
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
      )}

      {outputPath && (
        <div style={{ marginTop: 24 }}>
          <div>输出：<code>{outputPath}</code></div>
          <video src={dataUrl(outputPath)} controls style={{ width: "100%", marginTop: 8 }} />
        </div>
      )}

      {sampleId && (
        <section style={{ marginTop: 24 }}>
          <h3 style={{ fontSize: 14, marginBottom: 8 }}>本样例提取历史</h3>
          <ExtractHistoryList
            resourceKind="sample"
            resourceId={sampleId}
            emptyHint={
              <span style={{ color: "#999", fontSize: 13 }}>
                尚无提取任务。点击「提取模板」开始。
              </span>
            }
          />
        </section>
      )}

      {error && <div style={{ color: "#c33", marginTop: 16 }}>错误：{error}</div>}
    </div>
  );
};
