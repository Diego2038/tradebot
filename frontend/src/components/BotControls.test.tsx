import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BotControls } from "./BotControls";
import type { BotStatus } from "../types";

const stoppedStatus: BotStatus = {
  state: "stopped",
  mode: "random",
  symbol: "BTC/USD",
};

describe("BotControls", () => {
  it("(a) selecting 'predictive' and clicking Start calls onStart with 'predictive'", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn().mockResolvedValue(undefined);
    const onStop = vi.fn().mockResolvedValue(undefined);

    render(
      <BotControls
        status={stoppedStatus}
        busy={false}
        onStart={onStart}
        onStop={onStop}
      />,
    );

    await user.selectOptions(
      screen.getByLabelText("Modo de operación"),
      "predictive",
    );
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(onStart).toHaveBeenCalledTimes(1);
    expect(onStart).toHaveBeenCalledWith("predictive");
  });

  it("(b) clicking Stop calls onStop", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn().mockResolvedValue(undefined);
    const onStop = vi.fn().mockResolvedValue(undefined);

    render(
      <BotControls
        status={{ ...stoppedStatus, state: "running", mode: "predictive" }}
        busy={false}
        onStart={onStart}
        onStop={onStop}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Stop" }));

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onStart).not.toHaveBeenCalled();
  });

  it("(c) with busy=true the Start button is disabled (R3.8)", () => {
    render(
      <BotControls
        status={stoppedStatus}
        busy={true}
        onStart={vi.fn().mockResolvedValue(undefined)}
        onStop={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("(c2) with stopping=true the Stop button is disabled", () => {
    render(
      <BotControls
        status={{ ...stoppedStatus, state: "running" }}
        busy={false}
        stopping={true}
        onStart={vi.fn().mockResolvedValue(undefined)}
        onStop={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
  });

  it("(c3) a hung Start never blocks Stop: with busy=true and starting=true but stopping=false, Stop stays enabled and clicking it calls onStop", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn().mockResolvedValue(undefined);
    const onStop = vi.fn().mockResolvedValue(undefined);

    render(
      <BotControls
        status={{ ...stoppedStatus, state: "running" }}
        busy={true}
        starting={true}
        stopping={false}
        onStart={onStart}
        onStop={onStop}
      />,
    );

    const stopButton = screen.getByRole("button", { name: "Stop" });
    expect(stopButton).not.toBeDisabled();
    // Start remains disabled while its own operation is in flight.
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();

    await user.click(stopButton);

    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("(d) displays the current status state, mode and symbol (R3.5)", () => {
    render(
      <BotControls
        status={{ state: "running", mode: "predictive", symbol: "BTC/USD" }}
        busy={false}
        onStart={vi.fn().mockResolvedValue(undefined)}
        onStop={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByTestId("bot-state")).toHaveTextContent("running");
    expect(screen.getByTestId("bot-mode")).toHaveTextContent("predictive");
    expect(screen.getByTestId("bot-symbol")).toHaveTextContent("BTC/USD");
  });

  it("(e) renders the error message when error is present (R3.6, R3.7)", () => {
    render(
      <BotControls
        status={stoppedStatus}
        busy={false}
        onStart={vi.fn().mockResolvedValue(undefined)}
        onStop={vi.fn().mockResolvedValue(undefined)}
        error="no hay credenciales configuradas"
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("no hay credenciales configuradas");
  });
});
