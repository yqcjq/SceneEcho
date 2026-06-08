import React from "react";
import { Tree } from "react-arborist";
import { useWorkbenchStore } from "../../state/workbench.js";

interface IrNode {
  id: string;
  name: string;
  preview?: string;
  isLeaf?: boolean;
  children?: IrNode[];
}

const VALUE_PREVIEW_LIMIT = 60;

function flatten(value: unknown, path: string, name: string): IrNode {
  if (value === null || value === undefined) {
    return { id: path, name, preview: String(value), isLeaf: true };
  }
  if (typeof value !== "object") {
    const text = String(value);
    return {
      id: path,
      name,
      preview:
        text.length > VALUE_PREVIEW_LIMIT
          ? `${text.slice(0, VALUE_PREVIEW_LIMIT)}…`
          : text,
      isLeaf: true,
    };
  }
  if (Array.isArray(value)) {
    return {
      id: path,
      name: `${name} [${value.length}]`,
      children: value.map((v, i) => flatten(v, `${path}[${i}]`, `[${i}]`)),
    };
  }
  const obj = value as Record<string, unknown>;
  const entries = Object.entries(obj);
  return {
    id: path,
    name,
    children: entries.map(([k, v]) =>
      flatten(v, path ? `${path}.${k}` : k, k),
    ),
  };
}

export const WorkbenchIRPane: React.FC = () => {
  const ir = useWorkbenchStore((s) => s.irSnapshot);
  const events = useWorkbenchStore((s) => s.events);
  const lastEvent = events[events.length - 1];
  // Resolve the full lodash path the last event wrote (path + field), the
  // same way the store's writeIr() does. Flashing on bare ``path`` would
  // miss writes that target a subfield.
  const flashPath = lastEvent?.ir_target
    ? lastEvent.ir_target.field
      ? `${lastEvent.ir_target.path}.${lastEvent.ir_target.field}`
      : lastEvent.ir_target.path
    : null;

  const root = React.useMemo<IrNode[]>(() => {
    const top = flatten(ir, "", "TemplateIR / ProjectIR");
    return top.children && top.children.length > 0 ? top.children : [];
  }, [ir]);

  // react-arborist takes numeric width/height — measure the container so
  // the tree fills its parent regardless of viewport size. The container
  // div is always mounted (occupied by either the placeholder or the Tree)
  // so the ref attaches on first render and the observer is reliably set
  // up; the previous "early-return placeholder" branch hid the ref behind
  // a conditional, leaving the observer permanently unwired and the Tree
  // stuck at its default width.
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [size, setSize] = React.useState<{ w: number; h: number }>({
    w: 360,
    h: 600,
  });
  React.useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // Synchronous initial measurement before paint avoids one frame of the
    // 360×600 default flashing before ResizeObserver fires.
    const r0 = el.getBoundingClientRect();
    if (r0.width > 0 && r0.height > 0) {
      setSize({ w: r0.width, h: r0.height });
    }
    const observer = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) setSize({ w: Math.max(80, r.width), h: Math.max(80, r.height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3">
        <h2 className="font-serif text-lg text-primary">VLM 决定写入 IR</h2>
        <p className="text-tertiary text-xs">点击节点展开；最近写入字段 800ms 高亮</p>
      </div>
      <div ref={containerRef} className="flex-1 overflow-hidden">
        {root.length === 0 ? (
          <div className="flex h-full items-center justify-center text-secondary">
            <p className="text-sm">事件流尚未写入字段…</p>
          </div>
        ) : (
          <Tree<IrNode>
            data={root}
            openByDefault
            rowHeight={26}
            width={size.w}
            height={size.h}
            padding={8}
            indent={18}
          >
            {({ node, style }) => {
              const isFlash = flashPath !== null && node.data.id === flashPath;
              return (
                <div
                  style={style}
                  className={`flex items-center gap-2 px-2 text-sm ${isFlash ? "se-ir-flash rounded-sm" : ""}`}
                  onClick={() => node.toggle()}
                >
                  {!node.data.isLeaf ? (
                    <span className="text-tertiary text-xs w-3 shrink-0">
                      {node.isOpen ? "▾" : "▸"}
                    </span>
                  ) : (
                    <span className="w-3 shrink-0" />
                  )}
                  <span className="font-mono text-xs text-secondary shrink-0">
                    {node.data.name}
                  </span>
                  {node.data.preview ? (
                    // min-w-0 + flex-1 lets `truncate` actually clip — without
                    // min-w-0 a flex item's min-width is `auto` (= content
                    // width), so the row grows past the tree's rendered width
                    // and react-arborist falls back to horizontal scroll.
                    <span className="ml-2 min-w-0 flex-1 truncate text-xs text-primary">
                      {node.data.preview}
                    </span>
                  ) : null}
                </div>
              );
            }}
          </Tree>
        )}
      </div>
    </div>
  );
};
