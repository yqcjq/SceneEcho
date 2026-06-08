import React from "react";

/**
 * Stage-prefix badge. Color comes from CSS variables in tokens.css so the
 * mapping is one place — Tailwind classes here would scatter the rule.
 */
const STAGE_COLOR: Array<[RegExp, string, string]> = [
  [/^0\.5\./, "var(--stage-mock)", "Mock"],
  [/^1A\./, "var(--stage-1a)", "1A"],
  [/^1B\./, "var(--stage-1b)", "1B"],
  [/^2\.5\./, "var(--stage-25)", "2.5"],
  [/^2\./, "var(--stage-2)", "2"],
  [/^3\./, "var(--stage-3)", "3"],
  [/^4\./, "var(--stage-4)", "4"],
  [/^5\./, "var(--stage-5)", "5"],
];

const SYSTEM_COLOR = "var(--stage-system)";

export interface EventBadgeProps {
  stage: string;
}

export function badgeColor(stage: string): string {
  for (const [pattern, color] of STAGE_COLOR) {
    if (pattern.test(stage)) return color;
  }
  return SYSTEM_COLOR;
}

export const EventBadge: React.FC<EventBadgeProps> = ({ stage }) => {
  const color = badgeColor(stage);
  return (
    <span
      data-testid="event-badge"
      data-stage={stage}
      className="inline-flex items-center rounded-sm px-2 py-0.5 text-[11px] font-mono uppercase tracking-wide"
      style={{
        backgroundColor: color,
        color: "var(--text-inverted)",
      }}
    >
      {stage}
    </span>
  );
};
