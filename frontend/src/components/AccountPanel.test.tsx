import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AccountPanel } from "./AccountPanel";
import type { AccountStatus } from "../types";

const account: AccountStatus = {
  cash: "10000.00",
  buying_power: "20000.00",
  status: "ACTIVE",
  mode: "paper",
};

describe("AccountPanel", () => {
  it("shows cash, buying_power and status when account is present (R2.2)", () => {
    render(<AccountPanel account={account} />);

    expect(screen.getByTestId("account-cash")).toHaveTextContent("10000.00");
    expect(screen.getByTestId("account-buying-power")).toHaveTextContent(
      "20000.00",
    );
    expect(screen.getByTestId("account-status")).toHaveTextContent("ACTIVE");
  });

  it("shows the error when account is null and error is present (R2.3)", () => {
    render(
      <AccountPanel account={null} error="No se pudo cargar la cuenta" />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "No se pudo cargar la cuenta",
    );
  });

  it("shows a discreet empty state when account is null and there is no error", () => {
    render(<AccountPanel account={null} />);

    expect(screen.getByTestId("account-empty")).toHaveTextContent(
      "Sin datos de cuenta",
    );
  });
});
