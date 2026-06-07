import pino from "pino";

export const logger = pino({
  level: process.env.LOG_LEVEL?.toLowerCase() ?? "info",
  base: { service: "renderer" },
});

export function withTask(taskId: string) {
  return logger.child({ task_id: taskId });
}
