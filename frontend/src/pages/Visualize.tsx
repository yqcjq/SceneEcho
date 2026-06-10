import React from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  fetchReplayEvents,
  fetchReplayEventsForSample,
  type ReplayEvent,
  type ReplayEventsResponse,
} from "../api/index.js";
import { WorkbenchEventStream } from "../components/workbench/WorkbenchEventStream.js";
import { WorkbenchIRPane } from "../components/workbench/WorkbenchIRPane.js";
import { WorkbenchVisionPane } from "../components/workbench/WorkbenchVisionPane.js";
import { useWorkbenchStore } from "../state/workbench.js";
import type { VisionEvent } from "../types/workbench.js";

/**
 * Visualize page (Phase 2.5, PLAN 1713-1718).
 *
 * Address by ``/projects/:id/replay`` (default → latest task) or
 * ``/samples/:id/replay`` (extract replays). Loads the entire events
 * jsonl via ``GET /replay/events``, then animates the workbench three
 * panes by replaying ``appendEvent`` calls in sequence order at the
 * chosen playback speed.
 *
 * Why reuse the workbench panes verbatim instead of building a parallel
 * "history" UI: keeping a single rendering pipeline ensures recordings
 * captured here look identical to what the user saw in the live
 * workbench — that's the whole point of "replay as demo录屏" (PLAN 1717).
 */
type ReplayParams =
  | { projectId: string; sampleId?: undefined }
  | { sampleId: string; projectId?: undefined };

const SPEEDS: number[] = [0.5, 1, 2, 4];

