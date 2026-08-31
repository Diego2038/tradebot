import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Mode } from "../types";

describe("test environment", () => {
  it("runs vitest with globals and imports shared types", () => {
    const mode: Mode = "random";
    expect(mode).toBe("random");
    expect(true).toBe(true);
  });

  it("renders into jsdom via @testing-library/react", () => {
    render(<div>tradebot smoke</div>);
    expect(screen.getByText("tradebot smoke")).toBeInTheDocument();
  });
});
