import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InstanceState, StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("maps each status to its TUI glyph + color", () => {
    const cases: [string, string, string][] = [
      ["running", "▸", "text-brand-amber"],
      ["success", "✓", "text-brand-sage"],
      ["error", "✗", "text-brand-rust"],
      ["awaiting_approval", "◷", "text-brand-lilac"],
      ["queued", "·", "text-brand-stone"],
    ];
    for (const [status, glyph, color] of cases) {
      const { container } = render(<StatusBadge status={status} />);
      expect(container.textContent).toContain(glyph);
      expect(container.textContent).toContain(status);
      expect(container.querySelector("span")?.className).toContain(color);
    }
  });

  it("falls back gracefully for an unknown status", () => {
    const { container } = render(<StatusBadge status="weird" />);
    expect(container.textContent).toContain("weird");
  });

  it("renders instance active/paused states", () => {
    expect(render(<InstanceState paused={false} />).container.textContent).toContain("active");
    expect(render(<InstanceState paused={true} />).container.textContent).toContain("paused");
  });
});
