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
  // the tree fills its parent regardless of viewport size.
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [size, setSize] = React.useState<{ w: number; h: number }>({
    w: 360,
    h: 600,
  });
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) setSize({ w: Math.max(80, r.width), h: Math.max(80, r.height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (root.length === 0) {
    return (
      <div className="flex h-full items-center justify-center bg-subtle text-secondary">
        <div className="text-center">
          <p className="font-serif text-base text-primary">VLM 决定写入 IR</p>
          <p className="mt-2 text-sm">事件流尚未写入字段…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3">
        <h2 className="font-serif text-lg text-primary">VLM 决定写入 IR</h2>
        <p className="text-tertiary text-xs">点击节点展开；最近写入字段 800ms 高亮</p>
      </div>
      <div ref={containerRef} className="flex-1 overflow-hidden">
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
                  <span className="text-tertiary text-xs w-3">
                    {node.isOpen ? "▾" : "▸"}
                  </span>
                ) : (
                  <span className="w-3" />
                )}
                <span className="font-mono text-xs text-secondary">
                  {node.data.name}
                </span>
                {node.data.preview ? (
                  <span className="ml-2 truncate text-xs text-primary">
                    {node.data.preview}
                  </span>
                ) : null}
              </div>
            );
          }}
        </Tree>
      </div>
    </div>
  );
};
