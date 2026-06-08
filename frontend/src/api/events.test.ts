/**
 * Tests for the SSE subscription helper.
 *
 * We swap in a fake EventSource so the test owns timing — no real network,
 * no waiting for browser internals.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { subscribeEvents } from "./events.js";
import type { VisionEvent } from "../types/workbench.js";

class FakeEventSource {
  static lastInstance: FakeEventSource | null = null;
  url: string;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: ((e: Event) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.lastInstance = this;
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }

  removeEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== fn);
  }

  dispatch(type: string, data: unknown) {
    const evt = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const l of this.listeners[type] ?? []) l(evt);
  }

  close() {
    this.closed = true;
  }
}

const sampleEvent: VisionEvent = {
  event_id: "ev_1",
  task_id: "t1",
  sequence: 1,
  timestamp: "2026-06-08T00:00:00.000+00:00",
  duration_ms: 0,
  source: "vlm",
  model_used: "qwen-vl-max-latest",
  stage: "0.5.mock.captions_demo",
  frame_ts: null,
  frame_url: null,
  bbox_norm: null,
  semantic_label: "test",
  reasoning: "",
  confidence: 1,
  ir_target: null,
  ir_value: null,
  parent_event_id: null,
  cost_tokens: null,
  confidence_warning: false,
  severity: "info",
};

describe("subscribeEvents", () => {
  let originalES: typeof EventSource;
  beforeEach(() => {
    originalES = globalThis.EventSource;
    // @ts-expect-error swapping in fake
    globalThis.EventSource = FakeEventSource;
  });
  afterEach(() => {
    globalThis.EventSource = originalES;
    FakeEventSource.lastInstance = null;
  });

  it("forwards parsed vision events to onEvent", () => {
    const onEvent = vi.fn();
    const teardown = subscribeEvents("t1", { onEvent });
    const inst = FakeEventSource.lastInstance!;
    inst.dispatch("vision", sampleEvent);
    expect(onEvent).toHaveBeenCalledWith(sampleEvent);
    teardown();
  });

  it("calls onDone and closes when 'done' arrives", () => {
    const onDone = vi.fn();
    const teardown = subscribeEvents("t1", { onEvent: () => {}, onDone });
    const inst = FakeEventSource.lastInstance!;
    inst.dispatch("done", {});
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(inst.closed).toBe(true);
    teardown();
  });

  it("teardown closes the underlying EventSource", () => {
    const teardown = subscribeEvents("t1", { onEvent: () => {} });
    const inst = FakeEventSource.lastInstance!;
    teardown();
    expect(inst.closed).toBe(true);
  });

  it("URL-encodes the task id", () => {
    const teardown = subscribeEvents("task with spaces", { onEvent: () => {} });
    const inst = FakeEventSource.lastInstance!;
    expect(inst.url).toBe("/api/tasks/task%20with%20spaces/events");
    teardown();
  });
});
