import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquityChart } from "./EquityChart";
import { ActivityChart } from "./ActivityChart";
import type { BacktestResult, BotEvent } from "../types";

const emptyResult: BacktestResult = {
  total_return: "0.0000",
  trade_count: 0,
  win_rate: "0.0000",
  max_drawdown: "0.0000",
  starting_equity: "100000",
  net_profit: "0.00",
  final_equity: "100000",
  bars_evaluated: 0,
  trades: [],
};

const pricelessEvent: BotEvent = {
  event_type: "SUBMITTED",
  symbol: "BTC/USD",
  side: "buy",
  qty: "0.001",
  price: null,
  order_id: "abc-1",
  reason: null,
  timestamp: "2024-01-01T10:00:00Z",
};

describe("EquityChart", () => {
  it("shows a discreet empty state when the result has no trades", () => {
    const { container } = render(<EquityChart result={emptyResult} />);

    const emptyState = container.querySelector(".empty-state");
    expect(emptyState).not.toBeNull();
    expect(emptyState?.textContent ?? "").toContain("Sin operaciones simuladas");
    // No chart body is rendered in that case.
    expect(container.querySelector(".chart")).toBeNull();
  });

  it("renders without throwing when trades are present", () => {
    const withTrades: BacktestResult = {
      ...emptyResult,
      trade_count: 1,
      final_equity: "100010.00",
      net_profit: "10.00",
      trades: [
        {
          side: "sell",
          qty: "0.001",
          price: "43000.00",
          timestamp: "2024-01-01T01:00:00Z",
          reason: "sma_cross",
          realized_profit: "10.00",
        },
      ],
    };

    const { container } = render(<EquityChart result={withTrades} />);
    expect(container.querySelector(".chart")).not.toBeNull();
    expect(container.querySelector(".empty-state")).toBeNull();
  });
});

describe("ActivityChart", () => {
  it("explains the missing prices when no event carries one", () => {
    render(<ActivityChart events={[pricelessEvent]} />);

    expect(screen.getByText(/eventos de tipo SUBMITTED/i)).toBeInTheDocument();
  });

  it("does not mutate the received events array", () => {
    const events: BotEvent[] = [
      { ...pricelessEvent, price: "65000.00", timestamp: "2024-01-01T10:00:00Z" },
      { ...pricelessEvent, price: "64000.00", timestamp: "2024-01-01T09:00:00Z" },
    ];
    const snapshot = [...events];

    render(<ActivityChart events={events} />);

    expect(events).toEqual(snapshot);
    expect(events[0].timestamp).toBe("2024-01-01T10:00:00Z");
  });
});
