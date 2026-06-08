import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EventBadge, badgeColor } from "./EventBadge.js";

describe("badgeColor", () => {
  it("maps 1A.* stages to the 1A color", () => {
    expect(badgeColor("1A.captions")).toBe("var(--stage-1a)");
    expect(badgeColor("1A.stickers")).toBe("var(--stage-1a)");
  });

  it("distinguishes 2.5.* from 2.*", () => {
    expect(badgeColor("2.5.nl_edit")).toBe("var(--stage-25)");
    expect(badgeColor("2.recommend")).toBe("var(--stage-2)");
  });

  it("falls back to the system color for unknown prefixes", () => {
    expect(badgeColor("system.boot")).toBe("var(--stage-system)");
  });

  it("renders the stage text", () => {
    render(<EventBadge stage="1A.captions" />);
    const el = screen.getByTestId("event-badge");
    expect(el).toHaveTextContent("1A.captions");
    expect(el).toHaveAttribute("data-stage", "1A.captions");
  });
});
