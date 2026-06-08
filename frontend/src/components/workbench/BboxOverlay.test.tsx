import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { BboxOverlay, bboxToRect } from "./BboxOverlay.js";

describe("bboxToRect", () => {
  it("maps 0-999 normalized coordinates to pixels", () => {
    // bbox center-ish on a 1080x1920 frame
    const r = bboxToRect([500, 500, 200, 200], 1080, 1920);
    expect(r.x).toBeCloseTo(540, 5);
    expect(r.y).toBeCloseTo(960, 5);
    expect(r.width).toBeCloseTo(216, 5);
    expect(r.height).toBeCloseTo(384, 5);
  });

  it("handles full-frame bbox", () => {
    const r = bboxToRect([0, 0, 999, 999], 1080, 1920);
    expect(r.x).toBe(0);
    expect(r.y).toBe(0);
    expect(r.width).toBeCloseTo(1078.92);
    expect(r.height).toBeCloseTo(1918.08);
  });
});

describe("BboxOverlay component", () => {
  it("renders an SVG rect at the right pixel coords", () => {
    const { container, getByTestId } = render(
      <div style={{ position: "relative", width: 1080, height: 1920 }}>
        <BboxOverlay
          frameWidth={1080}
          frameHeight={1920}
          bbox={[500, 500, 200, 200]}
          label="测试"
        />
      </div>,
    );
    const svg = getByTestId("bbox-overlay");
    expect(svg).toBeInTheDocument();
    const rect = container.querySelector("rect.se-bbox");
    expect(rect).not.toBeNull();
    expect(rect?.getAttribute("data-rect-x")).toBe("540");
    expect(rect?.getAttribute("data-rect-y")).toBe("960");
  });
});
