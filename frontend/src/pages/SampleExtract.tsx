import React, { useState } from "react";
import { dataUrl, renderDemo, uploadSample } from "../api/index.js";
import { TaskProgress } from "../components/TaskProgress.js";

export const SampleExtract: React.FC = () => {
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
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
      setTaskId(r.task_id);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: "40px auto", fontFamily: "system-ui, sans-serif" }}>
      <h1>SceneEcho · 阶段 0 渲染 Demo</h1>
      <p style={{ color: "#666" }}>
        上传一段 mp4 → 后端归一化 → 点"渲染 demo" → Node Remotion 出片，叠加 "Hello SceneEcho" 字幕。
      </p>

      <div style={{ marginTop: 16 }}>
        <input type="file" accept="video/mp4,video/quicktime,video/webm" onChange={onUpload} disabled={busy} />
        {busy && <span style={{ marginLeft: 12 }}>上传中…</span>}
      </div>

      {sampleId && (
        <div style={{ marginTop: 16 }}>
          <div>样例 ID：<code>{sampleId}</code></div>
          <button onClick={onRender} style={{ marginTop: 8 }} disabled={!!taskId && !outputPath}>
            渲染 demo
          </button>
        </div>
      )}

      {taskId && (
        <TaskProgress
          taskId={taskId}
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

      {error && <div style={{ color: "#c33", marginTop: 16 }}>错误：{error}</div>}
    </div>
  );
};
