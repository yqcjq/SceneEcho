import React, { useEffect, useState } from "react";
import { pollTask, TaskStatus } from "../api/index.js";

interface Props {
  taskId: string;
  onComplete?: (t: TaskStatus) => void;
}

export const TaskProgress: React.FC<Props> = ({ taskId, onComplete }) => {
  const [task, setTask] = useState<TaskStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const t = await pollTask(taskId);
        if (cancelled) return;
        setTask(t);
        if (t.status === "completed" || t.status === "failed") {
          onComplete?.(t);
          return;
        }
      } catch {
        // ignore; will retry
      }
      timer = setTimeout(tick, 1000);
    };
    void tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, onComplete]);

  if (!task) return <div>任务 {taskId}：连接中…</div>;
  const pct = Math.round((task.progress ?? 0) * 100);
  return (
    <div style={{ marginTop: 12 }}>
      <div>
        任务 <code>{task.id}</code> · 状态 <b>{task.status}</b> · 阶段 {task.stage || "-"}
      </div>
      <div style={{ background: "#eee", height: 12, borderRadius: 6, marginTop: 6 }}>
        <div
          style={{
            width: `${pct}%`,
            background: task.status === "failed" ? "#c33" : "#3a7",
            height: "100%",
            borderRadius: 6,
            transition: "width 0.3s",
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: "#666" }}>{pct}%</div>
      {task.error && <div style={{ color: "#c33" }}>错误：{task.error}</div>}
    </div>
  );
};
