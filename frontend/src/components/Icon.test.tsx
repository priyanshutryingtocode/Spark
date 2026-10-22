import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./Icon";

const NAMES = [
  "search", "history", "compare", "swap", "arrow-right", "download",
  "trash", "alert", "info",
] as const;

describe("Icon", () => {
  it("draws every mark on the same 24-unit grid with one stroke weight", () => {
    for (const name of NAMES) {
      const { container, unmount } = render(<Icon name={name} />);
      const svg = container.querySelector("svg");
      expect(svg).toBeTruthy();
      expect(svg?.getAttribute("viewBox")).toBe("0 0 24 24");
      expect(svg?.getAttribute("stroke-width")).toBe("1.5");
      expect(svg?.getAttribute("stroke-linecap")).toBe("round");
      expect(svg?.getAttribute("stroke-linejoin")).toBe("round");
      // Nothing is filled: these are strokes, so a filled path would read as a
      // different weight next to the others.
      expect(svg?.getAttribute("fill")).toBe("none");
      unmount();
    }
  });

  it("is decorative, so it never doubles the label's announcement", () => {
    const { container } = render(<Icon name="search" />);
    const svg = container.querySelector("svg");
    // Every mark sits on a control that already carries its label, so exposing
    // the icon would make a screen reader say the name twice.
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.getAttribute("focusable")).toBe("false");
  });

  it("takes its colour from the text it sits in", () => {
    const { container } = render(<Icon name="alert" />);
    expect(container.querySelector("svg")?.getAttribute("stroke")).toBe("currentColor");
  });

  it("renders at the size it is given", () => {
    const { container } = render(<Icon name="search" size={20} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("20");
    expect(svg?.getAttribute("height")).toBe("20");
  });

  it("draws a mark for every name it exports", () => {
    for (const name of NAMES) {
      const { container, unmount } = render(<Icon name={name} />);
      // An empty <svg> would be an invisible gap where a mark was meant to be.
      expect(container.querySelector("svg")?.childNodes.length).toBeGreaterThan(0);
      unmount();
    }
  });
});
