import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BacktestPanel } from "./BacktestPanel";
import type { BacktestResult } from "../types";

const sampleResult: BacktestResult = {
  total_return: "0.1234",
  trade_count: 2,
  win_rate: "0.5000",
  max_drawdown: "0.0500",
  starting_equity: "100000",
  net_profit: "1234.00",
  final_equity: "101234.00",
  bars_evaluated: 1440,
  trades: [
    {
      side: "buy",
      qty: "0.01",
      price: "42000.00",
      timestamp: "2024-01-01T00:00:00Z",
      reason: "sma_cross",
      realized_profit: null,
    },
    {
      side: "sell",
      qty: "0.01",
      price: "43000.00",
      timestamp: "2024-01-01T01:00:00Z",
      reason: "sma_cross",
      realized_profit: "10.00",
    },
  ],
};

describe("BacktestPanel", () => {
  it("(a) submitting the form calls onRun with the selected mode and timeframe", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn().mockResolvedValue(undefined);

    render(
      <BacktestPanel onRun={onRun} result={null} busy={false} />,
    );

    await user.selectOptions(
      screen.getByLabelText("Modo de backtest"),
      "predictive",
    );
    await user.selectOptions(screen.getByLabelText("Timeframe"), "1Hour");
    await user.click(
      screen.getByRole("button", { name: "Ejecutar backtest" }),
    );

    expect(onRun).toHaveBeenCalledTimes(1);
    const req = onRun.mock.calls[0][0];
    expect(req.mode).toBe("predictive");
    expect(req.timeframe).toBe("1Hour");
    expect(req.symbol).toBe("BTC/USD");
  });

  it("(a2) a typed position size is forwarded as a numeric qty", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn().mockResolvedValue(undefined);

    render(<BacktestPanel onRun={onRun} result={null} busy={false} />);

    await user.type(screen.getByLabelText("Tamaño de posición (BTC)"), "1");
    await user.click(screen.getByRole("button", { name: "Ejecutar backtest" }));

    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun.mock.calls[0][0].qty).toBe(1);
  });

  it("(a3) leaving the position size empty sends qty as null (engine default)", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn().mockResolvedValue(undefined);

    render(<BacktestPanel onRun={onRun} result={null} busy={false} />);

    await user.click(screen.getByRole("button", { name: "Ejecutar backtest" }));

    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun.mock.calls[0][0].qty).toBeNull();
  });

  it("(b) with busy=true the 'Ejecutar backtest' button is disabled", () => {
    render(
      <BacktestPanel
        onRun={vi.fn().mockResolvedValue(undefined)}
        result={null}
        busy={true}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Ejecutar backtest" }),
    ).toBeDisabled();
  });

  it("(c) when a result is passed, metrics and a trade row are rendered", () => {
    render(
      <BacktestPanel
        onRun={vi.fn().mockResolvedValue(undefined)}
        result={sampleResult}
        busy={false}
      />,
    );

    expect(screen.getByTestId("bt-total-return")).toHaveTextContent("0.1234");
    expect(screen.getByTestId("bt-trade-count")).toHaveTextContent("2");
    expect(screen.getByTestId("bt-win-rate")).toHaveTextContent("0.5000");
    expect(screen.getByTestId("bt-max-drawdown")).toHaveTextContent("0.0500");
    expect(screen.getByTestId("bt-bars-evaluated")).toHaveTextContent("1440");

    // Absolute figures, so the result is readable without decoding ratios.
    expect(screen.getByTestId("bt-net-profit")).toHaveTextContent("1234.00");
    expect(screen.getByTestId("bt-final-equity")).toHaveTextContent("101234.00");
    expect(screen.getByTestId("bt-starting-equity")).toHaveTextContent("100000");

    expect(screen.getByTestId("bt-trades-table")).toBeInTheDocument();
    const rows = screen.getAllByTestId("bt-trade-row");
    expect(rows).toHaveLength(2);
    // First trade has null realized_profit -> rendered as a dash.
    expect(screen.getAllByTestId("bt-trade-pnl")[0]).toHaveTextContent("—");
    expect(screen.getAllByTestId("bt-trade-pnl")[1]).toHaveTextContent("10.00");
  });

  it("(d) when error is present, an alert is shown", () => {
    render(
      <BacktestPanel
        onRun={vi.fn().mockResolvedValue(undefined)}
        result={null}
        busy={false}
        error="Rango de fechas inválido."
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Rango de fechas inválido.");
  });
});