export const Visualize: React.FC = () => {
  const params = useParams<{ projectId?: string; sampleId?: string }>();
  const [search] = useSearchParams();

  const projectId = params.projectId;
  const sampleId = params.sampleId;
  const explicitTask = search.get("task_id");

  const reset = useWorkbenchStore((s) => s.reset);
  const appendEvent = useWorkbenchStore((s) => s.appendEvent);

  const [data, setData] = React.useState<ReplayEventsResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [cursor, setCursor] = React.useState(0); // index into events
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState(1);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const [recording, setRecording] = React.useState(false);
  const captureRegionRef = React.useRef<HTMLDivElement>(null);

  const load = React.useCallback(async () => {
    setError(null);
    setData(null);
    try {
      const r = projectId
        ? await fetchReplayEvents(projectId, explicitTask ?? undefined)
        : await fetchReplayEventsForSample(sampleId!, explicitTask ?? undefined);
      setData(r);
      reset(r.task_id);
      setCursor(0);
    } catch (e: any) {
      setError(String(e?.response?.data?.detail ?? e?.message ?? e));
    }
  }, [projectId, sampleId, explicitTask, reset]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Drive the timeline. Each tick we feed the next event into the
  // workbench store. Wall-clock per event = 1s / speed by default; we
  // could use event.timestamp gaps for true-time-replay but that gives
  // multi-minute idles on slow LLM calls — uniform pacing matches what
  // the user wants for "scroll through what happened" demo replays.
  React.useEffect(() => {
    if (!playing || !data) return;
    if (cursor >= data.events.length) {
      setPlaying(false);
      return;
    }
    const next = data.events[cursor];
    appendEvent(toVisionEvent(next));
    const delay = Math.max(60, 600 / speed);
    const timer = window.setTimeout(() => setCursor((c) => c + 1), delay);
    return () => window.clearTimeout(timer);
  }, [playing, cursor, data, appendEvent, speed]);

  // Scrub: jumping the cursor manually re-flushes events from the
  // beginning up to the new position. ``reset`` clears the workbench
  // store; we then bulk-append (synchronous loop) so the panes settle
  // before the next paint.
  const scrubTo = (newCursor: number) => {
    if (!data) return;
    setPlaying(false);
    reset(data.task_id);
    for (let i = 0; i < newCursor; i++) {
      appendEvent(toVisionEvent(data.events[i]));
    }
    setCursor(newCursor);
  };

  const startRecording = async () => {
    if (!captureRegionRef.current) return;
    if (!("MediaRecorder" in window)) {
      alert("此浏览器不支持 MediaRecorder。请用 Chrome / Edge / Firefox。");
      return;
    }
    try {
      // Safari rejects video/webm in MediaRecorder.isTypeSupported —
      // surface the limitation rather than swallow a TypeError.
      if (!MediaRecorder.isTypeSupported("video/webm;codecs=vp9")) {
        alert("当前浏览器不支持 webm/vp9 录制（Safari 不兼容）。请改用 Chrome / Edge / Firefox。");
        return;
      }
      // Capture the visible region via getDisplayMedia → user picks
      // which surface (the page / a tab) to record. Recording the
      // captureRegion via captureStream would limit to <canvas>
      // elements, which we don't use here.
      const stream = await (navigator.mediaDevices as any).getDisplayMedia({
        video: { displaySurface: "browser" },
      });
      const recorder = new MediaRecorder(stream, { mimeType: "video/webm;codecs=vp9" });
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: "video/webm" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `workbench_replay_${Date.now()}.webm`;
        a.click();
        URL.revokeObjectURL(url);
        stream.getTracks().forEach((t: MediaStreamTrack) => t.stop());
        setRecording(false);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      // Auto-stop after 60 seconds (PLAN 1717 specifies 30-60s).
      window.setTimeout(() => {
        if (recorder.state !== "inactive") recorder.stop();
      }, 60_000);
    } catch (e: any) {
      alert(`录屏失败：${e?.message ?? e}`);
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
  };

  if (error) {
    return (
      <div className="mx-auto max-w-[640px] px-6 py-12 text-center">
        <h1 className="font-serif text-2xl">事件回放</h1>
        <p className="mt-2 text-error">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="mx-auto max-w-[640px] px-6 py-12 text-center">
        <h1 className="font-serif text-2xl">事件回放</h1>
        <p className="mt-2 text-secondary">读取中…</p>
      </div>
    );
  }

  const total = data.events.length;
  const pct = total > 0 ? Math.round((cursor / total) * 100) : 0;

  return (
    <div className="flex h-[calc(100vh-65px)] flex-col">
      <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
        <div>
          <h1 className="font-serif text-lg text-primary">事件回放器</h1>
          <p className="text-tertiary text-xs font-mono">
            task #{data.task_id.slice(0, 12)} · {data.task.kind ?? "?"} · {total} 事件
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1 hover:bg-canvas"
            onClick={() => setPlaying((p) => !p)}
          >
            {playing ? "⏸ 暂停" : "▶ 播放"}
          </button>
          <div className="flex items-center gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                className={`rounded border px-2 py-1 ${
                  speed === s ? "border-accent-primary bg-accent-subtle" : "border-border"
                }`}
              >
                {s}×
              </button>
            ))}
          </div>
          {recording ? (
            <button
              type="button"
              className="rounded-md bg-error px-3 py-1 text-inverted"
              onClick={stopRecording}
            >
              ⏹ 停止录屏
            </button>
          ) : (
            <button
              type="button"
              className="rounded-md border border-border px-3 py-1 hover:bg-canvas"
              onClick={startRecording}
            >
              ● 导出录屏 (webm)
            </button>
          )}
          <Link
            to={`/workbench/${data.task_id}`}
            className="text-accent-primary hover:underline"
          >
            打开实时工作台 →
          </Link>
        </div>
      </div>

      <div className="border-b border-border bg-surface px-6 py-2">
        <input
          type="range"
          min={0}
          max={total}
          value={cursor}
          onChange={(e) => scrubTo(parseInt(e.target.value, 10))}
          className="w-full"
        />
        <div className="flex items-center justify-between text-xs text-tertiary">
          <span>0</span>
          <span>{cursor} / {total} ({pct}%)</span>
          <span>{total}</span>
        </div>
      </div>

      <div
        ref={captureRegionRef}
        className="grid flex-1 overflow-hidden border-t border-border md:grid-cols-3 md:grid-rows-1"
      >
        <div className="border-r border-border">
          <WorkbenchVisionPane videoUrl={null} />
        </div>
        <div className="border-r border-border">
          <WorkbenchEventStream />
        </div>
        <div>
          <WorkbenchIRPane />
        </div>
      </div>
    </div>
  );
};

/** Coerce ReplayEvent (server shape) into the local VisionEvent type. */
function toVisionEvent(ev: ReplayEvent): VisionEvent {
  return {
    event_id: ev.event_id,
    task_id: ev.task_id,
    sequence: ev.sequence,
    timestamp: ev.timestamp,
    duration_ms: ev.duration_ms,
    source: ev.source as any,
    model_used: ev.model_used ?? undefined,
    stage: ev.stage,
    frame_ts: ev.frame_ts ?? undefined,
    frame_url: ev.frame_url ?? undefined,
    bbox_norm: ev.bbox_norm ?? undefined,
    semantic_label: ev.semantic_label,
    reasoning: ev.reasoning,
    confidence: ev.confidence,
    ir_target: ev.ir_target as any,
    ir_value: ev.ir_value,
    parent_event_id: ev.parent_event_id ?? undefined,
    cost_tokens: ev.cost_tokens ?? undefined,
    severity: (ev.severity ?? "info") as any,
    confidence_warning: ev.confidence_warning ?? false,
  } as VisionEvent;
}
