import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PaperTradingBanner } from "./PaperTradingBanner";

describe("PaperTradingBanner", () => {
  it("renders a persistent banner mentioning paper trading (R5.1, R5.2)", () => {
    render(<PaperTradingBanner />);

    const banner = screen.getByTestId("paper-trading-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent?.toLowerCase()).toContain("paper");
  });
});
