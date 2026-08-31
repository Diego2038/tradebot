import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { Dashboard } from "./Dashboard";
import type { BotEvent } from "../types";

const filled: BotEvent = {
  event_type: "FILLED",
  symbol: "BTC/USD",
  side: "buy",
  qty: "0.5",
  price: "65000.00",
  order_id: "abc-123",
  reason: null,
  timestamp: "2024-01-01T10:00:00Z",
};

const submitted: BotEvent = {
  event_type: "SUBMITTED",
  symbol: "BTC/USD",
  side: "sell",
  qty: "0.25",
  price: "64000.00",
  order_id: "abc-124",
  reason: null,
  timestamp: "2024-01-01T09:00:00Z",
};

describe("Dashboard", () => {
  it("renders a row containing all required fields for a BotEvent (R4.2)", () => {
    render(<Dashboard events={[filled]} />);

    const rows = screen.getAllByTestId("event-row");
    expect(rows).toHaveLength(1);

    const row = within(rows[0]);
    expect(row.getByTestId("event-type")).toHaveTextContent("FILLED");
    expect(row.getByTestId("event-symbol")).toHaveTextContent("BTC/USD");
    expect(row.getByTestId("event-side")).toHaveTextContent("buy");
    expect(row.getByTestId("event-qty")).toHaveTextContent("0.5");
    expect(row.getByTestId("event-price")).toHaveTextContent("65000.00");
    expect(row.getByTestId("event-timestamp")).toHaveTextContent(
      "2024-01-01T10:00:00Z",
    );
  });

  it("renders events in the received order, most-recent-first (R4.3)", () => {
    // Array is already ordered [mostRecent, lessRecent]; Dashboard must not reorder.
    render(<Dashboard events={[filled, submitted]} />);

    const rows = screen.getAllByTestId("event-row");
    expect(rows).toHaveLength(2);

    // First row = most recent event.
    expect(within(rows[0]).getByTestId("event-type")).toHaveTextContent(
      "FILLED",
    );
    expect(within(rows[0]).getByTestId("event-timestamp")).toHaveTextContent(
      "2024-01-01T10:00:00Z",
    );
    // Second row = less recent event.
    expect(within(rows[1]).getByTestId("event-type")).toHaveTextContent(
      "SUBMITTED",
    );
  });

  it("renders nullable fields with a dash placeholder", () => {
    const nullish: BotEvent = {
      event_type: "ERROR",
      symbol: "BTC/USD",
      side: null,
      qty: null,
      price: null,
      order_id: null,
      reason: "boom",
      timestamp: "2024-01-01T11:00:00Z",
    };

    render(<Dashboard events={[nullish]} />);

    const row = within(screen.getByTestId("event-row"));
    expect(row.getByTestId("event-side")).toHaveTextContent("—");
    expect(row.getByTestId("event-qty")).toHaveTextContent("—");
    expect(row.getByTestId("event-price")).toHaveTextContent("—");
  });

  it("shows a discreet empty state when there are no events", () => {
    render(<Dashboard events={[]} />);

    expect(screen.queryAllByTestId("event-row")).toHaveLength(0);
    expect(screen.getByTestId("dashboard-empty")).toHaveTextContent(
      "Sin eventos todavía",
    );
  });
});
