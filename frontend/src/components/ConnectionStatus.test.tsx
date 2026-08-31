import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConnectionStatus } from "./ConnectionStatus";
import type { ConnectionStatus as ConnectionStatusValue } from "../types";

describe("ConnectionStatus", () => {
  const cases: Array<[ConnectionStatusValue, string]> = [
    ["connected", "Conectado"],
    ["connecting", "Conectando…"],
    ["disconnected", "Desconectado"],
  ];

  it.each(cases)(
    "shows the corresponding text for status %s (R4.5)",
    (status, label) => {
      const { unmount } = render(<ConnectionStatus status={status} />);

      const el = screen.getByTestId("connection-status");
      expect(el).toHaveTextContent(label);
      expect(el).toHaveAttribute("data-status", status);

      unmount();
    },
  );

  it("reflects the status via rerender (R4.5)", () => {
    const { rerender } = render(<ConnectionStatus status="connecting" />);
    expect(screen.getByTestId("connection-status")).toHaveTextContent(
      "Conectando…",
    );

    rerender(<ConnectionStatus status="connected" />);
    expect(screen.getByTestId("connection-status")).toHaveTextContent(
      "Conectado",
    );

    rerender(<ConnectionStatus status="disconnected" />);
    expect(screen.getByTestId("connection-status")).toHaveTextContent(
      "Desconectado",
    );
  });
});
