import React from "react";
import get from "lodash/get.js";
import { Tree, type TreeApi } from "react-arborist";
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

  // The currently "pinned" leaf path — click any leaf row to mirror its
  // full value into the detail strip at the bottom of the pane. We store
  // only the path (not a snapshot of the value): the strip re-resolves via
  // lodash.get on every render, so streaming events that rewrite the
  // pinned field keep the strip in sync without an extra subscription.
  const [pinnedPath, setPinnedPath] = React.useState<{
    path: string;
    name: string;
  } | null>(null);
  // Reading lodash paths with bracketed indices is tolerated by ``get``:
  // ``captions[0].reasoning`` resolves the same as ``captions.0.reasoning``.
  const pinnedValueRaw = pinnedPath ? get(ir, pinnedPath.path) : undefined;
  const pinnedValueText =
    pinnedValueRaw === undefined
      ? null
      : typeof pinnedValueRaw === "string"
      ? pinnedValueRaw
      : JSON.stringify(pinnedValueRaw, null, 2);

  // Pick the IR-type label from the most recent event so 1A subcap runs
  // show "Phase1AReport" while 1B/2 runs show "TemplateIR / ProjectIR".
  // Multiple ir_types in a single task are still rendered into one snapshot
  // tree (their top-level keys don't collide in practice).
  const irTypeLabel = React.useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const t = events[i]?.ir_target?.ir_type;
      if (t) return t;
    }
    return "TemplateIR / ProjectIR";
  }, [events]);

  const root = React.useMemo<IrNode[]>(() => {
    const top = flatten(ir, "", irTypeLabel);
    return top.children && top.children.length > 0 ? top.children : [];
  }, [ir, irTypeLabel]);

  // react-arborist takes numeric width/height — measure the container so
  // the tree fills its parent regardless of viewport size. The container
  // div is always mounted (occupied by either the placeholder or the Tree)
  // so the ref attaches on first render and the observer is reliably set
  // up; the previous "early-return placeholder" branch hid the ref behind
  // a conditional, leaving the observer permanently unwired and the Tree
  // stuck at its default width.
  const treeRef = React.useRef<TreeApi<IrNode> | null>(null);
  const [irAllCollapsed, setIrAllCollapsed] = React.useState(false);

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
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-serif text-lg text-primary">
            AI 写入 IR · <span className="font-mono text-sm text-secondary">{irTypeLabel}</span>
          </h2>
          {root.length > 0 ? (
            <button
              type="button"
              onClick={() => {
                if (irAllCollapsed) {
                  treeRef.current?.openAll();
                  setIrAllCollapsed(false);
                } else {
                  treeRef.current?.closeAll();
                  setIrAllCollapsed(true);
                }
              }}
              className="shrink-0 rounded-sm border border-border bg-subtle px-2 py-0.5 font-mono text-[11px] text-secondary hover:text-primary"
            >
              {irAllCollapsed ? "展开全部" : "折叠全部"}
            </button>
          ) : null}
        </div>
        <p className="text-tertiary text-xs">点击展开/收起节点；点击叶子值查看全文；最近写入字段 800ms 高亮</p>
      </div>
      <div ref={containerRef} className="flex-1 overflow-hidden">
        {root.length === 0 ? (
          <div className="flex h-full items-center justify-center text-secondary">
            <p className="text-sm">事件流尚未写入字段…</p>
          </div>
        ) : (
          <Tree<IrNode>
            ref={treeRef}
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
              const isLeaf = !!node.data.isLeaf;
              const isPinned =
                isLeaf && pinnedPath !== null && pinnedPath.path === node.data.id;
              return (
                <div
                  style={style}
                  data-testid={isLeaf ? "ir-leaf" : "ir-branch"}
                  data-ir-path={node.data.id}
                  className={`flex items-center gap-2 px-2 text-sm ${
                    isFlash ? "se-ir-flash rounded-sm" : ""
                  } ${isPinned ? "bg-accent-subtle" : ""}`}
                  onClick={() => {
                    // Leaf rows pin to the detail strip; branch rows toggle
                    // expand. Splitting on isLeaf avoids the click being
                    // ambiguous and lets the user reliably re-open the strip
                    // by clicking the same leaf again (idempotent).
                    if (isLeaf) {
                      setPinnedPath({ path: node.data.id, name: node.data.name });
                    } else {
                      node.toggle();
                    }
                  }}
                >
                  {!isLeaf ? (
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
                    <span
                      className={`ml-2 min-w-0 flex-1 truncate text-xs ${
                        isLeaf ? "cursor-pointer text-primary" : "text-primary"
                      }`}
                    >
                      {node.data.preview}
                    </span>
                  ) : null}
                </div>
              );
            }}
          </Tree>
        )}
      </div>
      {pinnedPath ? (
        <div
          data-testid="ir-detail-strip"
          // Bottom inline detail strip — bounded by max-h so it never eats
          // the tree's screen real estate, and ``overflow-y-auto`` lets very
          // long strings scroll within the strip rather than push the tree
          // off-screen.
          className="border-t border-border bg-subtle px-4 py-3"
          style={{ maxHeight: "40%", overflowY: "auto" }}
        >
          <div className="mb-2 flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="font-mono text-[11px] text-tertiary break-all">
                {pinnedPath.path}
              </p>
              <p className="font-mono text-xs text-secondary">{pinnedPath.name}</p>
            </div>
            <button
              type="button"
              data-testid="ir-detail-close"
              onClick={() => setPinnedPath(null)}
              className="se-btn-ghost shrink-0 text-[11px]"
            >
              关闭
            </button>
          </div>
          {pinnedValueText === null ? (
            <p className="text-xs italic text-tertiary">字段不存在或已被移除。</p>
          ) : (
            <p
              data-testid="ir-detail-value"
              className="whitespace-pre-wrap break-words text-xs text-primary"
            >
              {pinnedValueText}
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
};
