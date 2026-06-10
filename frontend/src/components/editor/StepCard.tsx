import React from "react";

/**
 * StepCard — reusable step container for linear flows (Editor / SampleExtract).
 *
 * Visual language follows PLAN 257-318: bg-surface + border-default +
 * radius-md, no shadow (borders carry the layering). A small circular
 * step-number badge in the header replaces the visual noise of headings
 * floating in dead space. Status drives badge color only — a deliberate
 * choice over coloring the whole card so cards stay restrained even
 * when a flow is mid-progress.
 */
type Status = "pending" | "active" | "done";

interface Props {
  step: number;
  title: string;
  status?: Status;
  /** Right-aligned slot for a status pill ("已完成" / "处理中" / counters). */
  meta?: React.ReactNode;
  children: React.ReactNode;
  /** Extra classes appended to the outer <section>. */
  className?: string;
}

function badgeClasses(_status: Status): string {
  return "bg-accent-subtle text-accent-primary border-accent-primary";
}

export const StepCard: React.FC<Props> = ({
  step,
  title,
  status = "pending",
  meta,
  children,
  className,
}) => (
  <section
    className={`rounded-md border border-border bg-surface p-6 ${className ?? ""}`}
  >
    <header className="flex items-center justify-between gap-3 mb-4">
      <div className="flex items-center gap-3">
        <span
          className={`flex h-7 w-7 items-center justify-center rounded-full border text-sm font-mono ${badgeClasses(
            status,
          )}`}
        >
          {step}
        </span>
        <h2 className="font-serif text-lg text-primary">{title}</h2>
      </div>
      {meta ? <div className="text-xs text-secondary">{meta}</div> : null}
    </header>
    {children}
  </section>
);
